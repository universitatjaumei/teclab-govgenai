import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { RevisionInteraccionesPage } from '../RevisionInteraccionesPage'
import {
  useGetInteractionsForReviewApiV1HubFeedbackChatbotIdReviewGet,
  useReviewInteractionApiV1HubFeedbackInteractionsInteractionIdReviewPatch,
} from '@/shared/api/generated/hub-feedback/hub-feedback'
import { useListChatbotsApiV1HubChatbotsGet } from '@/shared/api/generated/hub-chatbots/hub-chatbots'
import type { InteractionReviewOut } from '@/shared/api/generated/model'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, def?: string) => def ?? key,
  }),
}))

vi.mock('lucide-react', () => ({
  Download: () => <div data-testid="download-icon" />,
  Star: () => <div data-testid="star-icon" />,
  ChevronDown: () => <div data-testid="chevron-down" />,
  ChevronUp: () => <div data-testid="chevron-up" />,
  Loader2: () => <div data-testid="loader-icon" />,
}))

vi.mock('recharts', () => ({
  BarChart: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="bar-chart">{children}</div>
  ),
  Bar: () => null,
  XAxis: () => null,
  YAxis: () => null,
  Tooltip: () => null,
  ResponsiveContainer: ({ children }: { children: React.ReactNode }) => (
    <div>{children}</div>
  ),
  Cell: () => null,
}))

vi.mock('@/shared/api/generated/hub-chatbots/hub-chatbots', () => ({
  useOpcionesDeGrafoApiV1HubChatbotsOpcionesDeGrafoGet: () => ({ data: { perfiles: [{ nombre: 'PUBLIC_KB_RICH', configurable: true }], modos: [{ nombre: 'RAG' }, { nombre: 'MD_LONG_CONTEXT' }, { nombre: 'MD_AGENT_SELECTOR' }], estrategias: { retrieval: [], merge: [], template: [], language: [] }, ejes: ['retrieval', 'merge', 'template', 'language'] } }),
  useListChatbotsApiV1HubChatbotsGet: vi.fn(),
  getListChatbotsApiV1HubChatbotsGetQueryKey: vi.fn(() => ['/api/v1/hub/chatbots']),
}))
vi.mock('@/shared/api/generated/hub-feedback/hub-feedback', () => ({
  useGetInteractionsForReviewApiV1HubFeedbackChatbotIdReviewGet: vi.fn(),
  useReviewInteractionApiV1HubFeedbackInteractionsInteractionIdReviewPatch: vi.fn(),
  getGetInteractionsForReviewApiV1HubFeedbackChatbotIdReviewGetQueryKey: vi.fn(() => [
    '/api/v1/hub/feedback/c-1/review',
  ]),
}))

const SAMPLE_INTERACTIONS: InteractionReviewOut[] = [
  {
    id: 'i-1',
    user_message: 'How does Python work?',
    assistant_message: 'Python is an interpreted language that runs on a virtual machine.',
    feedback_score: 4,
    feedback_text: 'Good answer',
    run_id: null,
    created_at: '2026-04-01T10:00:00Z',
  },
  {
    id: 'i-2',
    user_message: 'What is FastAPI?',
    assistant_message: 'FastAPI is a modern web framework for building APIs with Python.',
    feedback_score: 2,
    feedback_text: 'Could be more detailed',
    run_id: null,
    created_at: '2026-04-02T12:00:00Z',
  },
]

const SAMPLE_CHATBOTS = [
  { id: 'c-1', name: 'Test Bot', organizacion_id: '', llm_config_id: '', system_prompt: '', sources: [], is_active: true, retrieval_mode: 'vector' as const, retrieval_top_k: 8, created_at: '', updated_at: '' },
]

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <RevisionInteraccionesPage />
    </QueryClientProvider>,
  )
}

