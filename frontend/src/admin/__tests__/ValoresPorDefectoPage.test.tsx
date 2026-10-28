import { readFileSync } from 'node:fs'
import { describe, it, expect, beforeEach, beforeAll, vi } from 'vitest'
import { render, screen, within, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import i18n from '@/shared/i18n'
import { ValoresPorDefectoPage } from '../pages/ValoresPorDefectoPage'
import { CONTROLES } from '../pages/controlesDeValoresPorDefecto'
import {
  useListOrganizacionesApiV1HubOrganizacionesGet,
  useGetValoresPorDefectoApiV1HubOrganizacionesOrganizacionIdValoresPorDefectoGet as useValores,
  useUpdateValoresPorDefectoApiV1HubOrganizacionesOrganizacionIdValoresPorDefectoPatch as useGuardar,
} from '@/shared/api/generated/hub-organizaciones/hub-organizaciones'

/**
 * PLAT.3 — los valores por defecto de RAG, en su módulo.
 *
 * Vivían dentro de la pantalla de Organizaciones, y por eso esa pantalla acabó bajo Chatbots: la
 * mayoría de sus campos eran de Chatbots. Lo que esta pantalla tiene que hacer bien, además de
 * mostrarlos, es **distinguir un valor propio de uno heredado** y permitir volver a heredar —
 * que hasta PLAT.3 era imposible por API, porque el `PATCH` descartaba el `null` explícito.
 */
// PLG.3 — el catalogo de perfiles, modos y estrategias de ESTA instalacion. Antes la pagina
// llevaba las listas escritas dentro; ahora las pide, asi que el test tiene que servirlas.
vi.mock('@/shared/api/generated/hub-chatbots/hub-chatbots', () => ({
  useOpcionesDeGrafoApiV1HubChatbotsOpcionesDeGrafoGet: () => ({
    data: {
      perfiles: [
        { nombre: 'PUBLIC_KB_RICH', configurable: true },
        { nombre: 'PUBLIC_PORTAL_ROUTER', configurable: false },
      ],
      modos: [{ nombre: 'RAG' }, { nombre: 'MD_LONG_CONTEXT' }, { nombre: 'MD_AGENT_SELECTOR' }],
      estrategias: {
        retrieval: [{ nombre: 'single_source' }],
        merge: [{ nombre: 'passthrough' }],
        template: [{ nombre: 'generic' }],
        language: [{ nombre: 'default' }],
      },
      ejes: ['retrieval', 'merge', 'template', 'language'],
    },
  }),
}))

vi.mock('@/shared/api/generated/hub-organizaciones/hub-organizaciones', () => ({
  useListOrganizacionesApiV1HubOrganizacionesGet: vi.fn(),
  useGetValoresPorDefectoApiV1HubOrganizacionesOrganizacionIdValoresPorDefectoGet: vi.fn(),
  useUpdateValoresPorDefectoApiV1HubOrganizacionesOrganizacionIdValoresPorDefectoPatch: vi.fn(),
  getGetValoresPorDefectoApiV1HubOrganizacionesOrganizacionIdValoresPorDefectoGetQueryKey: () => [
    'valores',
  ],
}))

const ORGS = [
  { id: 'org-1', name: 'Universitat Jaume I' },
  { id: 'org-2', name: 'Diputación de Castellón' },
]

const VALORES = {
  default_public_graph_profile: 'PUBLIC_KB_RICH',
  default_retrieval_mode: 'RAG',
  default_reranker_enabled: false,
  // Con valor propio: se puede volver a heredar.
  default_chunk_size: 500,
  // Heredado ya: no se ofrece volver a heredar lo que ya hereda.
  default_chunk_overlap: null,
  default_context_token_budget: null,
}

const guardar = vi.fn()

beforeAll(async () => {
  await i18n.changeLanguage('es')
})

beforeEach(() => {
  // La organizacion elegida se recuerda en localStorage (REV.10): sin limpiarla, la eleccion
  // de un test se filtra al siguiente y el fallo aparece lejos de su causa.
  localStorage.clear()
  guardar.mockClear()
  vi.mocked(useListOrganizacionesApiV1HubOrganizacionesGet).mockReturnValue({
    data: ORGS,
  } as never)
  vi.mocked(useValores).mockReturnValue({ data: VALORES, isLoading: false } as never)
  vi.mocked(useGuardar).mockReturnValue({ mutate: guardar, isPending: false } as never)
})

function renderPage() {
  const cliente = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={cliente}>
      <ValoresPorDefectoPage />
    </QueryClientProvider>
  )
}

