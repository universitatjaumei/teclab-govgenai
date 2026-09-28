/**
 * PRO.6 — el copiloto se abre desde la interfaz, sin escribir la URL.
 *
 * `CopilotPanel` → `DrawerHub` → `FocusLayout` existían con sus tests y **ninguna ruta montaba
 * `FocusLayout`**, así que el panel era inalcanzable por el lado del navegador (y por el del
 * servidor, donde el endpoint daba 503).
 *
 * Dónde se monta no se decide aquí: en la aplicación NiceGUI el copiloto vivía en un **cajón
 * lateral** que se abría mientras se trabajaba —`focus_manager.py` entra en modo foco y
 * `drawer_hub.py` pinta tres pestañas más el copiloto—, no en una pantalla propia. Su
 * equivalente es la pantalla del informe.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import { WorkspacePage } from '../pages/WorkspacePage'
import { useFocusStore } from '@/shared/layout/useFocusStore'

vi.mock('@/shared/api/generated/redaccion-workspaces/redaccion-workspaces', () => ({
  useRunWorkspace: () => ({ mutate: vi.fn(), isPending: false }),
  useResumeWorkspace: () => ({ mutate: vi.fn(), isPending: false }),
  useSetWorkspaceFields: vi.fn(() => ({ mutateAsync: vi.fn().mockResolvedValue({}), isPending: false })),
  useUploadWorkspaceInput: () => ({ mutate: vi.fn(), isPending: false }),
  useTransitionBlock: () => ({ mutate: vi.fn(), isPending: false }),
}))

vi.mock('@/shared/api/generated/hub-redaccion/hub-redaccion', () => ({
  useGetWorkspaceById: () => ({
    data: {
      workspace_id: 'w1',
      status: 'in_review',
      blocks: [
        { block_id: 'b1', kind: 'DETERMINISTIC_DATA', status: 'extracted', content: null },
      ],
    },
    isPending: false,
    isError: false,
  }),
  useGetTemplateUiContractApiV1HubRedaccionTemplateVersionsVersionIdUiContractGet: () => ({
    data: undefined,
    isPending: false,
  }),
  useGetWorkspaceWarnings: () => ({ data: [], isPending: false }),
  getGetWorkspaceByIdQueryKey: () => ['ws'],
}))

function wrap() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/redaccion/workspaces/w1']}>
        <Routes>
          <Route path="/redaccion/workspaces/:id" element={<WorkspacePage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  useFocusStore.getState().reset()
})

describe('El copiloto en la pantalla del informe', () => {
  it('should_ofrecer_un_boton_para_abrir_el_copiloto', () => {
    wrap()

    expect(screen.getByTestId('btn-abrir-copiloto')).toBeDefined()
    // Arranca cerrado: un panel que nadie ha pedido tapa la mitad de la pantalla.
    expect(screen.queryByTestId('drawer-hub')).toBeNull()
  })

  it('should_abrir_el_cajon_en_la_pestana_del_copiloto', () => {
    wrap()

    fireEvent.click(screen.getByTestId('btn-abrir-copiloto'))

    expect(screen.getByTestId('drawer-hub')).toBeDefined()
    expect(screen.getByTestId('tab-panel-copilot')).toBeDefined()
  })

  it('should_dar_al_copiloto_el_contexto_de_este_informe', () => {
    wrap()

    const contexto = useFocusStore.getState().context
    expect(contexto?.type).toBe('informe')
    expect(contexto?.entityId).toBe('w1')
  })

  it('should_cerrarse_con_el_mismo_boton', () => {
    wrap()

    fireEvent.click(screen.getByTestId('btn-abrir-copiloto'))
    fireEvent.click(screen.getByTestId('btn-abrir-copiloto'))

    expect(screen.queryByTestId('drawer-hub')).toBeNull()
  })
})
