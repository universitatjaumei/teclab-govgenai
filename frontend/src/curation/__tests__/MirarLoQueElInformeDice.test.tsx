import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { FindingsPage } from '../FindingsPage'
import { PageContentDialog } from '../PageContentDialog'

/**
 * Poder mirar lo que el informe dice (CUR.4).
 *
 * Del usuario, tras revisar el informe del apartado: «sería muy útil que el listado de hallazgos
 * fueran url clickables, que se abrieran en una página distinta para no perder la navegación. Ahora
 * hay que copiar y pegar». Y del mismo mensaje: el «+4 más» de los grupos tampoco es clickable.
 *
 * La tercera es la que más falta hacía y no estaba pedida así: **ver el texto guardado** de una
 * página, que es lo que iría al corpus y lo único que permite juzgar si un hallazgo es cierto o si
 * el recorte de plantilla de CUR.3 se ha comido algo.
 */

const HALLAZGOS = [
  {
    id: 'f1',
    finding_type: 'stale',
    severity: 'info' as const,
    status: 'new',
    acciones_permitidas: ['confirmed', 'dismissed'],
    source_url: 'https://www.uji.es/centres/escola-doctorat/info-general/organitzacio/',
    detected_at: '2026-08-19T10:00:00Z',
    page_id: 'p1',
    signal: { date: '2015-04-10T00:00:00Z', source: 'page_date', owner: 'Escola de Doctorat' },
  },
  {
    id: 'f2',
    finding_type: 'version_series',
    severity: 'info' as const,
    status: 'new',
    acciones_permitidas: ['confirmed', 'dismissed'],
    source_url: 'https://www.uji.es/centres/escola-doctorat/normativa/acordacded/2025/',
    detected_at: '2026-08-19T10:00:00Z',
    page_id: null,
    signal: {
      count: 6,
      versions: [
        { url: 'https://www.uji.es/x/2025/', date: '2025-01-01T00:00:00Z' },
        { url: 'https://www.uji.es/x/2024/', date: '2024-01-01T00:00:00Z' },
        { url: 'https://www.uji.es/x/2023/', date: '2023-01-01T00:00:00Z' },
        { url: 'https://www.uji.es/x/2022/', date: '2022-01-01T00:00:00Z' },
        { url: 'https://www.uji.es/x/2021/', date: '2021-01-01T00:00:00Z' },
        { url: 'https://www.uji.es/x/2020/', date: '2020-01-01T00:00:00Z' },
      ],
    },
  },
]

vi.mock('@/shared/api/generated/hub-sites/hub-sites', () => ({
  useListSites: () => ({
    data: [{ id: 's1', name: 'Escola de Doctorat' }],
    isLoading: false,
  }),
  useGetPageContent: () => ({
    data: {
      id: 'p1',
      url: 'https://www.uji.es/centres/escola-doctorat/info-general/organitzacio/',
      title: 'Organització',
      status: 'active',
      content: 'Organització de l Escola de Doctorat\nLa comissió es reuneix cada mes.',
      token_count: 24,
      owner: 'Escola de Doctorat',
      published_at: '2015-04-10T00:00:00Z',
      render_signals: [],
    },
    isLoading: false,
  }),
}))

vi.mock('@/shared/api/generated/hub-content-quality/hub-content-quality', () => ({
  useListSiteFindings: () => ({ data: HALLAZGOS, isLoading: false }),
  useTransitionFinding: () => ({ mutate: vi.fn() }),
  getListSiteFindingsQueryKey: () => ['findings'],
  useListContentGaps: () => ({ data: [], isLoading: false }),
  useAnalyzeContentGaps: () => ({ mutate: vi.fn(), isPending: false }),
}))

