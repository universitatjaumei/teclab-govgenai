import { describe, test, expect, vi, beforeAll, afterEach } from 'vitest'
import { render, screen, waitFor, act, fireEvent } from '@testing-library/react'
import i18n from '@/shared/i18n'
import { ChatWidget } from '../components/ChatWidget'

// Helper: mock SSE Response with all events delivered at once
function makeSseResponse(events: Array<{ event: string; data: object }>): Response {
  const encoder = new TextEncoder()
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const { event, data } of events) {
        controller.enqueue(
          encoder.encode(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`),
        )
      }
      controller.close()
    },
  })
  return new Response(stream, { headers: { 'Content-Type': 'text/event-stream' } })
}

// Helper: deferred SSE stream with externally controlled enqueue/close
function makeDeferredStream() {
  const encoder = new TextEncoder()
  let ctrl!: ReadableStreamDefaultController<Uint8Array>
  const stream = new ReadableStream<Uint8Array>({ start(c) { ctrl = c } })
  return {
    response: new Response(stream),
    send(event: string, data: object) {
      ctrl.enqueue(encoder.encode(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`))
    },
    close() { ctrl.close() },
  }
}

const DEFAULT_PROPS = {
  chatbotId: 'bot-1',
  apiUrl: 'http://localhost:8000/api/v1',
  lang: 'es',
}

const DONE_EVENT = {
  interaction_id: 'iact-1',
  sources: [],
  language_fallback: false,
  translation_warning: null,
}

const DONE_WITH_SOURCES = {
  interaction_id: 'iact-1',
  sources: [
    { document_id: 'doc-1', title: 'Reglament del Consell de Govern', url: 'https://www.uji.es/reglament.pdf', score: 0.92 },
    { document_id: 'doc-2', title: 'Estatuts UJI', url: 'https://dogv.gva.es/estatuts.pdf', score: 0.85 },
  ],
  language_fallback: false,
  translation_warning: null,
}

const fetchMock = vi.fn()

// El widget monta `EnlaceAlFuente` (AIS.6), que pide `/api/v1/instancia` al cargarse. Con un
// único mock compartido, esa petición se comía el `mockResolvedValueOnce` que cada test tenía
// preparado para la respuesta del chat, así que el chat recibía `undefined` y 18 tests caían
// con «Unable to find an element with the text».
//
// Se enruta por URL en vez de añadir un `Once` de más al principio de cada test: así el test
// declara sólo lo suyo, y montar mañana otro componente que pida algo al arrancar no vuelve a
// desplazar la cola. Lo destapó CI.
const fetchEnrutado = vi.fn((entrada: RequestInfo | URL, ...resto: unknown[]) => {
  const url = typeof entrada === 'string' ? entrada : String((entrada as Request).url ?? entrada)
  if (url.includes('/instancia')) {
    return Promise.resolve(new Response(JSON.stringify({ source_url: null })))
  }
  return fetchMock(entrada, ...resto)
})

beforeAll(async () => {
  await i18n.changeLanguage('es')
  vi.stubGlobal('fetch', fetchEnrutado)
})

afterEach(() => {
  vi.clearAllMocks()
})

// UX.1: el widget arranca CERRADO, que es la convención de un widget de chat. Los tests
// que ejercitan la conversación necesitan abrirlo antes, y lo hacen por el lanzador —no
// por un prop de conveniencia—, así que prueban también el camino que recorre el visitante.
function renderOpen(ui: React.ReactElement) {
  const resultado = render(ui)
  fireEvent.click(screen.getByTestId('widget-launcher'))
  return resultado
}

