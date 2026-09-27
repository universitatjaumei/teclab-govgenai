import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { useOrganizacionElegida } from '@/shared/organizacion/useOrganizacionElegida'
import {
  useGetValoresPorDefectoApiV1HubOrganizacionesOrganizacionIdValoresPorDefectoGet as useValores,
  useUpdateValoresPorDefectoApiV1HubOrganizacionesOrganizacionIdValoresPorDefectoPatch as useGuardarValores,
  getGetValoresPorDefectoApiV1HubOrganizacionesOrganizacionIdValoresPorDefectoGetQueryKey as claveDeValores,
} from '@/shared/api/generated/hub-organizaciones/hub-organizaciones'
import { useOpcionesDeLengua } from '@/shared/api/generated/hub-opciones/hub-opciones'
import { useOpcionesDeGrafoApiV1HubChatbotsOpcionesDeGrafoGet } from '@/shared/api/generated/hub-chatbots/hub-chatbots'
import type { OpcionesDeLengua } from '@/shared/api/generated/model'

/** Los campos que pueden volver a «heredar el defecto de plataforma» valiendo `null`. */
const HEREDABLES = [
  'default_context_token_budget',
  'default_chunk_size',
  'default_chunk_overlap',
  'default_chunking_strategy',
  'default_query_rewriting_enabled',
] as const

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

/**
 * Valores conocidos de los campos enumerados, en un `<datalist>` y **no en un `<select>`**.
 *
 * El contrato declara estos cuatro campos como `string` libre, así que un desplegable perdería
 * en silencio cualquier valor que esta lista no conociera —justo al abrir la pantalla, sin que
 * nadie lo pidiera—. Es el mismo criterio, y por el mismo motivo, que la lista de tipografías
 * de Identidad visual. Cuando el servidor los declare como enumeración cerrada, esto puede
 * pasar a `<select>` generado del contrato y dejar de vivir aquí.
 *
 * **`default_language_mode` ya se fue de aquí (LANG.2)**, y no por gusto: la lista decía
 * `['prefer', 'strict', 'neutral']` y dos de los tres eran falsos —`strict` es una política que
 * la factoría del grafo nunca compuso, y `neutral` es el nombre de la clase, no el valor, que se
 * llama `none`—. Desde LANG.1 los dos dan 422 al guardar. Ahora sale del catálogo del servidor,
 * que además da el código del corpus (`val`, no `ca`). Sigue siendo `<datalist>` por el motivo
 * de arriba: `fixed:<código>` es paramétrico, así que el campo tiene que ser cadena libre.
 */
/**
 * **PLG.3 — los perfiles y los modos ya NO estan aqui**, y es exactamente el mismo error que
 * LANG.2 arreglo con `default_language_mode`: una lista escrita en React que dice lo que el
 * servidor acepta. Entonces mentia porque dos de los tres valores daban 422; ahora mentiria de
 * otra forma —por defecto— al no poder enumerar lo que aporte un paquete instalado.
 *
 * Lo que queda es `default_chunking_strategy`, y se queda a proposito: es un CHECK de la base
 * (`ck_chatbot_chunking_strategy`), o sea ESTRUCTURA con codigo que la aplica en el chunker, no
 * vocabulario que pueda crecer por instalacion. El criterio es el mismo de CLAUDE.md §5.
 */
/** Claves LITERALES por el guardarrail de i18n de CAL.4 (ver ChatbotsPage). */
const ETIQUETA_DE_EJE: Record<string, string> = {
  retrieval: 'hub.chatbot_eje_retrieval',
  merge: 'hub.chatbot_eje_merge',
  template: 'hub.chatbot_eje_template',
  language: 'hub.chatbot_eje_language',
}

const SUGERENCIAS: Record<string, readonly string[]> = {
  default_chunking_strategy: ['structural', 'parent_child'],
}

/**
 * Los valores que se ofrecen para `default_language_mode`, compuestos del catálogo (LANG.2).
 *
 * Los modos simples tal cual, y el paramétrico una vez por idioma —`fixed:val`, `fixed:es`…—,
 * porque lo que se guarda en el campo es el valor completo. `requiere_lengua` lo dice el
 * servidor: el día que haya un segundo modo paramétrico, esto no hay que tocarlo.
 */
