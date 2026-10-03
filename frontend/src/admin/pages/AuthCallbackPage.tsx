import { useEffect, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useAuth } from '@/shared/auth'
import { tomarVuelta } from '@/shared/auth/vuelta'

/**
 * Destino del ACS de SAML (SAML_FRONTEND_RETURN_URL). El backend redirige aquí con
 * el JWT en el fragment (#token=…) para que no quede en logs de servidor/proxy.
 */
export function AuthCallbackPage() {
  const { t } = useTranslation('auth')
  const { login } = useAuth()
  const navigate = useNavigate()

  // El token se lee **al renderizar**, no dentro del efecto. La URL ya está ahí cuando este
  // componente se monta, así que «no hay token» es un hecho derivable y no un estado que haya
  // que poner con un `setState`: con el efecto, la pantalla decía «entrando…» durante un
  // render y sólo entonces pasaba a «no se ha podido entrar».
  //
  // `useMemo` con dependencias vacías porque `window.location` no cambia sin remontar este
  // componente: es la URL con la que se llegó.
  const token = useMemo(
    () => new URLSearchParams(window.location.hash.replace(/^#/, '')).get('token'),
    [],
  )

  // El efecto se queda con lo que SÍ es efecto: guardar la sesión y navegar.
  useEffect(() => {
    if (!token) return
    login(token)
    // A donde se iba antes de salir al proveedor; si no se iba a ningún sitio, a la raíz, que
    // decide `Aterrizaje`.
    navigate(tomarVuelta(), { replace: true })
  }, [token, login, navigate])

  return (
    <div className="min-h-screen flex items-center justify-center bg-background">
      {!token ? (
        <p role="alert" className="text-destructive text-sm">{t('callback_error')}</p>
      ) : (
        <p role="status" className="text-muted-foreground text-sm">{t('callback_loading')}</p>
      )}
    </div>
  )
}