describe('PLAT.3 — la pantalla de valores por defecto', () => {
  it('should_let_you_pick_the_organisation', () => {
    // Es configuración del módulo aplicada a una organización, no identidad de una.
    renderPage()

    const selector = screen.getByLabelText(/organización/i)
    expect([...selector.querySelectorAll('option')].map((o) => o.textContent)).toEqual([
      'Universitat Jaume I',
      'Diputación de Castellón',
    ])
  })

  it('should_render_every_field_the_server_sends', () => {
    // Iterando la respuesta: si el contrato crece, la pantalla crece.
    renderPage()

    expect(screen.getByTestId('default_public_graph_profile')).toBeDefined()
    expect(screen.getByTestId('default_chunk_size')).toBeDefined()
  })

  it('should_say_inherited_instead_of_leaving_it_blank', () => {
    // `null` aquí es una decisión, no un dato que falte.
    renderPage()

    expect(screen.getByTestId('default_chunk_overlap').textContent).toMatch(/heredado/i)
  })

  it('should_offer_going_back_to_inheriting_only_where_it_applies', () => {
    renderPage()

    const conValorPropio = screen.getByTestId('default_chunk_size')
    expect(within(conValorPropio).getByRole('button', { name: /heredar/i })).toBeDefined()

    // Ya heredado: no hay nada que devolver. Se busca el botón POR SU NOMBRE porque desde
    // REV.2 una fila heredada sí tiene otro botón —el de tomar valor propio—, y un
    // `queryByRole('button')` a secas confundiría las dos cosas.
    expect(
      within(screen.getByTestId('default_chunk_overlap')).queryByRole('button', {
        name: /volver a heredar/i,
      })
    ).toBeNull()

    // No heredable: el reranker no tiene defecto de plataforma que heredar.
    expect(
      within(screen.getByTestId('default_reranker_enabled')).queryByRole('button', {
        name: /volver a heredar/i,
      })
    ).toBeNull()
  })

  it('should_send_an_explicit_null_when_going_back_to_inheriting', () => {
    // **El test del prompt**: el `null` explícito es lo que `exclude_none` descartaba.
    renderPage()

    const fila = screen.getByTestId('default_chunk_size')
    fireEvent.click(within(fila).getByRole('button', { name: /heredar/i }))

    expect(guardar).toHaveBeenCalledWith(
      { organizacionId: 'org-1', data: { default_chunk_size: null } },
      expect.anything()
    )
  })

  it('should_show_a_translated_label_and_not_the_field_name', () => {
    // Ensenar `default_public_graph_profile` a una persona es ensenarle el contrato.
    renderPage()

    expect(screen.getByTestId('default_public_graph_profile').textContent).toMatch(
      /Perfil de grafo/i
    )
  })

  it('should_fall_back_to_the_field_name_for_a_field_with_no_label', () => {
    // Si el contrato crece, la fila aparece igual en vez de quedarse vacia.
    vi.mocked(useValores).mockReturnValue({
      data: { default_campo_futuro: 7 },
      isLoading: false,
    } as never)
    renderPage()

    expect(screen.getByTestId('default_campo_futuro').textContent).toMatch(
      /default_campo_futuro/
    )
  })

  it('should_say_this_is_not_tenant_identity', () => {
    renderPage()

    expect(document.body.textContent).toMatch(/no es identidad|Chatbots/i)
  })
})

/**
 * REV.2 — los valores se pueden cambiar.
 *
 * La pantalla los pintaba con `String(valor)` y el único botón era «volver a heredar»: se veía
 * la configuración y no se podía tocar, así que para cambiar el tamaño de fragmento de una
 * organización había que ir por API. El `PATCH` ya lo aceptaba todo desde PLAT.3; lo que
 * faltaba era el control.
 */
