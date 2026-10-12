import { describe, it, expect, vi, beforeEach } from 'vitest'
import { act, render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { DocumentsPage } from '../DocumentsPage'
import {
  useListDocumentsApiV1HubIngestionChatbotIdDocumentsGet,
  useGetDocumentApiV1HubIngestionChatbotIdDocumentsDocumentIdGet,
  useDeleteDocumentApiV1HubIngestionChatbotIdDocumentsDocumentIdDelete,
  useGetIngestionJobsApiV1HubIngestionChatbotIdJobsGet,
  useDeleteIngestionJobApiV1HubIngestionChatbotIdJobsJobIdDelete,
  useUploadDocumentApiV1HubIngestionUploadPost,
  useClearChatbotCollectionApiV1HubIngestionChatbotIdChunksDelete,
  useGetDocumentCopiesApiV1HubIngestionChatbotIdDocumentsDocumentIdCopiasGet,
} from '@/shared/api/generated/hub-ingestion/hub-ingestion'
import {
  useListChatbotsApiV1HubChatbotsGet,
  useRecalculateCorpusEndpointApiV1HubChatbotsChatbotIdRecalculateCorpusPost,
} from '@/shared/api/generated/hub-chatbots/hub-chatbots'
import type { HubDocumentOut } from '@/shared/api/generated/model'

// El doble resuelve contra el diccionario castellano real, no devuelve la clave: desde CAL.4
// hay etiquetas que sólo existen en `admin.json` (las de `LANGUAGE_OPTIONS` y
// `RETRIEVAL_LABEL_KEYS`), y un doble que devolviera la clave escondería que falta traducir.
vi.mock('react-i18next', async () => {
  const es = (await import('@/shared/i18n/locales/es/admin.json')).default as Record<string, unknown>
  const resolver = (clave: string) =>
    clave.split('.').reduce<unknown>((o, p) => (o as Record<string, unknown>)?.[p], es)
  // Resuelve también plurales (`_one`/`_other`) e interpolación de `{{count}}`: i18next real
  // lo hace, y un doble que no lo hiciera obligaría a escribir el producto para el doble.
  const traducir = (key: string, arg?: string | { count?: number }) => {
    if (arg && typeof arg === 'object' && typeof arg.count === 'number') {
      const sufijo = arg.count === 1 ? '_one' : '_other'
      const plantilla = (resolver(`${key}${sufijo}`) ?? resolver(key)) as string | undefined
      return plantilla?.replace('{{count}}', String(arg.count)) ?? key
    }
    return (resolver(key) as string) ?? (arg as string | undefined) ?? key
  }
  return {
    useTranslation: () => ({
      t: traducir,
      i18n: { changeLanguage: vi.fn() },
    }),
  }
})

vi.mock('lucide-react', () => ({
  UploadCloud: () => <div data-testid="upload-icon" />,
  Trash2: () => <div data-testid="trash-icon" />,
  FileText: () => <div data-testid="file-icon" />,
  AlertCircle: () => <div data-testid="alert-icon" />,
  CheckCircle2: () => <div data-testid="check-icon" />,
  Clock: () => <div data-testid="clock-icon" />,
  Loader2: () => <div data-testid="loader-icon" />,
  Link: () => <div data-testid="link-icon" />,
  Globe: () => <div data-testid="globe-icon" />,
  RefreshCw: () => <div data-testid="refresh-icon" />,
  Eye: () => <div data-testid="eye-icon" />,
  FileUp: () => <div data-testid="file-up-icon" />,
  ChevronDown: () => <div data-testid="chevron-down" />,
  ChevronUp: () => <div data-testid="chevron-up" />,
  Upload: () => <div data-testid="upload-subst-icon" />,
}))

vi.mock('react-dropzone', () => ({
  useDropzone: () => ({
    getRootProps: () => ({}),
    getInputProps: () => ({ type: 'file', accept: 'application/pdf,.pdf' }),
    isDragActive: false,
  }),
}))

vi.mock('@/shared/api/generated/hub-chatbots/hub-chatbots', () => ({
  useOpcionesDeGrafoApiV1HubChatbotsOpcionesDeGrafoGet: () => ({ data: { perfiles: [{ nombre: 'PUBLIC_KB_RICH', configurable: true }], modos: [{ nombre: 'RAG' }, { nombre: 'MD_LONG_CONTEXT' }, { nombre: 'MD_AGENT_SELECTOR' }], estrategias: { retrieval: [], merge: [], template: [], language: [] }, ejes: ['retrieval', 'merge', 'template', 'language'] } }),
  useListChatbotsApiV1HubChatbotsGet: vi.fn(),
  useRecalculateCorpusEndpointApiV1HubChatbotsChatbotIdRecalculateCorpusPost: vi.fn(),
  getListChatbotsApiV1HubChatbotsGetQueryKey: vi.fn(() => ['/api/v1/hub/chatbots']),
}))

vi.mock('@/shared/api/generated/hub-ingestion/hub-ingestion', () => ({
  useListDocumentsApiV1HubIngestionChatbotIdDocumentsGet: vi.fn(),
  useGetDocumentApiV1HubIngestionChatbotIdDocumentsDocumentIdGet: vi.fn(),
  useDeleteDocumentApiV1HubIngestionChatbotIdDocumentsDocumentIdDelete: vi.fn(),
  useGetIngestionJobsApiV1HubIngestionChatbotIdJobsGet: vi.fn(),
  useDeleteIngestionJobApiV1HubIngestionChatbotIdJobsJobIdDelete: vi.fn(),
  useUploadDocumentApiV1HubIngestionUploadPost: vi.fn(),
  useClearChatbotCollectionApiV1HubIngestionChatbotIdChunksDelete: vi.fn(),
  useGetDocumentCopiesApiV1HubIngestionChatbotIdDocumentsDocumentIdCopiasGet: vi.fn(),
  getListDocumentsApiV1HubIngestionChatbotIdDocumentsGetQueryKey: vi.fn(
    (id: string) => [`/api/v1/hub/ingestion/${id}/documents`],
  ),
  getGetIngestionJobsApiV1HubIngestionChatbotIdJobsGetQueryKey: vi.fn(
    (id: string) => [`/api/v1/hub/ingestion/${id}/jobs`],
  ),
}))

vi.mock('@/components/ui/progress', () => ({
  Progress: () => <div data-testid="progress" />,
}))

const CHATBOT = {
  id: 'bot-1',
  name: 'Bot Test',
  organizacion_id: 'client-1',
  llm_config_id: 'llm-1',
  system_prompt: '',
  sources: [],
  is_active: true,
  retrieval_mode: 'vector' as const,
  created_at: '2024-01-01T00:00:00Z',
  updated_at: '2024-01-01T00:00:00Z',
}

const DOCS_ES_CA: HubDocumentOut[] = [
  {
    id: 'doc-es',
    chatbot_id: 'bot-1',
    title: 'Normativa Española',
    canonical_url: 'https://example.com/normativa-es.pdf',
    language: 'es',
    source_kind: 'upload',
    token_count: 1200,
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z',
  },
  {
    id: 'doc-ca',
    chatbot_id: 'bot-1',
    title: 'Normativa Catalana',
    canonical_url: 'https://example.com/normativa-ca.pdf',
    language: 'ca',
    source_kind: 'crawler',
    token_count: 3500,
    created_at: '2024-01-02T00:00:00Z',
    updated_at: '2024-01-02T00:00:00Z',
  },
]

const deleteDocMutate = vi.fn()
const recalculateMutate = vi.fn()

/** Doble de un `useMutation` de Orval: sólo lo que la página consulta. */
const mutationDouble = (mutate = vi.fn()) => ({ mutate, isPending: false }) as any

const createWrapper = () => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  )
}

