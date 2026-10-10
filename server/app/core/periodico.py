"""Una pasada que se repite para siempre, y que no se para porque falle una (#258).

Es la forma de `bucle_de_caducados` (AUT.7) y `bucle_de_temporales` (#254), sacada aquí para los
barridos nuevos, que no tienen otro sitio natural: cruzan módulos —chatbots y propuestas de script—
y `core/` no puede importar de ellos (AIS.3). La pasada la arma quien la lanza, el arranque.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

_log = logging.getLogger(__name__)

#: Cada cuánto, por defecto: la cadencia del resto de barridos de retención.
SEIS_HORAS = 6 * 60 * 60


async def cada(
    pasada: Callable[[], Awaitable[object]], *, descripcion: str, segundos: int = SEIS_HORAS
) -> None:
    """Ejecuta `pasada` ahora y luego cada `segundos`. **Un fallo se registra y no para el bucle.**"""
    while True:
        try:
            await pasada()
        except Exception:  # noqa: BLE001 — se registra y se reintenta en la siguiente pasada
            _log.exception("%s falló; se reintenta luego", descripcion)
        await asyncio.sleep(segundos)
