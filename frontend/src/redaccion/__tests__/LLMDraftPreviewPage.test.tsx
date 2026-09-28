/**
 * Tests 9R.7.4 (RED → GREEN)
 * LLMDraftPreviewPage
 */
import { describe, it, expect, vi, beforeAll, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import i18n from '@/shared/i18n'

import { LLMDraftPreviewPage } from '../pages/LLMDraftPreviewPage'

// --------------------------------------------------------------------------
// Mock Orval hooks
// --------------------------------------------------------------------------

const mockPropose = vi.fn()
const mockValidate = vi.fn()
const mockApproveTemplate = vi.fn()
const mockApproveWorkspace = vi.fn()

vi.mock('@/shared/api/generated/redaccion-llm-drafts/redaccion-llm-drafts', () => ({
  useProposeLlmDraft: vi.fn(),
  useValidateLlmDraft: vi.fn(),
  useApproveAsTemplate: vi.fn(),
  useApproveAsWorkspace: vi.fn(),
  // INF.4 — el fichero de muestra opcional. El mock de un módulo tiene que cubrir todo lo que
  // el componente importa: sin esta entrada, la pantalla revienta al montar.
  useDescribeSampleFile: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
}))

vi.mock('@/shared/auth', async () => {
  const actual = await vi.importActual<typeof import('@/shared/auth')>('@/shared/auth')
  return {
    ...actual,
    useAuth: vi.fn(),
  }
})

import {
  useProposeLlmDraft,
  useValidateLlmDraft,
  useApproveAsTemplate,
  useApproveAsWorkspace,
} from '@/shared/api/generated/redaccion-llm-drafts/redaccion-llm-drafts'
import { useAuth } from '@/shared/auth'

// --------------------------------------------------------------------------
// Fixtures
// --------------------------------------------------------------------------

const SAMPLE_DRAFT = {
  proposed_profile: 'GENERIC_REPORT',
  proposed_sections: [{ section_id: 's1', title: 'Introducción', blocks: [] }],
  proposed_blocks: [],
  proposed_inputs: { slots: [] },
  rationale: 'Test rationale',
  model_used: 'gpt-4o',
  prompt_version: '1.0',
}

/**
 * Con `MemoryRouter` desde el issue #87: la página llama a `useNavigate`, que sólo funciona
 * dentro de un Router. Aquí no se declaran rutas de destino porque estos tests no comprueban la
 * navegación — eso lo hace `Issue87AprobarConfirmaYNavega.test.tsx`—; sólo hacen falta el
 * contexto para que monte.
 */
function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
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
  mockPropose.mockClear()
  mockValidate.mockClear()
  mockApproveTemplate.mockClear()
  mockApproveWorkspace.mockClear()

  // Default: draft present, no validation yet, admin user
  vi.mocked(useProposeLlmDraft).mockReturnValue({
    mutate: mockPropose,
    data: SAMPLE_DRAFT,
    isPending: false,
    isSuccess: true,
    isError: false,
  } as unknown as ReturnType<typeof useProposeLlmDraft>)

  vi.mocked(useValidateLlmDraft).mockReturnValue({
    mutate: mockValidate,
    data: undefined,
    isPending: false,
    isSuccess: false,
    isError: false,
  } as unknown as ReturnType<typeof useValidateLlmDraft>)

  vi.mocked(useApproveAsTemplate).mockReturnValue({
    mutate: mockApproveTemplate,
    isPending: false,
    isSuccess: false,
    isError: false,
  } as unknown as ReturnType<typeof useApproveAsTemplate>)

  vi.mocked(useApproveAsWorkspace).mockReturnValue({
    mutate: mockApproveWorkspace,
    isPending: false,
    isSuccess: false,
    isError: false,
  } as unknown as ReturnType<typeof useApproveAsWorkspace>)

  vi.mocked(useAuth).mockReturnValue({
    user: { user_id: 'u1', email: 'admin@test.com', role: 'admin', cambio_pendiente: false },
    isAuthenticated: true,
    login: vi.fn(),
    logout: vi.fn(),
  })
})

