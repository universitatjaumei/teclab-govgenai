import { describe, it, expect, beforeAll, beforeEach, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import i18n from '@/shared/i18n'
import { AdminScriptReviewQueuePage } from '../pages/AdminScriptReviewQueuePage'
import {
  useListPendingScripts,
  useAdminRetestScript,
  useApproveScriptProposal,
  useRejectScriptProposal,
} from '@/shared/api/generated/redaccion-scripts/redaccion-scripts'
import { useListTemplates } from '@/shared/api/generated/hub-redaccion/hub-redaccion'

/**
 * VER.5 — la plantilla de destino se elige, no se teclea.
 *
 * El campo era un texto libre con el marcador «UUID de la plantilla». Un administrador no
 * sabe de memoria el UUID de una plantilla, y escribir uno mal da un 404 después de haber
 * aprobado: la lista de plantillas ya la sirve la API, así que el campo puede ser un
 * desplegable y dejar de ser una trampa.
 */
vi.mock('@/shared/api/generated/redaccion-scripts/redaccion-scripts', () => ({
  useListPendingScripts: vi.fn(),
  useAdminRetestScript: vi.fn(),
  useApproveScriptProposal: vi.fn(),
  useRejectScriptProposal: vi.fn(),
}))
vi.mock('@/shared/api/generated/hub-redaccion/hub-redaccion', () => ({
  useListTemplates: vi.fn(),
}))
vi.mock('@/shared/auth', () => ({
  useAuth: () => ({ user: { role: 'superadmin', email: 'admin@example.local' } }),
}))

const PROPUESTA = {
  proposal_id: 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
  proposer_user_id: 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
  prompt_nl: 'Extrae el total de una factura',
  code_preview: 'result = {}',
  created_at: '2026-08-17T00:00:00Z',
}

const PLANTILLAS = [
  { id: 'tpl-global', name: 'Extracciones de facturas', report_profile: 'GENERIC_REPORT', is_global: true },
  { id: 'tpl-privada', name: 'Mi plantilla privada', report_profile: 'GENERIC_REPORT', is_global: false },
]

const approveMutate = vi.fn()

beforeAll(async () => {
  await i18n.changeLanguage('es')
})

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(useListPendingScripts).mockReturnValue({ data: [PROPUESTA], isLoading: false } as any)
  vi.mocked(useAdminRetestScript).mockReturnValue({
    mutate: vi.fn(), isPending: false, data: { hash_matches: true, hash: 'abc' },
  } as any)
  vi.mocked(useApproveScriptProposal).mockReturnValue({ mutate: approveMutate, isPending: false } as any)
  vi.mocked(useRejectScriptProposal).mockReturnValue({ mutate: vi.fn(), isPending: false } as any)
  vi.mocked(useListTemplates).mockReturnValue({ data: PLANTILLAS, isLoading: false } as any)
})

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <AdminScriptReviewQueuePage />
      </MemoryRouter>
    </QueryClientProvider>
  )
}

describe('AdminScriptReviewQueuePage', () => {
  it('should_offer_the_global_templates_to_choose_from', async () => {
    renderPage()

    const selector = await screen.findByTestId(`target-template-${PROPUESTA.proposal_id}`)
    expect(selector.tagName).toBe('SELECT')
    expect(selector.textContent).toContain('Extracciones de facturas')
  })

  it('should_not_offer_a_private_template_as_a_destination', async () => {
    renderPage()

    const selector = await screen.findByTestId(`target-template-${PROPUESTA.proposal_id}`)
    expect(selector.textContent).not.toContain('Mi plantilla privada')
  })

  it('should_approve_with_the_chosen_template', async () => {
    renderPage()

    const selector = await screen.findByTestId(`target-template-${PROPUESTA.proposal_id}`)
    fireEvent.change(selector, { target: { value: 'tpl-global' } })
    fireEvent.click(screen.getByTestId('btn-approve-proposal'))

    await waitFor(() => expect(approveMutate).toHaveBeenCalledWith(
      expect.objectContaining({
        proposalId: PROPUESTA.proposal_id,
        data: { target_global_template_id: 'tpl-global' },
      })
    ))
  })

  it('should_show_the_anonymization_report_and_let_download_the_synthetic', async () => {
    // #255 — quien revisa ve qué se anonimizó, qué quedó y quién lo aceptó.
    vi.mocked(useListPendingScripts).mockReturnValue({
      data: [{
        ...PROPUESTA,
        informe_anonimizacion: {
          tipo: 'tabular',
          sustituidas: [{ columna: 'IBAN', sustituto: 'iban' }],
          mantenidas: [{ columna: 'Nombre', propuesta: 'first_name' }],
          fragmentos: {},
          rechazados: {},
          restos: 0,
          requiere_aceptacion: true,
          aceptado_por: 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
          aceptado_en: '2026-10-10T10:00:00Z',
        },
      }],
      isLoading: false,
    } as any)
    renderPage()

    const informe = await screen.findByTestId('informe-anonimizacion')
    expect(informe.textContent).toContain('IBAN')
    expect(screen.getByTestId('mantenida-personal-Nombre')).toBeDefined()
    expect(screen.getByTestId('informe-aceptado')).toBeDefined()
    expect(screen.getByTestId('btn-descargar-sintetico')).toBeDefined()
  })
})

