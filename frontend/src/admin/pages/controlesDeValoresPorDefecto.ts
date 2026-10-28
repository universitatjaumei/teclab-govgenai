/**
 * Qué control pide cada campo (REV.2).
 *
 * Es la **única** lista de campos que queda escrita en el React, y está aquí porque el tipo no
 * se puede deducir del dato: la mitad de estos campos valen `null` cuando heredan, y `null` no
 * dice si lo que va debajo es un número o una casilla.
 *
 * Para que no se desincronice del contrato la vigila un test que la compara con la interfaz
 * generada por Orval (`valoresPorDefectoRead.ts`): si el servidor añade un campo y nadie le da
 * control, se pone rojo. Eso es lo que separa un mapa mantenido de una lista que miente.
 */
export const CONTROLES: Record<
  string,
  'numero' | 'booleano' | 'texto' | 'texto-largo' | 'estrategias'
> = {
  // PLG.2 — un select POR EJE, no un campo de texto con JSON: lo que se guarda es
  // `{eje: nombre}` y escribirlo a mano invita a errores que solo se ven al guardar.
  default_estrategias: 'estrategias',
  default_public_graph_profile: 'texto',
  default_retrieval_mode: 'texto',
  default_language_mode: 'texto',
  default_quality_threshold: 'numero',
  default_min_retrieval_results: 'numero',
  default_min_retrieval_score: 'numero',
  default_reranker_enabled: 'booleano',
  default_answer_template: 'texto-largo',
  default_context_token_budget: 'numero',
  default_chunk_size: 'numero',
  default_chunk_overlap: 'numero',
  default_chunking_strategy: 'texto',
  default_query_rewriting_enabled: 'booleano',
  rewrite_llm_config_id: 'texto',
}
