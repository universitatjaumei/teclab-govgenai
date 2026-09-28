import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { useAuth } from './useAuth'
import { CambioObligatorio } from './CambioObligatorio'

export function PrivateRoute() {
  const { isAuthenticated, user } = useAuth()
  const location = useLocation()

  if (!isAuthenticated) {
    return <Navigate to={`/login?from=${encodeURIComponent(location.pathname)}`} replace />
  }

  // Issue #94 — con la contraseña que puso otra persona no se entra a ningún sitio. El servidor
  // ya responde 403 a todo lo demás; sin esto, el panel sólo enseñaría la cascada de errores.
  if (user?.cambio_pendiente) {
    return <CambioObligatorio />
  }

  return <Outlet />
}
