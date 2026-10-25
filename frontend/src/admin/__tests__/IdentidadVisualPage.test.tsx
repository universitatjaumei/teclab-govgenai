import { describe, it, expect, beforeEach, beforeAll, vi } from 'vitest'
import { render, screen, within, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import i18n from '@/shared/i18n'
import { IdentidadVisualPage } from '../pages/IdentidadVisualPage'
import {
  useGetThemesApiV1HubThemesGet,
  useCreateThemeApiV1HubThemesPost,
  useUpdateThemeApiV1HubThemesThemeIdPut,
  useUploadThemeLogoApiV1HubThemesThemeIdLogoPost,
  useGetThemeDefaultsApiV1HubThemesDefaultsGet,
} from '@/shared/api/generated/hub-themes/hub-themes'
import { useListOrganizacionesApiV1HubOrganizacionesGet } from '@/shared/api/generated/hub-organizaciones/hub-organizaciones'
import { useListChatbotsApiV1HubChatbotsGet } from '@/shared/api/generated/hub-chatbots/hub-chatbots'
import { useAuth } from '@/shared/auth'
import { expectNoA11yViolations } from '@/test/a11y'

/**
 * PLAT.6 — la identidad visual se configura, no se escribe en JSON.
 *
 * La cascada visual existía y funcionaba —plataforma → organización → chatbot— y desde la marca
 * institucional lleva también el logotipo. Lo que no existía era dónde configurarla: el logotipo
 * se subía por `curl` y los colores solo se podían tocar escribiendo JSON a mano en un
 * `<textarea>` cuyo destino, además, no lo leía nadie.
 *
 * Lo que esta pantalla tiene que hacer bien, y que no es evidente:
 *
 * - **Los campos salen del contrato**, iterando lo que devuelve el servidor. Si estuvieran
 *   escritos, la pantalla dejaría de pintar lo que el contrato mande y volvería a decidir ella.
 * - **Decir qué hereda cada nivel** de su padre. Una cascada que no se ve es una cascada que se
 *   configura a ciegas.
 * - **No congelar lo heredado al guardar otra cosa.** Copiar la paleta del padre al guardar solo
 *   el logotipo deja al hijo con valores propios que ya no siguen al padre, y nadie se enteraría.
 */
vi.mock('@/shared/api/generated/hub-themes/hub-themes', () => ({
  useGetThemesApiV1HubThemesGet: vi.fn(),
  useCreateThemeApiV1HubThemesPost: vi.fn(),
  useUpdateThemeApiV1HubThemesThemeIdPut: vi.fn(),
  useUploadThemeLogoApiV1HubThemesThemeIdLogoPost: vi.fn(),
  useGetThemeDefaultsApiV1HubThemesDefaultsGet: vi.fn(),
  getGetThemesApiV1HubThemesGetQueryKey: () => ['temas'],
  getGetResolvedThemeApiV1HubThemesResolvedGetQueryKey: () => ['tema-resuelto'],
}))
vi.mock('@/shared/api/generated/hub-organizaciones/hub-organizaciones', () => ({
  useListOrganizacionesApiV1HubOrganizacionesGet: vi.fn(),
}))
vi.mock('@/shared/api/generated/hub-chatbots/hub-chatbots', () => ({
  useOpcionesDeGrafoApiV1HubChatbotsOpcionesDeGrafoGet: () => ({ data: { perfiles: [{ nombre: 'PUBLIC_KB_RICH', configurable: true }], modos: [{ nombre: 'RAG' }, { nombre: 'MD_LONG_CONTEXT' }, { nombre: 'MD_AGENT_SELECTOR' }], estrategias: { retrieval: [], merge: [], template: [], language: [] }, ejes: ['retrieval', 'merge', 'template', 'language'] } }),
  useListChatbotsApiV1HubChatbotsGet: vi.fn(),
}))
vi.mock('@/shared/auth', () => ({ useAuth: vi.fn() }))

const TEMA_PLATAFORMA = {
  id: 'tema-plataforma',
  name: 'Plataforma',
  organizacion_id: null,
  chatbot_id: null,
  is_default: false,
  config: {
    colors: { primary: '#0066cc', background: '#ffffff' },
    typography: { fontFamily: "'Inter', sans-serif" },
    branding: { logoAlt: 'Gov Gen AI Platform' },
  },
}

const TEMA_ORG = {
  id: 'tema-org',
  name: 'UJI',
  organizacion_id: 'org-1',
  chatbot_id: null,
  is_default: false,
  // Solo define `primary`: el resto lo hereda de la plataforma.
  config: { colors: { primary: '#c026d3' }, branding: {} },
}

/** Lo que publica `GET /hub/themes/defaults`: el contrato con sus valores por omisión. */
const VALORES_DEL_CONTRATO = {
  colors: { primary: '#0066cc', background: '#ffffff', border: '#dee2e6' },
  typography: { fontFamily: "'Inter', sans-serif", fontSize: '1rem' },
  branding: { logoUrl: null, logoAlt: null },
}

const guardar = vi.fn()
const crear = vi.fn()
const subirLogo = vi.fn()

function conRol(role: string) {
  vi.mocked(useAuth).mockReturnValue({ user: { role } } as never)
}

beforeAll(async () => {
  await i18n.changeLanguage('es')
})

// #277 — la pantalla pregunta capacidades a `/auth/me`; se simulan las del rol del test.
vi.mock('@/shared/auth/useCapacidad', async () =>
  (await import('@/test-utils/capacidades')).dobleDeUseCapacidad(() => vi.mocked(useAuth)()?.user?.role),
)

beforeEach(() => {
  guardar.mockClear()
  crear.mockClear()
  subirLogo.mockClear()
  conRol('superadmin')
  vi.mocked(useGetThemesApiV1HubThemesGet).mockReturnValue({
    data: [TEMA_PLATAFORMA, TEMA_ORG],
    isLoading: false,
  } as never)
  vi.mocked(useGetThemeDefaultsApiV1HubThemesDefaultsGet).mockReturnValue({
    data: { config: VALORES_DEL_CONTRATO },
  } as never)
  vi.mocked(useListOrganizacionesApiV1HubOrganizacionesGet).mockReturnValue({
    data: [{ id: 'org-1', name: 'Universitat Jaume I' }],
  } as never)
  vi.mocked(useListChatbotsApiV1HubChatbotsGet).mockReturnValue({
    data: [{ id: 'bot-1', name: 'Asistente normativo', organizacion_id: 'org-1' }],
  } as never)
  vi.mocked(useUpdateThemeApiV1HubThemesThemeIdPut).mockReturnValue({
    mutate: guardar,
    isPending: false,
  } as never)
  vi.mocked(useCreateThemeApiV1HubThemesPost).mockReturnValue({
    mutate: crear,
    isPending: false,
  } as never)
  vi.mocked(useUploadThemeLogoApiV1HubThemesThemeIdLogoPost).mockReturnValue({
    mutate: subirLogo,
    isPending: false,
  } as never)
})

function renderPage(ruta = '/plataforma/identidad-visual') {
  const cliente = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <MemoryRouter initialEntries={[ruta]}>
      <QueryClientProvider client={cliente}>
        <IdentidadVisualPage />
      </QueryClientProvider>
    </MemoryRouter>
  )
}

