import { describe, it, expect, beforeAll, beforeEach, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import i18n from '@/shared/i18n'
import { LLMDraftPreviewPage } from '../pages/LLMDraftPreviewPage'
import {
  useProposeLlmDraft,
  useValidateLlmDraft,
  useApproveAsTemplate,
  useApproveAsWorkspace,
  useDescribeSampleFile,
} from '@/shared/api/generated/redaccion-llm-drafts/redaccion-llm-drafts'

/**
 * INF.4 — el fichero de datos se ofrece antes del prompt, y lo que se va a enviar se ve.
 *
 * `propose` recibía solo el texto, así que el modelo no conocía las columnas y las adivinaba.
 * El legacy sí mandaba la estructura, anonimizada (`etl_factory`).
 */
vi.mock('@/shared/api/generated/redaccion-llm-drafts/redaccion-llm-drafts', () => ({
  useProposeLlmDraft: vi.fn(),
  useValidateLlmDraft: vi.fn(),
  useApproveAsTemplate: vi.fn(),
  useApproveAsWorkspace: vi.fn(),
  useDescribeSampleFile: vi.fn(),
}))
vi.mock('@/shared/auth', () => ({
  useAuth: () => ({ user: { role: 'superadmin', email: 'x@uji.es', user_id: '1' } }),
}))
// #277 — la pantalla pregunta capacidades a `/auth/me`; se simulan las del rol del test.
vi.mock('@/shared/auth/useCapacidad', async () =>
  (await import('@/test-utils/capacidades')).dobleDeUseCapacidad(() => 'superadmin'),
)

const MUESTRA = {
  nombre_del_fichero: 'saldos.csv',
  columnas: ['ccc', 'periodo', 'saldo'],
  tipos: { ccc: 'object', periodo: 'object', saldo: 'object' },
  filas_totales: 412,
  primeras_filas: [{ ccc: '0001', periodo: '202601', saldo: '1.234,56' }],
}

const proponer = vi.fn()
const describir = vi.fn()

beforeAll(async () => {
  await i18n.changeLanguage('es')
})

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(useProposeLlmDraft).mockReturnValue({ mutate: proponer, isPending: false } as never)
  vi.mocked(useValidateLlmDraft).mockReturnValue({ mutate: vi.fn(), isPending: false } as never)
  vi.mocked(useApproveAsTemplate).mockReturnValue({ mutate: vi.fn(), isPending: false } as never)
  vi.mocked(useApproveAsWorkspace).mockReturnValue({ mutate: vi.fn(), isPending: false } as never)
  vi.mocked(useDescribeSampleFile).mockReturnValue({ mutate: describir, isPending: false } as never)
})

/**
 * Con `MemoryRouter` desde el issue #87: la pagina llama a `useNavigate`, que solo funciona
 * dentro de un Router. Sin rutas de destino, porque aqui no se comprueba la navegacion — eso lo
 * hace `Issue87AprobarConfirmaYNavega.test.tsx`—: hace falta solo el contexto para que monte.
 */
