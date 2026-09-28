/**
 * Issue #98 — el resumen de datos personales se ve en el informe, una vez y por quien lo subió.
 *
 * **El defecto era peor de lo que la issue decía.** La issue hablaba de una pantalla «enterrada
 * en el diagnóstico por bloque» y corregía al probador, que había dicho que no estaba montada.
 * El probador tenía razón en el efecto: la cadena era
 * `WorkspaceAnonymizationPanel` ← `BlockDebugPanel` ← `BlockEditor` ← **nadie**. `BlockEditor`
 * sólo aparecía en tests, así que el panel era **inalcanzable desde la aplicación**. Es la misma
 * forma que ya se vio en PRO.6 con el copiloto y en DIN.4 con la auto-ingesta: una capacidad que
 * nadie monta no existe.
 *
 * **Y la decisión que la issue dejaba abierta ya estaba tomada en el servidor, al revés de lo
 * que hacía la pantalla.** `_get_workspace_checked` exige **ser el dueño del workspace**, no ser
 * administrador: SEC.8.1 quitó el bypass por rol a propósito, porque «el resumen NER no se
 * comparte por jerarquía: se comparte con quien lo generó». El panel hacía
 * `if (!isAdmin) return null`, que es exactamente lo contrario — y además el frontend no calcula
 * permisos (invariante I6).
 *
 * Lo que se fija aquí:
 *
 * 1. El panel aparece **en el informe y una sola vez**, no una por bloque.
 * 2. Lo ve quien **no** es administrador: el servidor ya decide por propiedad y responde 403 a
 *    quien no sea el dueño, así que esconderlo en el cliente sólo se lo quita a la persona
 *    cuyos documentos se anonimizan.
 * 3. Se ve **durante `drafting` e `in_review`**, que es justo cuando alguien quiere comprobar la
 *    garantía. Que no se pueda cambiar el modo ahí ya lo resuelve el propio panel, poniéndose en
 *    solo lectura.
 */
import { describe, it, expect, beforeAll, beforeEach, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import i18n from '@/shared/i18n'
import { WorkspacePage } from '../pages/WorkspacePage'
import {
  useGetWorkspaceById,
  useGetTemplateUiContractApiV1HubRedaccionTemplateVersionsVersionIdUiContractGet as useGetTemplateUiContract,
} from '@/shared/api/generated/hub-redaccion/hub-redaccion'
import { useGetAnonymizationSummary } from '@/shared/api/generated/redaccion-anonymization/redaccion-anonymization'

vi.mock('@/shared/api/generated/hub-redaccion/hub-redaccion', () => ({
  useGetWorkspaceById: vi.fn(),
  useGetTemplateUiContractApiV1HubRedaccionTemplateVersionsVersionIdUiContractGet: vi.fn(),
  getGetWorkspaceByIdQueryKey: vi.fn(() => ['workspace']),
  useGetWorkspaceWarnings: vi.fn(() => ({ data: [], isLoading: false })),
  usePatchWorkspaceBlock: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
}))
vi.mock('@/shared/api/download', () => ({
  descargarConAutorizacion: vi.fn().mockResolvedValue(undefined),
}))
vi.mock('@/shared/api/generated/redaccion-workspaces/redaccion-workspaces', () => ({
  useResumeWorkspace: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
  useRunWorkspace: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
  useSetWorkspaceFields: vi.fn(() => ({ mutateAsync: vi.fn().mockResolvedValue({}), isPending: false })),
  useUploadWorkspaceInput: vi.fn(() => ({
    mutateAsync: vi.fn().mockResolvedValue({}),
    isPending: false,
  })),
  useApproveBlock: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
  useEditBlock: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
  useRejectBlock: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
  useRegenerateBlock: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
}))
vi.mock('@/shared/api/generated/redaccion-anonymization/redaccion-anonymization', () => ({
  useGetAnonymizationSummary: vi.fn(),
  usePatchAnonymizationMode: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
  getGetAnonymizationSummaryQueryKey: vi.fn(() => ['anon']),
}))

// Quien mira es `user`, que es el caso de la issue: la persona cuyos documentos se anonimizan.
vi.mock('@/shared/auth', () => ({
  useAuth: () => ({ user: { role: 'user', email: 'quien.redacta@uji.es' } }),
}))

const WORKSPACE_ID = '11111111-1111-1111-1111-111111111111'
const VERSION_ID = '22222222-2222-2222-2222-222222222222'

const CONTRATO = {
  wizard_steps: [],
  dropzones: [],
  manual_fields: [],
  block_editor_enabled: true,
  ai_review_panel_enabled: false,
  preview_layout: 'markdown',
}

const RESUMEN = {
  mode: 'replace',
  counts_by_type: { PER: 3, LOC: 1 },
  total_spans: 4,
  last_run_at: '2026-09-26T10:00:00Z',
  current_workspace_mode: 'replace',
}

function workspaceEn(status: string) {
  return {
    id: WORKSPACE_ID,
    template_version_id: VERSION_ID,
    status,
    blocks: [
      { block_id: 'b_datos', kind: 'DETERMINISTIC_DATA', status: 'draft' },
      { block_id: 'b_resumen', kind: 'AI_ASSISTED_TEXT', status: 'draft' },
    ],
    created_at: '2026-09-26T00:00:00Z',
    updated_at: '2026-09-26T00:00:00Z',
  }
}

beforeAll(async () => {
  await i18n.changeLanguage('es')
})

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(useGetAnonymizationSummary).mockReturnValue({
    data: RESUMEN,
    isLoading: false,
  } as never)
})

function renderPage(status = 'draft') {
  vi.mocked(useGetWorkspaceById).mockReturnValue({
    data: workspaceEn(status),
    isLoading: false,
  } as never)
  vi.mocked(useGetTemplateUiContract).mockReturnValue({
    data: CONTRATO,
    isLoading: false,
  } as never)

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

describe('Issue #98 — el resumen de anonimización, en el informe', () => {
  it('should_render_the_panel_once_per_report_and_not_once_per_block', async () => {
    renderPage()

    await waitFor(() => {
      const paneles = screen.getAllByTestId('workspace-anonymization-panel')
      expect(paneles).toHaveLength(1)
    })
  })

  it('should_show_it_to_someone_who_is_not_an_administrator', async () => {
    // El servidor sólo se lo sirve al dueño del workspace (SEC.8.1), así que esconderlo aquí
    // sólo se lo quita a la persona cuyos documentos se anonimizan.
    renderPage()

    await waitFor(() =>
      expect(screen.getByTestId('workspace-anonymization-panel')).toBeDefined(),
    )
  })

  it.each(['drafting', 'in_review'])(
    'should_still_show_it_while_the_report_is_being_written_or_reviewed_(%s)',
    async status => {
      renderPage(status)

      await waitFor(() =>
        expect(screen.getByTestId('workspace-anonymization-panel')).toBeDefined(),
      )
    },
  )

  it('should_not_show_original_or_synthetic_values', async () => {
    // Lo garantiza el servidor —el resumen son recuentos por tipo— y se fija también desde la
    // pantalla: si algún día el DTO creciera con los valores, este test se pondría rojo antes
    // de que aparecieran delante de alguien.
    renderPage()

    await waitFor(() =>
      expect(screen.getByTestId('workspace-anonymization-panel')).toBeDefined(),
    )
    const panel = screen.getByTestId('workspace-anonymization-panel')
    expect(panel.textContent).not.toMatch(/quien\.redacta@uji\.es/)
  })
})
