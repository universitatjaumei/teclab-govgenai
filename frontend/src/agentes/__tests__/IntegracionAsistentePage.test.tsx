import { describe, it, expect, vi, beforeAll, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import i18n from '@/shared/i18n'
import {
  useCambiarElAdaptadorApiV1AgentesAsistentesAsistenteAdaptadorPut,
  useEstadoDeLosAdaptadoresApiV1AgentesAsistentesGet,
} from '@/shared/api/generated/agentes/agentes'
import { IntegracionAsistentePage } from '../IntegracionAsistentePage'

/**
 * #215 — si la integración con Gemini funciona, y corregirla sin publicar la extensión.
 *
 * **Los selectores que se pintan son los que manda el servidor**, y si está rota lo dice el
 * servidor (`rota`): la pantalla no cuenta fallos ni decide nada.
 */
vi.mock('@/shared/api/generated/agentes/agentes', () => ({
  useEstadoDeLosAdaptadoresApiV1AgentesAsistentesGet: vi.fn(),
  useCambiarElAdaptadorApiV1AgentesAsistentesAsistenteAdaptadorPut: vi.fn(),
}))

const GEMINI = {
  asistente: 'gemini',
  nombre: 'Gemini',
  origen: 'https://gemini.google.com',
  version: 2,
  selectores: { cuadro: "rich-textarea [role='textbox']", nuevo_del_servidor: 'model-response' },
  actualizado_en: '2026-10-03T10:00:00Z',
  fallos_de_la_version: 0,
  ultimo_fallo_en: null,
  ultimo_fallo_selector: null,
  rota: false,
}
const cambiar = vi.fn()

function montar(adaptadores: unknown[]) {
  vi.mocked(useEstadoDeLosAdaptadoresApiV1AgentesAsistentesGet).mockReturnValue({ data: adaptadores, isLoading: false } as never)
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <IntegracionAsistentePage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeAll(async () => {
  await i18n.changeLanguage('es')
})
beforeEach(() => {
  vi.mocked(useCambiarElAdaptadorApiV1AgentesAsistentesAsistenteAdaptadorPut).mockReturnValue({ mutate: cambiar, isPending: false } as never)
})
afterEach(() => vi.clearAllMocks())

describe('#215 — la integración con el asistente', () => {
  it('pinta los selectores que manda el servidor, sin conocerlos de antemano', () => {
    montar([GEMINI])
    expect(screen.getByLabelText('cuadro')).toHaveValue("rich-textarea [role='textbox']")
    expect(screen.getByLabelText('nuevo_del_servidor')).toHaveValue('model-response')
    expect(screen.getByTestId('integracion-funciona')).toBeInTheDocument()
  })

  it('si el servidor dice que está rota, lo dice con el selector que falló', () => {
    montar([{ ...GEMINI, rota: true, fallos_de_la_version: 4, ultimo_fallo_selector: 'texto', ultimo_fallo_en: '2026-10-03T11:00:00Z' }])
    expect(screen.getByTestId('integracion-rota').textContent).toContain('«texto»')
    expect(screen.getByTestId('integracion-rota').textContent).toContain('4 avisos')
  })

  it('con un solo aviso no dice «1 avisos»', () => {
    montar([{ ...GEMINI, rota: true, fallos_de_la_version: 1, ultimo_fallo_selector: 'cuadro', ultimo_fallo_en: '2026-10-03T11:00:00Z' }])
    expect(screen.getByTestId('integracion-rota').textContent).toContain('un aviso')
  })

  it('guardar manda todos los selectores, y sólo se puede si algo cambió', () => {
    montar([GEMINI])
    const guardar = screen.getByRole('button', { name: i18n.t('agentes:integracion.guardar') })
    expect(guardar).toBeDisabled()
    fireEvent.change(screen.getByLabelText('cuadro'), { target: { value: "div[role='textbox']" } })
    expect(guardar).toBeEnabled()
    fireEvent.click(guardar)
    expect(cambiar).toHaveBeenCalledWith(
      { asistente: 'gemini', data: { selectores: { cuadro: "div[role='textbox']", nuevo_del_servidor: 'model-response' } } },
      expect.anything(),
    )
  })
})