function pintar() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <LLMDraftPreviewPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('INF.4 — la propuesta ve los datos', () => {
  it('should_offer_the_data_file_before_the_prompt', () => {
    pintar()
    expect(screen.getByTestId('input-muestra')).toBeDefined()
  })

  /**
   * Encontrado al capturar la pantalla para la guia: el fichero de muestra que INF.4 anadio
   * aqui era un `<input type="file">` desnudo, o sea el navegador pintando su propio control
   * **en su idioma** —«Tria un fitxer» en una pantalla en castellano—. Es el mismo defecto que
   * INF.8 arreglo en la pantalla del informe, reintroducido en otra pantalla.
   */
  it('should_not_leave_the_browser_file_control_bare', () => {
    pintar()

    // Hay zona propia, con su texto.
    const zona = screen.getByTestId('zona-muestra')
    expect(zona.textContent).toMatch(/arrastra|pulsa/i)
    // Y el input sigue existiendo y alcanzable: oculto a la vista, no para el teclado.
    const entrada = screen.getByTestId('input-muestra')
    expect(entrada.className).toContain('sr-only')
    expect(zona.getAttribute('for')).toBe(entrada.getAttribute('id'))
  })

  it('should_send_the_file_to_the_server_to_be_summarised_and_anonymised', async () => {
    pintar()

    const fichero = new File(['ccc,saldo\n1,2\n'], 'saldos.csv', { type: 'text/csv' })
    fireEvent.change(screen.getByTestId('input-muestra'), { target: { files: [fichero] } })

    await waitFor(() =>
      expect(describir).toHaveBeenCalledWith(
        expect.objectContaining({ data: { file: fichero } }),
        expect.anything(),
      ),
    )
  })

  it('should_show_what_is_going_to_be_sent', async () => {
    describir.mockImplementation((_v: unknown, o: { onSuccess?: (m: unknown) => void }) =>
      o?.onSuccess?.(MUESTRA),
    )
    pintar()

    fireEvent.change(screen.getByTestId('input-muestra'), {
      target: { files: [new File(['x'], 'saldos.csv')] },
    })

    const resumen = await screen.findByTestId('resumen-de-muestra')
    expect(resumen.textContent).toMatch(/saldos\.csv/)
    expect(resumen.textContent).toMatch(/412/)
    expect(resumen.textContent).toMatch(/ccc/)
  })

  it('should_include_the_sample_in_the_proposal_request', async () => {
    describir.mockImplementation((_v: unknown, o: { onSuccess?: (m: unknown) => void }) =>
      o?.onSuccess?.(MUESTRA),
    )
    pintar()

    fireEvent.change(screen.getByTestId('input-muestra'), {
      target: { files: [new File(['x'], 'saldos.csv')] },
    })
    await screen.findByTestId('resumen-de-muestra')

    fireEvent.change(screen.getByTestId('input-prompt'), {
      target: { value: 'Informe de tesoreria por ano y mes' },
    })
    fireEvent.click(screen.getByTestId('btn-propose'))

    await waitFor(() =>
      expect(proponer).toHaveBeenCalledWith(
        expect.objectContaining({ data: expect.objectContaining({ muestra: MUESTRA }) }),
      ),
    )
  })

  it('should_still_propose_without_a_file', async () => {
    pintar()

    fireEvent.change(screen.getByTestId('input-prompt'), { target: { value: 'Un informe' } })
    fireEvent.click(screen.getByTestId('btn-propose'))

    await waitFor(() =>
      expect(proponer).toHaveBeenCalledWith(
        expect.objectContaining({ data: expect.objectContaining({ muestra: null }) }),
      ),
    )
  })
})

/**
 * INF.6 — una propuesta inválida se arregla sin volver a llamar al modelo.
 *
 * Con la propuesta rechazada, «Aprobar y crear» quedaba deshabilitado y la única salida era
 * reescribir el prompt entero. El usuario se quedó ahí el 2026-08-20: dos líneas rojas con
 * `blocks[b6].data_block_refs` y ningún sitio donde tocar.
 */