function modosDeIdiomaOfrecidos(
  catalogo: OpcionesDeLengua | undefined
): readonly string[] | undefined {
  if (!catalogo) return undefined
  return catalogo.modos.flatMap((m) =>
    m.requiere_lengua ? catalogo.lenguas.map((l) => `${m.valor}:${l.codigo}`) : [m.valor]
  )
}


/**
 * Los valores por defecto de RAG de una organización (PLAT.3, editables en REV.2).
 *
 * Vivían dentro de la pantalla de Organizaciones, y por eso esa pantalla acabó bajo el módulo
 * Chatbots: la mayoría de sus campos eran de Chatbots. Aquí están donde pertenecen —el perfil de
 * grafo, el modo de recuperación, el troceado o el reranker no dicen nada de quién es el
 * inquilino— con selector de organización, porque son configuración **del módulo** aplicada a
 * una organización.
 *
 * **Y se puede volver a heredar.** Seis de estos campos usan `null` con el significado «usa el
 * defecto de la plataforma», y hasta PLAT.3 el `PATCH` descartaba el `null` explícito
 * (`exclude_none`), así que una vez fijado un valor propio no había vuelta atrás por API. El
 * botón de cada campo heredable manda ese `null`.
 *
 * **REV.2 — y se pueden cambiar.** Hasta aquí la pantalla los pintaba con `String(valor)`: se
 * veía la configuración y no se podía tocar, así que cambiar el tamaño de fragmento de una
 * organización exigía ir por API. El `PATCH` ya lo aceptaba; sólo faltaba el control.
 */
