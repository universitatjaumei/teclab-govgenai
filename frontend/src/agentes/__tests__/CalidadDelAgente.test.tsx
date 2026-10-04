import { describe, it, expect, vi, beforeAll, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import i18n from '@/shared/i18n'
import {
  useConversacionesApiV1AgentesAgenteIdConversacionesGet,
  useMotivosDeInformeApiV1AgentesMotivosDeInformeGet,
  useRevisarConversacionApiV1AgentesConsultasConsultaIdRevisionPut,
} from '@/shared/api/generated/agentes/agentes'
import { CalidadDelAgente } from '../CalidadDelAgente'

/**
 * #217 — la calidad de un agente: conversaciones, informes y dónde está el fallo.
 *
 * **La pantalla no decide nada**: los motivos y sus etiquetas, la pista y los filtros los resuelve
 * el servidor. Aquí se comprueba que se pintan, que los filtros llegan como parámetros y que el
 * veredicto se manda.
 */
vi.mock('@/shared/api/generated/agentes/agentes', () => ({
  useConversacionesApiV1AgentesAgenteIdConversacionesGet: vi.fn(),
  useMotivosDeInformeApiV1AgentesMotivosDeInformeGet: vi.fn(),
  useRevisarConversacionApiV1AgentesConsultasConsultaIdRevisionPut: vi.fn(),
}))

const INFORME = {
  id: 'c1',
  ocurrido_en: '2026-10-04T10:00:00Z',
  version: 2,
  modo: 'validacion',
  pregunta: '¿Qué solvencia pido?',
  datos: { tipo_de_contrato: 'Servicios' },
  documentos: [{ url: 'https://drive.google.com/file/d/1', titulo: 'Pliego de consultoría', score: 0.82 }],
  respuesta: 'Pide tres trabajos similares.',
  respuesta_no_capturada: null,
  fuentes: ['https://drive.google.com/file/d/1'],
  puntuacion: -1,
  motivo: 'inventa',
  comentario: 'Cita un artículo que no existe',
  pista: 'prompt',
  veredicto: null,
  nota_revision: null,
  revisada_en: null,
}
const SIN_CAPTURA = { ...INFORME, id: 'c2', respuesta: null, respuesta_no_capturada: 'selector', puntuacion: null, motivo: null, comentario: null, pista: null }
const revisar = vi.fn()

function montar(conversaciones = [INFORME, SIN_CAPTURA]) {
  vi.mocked(useConversacionesApiV1AgentesAgenteIdConversacionesGet).mockReturnValue({ data: conversaciones, isLoading: false } as never)
  vi.mocked(useMotivosDeInformeApiV1AgentesMotivosDeInformeGet).mockReturnValue({
    data: [
      { codigo: 'inventa', etiqueta: 'Se inventa cosas' },
      { codigo: 'desactualizado', etiqueta: 'Información desactualizada' },
    ],
  } as never)
  vi.mocked(useRevisarConversacionApiV1AgentesConsultasConsultaIdRevisionPut).mockReturnValue({ mutate: revisar, isPending: false } as never)
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <CalidadDelAgente agenteId="a1" />
    </QueryClientProvider>,
  )
}

beforeAll(async () => {
  await i18n.changeLanguage('es')
})
beforeEach(() => revisar.mockClear())
afterEach(() => vi.clearAllMocks())

describe('#217 — la calidad de un agente', () => {
  it('pinta la conversación con el motivo, la pista, los documentos ofrecidos y la respuesta', () => {
    montar()
    const informe = screen.getByTestId('conversacion-c1')
    expect(within(informe).getByText('¿Qué solvencia pido?')).toBeInTheDocument()
    expect(within(informe).getByTestId('informe')).toHaveTextContent('Se inventa cosas')
    expect(within(informe).getByTestId('pista')).toHaveTextContent('las instrucciones del agente (el prompt)')
    expect(within(informe).getByText('Pliego de consultoría')).toBeInTheDocument()
    expect(within(informe).getByText('Pide tres trabajos similares.')).toBeInTheDocument()
    expect(within(informe).getByText('«Cita un artículo que no existe»')).toBeInTheDocument()
  })

  it('dice por qué no hay respuesta cuando no se pudo leer', () => {
    montar()
    expect(within(screen.getByTestId('conversacion-c2')).getByText(/la integración con el asistente falló/)).toBeInTheDocument()
  })

  it('los filtros van al servidor', () => {
    montar()
    fireEvent.change(screen.getByLabelText('Valoración'), { target: { value: '-1' } })
    fireEvent.change(screen.getByLabelText('Motivo'), { target: { value: 'inventa' } })
    fireEvent.click(screen.getByLabelText('Sólo sin revisar'))
    const llamadas = vi.mocked(useConversacionesApiV1AgentesAgenteIdConversacionesGet).mock.calls
    expect(llamadas[llamadas.length - 1]).toEqual(['a1', { modo: undefined, puntuacion: -1, motivo: 'inventa', sin_revisar: true }])
  })

  it('el veredicto y la nota se mandan', () => {
    montar()
    const informe = screen.getByTestId('conversacion-c1')
    const guardar = within(informe).getByRole('button', { name: 'Guardar' })
    expect(guardar).toBeDisabled()
    fireEvent.change(within(informe).getByLabelText('Veredicto'), { target: { value: 'bad' } })
    fireEvent.change(within(informe).getByLabelText('Nota de la revisión'), { target: { value: 'Ajustar el prompt' } })
    fireEvent.click(guardar)
    expect(revisar).toHaveBeenCalledWith({ consultaId: 'c1', data: { veredicto: 'bad', nota: 'Ajustar el prompt' } }, expect.anything())
  })

  it('sin conversaciones, lo dice', () => {
    montar([])
    expect(screen.getByText('No hay conversaciones con estos filtros.')).toBeInTheDocument()
  })
})
