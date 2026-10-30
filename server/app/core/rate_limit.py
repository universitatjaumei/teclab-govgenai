"""Limitación de peticiones por ventana (SEC.4, Parte 1). Deploy: shared.

Dos cosas distintas que la gente confunde: **esto cuenta peticiones**, las cuotas de
`quotas.py` cuentan tokens. El limitador frena la fuerza bruta contra el login y el martilleo
del chat; la cuota controla el gasto. Una petición puede costar mil veces más que otra, así
que ninguna de las dos sustituye a la otra.

**Ventana deslizante en memoria del proceso, y no Redis.** Es una decisión con su límite
escrito: con varias instancias detrás de un balanceador, cada una cuenta lo suyo, así que el
límite efectivo se multiplica por el número de instancias. Para lo que este limitador
defiende —fuerza bruta contra un login que ya exige contraseña desde SEC.1— eso sigue siendo
tres órdenes de magnitud menos que sin límite, y no arrastra una dependencia de
infraestructura al despliegue edge, donde a menudo hay **una** instancia y no hay Redis.
Cuando el despliegue en Cloud Run escale de verdad, el reemplazo es este mismo módulo con
otro almacén detrás: la superficie es `permitir()` y nada más.

La memoria está acotada: las claves caducan solas al quedarse sin marcas dentro de la ventana
y se recogen al consultarlas.
"""
from __future__ import annotations

import ipaddress
import os
import time
from collections import defaultdict, deque
from threading import Lock

from fastapi import HTTPException, Request, status

# Por defecto conservador en el login —fuerza bruta— y holgado en el chat, donde una persona
# haciendo preguntas seguidas es un uso normal y no un ataque.
LIMITE_LOGIN_POR_DEFECTO = "10/minute"
LIMITE_CHAT_POR_DEFECTO = "30/minute"

_UNIDADES = {"second": 1, "minute": 60, "hour": 3600, "day": 86_400}


def _parsear(regla: str) -> tuple[int, int]:
    """`'10/minute'` → `(10, 60)`. Una regla ilegible no se interpreta: se levanta."""
    try:
        veces, unidad = regla.split("/")
        return int(veces), _UNIDADES[unidad.strip().lower()]
    except (ValueError, KeyError) as fallo:
        raise RuntimeError(
            f"Regla de límite inválida: {regla!r}. Formato: '<n>/<second|minute|hour|day>'"
        ) from fallo


class LimitadorEnMemoria:
    """Ventana deslizante por clave. Seguro entre hilos; no entre procesos (ver módulo)."""

    def __init__(self) -> None:
        self._marcas: dict[str, deque[float]] = defaultdict(deque)
        self._cerrojo = Lock()

    def permitir(self, clave: str, regla: str, ahora: float | None = None) -> tuple[bool, int]:
        """`(permitida, segundos_hasta_que_se_libere)`."""
        veces, ventana = _parsear(regla)
        instante = ahora if ahora is not None else time.monotonic()

        with self._cerrojo:
            marcas = self._marcas[clave]
            while marcas and instante - marcas[0] >= ventana:
                marcas.popleft()

            if len(marcas) >= veces:
                return False, max(1, int(ventana - (instante - marcas[0])))

            marcas.append(instante)
            if not marcas:
                del self._marcas[clave]
            return True, 0

    def reiniciar(self) -> None:
        """Solo para tests: un limitador con memoria entre tests da falsos rojos."""
        with self._cerrojo:
            self._marcas.clear()


limitador = LimitadorEnMemoria()


def _es_proxy_de_confianza(ip: str) -> bool:
    """¿Está `ip` en `FORWARDED_ALLOW_IPS`? Redes o direcciones separadas por comas; `*` es todas."""
    declarado = os.getenv("FORWARDED_ALLOW_IPS", "").strip()
    if not declarado or declarado == "*":
        return True
    try:
        direccion = ipaddress.ip_address(ip)
    except ValueError:
        return False
    for trozo in declarado.split(","):
        trozo = trozo.strip()
        if not trozo:
            continue
        try:
            if direccion in ipaddress.ip_network(trozo, strict=False):
                return True
        except ValueError:
            continue
    return False


