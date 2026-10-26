"""Fuente de corpus sobre el servicio de publicación (SYNC.1). Deploy: edge.

Segunda implementación de `CorpusSource` (ING.0.5), junto a la carpeta local. **Todo lo que
es reconciliación —emparejamiento, deltas, poda, salvaguarda de proporción, findings y el
registro del job— vive en el reconciliador y no se toca aquí.** Este módulo solo traduce dos
datasets a entradas y cuerpos, y un guardarraíl de texto en los tests falla si este fichero
llega a nombrar el modelo ORM de documentos: duplicar el emparejamiento no lo detectaría
ningún test funcional, porque los dos caminos darían el mismo resultado hasta el día en que
dejaran de darlo.

**`is_census()` es la pieza delicada.** Solo con el índice completo se puede afirmar que una
norma ausente ha sido retirada. Si la instalación usa el dataset de «modificadas en los
últimos N días» —la variante prevista si la tool no admite parámetros—, esto es `False` y el
reconciliador no poda. Es la respuesta correcta: un delta no distingue «retirada» de «no
tocada», y confundirlas retira normas vigentes.
"""
from __future__ import annotations

from typing import Any

from server.app.modules.agents_hub.ingestion.corpus.frontmatter import parse_frontmatter
from server.app.modules.agents_hub.ingestion.corpus.manifest import (
    CorpusDocumentEntry,
    CorpusValidationError,
    entry_from_frontmatter,
)
from server.app.modules.agents_hub.ingestion.corpus.publication_client import (
    PublicationMcpClient,
    PublicationSyncError,
)

# Claves del registro del índice que son transporte y no metadatos del documento.
_RESERVADAS = ("relative_path", "content_hash", "metadades", "metadata", "markdown")


class PublicationMcpSource:
    """Índice + contenido del servicio de publicación, como `CorpusSource`."""

    def __init__(
        self,
        client: PublicationMcpClient,
        index_dataset: str,
        content_dataset: str,
        is_census_declared: bool = True,
    ) -> None:
        self._client = client
        self._index_dataset = index_dataset
        self._content_dataset = content_dataset
        self._is_census = is_census_declared
        # El contenido se baja una sola vez y solo si alguien pide un cuerpo. Con el hash
        # del índice, una pasada sin cambios no llega a pedirlo nunca.
        self._cuerpos: dict[str, str] | None = None

    def is_census(self) -> bool:
        return self._is_census

    async def list_entries(self) -> list[CorpusDocumentEntry]:
        registros = await self._client.execute_dataset(self._index_dataset)

        entradas: list[CorpusDocumentEntry] = []
        errores: list[str] = []
        for posicion, registro in enumerate(registros):
            id_publicacio = str(registro.get("id_publicacio") or "").strip()
            ruta = str(
                registro.get("relative_path") or (f"{id_publicacio}.md" if id_publicacio else "")
            )
            if not ruta:
                errores.append(
                    f"  registro {posicion}: sin id_publicacio ni relative_path, no hay "
                    "forma de emparejarlo"
                )
                continue

            metadatos = self._metadatos(registro)
            try:
                entrada = entry_from_frontmatter(
                    metadatos,
                    relative_path=ruta,
                    source_url=str(metadatos.get("url_oficial") or ruta),
                )
            except Exception as exc:  # noqa: BLE001 — se acumulan todos los errores del paquete y se rechaza entero
                errores.append(f"  {ruta}: {exc}")
                continue

            if hash_declarado := registro.get("content_hash"):
                entrada = entrada.model_copy(
                    update={"content_hash": str(hash_declarado)}
                )
            entradas.append(entrada)

        if errores:
            # Mismo criterio que la carpeta local: el paquete se acepta entero o no se
            # acepta. Un censo a medias que se diera por bueno despublicaría lo que falta.
            raise CorpusValidationError(
                "El indice de publicacion no cumple el contrato y no se sincroniza nada "
                f"({len(errores)} de {len(registros)} registros):\n" + "\n".join(errores)
            )
        return entradas

    @staticmethod
    def _metadatos(registro: dict[str, Any]) -> dict[str, Any]:
        """El bloque de metadatos del registro, o el registro entero sin las de transporte.

        Las dos formas se aceptan porque el dataset todavía no existe y no conviene atarse a
        una de ellas: si viene anidado en `metadades`, se usa; si el registro es plano, se
        usa el registro menos las claves de transporte.
        """
        anidado = registro.get("metadades") or registro.get("metadata")
        if isinstance(anidado, dict):
            return dict(anidado)
        return {k: v for k, v in registro.items() if k not in _RESERVADAS}

    async def read_body(self, entry: CorpusDocumentEntry) -> str:
        cuerpos = await self._cargar_contenido()
        clave = entry.id_publicacio or entry.relative_path
        if clave not in cuerpos:
            raise PublicationSyncError(
                f"El dataset de contenido no trae '{clave}', que el indice si declara. "
                "Los dos datasets estan desincronizados; no se ingiere a medias."
            )
        return cuerpos[clave]

    async def _cargar_contenido(self) -> dict[str, str]:
        if self._cuerpos is not None:
            return self._cuerpos

        registros = await self._client.execute_dataset(self._content_dataset)
        cuerpos: dict[str, str] = {}
        for registro in registros:
            clave = str(
                registro.get("id_publicacio") or registro.get("relative_path") or ""
            ).strip()
            if not clave:
                continue
            markdown = str(registro.get("markdown") or registro.get("content") or "")
            # El cuerpo se entrega sin front-matter, igual que la carpeta local: es lo que
            # se hashea y lo que se trocea. Si el registro no lo trae, `parse_frontmatter`
            # devuelve el texto tal cual.
            _, cuerpo = parse_frontmatter(markdown)
            cuerpos[clave] = cuerpo

        self._cuerpos = cuerpos
        return cuerpos