describe('RevisionInteraccionesPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(useListChatbotsApiV1HubChatbotsGet).mockReturnValue({ data: SAMPLE_CHATBOTS } as any)
    vi.mocked(useGetInteractionsForReviewApiV1HubFeedbackChatbotIdReviewGet).mockReturnValue({
      data: SAMPLE_INTERACTIONS,
      isLoading: false,
    } as any)
    vi.mocked(useReviewInteractionApiV1HubFeedbackInteractionsInteractionIdReviewPatch).mockReturnValue(
      { mutate: vi.fn(), isPending: false } as any,
    )
  })

  it('should_display_interactions_table', async () => {
    renderPage()
    await waitFor(() => {
      expect(screen.getByText('How does Python work?')).toBeInTheDocument()
      expect(screen.getByText('What is FastAPI?')).toBeInTheDocument()
    })
  })

  it('should_filter_low_score_interactions', async () => {
    renderPage()
    await waitFor(() => screen.getByText('How does Python work?'))

    fireEvent.click(screen.getByRole('checkbox'))

    // El filtro viaja como parámetro de consulta del contrato, no como opción propia
    // de la pantalla: es el backend quien decide qué es «puntuación baja».
    await waitFor(() => {
      expect(useGetInteractionsForReviewApiV1HubFeedbackChatbotIdReviewGet).toHaveBeenCalledWith(
        'c-1',
        expect.objectContaining({ only_low_scores: true }),
        expect.anything(),
      )
    })
  })

  it('should_expand_row_to_show_full_messages', async () => {
    renderPage()
    await waitFor(() => screen.getByText('How does Python work?'))

    const expandBtns = screen.getAllByRole('button', { name: /expand/i })
    fireEvent.click(expandBtns[0])

    expect(
      screen.getByText('Python is an interpreted language that runs on a virtual machine.'),
    ).toBeInTheDocument()
  })

  it('should_export_data_as_csv', async () => {
    vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:mock')
    vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})

    renderPage()
    await waitFor(() => screen.getByText('How does Python work?'))

    fireEvent.click(screen.getByRole('button', { name: /csv/i }))

    expect(URL.createObjectURL).toHaveBeenCalledWith(expect.any(Blob))
  })

  it('should_display_average_score_metric', async () => {
    renderPage()
    await waitFor(() => {
      // Average of scores 4 and 2 = 3.0
      expect(screen.getByTestId('avg-score')).toHaveTextContent('3.0')
    })
  })
})

// ─────────────────────────── REV.1 — veredicto del revisor ───────────────────────────
//
// Distinto de las estrellas de arriba: eso es lo que opinó el usuario final. Esto es lo que
// dice quien audita, y es lo que Gerencia pidió para decidir si hay que reformular una FAQ.

