import { describe, it, expect, beforeEach, beforeAll, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import i18n from '@/shared/i18n'
import { UsuariosPage } from '../pages/UsuariosPage'
import {
  useListUsersApiV1HubUsersGet,
  useCreateUserApiV1HubUsersPost,
  useUpdateUserApiV1HubUsersUserIdPatch,
  useDeleteUserApiV1HubUsersUserIdDelete as useBorrar,
  useSetUsuarioPassword,
  useCapacidadesDePersonas,
} from '@/shared/api/generated/hub-users/hub-users'
import { useGetCatalogoApiV1HubModulosCatalogoGet } from '@/shared/api/generated/hub-modulos/hub-modulos'
import type { UsuarioRead } from '@/shared/api/generated/model'

/**
 * Conceder módulos ocurre donde se da de alta a la persona (issue #100).
 *
 * `hub_module_grants` estuvo **completamente vacía** en producción durante semanas, con la
 * pantalla de concesiones existiendo desde IDE.5. No faltaba la pantalla: conceder vivía en
 * *Plataforma → Módulos* y dar de alta en *Personas*, o sea dos viajes, y el segundo se olvida.
 *
 * Y una persona sin acceso a nada **se veía igual** que una recién creada, así que nadie lo notó.
 *
 * **Lo que la pantalla NO hace es decidir.** `sin_concesion_directa` lo calcula el servidor; aquí
 * sólo se pinta. Un `if (role !== 'superadmin' && modulos.length === 0)` en React sería la regla
 * escrita por segunda vez — es la regla maestra de `AGENTS.md`, y el test de abajo la fija
 * dando un superadministrador con la lista vacía y `sin_concesion_directa: false`.
 */
vi.mock('@/shared/api/generated/hub-users/hub-users', () => ({
  useListUsersApiV1HubUsersGet: vi.fn(),
  useCreateUserApiV1HubUsersPost: vi.fn(),
  useUpdateUserApiV1HubUsersUserIdPatch: vi.fn(),
  useDeleteUserApiV1HubUsersUserIdDelete: vi.fn(),
  useSetUsuarioPassword: vi.fn(),
  useCapacidadesDePersonas: vi.fn(),
  getListUsersApiV1HubUsersGetQueryKey: () => ['usuarios'],
}))

// El catálogo de módulos es dato del servidor. Se mockea su módulo entero porque la pantalla
// pasa a llamarlo: añadir un hook rompe los tests que mockean su módulo con un factory
// explícito, y este fichero nace ya con el suyo.
vi.mock('@/shared/api/generated/hub-modulos/hub-modulos', () => ({
  useGetCatalogoApiV1HubModulosCatalogoGet: vi.fn(),
}))

vi.mock('@/shared/auth/useAutoridadDelRol', () => ({
  useAutoridadDelRol: vi.fn(() => ({ data: { authority: 'app' }, isLoading: false })),
}))

vi.mock('@/shared/api/generated/hub-organizaciones/hub-organizaciones', () => ({
  useListOrganizacionesApiV1HubOrganizacionesGet: () => ({ data: [] }),
}))

function persona(cambios: Partial<UsuarioRead> = {}): UsuarioRead {
  return {
    id: '11111111-1111-1111-1111-111111111111',
    email: 'persona@uji.es',
    display_name: 'Una Persona',
    role: 'user',
    organizacion_id: null,
    is_active: true,
    origen: 'manual',
    created_at: '2026-09-22T09:00:00Z',
    created_by: 'root',
    last_login_at: null,
    puede_borrarse: true,
    motivo_no_borrable: null,
    puede_fijar_contrasena: true,
    modulos_concedidos: [],
    sin_concesion_directa: false,
    ...cambios,
  }
}

const crear = vi.fn()

function montar(
  personas: UsuarioRead[],
  acciones: string[] = ['listar', 'crear', 'editar', 'borrar']
) {
  vi.mocked(useListUsersApiV1HubUsersGet).mockReturnValue({
    data: personas,
    isLoading: false,
    error: null,
  } as never)
  vi.mocked(useCreateUserApiV1HubUsersPost).mockReturnValue({
    mutate: crear,
    isPending: false,
  } as never)
  vi.mocked(useUpdateUserApiV1HubUsersUserIdPatch).mockReturnValue({
    mutate: vi.fn(),
    isPending: false,
  } as never)
  vi.mocked(useBorrar).mockReturnValue({ mutate: vi.fn(), isPending: false } as never)
  vi.mocked(useSetUsuarioPassword).mockReturnValue({
    mutate: vi.fn(),
    isPending: false,
  } as never)
  vi.mocked(useCapacidadesDePersonas).mockReturnValue({
    data: { acciones_permitidas: acciones },
    isLoading: false,
  } as never)
  vi.mocked(useGetCatalogoApiV1HubModulosCatalogoGet).mockReturnValue({
    data: [
      { code: 'chatbots', label: 'Chatbots', vigente: true },
      { code: 'informes', label: 'Informes', vigente: true },
      { code: 'retirado', label: 'Retirado', vigente: false },
    ],
  } as never)

  return render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <UsuariosPage />
      </MemoryRouter>
    </QueryClientProvider>
  )
}