describe('ChatWidget — comportamiento de widget (UX.1)', () => {
  test('should_start_closed_showing_only_the_launcher', () => {
    render(<ChatWidget {...DEFAULT_PROPS} />)

    expect(screen.getByTestId('widget-launcher')).toBeInTheDocument()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  test('should_open_when_the_launcher_is_clicked', () => {
    render(<ChatWidget {...DEFAULT_PROPS} />)

    fireEvent.click(screen.getByTestId('widget-launcher'))

    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(screen.queryByTestId('widget-launcher')).not.toBeInTheDocument()
  })

  test('should_show_the_declared_title_in_the_header', () => {
    render(<ChatWidget {...DEFAULT_PROPS} title="Assistent econòmic-administratiu" />)

    fireEvent.click(screen.getByTestId('widget-launcher'))

    expect(screen.getByTestId('widget-header-title')).toHaveTextContent(
      'Assistent econòmic-administratiu',
    )
  })

  test('should_fall_back_to_the_translated_title_without_one', () => {
    render(<ChatWidget {...DEFAULT_PROPS} />)

    fireEvent.click(screen.getByTestId('widget-launcher'))

    const encabezado = screen.getByTestId('widget-header-title')
    expect(encabezado).toBeInTheDocument()
    expect(encabezado.textContent?.trim()).not.toBe('')
  })

  test('should_bring_its_own_box_instead_of_inheriting_the_host_page', () => {
    // El defecto que lo motiva: el panel se renderizaba con `height: 100%` dentro del
    // contenedor y heredaba lo que le diera la página, así que en un `<div>` pelado se
    // estiraba a ancho completo al final del documento.
    renderOpen(<ChatWidget {...DEFAULT_PROPS} />)

    const caja = screen.getByRole('dialog')

    expect(caja).toHaveStyle({ position: 'fixed' })
    expect(caja.style.width).not.toBe('')
    expect(caja.style.borderTop).toContain('#0b5394')
  })

  test('should_use_a_growing_textarea_not_a_single_line_input', () => {
    renderOpen(<ChatWidget {...DEFAULT_PROPS} />)

    const campo = screen.getByRole('textbox')

    expect(campo.tagName).toBe('TEXTAREA')
    expect(campo).toHaveStyle({ resize: 'none' })
    expect(campo.style.overflowY).not.toBe('scroll')
  })

  test('should_grow_the_textarea_as_the_question_gets_longer', () => {
    renderOpen(<ChatWidget {...DEFAULT_PROPS} />)
    const campo = screen.getByRole('textbox') as HTMLTextAreaElement
    // jsdom no calcula `scrollHeight`, así que se simula: lo que se comprueba es que el
    // componente REACCIONA al contenido, no la altura exacta que pintaría un navegador.
    Object.defineProperty(campo, 'scrollHeight', { value: 92, configurable: true })

    fireEvent.change(campo, { target: { value: 'Una pregunta prou llarga '.repeat(6) } })

    expect(campo.style.height).toBe('92px')
  })

  test('should_scroll_to_the_answer_without_the_user_doing_it', async () => {
    const scrollIntoView = vi.fn()
    Object.defineProperty(window.HTMLElement.prototype, 'scrollIntoView', {
      value: scrollIntoView,
      writable: true,
      configurable: true,
    })
    fetchMock.mockResolvedValueOnce(
      makeSseResponse([
        { event: 'token', data: { delta: 'Resposta llarga.' } },
        { event: 'done', data: DONE_EVENT },
      ]),
    )
    renderOpen(<ChatWidget {...DEFAULT_PROPS} />)

    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Pregunta' } })
    fireEvent.click(screen.getByRole('button', { name: /enviar/i }))

    await waitFor(() => expect(scrollIntoView).toHaveBeenCalled())
  })
})

describe('ChatWidget — señal inmediata y aviso de IA (UX.7)', () => {
  test('should_acknowledge_the_question_before_the_server_says_anything', async () => {
    // El primer `status` del servidor tarda unos segundos: hasta que llegaba, quien
    // preguntaba no tenía ninguna señal de que su pregunta se hubiera enviado.
    const deferred = makeDeferredStream()
    fetchMock.mockResolvedValueOnce(deferred.response)
    renderOpen(<ChatWidget {...DEFAULT_PROPS} />)

    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Pregunta' } })
    fireEvent.click(screen.getByRole('button', { name: /enviar/i }))

    // Sin ningún evento del servidor todavía.
    await waitFor(() => expect(screen.getByTestId('widget-pensando')).toBeInTheDocument())
  })

  test('should_replace_the_placeholder_with_the_real_progress', async () => {
    const deferred = makeDeferredStream()
    fetchMock.mockResolvedValueOnce(deferred.response)
    renderOpen(<ChatWidget {...DEFAULT_PROPS} />)

    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Pregunta' } })
    fireEvent.click(screen.getByRole('button', { name: /enviar/i }))
    await screen.findByTestId('widget-pensando')

    await act(async () => {
      deferred.send('status', { node: 'retrieve', msg: 'Buscando…' })
      await Promise.resolve()
    })

    await waitFor(() => {
      expect(screen.queryByTestId('widget-pensando')).not.toBeInTheDocument()
      expect(screen.getByText(/Buscando en la base documental/)).toBeInTheDocument()
    })
  })

  test('should_warn_that_the_answers_come_from_ai_and_may_be_wrong', () => {
    renderOpen(<ChatWidget {...DEFAULT_PROPS} />)

    const aviso = screen.getByTestId('widget-aviso-ia')

    expect(aviso.textContent).toMatch(/inteligencia artificial/i)
    expect(aviso.textContent).toMatch(/errores/i)
  })

  // La respuesta la redacta el modelo y NO pasa por el Servei de Llengües: el aviso tiene que
  // decirlo. Sale de la respuesta del DEDIA a la OIATI (2026-09-09), que da por hecho que «a les
  // respostes s'aplica el disclaimer general..., inclosa la referència a la validació
  // lingüística» — y no la llevaba. No es un flujo de validación por respuesta, que no tendría
  // sentido: es advertir de lo que no se ha hecho.
  test('should_warn_that_the_answer_has_not_been_checked_by_a_language_service', () => {
    renderOpen(<ChatWidget {...DEFAULT_PROPS} />)

    expect(screen.getByTestId('widget-aviso-ia').textContent).toMatch(
      /revisi[oó]n ling[uü][ií]stica/i,
    )
  })

  test('should_name_the_model_when_the_page_declares_it', () => {
    renderOpen(<ChatWidget {...DEFAULT_PROPS} model="Gemini 2.5 Flash" />)

    expect(screen.getByTestId('widget-aviso-ia').textContent).toContain('(Gemini 2.5 Flash)')
  })

  test('should_not_show_empty_parentheses_without_a_model', () => {
    renderOpen(<ChatWidget {...DEFAULT_PROPS} />)

    expect(screen.getByTestId('widget-aviso-ia').textContent).not.toContain('()')
  })
})

describe('ChatWidget — la cita dice qué artículo (UX.6)', () => {
  test('should_show_the_anchor_next_to_the_document_title', async () => {
    fetchMock.mockResolvedValueOnce(
      makeSseResponse([
        { event: 'token', data: { delta: 'Sis anys.' } },
        {
          event: 'done',
          data: {
            ...DONE_EVENT,
            sources: [{
              document_id: 'doc-1',
              title: 'Reglament de la Sindicatura de Greuges',
              url: 'https://www.uji.es/reglament.pdf#art-9',
              score: 0.9,
            }],
          },
        },
      ]),
    )
    renderOpen(<ChatWidget {...DEFAULT_PROPS} />)

    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Pregunta' } })
    fireEvent.click(screen.getByRole('button', { name: /enviar/i }))

    // El ancla viajaba en el enlace pero no se veía: la píldora solo pintaba el título.
    await waitFor(() => expect(screen.getByText(/art-9/)).toBeInTheDocument())
  })

  test('should_not_invent_an_anchor_when_the_source_has_none', async () => {
    fetchMock.mockResolvedValueOnce(
      makeSseResponse([
        { event: 'token', data: { delta: 'Resposta.' } },
        { event: 'done', data: DONE_WITH_SOURCES },
      ]),
    )
    renderOpen(<ChatWidget {...DEFAULT_PROPS} />)

    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Pregunta' } })
    fireEvent.click(screen.getByRole('button', { name: /enviar/i }))

    await screen.findByText('Estatuts UJI')
    expect(screen.queryByText(/·/)).not.toBeInTheDocument()
  })
})

describe('ChatWidget — el progreso habla el idioma de la página (UX.3)', () => {
  test('should_translate_the_node_status_instead_of_showing_the_server_text', async () => {
    await i18n.changeLanguage('ca')
    const deferred = makeDeferredStream()
    fetchMock.mockResolvedValueOnce(deferred.response)
    renderOpen(<ChatWidget {...DEFAULT_PROPS} lang="ca" />)

    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Pregunta' } })
    fireEvent.click(screen.getByRole('button', { name: /enviar/i }))

    await act(async () => {
      // El servidor manda el texto en castellano; el widget no lo debe pintar.
      deferred.send('status', { node: 'retrieve', msg: 'Buscando en la base de conocimiento...' })
      await Promise.resolve()
    })

    await waitFor(() => {
      expect(screen.getByText(/Cercant en la base documental/)).toBeInTheDocument()
      expect(screen.queryByText(/Buscando en la base de conocimiento/)).not.toBeInTheDocument()
    })
    await i18n.changeLanguage('es')
  })

  test('should_fall_back_to_the_server_text_for_an_untranslated_node', async () => {
    const deferred = makeDeferredStream()
    fetchMock.mockResolvedValueOnce(deferred.response)
    renderOpen(<ChatWidget {...DEFAULT_PROPS} />)

    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Pregunta' } })
    fireEvent.click(screen.getByRole('button', { name: /enviar/i }))

    await act(async () => {
      deferred.send('status', { node: 'un_nodo_futuro', msg: 'Haciendo algo nuevo...' })
      await Promise.resolve()
    })

    // Un nodo sin traducción enseña lo que diga el servidor: mejor eso que un hueco.
    await waitFor(() =>
      expect(screen.getByText('Haciendo algo nuevo...')).toBeInTheDocument(),
    )
  })
})

describe('ChatWidget — pregunta y respuesta se distinguen (UX.2)', () => {
  test('should_frame_the_user_question_in_light_blue', async () => {
    fetchMock.mockResolvedValueOnce(
      makeSseResponse([
        { event: 'token', data: { delta: 'Resposta.' } },
        { event: 'done', data: DONE_EVENT },
      ]),
    )
    renderOpen(<ChatWidget {...DEFAULT_PROPS} />)

    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Pregunta' } })
    fireEvent.click(screen.getByRole('button', { name: /enviar/i }))

    const turno = await screen.findByTestId('turn-user')
    // jsdom normaliza el hexadecimal a rgb(): #e8f0f8 -> rgb(232, 240, 248).
    expect(turno).toHaveStyle({ background: 'rgb(232, 240, 248)' })
  })

  test('should_separate_a_question_from_the_previous_answer', async () => {
    fetchMock.mockResolvedValueOnce(
      makeSseResponse([
        { event: 'token', data: { delta: 'Resposta.' } },
        { event: 'done', data: DONE_EVENT },
      ]),
    )
    renderOpen(<ChatWidget {...DEFAULT_PROPS} />)

    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Pregunta' } })
    fireEvent.click(screen.getByRole('button', { name: /enviar/i }))

    const turno = await screen.findByTestId('turn-user')
    expect(turno.style.marginTop).not.toBe('')
    const respuesta = await screen.findByTestId('turn-assistant')
    expect(respuesta.style.marginTop).not.toBe('')
  })
})

describe('ChatWidget — el seguimiento lleva el contexto (HIB.C)', () => {
  // La premisa del prompt era que `necesita_reescritura` exigía dos turnos previos y que por
  // eso el segundo turno no se reescribía. Falso: el historial se aplana a 'rol: texto' por
  // turno, así que un intercambio completo YA son dos entradas. El defecto real es que **el
  // widget no enviaba historial**: el cuerpo era `{ message, lang }`, así que `request.history`
  // llegaba siempre vacío, la reescritura nunca corría y cada pregunta se trataba como la
  // primera. De ahí el caso del doctorado internacional del 2026-08-26.
  //
  // Cinco intercambios, decisión del usuario (2026-08-27): tres se juzgó poco para el hábito
  // de un chat, y el modelo de reescritura es pequeño.
  async function enviarYResponder(texto: string, respuesta: string) {
    fetchMock.mockResolvedValueOnce(
      makeSseResponse([
        { event: 'token', data: { delta: respuesta } },
        { event: 'done', data: DONE_EVENT },
      ]),
    )
    fireEvent.change(screen.getByRole('textbox'), { target: { value: texto } })
    fireEvent.click(screen.getByRole('button', { name: /enviar/i }))
    await waitFor(() => {
      expect(screen.getAllByTestId('turn-assistant').at(-1)).toHaveTextContent(respuesta)
    })
  }

  function cuerpoDeLaLlamada(indice: number): Record<string, unknown> {
    return JSON.parse(String(fetchMock.mock.calls[indice][1].body))
  }

  test('should_not_send_history_on_the_first_question', async () => {
    renderOpen(<ChatWidget {...DEFAULT_PROPS} />)

    await enviarYResponder('Primera', 'R1.')

    expect(cuerpoDeLaLlamada(0).history).toEqual([])
  })

  test('should_send_the_previous_turns_on_a_follow_up', async () => {
    renderOpen(<ChatWidget {...DEFAULT_PROPS} />)

    await enviarYResponder('Requisits per a la menció de doctorat internacional', 'R1.')
    await enviarYResponder('Fan falta requisits addicionals per a l’acte de defensa?', 'R2.')

    const historial = cuerpoDeLaLlamada(1).history as Array<{ role: string; content: string }>
    expect(historial).toHaveLength(2)
    expect(historial[0]).toEqual({
      role: 'user',
      content: 'Requisits per a la menció de doctorat internacional',
    })
    expect(historial[1]).toEqual({ role: 'assistant', content: 'R1.' })
  })

  test('should_cap_the_history_at_five_exchanges', async () => {
    renderOpen(<ChatWidget {...DEFAULT_PROPS} />)

    for (let i = 1; i <= 7; i++) {
      await enviarYResponder(`Pregunta ${i}`, `R${i}.`)
    }

    // La octava llamada lleva los cinco intercambios anteriores: diez entradas.
    const historial = cuerpoDeLaLlamada(6).history as Array<{ role: string; content: string }>
    expect(historial).toHaveLength(10)
    // Y son los ÚLTIMOS cinco, no los primeros.
    expect(historial[0]).toEqual({ role: 'user', content: 'Pregunta 2' })
    expect(historial.at(-1)).toEqual({ role: 'assistant', content: 'R6.' })
  })

  test('should_offer_a_way_to_start_a_new_conversation', async () => {
    // Sin esto, enviar historial convierte un hilo viejo en contaminación: una pregunta de
    // otro tema se reescribe contra el tema anterior. Y en un equipo compartido —un aula, la
    // biblioteca— quien se sienta después ve las preguntas del anterior.
    renderOpen(<ChatWidget {...DEFAULT_PROPS} />)

    await enviarYResponder('Primera', 'R1.')

    fireEvent.click(screen.getByRole('button', { name: /nova conversa|nueva conversación|new conversation/i }))

    await waitFor(() => {
      expect(screen.queryByTestId('turn-user')).not.toBeInTheDocument()
    })
  })

  test('should_not_send_the_previous_thread_after_a_reset', async () => {
    renderOpen(<ChatWidget {...DEFAULT_PROPS} />)

    await enviarYResponder('Primera', 'R1.')
    fireEvent.click(screen.getByRole('button', { name: /nova conversa|nueva conversación|new conversation/i }))
    await enviarYResponder('Tema distinto', 'R2.')

    expect(cuerpoDeLaLlamada(1).history).toEqual([])
  })

  test('should_keep_the_thread_when_the_panel_is_closed_and_reopened', async () => {
    // Cerrar no significa «he terminado»: quien cierra para mirar otra cosa y vuelve no
    // debería perder el hilo. Decisión del usuario (2026-08-27).
    renderOpen(<ChatWidget {...DEFAULT_PROPS} />)

    await enviarYResponder('Primera', 'R1.')
    fireEvent.click(screen.getByRole('button', { name: /tanca|cerrar|close/i }))
    fireEvent.click(screen.getByTestId('widget-launcher'))

    expect(screen.getByTestId('turn-user')).toHaveTextContent('Primera')
  })

  test('should_expire_the_thread_after_thirty_minutes_without_activity', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    try {
      renderOpen(<ChatWidget {...DEFAULT_PROPS} />)
      await enviarYResponder('Primera', 'R1.')

      await act(async () => {
        vi.advanceTimersByTime(30 * 60 * 1000 + 1000)
      })

      await waitFor(() => {
        expect(screen.queryByTestId('turn-user')).not.toBeInTheDocument()
      })
    } finally {
      vi.useRealTimers()
    }
  })

  test('should_not_send_the_question_being_asked_as_part_of_the_history', async () => {
    // Enviarla dos veces —en `message` y en `history`— haría que el reescritor la tomara
    // como su propio antecedente.
    renderOpen(<ChatWidget {...DEFAULT_PROPS} />)

    await enviarYResponder('Primera', 'R1.')
    await enviarYResponder('Segunda', 'R2.')

    const historial = cuerpoDeLaLlamada(1).history as Array<{ content: string }>
    expect(historial.map(h => h.content)).not.toContain('Segunda')
  })
})

describe('ChatWidget — una respuesta descartada no se queda en pantalla (HIB.B)', () => {
  test('should_replace_the_streamed_answer_when_the_server_discards_it', async () => {
    // El contrato de citas corre DENTRO de `generate_answer`, después de generar, así que
    // cuando rechaza sus tokens ya se han pintado. Por SSE no se retira lo enviado: el
    // servidor manda `discard` y aquí se vacía la burbuja antes de que llegue el mensaje
    // de rendición. Sin esto, quien pregunta se queda con la respuesta que el contrato
    // acaba de descartar — y encima con apariencia de buena.
    fetchMock.mockResolvedValueOnce(
      makeSseResponse([
        { event: 'token', data: { delta: 'Segons l’article 4, has de superar el 20%.' } },
        { event: 'discard', data: { reason: 'citation' } },
        { event: 'token', data: { delta: 'No tinc fonament per a respondre.' } },
        { event: 'done', data: DONE_EVENT },
      ]),
    )
    renderOpen(<ChatWidget {...DEFAULT_PROPS} />)

    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Pregunta' } })
    fireEvent.click(screen.getByRole('button', { name: /enviar/i }))

    const respuesta = await screen.findByTestId('turn-assistant')
    await waitFor(() => {
      expect(respuesta).toHaveTextContent('No tinc fonament per a respondre.')
    })
    expect(respuesta).not.toHaveTextContent('has de superar el 20%')
  })

  test('should_keep_the_bubble_so_the_rendition_has_somewhere_to_land', async () => {
    // Se vacía, no se borra: si se quitara la burbuja, el `token` siguiente no encontraría
    // un mensaje de asistente al que añadirse y el mensaje de rendición se perdería.
    fetchMock.mockResolvedValueOnce(
      makeSseResponse([
        { event: 'token', data: { delta: 'Text que es descarta.' } },
        { event: 'discard', data: { reason: 'quality_gate' } },
        { event: 'done', data: DONE_EVENT },
      ]),
    )
    renderOpen(<ChatWidget {...DEFAULT_PROPS} />)

    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Pregunta' } })
    fireEvent.click(screen.getByRole('button', { name: /enviar/i }))

    const respuesta = await screen.findByTestId('turn-assistant')
    await waitFor(() => {
      expect(respuesta).not.toHaveTextContent('Text que es descarta')
    })
  })
})

describe('ChatWidget', () => {
  test('should_display_user_and_assistant_messages', async () => {
    fetchMock.mockResolvedValueOnce(
      makeSseResponse([
        { event: 'token', data: { delta: 'Hola, soy el asistente.' } },
        { event: 'done', data: DONE_EVENT },
      ]),
    )

    renderOpen(<ChatWidget {...DEFAULT_PROPS} />)

    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Hola' } })
    fireEvent.click(screen.getByRole('button', { name: /enviar/i }))

    await waitFor(() => {
      expect(screen.getByText('Hola')).toBeInTheDocument()
      expect(screen.getByText('Hola, soy el asistente.')).toBeInTheDocument()
    })
  })

  test('should_stream_chunks_in_real_time', async () => {
    fetchMock.mockResolvedValueOnce(
      makeSseResponse([
        { event: 'token', data: { delta: 'Chunk1' } },
        { event: 'token', data: { delta: 'Chunk2' } },
        { event: 'done', data: DONE_EVENT },
      ]),
    )

    renderOpen(<ChatWidget {...DEFAULT_PROPS} />)

    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Hola' } })
    fireEvent.click(screen.getByRole('button', { name: /enviar/i }))

    await waitFor(() => {
      expect(screen.getByText('Chunk1Chunk2')).toBeInTheDocument()
    })
  })

  test('should_show_node_status_during_stream', async () => {
    const deferred = makeDeferredStream()
    fetchMock.mockResolvedValueOnce(deferred.response)

    renderOpen(<ChatWidget {...DEFAULT_PROPS} />)

    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Hola' } })
    fireEvent.click(screen.getByRole('button', { name: /enviar/i }))

    await act(async () => {
      deferred.send('status', { node: 'retriever', msg: 'Buscando en la base de conocimiento...' })
    })

    await waitFor(() => {
      expect(screen.getByText('Buscando en la base de conocimiento...')).toBeInTheDocument()
    })

    await act(async () => {
      deferred.send('done', DONE_EVENT)
      deferred.close()
    })
  })

  test('should_hide_status_when_streaming_ends', async () => {
    const deferred = makeDeferredStream()
    fetchMock.mockResolvedValueOnce(deferred.response)

    renderOpen(<ChatWidget {...DEFAULT_PROPS} />)

    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Hola' } })
    fireEvent.click(screen.getByRole('button', { name: /enviar/i }))

    await act(async () => {
      deferred.send('status', { node: 'retriever', msg: 'Buscando...' })
    })

    await waitFor(() => {
      expect(screen.getByText('Buscando...')).toBeInTheDocument()
    })

    await act(async () => {
      deferred.send('token', { delta: 'Respuesta' })
      deferred.send('done', DONE_EVENT)
      deferred.close()
    })

    await waitFor(() => {
      expect(screen.queryByText('Buscando...')).not.toBeInTheDocument()
    })
  })

  test('should_show_translation_warning_on_language_fallback', async () => {
    fetchMock.mockResolvedValueOnce(
      makeSseResponse([
        { event: 'token', data: { delta: 'Resposta' } },
        {
          event: 'done',
          data: {
            interaction_id: 'iact-1',
            sources: [],
            language_fallback: true,
            translation_warning: 'Resposta en idioma alternatiu',
          },
        },
      ]),
    )

    renderOpen(<ChatWidget {...DEFAULT_PROPS} lang="ca" />)

    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Hola' } })
    fireEvent.click(screen.getByRole('button', { name: /enviar/i }))

    await waitFor(() => {
      expect(screen.getByRole('alert')).toBeInTheDocument()
      expect(screen.getByText('Resposta en idioma alternatiu')).toBeInTheDocument()
    })
  })

  test('should_show_star_rating_after_response', async () => {
    fetchMock.mockResolvedValueOnce(
      makeSseResponse([
        { event: 'token', data: { delta: 'Aquí está la respuesta.' } },
        { event: 'done', data: DONE_EVENT },
      ]),
    )

    renderOpen(<ChatWidget {...DEFAULT_PROPS} />)

    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Pregunta' } })
    fireEvent.click(screen.getByRole('button', { name: /enviar/i }))

    await waitFor(() => {
      expect(screen.getByRole('group')).toBeInTheDocument()
    })
  })

  test('should_submit_feedback_on_star_click', async () => {
    fetchMock
      .mockResolvedValueOnce(
        makeSseResponse([
          { event: 'token', data: { delta: 'Respuesta.' } },
          { event: 'done', data: { ...DONE_EVENT, interaction_id: 'iact-99' } },
        ]),
      )
      .mockResolvedValueOnce(new Response('{}', { status: 200 }))

    renderOpen(<ChatWidget {...DEFAULT_PROPS} />)

    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Pregunta' } })
    fireEvent.click(screen.getByRole('button', { name: /enviar/i }))

    await waitFor(() => {
      expect(screen.getByRole('group')).toBeInTheDocument()
    })

    const starButtons = screen.getAllByRole('button', { name: /estrellas/i })
    await act(async () => {
      fireEvent.click(starButtons[2]) // 3 estrellas
    })

    expect(fetchMock).toHaveBeenCalledWith(
      'http://localhost:8000/api/v1/hub/feedback/iact-99',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ score: 3 }),
      }),
    )
  })

  test('should_render_source_pills_after_last_assistant_message', async () => {
    fetchMock.mockResolvedValueOnce(
      makeSseResponse([
        { event: 'token', data: { delta: 'Aquí tienes la respuesta.' } },
        { event: 'done', data: DONE_WITH_SOURCES },
      ]),
    )

    renderOpen(<ChatWidget {...DEFAULT_PROPS} />)

    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Pregunta' } })
    fireEvent.click(screen.getByRole('button', { name: /enviar/i }))

    await waitFor(() => {
      expect(screen.getByRole('link', { name: /Reglament del Consell de Govern/i })).toBeInTheDocument()
      expect(screen.getByRole('link', { name: /Estatuts UJI/i })).toBeInTheDocument()
    })
  })

  test('should_open_source_pill_in_new_tab', async () => {
    fetchMock.mockResolvedValueOnce(
      makeSseResponse([
        { event: 'token', data: { delta: 'Respuesta.' } },
        { event: 'done', data: DONE_WITH_SOURCES },
      ]),
    )

    renderOpen(<ChatWidget {...DEFAULT_PROPS} />)

    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Pregunta' } })
    fireEvent.click(screen.getByRole('button', { name: /enviar/i }))

    await waitFor(() => {
      const link = screen.getByRole('link', { name: /Reglament del Consell de Govern/i })
      expect(link).toHaveAttribute('href', 'https://www.uji.es/reglament.pdf')
      expect(link).toHaveAttribute('target', '_blank')
      expect(link).toHaveAttribute('rel', expect.stringContaining('noopener'))
    })
  })

  test('should_render_no_pills_when_sources_empty', async () => {
    fetchMock.mockResolvedValueOnce(
      makeSseResponse([
        { event: 'token', data: { delta: 'Respuesta sin fuentes.' } },
        { event: 'done', data: DONE_EVENT },
      ]),
    )

    renderOpen(<ChatWidget {...DEFAULT_PROPS} />)

    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Pregunta' } })
    fireEvent.click(screen.getByRole('button', { name: /enviar/i }))

    await waitFor(() => {
      expect(screen.getByText('Respuesta sin fuentes.')).toBeInTheDocument()
    })

    expect(screen.queryByRole('link')).not.toBeInTheDocument()
  })

  test('should_have_sources_section_label_for_screen_readers', async () => {
    fetchMock.mockResolvedValueOnce(
      makeSseResponse([
        { event: 'token', data: { delta: 'Respuesta.' } },
        { event: 'done', data: DONE_WITH_SOURCES },
      ]),
    )

    renderOpen(<ChatWidget {...DEFAULT_PROPS} />)

    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Pregunta' } })
    fireEvent.click(screen.getByRole('button', { name: /enviar/i }))

    await waitFor(() => {
      expect(screen.getByRole('navigation', { name: /fuentes/i })).toBeInTheDocument()
    })
  })

  test('should_render_assistant_message_as_markdown', async () => {
    fetchMock.mockResolvedValueOnce(
      makeSseResponse([
        { event: 'token', data: { delta: '**Texto en negrita**' } },
        { event: 'done', data: DONE_EVENT },
      ]),
    )

    renderOpen(<ChatWidget {...DEFAULT_PROPS} />)

    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Pregunta' } })
    fireEvent.click(screen.getByRole('button', { name: /enviar/i }))

    await waitFor(() => {
      expect(screen.getByRole('strong')).toBeInTheDocument()
    })
  })

  test('should_show_loading_indicator_during_stream', async () => {
    let resolveFetch!: (r: Response) => void
    fetchMock.mockReturnValueOnce(new Promise<Response>(r => { resolveFetch = r }))

    renderOpen(<ChatWidget {...DEFAULT_PROPS} />)

    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Hola' } })

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /enviar/i }))
    })

    // isStreaming=true before fetch resolves → loading indicator visible
    expect(screen.getByRole('status')).toBeInTheDocument()

    await act(async () => {
      resolveFetch(
        makeSseResponse([
          { event: 'token', data: { delta: 'Resp' } },
          { event: 'done', data: DONE_EVENT },
        ]),
      )
    })

    await waitFor(() => {
      expect(screen.queryByRole('status')).not.toBeInTheDocument()
    })
  })
})

