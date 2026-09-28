import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { AlertTriangle, CheckCircle2, ExternalLink, Loader2 } from 'lucide-react'

import {
  useListPendingVigenciaApiV1HubIngestionChatbotIdVigenciaGet,
  useValidarVigenciaApiV1HubIngestionChatbotIdVigenciaDocumentIdValidarPost as useValidarVigencia,
  getListPendingVigenciaApiV1HubIngestionChatbotIdVigenciaGetQueryKey as claveDeVigencia,
} from '@/shared/api/generated/hub-ingestion/hub-ingestion'
import type { ChatbotRead, DocumentVigenciaOut } from '@/shared/api/generated/model'
import { useChatbotsDeLaOrganizacion } from '@/shared/organizacion/useChatbotsDeLaOrganizacion'

const MOTIU_ESTAT_NO_VIGENT = 'estat_no_vigent'

/**
 * Si `canonical_url` es de verdad una dirección a la que ir (REV.5).
 *
 * Para los documentos del corpus normativo cargados desde carpeta, `canonical_url` es el nombre
 * del fichero —`20260203_UJI_REC_Resolucio_assimilacio_carrecs.md`—, no una URL. Sólo `http` y
 * `https`: un `javascript:` o un `data:` en ese campo se convertiría en un enlace ejecutable
 * servido desde nuestro propio origen.
 */
function esEnlaceExterno(url: string | null | undefined): url is string {
  return typeof url === 'string' && /^https?:\/\//i.test(url)
}

/**
 * Cola de validación de vigencia del corpus (A7).
 *
 * El asistente ya advierte cada vez que cita un documento cuya vigencia nadie ha comprobado
 * (VIS.3). Advertir es lo correcto, pero por sí solo no cierra nada: sin una lista de
 * *cuáles* son, el aviso se repite indefinidamente y no hay forma de ver si el corpus mejora.
 *
 * Quién entra en la lista lo decide el servidor con la misma regla que dispara el aviso, y
 * el motivo viene calculado de allí: si esta pantalla lo recalculara, el número de aquí y el
 * comportamiento del asistente podrían divergir sin que se note.
 */
