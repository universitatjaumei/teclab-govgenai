import { describe, it, expect, vi, beforeAll, beforeEach, afterEach } from 'vitest'
import { act, render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useSearchParams } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import i18n from '@/shared/i18n'
import {
  useConectarLaExtensionApiV1AgentesExtensionConectarPost,
  useConexionesDeLaExtensionApiV1AgentesExtensionConexionesGet,
  useRevocarConexionDeLaExtensionApiV1AgentesExtensionConexionesConexionIdDelete,
} from '@/shared/api/generated/agentes/agentes'
import { ConectarExtensionPage } from '../ConectarExtensionPage'
import { ConexionesDeLaExtension } from '../ConexionesDeLaExtension'
import { recordarVuelta, rutaSegura, tomarVuelta } from '@/shared/auth/vuelta'
import { PrivateRoute } from '@/shared/auth/PrivateRoute'

/**
 * #176 — la extensión del navegador se conecta con la cuenta de la persona.
 *
 * - La página de conexión **no entrega nada sin que la persona pulse**, y vuelve a la extensión
 *   con el token en el fragmento; el destino lo valida el servidor.
 * - Las conexiones se ven y se revocan desde «Consultar».
 * - Quien llega sin sesión **vuelve a la página de conexión** después de entrar, también por SSO.
 */
vi.mock('@/shared/api/generated/agentes/agentes', () => ({
  useConectarLaExtensionApiV1AgentesExtensionConectarPost: vi.fn(),
  useConexionesDeLaExtensionApiV1AgentesExtensionConexionesGet: vi.fn(),
  useRevocarConexionDeLaExtensionApiV1AgentesExtensionConexionesConexionIdDelete: vi.fn(),
}))
// Sin sesión: es lo que hace saltar a `PrivateRoute`. La página de conexión no lo mira.
vi.mock('@/shared/auth/useAuth', () => ({ useAuth: () => ({ isAuthenticated: false, user: null }) }))

const DESTINO = 'https://abcdefghijklmnopabcdefghijklmnop.chromiumapp.org/'
const conectar = vi.fn()
const revocar = vi.fn()
const asignar = vi.fn()

function envolver(hijo: React.ReactNode) {
  return (
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>{hijo}</MemoryRouter>
    </QueryClientProvider>
  )
}

beforeAll(async () => {
  await i18n.changeLanguage('es')
})

beforeEach(() => {
  vi.mocked(useConectarLaExtensionApiV1AgentesExtensionConectarPost).mockReturnValue({ mutate: conectar, isPending: false } as never)
  vi.mocked(useRevocarConexionDeLaExtensionApiV1AgentesExtensionConexionesConexionIdDelete).mockReturnValue({ mutate: revocar } as never)
  vi.mocked(useConexionesDeLaExtensionApiV1AgentesExtensionConexionesGet).mockReturnValue({ data: [] } as never)
  vi.stubGlobal('location', { ...window.location, search: `?destino=${encodeURIComponent(DESTINO)}`, assign: asignar })
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.clearAllMocks()
  sessionStorage.clear()
})

