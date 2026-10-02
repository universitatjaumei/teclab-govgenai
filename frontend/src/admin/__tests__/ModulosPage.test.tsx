import { describe, it, expect, beforeEach, beforeAll, vi } from 'vitest'
import { render, screen, within, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import i18n from '@/shared/i18n'
import { ModulosPage } from '../pages/ModulosPage'
import {
  useGetCatalogoApiV1HubModulosCatalogoGet,
  useListConcesionesApiV1HubModulosGet,
  useConcederApiV1HubModulosPost,
  useRetirarApiV1HubModulosConcesionIdDelete,
} from '@/shared/api/generated/hub-modulos/hub-modulos'
import { useListUsersApiV1HubUsersGet } from '@/shared/api/generated/hub-users/hub-users'

/**
 * IDE.5 — conceder módulos a una persona o a un grupo del IdP.
 *
 * Las concesiones eran filas que solo se ponían conectándose a Postgres. Y la vía del grupo es
 * la puerta al modelo que quiere el usuario: el ERP mete a la persona en un grupo, el IdP lo
 * declara, y la concesión del grupo le da los módulos sin que nadie toque nada aquí.
 */
vi.mock('@/shared/api/generated/hub-modulos/hub-modulos', () => ({
  useGetCatalogoApiV1HubModulosCatalogoGet: vi.fn(),
  useListConcesionesApiV1HubModulosGet: vi.fn(),
  useConcederApiV1HubModulosPost: vi.fn(),
  useRetirarApiV1HubModulosConcesionIdDelete: vi.fn(),
  getListConcesionesApiV1HubModulosGetQueryKey: () => ['concesiones'],
}))

vi.mock('@/shared/api/generated/hub-users/hub-users', () => ({
  useListUsersApiV1HubUsersGet: vi.fn(),
}))

const CATALOGO = [
  { code: 'chatbots', label: 'Chatbots y asistentes', vigente: true },
  { code: 'informes', label: 'Informes', vigente: true },
  { code: 'curacion', label: 'Curación de contenido', vigente: false },
  { code: 'utilidades', label: 'Utilidades', vigente: true, de_oficio: true },
]

const CONCESIONES = [
  {
    id: 1,
    subject_type: 'grupo',
    subject_id: 'PDI',
    module_code: 'informes',
    granted_at: '2026-08-22T09:00:00Z',
    granted_by: 'root',
  },
  {
    id: 2,
    subject_type: 'usuario',
    subject_id: '2975357b-76cc-58c7-a3cf-2f7291bf7d5d',
    module_code: 'chatbots',
    granted_at: '2026-08-22T09:00:00Z',
    granted_by: 'root',
  },
]

const conceder = vi.fn()
const retirar = vi.fn()

beforeAll(async () => {
  await i18n.changeLanguage('es')
})

beforeEach(() => {
  conceder.mockClear()
  retirar.mockClear()
  vi.mocked(useGetCatalogoApiV1HubModulosCatalogoGet).mockReturnValue({
    data: CATALOGO,
  } as never)
  vi.mocked(useListConcesionesApiV1HubModulosGet).mockReturnValue({
    data: CONCESIONES,
  } as never)
  vi.mocked(useListUsersApiV1HubUsersGet).mockReturnValue({
    data: { personas: [{ id: 'aaa', email: 'alguien@uji.es' }], de_plataforma_no_mostradas: 0 },
  } as never)
  vi.mocked(useConcederApiV1HubModulosPost).mockReturnValue({
    mutate: conceder,
    isPending: false,
  } as never)
  vi.mocked(useRetirarApiV1HubModulosConcesionIdDelete).mockReturnValue({
    mutate: retirar,
    isPending: false,
  } as never)
})

function renderPage() {
  const cliente = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={cliente}>
      <MemoryRouter>
        <ModulosPage />
      </MemoryRouter>
    </QueryClientProvider>
  )
}