beforeAll(async () => {
  await i18n.changeLanguage('es')
})

beforeEach(() => {
  vi.clearAllMocks()
})

describe('Los módulos se eligen al dar de alta', () => {
  it('ofrece los módulos vigentes del catálogo del servidor', () => {
    montar([])

    expect(screen.getByLabelText('Chatbots')).toBeInTheDocument()
    expect(screen.getByLabelText('Informes')).toBeInTheDocument()
  })

  it('no ofrece un módulo retirado del catálogo', () => {
    montar([])

    expect(screen.queryByLabelText('Retirado')).not.toBeInTheDocument()
  })

  it('envía los módulos marcados junto con el alta', () => {
    montar([])

    fireEvent.change(screen.getByLabelText('Correo'), {
      target: { value: 'nueva@uji.es' },
    })
    fireEvent.click(screen.getByLabelText('Informes'))
    fireEvent.click(screen.getByRole('button', { name: 'Dar de alta' }))

    expect(crear).toHaveBeenCalledTimes(1)
    expect(crear.mock.calls[0][0].data.modulos).toEqual(['informes'])
  })

  it('sin marcar ninguno, envía la lista vacía y no omite el campo', () => {
    montar([])

    fireEvent.change(screen.getByLabelText('Correo'), {
      target: { value: 'nueva@uji.es' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Dar de alta' }))

    expect(crear.mock.calls[0][0].data.modulos).toEqual([])
  })
})

describe('El catálogo sólo se pide a quien puede crear personas', () => {
  /**
   * `get_catalogo` está protegido con `_require_superadmin`, pero esta pantalla **también la ven
   * los administradores de organización**: pueden listar personas y fijar contraseñas (USR.9).
   *
   * Sin condición, el hook se dispara igual para ellos: un 403 en cada carga de la pantalla, con
   * los reintentos de React Query encima. Lo señaló la revisión automática de la PR #105 y era
   * cierto — lo introduje con el propio arreglo del #100.
   */
  it('no lo pide si quien mira no puede crear', () => {
    montar([], ['listar', 'fijar_contrasena'])

    const opciones = vi.mocked(useGetCatalogoApiV1HubModulosCatalogoGet).mock.calls[0]?.[0]
    expect(opciones?.query?.enabled).toBe(false)
  })

  it('sí lo pide a quien puede crear', () => {
    montar([])

    const opciones = vi.mocked(useGetCatalogoApiV1HubModulosCatalogoGet).mock.calls[0]?.[0]
    expect(opciones?.query?.enabled).toBe(true)
  })
})

describe('Quien no puede entrar en ningún módulo se ve', () => {
  it('avisa en la fila de quien el servidor marca', () => {
    montar([persona({ sin_concesion_directa: true })])

    expect(screen.getByTestId('sin-concesion-directa-11111111-1111-1111-1111-111111111111')).toBeInTheDocument()
  })

  it('no avisa cuando el servidor no lo marca, aunque la lista esté vacía', () => {
    // Un superadministrador entra por su rol: lista vacía y `sin_concesion_directa` en falso.
    // Si la pantalla mirara `modulos_concedidos.length === 0` aquí avisaría, y estaría
    // calculando la regla por su cuenta.
    montar([persona({ role: 'superadmin', modulos_concedidos: [], sin_concesion_directa: false })])

    expect(
      screen.queryByTestId('sin-concesion-directa-11111111-1111-1111-1111-111111111111')
    ).not.toBeInTheDocument()
  })

  it('enseña los módulos que sí tiene', () => {
    montar([persona({ modulos_concedidos: ['chatbots', 'informes'] })])

    const celda = screen.getByTestId('modulos-11111111-1111-1111-1111-111111111111')
    expect(celda).toHaveTextContent('chatbots')
    expect(celda).toHaveTextContent('informes')
  })
})
