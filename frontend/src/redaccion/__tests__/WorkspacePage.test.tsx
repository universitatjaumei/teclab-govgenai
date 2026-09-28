import { describe, it, expect, beforeAll, beforeEach, vi } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import i18n from '@/shared/i18n'
import { WorkspacePage } from '../pages/WorkspacePage'
import {
  useGetWorkspaceById,
  useGetTemplateUiContractApiV1HubRedaccionTemplateVersionsVersionIdUiContractGet as useGetTemplateUiContract,
} from '@/shared/api/generated/hub-redaccion/hub-redaccion'
import {
  useRunWorkspace,
  useSetWorkspaceFields,
  useUploadWorkspaceInput,
} from '@/shared/api/generated/redaccion-workspaces/redaccion-workspaces'

/**
 * VER.4 — la pantalla donde se trabaja un informe.
 *
 * El módulo sabía crear workspaces y **no tenía dónde abrirlos**: `WorkspaceEditor`,
 * `DynamicUploadSlots`, `AIBlockReviewPanel` y `DataQualityPanel` existían desde 9R sin que
 * ninguna ruta los montara. `App.tsx` solo enrutaba la vista de impresión.
 *
 * El formulario de entrada se construye desde el `ui_contract` de la versión de plantilla,
 * no desde campos fijos: es la regla maestra nº1 del proyecto.
 */
vi.mock('@/shared/api/generated/hub-redaccion/hub-redaccion', () => ({
  useGetWorkspaceById: vi.fn(),
  useGetTemplateUiContractApiV1HubRedaccionTemplateVersionsVersionIdUiContractGet: vi.fn(),
  getGetWorkspaceByIdQueryKey: vi.fn(() => ['workspace']),
  // Los usan los paneles que la página compone.
  useGetWorkspaceWarnings: vi.fn(() => ({ data: [], isLoading: false })),
  usePatchWorkspaceBlock: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
}))
vi.mock('@/shared/api/download', () => ({
  descargarConAutorizacion: vi.fn().mockResolvedValue(undefined),
}))
vi.mock('@/shared/api/generated/redaccion-workspaces/redaccion-workspaces', () => ({
  useResumeWorkspace: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
  useRunWorkspace: vi.fn(),
  useSetWorkspaceFields: vi.fn(),
  useUploadWorkspaceInput: vi.fn(),
  useApproveBlock: vi.fn(),
  // SEG.4 — el panel de revisión ya edita, y editar es una mutación más de este módulo.
  useEditBlock: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
  useRejectBlock: vi.fn(),
  useRegenerateBlock: vi.fn(),
}))

const WORKSPACE_ID = '11111111-1111-1111-1111-111111111111'
const VERSION_ID = '22222222-2222-2222-2222-222222222222'

const CONTRATO = {
  wizard_steps: [{ id: 's1', title: 'Datos', order: 1, block_ids: ['b_datos'] }],
  dropzones: [{
    slot_id: 'datos_excel',
    label: { es: 'Datos presupuestarios', ca: 'Dades', en: 'Data' },
    accept: ['.xlsx'], multiple: false, max_size_mb: null,
  }],
  manual_fields: [{
    slot_id: 'periodo',
    label: { es: 'Periodo', ca: 'Període', en: 'Period' },
    field_type: 'text', placeholder: {}, required: true,
  }],
  block_editor_enabled: true,
  ai_review_panel_enabled: true,
  preview_layout: 'markdown',
}

const WORKSPACE = {
  id: WORKSPACE_ID,
  template_version_id: VERSION_ID,
  status: 'draft',
  blocks: [
    { block_id: 'b_datos', kind: 'DETERMINISTIC_DATA', status: 'draft' },
    { block_id: 'b_resumen', kind: 'AI_ASSISTED_TEXT', status: 'draft' },
  ],
  created_at: '2026-08-17T00:00:00Z',
  updated_at: '2026-08-17T00:00:00Z',
}