describe('RevisionInteraccionesPage — revisión (REV.1)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(useListChatbotsApiV1HubChatbotsGet).mockReturnValue({ data: SAMPLE_CHATBOTS } as any)
    vi.mocked(useGetInteractionsForReviewApiV1HubFeedbackChatbotIdReviewGet).mockReturnValue({
      data: SAMPLE_INTERACTIONS,
      isLoading: false,
    } as any)
    vi.mocked(useReviewInteractionApiV1HubFeedbackInteractionsInteractionIdReviewPatch).mockReturnValue(
      { mutate: vi.fn(), isPending: false } as any,
    )
  })

  it('should_ask_the_backend_for_pending_interactions_by_default', async () => {
    renderPage()
    // La cola de revisión es lo que falta por mirar, no el historial entero. Y el filtro
    // viaja al backend: filtrarlo aquí daría lo mismo con 50 filas y nada con 50.000.
    await waitFor(() => {
      expect(useGetInteractionsForReviewApiV1HubFeedbackChatbotIdReviewGet).toHaveBeenCalledWith(
        'c-1',
        expect.objectContaining({ review_status: 'pending' }),
        expect.anything(),
      )
    })
  })

  it('should_show_the_pending_count', async () => {
    renderPage()
    // Las dos de la muestra están sin revisar (review_verdict ausente).
    await waitFor(() => {
      expect(screen.getByTestId('pending-count')).toHaveTextContent('2')
    })
  })

  it('should_send_the_verdict_when_the_reviewer_marks_an_answer_as_good', async () => {
    const mutate = vi.fn()
    vi.mocked(useReviewInteractionApiV1HubFeedbackInteractionsInteractionIdReviewPatch).mockReturnValue(
      { mutate, isPending: false } as any,
    )

    renderPage()
    await waitFor(() => screen.getByText('How does Python work?'))

    fireEvent.click(screen.getAllByRole('button', { name: /adecuada/i })[0])

    expect(mutate).toHaveBeenCalledWith(
      expect.objectContaining({
        interactionId: 'i-1',
        data: expect.objectContaining({ verdict: 'good' }),
      }),
      expect.anything(),
    )
  })

  it('should_not_send_a_bad_verdict_without_a_note', async () => {
    const mutate = vi.fn()
    vi.mocked(useReviewInteractionApiV1HubFeedbackInteractionsInteractionIdReviewPatch).mockReturnValue(
      { mutate, isPending: false } as any,
    )

    renderPage()
    await waitFor(() => screen.getByText('How does Python work?'))

    // Un «mal» sin motivo no reformula nada; el backend lo rechaza con 422 y la pantalla
    // no debe llegar a pedírselo.
    fireEvent.click(screen.getAllByRole('button', { name: /inadecuada/i })[0])

    expect(mutate).not.toHaveBeenCalled()
  })

  it('should_say_why_a_bad_verdict_is_blocked_instead_of_doing_nothing', async () => {
    /** El defecto que salió verificando RHR.1 en navegador.
     *
     * `revisar()` hacía `if (verdict === 'bad' && !note) return` — no mandaba nada al servidor,
     * que es correcto, y **no se lo decía a nadie**: se pulsaba «Inadecuada», la fila no cambiaba
     * y no aparecía ningún motivo. La única pista vivía en el *placeholder* del campo, que
     * desaparece en cuanto escribes una letra.
     *
     * El test de al lado (`should_not_send_a_bad_verdict_without_a_note`) afirma **la mitad que
     * pasa con el defecto**: que la llamada no ocurre. Esta es la otra mitad, y es la que
     * convierte «no pasa nada» en «falta la nota». Mismo patrón que el catálogo de funciones y
     * el asistente de scripts: el botón deshabilitado y el motivo a la vista.
     */
    vi.mocked(useReviewInteractionApiV1HubFeedbackInteractionsInteractionIdReviewPatch).mockReturnValue(
      { mutate: vi.fn(), isPending: false } as any,
    )

    renderPage()
    await waitFor(() => screen.getByText('How does Python work?'))

    const inadecuada = screen.getAllByRole('button', { name: /inadecuada/i })[0]
    expect(inadecuada).toBeDisabled()
    // Y el motivo, legible y no sólo un botón gris: el `title` lo lee también quien usa
    // lector de pantalla.
    expect(inadecuada).toHaveAttribute('title')
    expect(screen.getAllByTestId('nota-obligatoria')[0]).toBeInTheDocument()

    // Los otros dos veredictos no exigen nota y siguen disponibles.
    expect(screen.getAllByRole('button', { name: /adecuada/i })[0]).not.toBeDisabled()
  })

  it('should_enable_the_bad_verdict_once_the_note_is_written', async () => {
    const mutate = vi.fn()
    vi.mocked(useReviewInteractionApiV1HubFeedbackInteractionsInteractionIdReviewPatch).mockReturnValue(
      { mutate, isPending: false } as any,
    )

    renderPage()
    await waitFor(() => screen.getByText('How does Python work?'))

    fireEvent.change(screen.getAllByLabelText('hub.reports_review_note')[0], {
      target: { value: 'La respuesta cita un artículo derogado' },
    })
    const inadecuada = screen.getAllByRole('button', { name: /inadecuada/i })[0]
    expect(inadecuada).not.toBeDisabled()

    fireEvent.click(inadecuada)

    expect(mutate).toHaveBeenCalledWith(
      expect.objectContaining({
        data: { verdict: 'bad', note: 'La respuesta cita un artículo derogado' },
      }),
      expect.anything(),
    )
  })

  it('should_export_the_verdict_columns_to_csv', async () => {
    let exportado: Blob | null = null
    vi.spyOn(URL, 'createObjectURL').mockImplementation((blob) => {
      exportado = blob as Blob
      return 'blob:mock'
    })
    vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})

    renderPage()
    await waitFor(() => screen.getByText('How does Python work?'))
    fireEvent.click(screen.getByRole('button', { name: /csv/i }))

    // Es lo que Gerencia se lleva a una reunión: si el veredicto no viaja en el CSV, la
    // revisión se queda dentro de la aplicación.
    expect(exportado).not.toBeNull()
    const contenido = await (exportado as unknown as Blob).text()
    expect(contenido).toContain('review_verdict')
    expect(contenido).toContain('review_note')
  })
})
