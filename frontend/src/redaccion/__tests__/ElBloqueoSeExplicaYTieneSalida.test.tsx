import { describe, it, expect, beforeAll, beforeEach, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import i18n from '@/shared/i18n'
import { WorkspacePage } from '../pages/WorkspacePage'
import { WorkspacePreview } from '../preview/WorkspacePreview'
import {
  useGetWorkspaceById,
  useGetTemplateUiContractApiV1HubRedaccionTemplateVersionsVersionIdUiContractGet as useGetTemplateUiContract,
} from '@/shared/api/generated/hub-redaccion/hub-redaccion'
import {
  useRunWorkspace,
  useUploadWorkspaceInput,
  useGetWorkspacePreview,
} from '@/shared/api/generated/redaccion-workspaces/redaccion-workspaces'
import { descargarConAutorizacion } from '@/shared/api/download'

/**
 * INF.3 — un bloqueo se explica y ofrece salida.
 *
 * De las pruebas humanas del 2026-08-20: «El botón exportar a Word no hace nada». Hacía: pedía
 * el DOCX, recibía 409 y **se callaba**, porque el mensaje se guardaba en un estado que se
 * pintaba **dentro de la sección del contrato** — si esa sección no estaba visible, el error no
 * se pintaba en ningún sitio.
 *
 * Y la vista previa sí explicaba el 409, pero en un callejón: se monta fuera del layout, así que
 * el usuario tuvo que descubrir que se sale con el botón atrás del navegador.
 */
vi.mock('@/shared/api/generated/hub-redaccion/hub-redaccion', () => ({
  useGetWorkspaceById: vi.fn(),
  useGetTemplateUiContractApiV1HubRedaccionTemplateVersionsVersionIdUiContractGet: vi.fn(),
  getGetWorkspaceByIdQueryKey: vi.fn(() => ['workspace']),
  useGetWorkspaceWarnings: vi.fn(() => ({ data: [], isLoading: false })),
  usePatchWorkspaceBlock: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
}))
vi.mock('@/shared/api/generated/redaccion-workspaces/redaccion-workspaces', () => ({
  useResumeWorkspace: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
  useRunWorkspace: vi.fn(),
  useSetWorkspaceFields: vi.fn(() => ({ mutateAsync: vi.fn().mockResolvedValue({}), isPending: false })),
  useUploadWorkspaceInput: vi.fn(),
  useEditBlock: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
  useGetWorkspacePreview: vi.fn(),
}))
vi.mock('@/shared/api/download', () => ({
  descargarConAutorizacion: vi.fn(),
}))

const WS = '11111111-1111-1111-1111-111111111111'

const WORKSPACE = {
  id: WS,
  template_version_id: '22222222-2222-2222-2222-222222222222',
  status: 'in_review',
  uploaded_slots: ['datos'],
  blocks: [
    {
      block_id: 'v_matricula',
      kind: 'AI_ASSISTED_TEXT',
      status: 'needs_review',
      content: { text: 'Texto.' },
      retry_attempts: 0,
      updated_at: '2026-08-20T10:00:00Z',
      acciones_permitidas: ['approve', 'edit', 'reject'],
    },
  ],
  created_at: '2026-08-20T10:00:00Z',
  updated_at: '2026-08-20T10:00:00Z',
}

/** Un 409 de la exportación, con la forma que devuelve el servidor. */
const CONFLICTO_409 = {
  response: { status: 409, data: { detail: { pending_block_ids: ['v_matricula', 'v_tesis'] } } },
}

beforeAll(async () => {
  await i18n.changeLanguage('es')
})

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(useRunWorkspace).mockReturnValue({ mutate: vi.fn(), isPending: false } as never)
  vi.mocked(useUploadWorkspaceInput).mockReturnValue({
    mutateAsync: vi.fn().mockResolvedValue({}),
    isPending: false,
  } as never)
})