// --------------------------------------------------------------------------
// Tests
// --------------------------------------------------------------------------

describe('LLMDraftPreviewPage', () => {
  it('should_render_llm_generated_draft_preview_before_persisting', () => {
    wrap(<LLMDraftPreviewPage />)

    expect(screen.getByTestId('draft-preview')).toBeDefined()
    // Draft profile visible
    expect(screen.getByTestId('draft-preview').textContent).toContain('GENERIC_REPORT')
  })

  it('should_block_approve_button_when_draft_invalid', () => {
    vi.mocked(useValidateLlmDraft).mockReturnValue({
      mutate: mockValidate,
      data: {
        ok: false,
        errors: [{ field: 'proposed_blocks', message: 'Must have at least one block' }],
      },
      isPending: false,
      isSuccess: true,
      isError: false,
    } as unknown as ReturnType<typeof useValidateLlmDraft>)

    wrap(<LLMDraftPreviewPage />)

    const approveBtn = screen.getByTestId('btn-approve') as HTMLButtonElement
    expect(approveBtn.disabled).toBe(true)
  })

  it('should_call_approve_as_template_when_admin_mode', () => {
    wrap(<LLMDraftPreviewPage />)

    fireEvent.click(screen.getByTestId('mode-template'))
    fireEvent.click(screen.getByTestId('btn-approve'))

    // Segundo argumento desde el issue #87: la llamada lleva ahora `onSuccess`/`onError`.
    // Aquí se admite con `expect.anything()` en vez de afirmarlo, porque lo que este test
    // comprueba es **qué mutación se llama y con qué datos**; que esas devoluciones hagan
    // lo suyo lo comprueba `Issue87AprobarConfirmaYNavega.test.tsx`.
    expect(mockApproveTemplate).toHaveBeenCalledWith(
      expect.objectContaining({ data: expect.objectContaining({ draft: SAMPLE_DRAFT }) }),
      expect.anything(),
    )
  })

  it('should_call_approve_as_workspace_when_user_mode', () => {
    vi.mocked(useAuth).mockReturnValue({
      user: { user_id: 'u2', email: 'user@test.com', role: 'user', cambio_pendiente: false },
      isAuthenticated: true,
      login: vi.fn(),
      logout: vi.fn(),
    })

    wrap(<LLMDraftPreviewPage />)

    // Default mode is 'workspace' — click approve directly
    fireEvent.click(screen.getByTestId('btn-approve'))

    // Segundo argumento desde el issue #87: la llamada lleva ahora `onSuccess`/`onError`.
    // Aquí se admite con `expect.anything()` en vez de afirmarlo, porque lo que este test
    // comprueba es **qué mutación se llama y con qué datos**; que esas devoluciones hagan
    // lo suyo lo comprueba `Issue87AprobarConfirmaYNavega.test.tsx`.
    expect(mockApproveWorkspace).toHaveBeenCalledWith(
      expect.objectContaining({ data: expect.objectContaining({ draft: SAMPLE_DRAFT }) }),
      expect.anything(),
    )
  })

  it('should_show_validation_errors_inline', () => {
    vi.mocked(useValidateLlmDraft).mockReturnValue({
      mutate: mockValidate,
      data: {
        ok: false,
        errors: [
          { field: 'proposed_blocks', message: 'Must have at least one block' },
          { field: 'proposed_profile', message: 'Unknown profile' },
        ],
      },
      isPending: false,
      isSuccess: true,
      isError: false,
    } as unknown as ReturnType<typeof useValidateLlmDraft>)

    wrap(<LLMDraftPreviewPage />)

    expect(screen.getByTestId('validation-errors')).toBeDefined()
    expect(screen.getByText(/Must have at least one block/)).toBeDefined()
    expect(screen.getByText(/Unknown profile/)).toBeDefined()
  })
})
