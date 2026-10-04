import { useState, type FormEvent } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useAuth } from '@/shared/auth'
import { recordarVuelta, rutaSegura } from '@/shared/auth/vuelta'
import {
  getLoginAdminApiV1AuthAdminLoginPostUrl,
  getLoginSuperadminApiV1AuthSuperadminLoginPostUrl,
  getLoginUsuarioUrl,
  useProveedoresSSO,
} from '@/shared/api/generated/auth/auth'
import { getLoginConGoogleUrl } from '@/shared/api/generated/auth-google/auth-google'
import { apiBaseUrl as API_BASE } from '@/shared/api/client'

// Las rutas se toman de lo generado por Orval desde `openapi.json`, no se escriben a mano.
// Escritas a mano llevaban desde el 2026-04-24 apuntando a `/api/v1/auth/token/admin`, que
// no existe: el 404 caía en el catch y se pintaba «credenciales incorrectas», así que el
// síntoma acusaba a la contraseña del usuario y el fallo estaba aquí.
//
// **Tres puertas y un solo formulario** (USR.3): dos tablas de cuentas de administración y
// `hub_users`, que es donde están las personas. Se prueban en orden, y el orden importa: el
// mensaje de error **sólo** aparece si fallan las tres, y no dice cuál de ellas conocía el
// correo. Decirlo convertiría el formulario en un oráculo para saber en qué tabla está alguien;
// y enseñarlo antes de tiempo es lo que pasó el 2026-09-01, cuando ninguno de los 401 de la
// cadena distinguía «contraseña mala» de «esta cuenta no tiene login local».
//
// La tercera puede responder **404** en vez de 401: es `LOCAL_USER_LOGIN_ENABLED=false`, o sea
// que en este despliegue esa puerta no existe. Se trata igual que un rechazo.
const RUTAS_LOGIN = [
  getLoginSuperadminApiV1AuthSuperadminLoginPostUrl(),
  getLoginAdminApiV1AuthAdminLoginPostUrl(),
  getLoginUsuarioUrl(),
]

// Iconos en línea: el proyecto no tiene librería de iconos en esta pantalla y traerla por dos
// glifos no sale a cuenta. `aria-hidden` porque quien nombra el botón es su `aria-label`.
function Ojo() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  )
}

function OjoTachado() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M9.9 4.24A9.1 9.1 0 0 1 12 4c6.5 0 10 7 10 7a17.6 17.6 0 0 1-3.2 4.19" />
      <path d="M6.6 6.6A17.7 17.7 0 0 0 2 11s3.5 7 10 7a9.7 9.7 0 0 0 5.4-1.6" />
      <path d="m2 2 20 20" />
      <path d="M14.1 14.1a3 3 0 0 1-4.2-4.2" />
    </svg>
  )
}

