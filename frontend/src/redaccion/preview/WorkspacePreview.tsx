import { Link, useParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useGetWorkspacePreview } from '@/shared/api/generated/redaccion-workspaces/redaccion-workspaces'
import { errorDeLaApi } from '@/shared/api/errorDeLaApi'
import { PreviewRenderer } from './PreviewRenderer'
import './WorkspacePreview.css'

/** Los bloques que el servidor devuelve como pendientes en el 409, si es lo que ha pasado. */
function bloquesPendientes(error: unknown): string[] {
  const pendientes = errorDeLaApi(error)?.pending_block_ids
  return Array.isArray(pendientes) ? pendientes.map(String) : []
}

export function WorkspacePreview() {
  const { id } = useParams<{ id: string }>()
  const { t } = useTranslation('common')
  const { t: tr } = useTranslation('redaccion')

  const { data, isLoading, isError, error } = useGetWorkspacePreview(id ?? '')

  /**
   * INF.3 — la vuelta al informe.
   *
   * Esta vista se monta **fuera del layout** a propósito: es para imprimir, y un menú saldría
   * en el papel. Pero sin ninguna salida no es una vista de impresión, es una trampa: el
   * usuario tuvo que descubrir en las pruebas que se sale con el botón atrás del navegador.
   * Va con `no-print`, así que no aparece en el papel.
   */
  const volver = (
    <Link data-testid="volver-al-informe" to={`/redaccion/workspaces/${id}`} className="no-print">
      {tr('preview_back')}
    </Link>
  )

  if (isLoading) return <div className="preview-loading">{t('loading')}</div>

  // GUI.5 — cualquier fallo salía como la palabra «Error», a secas. El caso normal no es un
  // fallo: es que falta aprobar un bloque de IA, y el servidor lo dice con nombres y apellidos
  // en un 409. Dejarlo en «Error» convierte un paso pendiente en un misterio.
  const pendientes = isError ? bloquesPendientes(error) : []
  if (pendientes.length > 0) {
    return (
      <div className="preview-error" data-testid="preview-pendiente">
        <p>{tr('preview_pending', { count: pendientes.length })}</p>
        <ul>
          {pendientes.map((bloque) => (
            <li key={bloque}>
              {/* Al bloque concreto del informe, no a su nombre a secas. */}
              <Link to={`/redaccion/workspaces/${id}#bloque-${bloque}`}>{bloque}</Link>
            </li>
          ))}
        </ul>
        {volver}
      </div>
    )
  }
  if (isError || !data) {
    return (
      <div className="preview-error">
        <p>{t('error')}</p>
        {volver}
      </div>
    )
  }

  return (
    <div className="workspace-preview-page">
      <div className="preview-toolbar no-print">
        {volver}
        <button
          className="btn-print"
          onClick={() => window.print()}
        >
          {tr('preview_print')}
        </button>
      </div>
      <div className="preview-a4-container">
        <PreviewRenderer payload={data} />
      </div>
    </div>
  )
}