def ip_de(request: Request) -> str:
    """La IP del cliente, contando desde el proxy y no desde el cliente (SEC.8.4).

    `X-Forwarded-For` se lee de izquierda a derecha: el primer valor es el que dice el
    cliente y **cada proxy añade el suyo al final**. Tomar el primero, que es lo que se
    hacía, significa tomar el valor que el atacante escribe: cambiándolo en cada petición
    se obtiene un cubo distinto y el límite de fuerza bruta del login deja de aplicarse.

    Se cuenta por tanto desde la derecha, tantos saltos como proxies de confianza haya
    declarados en `TRUSTED_PROXY_HOPS` (1 detrás del proxy inverso que termina TLS, o de un
    balanceador). Con 0
    —expuesto directamente— la cabecera se ignora entera, porque ahí no la pone nadie de
    fiar.
    """
    try:
        saltos = int(os.getenv("TRUSTED_PROXY_HOPS", "0"))
    except ValueError:
        saltos = 0

    socket = getattr(getattr(request, "client", None), "host", None) or "desconocida"
    if saltos <= 0:
        return socket
    # La cabecera sólo vale si la manda el proxy. Desde la red del sandbox se llega a la API sin
    # pasar por él, y ahí la escribe un guion: cambiándola en cada petición el límite del login
    # dejaba de aplicarse. Quién es el proxy lo dice `FORWARDED_ALLOW_IPS`, la misma lista con la
    # que uvicorn decide si reescribe la IP del cliente. Sin la variable, como hasta ahora.
    if not _es_proxy_de_confianza(socket):
        return socket

    reenviada = request.headers.get("X-Forwarded-For")
    if not reenviada:
        return socket

    cadena = [trozo.strip() for trozo in reenviada.split(",") if trozo.strip()]
    if not cadena:
        return socket
    # El último valor lo pone el proxy más cercano; con N proxies de confianza, la IP real
    # del cliente es la que está N posiciones desde el final.
    indice = max(len(cadena) - saltos, 0)
    return cadena[indice]


def _regla(variable: str, por_defecto: str) -> str:
    return os.getenv(variable, por_defecto)


def limitar(*, ambito: str, clave: str, regla: str) -> None:
    """429 si esta clave ha gastado su cupo en la ventana."""
    permitida, espera = limitador.permitir(f"{ambito}:{clave}", regla)
    if not permitida:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"code": "RATE_LIMITED", "scope": ambito, "limit": regla},
            headers={"Retry-After": str(espera)},
        )


def limitar_login(request: Request) -> None:
    """Por IP: en el login todavía no se sabe quién llama, y esa es la gracia del ataque."""
    limitar(
        ambito="login",
        clave=ip_de(request),
        regla=_regla("RATE_LIMIT_LOGIN", LIMITE_LOGIN_POR_DEFECTO),
    )


def limitar_valoracion(request: Request, *, chatbot_id) -> None:
    """Por IP, con la regla del chat: la valoración anónima del widget (#340).

    Ámbito propio y no el del chat: valorar no tiene que gastar el cupo de preguntar.
    """
    limitar(
        ambito=f"valoracion:{chatbot_id}",
        clave=ip_de(request),
        regla=_regla("RATE_LIMIT_CHAT", LIMITE_CHAT_POR_DEFECTO),
    )


def limitar_chat(request: Request, *, actor_id: str | None, chatbot_id) -> None:
    """Por actor efectivo cuando hay identidad y por IP cuando no.

    Por **actor** y no por credencial: si se contara por PAT, un cliente de confianza que
    atiende a cien personas se llevaría el límite de una sola. Es la misma razón por la que
    la cuota se le carga al actor y no al dueño del token.
    """
    limitar(
        ambito=f"chat:{chatbot_id}",
        clave=actor_id or ip_de(request),
        regla=_regla("RATE_LIMIT_CHAT", LIMITE_CHAT_POR_DEFECTO),
    )
