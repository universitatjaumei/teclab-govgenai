/**
 * Tests 13.2 (RED → GREEN)
 * WorkspaceAnonymizationPanel — 4 tests Vitest
 */
import { describe, it, expect, vi, beforeAll } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import i18n from '@/shared/i18n'

import { WorkspaceAnonymizationPanel } from '../components/WorkspaceAnonymizationPanel'

// ---------------------------------------------------------------------------
// Mock hooks
// ---------------------------------------------------------------------------

const mockPatchMutate = vi.fn()

vi.mock('@/shared/api/generated/redaccion-anonymization/redaccion-anonymization', () => ({
  getGetAnonymizationSummaryQueryKey: (id: string) => ['anon-summary', id],
  useGetAnonymizationSummary: vi.fn(),
  usePatchAnonymizationMode: vi.fn(),
}))

import {
  useGetAnonymizationSummary,
  usePatchAnonymizationMode,
} from '@/shared/api/generated/redaccion-anonymization/redaccion-anonymization'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeSummary(overrides: Record<string, unknown> = {}) {
  return {
    mode: 'replace' as const,
    counts_by_type: { PERSON: 3, EMAIL: 1 },
    total_spans: 4,
    last_run_at: '2026-05-18T10:00:00Z',
    current_workspace_mode: 'replace',
    ...overrides,
  }
}

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

beforeAll(async () => {
  await i18n.changeLanguage('es')
})

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('WorkspaceAnonymizationPanel', () => {
  it('test_panel_renders_counts_by_type', () => {
    vi.mocked(useGetAnonymizationSummary).mockReturnValue({
      data: makeSummary(),
      isLoading: false,
      isError: false,
    } as never)
    vi.mocked(usePatchAnonymizationMode).mockReturnValue({
      mutate: mockPatchMutate,
      isPending: false,
    } as never)

    wrap(
      <WorkspaceAnonymizationPanel
        workspaceId="ws-1"
        workspaceStatus="assembled"
      />
    )

    expect(screen.getByTestId('anon-type-PERSON')).toHaveTextContent('3')
    expect(screen.getByTestId('anon-type-EMAIL')).toHaveTextContent('1')
    expect(screen.getByTestId('anon-total-spans')).toHaveTextContent('4')
  })

  it('test_panel_disables_mode_selector_when_workspace_drafting', () => {
    vi.mocked(useGetAnonymizationSummary).mockReturnValue({
      data: makeSummary({ current_workspace_mode: 'replace' }),
      isLoading: false,
      isError: false,
    } as never)
    vi.mocked(usePatchAnonymizationMode).mockReturnValue({
      mutate: mockPatchMutate,
      isPending: false,
    } as never)

    wrap(
      <WorkspaceAnonymizationPanel
        workspaceId="ws-2"
        workspaceStatus="drafting"
      />
    )

    const radios = screen.getAllByRole('radio')
    radios.forEach(radio => {
      expect(radio).toBeDisabled()
    })
    expect(screen.getByTestId('anon-mode-locked-msg')).toBeInTheDocument()
  })

  it('test_panel_shows_lopdgdd_badge_in_disposition_7_mode', () => {
    vi.mocked(useGetAnonymizationSummary).mockReturnValue({
      data: makeSummary({ current_workspace_mode: 'replace_with_disposition_7' }),
      isLoading: false,
      isError: false,
    } as never)
    vi.mocked(usePatchAnonymizationMode).mockReturnValue({
      mutate: mockPatchMutate,
      isPending: false,
    } as never)

    wrap(
      <WorkspaceAnonymizationPanel
        workspaceId="ws-3"
        workspaceStatus="draft"
      />
    )

    expect(screen.getByTestId('anon-badge-lopdgdd')).toBeInTheDocument()
  })

  it('test_el_boton_refresca_la_vista_y_no_lanza_ninguna_mutacion', () => {
    // **Issue #169.** Este test se llamaba `test_re_analyze_button_dispatches_mutation` y
    // comprobaba que el botón llamaba a una mutación que respondía 202 «encolado» **sin encolar
    // nada**: fijaba la forma de una promesa que no se cumplía.
    //
    // El botón se queda porque la finalidad era otra y sí existe —ver el resultado de una
    // anonimización ya aplicada, o el de la iteración anterior— y eso lo sirve el `GET`. Así que
    // ahora refresca la vista, y lo que se comprueba es que **no llama a ninguna mutación**.
    vi.mocked(useGetAnonymizationSummary).mockReturnValue({
      data: makeSummary(),
      isLoading: false,
      isError: false,
    } as never)
    vi.mocked(usePatchAnonymizationMode).mockReturnValue({
      mutate: mockPatchMutate,
      isPending: false,
    } as never)

    wrap(
      <WorkspaceAnonymizationPanel
        workspaceId="ws-4"
        workspaceStatus="draft"
      />
    )

    fireEvent.click(screen.getByTestId('btn-refrescar-resumen'))

    expect(mockPatchMutate).not.toHaveBeenCalled()
  })
})
