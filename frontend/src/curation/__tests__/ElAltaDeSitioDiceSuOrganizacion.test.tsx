import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { SitesPage } from '../SitesPage'

/**
 * Dar de alta un sitio decía **qué** rastrear y no **de quién** es (defecto encontrado al montar
 * la verificación de DIN.7).
 *
 * `POST /hub/sites` recibe la organización como parámetro de consulta y, sin ella, responde
 * **403 «Indica la organización del sitio»** a cualquiera que no sea superadministrador: sin
 * organización el sitio quedaría fuera de toda cascada y de todo listado acotado, así que el
 * servidor hace bien en rechazarlo (SEC.8.1). La pantalla nunca lo enviaba, de modo que **un
 * administrador de organización no podía crear un sitio desde la interfaz** — y ésa es la única
 * forma que hay de crearlo.
 *
 * Se resuelve con el hook que ya existe para esto, `useOrganizacionElegida` (REV.10): la misma
 * elección que el resto del panel, en vez de un selector nuevo en esta pantalla.
 */

const createMutate = vi.fn()

vi.mock('@/shared/api/generated/hub-sites/hub-sites', () => ({
  useListSites: () => ({ data: [], isLoading: false }),
  useCreateSite: () => ({ mutate: createMutate, isPending: false }),
  useDeleteSite: () => ({ mutate: vi.fn() }),
  useTriggerSiteCrawl: () => ({ mutate: vi.fn() }),

  // #358 — la confirmación de borrado cuenta las páginas del sitio.

  useListSitePages: vi.fn(() => ({ data: undefined })),
  useReconnoiterSite: () => ({ mutateAsync: vi.fn(), isPending: false }),
  usePatchSite: () => ({ mutate: vi.fn(), isPending: false }),
  getListSitesQueryKey: () => ['sites'],
}))

let organizacionElegida = 'org-1'

vi.mock('@/shared/organizacion/useOrganizacionElegida', () => ({
  useOrganizacionElegida: () => ({
    organizaciones: [{ id: 'org-1', name: 'Universitat' }],
    elegida: organizacionElegida,
    elegir: vi.fn(),
    hayVarias: false,
  }),
}))

function darDeAlta() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={qc}>
      <SitesPage />
    </QueryClientProvider>,
  )
  fireEvent.click(screen.getByTestId('btn-nuevo-sitio'))
  fireEvent.change(screen.getByTestId('campo-nombre'), {
    target: { value: 'Portal de prueba' },
  })
  fireEvent.change(screen.getByTestId('campo-url'), {
    target: { value: 'http://127.0.0.1:8123/' },
  })
  fireEvent.submit(screen.getByTestId('form-sitio'))
}

describe('el alta de un sitio dice de quién es', () => {
  beforeEach(() => {
    createMutate.mockClear()
    organizacionElegida = 'org-1'
  })

  it('manda la organización elegida, sin la cual el servidor responde 403', async () => {
    darDeAlta()

    await waitFor(() => expect(createMutate).toHaveBeenCalled())
    expect(createMutate.mock.calls[0][0].params).toEqual({ organizacion_id: 'org-1' })
  })

  it('sin organización elegida no la inventa: el servidor decide si eso vale', async () => {
    /* Un superadministrador puede crear un sitio de plataforma, y ésa es su decisión, no la de
       la pantalla. Mandar un id cualquiera sería peor que no mandar ninguno. */
    organizacionElegida = ''
    darDeAlta()

    await waitFor(() => expect(createMutate).toHaveBeenCalled())
    expect(createMutate.mock.calls[0][0].params).toBeUndefined()
  })
})
