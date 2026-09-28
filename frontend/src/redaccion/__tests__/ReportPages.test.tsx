/**
 * Tests 9R.7.3 (RED → GREEN)
 * ReportTemplateBuilderPage + GenericReportWizard
 */
import { describe, it, expect, vi, beforeAll, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import i18n from '@/shared/i18n'

import { ReportTemplateBuilderPage } from '../pages/ReportTemplateBuilderPage'
import { GenericReportWizard } from '../pages/GenericReportWizard'

// --------------------------------------------------------------------------
// Mock Orval hooks
// --------------------------------------------------------------------------

const mockCreateWorkspace = vi.fn()

vi.mock('@/shared/api/generated/hub-redaccion/hub-redaccion', () => ({
  useListTemplates: vi.fn(),
  useCreateWorkspace: vi.fn(),
  usePatchTemplate: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
  useArchiveTemplate: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
  useRestoreTemplate: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
  getListTemplatesQueryKey: vi.fn(() => ['templates']),
}))

vi.mock('@/shared/auth', async () => {
  const actual = await vi.importActual<typeof import('@/shared/auth')>('@/shared/auth')
  return {
    ...actual,
    useAuth: vi.fn(),
  }
})

import {
  useListTemplates,
  useCreateWorkspace,
} from '@/shared/api/generated/hub-redaccion/hub-redaccion'
import { useAuth } from '@/shared/auth'

// --------------------------------------------------------------------------
// Helpers
// --------------------------------------------------------------------------

function makeTemplate(id: string, name: string, profile = 'GENERIC_REPORT') {
  return {
    id,
    name,
    description: null,
    report_profile: profile,
    owner_kind: 'platform',
    is_global: true,
    current_version_id: `ver-${id}`,
    created_at: '2026-01-01T00:00:00Z',
  }
}

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  // `MemoryRouter` desde VER.4: el asistente navega al informe recién creado, así que ya
  // no se puede montar fuera de un router.
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>
  )
}

beforeAll(async () => {
  await i18n.changeLanguage('es')
})

beforeEach(() => {
  mockCreateWorkspace.mockClear()

  vi.mocked(useCreateWorkspace).mockReturnValue({
    mutate: mockCreateWorkspace,
    isPending: false,
    isError: false,
    isSuccess: false,
  } as unknown as ReturnType<typeof useCreateWorkspace>)

  vi.mocked(useAuth).mockReturnValue({
    user: { user_id: 'u1', email: 'admin@test.com', role: 'admin', cambio_pendiente: false },
    isAuthenticated: true,
    login: vi.fn(),
    logout: vi.fn(),
  })
})

// --------------------------------------------------------------------------
// ReportTemplateBuilderPage
// --------------------------------------------------------------------------

/**
 * GUI.1 — aquí había un `should_allow_admin_to_save_template_version` que exigía el alta con
 * `spec_json: {}`. Ese alta **producía basura**: una plantilla sin bloques da un informe vacío y
 * no hay editor de bloques con el que arreglarla después, así que la mitad de lo que ensuciaba
 * la lista de plantillas lo generaba ese botón. Se crea describiendo el informe.
 *
 * El resto de la gestión (renombrar, retirar, recuperar) vive en `GestionDePlantillas.test.tsx`.
 */
describe('ReportTemplateBuilderPage', () => {
  it('should_redirect_non_admin_away_from_builder_page', () => {
    // Los hooks se llaman antes de comprobar el rol, como exige React: sin stub, el render
    // revienta al desestructurar y el test pasaría a medir otra cosa.
    vi.mocked(useListTemplates).mockReturnValue({
      data: [],
      isLoading: false,
    } as unknown as ReturnType<typeof useListTemplates>)

    vi.mocked(useAuth).mockReturnValue({
      user: { user_id: 'u2', email: 'user@test.com', role: 'user', cambio_pendiente: false },
      isAuthenticated: true,
      login: vi.fn(),
      logout: vi.fn(),
    })

    wrap(<ReportTemplateBuilderPage />)

    expect(screen.getByTestId('access-denied')).toBeDefined()
    expect(screen.queryByTestId('btn-save-template')).toBeNull()
  })
})

// --------------------------------------------------------------------------
// GenericReportWizard
// --------------------------------------------------------------------------

describe('GenericReportWizard', () => {
  it('should_list_only_user_visible_templates', () => {
    vi.mocked(useListTemplates).mockReturnValue({
      data: [makeTemplate('t1', 'Plantilla A'), makeTemplate('t2', 'Plantilla B')],
      isLoading: false,
    } as unknown as ReturnType<typeof useListTemplates>)

    wrap(<GenericReportWizard />)

    expect(screen.getByText('Plantilla A')).toBeDefined()
    expect(screen.getByText('Plantilla B')).toBeDefined()
  })

  it('should_allow_user_to_create_ad_hoc_workspace_from_generic_report', () => {
    vi.mocked(useListTemplates).mockReturnValue({
      data: [makeTemplate('t1', 'Informe Genérico')],
      isLoading: false,
    } as unknown as ReturnType<typeof useListTemplates>)

    wrap(<GenericReportWizard />)

    fireEvent.click(screen.getByTestId('btn-create-workspace-t1'))

    // El segundo argumento son las opciones de la mutación: desde VER.4 lleva el
    // `onSuccess` que abre el informe recién creado.
    expect(mockCreateWorkspace).toHaveBeenCalledWith(
      expect.objectContaining({ data: expect.objectContaining({ template_version_id: 'ver-t1' }) }),
      expect.anything(),
    )
  })
})
