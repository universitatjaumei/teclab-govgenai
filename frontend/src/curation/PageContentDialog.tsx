import { useTranslation } from 'react-i18next'
import { useGetPageContent } from '@/shared/api/generated/hub-sites/hub-sites'

interface Props {
  pageId: string
  onClose: () => void
}

interface Contenido {
  url: string
  title: string | null
  status: string
  content: string
  token_count: number | null
  owner: string | null
  published_at: string | null
  render_signals: unknown[]
}

/**
 * El texto **guardado** de una página rastreada (CUR.4).
 *
 * El informe de calidad acusaba y no dejaba comprobar: no había ninguna pantalla que mostrara el
 * contenido de una página, así que juzgar un hallazgo obligaba a copiar la URL y abrirla a mano —y
 * eso enseña la página original, no lo que el asistente va a leer—.
 *
 * Lo que se muestra aquí es lo que iría al corpus, que desde CUR.3 ya no lleva el menú del portal.
 * Es la única forma de ver que el recorte de plantilla no se ha comido contenido.
 */
export function PageContentDialog({ pageId, onClose }: Props) {
  const { t } = useTranslation('curation')
  const { t: tc } = useTranslation('common')

  const { data, isLoading } = useGetPageContent(pageId)
  const pagina = data as unknown as Contenido | undefined

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={t('page_content_title')}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
    >
      <div className="bg-background rounded-lg shadow-lg w-full max-w-3xl max-h-[85vh] flex flex-col">
        <div className="p-4 border-b space-y-1">
          <div className="flex items-start justify-between gap-4">
            <h2 className="text-lg font-semibold">{t('page_content_title')}</h2>
            <button
              type="button"
              data-testid="btn-cerrar-contenido"
              onClick={onClose}
              className="text-sm px-2 py-1 rounded border hover:bg-accent"
            >
              {tc('close')}
            </button>
          </div>

          {isLoading || !pagina ? (
            <p className="text-sm text-muted-foreground">{tc('loading')}</p>
          ) : (
            <>
              <p data-testid="cabecera-pagina" className="text-xs text-muted-foreground">
                {pagina.title ?? '—'}
                {pagina.owner ? ` · ${pagina.owner}` : ''}
                {pagina.published_at
                  ? ` · ${new Date(pagina.published_at).toLocaleDateString()}`
                  : ''}
                {pagina.token_count !== null ? ` · ${pagina.token_count} tokens` : ''}
              </p>
              {/* Enlace a la original para poder comparar: lo de abajo es lo guardado. */}
              <a
                data-testid="enlace-pagina-original"
                href={pagina.url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-xs text-primary underline break-all"
              >
                {pagina.url}
              </a>
            </>
          )}
        </div>

        <div className="p-4 overflow-y-auto space-y-3">
          {/* Que quede claro qué se está leyendo: si no, se confunde con la página del portal. */}
          <p data-testid="aviso-texto-guardado" className="text-xs text-muted-foreground italic">
            {t('page_content_note')}
          </p>

          {pagina && pagina.render_signals.length > 0 && (
            <p className="text-xs bg-yellow-50 text-yellow-900 rounded p-2">
              {t('page_content_needs_js')}
            </p>
          )}

          {pagina && !pagina.content.trim() ? (
            <p className="text-sm text-muted-foreground">{t('page_content_empty')}</p>
          ) : (
            <pre
              data-testid="contenido-de-la-pagina"
              className="text-sm whitespace-pre-wrap font-sans bg-muted/40 rounded p-3"
            >
              {pagina?.content}
            </pre>
          )}
        </div>
      </div>
    </div>
  )
}
