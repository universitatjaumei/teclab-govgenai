import { describe, it, expect, vi, beforeEach, beforeAll, afterEach } from 'vitest'
import { render, screen, fireEvent, cleanup } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import i18n from '@/shared/i18n'

/**
 * Un hallazgo tiene que explicarse solo (CUR.8).
 *
 * Del usuario, revisando el informe del apartado:
 *
 * > «Se muestran una serie de páginas duplicadas pero solo se menciona una. Se deberían mostrar las
 * > dos para poder analizar si están duplicadas o no. Cuando se dice que están desactualizadas o
 * > potencialmente desactualizadas, se debería decir la razón (que la fecha que se indica como fecha
 * > de actualización es anterior a x años, meses o el criterio que se utilice).»
 *
 * Las dos son la misma carencia: la fila acusa y no da con qué comprobarlo. Un duplicado con una
 * sola URL no se puede juzgar, y «desactualizada» sin la fecha ni el criterio es una etiqueta que
 * hay que creerse.
 */

const SITIO = 's1'

const DESACTUALIZADA = {
  id: 'f-stale',
  finding_type: 'stale',
  severity: 'info' as const,
  status: 'new',
  acciones_permitidas: ['confirmed', 'dismissed'],
  source_url: 'https://www.uji.es/centres/escola-doctorat/organitzacio/',
  detected_at: '2026-08-19T10:00:00Z',
  page_id: 'p1',
  related_page_id: null,
  signal: {
    date: '2021-11-18T00:00:00Z',
    age_days: 1735,
    source: 'page_date',
    owner: 'Escola de Doctorat',
    threshold: 365,
  },
}

const DUPLICADA = {
  id: 'f-dup',
  finding_type: 'duplicate',
  severity: 'warning' as const,
  status: 'new',
  acciones_permitidas: ['confirmed', 'dismissed'],
  source_url: 'https://www.uji.es/estudis/centres/escola-doctorat/base/calendari',
  detected_at: '2026-08-19T10:00:00Z',
  page_id: 'p2',
  related_page_id: 'p3',
  signal: {
    similarity: 1,
    related_url: 'https://www.uji.es/estudis/centres/escola-doctorat/base/calendari/',
    explanation: 'Ambos documentos son idénticos en su contenido y estructura.',
  },
}

const POBRE = {
  id: 'f-thin',
  finding_type: 'thin',
  severity: 'warning' as const,
  status: 'new',
  acciones_permitidas: ['confirmed', 'dismissed'],
  source_url: 'https://www.uji.es/x/',
  detected_at: '2026-08-19T10:00:00Z',
  page_id: 'p4',
  related_page_id: null,
  signal: { token_count: 42, threshold: 120 },
}

const ROTA = {
  id: 'f-err',
  finding_type: 'crawl_error',
  severity: 'warning' as const,
  status: 'new',
  acciones_permitidas: ['confirmed', 'dismissed'],
  source_url: 'https://www.uji.es/roto/',
  detected_at: '2026-08-19T10:00:00Z',
  page_id: 'p5',
  related_page_id: null,
  signal: { kind: 'not_found', attempts: 3, error_message: 'HTTP 404' },
}

const HALLAZGOS = [DESACTUALIZADA, DUPLICADA, POBRE, ROTA]

vi.mock('@/shared/api/generated/hub-sites/hub-sites', () => ({
  useListSites: () => ({ data: [{ id: SITIO, name: 'Escola de Doctorat' }], isLoading: false }),
  useGetPageContent: () => ({ data: undefined, isLoading: false }),
}))

vi.mock('@/shared/api/generated/hub-content-quality/hub-content-quality', () => ({
  useListSiteFindings: vi.fn(() => ({ data: HALLAZGOS, isLoading: false })),
  useTransitionFinding: () => ({ mutate: vi.fn() }),
  getListSiteFindingsQueryKey: () => ['findings'],
  useListContentGaps: () => ({ data: [], isLoading: false }),
  useAnalyzeContentGaps: () => ({ mutate: vi.fn(), isPending: false }),
}))

vi.mock('@/shared/api/generated/hub-chatbots/hub-chatbots', () => ({
  useOpcionesDeGrafoApiV1HubChatbotsOpcionesDeGrafoGet: () => ({ data: { perfiles: [{ nombre: 'PUBLIC_KB_RICH', configurable: true }], modos: [{ nombre: 'RAG' }, { nombre: 'MD_LONG_CONTEXT' }, { nombre: 'MD_AGENT_SELECTOR' }], estrategias: { retrieval: [], merge: [], template: [], language: [] }, ejes: ['retrieval', 'merge', 'template', 'language'] } }),
  useListChatbotsApiV1HubChatbotsGet: () => ({ data: [], isLoading: false }),
}))