describe('#176 — la página de conexión', () => {
  it('no pide nada hasta que la persona pulsa Conectar', () => {
    render(envolver(<ConectarExtensionPage />))
    expect(conectar).not.toHaveBeenCalled()
    expect(screen.getByText(i18n.t('agentes:extension.no_es_control'))).toBeInTheDocument()
  })

  it('al pulsar, pide el token para ese destino y vuelve a la extensión con él en el fragmento', () => {
    render(envolver(<ConectarExtensionPage />))
    fireEvent.click(screen.getByRole('button', { name: i18n.t('agentes:extension.conectar') }))
    expect(conectar).toHaveBeenCalledWith({ data: { destino: DESTINO } }, expect.anything())
    conectar.mock.calls[0][1].onSuccess({ id: 'c1', token: 'pat_abc_def', destino: DESTINO })
    expect(asignar).toHaveBeenCalledWith(`${DESTINO}#token=pat_abc_def`)
  })

  it('vuelve al destino que devuelve el servidor, y nunca a uno que no sea de una extensión', () => {
    render(envolver(<ConectarExtensionPage />))
    fireEvent.click(screen.getByRole('button', { name: i18n.t('agentes:extension.conectar') }))
    act(() => conectar.mock.calls[0][1].onSuccess({ id: 'c1', token: 'pat_abc_def', destino: 'https://evil.example/' }))
    expect(asignar).not.toHaveBeenCalled()
    expect(screen.getByRole('alert')).toBeInTheDocument()
  })

  it('si el servidor no reconoce la extensión, lo dice y no redirige', () => {
    render(envolver(<ConectarExtensionPage />))
    fireEvent.click(screen.getByRole('button', { name: i18n.t('agentes:extension.conectar') }))
    act(() => conectar.mock.calls[0][1].onError({ status: 400, data: { detail: { message: 'Esta extensión no está reconocida por la plataforma.' } } }))
    expect(asignar).not.toHaveBeenCalled()
    expect(screen.getByRole('alert')).toBeInTheDocument()
  })

  it('sin destino no hay nada que conectar', () => {
    vi.stubGlobal('location', { ...window.location, search: '', assign: asignar })
    render(envolver(<ConectarExtensionPage />))
    expect(screen.getByRole('button', { name: i18n.t('agentes:extension.conectar') })).toBeDisabled()
  })
})

describe('#176 — las conexiones, en Consultar', () => {
  it('sin ninguna, lo dice', () => {
    render(envolver(<ConexionesDeLaExtension />))
    expect(screen.getByText(i18n.t('agentes:extension.ninguna'))).toBeInTheDocument()
  })

  it('lista las conexiones y revoca la elegida', () => {
    vi.mocked(useConexionesDeLaExtensionApiV1AgentesExtensionConexionesGet).mockReturnValue({
      data: [
        { id: 'c1', prefijo: 'a1b2c3', creado_en: '2026-10-03T10:00:00Z', ultimo_uso_en: null, caduca_en: '2026-11-02T10:00:00Z' },
      ],
    } as never)
    render(envolver(<ConexionesDeLaExtension />))
    expect(screen.getByText('a1b2c3…')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: i18n.t('agentes:extension.revocar') }))
    expect(revocar).toHaveBeenCalledWith({ conexionId: 'c1' }, expect.anything())
  })
})

describe('#176 — se vuelve adonde se iba después de entrar', () => {
  it('sólo rutas de la propia aplicación', () => {
    expect(rutaSegura('/extension/conectar?destino=x')).toBe('/extension/conectar?destino=x')
    expect(rutaSegura('//evil.example/')).toBe('/')
    expect(rutaSegura('/\\evil.example')).toBe('/')
    expect(rutaSegura('https://evil.example/')).toBe('/')
    expect(rutaSegura(null)).toBe('/')
  })

  it('la vuelta apuntada antes del SSO se toma una sola vez', () => {
    recordarVuelta('/extension/conectar?destino=x')
    expect(tomarVuelta()).toBe('/extension/conectar?destino=x')
    expect(tomarVuelta()).toBe('/')
  })

  it('PrivateRoute manda al login con la ruta y la consulta', () => {
    render(
      <MemoryRouter initialEntries={['/extension/conectar?destino=abc']}>
        <Routes>
          <Route element={<PrivateRoute />}>
            <Route path="/extension/conectar" element={<p>conectar</p>} />
          </Route>
          <Route path="/login" element={<LoginEco />} />
        </Routes>
      </MemoryRouter>,
    )
    expect(screen.getByTestId('from').textContent).toBe('/extension/conectar?destino=abc')
  })
})

function LoginEco() {
  const [params] = useSearchParams()
  return <p data-testid="from">{params.get('from')}</p>
}
