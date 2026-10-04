import { Navigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useModulos } from '@/shared/auth/useModulos'

/**
 * Entrar en «Agentes» lleva a consultar si se puede, y si no a publicar y gestionar.
 *
 * **Se espera a saber los módulos**: al recargar `/agentes` la lista llega vacía un instante, y
 * decidir entonces mandaba a gestionar a quien sólo puede consultar (revisión de la PR #221).
 */
export function EntradaDeAgentes() {
  const { t } = useTranslation('common')
  const { modulos, cargando } = useModulos()
  if (cargando) return <div className="p-4">{t('loading')}</div>
  return (
    <Navigate to={modulos.includes('consulta_agentes') ? '/agentes/consultar' : '/agentes/gestion'} replace />
  )
}