/** Documentos que devuelve el hook generado, en la forma del contrato. */
function mockDocuments(documents: HubDocumentOut[]) {
  vi.mocked(useListDocumentsApiV1HubIngestionChatbotIdDocumentsGet).mockReturnValue({
    data: { documents },
    isLoading: false,
  } as any)
}

describe('DocumentsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(useListChatbotsApiV1HubChatbotsGet).mockReturnValue({ data: [CHATBOT] } as any)
    mockDocuments(DOCS_ES_CA)
    vi.mocked(useGetDocumentApiV1HubIngestionChatbotIdDocumentsDocumentIdGet).mockReturnValue({
      data: undefined,
      isLoading: false,
    } as any)
    vi.mocked(useGetIngestionJobsApiV1HubIngestionChatbotIdJobsGet).mockReturnValue({
      data: { jobs: [] },
      isLoading: false,
    } as any)
    vi.mocked(useDeleteDocumentApiV1HubIngestionChatbotIdDocumentsDocumentIdDelete)
      .mockReturnValue(mutationDouble(deleteDocMutate))
    vi.mocked(useRecalculateCorpusEndpointApiV1HubChatbotsChatbotIdRecalculateCorpusPost)
      .mockReturnValue(mutationDouble(recalculateMutate))
    vi.mocked(useDeleteIngestionJobApiV1HubIngestionChatbotIdJobsJobIdDelete)
      .mockReturnValue(mutationDouble())
    vi.mocked(useUploadDocumentApiV1HubIngestionUploadPost).mockReturnValue(mutationDouble())
    vi.mocked(useClearChatbotCollectionApiV1HubIngestionChatbotIdChunksDelete)
      .mockReturnValue(mutationDouble())
    vi.mocked(useGetDocumentCopiesApiV1HubIngestionChatbotIdDocumentsDocumentIdCopiasGet)
      .mockReturnValue({ data: undefined, isLoading: false } as any)
  })

  it('should_list_documents_with_language_badge', async () => {
    render(<DocumentsPage />, { wrapper: createWrapper() })

    expect(await screen.findByText('Normativa Española')).toBeInTheDocument()
    expect(screen.getByText('Normativa Catalana')).toBeInTheDocument()
    // Las etiquetas de idioma salen en varios sitios (badge + opción de filtro).
    expect(screen.getAllByText('ES').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('CA').length).toBeGreaterThanOrEqual(1)
  })

  it('should_filter_table_by_language', async () => {
    render(<DocumentsPage />, { wrapper: createWrapper() })
    await screen.findByText('Normativa Española')

    const select = screen.getByLabelText('Filtrar por idioma')
    fireEvent.change(select, { target: { value: 'es' } })

    expect(screen.getByText('Normativa Española')).toBeInTheDocument()
    expect(screen.queryByText('Normativa Catalana')).not.toBeInTheDocument()
  })

  it('should_show_two_versions_of_same_document_in_different_languages', async () => {
    mockDocuments([
      { ...DOCS_ES_CA[0], title: 'Normativa v2 ES', canonical_url: 'https://example.com/norm.pdf', language: 'es' },
      { ...DOCS_ES_CA[1], id: 'doc-ca-2', title: 'Normativa v2 CA', canonical_url: 'https://example.com/norm.pdf', language: 'ca' },
    ])

    render(<DocumentsPage />, { wrapper: createWrapper() })

    expect(await screen.findByText('Normativa v2 ES')).toBeInTheDocument()
    expect(screen.getByText('Normativa v2 CA')).toBeInTheDocument()
    expect(screen.getAllByText('ES').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('CA').length).toBeGreaterThanOrEqual(1)
  })

  it('should_show_source_kind_icon', async () => {
    render(<DocumentsPage />, { wrapper: createWrapper() })
    await screen.findByText('Normativa Española')

    // upload → icono de fichero, crawler → icono de globo
    expect(screen.getAllByTestId('file-icon').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByTestId('globe-icon').length).toBeGreaterThanOrEqual(1)
  })

  it('should_show_total_tokens_summary_banner', async () => {
    render(<DocumentsPage />, { wrapper: createWrapper() })
    await screen.findByText('Normativa Española')

    // Banner con el modo de retrieval + tokens totales (1200 + 3500 = 4700 → «4.7 k»)
    expect(screen.getByText(/Modo de retrieval/i)).toBeInTheDocument()
    expect(screen.getByText(/Vectorial/i)).toBeInTheDocument()
    expect(screen.getByText(/4\.7 k tokens/i)).toBeInTheDocument()
  })

  it('should_open_preview_modal_on_view_action', async () => {
    vi.mocked(useGetDocumentApiV1HubIngestionChatbotIdDocumentsDocumentIdGet).mockReturnValue({
      data: { ...DOCS_ES_CA[0], markdown_content: '# Normativa\n\nContenido de prueba.' },
      isLoading: false,
    } as any)

    render(<DocumentsPage />, { wrapper: createWrapper() })
    await screen.findByText('Normativa Española')

    fireEvent.click(screen.getAllByTestId('eye-icon')[0].closest('button')!)

    // El <pre> contiene el markdown completo; se busca por fragmento.
    expect(await screen.findByText(/# Normativa/)).toBeInTheDocument()
  })

  it('should_delete_document_with_confirm', async () => {
    render(<DocumentsPage />, { wrapper: createWrapper() })
    await screen.findByText('Normativa Española')

    const firstDocTrash = screen.getAllByTestId('trash-icon').find(
      el => el.closest('button')?.title === 'Eliminar documento',
    )
    expect(firstDocTrash).toBeDefined()
    fireEvent.click(firstDocTrash!.closest('button')!)

    expect(await screen.findByText('¿Eliminar documento?')).toBeInTheDocument()
    fireEvent.click(screen.getByText('Sí, eliminar'))

    // Las variables del hook generado son las del contrato, no una firma propia.
    // DER.2 añadió `params`: el borrado en cascada se pide, no se hereda.
    await waitFor(() => {
      expect(deleteDocMutate).toHaveBeenCalledWith({
        chatbotId: 'bot-1',
        documentId: 'doc-es',
        params: { en_todos_los_chatbots: false },
      })
    })
  })

  it('should_show_recalculate_button_when_documents_exist', async () => {
    render(<DocumentsPage />, { wrapper: createWrapper() })
    await screen.findByText('Normativa Española')
    expect(screen.getByRole('button', { name: /recalcular corpus/i })).toBeInTheDocument()
  })

  it('should_open_recalculate_confirmation_modal', async () => {
    render(<DocumentsPage />, { wrapper: createWrapper() })
    await screen.findByText('Normativa Española')

    fireEvent.click(screen.getByRole('button', { name: /recalcular corpus/i }))
    expect(await screen.findByText('¿Recalcular corpus?')).toBeInTheDocument()
  })

  it('should_call_recalculate_corpus_on_confirm', async () => {
    render(<DocumentsPage />, { wrapper: createWrapper() })
    await screen.findByText('Normativa Española')

    fireEvent.click(screen.getByRole('button', { name: /recalcular corpus/i }))
    fireEvent.click(await screen.findByRole('button', { name: /sí, recalcular/i }))

    await waitFor(() => {
      expect(recalculateMutate).toHaveBeenCalledWith({ chatbotId: 'bot-1' })
    })
  })

  // ───────────────────── DER.2 — borrar una norma que vive en varios ─────────────────────
  //
  // Con el documento duplicado por chatbot, «borrar la norma» es ambiguo: puede significar
  // quitarla de este asistente o retirarla del corpus de la organización. El aviso sale
  // ANTES de confirmar — decirlo después convierte la información en un lamento.

  it('should_warn_how_many_chatbots_hold_the_document_before_deleting', async () => {
    vi.mocked(useGetDocumentCopiesApiV1HubIngestionChatbotIdDocumentsDocumentIdCopiasGet)
      .mockReturnValue({
        data: { copias_en_otros_chatbots: 2, chatbots_afectados: ['bot-2', 'bot-3'] },
        isLoading: false,
      } as any)

    render(<DocumentsPage />, { wrapper: createWrapper() })
    await screen.findByText('Normativa Española')

    fireEvent.click(screen.getAllByRole('button', { name: /eliminar documento/i })[0])

    expect(await screen.findByTestId('copias-aviso')).toHaveTextContent('2')
  })

  it('should_not_warn_when_no_other_chatbot_holds_it', async () => {
    vi.mocked(useGetDocumentCopiesApiV1HubIngestionChatbotIdDocumentsDocumentIdCopiasGet)
      .mockReturnValue({
        data: { copias_en_otros_chatbots: 0, chatbots_afectados: [] },
        isLoading: false,
      } as any)

    render(<DocumentsPage />, { wrapper: createWrapper() })
    await screen.findByText('Normativa Española')

    fireEvent.click(screen.getAllByRole('button', { name: /eliminar documento/i })[0])

    await screen.findByText(/eliminar documento/i)
    expect(screen.queryByTestId('copias-aviso')).not.toBeInTheDocument()
  })

  it('should_delete_only_in_this_chatbot_by_default', async () => {
    vi.mocked(useGetDocumentCopiesApiV1HubIngestionChatbotIdDocumentsDocumentIdCopiasGet)
      .mockReturnValue({
        data: { copias_en_otros_chatbots: 1, chatbots_afectados: ['bot-2'] },
        isLoading: false,
      } as any)

    render(<DocumentsPage />, { wrapper: createWrapper() })
    await screen.findByText('Normativa Española')

    fireEvent.click(screen.getAllByRole('button', { name: /eliminar documento/i })[0])
    fireEvent.click(await screen.findByRole('button', { name: /sí, eliminar/i }))

    // Un borrado en cascada implícito sobre corpus normativo no puede ser el defecto.
    await waitFor(() => {
      expect(deleteDocMutate).toHaveBeenCalledWith(
        expect.objectContaining({ params: { en_todos_los_chatbots: false } }),
      )
    })
  })

  it('should_delete_in_all_chatbots_when_explicitly_asked', async () => {
    vi.mocked(useGetDocumentCopiesApiV1HubIngestionChatbotIdDocumentsDocumentIdCopiasGet)
      .mockReturnValue({
        data: { copias_en_otros_chatbots: 1, chatbots_afectados: ['bot-2'] },
        isLoading: false,
      } as any)

    render(<DocumentsPage />, { wrapper: createWrapper() })
    await screen.findByText('Normativa Española')

    fireEvent.click(screen.getAllByRole('button', { name: /eliminar documento/i })[0])
    fireEvent.click(await screen.findByRole('checkbox', { name: /todos los chatbots/i }))
    fireEvent.click(screen.getByRole('button', { name: /sí, eliminar/i }))

    await waitFor(() => {
      expect(deleteDocMutate).toHaveBeenCalledWith(
        expect.objectContaining({ params: { en_todos_los_chatbots: true } }),
      )
    })
  })

  it('should_not_render_retired_sources_tab', async () => {
    // El panel de fuentes web mandaba sobre `/hub/ingestion/{id}/sources`, un endpoint
    // retirado en 0196ff5 junto con su tabla. Su sustituto vivo es /admin/sites.
    render(<DocumentsPage />, { wrapper: createWrapper() })
    await screen.findByText('Normativa Española')

    expect(screen.queryByText('Fuentes web')).not.toBeInTheDocument()
    expect(screen.queryByText('Añadir fuente web')).not.toBeInTheDocument()
    expect(screen.queryByText('Asistente')).not.toBeInTheDocument()
  })

  describe('una subida rechazada dice por qué', () => {
    // El servidor manda el motivo en `detail` y la página enseñaba el mensaje genérico de la
    // petición («Request failed with status code 422»): quien subió un documento mal
    // preparado no sabía qué corregir.
    /** Falla la subida como lo hace el cliente generado: un error con `response.data`. */
    async function rechazarSubida(status: number, detail: unknown) {
      render(<DocumentsPage />, { wrapper: createWrapper() })
      await screen.findByText('Normativa Española')
      const { mutation } = vi.mocked(useUploadDocumentApiV1HubIngestionUploadPost).mock.calls.at(-1)![0] as any
      const fallo = Object.assign(new Error(`Request failed with status code ${status}`), {
        response: { status, data: { detail } },
      })
      act(() => mutation.onError(fallo))
    }

    it('nombra el contrato y los campos que fallan', async () => {
      await rechazarSubida(422, {
        code: 'CORPUS_CONTRACT_VIOLATION',
        message: 'El front-matter no cumple el contrato del corpus.',
        problemas: [
          { campo: 'title', problema: 'Field required' },
          { campo: 'estat_vigencia', problema: 'Input should be vigent or derogat' },
        ],
      })

      const aviso = await screen.findByText(/no cumple el contrato del corpus/)
      expect(aviso.textContent).toContain('title: Field required')
      expect(aviso.textContent).toContain('estat_vigencia: Input should be vigent or derogat')
      expect(screen.queryByText(/Request failed/)).not.toBeInTheDocument()
    })

    it('con un código sin traducir enseña el mensaje del servidor', async () => {
      await rechazarSubida(422, {
        code: 'FAQ_FORMAT_INVALID',
        message: 'La pregunta 3 no lleva respuesta.',
      })

      expect(await screen.findByText('La pregunta 3 no lleva respuesta.')).toBeInTheDocument()
    })

    it('sin detalle reconocible se queda el mensaje de la petición', async () => {
      await rechazarSubida(500, undefined)

      expect(await screen.findByText('Request failed with status code 500')).toBeInTheDocument()
    })
  })
})
