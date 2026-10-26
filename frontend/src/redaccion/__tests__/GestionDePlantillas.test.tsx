import { describe, it, expect, beforeAll, beforeEach, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import i18n from '@/shared/i18n'
import { ReportTemplateBuilderPage } from '../pages/ReportTemplateBuilderPage'
import {
  useListTemplates,
  usePatchTemplate,
  useArchiveTemplate,
  useRestoreTemplate,
} from '@/shared/api/generated/hub-redaccion/hub-redaccion'

/**
 * GUI.1 + GUI.2 — la pantalla de plantillas se puede gestionar.
 *
 * Encontrado por el usuario probando: «se han creado muchas plantillas, se ven en dos pantallas
 * y no hay ninguna opción para borrarlas o editarlas». La lista sólo podía crecer.
 *
 * Y el alta que había aquí creaba plantillas con `spec_json: {}` — sin bloques, o sea informes
 * vacíos—: la mitad de lo que ensuciaba la lista lo producía este botón. Crear se hace
 * describiendo el informe, que es donde el modelo propone los bloques.
 */
vi.mock('@/shared/api/generated/hub-redaccion/hub-redaccion', () => ({
  useListTemplates: vi.fn(),
  usePatchTemplate: vi.fn(),
  useArchiveTemplate: vi.fn(),
  useRestoreTemplate: vi.fn(),
}))

vi.mock('@/shared/auth', () => ({
  useAuth: () => ({ user: { role: 'superadmin', email: 'admin@example.local' } }),
}))
// #277 — la pantalla pregunta capacidades a `/auth/me`; se simulan las del rol del test.
vi.mock('@/shared/auth/useCapacidad', async () =>
  (await import('@/test-utils/capacidades')).dobleDeUseCapacidad(() => 'superadmin'),
)

const PLANTILLA = {
  id: 'tpl-1',
  name: 'Informe presupuestario',
  report_profile: 'GENERIC_REPORT',
  owner_kind: 'platform',
  is_global: true,
  current_version_id: 'ver-1',
  created_at: '2026-08-18T10:00:00Z',
  archived: false,
}

function mockearApi(overrides: Record<string, unknown> = {}) {
  vi.mocked(useListTemplates).mockReturnValue({
    data: [PLANTILLA],
    isLoading: false,
    refetch: vi.fn(),
    ...(overrides.list as object),
  } as any)
  vi.mocked(usePatchTemplate).mockReturnValue({
    mutate: overrides.patch ?? vi.fn(),
    isPending: false,
  } as any)
  vi.mocked(useArchiveTemplate).mockReturnValue({
    mutate: overrides.archive ?? vi.fn(),
    isPending: false,
  } as any)
  vi.mocked(useRestoreTemplate).mockReturnValue({
    mutate: overrides.restore ?? vi.fn(),
    isPending: false,
  } as any)
}

function pintar() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <ReportTemplateBuilderPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeAll(async () => {
  await i18n.changeLanguage('es')
})

beforeEach(() => {
  vi.clearAllMocks()
})

describe('gestión de plantillas', () => {
  it('should_ofrecer_retirar_y_renombrar_cada_plantilla', () => {
    mockearApi()
    pintar()

    expect(screen.getByTestId('btn-renombrar-tpl-1')).toBeInTheDocument()
    expect(screen.getByTestId('btn-archivar-tpl-1')).toBeInTheDocument()
  })

  it('should_pedir_confirmacion_antes_de_retirar', () => {
    const archive = vi.fn()
    mockearApi({ archive })
    pintar()

    fireEvent.click(screen.getByTestId('btn-archivar-tpl-1'))
    // Nada se retira por un solo clic: el diálogo aparece y la llamada no.
    expect(archive).not.toHaveBeenCalled()
    expect(screen.getByTestId('confirmar-archivar')).toBeInTheDocument()
  })

  it('should_retirar_al_confirmar', async () => {
    const archive = vi.fn()
    mockearApi({ archive })
    pintar()

    fireEvent.click(screen.getByTestId('btn-archivar-tpl-1'))
    fireEvent.click(screen.getByTestId('confirmar-archivar'))

    await waitFor(() =>
      expect(archive).toHaveBeenCalledWith(
        expect.objectContaining({ templateId: 'tpl-1' }),
        expect.anything(),
      ),
    )
  })

  it('should_decir_que_los_informes_ya_hechos_se_conservan', () => {
    mockearApi()
    pintar()

    fireEvent.click(screen.getByTestId('btn-archivar-tpl-1'))
    // Quien retira una plantilla necesita saber que no se lleva los informes por delante.
    expect(screen.getByTestId('aviso-archivar').textContent).toMatch(/informes/i)
  })

  it('should_guardar_el_nombre_nuevo', async () => {
    const patch = vi.fn()
    mockearApi({ patch })
    pintar()

    fireEvent.click(screen.getByTestId('btn-renombrar-tpl-1'))
    fireEvent.change(screen.getByTestId('input-nombre-tpl-1'), {
      target: { value: 'Ejecución presupuestaria trimestral' },
    })
    fireEvent.click(screen.getByTestId('btn-guardar-nombre-tpl-1'))

    await waitFor(() =>
      expect(patch).toHaveBeenCalledWith(
        expect.objectContaining({
          templateId: 'tpl-1',
          data: expect.objectContaining({ name: 'Ejecución presupuestaria trimestral' }),
        }),
        expect.anything(),
      ),
    )
  })

  it('should_no_guardar_un_nombre_en_blanco', () => {
    const patch = vi.fn()
    mockearApi({ patch })
    pintar()

    fireEvent.click(screen.getByTestId('btn-renombrar-tpl-1'))
    fireEvent.change(screen.getByTestId('input-nombre-tpl-1'), { target: { value: '   ' } })

    expect(screen.getByTestId('btn-guardar-nombre-tpl-1')).toBeDisabled()
  })

  it('should_poder_ver_y_recuperar_las_retiradas', async () => {
    const restore = vi.fn()
    mockearApi({
      restore,
      list: { data: [{ ...PLANTILLA, archived: true }] },
    })
    pintar()

    fireEvent.click(screen.getByTestId('toggle-archivadas'))
    fireEvent.click(screen.getByTestId('btn-recuperar-tpl-1'))

    await waitFor(() =>
      expect(restore).toHaveBeenCalledWith(
        expect.objectContaining({ templateId: 'tpl-1' }),
        expect.anything(),
      ),
    )
  })

  it('should_marcar_las_retiradas_para_que_no_se_confundan', () => {
    mockearApi({ list: { data: [{ ...PLANTILLA, archived: true }] } })
    pintar()

    fireEvent.click(screen.getByTestId('toggle-archivadas'))
    expect(screen.getByTestId('marca-archivada-tpl-1')).toBeInTheDocument()
  })

  it('should_no_ofrecer_crear_plantillas_vacias', () => {
    /**
     * El alta que había aquí mandaba `spec_json: {}`: una plantilla sin bloques da un informe
     * vacío, y no hay forma de arreglarla después porque no hay editor de bloques. Se crea
     * describiendo el informe, y desde aquí se enlaza allí.
     */
    mockearApi()
    pintar()

    expect(screen.queryByTestId('btn-save-template')).not.toBeInTheDocument()
    expect(screen.getByTestId('enlace-crear-describiendo')).toHaveAttribute(
      'href',
      '/redaccion/draft',
    )
  })

  it('should_negar_la_pantalla_a_quien_no_es_administrador', async () => {
    vi.resetModules()
    vi.doMock('@/shared/auth', () => ({ useAuth: () => ({ user: { role: 'user' } }) }))
    vi.doMock('@/shared/auth/useCapacidad', async () =>
      (await import('@/test-utils/capacidades')).dobleDeUseCapacidad(() => 'user'),
    )
    const { ReportTemplateBuilderPage: Pagina } = await import(
      '../pages/ReportTemplateBuilderPage'
    )
    mockearApi()

    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter>
          <Pagina />
        </MemoryRouter>
      </QueryClientProvider>,
    )
    expect(screen.getByTestId('access-denied')).toBeInTheDocument()
  })
})
