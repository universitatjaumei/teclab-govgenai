"""Servicios de embeddings vectoriales para búsqueda semántica.

MOD.1: los dos servicios declaran `model_name` y `dimensions`. No es decorado — es lo que
permite grabar la procedencia con cada vector y que la guarda de `recalculate-corpus` pueda
saltar. Hasta MOD.1 esa guarda leía dos atributos que no existían, caía a los defaults y
comparaba `1024 != 1024`: estaba escrita y no podía dispararse nunca.

**La plataforma trabaja a 1024 dimensiones.** Es el único valor que sirve a la vez a BGE-M3
en edge (nativo) y a Google en cloud (rango flexible 128-3072), así que cambiar de proveedor
no obliga a migrar la columna `Vector(1024)` ni a reconstruir el índice HNSW. Detalle y
verificación en `docs/DECISION_MODELOS_EMBEDDING_RERANKER.md`.
"""

import asyncio
import inspect
import math
import os

DIMENSION_PLATAFORMA = 1024

# PIL.1 — el propósito del embedding, decidido el 2026-08-15.
#
# `gemini-embedding-001` produce un vector distinto según para qué se vaya a usar el texto, y
# usar el par correcto mejora la recuperación de forma medible: sin él, el vector de una
# pregunta y el de un artículo tienen que parecerse por casualidad, y en un corpus normativo
# —donde el ciudadano no usa las palabras de la norma— es justo donde más se pierde.
#
# **Se adopta en los dos lados o en ninguno.** Indexar con `RETRIEVAL_DOCUMENT` y preguntar
# sin declarar nada compara dos espacios distintos, y eso no da error: da respuestas peores.
# Por eso el propósito viaja con la procedencia del vector (`embedding_task_type`) y
# `assert_embedding_space_matches` lo compara junto al modelo y la dimensión.
PURPOSE_DOCUMENT = "RETRIEVAL_DOCUMENT"
PURPOSE_QUERY = "RETRIEVAL_QUERY"

# Tope de instancias por petición, MEDIDO contra la API real el 2026-08-15 (probado 1, 2, 16,
# 64 y 250 con el proyecto `uji-teclab`). Es constante del módulo y no parámetro de negocio:
# lo fija la API, no el caso de uso.
LOTE_MAXIMO_API = 250

# Región por defecto de Vertex. Madrid: el texto normativo no sale de España, que es lo que
# sostiene la frontera edge-cloud ante protección de datos. Verificada sirviendo
# `gemini-embedding-001` a 1024 dimensiones. No ata a las demás: el modelo de chat y el
# Ranking API de RAG.6b eligen la suya.
REGION_VERTEX_POR_DEFECTO = "europe-southwest1"

# D.4.0: la pila de modelos locales (`torch`, `transformers`, `sentence-transformers`) es un
# extra de instalación. Un `ModuleNotFoundError: torch` en mitad de una ingesta no le dice a
# nadie qué instalar, así que se traduce a esto.
FALTA_EL_EXTRA = (
    "Este despliegue está configurado para usar {para}, pero la pila de modelos locales no "
    "está instalada. Instálala con:\n"
    "    uv sync --extra local-models\n"
    "O cambia la configuración para usar el proveedor por API, que es lo previsto en el "
    "despliegue estándar (ver docs/DECISION_MODELOS_EMBEDDING_RERANKER.md)."
)


def _l2_normalize(vector: list[float]) -> list[float]:
    norma = math.sqrt(sum(v * v for v in vector))
    return [v / norma for v in vector] if norma else vector


