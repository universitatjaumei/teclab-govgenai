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

#: Lo que se puede pedir: **sólo `https`**, que es lo que dice la #118. Un documento en claro se
#: puede alterar por el camino, y lo que entra aquí es la entrada de una función que alguien
#: firmó como declaración responsable. `file://` leería el disco del servidor (PR #210).
ESQUEMAS = ("https",)

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

    Las dos comprobaciones del destino van **en cada petición, redirecciones incluidas**, por
    los hooks de `httpx` (`hooks_de_la_descarga`): la lista blanca dice «de este servidor no se
    pide» y la de I15, «esta dirección no es pública». Un origen declarado que redirige a
    `127.0.0.1` lo para la segunda; uno que redirige a otro dominio, la primera.
    """
    import httpx

    from server.app.core.red_publica import transporte_a_la_direccion_validada

    comprobar_contra_los_origenes(url, origenes=origenes)

    async with httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=True,
        transport=transporte_a_la_direccion_validada(),
        event_hooks={"request": hooks_de_la_descarga(origenes=origenes)},
    ) as cliente:
        async with cliente.stream("GET", url) as respuesta:
            respuesta.raise_for_status()
            contenido = await leer_con_tope(respuesta, maximo_bytes=maximo_bytes)
            final = str(respuesta.url)

    nombre = (urlsplit(final).path.rsplit("/", 1)[-1] or "descarga").strip()
    return contenido, nombre


def hooks_de_la_descarga(*, origenes: list[str], resolver=None) -> list:
    """Los hooks de petición: **la lista blanca primero**, la red pública después.

    `httpx` los dispara en la petición inicial **y en cada redirección**, y ése es el sitio
    donde tiene que estar la lista (PR #210). Comprobar sólo la primera URL y la última dejaba
    pasar A (declarado) → B (no declarado) → A: el servidor hablaba con B antes de que nada lo
    parara, y la garantía de AUT.8 es justo que eso no pasa.

    La lista va primero porque no necesita resolver nada: un salto no declarado ni siquiera
    llega a la consulta de DNS.
    """
    from server.app.core.red_publica import hook_de_destino_publico

    async def comprobar_la_lista(request) -> None:
        comprobar_contra_los_origenes(str(request.url), origenes=origenes)

    return [comprobar_la_lista, hook_de_destino_publico(resolver=resolver)]


async def leer_con_tope(respuesta, *, maximo_bytes: int) -> bytes:
    """Lee el cuerpo a trozos y **deja de leer** en cuanto se pasa del tope.

    Comprobarlo sobre `respuesta.content` llegaba tarde: para entonces la respuesta entera ya
    estaba en memoria, y un servidor declarado podía hacer que el proceso reservara lo que
    quisiera antes de que el tope dijera nada (PR #210).
    """
    trozos: list[bytes] = []
    total = 0
    async for trozo in respuesta.aiter_bytes():
        total += len(trozo)
        if total > maximo_bytes:
            raise OrigenNoDeclarado(
                f"el documento pasa de {maximo_bytes} bytes, que es el tope; se deja de leer ahí."
            )
        trozos.append(trozo)
    return b"".join(trozos)
