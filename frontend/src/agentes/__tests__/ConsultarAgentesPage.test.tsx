import { describe, it, expect, vi, beforeAll, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import i18n from '@/shared/i18n'
import {
  useCatalogoApiV1AgentesCatalogoGet,
  useConsultarApiV1AgentesAgenteIdConsultaPost,
  useAmpliarApiV1AgentesConsultasConsultaIdAmpliacionPost,
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
  useAmpliarApiV1AgentesConsultasConsultaIdAmpliacionPost: vi.fn(),
  // #176 — la sección de la extensión, que aquí no es lo que se prueba.
  useConexionesDeLaExtensionApiV1AgentesExtensionConexionesGet: () => ({ data: [] }),
  useRevocarConexionDeLaExtensionApiV1AgentesExtensionConexionesConexionIdDelete: () => ({ mutate: vi.fn() }),
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
    adjunto: 'no',
    indice_sin_actualizar: false,
    modo_registro: 'validacion',
  },
  {
    id: 'a2',
    nombre: 'Viajes y dietas',
    unidad: 'Servicio de Gestión Económica',
    finalidad: 'Comisiones de servicio',
    responsable: 'Jefatura de Gestión Económica',
    version: 1,
    revision_vencida: true,
    adjunto: 'obligatorio',
    indice_sin_actualizar: true,
    modo_registro: 'incidencias',
  },
]

const RESPUESTA = {
  consulta_id: 'c1',
  modo_registro: 'validacion',
  agente: 'Contratación menor',
  version: 2,
  prompt: 'Eres el asistente.\n\nPregunta: ¿importe?\n\n1. Instrucción — https://drive.google.com/file/d/1',
  espera_adjunto: false,
  documentos: [
    { url: 'https://drive.google.com/file/d/1', titulo: 'Instrucción', score: 0.81, revision_vencida: false },
  ],
}

const consultar = vi.fn()
const ampliar = vi.fn()