class LocalEmbeddingService:
    """Genera embeddings con BAAI/bge-m3 en local (CPU o GPU).

    El modelo se descarga desde HuggingFace Hub en la primera llamada (~1.1 GB).
    Las llamadas sucesivas reutilizan los pesos en memoria (singleton).
    Dimensión de salida: 1024 (dense, L2-normalizado por el propio modelo).
    """

    MODEL_NAME = "BAAI/bge-m3"

    # BGE-M3 no tiene tipos de tarea, y no se le va a inventar uno: `None` es la declaración
    # honesta de que este espacio vectorial no distingue documento de consulta.
    embedding_task_type: str | None = None

    def __init__(self) -> None:
        self._model = None

    @property
    def model_name(self) -> str:
        return self.MODEL_NAME

    @property
    def dimensions(self) -> int:
        return DIMENSION_PLATAFORMA

    def _get_model(self):
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as falta:
                raise RuntimeError(FALTA_EL_EXTRA.format(para="embeddings locales")) from falta
            self._model = SentenceTransformer(self.MODEL_NAME)
        return self._model

    async def embed(self, text: str, purpose: str = PURPOSE_QUERY) -> list[float]:  # noqa: ARG002 — el modelo local no distingue el propósito (ver docstring)
        """`purpose` se acepta y se ignora: el modelo local no lo distingue.

        Se acepta —en vez de omitirlo— para que quien llame no tenga que preguntar qué
        adaptador tiene delante. Ignorarlo aquí es correcto; omitirlo obligaría a cada
        llamante a ramificar, y esa rama es donde se cuela el error.
        """
        def _encode(t: str) -> list[float]:
            return self._get_model().encode(t, normalize_embeddings=True).tolist()

        return await asyncio.to_thread(_encode, text)

    async def embed_batch(
        self, texts: list[str], purpose: str = PURPOSE_DOCUMENT  # noqa: ARG002 — el modelo local no distingue el propósito (ver docstring)
    ) -> list[list[float]]:
        """Un `encode` para toda la lista (RAG.7).

        `SentenceTransformer.encode` acepta lista y la procesa por lotes internamente, así
        que una llamada por documento en vez de una por fragmento aprovecha la vectorización
        en vez de pagar el arranque de la inferencia N veces.
        """
        def _encode(ts: list[str]) -> list[list[float]]:
            return self._get_model().encode(ts, normalize_embeddings=True).tolist()

        return await asyncio.to_thread(_encode, texts)


class _AdaptadorPorAPI:
    """Lo común a los dos proveedores por API: normalizar, trocear y elegir el propósito.

    **Normaliza siempre**, y esa es la decisión que no se puede quitar. No es una precaución
    leída en la documentación: el 2026-08-15 se midió contra la API real y el vector de 1024
    dimensiones llega con **norma L2 = 0,6225**. Mezclar vectores normalizados y sin
    normalizar en la misma columna rompe cualquier semántica de score absoluto —el umbral de
    RAG.5— y no da error: da un retriever que «funciona regular».

    **El propósito decide el método**, no un parámetro suelto: `aembed_documents` manda
    `RETRIEVAL_DOCUMENT` y `aembed_query` manda `RETRIEVAL_QUERY`, que es exactamente la
    asimetría que se quiere. Enviar el tipo a mano duplicaría lo que la librería ya hace.
    """

    # Lo que este adaptador usa AL INDEXAR, y lo que por tanto se graba en la procedencia
    # del vector. La consulta usa el otro, y esa asimetría es el objetivo.
    embedding_task_type: str | None = PURPOSE_DOCUMENT

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimensions(self) -> int:
        return self._dimensions

    async def embed(self, text: str, purpose: str = PURPOSE_QUERY) -> list[float]:
        if purpose == PURPOSE_DOCUMENT:
            vectores = await self._client.aembed_documents([text])
            return _l2_normalize(vectores[0])
        return _l2_normalize(await self._client.aembed_query(text))

    async def embed_batch(
        self, texts: list[str], purpose: str = PURPOSE_DOCUMENT
    ) -> list[list[float]]:
        """Trocea en peticiones del tamaño que admite la API y **conserva el orden**.

        El orden no es un detalle de estilo: un lote reordenado asigna el vector al fragmento
        equivocado y tampoco da error.
        """
        if not texts:
            return []
        if purpose == PURPOSE_QUERY:
            return [_l2_normalize(await self._client.aembed_query(t)) for t in texts]

        salida: list[list[float]] = []
        for inicio in range(0, len(texts), LOTE_MAXIMO_API):
            trozo = texts[inicio : inicio + LOTE_MAXIMO_API]
            vectores = await self._client.aembed_documents(trozo)
            salida.extend(_l2_normalize(v) for v in vectores)
        return salida


class GoogleEmbeddingService(_AdaptadorPorAPI):
    """Embeddings por la API de AI Studio (clave de API en el entorno).

    Se conserva, pero **el despliegue va por Vertex** (PIL.1): una clave de API repartida no
    es lo que una administración pone en producción. Este adaptador vale para un desarrollo
    sin proyecto de GCP.
    """

    MODEL_NAME = "gemini-embedding-001"

    def __init__(
        self,
        model_name: str | None = None,
        output_dimensionality: int = DIMENSION_PLATAFORMA,
        client=None,
    ) -> None:
        self._model_name = model_name or self.MODEL_NAME
        self._dimensions = output_dimensionality
        self._client = client if client is not None else self._build_client()

    def _build_client(self):
        from langchain_google_genai import GoogleGenerativeAIEmbeddings

        return GoogleGenerativeAIEmbeddings(
            model=f"models/{self._model_name}",
            google_api_key=os.getenv("GOOGLE_API_KEY", ""),
            output_dimensionality=self._dimensions,
        )


