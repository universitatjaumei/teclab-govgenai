import { Navigate } from 'react-router-dom'
import { useModulos } from '@/shared/auth/useModulos'

/** Entrar en «Agentes» lleva a consultar si se puede, y si no a publicar y gestionar. */
export function EntradaDeAgentes() {
  const { modulos } = useModulos()
  return (
    <Navigate to={modulos.includes('consulta_agentes') ? '/agentes/consultar' : '/agentes/gestion'} replace />
  )
}