function pintarInforme(contrato: object | undefined) {
  vi.mocked(useGetWorkspaceById).mockReturnValue({ data: WORKSPACE, isLoading: false } as never)
  vi.mocked(useGetTemplateUiContract).mockReturnValue({ data: contrato, isLoading: false } as never)

  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[`/redaccion/workspaces/${WS}`]}>
        <Routes>
          <Route path="/redaccion/workspaces/:id" element={<WorkspacePage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('INF.3 — la exportación que falla lo dice', () => {
  it('should_explain_the_conflict_instead_of_doing_nothing', async () => {
    vi.mocked(descargarConAutorizacion).mockRejectedValue(CONFLICTO_409)
    pintarInforme(undefined)

    fireEvent.click(await screen.findByTestId('btn-exportar'))

    const aviso = await screen.findByTestId('workspace-aviso')
    expect(aviso.textContent).toMatch(/aprobar|pendiente/i)
  })

  it('should_show_the_error_even_when_there_is_no_input_form', async () => {
    // El mensaje vivía **dentro** de la sección del contrato: sin contrato, no se pintaba nada.
    vi.mocked(descargarConAutorizacion).mockRejectedValue(CONFLICTO_409)
    pintarInforme(undefined)

    fireEvent.click(await screen.findByTestId('btn-exportar'))

    expect(await screen.findByTestId('workspace-aviso')).toBeDefined()
  })

  it('should_turn_each_pending_block_into_a_link_to_that_block', async () => {
    vi.mocked(descargarConAutorizacion).mockRejectedValue(CONFLICTO_409)
    pintarInforme(undefined)

    fireEvent.click(await screen.findByTestId('btn-exportar'))

    await screen.findByTestId('workspace-aviso')
    const enlace = screen.getByTestId('enlace-a-bloque-v_matricula')
    expect(enlace.getAttribute('href')).toBe('#bloque-v_matricula')
  })

  it('should_anchor_every_block_so_the_link_lands_somewhere', async () => {
    pintarInforme(undefined)

    await waitFor(() => expect(screen.getByTestId('workspace-editor')).toBeDefined())
    expect(document.getElementById('bloque-v_matricula')).not.toBeNull()
  })
})

describe('INF.3 — la vista previa tiene salida', () => {
  function pintarVistaPrevia(resultado: object) {
    vi.mocked(useGetWorkspacePreview).mockReturnValue(resultado as never)
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    return render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={[`/redaccion/workspaces/${WS}/preview`]}>
          <Routes>
            <Route path="/redaccion/workspaces/:id/preview" element={<WorkspacePreview />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    )
  }

  it('should_offer_a_way_back_when_there_are_blocks_to_approve', async () => {
    pintarVistaPrevia({ isLoading: false, isError: true, error: CONFLICTO_409, data: undefined })

    const volver = await screen.findByTestId('volver-al-informe')
    expect(volver.getAttribute('href')).toBe(`/redaccion/workspaces/${WS}`)
  })

  it('should_offer_a_way_back_from_the_finished_preview_too', async () => {
    pintarVistaPrevia({
      isLoading: false,
      isError: false,
      data: { workspace_id: WS, cover: { title: 'T', blocks: [] }, toc: [], body: [], audit_annex: [] },
    })

    expect(await screen.findByTestId('volver-al-informe')).toBeDefined()
  })

  it('should_not_leave_hardcoded_spanish_in_the_toolbar', async () => {
    pintarVistaPrevia({
      isLoading: false,
      isError: false,
      data: { workspace_id: WS, cover: { title: 'T', blocks: [] }, toc: [], body: [], audit_annex: [] },
    })

    await screen.findByTestId('volver-al-informe')
    await i18n.changeLanguage('en')
    // Con el idioma en inglés no puede quedar texto castellano incrustado en el JSX.
    expect(screen.queryByText('Imprimir / Exportar PDF')).toBeNull()
    await i18n.changeLanguage('es')
  })
})
