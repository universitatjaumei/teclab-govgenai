"""La traza de diagnóstico de una respuesta (HIB.I). Deploy: edge.

Antes de esto, `interaction_metadata` guardaba `usage_source` y nada más. Con el piloto en
marcha ya es tarde para los datos que no se guardaron: sin los identificadores y las
puntuaciones de lo recuperado no se puede saber, meses después, si una respuesta mala fue de
recuperación o de redacción, ni re-ejecutar una ablación contra las mismas consultas sin volver
a pedir trabajo a los informadores.

**Por qué JSONB y no columnas.** Son campos de diagnóstico cuya lista va a crecer con cada
prompt de medición, y una migración por campo es exactamente lo que hace que dejen de añadirse.
El precio de esa flexibilidad es que un cambio de nombre rompería el instrumental en silencio:
por eso las claves se fijan por snapshot en un test.

**Qué NO entra.** El contenido de los fragmentos: ya está en `hub_document_chunks` por su
identificador, y duplicarlo multiplicaría la tabla por el tamaño del contexto. Y
`fallback_reason`, que ya es columna indexada de `hub_interactions` porque se filtra por ella.

La configuración se guarda **por valor y no por referencia**. La del chatbot cambia: si la traza
guardara sólo el identificador, una respuesta de hace tres semanas se leería con el umbral de
hoy y la comparación entre tandas quedaría muda sin dar ningún error.
"""
from __future__ import annotations

from typing import Any

CLAVES_DE_TRAZA = (
    # De SEC.4, que ya estaba y sigue siendo suyo.
    "usage_source",
    # Configuración vigente en ESTA respuesta.
    "retrieval_mode",
    # PLG.2 — qué estrategia corrió en cada eje. **Clave añadida a conciencia**, que es lo que
    # este `CLAVES_DE_TRAZA` existe para forzar: el aviso de HIB.I es que un cambio de claves
    # rompe el instrumental de `_local/` en silencio, así que añadir una obliga a pasar por aquí
    # y a mirar quién lee la traza. Añadir no rompe a nadie —los lectores ignoran lo que no
    # conocen—; renombrar sí, y por eso el snapshot compara el conjunto entero.
    "estrategias",
    "chunking_strategy",
    "retrieval_top_k",
    "candidate_k",
    "quality_threshold",
    "reranker_enabled",
    # Lo que llegó al modelo.
    "retrieved",
    "dropped_count",
    # La decisión de la puerta.
    "best_score",
    "gate_passed",
    # El camino que siguió la consulta.
    "language",
    # Revisión de la PR #365 — desde #363 `language` es la preferencia de versión del corpus, y
    # la lengua en que contestó el modelo, con la que se decide el aviso, es otra.
    "answer_language",
    "source_language",
    "translation_warning",
    "turn_index",
    "rewritten_query",
    "reformulada",
    "last_index_level",
    # Coste en tiempo. El de tokens ya son columnas propias (SEC.4).
    "latency_ms",
    "first_token_ms",
)

_CLAVES_DE_FUENTE = ("document_id", "url", "anchor", "score", "title")


def _ancla(url: str | None) -> str | None:
    """El ancla del artículo, separada de la URL para poder compararla.

    Se extrae aquí y no se deja implícita en la URL porque `escenario_metricas` compara
    anclas, y hacerlo sobre la cadena entera obligaría a repetir el troceado en cada
    consumidor.
    """
    if not url or "#" not in url:
        return None
    ancla = url.rpartition("#")[2].strip()
    return ancla or None


def _fuente_reducida(fuente: dict) -> dict:
    return {
        "document_id": fuente.get("document_id"),
        "url": fuente.get("url"),
        "anchor": _ancla(fuente.get("url")),
        "score": fuente.get("score"),
        "title": fuente.get("title"),
    }


def construye_traza(
    cfg: Any,
    fuentes: list[dict],
    *,
    usage_source: str = "estimated",
    dropped_count: int = 0,
    best_score: float | None = None,
    gate_passed: bool | None = None,
    language: str | None = None,
    answer_language: str | None = None,
    source_language: str | None = None,
    translation_warning: bool = False,
    turn_index: int | None = None,
    rewritten_query: str | None = None,
    reformulada: bool = False,
    last_index_level: str | None = None,
    latency_ms: int | None = None,
    first_token_ms: int | None = None,
) -> dict:
    """La traza completa de una respuesta, lista para `interaction_metadata`.

    `cfg` se acepta como objeto o como diccionario: en el chat es la configuración efectiva
    resuelta por la cascada, y en los tests un diccionario. Se lee con `getattr`/`get` en vez
    de exigir un tipo para que el instrumental de `_local/` pueda construirla sin arrastrar la
    resolución entera.
    """

    def _de_cfg(clave: str, defecto=None):
        if isinstance(cfg, dict):
            return cfg.get(clave, defecto)
        return getattr(cfg, clave, defecto)

    return {
        "usage_source": usage_source,
        "retrieval_mode": _de_cfg("retrieval_mode"),
        # PLG.2 — qué estrategia corrió en cada eje, POR VALOR y con el resto de la
        # configuración. Sin esto, una respuesta rara de un chatbot con `merge` sobreescrito no
        # se podría explicar mirando su traza: habría que ir a la base a ver qué tenía puesto
        # **en ese momento**, y la configuración cambia.
        "estrategias": _de_cfg("estrategias"),
        "chunking_strategy": _de_cfg("chunking_strategy"),
        "retrieval_top_k": _de_cfg("retrieval_top_k"),
        "candidate_k": _de_cfg("candidate_k"),
        "quality_threshold": _de_cfg("quality_threshold"),
        "reranker_enabled": _de_cfg("reranker_enabled"),
        "retrieved": [_fuente_reducida(f) for f in fuentes],
        "dropped_count": dropped_count,
        "best_score": best_score,
        "gate_passed": gate_passed,
        "language": language,
        "answer_language": answer_language,
        "source_language": source_language,
        "translation_warning": translation_warning,
        "turn_index": turn_index,
        "rewritten_query": rewritten_query,
        "reformulada": reformulada,
        "last_index_level": last_index_level,
        "latency_ms": latency_ms,
        "first_token_ms": first_token_ms,
    }