export function VigenciaPage() {
  const { t } = useTranslation('admin')
  const { t: tc } = useTranslation('common')
  const qc = useQueryClient()

  const [selectedChatbotId, setSelectedChatbotId] = useState<string>('')
  const [motiuFilter, setMotiuFilter] = useState<string>('')
  const [error, setError] = useState<string | null>(null)

  const { data: chatbotsRaw, isLoading: isLoadingChatbots } = useChatbotsDeLaOrganizacion()
  const chatbots: ChatbotRead[] = (chatbotsRaw as unknown as ChatbotRead[] | undefined) ?? []

  if (!selectedChatbotId && chatbots.length > 0) {
    setSelectedChatbotId(chatbots[0].id)
  }

  const { data, isLoading } = useListPendingVigenciaApiV1HubIngestionChatbotIdVigenciaGet(
    selectedChatbotId,
    { query: { enabled: !!selectedChatbotId } },
  )

  /**
   * Validar es un `POST` por documento y no un guardado de la pantalla entera: cada fila es
   * una decisión de una persona sobre una norma concreta, y agruparlas en un «guardar» haría
   * que un fallo en la quinta dejara en duda las cuatro anteriores.
   */
  const { mutate: enviarValidacion, isPending: validando } = useValidarVigencia()

  function validar(documentId: string) {
    setError(null)
    enviarValidacion(
      { chatbotId: selectedChatbotId, documentId },
      {
        onSuccess: () => {
          void qc.invalidateQueries({ queryKey: claveDeVigencia(selectedChatbotId) })
        },
        // Sin esto el botón falla **en silencio**: así se descubrió en la verificación que
        // `require_role("admin")` devolvía 403 a un superadministrador —la pantalla se quedó
        // exactamente igual, con las 41 filas intactas y sin decir nada—. Es el mismo patrón
        // que FIX.1: una mutación sin `onError` convierte cualquier fallo del servidor en
        // «el botón no hace nada».
        onError: (e: unknown) => {
          const detalle = (e as { detail?: string; message?: string })
          setError(detalle?.detail ?? detalle?.message ?? t('hub.vigencia_error_validar'))
        },
      },
    )
  }

  const documentos: DocumentVigenciaOut[] = data?.documents ?? []
  const visibles = motiuFilter ? documentos.filter(d => d.motiu === motiuFilter) : documentos

  const etiquetaMotiu = (motiu: string) =>
    motiu === MOTIU_ESTAT_NO_VIGENT
      ? t('hub.vigencia_motiu_estat_no_vigent')
      : t('hub.vigencia_motiu_sense_validar')

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold">{t('hub.vigencia_title')}</h1>
          <p className="text-sm text-muted-foreground">{t('hub.vigencia_desc')}</p>
        </div>
        {chatbots.length > 0 && (
          <select
            data-testid="vigencia-chatbot"
            value={selectedChatbotId}
            onChange={e => setSelectedChatbotId(e.target.value)}
            className="px-3 py-2 border rounded-md text-sm bg-background w-full sm:w-64"
            aria-label={t('hub.vigencia_title')}
          >
            {chatbots.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        )}
      </div>

      {!selectedChatbotId ? (
        <div className="p-8 text-center border border-dashed rounded-lg text-muted-foreground">
          {isLoadingChatbots ? tc('loading') : t('hub.select_chatbot_first')}
        </div>
      ) : isLoading ? (
        <div className="p-8 text-center text-muted-foreground text-sm flex items-center justify-center gap-2">
          <Loader2 className="w-4 h-4 animate-spin" />{tc('loading')}
        </div>
      ) : (data?.pendents ?? 0) === 0 ? (
        <div
          data-testid="vigencia-todo-validado"
          className="p-8 text-center border rounded-lg text-sm flex items-center justify-center gap-2 bg-card"
        >
          <CheckCircle2 className="w-5 h-5 text-primary" />
          {t('hub.vigencia_all_ok')}
        </div>
      ) : (
        <div className="space-y-4">
          {error && (
            <p role="alert" className="rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
              {error}
            </p>
          )}

          <div
            data-testid="vigencia-resumen"
            className="flex items-center gap-3 p-4 border rounded-lg bg-card"
          >
            <AlertTriangle className="w-5 h-5 text-amber-500 shrink-0" />
            <p className="text-sm">
              {t('hub.vigencia_resumen', {
                pendents: data?.pendents ?? 0,
                total: data?.total ?? 0,
              })}
            </p>
          </div>

          <div className="bg-card rounded-lg border overflow-hidden">
            <div className="flex items-center justify-between p-4 border-b bg-muted/20 gap-3 flex-wrap">
              <h2 className="text-base font-medium">{t('hub.vigencia_table_title')}</h2>
              <select
                data-testid="vigencia-filtro-motiu"
                value={motiuFilter}
                onChange={e => setMotiuFilter(e.target.value)}
                className="px-2 py-1 text-xs border rounded-md bg-background ml-auto"
                aria-label={t('hub.vigencia_motiu')}
              >
                <option value="">{t('hub.vigencia_all_motius')}</option>
                <option value="sense_validar">{t('hub.vigencia_motiu_sense_validar')}</option>
                <option value={MOTIU_ESTAT_NO_VIGENT}>
                  {t('hub.vigencia_motiu_estat_no_vigent')}
                </option>
              </select>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b bg-muted/10 text-left text-muted-foreground">
                    <th className="px-4 py-3 font-medium">{t('hub.doc_title')}</th>
                    <th className="px-4 py-3 font-medium">{t('hub.vigencia_col_estat')}</th>
                    <th className="px-4 py-3 font-medium">{t('hub.vigencia_motiu')}</th>
                    <th className="px-4 py-3 font-medium">{t('hub.vigencia_col_revisio')}</th>
                    <th className="px-4 py-3 font-medium">{t('hub.vigencia_col_revisat')}</th>
                    <th className="px-4 py-3 font-medium">{t('hub.vigencia_col_accion')}</th>
                  </tr>
                </thead>
                <tbody>
                  {visibles.map(doc => (
                    <tr key={doc.id} className="border-b last:border-0 hover:bg-accent/20">
                      <td className="px-4 py-3 max-w-[380px]">
                        {esEnlaceExterno(doc.canonical_url) ? (
                          <a
                            href={doc.canonical_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="flex items-center gap-1 font-medium text-primary hover:underline"
                            title={doc.canonical_url}
                          >
                            <span className="truncate">{doc.title}</span>
                            <ExternalLink className="w-3 h-3 shrink-0" />
                          </a>
                        ) : (
                          /* Sin URL externa no se finge que la hay. Con `href` relativo el
                             navegador lo resolvía contra la ruta actual, abría una pestaña en
                             `/hub/<fichero>.md`, no casaba ninguna ruta y el comodín acababa
                             redirigiendo a Informes. */
                          <span className="block truncate font-medium" title={doc.canonical_url}>
                            {doc.title}
                          </span>
                        )}
                        <span className="text-xs text-muted-foreground">
                          {/* El origen del documento, que cuando no es una URL es el nombre
                              del fichero del corpus: dejar de enlazarlo no puede significar
                              esconderlo, porque es lo único con lo que ir a buscarlo. */}
                          {doc.id_publicacio ?? doc.canonical_url ?? '—'} ·{' '}
                          {doc.language.toUpperCase()}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-muted-foreground">
                        {doc.estat_vigencia ?? '—'}
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className={`px-2 py-0.5 rounded-full text-xs ${
                            doc.motiu === MOTIU_ESTAT_NO_VIGENT
                              ? 'bg-destructive/10 text-destructive'
                              : 'bg-amber-500/10 text-amber-700'
                          }`}
                        >
                          {etiquetaMotiu(doc.motiu)}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-muted-foreground text-xs whitespace-nowrap">
                        {doc.data_revisio_prevista ?? '—'}
                      </td>
                      <td className="px-4 py-3 text-muted-foreground text-xs">
                        {doc.revisat_per ?? '—'}
                        {/* Dos hechos distintos sobre dos momentos distintos: quién revisó el
                            contenido —lo declara el frontmatter del corpus— y quién comprobó
                            que la norma sigue en vigor. Sin esta línea, la firma de REV.6 se
                            guardaría y no la vería nadie. */}
                        {doc.vigencia_validada_per && (
                          <span className="block text-xs text-muted-foreground/80">
                            {t('hub.vigencia_validada_por', {
                              persona: doc.vigencia_validada_per,
                            })}
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-3 whitespace-nowrap">
                        {doc.motiu === MOTIU_ESTAT_NO_VIGENT ? (
                          /* Sin botón, y diciendo por qué. Este documento sigue en la cola
                             por su estado, no por falta de sello: validarlo no lo sacaría de
                             ella —el servidor responde 409— y lo que pide no es revisarlo,
                             es retirarlo. Una fila sin acción y sin explicación se lee como
                             «aquí no se puede hacer nada». */
                          <span className="text-xs text-muted-foreground">
                            {t('hub.vigencia_sugerencia_retirar')}
                          </span>
                        ) : (
                          <button
                            type="button"
                            disabled={validando}
                            onClick={() => validar(doc.id)}
                            className="rounded-md border border-primary px-2 py-1 text-xs font-medium text-primary hover:bg-accent disabled:opacity-50"
                          >
                            {t('hub.vigencia_validar')}
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