describe('INF.6 — corregir la propuesta, no rehacerla', () => {
  const PROPUESTA_MAL = {
    proposed_profile: 'GENERIC_REPORT',
    proposed_sections: [{ id: 's1', title: 'Tesoreria', order: 1, block_ids: ['b3', 'b4', 'b6'] }],
    proposed_blocks: [
      { kind: 'DETERMINISTIC_DATA', id: 'b3', title: 'Saldos', order: 1, source_pipeline: 'csv' },
      { kind: 'TABLE', id: 'b4', title: 'Saldos por mes', order: 2, data_block_ref: 'b3' },
      {
        kind: 'AI_SUMMARY', id: 'b6', title: 'Valoracion', order: 3,
        ai_prompt_template_id: 'generic_report_v1', review_policy_id: 'required',
        data_block_refs: ['b4'],
      },
    ],
    proposed_inputs: { required_slots: [], optional_slots: [] },
    model_used: 'gemini', prompt_version: 'llm_spec_v2',
  }

  const ERROR = {
    field: 'blocks[b6].data_block_refs',
    message: "AI_SUMMARY block 'b6' valora 'b4', que no produce datos ('TABLE')",
  }

  function pintarConPropuestaInvalida() {
    vi.mocked(useProposeLlmDraft).mockReturnValue({
      mutate: proponer, data: PROPUESTA_MAL, isPending: false,
    } as never)
    vi.mocked(useValidateLlmDraft).mockReturnValue({
      mutate: vi.fn(), data: { ok: false, errors: [ERROR] }, isPending: false,
    } as never)
    return pintar()
  }

  it('should_show_the_error_next_to_its_block', async () => {
    pintarConPropuestaInvalida()

    const bloque = await screen.findByTestId('bloque-propuesto-b6')
    expect(bloque.textContent).toMatch(/valoracion/i)
    expect(screen.getByTestId('error-b6-0')).toBeDefined()
  })

  it('should_explain_the_error_in_plain_words_not_with_the_field_path', async () => {
    pintarConPropuestaInvalida()

    const aviso = await screen.findByTestId('error-b6-0')
    expect(aviso.textContent).toMatch(/tabla|grafico/i)
    expect(aviso.textContent).not.toMatch(/data_block_refs/)
  })

  it('should_offer_the_mechanical_fix', async () => {
    pintarConPropuestaInvalida()
    expect(await screen.findByTestId('btn-corregir-b6')).toBeDefined()
  })

  it('should_revalidate_after_the_fix_without_asking_the_model_again', async () => {
    const revalidar = vi.fn()
    vi.mocked(useProposeLlmDraft).mockReturnValue({
      mutate: proponer, data: PROPUESTA_MAL, isPending: false,
    } as never)
    vi.mocked(useValidateLlmDraft).mockReturnValue({
      mutate: revalidar, data: { ok: false, errors: [ERROR] }, isPending: false,
    } as never)
    pintar()

    fireEvent.click(await screen.findByTestId('btn-corregir-b6'))

    await waitFor(() =>
      expect(revalidar).toHaveBeenCalledWith(
        expect.objectContaining({
          data: expect.objectContaining({
            proposed_blocks: expect.arrayContaining([
              expect.objectContaining({ id: 'b6', data_block_refs: ['b3'] }),
            ]),
          }),
        }),
      ),
    )
    // Y sin volver a pedir la propuesta al modelo.
    expect(proponer).not.toHaveBeenCalled()
  })

  it('should_say_it_is_asking_the_model_while_it_waits', async () => {
    vi.mocked(useProposeLlmDraft).mockReturnValue({
      mutate: proponer, data: undefined, isPending: true,
    } as never)
    pintar()

    expect(await screen.findByTestId('proponiendo')).toBeDefined()
  })
})

/**
 * INF.9 — plantilla o informe suelto, explicado al elegir.
 *
 * Del usuario: «Tampoco sabe la diferencia entre workspace y plantilla. Por el principio de
 * determinista first debería sugerirse plantilla por defecto si se va a repetir el informe.»
 * La pantalla ofrecía «Crear workspace» y «Crear plantilla» como equivalentes, con vocabulario
 * interno y sin decir que la elección importa.
 */
describe('INF.9 — la elección se explica', () => {
  function pintarConPropuesta() {
    vi.mocked(useProposeLlmDraft).mockReturnValue({
      mutate: proponer,
      data: {
        proposed_profile: 'GENERIC_REPORT', proposed_sections: [], proposed_blocks: [],
        proposed_inputs: { required_slots: [], optional_slots: [] },
        model_used: 'gemini', prompt_version: 'v2',
      },
      isPending: false,
    } as never)
    vi.mocked(useValidateLlmDraft).mockReturnValue({
      mutate: vi.fn(), data: { ok: true, errors: [] }, isPending: false,
    } as never)
    return pintar()
  }

  it('should_not_use_the_word_workspace_in_the_choice', async () => {
    pintarConPropuesta()

    const eleccion = await screen.findByTestId('eleccion-de-modo')
    expect(eleccion.textContent?.toLowerCase()).not.toContain('workspace')
  })

  it('should_mark_the_template_as_the_recommended_option', async () => {
    pintarConPropuesta()

    const plantilla = await screen.findByTestId('mode-template')
    expect(plantilla.textContent?.toLowerCase()).toMatch(/recomendado/)
  })

  it('should_say_why_the_template_is_recommended', async () => {
    pintarConPropuesta()

    const ayuda = await screen.findByTestId('ayuda-del-modo')
    // La razón concreta: se ejecuta sin volver a consultar a la IA.
    expect(ayuda.textContent?.toLowerCase()).toMatch(/repite|sin volver a consultar/)
  })

  it('should_explain_the_one_off_option_too', async () => {
    pintarConPropuesta()

    fireEvent.click(await screen.findByTestId('mode-workspace'))

    await waitFor(() =>
      expect(screen.getByTestId('ayuda-del-modo').textContent?.toLowerCase()).toMatch(/una vez/),
    )
  })
})
