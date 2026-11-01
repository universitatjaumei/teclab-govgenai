import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { SitesPage } from '../SitesPage'

/**
 * Dar de alta un apartado con su filtro y su cortesía (RAS.5).
 *
 * La decisión operativa del bloque es **un sitio por apartado** —cada apartado del portal tiene un
 * responsable distinto y un informe del portal completo no lo lee nadie—, y eso se expresa con
 * `url_regex_filter`. El formulario no tenía ese campo ni ninguno de los del rastreo, así que la
 * única forma de usarlo como tiene sentido era escribir en la base a mano.
 */

const createMutate = vi.fn()

vi.mock('@/shared/api/generated/hub-sites/hub-sites', () => ({
  useListSites: () => ({ data: [], isLoading: false }),
  useCreateSite: () => ({ mutate: createMutate, isPending: false }),
  useDeleteSite: () => ({ mutate: vi.fn() }),
  useTriggerSiteCrawl: () => ({ mutate: vi.fn() }),

  // #358 — la confirmación de borrado cuenta las páginas del sitio.

  useListSitePages: vi.fn(() => ({ data: undefined })),
  // CUR.6 — el formulario de alta ofrece el reconocimiento previo del apartado.
  useReconnoiterSite: () => ({ mutateAsync: vi.fn(), isPending: false }),
  // CUR.7 — la fila del sitio deja cambiar el alcance del análisis semántico.
  usePatchSite: () => ({ mutate: vi.fn(), isPending: false }),
  getListSitesQueryKey: () => ['sites'],
}))

// DIN.7 — `SitesPage` resuelve de qué organización es el sitio que se crea (sin ella el
// servidor responde 403). El hook se dobla aquí porque este fichero no prueba esa elección:
// la prueba `ElAltaDeSitioDiceSuOrganizacion` sí, y sin el doble la pantalla lanzaría la
// consulta real de organizaciones.
vi.mock('@/shared/organizacion/useOrganizacionElegida', () => ({
  useOrganizacionElegida: () => ({
    organizaciones: [{ id: 'org-1', name: 'Organización' }],
    elegida: 'org-1',
    elegir: vi.fn(),
    hayVarias: false,
  }),
}))


function renderizar() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <SitesPage />
    </QueryClientProvider>,
  )
}

function abrirFormulario() {
  renderizar()
  fireEvent.click(screen.getByTestId('btn-nuevo-sitio'))
}

describe('alta de un apartado del portal', () => {
  beforeEach(() => createMutate.mockClear())

  it('ofrece el filtro de URL para acotar el apartado', () => {
    abrirFormulario()

    expect(screen.getByTestId('campo-url-regex')).toBeInTheDocument()
  })

  it('ofrece la cortesía: pausa y robots.txt', () => {
    abrirFormulario()

    expect(screen.getByTestId('campo-pausa')).toBeInTheDocument()
    expect(screen.getByTestId('campo-robots')).toBeInTheDocument()
  })

  it('la pausa y el respeto a robots vienen puestos por defecto', () => {
    abrirFormulario()

    expect(screen.getByTestId('campo-pausa')).toHaveValue(1)
    expect(screen.getByTestId('campo-robots')).toBeChecked()
  })

  it('manda la configuración del rastreo al crear el sitio', async () => {
    abrirFormulario()

    fireEvent.change(screen.getByTestId('campo-nombre'), {
      target: { value: 'Escola de Doctorat' },
    })
    fireEvent.change(screen.getByTestId('campo-url'), {
      target: { value: 'https://www.uji.es/centres/escola-doctorat/' },
    })
    fireEvent.change(screen.getByTestId('campo-url-regex'), {
      target: { value: '/centres/escola-doctorat/' },
    })
    fireEvent.change(screen.getByTestId('campo-pausa'), { target: { value: '2' } })
    fireEvent.submit(screen.getByTestId('form-sitio'))

    await waitFor(() => expect(createMutate).toHaveBeenCalled())
    const enviado = createMutate.mock.calls[0][0].data
    expect(enviado.crawl_config.url_regex_filter).toBe('/centres/escola-doctorat/')
    expect(enviado.crawl_config.delay_seconds).toBe(2)
    expect(enviado.crawl_config.respect_robots).toBe(true)
  })

  it('ofrece de dónde saca el portal la fecha de cada página', () => {
    // CUR.1 — con esa fecha, «desactualizada» es un dato y no una conjetura sobre el año de la URL.
    abrirFormulario()

    expect(screen.getByTestId('campo-selector-fecha')).toBeInTheDocument()
    expect(screen.getByTestId('campo-formato-fecha')).toHaveValue('%d/%m/%Y')
  })

  it('manda el selector de fecha con la configuración del rastreo', async () => {
    abrirFormulario()

    fireEvent.change(screen.getByTestId('campo-nombre'), { target: { value: 'Escola' } })
    fireEvent.change(screen.getByTestId('campo-url'), {
      target: { value: 'https://www.uji.es/centres/escola-doctorat/' },
    })
    fireEvent.change(screen.getByTestId('campo-selector-fecha'), {
      target: { value: '.clockBarDate' },
    })
    fireEvent.submit(screen.getByTestId('form-sitio'))

    await waitFor(() => expect(createMutate).toHaveBeenCalled())
    const enviado = createMutate.mock.calls[0][0].data
    expect(enviado.crawl_config.content_date_selector).toBe('.clockBarDate')
    expect(enviado.crawl_config.content_date_format).toBe('%d/%m/%Y')
  })

  it('un filtro que no es una expresión regular válida se avisa antes de enviarlo', async () => {
    abrirFormulario()

    fireEvent.change(screen.getByTestId('campo-nombre'), { target: { value: 'Mal filtro' } })
    fireEvent.change(screen.getByTestId('campo-url'), {
      target: { value: 'https://www.uji.es/x/' },
    })
    fireEvent.change(screen.getByTestId('campo-url-regex'), {
      target: { value: '/centres/[escola' },
    })
    fireEvent.submit(screen.getByTestId('form-sitio'))

    expect(await screen.findByTestId('error-url-regex')).toBeInTheDocument()
    expect(createMutate).not.toHaveBeenCalled()
  })
})