class VertexEmbeddingService(_AdaptadorPorAPI):
    """Embeddings por Vertex AI — el proveedor del despliegue.

    Autentica con **ADC** (`gcloud auth application-default login` o cuenta de servicio), no
    con una clave de API: la credencial es del entorno y no hay secreto que repartir ni que
    rotar a mano.

    Verificado contra el proyecto real el 2026-08-15: `gemini-embedding-001` a 1024
    dimensiones en `europe-southwest1`, `europe-west1`, `europe-west4` y `europe-west9`.
    """

    MODEL_NAME = "gemini-embedding-001"

    def __init__(
        self,
        model_name: str | None = None,
        output_dimensionality: int = DIMENSION_PLATAFORMA,
        client=None,
        project: str | None = None,
        location: str | None = None,
    ) -> None:
        self._model_name = model_name or self.MODEL_NAME
        self._dimensions = output_dimensionality
        self._project = project or os.getenv("GOOGLE_CLOUD_PROJECT", "")
        self._location = (
            location or os.getenv("GOOGLE_CLOUD_LOCATION") or REGION_VERTEX_POR_DEFECTO
        )
        self._client = client if client is not None else self._build_client()

    def _build_client(self):
        # El proyecto se comprueba ANTES de importar: sin esto, quien no tenga la dependencia
        # instalada recibe un ImportError que no habla del problema que tiene.
        if not self._project:
            raise RuntimeError(
                "Vertex AI necesita saber contra qué proyecto habla, y GOOGLE_CLOUD_PROJECT "
                "no está definida. Ponla en el entorno (junto a GOOGLE_CLOUD_LOCATION, que "
                f"por defecto es {REGION_VERTEX_POR_DEFECTO}) y autentícate con:\n"
                "    gcloud auth application-default login\n"
                "No hace falta ninguna clave de API: Vertex usa las credenciales por "
                "defecto de la aplicación (ADC)."
            )
        try:
            from langchain_google_vertexai import VertexAIEmbeddings
        except ImportError as falta:  # pragma: no cover - depende del entorno instalado
            raise RuntimeError(
                "Falta la dependencia de Vertex. Instálala con:\n"
                "    uv sync\n"
                "o cambia el proveedor de embeddings configurado."
            ) from falta

        return VertexAIEmbeddings(
            model_name=self._model_name,
            project=self._project,
            location=self._location,
            dimensions=self._dimensions,
        )


def _acepta_proposito(funcion) -> bool:
    """¿Este servicio entiende de propósitos, o es un adaptador que no lo declara?

    Misma clase de detección que el `getattr(..., "embed_batch", None)` de la ingesta, y por
    el mismo motivo: hay servicios —dobles de test, adaptadores de terceros— que cumplen el
    contrato mínimo y no el ampliado. Pasarles un argumento que no aceptan los rompería.
    """
    try:
        return "purpose" in inspect.signature(funcion).parameters
    except (TypeError, ValueError):  # pragma: no cover - firmas no introspectables
        return False


async def embed_para_indexar(servicio, textos: list[str]) -> list[list[float]]:
    """Embebe una lista PARA INDEXAR, con el lote del servicio si lo expone.

    **Un solo sitio decide el propósito al indexar.** Repartir esta decisión entre el watcher
    y el re-embebido es cómo se acaba con medio corpus en `RETRIEVAL_DOCUMENT` y medio en el
    tipo por defecto, que es una avería que no da error.
    """
    if not textos:
        return []

    en_lote = getattr(servicio, "embed_batch", None)
    if en_lote is not None:
        if _acepta_proposito(en_lote):
            return await en_lote(textos, purpose=PURPOSE_DOCUMENT)
        return await en_lote(textos)

    if _acepta_proposito(servicio.embed):
        return [await servicio.embed(t, purpose=PURPOSE_DOCUMENT) for t in textos]
    return [await servicio.embed(t) for t in textos]


_local_service: LocalEmbeddingService | None = None


def get_embedding_service() -> LocalEmbeddingService:
    """Singleton del servicio local — carga el modelo solo en la primera llamada.

    Sigue devolviendo el local a propósito: la selección por configuración es MOD.2. Cambiar
    esto aquí, sin la cascada y sin el guardarraíl de espacio vectorial, sería justo el
    interruptor silencioso que MOD.1 viene a impedir.
    """
    global _local_service
    if _local_service is None:
        _local_service = LocalEmbeddingService()
    return _local_service