describe('PLAT.6 — el nivel de la cascada', () => {
  it('should_let_a_superadmin_choose_the_platform_level', () => {
    renderPage()

    const selector = screen.getByLabelText(/nivel/i) as HTMLSelectElement
    const valores = [...selector.querySelectorAll('option')].map((o) => o.getAttribute('value'))
    expect(valores).toEqual(['plataforma', 'organizacion', 'chatbot'])
  })

  it('should_not_offer_the_platform_level_to_an_admin', () => {
    // Un tema de plataforma lo hereda todo el mundo: mismo criterio que `create_theme`.
    conRol('admin')
    renderPage()

    const selector = screen.getByLabelText(/nivel/i) as HTMLSelectElement
    const valores = [...selector.querySelectorAll('option')].map((o) => o.getAttribute('value'))
    expect(valores).not.toContain('plataforma')
  })
})

describe('PLAT.6 — los campos salen del contrato', () => {
  it('should_build_the_colour_controls_from_the_theme_it_received', () => {
    renderPage()

    // La plataforma define dos colores: se pintan dos, no una lista escrita a mano.
    expect(screen.getByTestId('color-primary')).toBeDefined()
    expect(screen.getByTestId('color-background')).toBeDefined()
  })

  it('should_use_a_colour_picker_and_not_a_json_textarea', () => {
    // El sustituto del `<textarea>` de JSON tiene que ser un control de verdad.
    renderPage()

    expect(screen.getByTestId('color-primary').getAttribute('type')).toBe('color')
    expect(screen.queryByRole('textbox', { name: /json/i })).toBeNull()
  })

  it('should_grow_with_the_contract', () => {
    vi.mocked(useGetThemesApiV1HubThemesGet).mockReturnValue({
      data: [
        {
          ...TEMA_PLATAFORMA,
          config: { ...TEMA_PLATAFORMA.config, colors: { primary: '#000', nuevoColor: '#fff' } },
        },
      ],
      isLoading: false,
    } as never)
    renderPage()

    expect(screen.getByTestId('color-nuevoColor')).toBeDefined()
  })
})

