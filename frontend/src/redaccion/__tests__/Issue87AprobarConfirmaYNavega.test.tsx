import { describe, it, expect, vi, beforeAll, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import i18n from '@/shared/i18n'

/**
 * Issue #87 — aprobar un borrador tiene que llevar a lo que acaba de crear.
 *
 * **El defecto.** `handleApprove` disparaba la mutación y terminaba ahí: los dos hooks se pedían
 * **sin `onSuccess`** y el componente no importaba `useNavigate` ni ningún aviso. La plantilla se
 * creaba de verdad y en pantalla no cambiaba nada, así que había que ir a `/redaccion/builder`
 * para saber si había funcionado. El único cambio visible era que `isPending` volvía a `false` y
 * el botón se rehabilitaba — **indistinguible de un botón roto**.
 *
 * Es el mismo fallo que VER.4 arregló en `GenericReportWizard`, y de ahí se copia el remedio:
 * `onSuccess` que navega, con su ruta de destino en el test. No hacía falta inventar nada.
 *
 * **Y el camino de error iba en el mismo paquete**, porque tenía la misma forma: un fallo de la
 * mutación también era invisible. La página ya tenía convención para eso —el `onError` del
 * fichero de muestra guarda el mensaje en estado y lo pinta en un `<p role="alert">`— así que se
 * usa esa y no una nueva.
 *
 * Los dos destinos no son el mismo, y por eso hay un test por modo: una plantilla se va a ver al
 * catálogo (`/redaccion/builder`) y un informe se abre por su identificador
 * (`/redaccion/workspaces/:id`), que es lo que devuelve `ApproveAsWorkspaceResponse`.
 */

const mockPropose = vi.fn()
const mockValidate = vi.fn()

vi.mock('@/shared/api/generated/redaccion-llm-drafts/redaccion-llm-drafts', () => ({
  useProposeLlmDraft: vi.fn(),
  useValidateLlmDraft: vi.fn(),
  useApproveAsTemplate: vi.fn(),
  useApproveAsWorkspace: vi.fn(),
  // El mock de un módulo tiene que cubrir todo lo que el componente importa: sin esta entrada
  // la pantalla revienta al montar.
  useDescribeSampleFile: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
}))

vi.mock('@/shared/auth', async () => {
  const actual = await vi.importActual<typeof import('@/shared/auth')>('@/shared/auth')
  return { ...actual, useAuth: vi.fn() }
})

import { LLMDraftPreviewPage } from '../pages/LLMDraftPreviewPage'
import {
  useProposeLlmDraft,
  useValidateLlmDraft,
  useApproveAsTemplate,
  useApproveAsWorkspace,
} from '@/shared/api/generated/redaccion-llm-drafts/redaccion-llm-drafts'
import { useAuth } from '@/shared/auth'

const BORRADOR = {
  proposed_profile: 'GENERIC_REPORT',
  proposed_sections: [{ section_id: 's1', title: 'Introducción', blocks: [] }],
  proposed_blocks: [],
  proposed_inputs: { required_slots: [], optional_slots: [] },
  rationale: 'Para el test',
  model_used: 'gpt-4o',
  prompt_version: '1.0',
}

const WORKSPACE_ID = '44444444-4444-4444-4444-444444444444'

/** Un `mutate` que responde bien, invocando el `onSuccess` que le pasen. */
function mutateQueVaBien(respuesta: unknown) {
  return vi.fn((_vars, opciones) => opciones?.onSuccess?.(respuesta))
}

/** Un `mutate` que falla, invocando el `onError` que le pasen. */
function mutateQueFalla(mensaje: string) {
  return vi.fn((_vars, opciones) => opciones?.onError?.(new Error(mensaje)))
}

function montar() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/redaccion/draft']}>
        <Routes>
          <Route path="/redaccion/draft" element={<LLMDraftPreviewPage />} />
          <Route path="/redaccion/builder" element={<div data-testid="catalogo-de-plantillas" />} />
          <Route
            path="/redaccion/workspaces/:id"
            element={<div data-testid="pantalla-del-informe" />}
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  )
}

beforeAll(async () => {
  await i18n.changeLanguage('es')
})

beforeEach(() => {
  vi.clearAllMocks()

  vi.mocked(useProposeLlmDraft).mockReturnValue({
    mutate: mockPropose,
    data: BORRADOR,
    isPending: false,
    isSuccess: true,
    isError: false,
  } as unknown as ReturnType<typeof useProposeLlmDraft>)

  vi.mocked(useValidateLlmDraft).mockReturnValue({
    mutate: mockValidate,
    data: undefined,
    isPending: false,
    isSuccess: false,
    isError: false,
  } as unknown as ReturnType<typeof useValidateLlmDraft>)

  vi.mocked(useAuth).mockReturnValue({
    user: { user_id: 'u1', email: 'admin@test.com', role: 'admin', cambio_pendiente: false },
    isAuthenticated: true,
    login: vi.fn(),
    logout: vi.fn(),
  })
})

function conAprobaciones(
  plantilla: ReturnType<typeof vi.fn>,
  informe: ReturnType<typeof vi.fn>,
) {
  vi.mocked(useApproveAsTemplate).mockReturnValue({
    mutate: plantilla,
    isPending: false,
  } as unknown as ReturnType<typeof useApproveAsTemplate>)
  vi.mocked(useApproveAsWorkspace).mockReturnValue({
    mutate: informe,
    isPending: false,
  } as unknown as ReturnType<typeof useApproveAsWorkspace>)
}

describe('aprobar un borrador confirma y navega', () => {
  it('en modo plantilla, lleva al catálogo de plantillas', async () => {
    conAprobaciones(
      mutateQueVaBien({ template_id: 'tpl-1', version_id: 'ver-1', name: 'X', is_global: false }),
      vi.fn(),
    )
    montar()

    fireEvent.click(screen.getByTestId('mode-template'))
    fireEvent.click(screen.getByTestId('btn-approve'))

    await waitFor(() =>
      expect(screen.getByTestId('catalogo-de-plantillas')).toBeDefined()
    )
  })

  it('en modo informe, abre el informe que acaba de crear', async () => {
    conAprobaciones(
      vi.fn(),
      mutateQueVaBien({
        workspace_id: WORKSPACE_ID,
        template_id: 'tpl-1',
        template_version_id: 'ver-1',
        name: 'X',
        status: 'draft',
      }),
    )
    montar()

    fireEvent.click(screen.getByTestId('mode-workspace'))
    fireEvent.click(screen.getByTestId('btn-approve'))

    await waitFor(() =>
      expect(screen.getByTestId('pantalla-del-informe')).toBeDefined()
    )
  })

  it('si la aprobación falla, lo dice y no navega', async () => {
    conAprobaciones(mutateQueFalla('el servidor dijo que no'), vi.fn())
    montar()

    fireEvent.click(screen.getByTestId('mode-template'))
    fireEvent.click(screen.getByTestId('btn-approve'))

    // El mensaje sale donde esta página ya pone los suyos: un `role="alert"`.
    await waitFor(() =>
      expect(
        screen.getAllByRole('alert').some((n) => n.textContent?.includes('el servidor dijo que no'))
      ).toBe(true)
    )
    // Y sigue en la pantalla del borrador: un fallo no puede llevarte a ningún sitio.
    expect(screen.queryByTestId('catalogo-de-plantillas')).toBeNull()
    expect(screen.getByTestId('btn-approve')).toBeDefined()
  })
})