export function ValoresPorDefectoPage() {
  const { t } = useTranslation('admin')
  // LANG.2 — los modos de idioma los enumera el servidor. Mientras no ha llegado no se
  // ofrece nada: una lista propia sería volver a escribir el catálogo en React.
  const { data: opcionesDeLengua } = useOpcionesDeLengua()
  // PLG.3 — perfiles y modos, del catalogo de ESTA instalacion.
  const { data: opcionesDeGrafoRaw } = useOpcionesDeGrafoApiV1HubChatbotsOpcionesDeGrafoGet()
  const opcionesDeGrafo = opcionesDeGrafoRaw as unknown as
    | {
        perfiles: { nombre: string; configurable: boolean }[]
        modos: { nombre: string }[]
        estrategias: Record<string, { nombre: string }[]>
        ejes: string[]
      }
    | undefined
  const { t: tc } = useTranslation('common')
  const qc = useQueryClient()

  /**
   * La organización sale de la elección compartida del panel (REV.10).
   *
   * Esta pantalla tenía su propio selector con su propio estado, «Identidad visual» tenía otro,
   * y cambiar de organización obligaba a repetir la elección en cada una. El selector sigue
   * aquí —es donde se está trabajando— pero escribe en la elección común, así que al cambiarlo
   * también cambia el de la cabecera y el de las demás pantallas.
   */
  const {
    organizaciones,
    elegida: organizacionId,
    elegir: setOrganizacionId,
  } = useOrganizacionElegida()

  const { data: valores, isLoading } = useValores(organizacionId, {
    query: { enabled: Boolean(organizacionId) },
  })
  const { mutate: guardar, isPending } = useGuardarValores()

  /**
   * Los campos heredados a los que alguien ha pedido darles valor propio.
   *
   * Sin esto, «heredado» es un callejón sin salida: se puede volver a heredar pero no salir de
   * ahí. Es estado de la pantalla y no del servidor —todavía no se ha guardado nada—, y se
   * limpia al cambiar de organización porque lo que se abrió pertenecía a la anterior.
   */
  const [desplegados, setDesplegados] = useState<Set<string>>(new Set())

  // Se limpia **durante el render** y no en un efecto, que es el patrón que React documenta para
  // «reiniciar estado cuando cambia un valor». Con el efecto, React pintaba un fotograma con los
  // campos que alguien había desplegado en la organización ANTERIOR antes de limpiarlos: poca
  // cosa visualmente, pero en una pantalla multiorganización es enseñar un instante qué abrió
  // alguien en otra.
  const [organizacionPrevia, setOrganizacionPrevia] = useState(organizacionId)
  if (organizacionId !== organizacionPrevia) {
    setOrganizacionPrevia(organizacionId)
    setDesplegados(new Set())
  }

  function cambiar(campo: string, valor: unknown) {
    guardar(
      { organizacionId, data: { [campo]: valor } },
      {
        onSuccess: () =>
          void qc.invalidateQueries({ queryKey: claveDeValores(organizacionId) }),
      }
    )
  }

  /**
   * Guarda al salir del campo, y **sólo si el valor ha cambiado**.
   *
   * Pasar por un campo con el tabulador no es editarlo: guardar ahí escribiría un valor propio
   * sobre un campo que sólo estaba heredando, que es precisamente la decisión que esta pantalla
   * existe para hacer explícita.
   */
  function alSalirDelCampo(campo: string, crudo: string, original: unknown) {
    const tipo = CONTROLES[campo]
    if (tipo === 'numero') {
      if (crudo.trim() === '') return
      const numero = Number(crudo)
      // Un texto que no es número no se manda: el servidor respondería 422 y la pantalla
      // no sabría decir por qué. `<input type="number">` ya lo evita en la mayoría de
      // navegadores, pero no en todos ni con el teclado numérico de un móvil.
      if (Number.isNaN(numero) || numero === original) return
      cambiar(campo, numero)
      return
    }
    if (crudo === original || (original == null && crudo === '')) return
    cambiar(campo, crudo)
  }

  return (
    <div className="space-y-6">
      <header>
        <h2 className="text-lg font-semibold">{t('hub.valores_por_defecto.titulo')}</h2>
        <p className="text-sm text-muted-foreground">{t('hub.valores_por_defecto.alcance')}</p>
      </header>

      <div className="flex flex-col gap-1 max-w-sm">
        <label htmlFor="vpd_organizacion" className="text-sm font-medium">
          {t('hub.valores_por_defecto.organizacion')}
        </label>
        <select
          id="vpd_organizacion"
          value={organizacionId}
          onChange={(e) => setOrganizacionId(e.target.value)}
          className="rounded-md border px-2 py-1.5 text-sm bg-background"
        >
          {organizaciones.map((o) => (
            <option key={o.id} value={String(o.id)}>
              {o.name}
            </option>
          ))}
        </select>
      </div>

      {isLoading || !valores ? (
        <p>{tc('loading')}</p>
      ) : (
        <div className="space-y-3">
          {Object.entries(valores).map(([campo, valor]) => {
            const heredable = (HEREDABLES as readonly string[]).includes(campo)
            const heredado = valor === null
            const tipo = CONTROLES[campo]
            const editable = tipo !== undefined && (!heredado || desplegados.has(campo))
            const sugerencias =
              campo === 'default_language_mode'
                ? modosDeIdiomaOfrecidos(opcionesDeLengua)
                : campo === 'default_public_graph_profile'
                  ? opcionesDeGrafo?.perfiles.filter(p => p.configurable).map(p => p.nombre)
                  : campo === 'default_retrieval_mode'
                    ? opcionesDeGrafo?.modos.map(m => m.nombre)
                    : SUGERENCIAS[campo]
            const idLista = sugerencias ? `vpd_${campo}_opciones` : undefined

            return (
              <div
                key={campo}
                data-testid={campo}
                className="flex flex-wrap items-center gap-3 rounded-md border p-3 text-sm"
              >
                {/* La etiqueta traducida, con el nombre tecnico como reserva: si el
                    contrato crece con un campo nuevo, la fila aparece igual —con su nombre
                    crudo— en vez de quedarse vacia o reventar. */}
                <label htmlFor={`vpd_${campo}`} className="w-72 shrink-0">
                  {t(`hub.valores_por_defecto.campos.${campo}` as Parameters<typeof t>[0], {
                    defaultValue: campo,
                  })}
                </label>

                <span className="flex-1">
                  {editable ? (
                    tipo === 'estrategias' ? (
                      <span className="flex flex-wrap gap-2">
                        {(opcionesDeGrafo?.ejes ?? []).map((eje) => {
                          const puestas = (valor as Record<string, string> | null) ?? {}
                          return (
                            <span key={eje} className="flex items-center gap-1">
                              <label htmlFor={`vpd_${campo}_${eje}`} className="text-xs">
                                {ETIQUETA_DE_EJE[eje] ? t(ETIQUETA_DE_EJE[eje]) : eje}
                              </label>
                              <select
                                id={`vpd_${campo}_${eje}`}
                                value={puestas[eje] ?? ''}
                                disabled={isPending}
                                onChange={(e) => {
                                  const siguiente = { ...puestas }
                                  // Clave AUSENTE, no cadena vacia: la cascada distingue
                                  // «heredar» de «elegida», y mandar '' guardaria una eleccion.
                                  if (e.target.value) siguiente[eje] = e.target.value
                                  else delete siguiente[eje]
                                  cambiar(campo, Object.keys(siguiente).length ? siguiente : null)
                                }}
                                className="rounded border px-2 py-1 text-xs"
                              >
                                <option value="">{t('hub.chatbot_estrategia_heredar')}</option>
                                {(opcionesDeGrafo?.estrategias?.[eje] ?? []).map((s) => (
                                  <option key={s.nombre} value={s.nombre}>{s.nombre}</option>
                                ))}
                              </select>
                            </span>
                          )
                        })}
                      </span>
                    ) : tipo === 'booleano' ? (
                      <input
                        id={`vpd_${campo}`}
                        type="checkbox"
                        checked={valor === true}
                        disabled={isPending}
                        onChange={(e) => cambiar(campo, e.target.checked)}
                        className="h-4 w-4 rounded border"
                      />
                    ) : tipo === 'texto-largo' ? (
                      <textarea
                        id={`vpd_${campo}`}
                        defaultValue={valor == null ? '' : String(valor)}
                        disabled={isPending}
                        rows={3}
                        onBlur={(e) => alSalirDelCampo(campo, e.target.value, valor)}
                        className="w-full rounded border px-2 py-1 text-sm"
                      />
                    ) : (
                      <input
                        id={`vpd_${campo}`}
                        type={tipo === 'numero' ? 'number' : 'text'}
                        // `step="any"`: tres de estos campos son decimales (umbrales y
                        // puntuaciones) y el paso entero por omisión los rechazaría.
                        step={tipo === 'numero' ? 'any' : undefined}
                        list={idLista}
                        defaultValue={valor == null ? '' : String(valor)}
                        disabled={isPending}
                        onBlur={(e) => alSalirDelCampo(campo, e.target.value, valor)}
                        className="w-full max-w-xs rounded border px-2 py-1 text-sm"
                      />
                    )
                  ) : (
                    /* «Heredado» y no una celda vacía: `null` aquí es una decisión, no un dato
                       que falte, y confundirlas es lo que hace que nadie se atreva a tocarlo. */
                    <em className="text-muted-foreground">
                      {t('hub.valores_por_defecto.heredado')}
                    </em>
                  )}
                  {sugerencias && (
                    <datalist id={idLista}>
                      {sugerencias.map((opcion) => (
                        <option key={opcion} value={opcion} />
                      ))}
                    </datalist>
                  )}
                </span>

                {heredado && tipo !== undefined && !desplegados.has(campo) && (
                  <button
                    type="button"
                    onClick={() =>
                      setDesplegados((previo) => new Set(previo).add(campo))
                    }
                    className="text-xs underline"
                  >
                    {t('hub.valores_por_defecto.establecer_valor')}
                  </button>
                )}

                {heredable && !heredado && (
                  <button
                    type="button"
                    disabled={isPending}
                    onClick={() => cambiar(campo, null)}
                    className="text-xs underline disabled:opacity-50"
                  >
                    {t('hub.valores_por_defecto.volver_a_heredar')}
                  </button>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