const runMutate = vi.fn()
/** Issue #86 — lo escrito en los campos manuales, que antes se recogía y se tiraba. */
const guardarCampos = vi.fn().mockResolvedValue({})

beforeAll(async () => {
  await i18n.changeLanguage('es')
})

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(useRunWorkspace).mockReturnValue({ mutate: runMutate, isPending: false } as any)
  vi.mocked(useUploadWorkspaceInput).mockReturnValue({
    mutateAsync: vi.fn().mockResolvedValue({}), isPending: false,
  } as any)
  guardarCampos.mockClear().mockResolvedValue({})
  vi.mocked(useSetWorkspaceFields).mockReturnValue({
    mutateAsync: guardarCampos, isPending: false,
  } as any)
})

function renderPage(workspace: object | undefined = WORKSPACE, contrato: object | undefined = CONTRATO) {
  vi.mocked(useGetWorkspaceById).mockReturnValue({ data: workspace, isLoading: false } as any)
  vi.mocked(useGetTemplateUiContract).mockReturnValue({ data: contrato, isLoading: false } as any)

  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[`/redaccion/workspaces/${WORKSPACE_ID}`]}>
        <Routes>
          <Route path="/redaccion/workspaces/:id" element={<WorkspacePage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  )
}

describe('WorkspacePage', () => {
  it('should_build_the_input_form_from_the_contract_and_not_from_fixed_fields', async () => {
    renderPage()

    await waitFor(() => {
      expect(screen.getByLabelText(/datos presupuestarios/i)).toBeDefined()
      expect(screen.getByLabelText(/periodo/i)).toBeDefined()
    })
  })

  it('should_show_the_blocks_of_the_report', async () => {
    renderPage()

    await waitFor(() => expect(screen.getByTestId('workspace-editor')).toBeDefined())
  })

  /**
   * INF.1 — este test comprobaba el botón «Generar informe», que llamaba a `run` **sin pasar
   * por la subida**. Codificaba el bloqueo A de las pruebas humanas del 2026-08-20: el usuario
   * pulsó ese botón —el destacado—, el informe se ejecutó sin datos y la pantalla no dijo
   * nada. Ahora se genera enviando el formulario del contrato, que es el único camino.
   */
  it('should_let_the_user_generate_the_report_through_the_contract_form', async () => {
    renderPage()

    fireEvent.change(screen.getByLabelText(/datos presupuestarios/i), {
      target: { files: [new File(['x'], 'datos.xlsx')] },
    })
    fireEvent.change(screen.getByLabelText(/periodo/i), { target: { value: '2026' } })
    fireEvent.click(screen.getByRole('button', { name: /continuar/i }))

    await waitFor(() =>
      expect(runMutate).toHaveBeenCalledWith(
        expect.objectContaining({ workspaceId: WORKSPACE_ID }),
        expect.anything(),
      ),
    )
  })

  /**
   * Issue #86 — lo escrito en los campos manuales **se guarda**, y antes de lanzar.
   *
   * El formulario los recogia y `enviar` los tiraba: la seccion «Datos aportados por la
   * coordinacion» del informe del doctorado salia vacia hiciera uno lo que hiciera, y sin
   * ningun aviso. El grafo los lee del informe, no de la peticion de generacion, asi que
   * guardarlos despues de lanzar seria guardarlos para la vez siguiente.
   */
  it('should_save_what_was_typed_before_running', async () => {
    renderPage({ ...WORKSPACE, uploaded_slots: ['datos_excel'] })

    fireEvent.change(screen.getByLabelText(/periodo/i), { target: { value: '2026' } })
    fireEvent.click(screen.getByRole('button', { name: /continuar/i }))

    await waitFor(() =>
      expect(guardarCampos).toHaveBeenCalledWith({
        workspaceId: WORKSPACE_ID,
        data: { fields: { periodo: '2026' } },
      }),
    )
    expect(guardarCampos.mock.invocationCallOrder[0]).toBeLessThan(
      runMutate.mock.invocationCallOrder[0],
    )
  })

  it('should_bring_back_what_was_already_typed', async () => {
    // Issue #86 — sin esto, reejecutar manda el formulario vacío y **borra** lo guardado: el
    // endpoint de campos es un `PUT`, que es lo que permite vaciar uno a propósito.
    renderPage({ ...WORKSPACE, uploaded_slots: ['datos_excel'], manual_inputs: { periodo: '2025' } })

    await waitFor(() =>
      expect((screen.getByLabelText(/periodo/i) as HTMLInputElement).value).toBe('2025'),
    )
  })

  it('should_not_offer_any_way_to_run_that_skips_the_upload', async () => {
    renderPage()

    await waitFor(() => expect(screen.getByTestId('workspace-editor')).toBeDefined())
    // El test falla si alguien reintroduce un disparador que no pase por el formulario.
    expect(screen.queryByTestId('btn-generar-informe')).toBeNull()
  })

  it('should_not_demand_again_a_file_already_uploaded', async () => {
    renderPage({ ...WORKSPACE, uploaded_slots: ['datos_excel'] })

    fireEvent.change(screen.getByLabelText(/periodo/i), { target: { value: '2026' } })
    fireEvent.click(screen.getByRole('button', { name: /continuar/i }))

    // Sin esto, reejecutar un informe obligaría a resubir el mismo fichero cada vez.
    await waitFor(() => expect(runMutate).toHaveBeenCalled())
  })

  it('should_say_the_missing_slot_when_the_server_refuses_the_run', async () => {
    vi.mocked(useRunWorkspace).mockReturnValue({
      mutate: (_vars: unknown, opciones: { onError?: (e: unknown) => void }) =>
        opciones?.onError?.({ response: { data: { detail: { missing_slots: ['datos_excel'] } } } }),
      isPending: false,
    } as any)
    renderPage({ ...WORKSPACE, uploaded_slots: ['datos_excel'] })

    fireEvent.change(screen.getByLabelText(/periodo/i), { target: { value: '2026' } })
    fireEvent.click(screen.getByRole('button', { name: /continuar/i }))

    const aviso = await screen.findByRole('alert')
    expect(aviso.textContent).toMatch(/datos_excel/)
  })

  it('should_say_when_the_generation_failed_instead_of_looking_idle', async () => {
    renderPage({ ...WORKSPACE, status: 'error' })

    expect(await screen.findByTestId('workspace-error')).toBeDefined()
  })

  it('should_offer_the_preview_once_there_is_something_to_preview', async () => {
    renderPage({ ...WORKSPACE, status: 'in_review' })

    const enlace = await screen.findByRole('link', { name: /vista previa/i })
    expect(enlace.getAttribute('href')).toBe(`/redaccion/workspaces/${WORKSPACE_ID}/preview`)
  })

  it('should_not_offer_the_preview_before_generating', async () => {
    renderPage()

    expect(screen.queryByRole('link', { name: /vista previa/i })).toBeNull()
  })

  /**
   * CUR.5, encontrado de rebote: la exportación del informe tenía **el mismo defecto** que los
   * botones de descarga del informe de auditoría que el usuario reportó. Era un `<a href>` a
   * `/export`, o sea una navegación sin cabecera de autorización, y el endpoint depende de
   * `get_current_user`: 401 y el error de descarga del navegador. PRO.5 dio el informe por
   * «descargable» y la descarga no podía funcionar.
   */
  it('la exportación se pide con el token, no como una navegación del navegador', async () => {
    const { descargarConAutorizacion } = await import('@/shared/api/download')
    renderPage({ ...WORKSPACE, status: 'in_review' })

    expect(screen.queryByRole('link', { name: /exportar|descargar/i })).toBeNull()

    fireEvent.click(await screen.findByTestId('btn-exportar'))

    await waitFor(() =>
      expect(descargarConAutorizacion).toHaveBeenCalledWith(
        `/api/v1/redaccion/workspaces/${WORKSPACE_ID}/export`,
        expect.stringContaining('.docx'),
      ),
    )
  })
})