describe('REV.2 — editar los valores por defecto', () => {
  it('should_render_a_number_input_for_a_numeric_field', () => {
    renderPage()

    const campo = within(screen.getByTestId('default_chunk_size')).getByRole('spinbutton')
    expect((campo as HTMLInputElement).value).toBe('500')
  })

  it('should_render_a_checkbox_for_a_boolean_field', () => {
    renderPage()

    const campo = within(screen.getByTestId('default_reranker_enabled')).getByRole('checkbox')
    expect((campo as HTMLInputElement).checked).toBe(false)
  })

  it('should_send_a_number_and_not_a_string', () => {
    // **El test del prompt.** `<input>` devuelve siempre texto; mandar "800" donde el contrato
    // declara un entero es un 422 que sólo aparece en tiempo de ejecución.
    renderPage()

    const campo = within(screen.getByTestId('default_chunk_size')).getByRole('spinbutton')
    fireEvent.change(campo, { target: { value: '800' } })
    fireEvent.blur(campo)

    expect(guardar).toHaveBeenCalledWith(
      { organizacionId: 'org-1', data: { default_chunk_size: 800 } },
      expect.anything()
    )
  })

  it('should_send_a_boolean_for_a_checkbox', () => {
    renderPage()

    fireEvent.click(within(screen.getByTestId('default_reranker_enabled')).getByRole('checkbox'))

    expect(guardar).toHaveBeenCalledWith(
      { organizacionId: 'org-1', data: { default_reranker_enabled: true } },
      expect.anything()
    )
  })

  it('should_not_save_a_value_that_has_not_changed', () => {
    // Salir de un campo sin tocarlo no es una edición, y guardarlo escribiría un valor propio
    // sobre un campo que sólo estaba de paso.
    renderPage()

    const campo = within(screen.getByTestId('default_chunk_size')).getByRole('spinbutton')
    fireEvent.blur(campo)

    expect(guardar).not.toHaveBeenCalled()
  })

  it('should_let_an_inherited_field_take_its_own_value', () => {
    // Heredado no puede ser un callejón sin salida: se entra y se sale.
    renderPage()

    const fila = screen.getByTestId('default_chunk_overlap')
    expect(within(fila).queryByRole('spinbutton')).toBeNull()

    fireEvent.click(within(fila).getByRole('button', { name: /valor propio/i }))

    expect(within(fila).getByRole('spinbutton')).toBeDefined()
  })

  it('should_offer_the_known_options_for_an_enumerated_field', () => {
    // Sugerencias en un `datalist`, no un `<select>`: el contrato declara estos campos como
    // `string` libre, y un desplegable perdería en silencio un valor que no conociera. Es el
    // mismo criterio que la lista de tipografías de Identidad visual.
    renderPage()

    // `combobox` y no `textbox`: un `<input type="text">` con `list` expone rol combobox
    // (HTML-AAM). Que el rol cambie es justo la señal de que hay sugerencias asociadas.
    const campo = within(screen.getByTestId('default_retrieval_mode')).getByRole('combobox')
    const lista = campo.getAttribute('list')
    expect(lista).toBeTruthy()
    const opciones = [...document.querySelectorAll(`#${lista} option`)].map(o =>
      o.getAttribute('value')
    )
    expect(opciones).toContain('MD_LONG_CONTEXT')
  })

  it('should_know_a_control_for_every_field_of_the_contract', () => {
    // El mapa de controles es la única lista de campos que queda escrita en el React, así que
    // se comprueba contra el contrato generado: si el servidor añade un campo y nadie le da
    // control, esto se pone rojo en vez de pintar la fila sin poder editarla.
    // Ruta desde la raíz del frontend, que es el `cwd` de vitest. Con `import.meta.url` el
    // entorno jsdom da una URL http y `readFileSync` la rechaza.
    const contrato = readFileSync(
      'src/shared/api/generated/model/valoresPorDefectoRead.ts',
      'utf-8'
    )
    const campos = [...contrato.matchAll(/^\s{2}(\w+)\??:/gm)].map(m => m[1])

    expect(campos.length).toBeGreaterThan(10)
    expect(campos.filter(c => !(c in CONTROLES))).toEqual([])
  })
})