export function LoginPage() {
  /**
   * **Qué botones de SSO hay, se lo pregunta al servidor** (issue #95).
   *
   * Antes esto era `import.meta.env.VITE_SAML_ENABLED`, una variable de **build**, y el
   * despliegue **no la pasa**: el `Dockerfile` del frontend sólo declara `VITE_API_URL` y
   * `VITE_BASE_PATH`, así que en producción la condición era siempre falsa y **el botón de SSO
   * no aparecía nunca**. No se había notado porque el SAML está apagado.
   *
   * Con `useProveedoresSSO`, encender un proveedor es poner sus secretos y reiniciar la
   * aplicación: no hay que reconstruir el frontend para que salga su botón.
   */
  const { data: proveedores } = useProveedoresSSO()
  const SAML_ENABLED = proveedores?.saml === true
  const GOOGLE_ENABLED = proveedores?.google === true
  const { t } = useTranslation('admin')
  const { t: ta } = useTranslation('auth')
  const { login } = useAuth()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [verContrasena, setVerContrasena] = useState(false)

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    setError('')
    setLoading(true)
    const form = new FormData(e.currentTarget)
    const credenciales = JSON.stringify({
      email: form.get('email'),
      password: form.get('password'),
    })
    try {
      // Un solo formulario para dos tablas de cuentas. Se prueban las dos puertas en orden:
      // un 401 del SuperAdmin no significa «contraseña mala», significa «no es de los tuyos».
      for (const ruta of RUTAS_LOGIN) {
        const res = await fetch(`${API_BASE}${ruta}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: credenciales,
        })
        if (res.ok) {
          const { access_token } = await res.json() as { access_token: string }
          login(access_token)
          // **A la raíz, no a `/hub`.** El aterrizaje lo decide `Aterrizaje` desde INF.7, que
          // cae en el primer módulo concedido. Con el destino escrito aquí, una persona `user`
          // sin el módulo de chatbots aterrizaba en `/hub` y rebotaba a «sin acceso»: la misma
          // decisión en dos sitios, y una de las dos equivocada.
          navigate(rutaSegura(params.get('from')), { replace: true })
          return
        }
      }
      setError(t('login.error'))
    } catch {
      setError(t('login.error'))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-background">
      <div className="w-full max-w-sm space-y-4 p-8 rounded-lg border bg-card shadow-sm">
        <h1 className="text-2xl font-semibold">{t('login.title')}</h1>
        {GOOGLE_ENABLED && (
          <button
            type="button"
            data-testid="btn-entrar-con-google"
            onClick={() => {
              recordarVuelta(params.get('from'))
              window.location.href = `${API_BASE}${getLoginConGoogleUrl()}`
            }}
            className="w-full py-2 px-4 border rounded-md text-sm font-medium bg-card hover:bg-accent/30"
          >
            {ta('google_button')}
          </button>
        )}
        {(GOOGLE_ENABLED || SAML_ENABLED) && (
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <span className="h-px flex-1 bg-border" />
            {ta('sso_divider')}
            <span className="h-px flex-1 bg-border" />
          </div>
        )}
        {SAML_ENABLED && (
          <>
            <button
              type="button"
              onClick={() => {
                recordarVuelta(params.get('from'))
                window.location.href = `${API_BASE}/api/v1/auth/saml/login`
              }}
              className="w-full py-2 px-4 bg-primary text-primary-foreground rounded-md text-sm font-medium"
            >
              {ta('sso_button')}
            </button>
          </>
        )}
        <form onSubmit={handleSubmit} className="space-y-4">
        {error && <p role="alert" className="text-destructive text-sm">{error}</p>}
        <div className="space-y-1">
          <label htmlFor="email" className="text-sm font-medium">{t('login.email')}</label>
          <input id="email" name="email" type="email" required autoComplete="email"
            className="w-full px-3 py-2 border rounded-md text-sm bg-background" />
        </div>
        <div className="space-y-1">
          <label htmlFor="password" className="text-sm font-medium">{t('login.password')}</label>
          <div className="relative">
            <input id="password" name="password" type={verContrasena ? 'text' : 'password'}
              required autoComplete="current-password"
              className="w-full px-3 py-2 pr-10 border rounded-md text-sm bg-background" />
            {/* type="button" no es opcional: dentro de un <form>, un <button> sin type es
                submit, y el ojo enviaria el formulario a medio escribir. */}
            <button
              type="button"
              onClick={() => setVerContrasena((v) => !v)}
              aria-pressed={verContrasena}
              aria-controls="password"
              aria-label={verContrasena ? t('login.hide_password') : t('login.show_password')}
              title={verContrasena ? t('login.hide_password') : t('login.show_password')}
              className="absolute inset-y-0 right-0 px-3 flex items-center text-muted-foreground hover:text-foreground"
            >
              {verContrasena ? <OjoTachado /> : <Ojo />}
            </button>
          </div>
        </div>
        <button type="submit" disabled={loading}
          className="w-full py-2 px-4 bg-primary text-primary-foreground rounded-md text-sm font-medium disabled:opacity-50">
          {t('login.submit')}
        </button>
        </form>
      </div>
    </div>
  )
}
