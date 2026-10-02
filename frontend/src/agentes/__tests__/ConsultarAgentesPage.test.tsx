import { describe, it, expect, vi, beforeAll, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import i18n from '@/shared/i18n'
import {
  useCatalogoApiV1AgentesCatalogoGet,
  useConsultarApiV1AgentesAgenteIdConsultaPost,
} from '@/shared/api/generated/agentes/agentes'
import { ConsultarAgentesPage } from '../ConsultarAgentesPage'

/**
 * #175 — consultar un agente desde el panel y copiar el prompt (decisión del usuario, 2026-10-02).
 *
 * Es el circuito que valida la idea antes de la extensión (#176): la plataforma compone el prompt
 * con los enlaces, la persona lo copia y lo pega en el asistente general de la organización.
 * **La pantalla no compone nada**: pinta lo que devuelve el servidor.
 */
vi.mock('@/shared/api/generated/agentes/agentes', () => ({
  useCatalogoApiV1AgentesCatalogoGet: vi.fn(),
  useConsultarApiV1AgentesAgenteIdConsultaPost: vi.fn(),
}))

const CATALOGO = [
  {
    id: 'a1',
    nombre: 'Contratación menor',
    unidad: 'Servicio de Contratación',
    finalidad: 'Orientar sobre el contrato menor',
    responsable: 'Jefatura de Contratación',
    version: 2,
    revision_vencida: false,
    espera_adjunto: false,
  },
  {
    id: 'a2',
    nombre: 'Viajes y dietas',
    unidad: 'Servicio de Gestión Económica',
    finalidad: 'Comisiones de servicio',
    responsable: 'Jefatura de Gestión Económica',
    version: 1,
    revision_vencida: true,
    espera_adjunto: true,
  },
]

const RESPUESTA = {
  agente: 'Contratación menor',
  version: 2,
  prompt: 'Eres el asistente.\n\nPregunta: ¿importe?\n\n1. Instrucción — https://drive.google.com/file/d/1',
  espera_adjunto: false,
  documentos: [
    { url: 'https://drive.google.com/file/d/1', titulo: 'Instrucción', score: 0.81, revision_vencida: false },
  ],
}

const consultar = vi.fn()

function montar(catalogo = CATALOGO) {
  vi.mocked(useCatalogoApiV1AgentesCatalogoGet).mockReturnValue({ data: catalogo, isLoading: false } as never)
  vi.mocked(useConsultarApiV1AgentesAgenteIdConsultaPost).mockReturnValue({
    mutate: consultar,
    isPending: false,
  } as never)
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <ConsultarAgentesPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

function preguntar(texto: string) {
  fireEvent.change(screen.getByLabelText('Tu pregunta'), { target: { value: texto } })
}

beforeAll(async () => {
  await i18n.changeLanguage('es')
})

beforeEach(() => {
  consultar.mockReset()
})

afterEach(async () => {
  await i18n.changeLanguage('es')
})

describe('#175 — el catálogo de quien consulta', () => {
  it('enseña los agentes que el servidor le ofrece, con su finalidad y responsable', () => {
    montar()
    expect(screen.getByLabelText(/Contratación menor/)).toBeInTheDocument()
    expect(screen.getByText('Orientar sobre el contrato menor')).toBeInTheDocument()
    expect(screen.getByText(/Jefatura de Contratación/)).toBeInTheDocument()
  })

  it('un agente con la revisión vencida se ofrece, pero se avisa', () => {
    montar()
    const ficha = screen.getByTestId('agente-a2')
    expect(within(ficha).getByTestId('revision-vencida')).toBeInTheDocument()
  })

  it('sin agentes para su colectivo, lo dice', () => {
    montar([])
    expect(screen.getByText('No hay ningún agente para ti todavía.')).toBeInTheDocument()
  })
})

describe('#175 — preparar el prompt', () => {
  it('sin pregunta no se puede pedir', () => {
    montar()
    fireEvent.click(screen.getByLabelText(/Contratación menor/))
    expect(screen.getByRole('button', { name: 'Preparar el prompt' })).toBeDisabled()
  })

  it('manda la pregunta al agente elegido, en la lengua de la pantalla', () => {
    montar()
    fireEvent.click(screen.getByLabelText(/Contratación menor/))
    preguntar('¿importe máximo?')
    fireEvent.click(screen.getByRole('button', { name: 'Preparar el prompt' }))
    expect(consultar).toHaveBeenCalledWith(
      { agenteId: 'a1', data: { consulta: '¿importe máximo?', lengua: 'es' } },
      expect.anything(),
    )
  })

  it('en valenciano pide las instrucciones en valenciano', async () => {
    await i18n.changeLanguage('ca')
    montar()
    fireEvent.click(screen.getByLabelText(/Contratación menor/))
    fireEvent.change(screen.getByLabelText('La teua pregunta'), { target: { value: 'import?' } })
    fireEvent.click(screen.getByRole('button', { name: 'Preparar el prompt' }))
    expect(consultar.mock.calls[0][0].data.lengua).toBe('ca')
  })

  it('enseña el prompt tal como lo devuelve el servidor, y los enlaces', () => {
    consultar.mockImplementation((_vars, opciones) => opciones.onSuccess(RESPUESTA))
    montar()
    fireEvent.click(screen.getByLabelText(/Contratación menor/))
    preguntar('¿importe?')
    fireEvent.click(screen.getByRole('button', { name: 'Preparar el prompt' }))

    expect(screen.getByTestId('prompt')).toHaveValue(RESPUESTA.prompt)
    expect(screen.getByRole('link', { name: 'Instrucción' })).toHaveAttribute(
      'href',
      'https://drive.google.com/file/d/1',
    )
  })

  it('copiar pone el prompt en el portapapeles y lo dice', async () => {
    const escribir = vi.fn().mockResolvedValue(undefined)
    Object.assign(navigator, { clipboard: { writeText: escribir } })
    consultar.mockImplementation((_vars, opciones) => opciones.onSuccess(RESPUESTA))
    montar()
    fireEvent.click(screen.getByLabelText(/Contratación menor/))
    preguntar('¿importe?')
    fireEvent.click(screen.getByRole('button', { name: 'Preparar el prompt' }))
    fireEvent.click(screen.getByRole('button', { name: 'Copiar el prompt' }))

    expect(escribir).toHaveBeenCalledWith(RESPUESTA.prompt)
    expect(await screen.findByText('Copiado. Pégalo en el asistente general de la organización.')).toBeInTheDocument()
  })

  it('si el navegador no deja copiar, lo dice y deja el prompt seleccionado para copiarlo a mano', async () => {
    // Lo destapó la verificación en navegador: sin permiso de portapapeles, la pantalla callaba.
    Object.assign(navigator, {
      clipboard: { writeText: vi.fn().mockRejectedValue(new Error('NotAllowedError')) },
    })
    consultar.mockImplementation((_vars, opciones) => opciones.onSuccess(RESPUESTA))
    montar()
    fireEvent.click(screen.getByLabelText(/Contratación menor/))
    preguntar('¿importe?')
    fireEvent.click(screen.getByRole('button', { name: 'Preparar el prompt' }))
    fireEvent.click(screen.getByRole('button', { name: 'Copiar el prompt' }))

    expect(
      await screen.findByText('No se ha podido copiar. El prompt está seleccionado: cópialo con Ctrl+C.'),
    ).toBeInTheDocument()
    const prompt = screen.getByTestId('prompt') as HTMLTextAreaElement
    expect(prompt.selectionStart).toBe(0)
    expect(prompt.selectionEnd).toBe(RESPUESTA.prompt.length)
  })

  it('si el servidor no lo ofrece, se dice por qué', () => {
    consultar.mockImplementation((_vars, opciones) =>
      opciones.onError({
        response: { data: { detail: { code: 'AGENTE_NO_DISPONIBLE', message: 'Este agente no se te ofrece.' } } },
      }),
    )
    montar()
    fireEvent.click(screen.getByLabelText(/Contratación menor/))
    preguntar('¿importe?')
    fireEvent.click(screen.getByRole('button', { name: 'Preparar el prompt' }))
    expect(screen.getByRole('alert')).toHaveTextContent('Este agente no se te ofrece.')
  })
})

describe('#175 — un agente que espera un documento adjunto', () => {
  it('el catálogo lo avisa', () => {
    montar()
    expect(within(screen.getByTestId('agente-a2')).getByText('Con documento adjunto')).toBeInTheDocument()
    expect(within(screen.getByTestId('agente-a1')).queryByText('Con documento adjunto')).not.toBeInTheDocument()
  })

  it('al elegirlo, pide describir el documento en la pregunta', () => {
    montar()
    fireEvent.click(screen.getByLabelText(/Viajes y dietas/))
    expect(screen.getByText(/Describe en tu pregunta el documento que vas a adjuntar/)).toBeInTheDocument()
  })

  it('con el prompt listo, recuerda adjuntarlo en el mismo mensaje', () => {
    consultar.mockImplementation((_vars, opciones) => opciones.onSuccess({ ...RESPUESTA, espera_adjunto: true }))
    montar()
    fireEvent.click(screen.getByLabelText(/Viajes y dietas/))
    preguntar('Revisa esta liquidación de dietas')
    fireEvent.click(screen.getByRole('button', { name: 'Preparar el prompt' }))
    expect(screen.getByTestId('recordatorio-adjunto')).toHaveTextContent(
      'Al pegar el prompt en el asistente, adjunta tu documento en el mismo mensaje.',
    )
  })

  it('sin adjunto, no lo recuerda', () => {
    consultar.mockImplementation((_vars, opciones) => opciones.onSuccess(RESPUESTA))
    montar()
    fireEvent.click(screen.getByLabelText(/Contratación menor/))
    preguntar('¿importe?')
    fireEvent.click(screen.getByRole('button', { name: 'Preparar el prompt' }))
    expect(screen.queryByTestId('recordatorio-adjunto')).not.toBeInTheDocument()
  })
})
