import { describe, it, expect, beforeEach, beforeAll, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import i18n from '@/shared/i18n'
import { AuthProvider } from '@/shared/auth'
import { AppLayout } from '../AppLayout'
import { useGetMeApiV1AuthMeGet } from '@/shared/api/generated/auth/auth'
import { useGetResolvedThemeApiV1HubThemesResolvedGet } from '@/shared/api/generated/hub-themes/hub-themes'

/**
 * La marca del panel viene del servidor, no del repositorio.
 *
 * `AppLayout` hacía `import logoUji from '@/assets/logo-uji.png'` y pintaba el logotipo de
 * la Universitat Jaume I con `alt="Universitat Jaume I"`. En un proyecto multiorganización
 * eso significa que cualquier ayuntamiento que clonara el repositorio arrancaba con la
 * marca de una universidad ajena en su barra lateral — y había una excepción en
 * `.gitignore` más un guardarraíl en integración continua que garantizaban que ese fichero
 * viajase.
 *
 * Ahora la marca la resuelve la cascada visual del servidor (plataforma → organización) y
 * el panel solo la pinta. Es el mismo reparto que `acciones_permitidas` o que los módulos
 * concedidos: el servidor decide, el cliente pinta.
 */
// USR.7 — el menú de la cuenta lleva el formulario de la propia contraseña, así que el
// layout consulta también esa mutación. Sin ella en el doble, el componente llama a
// `undefined` y no monta nada: los rojos parecen de esta pantalla y son del doble.
vi.mock('@/shared/api/generated/auth/auth', () => ({
  useGetMeApiV1AuthMeGet: vi.fn(),
  useCambiarMiPassword: () => ({ mutate: vi.fn(), isPending: false, isError: false }),
}))

vi.mock('@/shared/api/generated/hub-themes/hub-themes', () => ({
  useGetResolvedThemeApiV1HubThemesResolvedGet: vi.fn(),
}))

// REV.10 — `AppLayout` lleva el selector de organización, así que consulta la lista. Sin el
// doble, el `useQuery` revienta por falta de `QueryClientProvider` y el fallo parece del menú.
// `vi.fn()` y no una funcion fija: un test necesita cambiar la lista para el caso «no hay
// ninguna organizacion», y con una funcion literal no se puede.
import { useListOrganizacionesApiV1HubOrganizacionesGet } from '@/shared/api/generated/hub-organizaciones/hub-organizaciones'

vi.mock('@/shared/api/generated/hub-organizaciones/hub-organizaciones', () => ({
  useListOrganizacionesApiV1HubOrganizacionesGet: vi.fn(),
}))

const ORGANIZACIONES = [
  { id: 'org-uji', name: 'Universitat Jaume I' },
  { id: 'org-b', name: 'Otra' },
]

const TOKEN =
  'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.' +
  btoa(JSON.stringify({ user_id: '1', email: 'admin@test.com', role: 'admin', exp: 9999999999 }))
    .replace(/=/g, '')
    .replace(/\+/g, '-')
    .replace(/\//g, '_') +
  '.signature'

function conMarca(branding: Record<string, unknown> | undefined) {
  vi.mocked(useGetResolvedThemeApiV1HubThemesResolvedGet).mockReturnValue({
    data: { config: branding === undefined ? {} : { branding } },
    isLoading: false,
  } as never)
}

beforeAll(async () => {
  await i18n.changeLanguage('es')
})

beforeEach(() => {
    vi.mocked(useListOrganizacionesApiV1HubOrganizacionesGet).mockReturnValue({
      data: ORGANIZACIONES,
    } as unknown as ReturnType<typeof useListOrganizacionesApiV1HubOrganizacionesGet>)
  localStorage.setItem('access_token', TOKEN)
  vi.mocked(useGetMeApiV1AuthMeGet).mockReturnValue({
    data: { modulos: ['chatbots', 'curacion', 'informes'] },
    isLoading: false,
  } as never)
  conMarca(undefined)
})

function renderLayout() {
  return render(
    <MemoryRouter initialEntries={['/hub']}>
      <AuthProvider>
        <AppLayout />
      </AuthProvider>
    </MemoryRouter>
  )
}

describe('la marca del panel la decide el servidor', () => {
  it('should_paint_the_logo_that_the_cascade_resolves', () => {
    conMarca({ logoUrl: '/api/v1/hub/themes/abc/logo', logoAlt: 'Ayuntamiento de Vila-real' })
    renderLayout()

    const logo = screen.getByRole('img', { name: 'Ayuntamiento de Vila-real' })
    expect(logo.getAttribute('src')).toBe('/api/v1/hub/themes/abc/logo')
  })

  it('should_fall_back_to_the_platform_name_when_there_is_no_logo', () => {
    // Sin marca configurada no se pinta un hueco ni el logotipo de nadie: se pone el
    // nombre de la plataforma, que ya está traducido.
    renderLayout()

    expect(screen.getByText('Gov Gen AI Platform')).toBeDefined()
    expect(screen.queryByRole('img')).toBeNull()
  })

  it('should_use_the_platform_name_as_alt_text_when_the_mark_has_no_alt', () => {
    // Un logotipo sin texto alternativo es una imagen muda para un lector de pantalla, y
    // el `alt` lo rellena quien sube la marca: puede no venir.
    conMarca({ logoUrl: '/api/v1/hub/themes/abc/logo' })
    renderLayout()

    expect(screen.getByRole('img', { name: 'Gov Gen AI Platform' })).toBeDefined()
  })

  it('should_not_paint_any_institution_mark_bundled_with_the_code', () => {
    // El guardarraíl del cambio: mientras el logotipo salga de un `import`, la marca viaja
    // en el bundle y es la misma para todos los despliegues.
    conMarca({ logoUrl: '/api/v1/hub/themes/abc/logo', logoAlt: 'Quien sea' })
    renderLayout()

    const src = screen.getByRole('img').getAttribute('src') ?? ''
    expect(src.startsWith('/api/')).toBe(true)
    expect(src).not.toMatch(/assets|logo-uji/)
  })
})

describe('REV.12 — la marca sigue a la organización elegida', () => {
  it('should_ask_the_server_for_the_organisation_chosen_in_the_panel', () => {
    // El usuario configuró el logotipo de la UJI y no lo veía: la cascada funde el nivel de
    // organización sólo para quien pertenece a una sola, y un superadministrador no pertenece
    // a ninguna. REV.10 puso la elección en la cabecera; esto la usa.
    localStorage.setItem('organizacion-elegida', 'org-uji')
    render(
      <MemoryRouter>
        <AuthProvider>
          <AppLayout />
        </AuthProvider>
      </MemoryRouter>
    )

    expect(vi.mocked(useGetResolvedThemeApiV1HubThemesResolvedGet)).toHaveBeenCalledWith(
      expect.objectContaining({ organizacion: 'org-uji' })
    )
  })

  it('should_land_on_the_first_organisation_when_none_is_chosen', () => {
    // **Reescrito el 2026-09-27, y por una decisión, no por un refactor.**
    //
    // Este test afirmaba que sin elección se pide la marca de PLATAFORMA. Nunca fue cierto en
    // el estado estable: el hook corregía con un efecto y elegía la primera organización, así
    // que la marca de plataforma duraba **un render**. El test pasaba por ese instante.
    //
    // Decidido: sin elección previa se aterriza en la primera organización, cambiable desde la
    // cabecera. Así que lo que se comprueba es eso, que es lo que de verdad ve quien entra.
    // Con cero organizaciones sigue sin pedirse ninguna — lo cubre el test de abajo.
    localStorage.clear()
    render(
      <MemoryRouter>
        <AuthProvider>
          <AppLayout />
        </AuthProvider>
      </MemoryRouter>
    )

    expect(vi.mocked(useGetResolvedThemeApiV1HubThemesResolvedGet)).toHaveBeenCalledWith(
      expect.objectContaining({ organizacion: 'org-uji' })
    )
  })

  it('should_ask_for_nothing_in_particular_when_there_are_no_organisations', () => {
    // El caso que sí pide la marca de plataforma: no hay ninguna organización a la que
    // aterrizar. Mandar una cadena vacía sería pedir «la organización que se llama ""», que
    // es un 422, así que el hook devuelve `''` y el consumidor lo traduce a `undefined`.
    localStorage.clear()
    vi.mocked(useListOrganizacionesApiV1HubOrganizacionesGet).mockReturnValue({
      data: [],
    } as unknown as ReturnType<typeof useListOrganizacionesApiV1HubOrganizacionesGet>)

    render(
      <MemoryRouter>
        <AuthProvider>
          <AppLayout />
        </AuthProvider>
      </MemoryRouter>
    )

    expect(vi.mocked(useGetResolvedThemeApiV1HubThemesResolvedGet)).toHaveBeenCalledWith(
      expect.objectContaining({ organizacion: undefined })
    )
  })
})