describe('PLAT.6 — la cascada se ve', () => {
  it('should_say_where_an_undefined_field_is_inherited_from', () => {
    // El tema de la organización solo define `primary`: `background` viene de la plataforma.
    renderPage()
    fireEvent.change(screen.getByLabelText(/nivel/i), { target: { value: 'organizacion' } })

    const fila = screen.getByTestId('campo-background')
    // El **nivel**, no el nombre de la fila del tema: en el navegador se leía «Heredado de
    // Tema», que no le dice nada a quien configura.
    expect(fila.textContent).toMatch(/heredado de plataforma/i)
  })

  it('should_not_mark_an_overridden_field_as_inherited', () => {
    renderPage()
    fireEvent.change(screen.getByLabelText(/nivel/i), { target: { value: 'organizacion' } })

    const fila = screen.getByTestId('campo-primary')
    expect(fila.textContent).not.toMatch(/heredado/i)
  })

  it('should_not_freeze_inherited_values_when_saving', () => {
    // **El test del prompt.** Si al guardar se mandara la paleta heredada, el hijo se quedaría
    // con valores propios que ya no siguen al padre — y nadie se enteraría.
    renderPage()
    fireEvent.change(screen.getByLabelText(/nivel/i), { target: { value: 'organizacion' } })
    fireEvent.click(screen.getByRole('button', { name: /guardar/i }))

    const [[argumentos]] = guardar.mock.calls
    expect(Object.keys(argumentos.data.config.colors)).toEqual(['primary'])
  })
})

describe('PLAT.6 — el logotipo y sus límites', () => {
  it('should_state_the_real_limits_including_why_no_svg', () => {
    renderPage()

    const texto = document.body.textContent ?? ''
    expect(texto).toMatch(/PNG/i)
    expect(texto).toMatch(/1 MB/i)
    expect(texto).toMatch(/SVG/i)
  })

  it('should_only_accept_the_formats_the_server_accepts', () => {
    renderPage()

    const entrada = screen.getByTestId('logo-file') as HTMLInputElement
    expect(entrada.accept).toBe('image/png,image/jpeg')
  })
})

describe('PLAT.6 — la vista previa', () => {
  it('should_preview_the_mark_over_the_real_sidebar_background', () => {
    // Es el motivo por el que la prueba manual necesitaba a una persona: un logotipo con
    // letras oscuras pasa todos los tests y se lee fatal sobre el azul del panel.
    renderPage()

    const previa = screen.getByTestId('previa-de-la-marca')
    expect(previa.className).toMatch(/bg-sidebar/)
  })

  it('should_show_the_alt_text_when_there_is_no_logo_yet', () => {
    renderPage()

    expect(within(screen.getByTestId('previa-de-la-marca')).getByText(/Gov Gen AI/i)).toBeDefined()
  })
})