beforeAll(async () => {
  await i18n.changeLanguage('es')
})

afterEach(cleanup)
beforeEach(() => vi.clearAllMocks())

async function pantalla() {
  const { FindingsPage } = await import('../FindingsPage')
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={qc}><FindingsPage /></QueryClientProvider>)
  fireEvent.change(screen.getAllByRole('combobox')[0], { target: { value: SITIO } })
  await screen.findByTestId('enlace-f-stale')
}

describe('un duplicado enseña las dos páginas', () => {
  it('la segunda URL también es un enlace, y a la vista', async () => {
    await pantalla()

    const segundo = screen.getByTestId('enlace-relacionada-f-dup')
    expect(segundo).toHaveAttribute('href', DUPLICADA.signal.related_url)
    expect(segundo).toHaveAttribute('target', '_blank')
  })

  it('se puede leer el texto guardado de las dos, que es con lo que se juzga', async () => {
    await pantalla()

    expect(screen.getByTestId('btn-ver-contenido-f-dup')).toBeInTheDocument()
    expect(screen.getByTestId('btn-ver-relacionada-f-dup')).toBeInTheDocument()
  })

  it('un hallazgo de una sola página no inventa una segunda', async () => {
    await pantalla()

    expect(screen.queryByTestId('enlace-relacionada-f-stale')).not.toBeInTheDocument()
    expect(screen.queryByTestId('btn-ver-relacionada-f-stale')).not.toBeInTheDocument()
  })
})

describe('cada hallazgo dice por qué lo es', () => {
  it('una desactualizada da su fecha, su antigüedad y el criterio del sitio', async () => {
    await pantalla()

    const razon = screen.getByTestId('razon-f-stale').textContent ?? ''
    expect(razon).toContain('2021')       // la fecha que publica el portal
    expect(razon).toContain('1735')       // los días que lleva sin tocarse
    expect(razon).toContain('365')        // el criterio con el que se juzga
  })

  it('una pobre dice cuántos tokens tiene y cuántos pide el sitio', async () => {
    await pantalla()

    const razon = screen.getByTestId('razon-f-thin').textContent ?? ''
    expect(razon).toContain('42')
    expect(razon).toContain('120')
  })

  it('una duplicada trae la explicación del modelo y su parecido', async () => {
    await pantalla()

    const razon = screen.getByTestId('razon-f-dup').textContent ?? ''
    expect(razon).toContain('idénticos')
    expect(razon).toContain('100')  // similitud 1 → 100 %
  })

  it('una rota dice qué pasó y cuántas veces se intentó', async () => {
    await pantalla()

    const razon = screen.getByTestId('razon-f-err').textContent ?? ''
    expect(razon).toMatch(/no se encontr|404/i)
    expect(razon).toContain('3')
  })

  it('un hallazgo sin señal no deja la celda con «undefined»', async () => {
    // Los hallazgos de antes de CUR.8 pueden no traer umbral: la fila no puede mentir ni romperse.
    const { razonDelHallazgo } = await import('../razonDelHallazgo')

    expect(razonDelHallazgo({ finding_type: 'stale', signal: {} }, (k: string) => k)).not.toContain(
      'undefined',
    )
  })
})

describe('la cola enseña lo que sigue pidiendo trabajo (CUR.9)', () => {
  /**
   * La reconciliación retira los hallazgos que ya no se detectan, pero si la pantalla los sigue
   * listando con la etiqueta «Resuelto» no hemos resuelto nada: en el apartado real serían 109 filas
   * caducadas entre las vivas. La cola por defecto es lo **abierto**, y lo cerrado se elige.
   */
  it('pide solo los abiertos si nadie ha elegido estado', async () => {
    const { useListSiteFindings } = await import(
      '@/shared/api/generated/hub-content-quality/hub-content-quality'
    )
    await pantalla()

    const parametros = (useListSiteFindings as unknown as ReturnType<typeof vi.fn>).mock.calls.at(-1)
    expect(parametros?.[1]).toEqual(expect.objectContaining({ status: 'open' }))
  })

  it('ofrece ver los retirados, que no es lo mismo que esconderlos', async () => {
    await pantalla()

    const opciones = [...(screen.getAllByRole('combobox')[1] as HTMLSelectElement).options].map(
      (o) => o.value,
    )
    expect(opciones).toContain('resolved')
    expect(opciones).toContain('')  // «todos», para poder auditar el histórico
  })
})
