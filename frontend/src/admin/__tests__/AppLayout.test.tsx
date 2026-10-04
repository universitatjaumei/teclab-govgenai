import { describe, it, expect, beforeEach, beforeAll, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import i18n from '@/shared/i18n'
import { AuthProvider } from '@/shared/auth'
import { AppLayout } from '../AppLayout'
import { useGetMeApiV1AuthMeGet } from '@/shared/api/generated/auth/auth'
import { useGetResolvedThemeApiV1HubThemesResolvedGet } from '@/shared/api/generated/hub-themes/hub-themes'

/**
 * INF.7 — el menú se genera con los módulos que concede el servidor, así que el test tiene que
 * darlos: antes las tres entradas estaban escritas en el componente y salían para cualquiera.
 */
// USR.7 — el menú de la cuenta lleva el formulario de la propia contraseña, así que este
// layout consulta también esa mutación. Un doble del módulo tiene que traer **todo** lo que el
// árbol usa: con `useCambiarMiPassword` fuera, el componente llama a `undefined` y el layout
// entero no monta — ocho rojos que parecen del menú y son del doble.
vi.mock('@/shared/api/generated/auth/auth', () => ({
  useGetMeApiV1AuthMeGet: vi.fn(),
  useCambiarMiPassword: () => ({ mutate: vi.fn(), isPending: false, isError: false }),
}))

// La marca del panel viene de la cascada del servidor; sin el doble, el `useQuery` de este
// hook reventaría por falta de `QueryClientProvider`. Lo que hace la marca tiene sus propios
// tests en `AppLayoutMarca.test.tsx`.
vi.mock('@/shared/api/generated/hub-themes/hub-themes', () => ({
  useGetResolvedThemeApiV1HubThemesResolvedGet: vi.fn(),
}))

// REV.10 — `AppLayout` lleva el selector de organización, así que consulta la lista. Sin el
// doble, el `useQuery` revienta por falta de `QueryClientProvider` y el fallo parece del menú.
vi.mock('@/shared/api/generated/hub-organizaciones/hub-organizaciones', () => ({
  useListOrganizacionesApiV1HubOrganizacionesGet: () => ({ data: [] }),
}))

function conModulos(modulos: string[]) {
  vi.mocked(useGetMeApiV1AuthMeGet).mockReturnValue({
    data: { modulos },
    isLoading: false,
  } as never)
}

const TOKEN = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.' +
  btoa(JSON.stringify({ user_id: '1', email: 'admin@test.com', role: 'admin', exp: 9999999999 }))
    .replace(/=/g, '').replace(/\+/g, '-').replace(/\//g, '_') +
  '.signature'

beforeAll(async () => {
  await i18n.changeLanguage('es')
})

beforeEach(() => {
  localStorage.setItem('access_token', TOKEN)
  conModulos(['chatbots', 'curacion', 'informes', 'plataforma'])
  vi.mocked(useGetResolvedThemeApiV1HubThemesResolvedGet).mockReturnValue({
    data: { config: {} },
    isLoading: false,
  } as never)
})

function renderLayout(path = '/hub') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <AppLayout />
      </AuthProvider>
    </MemoryRouter>
  )
}

describe('AppLayout', () => {
  it('should_render_the_three_modules_plus_platform_administration', () => {
    // «Automatización» y «Plataforma» eran pantallas vacías: un menú que promete lo que no
    // hay es peor que un menú corto. «Informes» estaba construido y fuera de todo menú.
    //
    // **PLAT.2 devuelve «Plataforma», esta vez con contenido**: las pantallas transversales
    // que vivían dentro del módulo Chatbots. «Automatización» sigue fuera, porque ese módulo
    // no existe — sólo hay infraestructura que consume Informes.
    renderLayout()
    expect(screen.getByText('Chatbots')).toBeDefined()
    expect(screen.getByText('Informes')).toBeDefined()
    expect(screen.getByText('Curación')).toBeDefined()
    expect(screen.getByText('Plataforma')).toBeDefined()
    expect(screen.queryByText('Automatización')).toBeNull()
  })

  it('should_mark_chatbots_section_active_on_hub_route', () => {
    renderLayout('/hub')
    const enlace = screen.getByRole('link', { name: /chatbots/i })
    expect(enlace.getAttribute('aria-current')).toBe('page')
  })

  it('should_mark_reports_section_active_on_redaccion_route', () => {
    renderLayout('/redaccion')
    const enlace = screen.getByRole('link', { name: /informes/i })
    expect(enlace.getAttribute('aria-current')).toBe('page')
  })

  it('should_let_the_user_change_the_language', async () => {
    // El panel se traducía a tres idiomas y no había forma de elegir: dependías de lo que
    // dijera el navegador.
    renderLayout()
    const selector = screen.getByLabelText('Idioma') as HTMLSelectElement

    expect(selector.value).toBe('es')
    expect(screen.getByRole('option', { name: 'Valencià' })).toBeDefined()
    expect(screen.getByRole('option', { name: 'English' })).toBeDefined()
  })

  it('should_render_outlet_content_area', () => {
    renderLayout()
    expect(screen.getByRole('main')).toBeDefined()
  })

  it('should_show_user_email_in_sidebar', () => {
    renderLayout()
    expect(screen.getByText('admin@test.com')).toBeDefined()
  })

  it('should_have_logout_button', () => {
    renderLayout()
    expect(screen.getByRole('button', { name: /cerrar sesión/i })).toBeDefined()
  })
})

describe('INF.7 — el menú sólo enseña lo concedido', () => {
  it('should_show_only_reports_for_a_reports_only_worker', () => {
    conModulos(['informes'])
    renderLayout('/redaccion')

    expect(screen.getByRole('link', { name: /informes/i })).toBeDefined()
    // Lo que hacía falta arreglar: un trabajador cualquiera veía —y podía editar— los
    // chatbots institucionales.
    expect(screen.queryByRole('link', { name: /chatbots/i })).toBeNull()
    expect(screen.queryByRole('link', { name: /curaci/i })).toBeNull()
  })
})

describe('Agentes — una sola entrada para consultar y para publicar (2026-10-03)', () => {
  function entradasDeAgentes() {
    return screen.queryAllByRole('link').filter((a) => a.getAttribute('href')?.startsWith('/agentes'))
  }

  it('quien sólo consulta ve una entrada «Agentes»', () => {
    conModulos(['consulta_agentes'])
    renderLayout('/agentes')
    expect(entradasDeAgentes().map((a) => a.textContent)).toEqual(['Agentes'])
  })

  it('quien además publica sigue viendo una sola', () => {
    conModulos(['consulta_agentes', 'agentes'])
    renderLayout('/agentes')
    expect(entradasDeAgentes()).toHaveLength(1)
  })

  it('con la consulta retirada, quien publica no pierde la entrada', () => {
    conModulos(['agentes'])
    renderLayout('/agentes')
    expect(entradasDeAgentes()).toHaveLength(1)
  })

  it('sin ninguno de los dos, no hay entrada', () => {
    conModulos(['informes'])
    renderLayout('/redaccion')
    expect(entradasDeAgentes()).toHaveLength(0)
  })
})
