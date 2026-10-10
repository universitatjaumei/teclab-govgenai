import { describe, it, expect, beforeAll, beforeEach, vi } from 'vitest'
import { render, screen, waitFor, act, fireEvent, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import i18n from '@/shared/i18n'
import { AuthProvider } from '@/shared/auth'
import { OrganizacionesPage } from '../pages/OrganizacionesPage'
import {
  useListOrganizacionesApiV1HubOrganizacionesGet,
  useCreateOrganizacionApiV1HubOrganizacionesPost,
  useUpdateOrganizacionApiV1HubOrganizacionesOrganizacionIdPatch,
  useDeleteOrganizacionApiV1HubOrganizacionesOrganizacionIdDelete,
} from '@/shared/api/generated/hub-organizaciones/hub-organizaciones'

// Se doblan los hooks generados, no `fetch`: desde CAL.2 la página habla por el
// cliente de Orval (axios sobre `customInstance`), así que un `fetch` global
// stubbeado ya no intercepta nada y el test mediría una pantalla vacía.
vi.mock('@/shared/api/generated/hub-organizaciones/hub-organizaciones', () => ({
  useListOrganizacionesApiV1HubOrganizacionesGet: vi.fn(),
  useCreateOrganizacionApiV1HubOrganizacionesPost: vi.fn(),
  useUpdateOrganizacionApiV1HubOrganizacionesOrganizacionIdPatch: vi.fn(),
  useDeleteOrganizacionApiV1HubOrganizacionesOrganizacionIdDelete: vi.fn(),
  getListOrganizacionesApiV1HubOrganizacionesGetQueryKey: vi.fn(() => ['/api/v1/hub/organizaciones']),
}))

const TOKEN = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.' +
  btoa(JSON.stringify({ sub: '1', email: 'admin@test.com', role: 'admin', exp: 9999999999 }))
    .replace(/=/g, '').replace(/\+/g, '-').replace(/\//g, '_') +
  '.signature'

const SAMPLE_CLIENTS = [
  {
    id: '00000000-0000-0000-0000-000000000010',
    name: 'Universitat Jaume I',
    partner_id: 'partner-1',
    theme_config: {},
    is_active: true,
    chatbot_count: 3,
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z',
  },
  {
    id: '00000000-0000-0000-0000-000000000011',
    name: 'Ajuntament de Castelló',
    partner_id: 'partner-2',
    theme_config: {},
    is_active: false,
    chatbot_count: 0,
    created_at: '2024-01-02T00:00:00Z',
    updated_at: '2024-01-02T00:00:00Z',
  },
]

const createMutate = vi.fn()
const mutationDouble = (mutate = vi.fn()) => ({ mutate, isPending: false }) as any

beforeAll(async () => {
  await i18n.changeLanguage('es')
  localStorage.setItem('access_token', TOKEN)
})

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(useCreateOrganizacionApiV1HubOrganizacionesPost).mockReturnValue(mutationDouble(createMutate))
  vi.mocked(useUpdateOrganizacionApiV1HubOrganizacionesOrganizacionIdPatch).mockReturnValue(mutationDouble())
  vi.mocked(useDeleteOrganizacionApiV1HubOrganizacionesOrganizacionIdDelete).mockReturnValue(mutationDouble())
})

function renderPage(clients: object[] = []) {
  vi.mocked(useListOrganizacionesApiV1HubOrganizacionesGet).mockReturnValue({
    data: clients,
    isLoading: false,
  } as any)

  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <AuthProvider>
          <OrganizacionesPage />
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>
  )
}

describe('OrganizacionesPage', () => {
  it('should_render_organizaciones_page_from_generated_types', async () => {
    renderPage(SAMPLE_CLIENTS)
    await waitFor(() => {
      expect(screen.getByText('Universitat Jaume I')).toBeDefined()
      expect(screen.getByText('Ajuntament de Castelló')).toBeDefined()
    })
  })

  it('should_create_client_with_valid_data', async () => {
    renderPage([])

    await waitFor(() => screen.getByRole('button', { name: /nueva organización/i }))
    await act(async () => {
      screen.getByRole('button', { name: /nueva organización/i }).click()
    })

    expect(screen.getByRole('dialog')).toBeDefined()

    fireEvent.change(screen.getByLabelText(/nombre de la organización/i), {
      target: { value: 'Nou Client' },
    })
    fireEvent.change(screen.getByLabelText(/admin id/i), { target: { value: 'partner-3' } })

    await act(async () => {
      screen.getByRole('button', { name: /guardar/i }).click()
    })

    // El cuerpo va en `data`, que es la forma de variables del hook generado.
    expect(createMutate).toHaveBeenCalledWith(
      expect.objectContaining({
        data: expect.objectContaining({ name: 'Nou Client', partner_id: 'partner-3' }),
      }),
    )
  })

  it('should_show_assigned_chatbots_count', async () => {
    renderPage(SAMPLE_CLIENTS)
    await waitFor(() => {
      expect(screen.getByText('Universitat Jaume I')).toBeDefined()
    })
    const badges = screen.getAllByText('3')
    expect(badges.length).toBeGreaterThan(0)
  })

  it('should_filter_clients_by_name', async () => {
    renderPage(SAMPLE_CLIENTS)
    await waitFor(() => {
      expect(screen.getByText('Universitat Jaume I')).toBeDefined()
    })

    const filterInput = screen.getByPlaceholderText(/filtrar por nombre/i)
    fireEvent.change(filterInput, { target: { value: 'Jaume' } })

    await waitFor(() => {
      expect(screen.getByText('Universitat Jaume I')).toBeDefined()
      expect(screen.queryByText('Ajuntament de Castelló')).toBeNull()
    })
  })

  it('should_explain_what_the_organizacion_still_has_when_delete_is_blocked', async () => {
    // #252 — el servidor no borra una organización que todavía tiene datos: responde 409 con lo
    // que le queda, y la pantalla lo tiene que decir en vez de «Request failed with status code».
    const fallo = Object.assign(new Error('Request failed with status code 409'), {
      response: {
        data: {
          detail: {
            code: 'ORGANIZACION_CON_DATOS',
            message: 'La organización todavía tiene datos; desactívala en vez de borrarla.',
            pendiente: { sitios: 1, informes: 12 },
          },
        },
      },
    })
    vi.mocked(useDeleteOrganizacionApiV1HubOrganizacionesOrganizacionIdDelete).mockImplementation(
      ((opciones: { mutation: { onError: (e: Error) => void } }) =>
        mutationDouble(vi.fn(() => opciones.mutation.onError(fallo)))) as any,
    )
    renderPage(SAMPLE_CLIENTS)
    await waitFor(() => screen.getByText('Universitat Jaume I'))

    await act(async () => {
      screen.getAllByRole('button', { name: /^eliminar$/i })[0].click()
    })
    const dialogo = screen.getByRole('dialog')
    await act(async () => {
      within(dialogo).getByRole('button', { name: /^eliminar$/i }).click()
    })

    expect(within(dialogo).getByText(/todavía tiene datos/i)).toBeDefined()
    expect(within(dialogo).getByText('1 sitio de curación')).toBeDefined()
    expect(within(dialogo).getByText('12 informes')).toBeDefined()
    expect(within(dialogo).queryByText(/status code/i)).toBeNull()
  })
})