describe('IDE.5 — el catálogo se itera, no se escribe', () => {
  it('should_offer_only_the_modules_the_server_reports_as_current', () => {
    // Si los códigos estuvieran escritos aquí, añadir un módulo exigiría tocar el frontend.
    renderPage()

    const selector = screen.getByLabelText(/^módulo/i)
    const opciones = [...selector.querySelectorAll('option')].map((o) => o.textContent)
    expect(opciones).toContain('Informes')
    expect(opciones).toContain('Chatbots y asistentes')
  })

  it('should_not_offer_a_retired_module', () => {
    // Concederlo no daría acceso a nada: la resolución filtra por `vigente`.
    renderPage()

    const selector = screen.getByLabelText(/^módulo/i)
    const opciones = [...selector.querySelectorAll('option')].map((o) => o.textContent)
    expect(opciones).not.toContain('Curación de contenido')
  })
})

describe('UTL — un módulo de oficio no se concede', () => {
  it('should_not_offer_a_module_everyone_already_has', () => {
    // Concederlo no cambiaría nada, y el servidor lo rechaza con un 400.
    renderPage()

    const selector = screen.getByLabelText(/^módulo/i)
    const opciones = [...selector.querySelectorAll('option')].map((o) => o.textContent)
    expect(opciones).not.toContain('Utilidades')
  })

  it('should_say_which_modules_everyone_has_so_nobody_looks_for_their_grant', () => {
    renderPage()

    expect(screen.getByTestId('nota-de-oficio')).toHaveTextContent('Utilidades')
  })
})

describe('IDE.5 — conceder', () => {
  it('should_grant_to_a_group_by_its_name', () => {
    renderPage()

    fireEvent.change(screen.getByLabelText(/nombre del grupo/i), { target: { value: 'PTGAS' } })
    fireEvent.change(screen.getByLabelText(/^módulo/i), { target: { value: 'informes' } })
    fireEvent.click(screen.getByRole('button', { name: /conceder/i }))

    expect(conceder).toHaveBeenCalledWith(
      {
        data: { subject_type: 'grupo', subject_id: 'PTGAS', module_code: 'informes' },
      },
      expect.anything()
    )
  })

  it('should_pick_a_person_from_a_list_instead_of_typing_an_id', () => {
    // Un campo de texto para el sujeto de tipo persona invitaría a teclear un UUID a mano.
    renderPage()

    fireEvent.change(screen.getByLabelText(/^tipo/i), { target: { value: 'usuario' } })
    const selector = screen.getByLabelText(/persona/i)
    expect(selector.tagName).toBe('SELECT')
    expect([...selector.querySelectorAll('option')].map((o) => o.textContent)).toContain(
      'alguien@uji.es'
    )
  })

  it('should_explain_what_a_group_grant_means', () => {
    renderPage()

    expect(document.body.textContent).toMatch(/IdP|proveedor de identidad|colectivo/i)
  })
})

describe('IDE.5 — el listado y la retirada', () => {
  it('should_show_both_kinds_of_grant', () => {
    renderPage()

    expect(screen.getByText('PDI')).toBeDefined()
    expect(screen.getByText('2975357b-76cc-58c7-a3cf-2f7291bf7d5d')).toBeDefined()
  })

  it('should_word_the_revocation_differently_for_a_group', () => {
    // Retirar la concesión de un grupo alcanza a todo el grupo: no puede leerse igual que
    // retirarle un permiso a una persona.
    renderPage()

    const filaGrupo = screen.getByRole('row', { name: /PDI/ })
    const filaPersona = screen.getByRole('row', { name: /2975357b/ })

    expect(within(filaGrupo).getByRole('button').textContent).not.toBe(
      within(filaPersona).getByRole('button').textContent
    )
  })

  it('should_revoke_the_grant_that_was_clicked', () => {
    renderPage()

    const fila = screen.getByRole('row', { name: /PDI/ })
    fireEvent.click(within(fila).getByRole('button'))

    expect(retirar).toHaveBeenCalledWith({ concesionId: 1 }, expect.anything())
  })

  it('should_say_that_a_superadmin_needs_no_grant', () => {
    // Para que nadie busque su fila en la tabla y crea que falta.
    renderPage()

    expect(document.body.textContent).toMatch(/superadministrador/i)
  })
})