// #278 — el widget tragaba todos los fallos: no miraba `response.ok`, pasaba un 401 o un 429 al
// lector de SSE, y el evento `error` sólo reiniciaba banderas. El visitante veía una burbuja vacía.
describe('ChatWidget — los fallos se dicen (#278)', () => {
  async function preguntar() {
    renderOpen(<ChatWidget {...DEFAULT_PROPS} />)
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Hola' } })
    fireEvent.click(screen.getByRole('button', { name: /enviar/i }))
  }

  const respuestaDeError = (status: number) =>
    new Response(JSON.stringify({ detail: { code: 'X', message: 'interno' } }), { status })

  test('should_say_the_assistant_is_not_available_on_a_401', async () => {
    fetchMock.mockResolvedValueOnce(respuestaDeError(401))
    await preguntar()

    expect(await screen.findByTestId('widget-error')).toHaveTextContent(
      i18n.t('chat:error_unauthorized'),
    )
    expect(screen.queryByTestId('turn-assistant')).not.toBeInTheDocument()
  })

  test('should_ask_to_wait_on_a_429', async () => {
    fetchMock.mockResolvedValueOnce(respuestaDeError(429))
    await preguntar()

    expect(await screen.findByTestId('widget-error')).toHaveTextContent(
      i18n.t('chat:error_rate_limited'),
    )
  })

  test('should_not_show_the_server_text_of_a_500', async () => {
    fetchMock.mockResolvedValueOnce(respuestaDeError(500))
    await preguntar()

    const aviso = await screen.findByTestId('widget-error')
    expect(aviso).toHaveTextContent(i18n.t('chat:error_generic'))
    expect(aviso).not.toHaveTextContent('interno')
  })

  test('should_stop_and_say_so_on_a_malformed_event', async () => {
    const encoder = new TextEncoder()
    const roto = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode('event: token\ndata: {esto no es json\n\n'))
        controller.close()
      },
    })
    fetchMock.mockResolvedValueOnce(new Response(roto))
    await preguntar()

    expect(await screen.findByTestId('widget-error')).toHaveTextContent(
      i18n.t('chat:error_generic'),
    )
    // Y se puede volver a preguntar: el turno no se queda «en curso».
    expect(screen.getByRole('textbox')).not.toBeDisabled()
  })

  test('should_say_so_when_the_server_sends_an_error_event', async () => {
    fetchMock.mockResolvedValueOnce(
      makeSseResponse([{ event: 'error', data: { message: "S'ha produït un error" } }]),
    )
    await preguntar()

    expect(await screen.findByTestId('widget-error')).toHaveTextContent(
      i18n.t('chat:error_generic'),
    )
  })
})