describe('PLAT.6 — el fichero que el servidor iba a rechazar', () => {
  function elegir(nombre: string, tipo: string, bytes: number) {
    const fichero = new File([new Uint8Array(bytes)], nombre, { type: tipo })
    fireEvent.change(screen.getByTestId('logo-file'), { target: { files: [fichero] } })
  }

  it('should_refuse_an_svg_with_a_readable_reason', () => {
    // El `accept` filtra el dialogo del sistema, no lo que llega: se puede arrastrar el
    // fichero o elegir «todos los archivos». Sin este corte, el servidor responde 400 y la
    // pantalla no dice por que.
    renderPage()
    elegir('logo.svg', 'image/svg+xml', 10)

    expect(subirLogo).not.toHaveBeenCalled()
    expect(screen.getByRole('alert').textContent).toMatch(/SVG/i)
  })

  it('should_refuse_a_file_over_one_megabyte_with_a_readable_reason', () => {
    renderPage()
    elegir('enorme.png', 'image/png', 1024 * 1024 + 1)

    expect(subirLogo).not.toHaveBeenCalled()
    expect(screen.getByRole('alert').textContent).toMatch(/1 MB/i)
  })

  it('should_let_a_valid_png_through', () => {
    renderPage()
    elegir('logo.png', 'image/png', 2048)

    expect(subirLogo).toHaveBeenCalled()
    expect(screen.queryByRole('alert')).toBeNull()
  })
})

describe('PLAT.6 — la tipografia se elige, no se teclea', () => {
  it('should_suggest_known_families_without_locking_out_the_stored_one', () => {
    // Sugerir sin encerrar: un tema con una familia que no este en la lista tiene que seguir
    // mostrando la suya, no perderla porque no figure en el catalogo.
    renderPage()

    const entrada = screen.getByTestId('tipo-fontFamily') as HTMLInputElement
    expect(entrada.getAttribute('list')).toBeTruthy()
    expect(entrada.value).toBe("'Inter', sans-serif")
    const lista = document.getElementById(entrada.getAttribute('list') as string)
    expect(lista?.querySelectorAll('option').length).toBeGreaterThan(1)
  })
})

describe('PLAT.6 — accesibilidad', () => {
  it('should_pass_the_projects_axe_gate', async () => {
    const { container } = renderPage()

    await expectNoA11yViolations(container)
  })
})

describe('PLAT.6 — la entrada desde la pantalla de organizaciones', () => {
  it('should_open_on_the_organisation_level_when_asked_for_one', () => {
    // El enlace de PLAT.3 trae la organización elegida: preguntarla otra vez en un selector
    // sería rehacer trabajo ya hecho.
    renderPage('/plataforma/identidad-visual?organizacion=org-1')

    expect((screen.getByLabelText(/nivel/i) as HTMLSelectElement).value).toBe('organizacion')
    expect((screen.getByLabelText(/organizaci/i) as HTMLSelectElement).value).toBe('org-1')
  })
})

describe('PLAT.6 — la instalacion recien levantada', () => {
  it('should_still_offer_every_field_when_no_theme_exists_at_all', () => {
    // Lo destapó la verificación en navegador: sin tema propio ni padre, la pantalla iteraba
    // un conjunto vacío y no ofrecía ni un campo — justo en el estado en el que alguien entra
    // por primera vez a poner los colores de su institución.
    vi.mocked(useGetThemesApiV1HubThemesGet).mockReturnValue({ data: [], isLoading: false } as never)
    renderPage()

    expect(screen.getByTestId('color-primary')).toBeDefined()
    expect(screen.getByTestId('color-border')).toBeDefined()
    expect((screen.getByTestId('color-primary') as HTMLInputElement).value).toBe('#0066cc')
  })

  it('should_not_claim_a_default_is_inherited_from_a_level', () => {
    // Decir «heredado de Plataforma» cuando no hay tema de plataforma seria mentirle a quien
    // configura: ese valor viene del contrato, no de un nivel de arriba.
    vi.mocked(useGetThemesApiV1HubThemesGet).mockReturnValue({ data: [], isLoading: false } as never)
    renderPage()

    expect(screen.getByTestId('campo-border').textContent).not.toMatch(/heredado/i)
  })
})

/**
 * REV.4 — el selector de logotipo tenía que poder pulsarse.
 *
 * En una instalación recién levantada el nivel de plataforma no tiene tema propio, y el
 * `<input type="file">` salía con `disabled`: «Tria un fitxer» en gris, inerte, con la
 * explicación en un párrafo de 12 px debajo que nadie lee. Además el texto del botón lo pone
 * el navegador —de ahí que saliera en valenciano con el panel en castellano— y va pegado al
 * «no s'ha triat cap fitxer» en la misma línea.
 */