// El nombre del hook generado, tal cual: `ContentGapsPanel` comparte pantalla con los hallazgos.
vi.mock('@/shared/api/generated/hub-chatbots/hub-chatbots', () => ({
  useOpcionesDeGrafoApiV1HubChatbotsOpcionesDeGrafoGet: () => ({ data: { perfiles: [{ nombre: 'PUBLIC_KB_RICH', configurable: true }], modos: [{ nombre: 'RAG' }, { nombre: 'MD_LONG_CONTEXT' }, { nombre: 'MD_AGENT_SELECTOR' }], estrategias: { retrieval: [], merge: [], template: [], language: [] }, ejes: ['retrieval', 'merge', 'template', 'language'] } }),
  useListChatbotsApiV1HubChatbotsGet: () => ({ data: [], isLoading: false }),
}))

function renderizar(elemento: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{elemento}</QueryClientProvider>)
}

function elegirElSitio() {
  renderizar(<FindingsPage />)
  const selector = screen.getAllByRole('combobox')[0]
  fireEvent.change(selector, { target: { value: 's1' } })
}

describe('mirar lo que el informe dice', () => {
  beforeEach(() => vi.clearAllMocks())

  it('la URL de cada hallazgo es un enlace que abre en otra pestaña', () => {
    elegirElSitio()

    const enlace = screen.getByTestId('enlace-f1')
    expect(enlace).toHaveAttribute('href', HALLAZGOS[0].source_url)
    expect(enlace).toHaveAttribute('target', '_blank')
    // Sin `noopener` la página abierta puede manipular la que la abrió.
    expect(enlace.getAttribute('rel')).toContain('noopener')
  })

  it('un grupo enseña sus versiones al desplegarlo, sin salir de la página', () => {
    elegirElSitio()

    // De inicio no están todas: seis versiones no caben en la fila.
    expect(screen.queryByText(/2020/)).not.toBeInTheDocument()

    fireEvent.click(screen.getByTestId('btn-desplegar-f2'))

    expect(screen.getByTestId('versiones-f2')).toBeInTheDocument()
    expect(screen.getAllByRole('link', { name: /uji\.es\/x\// }).length).toBe(6)
  })

  it('cada versión del grupo lleva su fecha, que es lo que se compara', () => {
    elegirElSitio()
    fireEvent.click(screen.getByTestId('btn-desplegar-f2'))

    const versiones = screen.getByTestId('versiones-f2')
    expect(versiones.textContent).toContain('2025')
    expect(versiones.textContent).toContain('2020')
  })

  it('se puede abrir el texto guardado de la página del hallazgo', async () => {
    elegirElSitio()

    fireEvent.click(screen.getByTestId('btn-ver-contenido-f1'))

    expect(await screen.findByTestId('contenido-de-la-pagina')).toBeInTheDocument()
    expect(screen.getByTestId('contenido-de-la-pagina').textContent).toContain(
      'La comissió es reuneix cada mes.',
    )
  })

  it('un hallazgo de grupo no ofrece ver contenido, porque no habla de una página', () => {
    elegirElSitio()

    expect(screen.queryByTestId('btn-ver-contenido-f2')).not.toBeInTheDocument()
  })
})

describe('el visor del texto guardado', () => {
  it('dice que es el texto que iría al corpus, no la página original', () => {
    renderizar(<PageContentDialog pageId="p1" onClose={() => {}} />)

    expect(screen.getByTestId('aviso-texto-guardado')).toBeInTheDocument()
  })

  it('enlaza a la página original para poder comparar', () => {
    renderizar(<PageContentDialog pageId="p1" onClose={() => {}} />)

    const enlace = screen.getByTestId('enlace-pagina-original')
    expect(enlace).toHaveAttribute('target', '_blank')
  })

  it('muestra quién la mantiene y cuándo la publicó', () => {
    renderizar(<PageContentDialog pageId="p1" onClose={() => {}} />)

    const cabecera = screen.getByTestId('cabecera-pagina').textContent ?? ''
    expect(cabecera).toContain('Escola de Doctorat')
    expect(cabecera).toContain('2015')
  })

  it('se cierra', async () => {
    const cerrar = vi.fn()
    renderizar(<PageContentDialog pageId="p1" onClose={cerrar} />)

    fireEvent.click(screen.getByTestId('btn-cerrar-contenido'))

    await waitFor(() => expect(cerrar).toHaveBeenCalled())
  })
})
