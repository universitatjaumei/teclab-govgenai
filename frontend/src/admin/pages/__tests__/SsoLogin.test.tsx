import { describe, it, expect, beforeAll, afterEach, vi } from 'vitest'
import { render, screen, act } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import i18n from '@/shared/i18n'
import { AuthProvider } from '@/shared/auth'
import { LoginPage } from '../LoginPage'

const navigateSpy = vi.hoisted(() => vi.fn())
const loginSpy = vi.hoisted(() => vi.fn())

vi.mock('react-router-dom', async (orig) => ({
  ...(await orig<typeof import('react-router-dom')>()),
  useNavigate: () => navigateSpy,
}))

/**
 * **Qué proveedores hay lo dice el servidor, no una variable de build** (issue #95).
 *
 * Estos tests usaban `vi.stubEnv('VITE_SAML_ENABLED', ...)`, y esa vía nunca funcionó en
 * producción: el despliegue **no pasa** esa variable al build del frontend —el `Dockerfile` sólo
 * declara `VITE_API_URL` y `VITE_BASE_PATH`—, así que el botón de SSO no habría aparecido nunca.
 * Ahora la pantalla pregunta a `/auth/sso-providers`, y el test se mueve a decirlo por ahí.
 */
vi.mock('@/shared/api/generated/auth/auth', async (orig) => ({
  ...(await orig<typeof import('@/shared/api/generated/auth/auth')>()),
  useProveedoresSSO: () => ({ data: proveedores() }),
}))

/** Lo que el servidor responde en cada test. Por omisión, nada encendido. */
let proveedores: () => { saml: boolean; google: boolean } = () => ({
  saml: false,
  google: false,
})

function conProveedores(valor: { saml: boolean; google: boolean }) {
  proveedores = () => valor
}

beforeAll(async () => {
  await i18n.changeLanguage('es')
})

afterEach(() => {
  conProveedores({ saml: false, google: false })
  vi.unstubAllEnvs()
  navigateSpy.mockClear()
  loginSpy.mockClear()
})

/**
 * Con `QueryClientProvider` desde el issue #95: la pantalla pregunta al servidor qué proveedores
 * de SSO hay encendidos (`useProveedoresSSO`), y eso es react-query. Antes no usaba ninguno, por
 * eso estos tests montaban sin proveedor.
 *
 * Un cliente por render, sin reintentos: compartirlo entre tests filtraría la caché de uno al
 * siguiente, que es la clase de estado compartido que CI busca con `-n0`.
 */
function renderLogin() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <AuthProvider>
          <LoginPage />
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('LoginPage SSO', () => {
  it('should_show_sso_button_when_enabled', () => {
    conProveedores({ saml: true, google: false })
    renderLogin()
    expect(screen.getByText('Entrar con SSO institucional')).toBeDefined()
  })

  it('should_hide_sso_button_when_disabled', () => {
    conProveedores({ saml: false, google: false })
    renderLogin()
    expect(screen.queryByText('Entrar con SSO institucional')).toBeNull()
  })

  it('should_redirect_to_saml_login_on_click', () => {
    conProveedores({ saml: true, google: false })
    const orig = window.location
    Object.defineProperty(window, 'location', {
      configurable: true,
      value: { href: '' },
    })
    renderLogin()
    act(() => {
      screen.getByText('Entrar con SSO institucional').click()
    })
    expect(window.location.href).toContain('/api/v1/auth/saml/login')
    // Sin `from`, la vuelta apuntada es la raíz.
    expect(sessionStorage.getItem('govgenai.vuelta')).toBe('/')
    Object.defineProperty(window, 'location', { configurable: true, value: orig })
  })
})

describe('AuthCallbackPage', () => {
  it('should_extract_token_from_fragment_and_login', async () => {
    vi.doMock('@/shared/auth', async (orig) => ({
      ...(await orig<typeof import('@/shared/auth')>()),
      useAuth: () => ({ login: loginSpy, logout: vi.fn(), user: null, isAuthenticated: false }),
    }))
    window.location.hash = '#token=jwt-token-value'
    const { AuthCallbackPage } = await import('../AuthCallbackPage')
    await act(async () => {
      render(
        <MemoryRouter>
          <AuthCallbackPage />
        </MemoryRouter>,
      )
    })
    expect(loginSpy).toHaveBeenCalledWith('jwt-token-value')
    // A la raíz, que decide `Aterrizaje`, si no se iba a ningún sitio (#176).
    expect(navigateSpy).toHaveBeenCalledWith('/', { replace: true })
    vi.doUnmock('@/shared/auth')
  })

  it('vuelve adonde se iba antes de salir al proveedor (#176)', async () => {
    vi.doMock('@/shared/auth', async (orig) => ({
      ...(await orig<typeof import('@/shared/auth')>()),
      useAuth: () => ({ login: loginSpy, logout: vi.fn(), user: null, isAuthenticated: false }),
    }))
    sessionStorage.setItem('govgenai.vuelta', '/extension/conectar?destino=x')
    window.location.hash = '#token=jwt-token-value'
    const { AuthCallbackPage } = await import('../AuthCallbackPage')
    await act(async () => {
      render(
        <MemoryRouter>
          <AuthCallbackPage />
        </MemoryRouter>,
      )
    })
    expect(navigateSpy).toHaveBeenCalledWith('/extension/conectar?destino=x', { replace: true })
    vi.doUnmock('@/shared/auth')
  })
})
