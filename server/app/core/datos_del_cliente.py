"""Lo que el cloud pregunta y pide al edge sobre los datos del cliente (#298).

La configuración —chatbots, organizaciones— es cloud; el corpus, los agentes de unidad, los
sitios, el léxico y los informes son del cliente, y por tanto edge. En tres cosas el cloud no
puede dejar de contar con ellos: el tamaño del corpus al pasar un chatbot a `MD_LONG_CONTEXT`, si
una organización todavía tiene datos antes de borrarla, y la purga del corpus al borrar. Las pide
por este protocolo, inyectado con `Depends(get_datos_del_cliente)`, y así ningún router cloud
importa modelos operacionales: lo vigila `test_la_ingesta_es_edge.py`.

Hoy hay una implementación, la local (`DatosDelClienteLocal`), que comparte la sesión del router:
la purga y el borrado de la configuración siguen siendo **la misma transacción**, que es lo que
exigió PIL.2. La remota, la de un despliegue partido, llegará con `RemoteConfigProvider`; no se
escribe antes porque no hay ningún edge que la conteste.
"""
from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class CorpusRetirado:
    """Lo que se llevó por delante, para poder decirlo en voz alta."""

    documentos: int
    fragmentos: int
    trabajos: int = 0


class DatosDelCliente(Protocol):
    async def tokens_del_corpus(self, chatbot_id: uuid.UUID) -> int:
        """Los tokens que suma el corpus del chatbot."""
        ...

    async def lo_que_impide_borrar(self, organizacion_id: uuid.UUID) -> dict[str, int]:
        """Cuánto le queda a la organización de cada cosa que impide borrarla; sólo lo que no es cero."""
        ...

    async def purgar_corpus(self, chatbot_ids: Sequence[uuid.UUID]) -> CorpusRetirado:
        """Retira el corpus de esos chatbots. **No confirma**: el commit es del que borra."""
        ...

    async def borrar_fuentes(self, chatbot_ids: Sequence[uuid.UUID]) -> None:
        """Los ficheros fuente de esos chatbots. **Después** del commit del borrado, y sin lanzar."""
        ...
