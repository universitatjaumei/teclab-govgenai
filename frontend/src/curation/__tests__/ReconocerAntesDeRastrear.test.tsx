import { describe, it, expect, vi, beforeEach, beforeAll, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import i18n from '@/shared/i18n'

/**
 * Cuántas páginas tiene esto, antes de comprometerse (CUR.6).
 *
 * Del usuario: «convendría que al dar de alta un nuevo sitio se pudiera generar y descargar un
 * sitemap. De ese modo se podría valorar la extensión del sitio y si conviene hacerlo todo de golpe
 * o por subapartados». La cifra que decide eso es **el tiempo**: con dos segundos de cortesía por
 * página, mil URLs son más de media hora.
 */

const RAIZ = 'https://www.uji.es/centres/escola-doctorat/'

const INFORME = {
  root_url: RAIZ,
  urls_encontradas: 349,
  paginas_sondeadas: 60,
  truncado: true,
  motivo_de_parada: 'max_pages',
  apartados: [
    { apartado: 'base', urls: 300, ejemplos: [`${RAIZ}base/doctorands/`] },
    { apartado: 'info-general', urls: 48, ejemplos: [`${RAIZ}info-general/`] },
    { apartado: '/', urls: 1, ejemplos: [RAIZ] },
  ],
  segundos_por_pagina: 2.4,
  segundos_estimados: 837.6,
  urls_prohibidas: 2,
  no_legibles: 5,
  fallos: 1,
}

const mockReconocer = vi.hoisted(() => ({ mutateAsync: vi.fn(), isPending: false }))

vi.mock('@/shared/api/generated/hub-sites/hub-sites', () => ({
  useListSites: () => ({ data: [], isLoading: false }),
  useCreateSite: () => ({ mutate: vi.fn(), isPending: false }),
  useDeleteSite: () => ({ mutate: vi.fn(), isPending: false }),
  useTriggerSiteCrawl: () => ({ mutate: vi.fn(), isPending: false }),

  // #358 — la confirmación de borrado cuenta las páginas del sitio.

  useListSitePages: vi.fn(() => ({ data: undefined })),
  useUpdateSite: () => ({ mutate: vi.fn(), isPending: false }),
  getListSitesQueryKey: () => ['sites'],
  useReconnoiterSite: () => mockReconocer,
  // CUR.7 — la fila del sitio deja cambiar el alcance del análisis semántico.
  usePatchSite: () => ({ mutate: vi.fn(), isPending: false }),
}))

vi.mock('@/shared/api/download', () => ({ descargarConAutorizacion: vi.fn() }))

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


function envolver(elemento: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{elemento}</QueryClientProvider>)
}

beforeAll(async () => {
  await i18n.changeLanguage('es')
})

afterEach(cleanup)

beforeEach(() => {
  vi.clearAllMocks()
  mockReconocer.mutateAsync = vi.fn().mockResolvedValue(INFORME)
  mockReconocer.isPending = false
})

async function abrirElFormulario() {
  const { SitesPage } = await import('../SitesPage')
  envolver(<SitesPage />)
  fireEvent.click(screen.getByText(/nuevo sitio/i))
  await screen.findByTestId('form-sitio')
}

describe('reconocer un apartado antes de darlo de alta', () => {
  it('se reconoce la URL escrita en el formulario, sin haber creado el sitio', async () => {
    await abrirElFormulario()

    fireEvent.change(screen.getByTestId('campo-url'), { target: { value: RAIZ } })
    fireEvent.click(screen.getByTestId('btn-reconocer'))

    await waitFor(() =>
      expect(mockReconocer.mutateAsync).toHaveBeenCalledWith({
        data: expect.objectContaining({ root_url: RAIZ }),
      }),
    )
  })

  it('sin URL no hay nada que reconocer', async () => {
    await abrirElFormulario()

    expect(screen.getByTestId('btn-reconocer')).toBeDisabled()
  })

  it('el filtro y la pausa del formulario van al reconocimiento: son los del rastreo que se lanzaría', async () => {
    await abrirElFormulario()

    fireEvent.change(screen.getByTestId('campo-url'), { target: { value: RAIZ } })
    fireEvent.change(screen.getByTestId('campo-url-regex'), { target: { value: 'escola-doctorat' } })
    fireEvent.change(screen.getByTestId('campo-pausa'), { target: { value: '2' } })
    fireEvent.click(screen.getByTestId('btn-reconocer'))

    await waitFor(() =>
      expect(mockReconocer.mutateAsync).toHaveBeenCalledWith({
        data: expect.objectContaining({ url_regex_filter: 'escola-doctorat', delay_seconds: 2 }),
      }),
    )
  })

  it('muestra el recuento por apartado y el total', async () => {
    await abrirElFormulario()
    fireEvent.change(screen.getByTestId('campo-url'), { target: { value: RAIZ } })
    fireEvent.click(screen.getByTestId('btn-reconocer'))

    const tabla = await screen.findByTestId('apartados-del-sitio')
    expect(tabla.textContent).toContain('base')
    expect(tabla.textContent).toContain('300')
    expect(screen.getByTestId('total-urls').textContent).toContain('349')
  })

  it('dice cuánto tardaría el rastreo, que es lo que decide de golpe o por apartados', async () => {
    await abrirElFormulario()
    fireEvent.change(screen.getByTestId('campo-url'), { target: { value: RAIZ } })
    fireEvent.click(screen.getByTestId('btn-reconocer'))

    // 837,6 s son casi catorce minutos: en minutos, no en segundos, que no se leen.
    const estimacion = await screen.findByTestId('estimacion-rastreo')
    expect(estimacion.textContent).toMatch(/14|13/)
  })

  it('avisa de que el sondeo se quedó corto en vez de dar el tope por respuesta', async () => {
    await abrirElFormulario()
    fireEvent.change(screen.getByTestId('campo-url'), { target: { value: RAIZ } })
    fireEvent.click(screen.getByTestId('btn-reconocer'))

    expect(await screen.findByTestId('aviso-sondeo-truncado')).toBeInTheDocument()
  })

  it('el CSV se descarga con el token, como el resto de ficheros de la API', async () => {
    const { descargarConAutorizacion } = await import('@/shared/api/download')
    await abrirElFormulario()
    fireEvent.change(screen.getByTestId('campo-url'), { target: { value: RAIZ } })
    fireEvent.click(screen.getByTestId('btn-reconocer'))
    await screen.findByTestId('apartados-del-sitio')

    fireEvent.click(screen.getByTestId('btn-descargar-csv'))

    await waitFor(() =>
      expect(descargarConAutorizacion).toHaveBeenCalledWith(
        expect.stringContaining('/hub/site-reconnaissance'),
        expect.stringContaining('.csv'),
        expect.objectContaining({ root_url: RAIZ, formato: 'csv' }),
      ),
    )
  })

  it('no hay CSV que descargar hasta que hay reconocimiento', async () => {
    await abrirElFormulario()

    expect(screen.queryByTestId('btn-descargar-csv')).not.toBeInTheDocument()
  })

  it('si el reconocimiento falla, se dice', async () => {
    mockReconocer.mutateAsync = vi.fn().mockRejectedValue(new Error('El portal no responde'))
    await abrirElFormulario()
    fireEvent.change(screen.getByTestId('campo-url'), { target: { value: RAIZ } })
    fireEvent.click(screen.getByTestId('btn-reconocer'))

    expect(await screen.findByTestId('error-reconocimiento')).toBeInTheDocument()
  })
})