describe('REV.4 — elegir el fichero del logotipo', () => {
  function elegir(nombre: string, tipo: string, bytes: number) {
    const fichero = new File([new Uint8Array(bytes)], nombre, { type: tipo })
    fireEvent.change(screen.getByTestId('logo-file'), { target: { files: [fichero] } })
  }

  it('should_offer_a_real_button_and_hide_the_native_control', () => {
    // El control nativo no se puede estilar ni traducir: se oculta a la vista —no a los
    // lectores de pantalla— y quien pulsa lo hace sobre una etiqueta con aspecto de botón.
    renderPage()

    const entrada = screen.getByTestId('logo-file') as HTMLInputElement
    expect(entrada.className).toMatch(/sr-only/)

    const boton = screen.getByTestId('logo-boton')
    expect(boton.tagName).toBe('LABEL')
    expect(boton.getAttribute('for')).toBe(entrada.id)
  })

  it('should_never_be_disabled', () => {
    // Sin tema propio en este nivel tampoco: ahora se crea al vuelo.
    vi.mocked(useGetThemesApiV1HubThemesGet).mockReturnValue({
      data: [],
      isLoading: false,
    } as never)
    renderPage()

    expect((screen.getByTestId('logo-file') as HTMLInputElement).disabled).toBe(false)
  })

  it('should_show_the_chosen_file_name_on_its_own_line', () => {
    renderPage()
    elegir('escut.png', 'image/png', 2048)

    expect(screen.getByTestId('logo-nombre').textContent).toMatch(/escut\.png/)
  })

  it('should_create_the_theme_on_the_fly_when_the_level_has_none', () => {
    // **El test del prompt.** Antes esto era un callejón: para subir el logotipo hacía falta
    // un tema, y para tener tema había que guardar colores que quizá nadie quería tocar.
    vi.mocked(useGetThemesApiV1HubThemesGet).mockReturnValue({
      data: [],
      isLoading: false,
    } as never)
    renderPage()
    elegir('escut.png', 'image/png', 2048)

    expect(crear).toHaveBeenCalled()
    expect(subirLogo).not.toHaveBeenCalled()

    // Y cuando el servidor devuelve el tema recién creado, se sube sobre él.
    const alCrear = crear.mock.calls[0][1] as { onSuccess: (t: { id: string }) => void }
    alCrear.onSuccess({ id: 'tema-nuevo' })

    expect(subirLogo).toHaveBeenCalledWith(
      expect.objectContaining({ themeId: 'tema-nuevo' }),
      expect.anything()
    )
  })

  it('should_upload_straight_away_when_the_level_already_has_a_theme', () => {
    renderPage()
    elegir('escut.png', 'image/png', 2048)

    expect(crear).not.toHaveBeenCalled()
    expect(subirLogo).toHaveBeenCalledWith(
      expect.objectContaining({ themeId: 'tema-plataforma' }),
      expect.anything()
    )
  })
})

describe('REV.9 — guardar un color se ve sin recargar', () => {
  it('should_invalidate_the_resolved_theme_and_not_only_the_list', async () => {
    // Lo destapó la verificación en navegador: se guardaba el color, la fila quedaba bien en la
    // base de datos y el panel seguía igual. Los colores del panel salen de
    // `/themes/resolved`, que es OTRA consulta, y se quedaba en caché — había que recargar a
    // mano, y eso se lee como «no se ha guardado».
    const { QueryClient, QueryClientProvider } = await import('@tanstack/react-query')
    const cliente = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const invalidadas: unknown[] = []
    cliente.invalidateQueries = ((opciones: { queryKey: unknown }) => {
      invalidadas.push(opciones.queryKey)
      return Promise.resolve()
    }) as never

    const { MemoryRouter } = await import('react-router-dom')
    render(
      <QueryClientProvider client={cliente}>
        <MemoryRouter>
          <IdentidadVisualPage />
        </MemoryRouter>
      </QueryClientProvider>,
    )

    fireEvent.change(screen.getByTestId('color-primary'), { target: { value: '#123456' } })
    fireEvent.click(screen.getByRole('button', { name: /guardar/i }))

    const alGuardar = guardar.mock.calls[0][1] as { onSuccess: () => void }
    alGuardar.onSuccess()

    expect(invalidadas).toContainEqual(['temas'])
    expect(invalidadas).toContainEqual(['tema-resuelto'])
  })
})