function montar(catalogo = CATALOGO) {
  vi.mocked(useCatalogoApiV1AgentesCatalogoGet).mockReturnValue({ data: catalogo, isLoading: false } as never)
  vi.mocked(useConsultarApiV1AgentesAgenteIdConsultaPost).mockReturnValue({
    mutate: consultar,
    isPending: false,
  } as never)
  vi.mocked(useAmpliarApiV1AgentesConsultasConsultaIdAmpliacionPost).mockReturnValue({
    mutate: ampliar,
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
  ampliar.mockReset()
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
      { agenteId: 'a1', data: { consulta: '¿importe máximo?', lengua: 'es', adjunta: false, datos: {} } },
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

describe('#174 — un índice parado se avisa a quien consulta', () => {
  it('el agente se ofrece, pero marcado', () => {
    montar()
    expect(within(screen.getByTestId('agente-a2')).getByTestId('indice-sin-actualizar')).toBeInTheDocument()
    expect(within(screen.getByTestId('agente-a1')).queryByTestId('indice-sin-actualizar')).not.toBeInTheDocument()
  })
})

describe('#216 — el aviso de validación', () => {
  it('el agente en validación lo dice antes de consultar, y el de incidencias no', () => {
    montar()
    expect(within(screen.getByTestId('agente-a1')).getByTestId('en-validacion')).toBeInTheDocument()
    expect(within(screen.getByTestId('agente-a2')).queryByTestId('en-validacion')).not.toBeInTheDocument()
  })
})

describe('#218 — el adjunto opcional', () => {
  const OPCIONAL = { ...CATALOGO[0], id: 'a3', nombre: 'Contratación y revisión de pliegos', adjunto: 'opcional' }

  it('ofrece decir que se adjunta, y lo manda', () => {
    montar([OPCIONAL])
    expect(within(screen.getByTestId('agente-a3')).getByText('Puedes adjuntar un documento')).toBeInTheDocument()
    fireEvent.click(screen.getByLabelText(/Contratación y revisión de pliegos/))
    expect(screen.queryByText(/Describe en tu pregunta el documento que vas a adjuntar/)).not.toBeInTheDocument()
    fireEvent.click(screen.getByLabelText('Voy a adjuntar un documento'))
    expect(screen.getByText(/Describe en tu pregunta el documento que vas a adjuntar/)).toBeInTheDocument()
    preguntar('Revisa este pliego')
    fireEvent.click(screen.getByRole('button', { name: 'Preparar el prompt' }))
    expect(consultar.mock.calls[0][0].data).toMatchObject({ adjunta: true })
  })

  it('si no lo marca, no se adjunta', () => {
    montar([OPCIONAL])
    fireEvent.click(screen.getByLabelText(/Contratación y revisión de pliegos/))
    preguntar('¿Qué plazo tiene un contrato menor?')
    fireEvent.click(screen.getByRole('button', { name: 'Preparar el prompt' }))
    expect(consultar.mock.calls[0][0].data).toMatchObject({ adjunta: false })
  })

  it('en un agente sin opción, la casilla no aparece', () => {
    montar()
    fireEvent.click(screen.getByLabelText(/Contratación menor/))
    expect(screen.queryByLabelText('Voy a adjuntar un documento')).not.toBeInTheDocument()
  })
})

describe('#219 — los datos de la consulta', () => {
  const PLIEGOS = {
    ...CATALOGO[0],
    id: 'a4',
    nombre: 'Pliegos',
    indicaciones: 'Indica el tipo de contrato y el CPV.',
    datos_consulta: [
      { clave: 'tipo_de_contrato', etiqueta: 'Tipo de contrato', tipo: 'opciones', opciones: ['Obras', 'Servicios'], obligatorio: true, ayuda: null, columna: 'Tipo de contrato', prefijo: false },
      { clave: 'codigo_cpv', etiqueta: 'Código CPV', tipo: 'texto', opciones: [], obligatorio: false, ayuda: 'Ocho cifras', columna: 'CPV', prefijo: true },
    ],
  }

  it('pinta los datos que declara el agente, con sus indicaciones y su ayuda', () => {
    montar([PLIEGOS])
    fireEvent.click(screen.getByLabelText(/Pliegos/))
    expect(screen.getByTestId('indicaciones')).toHaveTextContent('Indica el tipo de contrato y el CPV.')
    expect(screen.getByLabelText('Tipo de contrato *')).toBeInTheDocument()
    expect(screen.getByLabelText('Código CPV')).toBeInTheDocument()
    expect(screen.getByText('Ocho cifras')).toBeInTheDocument()
  })

  it('sin el obligatorio no se prepara; con él, manda los datos por su clave', () => {
    montar([PLIEGOS])
    fireEvent.click(screen.getByLabelText(/Pliegos/))
    preguntar('¿Qué solvencia pido?')
    const preparar = screen.getByRole('button', { name: 'Preparar el prompt' })
    expect(preparar).toBeDisabled()
    fireEvent.change(screen.getByLabelText('Tipo de contrato *'), { target: { value: 'Servicios' } })
    fireEvent.change(screen.getByLabelText('Código CPV'), { target: { value: '79341000' } })
    fireEvent.click(preparar)
    expect(consultar.mock.calls[0][0].data.datos).toEqual({ tipo_de_contrato: 'Servicios', codigo_cpv: '79341000' })
  })

  it('al cambiar de agente se vacían', () => {
    montar([PLIEGOS, CATALOGO[0]])
    fireEvent.click(screen.getByLabelText(/Pliegos/))
    fireEvent.change(screen.getByLabelText('Tipo de contrato *'), { target: { value: 'Obras' } })
    fireEvent.click(screen.getByLabelText(/Contratación menor/))
    expect(screen.queryByLabelText('Tipo de contrato *')).not.toBeInTheDocument()
    preguntar('¿importe?')
    fireEvent.click(screen.getByRole('button', { name: 'Preparar el prompt' }))
    expect(consultar.mock.calls[0][0].data.datos).toEqual({})
  })
})

describe('#216 — lo que se guarda de la consulta, dicho sin contradecirse', () => {
  it('la entrada no afirma que la pregunta nunca se guarde: en validación sí se guarda', async () => {
    for (const lengua of ['es', 'ca', 'en']) {
      await i18n.changeLanguage(lengua)
      const { unmount } = montar()
      const intro = screen.getByTestId('consulta-intro').textContent ?? ''
      expect(intro).not.toMatch(/no guarda tu pregunta|no guarda la teua pregunta|does not keep your question/)
      expect(intro).toMatch(/validación|validació|validation/)
      unmount()
    }
  })
})

describe('#225 — buscar más documentos en la misma conversación', () => {
  function consultado() {
    consultar.mockImplementation((_v, o) => o.onSuccess(RESPUESTA))
    montar()
    fireEvent.click(screen.getByLabelText(/Contratación menor/))
    preguntar('¿importe máximo?')
    fireEvent.click(screen.getByRole('button', { name: 'Preparar el prompt' }))
  }

  it('antes de consultar no se ofrece', () => {
    montar()
    expect(screen.queryByRole('button', { name: 'Buscar más documentos' })).not.toBeInTheDocument()
  })

  it('sin texto no se puede pedir', () => {
    consultado()
    expect(screen.getByRole('button', { name: 'Buscar más documentos' })).toBeDisabled()
  })

  it('manda su texto y amplía la última consulta', () => {
    consultado()
    fireEvent.change(screen.getByLabelText('¿Qué te falta o qué quieres precisar?'), {
      target: { value: 'la justificación de la exclusividad' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Buscar más documentos' }))
    expect(ampliar).toHaveBeenCalledWith(
      { consultaId: 'c1', data: { texto: 'la justificación de la exclusividad', lengua: 'es', datos: {} } },
      expect.anything(),
    )
  })

  it('pinta lo que devuelve y dice que va a la misma conversación', () => {
    consultado()
    ampliar.mockImplementation((_v, o) =>
      o.onSuccess({
        ...RESPUESTA,
        consulta_id: 'c2',
        prompt: 'Documentos adicionales para la consulta anterior, sobre: exclusividad',
        documentos: [{ url: 'https://drive.google.com/file/d/9', titulo: 'Negociado', score: 0.7, revision_vencida: false }],
      }),
    )
    fireEvent.change(screen.getByLabelText('¿Qué te falta o qué quieres precisar?'), { target: { value: 'exclusividad' } })
    fireEvent.click(screen.getByRole('button', { name: 'Buscar más documentos' }))
    expect(screen.getByTestId('prompt')).toHaveValue('Documentos adicionales para la consulta anterior, sobre: exclusividad')
    expect(screen.getByTestId('misma-conversacion')).toBeInTheDocument()
    expect(screen.getByText('Negociado')).toBeInTheDocument()
  })

  it('si no quedan documentos, lo dice', () => {
    consultado()
    ampliar.mockImplementation((_v, o) => o.onSuccess({ ...RESPUESTA, consulta_id: 'c2', prompt: 'x', documentos: [] }))
    fireEvent.change(screen.getByLabelText('¿Qué te falta o qué quieres precisar?'), { target: { value: 'otra cosa' } })
    fireEvent.click(screen.getByRole('button', { name: 'Buscar más documentos' }))
    expect(screen.getByTestId('no-quedan')).toBeInTheDocument()
  })
})
