import { useState, useCallback, useRef, useEffect } from 'react'

export interface Message {
  role: 'user' | 'assistant'
  content: string
}

export interface SourceRef {
  document_id: string
  title: string
  url: string
  score: number
}

/** Progreso del grafo: el NODO, y el texto del servidor solo como red de seguridad.
 *
 * UX.3: el servidor mandaba el mensaje ya escrito en castellano y el widget lo pintaba tal
 * cual, así que «Buscando en la base de conocimiento...» salía en castellano dentro de un
 * widget en valenciano. El idioma de una interfaz lo decide la interfaz: el servidor dice
 * *qué* está pasando —el nodo, que ya mandaba— y aquí se traduce. `msg` se conserva para
 * un nodo que todavía no tenga traducción: mejor el texto del servidor que un hueco.
 */
export interface NodeStatus {
  node: string
  msg: string
}

/** Por qué no llegó la respuesta (#278). Se traduce en el widget; el texto del servidor no se
 *  pinta: es para quien depura, y el del evento `error` es fijo y en una sola lengua. */
export type FalloDelChat = 'unauthorized' | 'rate_limited' | 'generic'

export interface UseChatReturn {
  messages: Message[]
  /** El último fallo, o `null`. Antes se tragaba: el visitante veía una burbuja vacía. */
  error: FalloDelChat | null
  currentNodeStatus: NodeStatus | null
  isStreaming: boolean
  translationWarning: string | null
  sources: SourceRef[]
  interactionId: string | null
  sendMessage: (text: string) => Promise<void>
  /** HIB.C — vacía el hilo. Necesario desde que el historial viaja: sin esto, una pregunta
   *  de otro tema se reescribe contra el tema anterior. */
  resetConversation: () => void
}

/** Cinco intercambios, decisión del usuario (2026-08-27). Diez entradas, porque cada
 *  intercambio son dos: la pregunta y la respuesta. El contrato admite hasta 50. */
const HISTORIAL_MAX_ENTRADAS = 10

/** Media hora sin actividad y el hilo se vacía solo.
 *
 *  Cubre lo que el botón no cubre: el hilo que nadie reinició y sigue ahí una hora después,
 *  en un equipo compartido —un aula, la biblioteca— o simplemente sobre otro tema. Cerrar el
 *  panel NO vacía: cerrar no significa «he terminado». */
const CADUCIDAD_MS = 30 * 60 * 1000

export function useChat(chatbotId: string, apiUrl: string, lang: string, widgetKey?: string): UseChatReturn {
  const [messages, setMessages] = useState<Message[]>([])
  const [currentNodeStatus, setCurrentNodeStatus] = useState<NodeStatus | null>(null)
  const [isStreaming, setIsStreaming] = useState(false)
  const [translationWarning, setTranslationWarning] = useState<string | null>(null)
  const [sources, setSources] = useState<SourceRef[]>([])
  const [interactionId, setInteractionId] = useState<string | null>(null)
  const [error, setError] = useState<FalloDelChat | null>(null)
  const isStreamingRef = useRef(false)
  // HIB.C — los turnos previos, en un ref y no leídos del estado.
  //
  // `sendMessage` es un `useCallback` cuyas dependencias no incluyen `messages` a propósito:
  // añadirlas recrearía la función en cada token que llega. Leer `messages` desde dentro
  // capturaría el valor del render en que se creó el callback, que es justo el turno
  // anterior al que se está enviando.
  const messagesRef = useRef<Message[]>([])

  // El ref sigue al estado, y no se escribe a mano al enviar: la respuesta del asistente se
  // rellena token a token DESPUÉS, así que asignarlo sólo al enviar dejaba el turno anterior
  // con la respuesta vacía y el historial viajaba mutilado. Al leerlo en `sendMessage` el ref
  // vale lo que valía en el último render, que es exactamente los turnos previos.
  useEffect(() => {
    messagesRef.current = messages
  }, [messages])

  const resetConversation = useCallback(() => {
    messagesRef.current = []
    setMessages([])
    setSources([])
    setInteractionId(null)
    setTranslationWarning(null)
    setCurrentNodeStatus(null)
    setError(null)
  }, [])

  // Caducidad por inactividad. El temporizador se reinicia con cada turno porque la
  // dependencia es `messages`: mientras la conversación avanza no caduca.
  useEffect(() => {
    if (messages.length === 0) return
    const temporizador = setTimeout(resetConversation, CADUCIDAD_MS)
    return () => clearTimeout(temporizador)
  }, [messages, resetConversation])

  const sendMessage = useCallback(async (text: string) => {
    if (isStreamingRef.current) return
    isStreamingRef.current = true
    setIsStreaming(true)
    setCurrentNodeStatus(null)
    setTranslationWarning(null)
    setSources([])
    setInteractionId(null)
    setError(null)
    // HIB.C — el historial se toma ANTES de añadir el turno nuevo: enviar la pregunta actual
    // también dentro de `history` haría que el reescritor la tomara como su propio
    // antecedente.
    const historial = messagesRef.current.slice(-HISTORIAL_MAX_ENTRADAS)

    setMessages(prev => [
      ...prev,
      { role: 'user', content: text },
      { role: 'assistant', content: '' },
    ])

    /** El turno termina en fallo: se dice, y no se deja una burbuja vacía esperando. */
    const fallar = (motivo: FalloDelChat) => {
      setError(motivo)
      setMessages(prev => {
        const last = prev[prev.length - 1]
        return last?.role === 'assistant' && last.content === '' ? prev.slice(0, -1) : prev
      })
      isStreamingRef.current = false
      setIsStreaming(false)
      setCurrentNodeStatus(null)
    }

    try {
      const headers: Record<string, string> = { 'Content-Type': 'application/json' }
      if (widgetKey) headers['X-Widget-Key'] = widgetKey
      const response = await fetch(`${apiUrl}/hub/chat/${chatbotId}`, {
        method: 'POST',
        headers,
        body: JSON.stringify({ message: text, lang, history: historial }),
      })

      // #278 — un 401, un 429 o un 5xx no traen SSE: antes se pasaban al lector como si lo
      // fueran y el visitante se quedaba con la burbuja vacía.
      if (!response.ok) {
        fallar(
          response.status === 401 || response.status === 403
            ? 'unauthorized'
            : response.status === 429
              ? 'rate_limited'
              : 'generic',
        )
        return
      }
      if (!response.body) throw new Error('No response body')

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      let currentEvent = ''

      while (true) {
        const { done, value: chunk } = await reader.read()
        if (done) break

        buffer += decoder.decode(chunk, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() ?? ''

        for (const line of lines) {
          if (line === '') {
            currentEvent = ''
            continue
          }
          const colon = line.indexOf(':')
          if (colon === -1) continue
          const field = line.slice(0, colon).trim()
          const sseValue = line.slice(colon + 1).trim()

          if (field === 'event') {
            currentEvent = sseValue
          } else if (field === 'data') {
            let payload: Record<string, unknown>
            try {
              payload = JSON.parse(sseValue) as Record<string, unknown>
            } catch {
              // Un evento que no se puede leer deja el turno a medias: se dice y se para.
              await reader.cancel()
              fallar('generic')
              return
            }
            if (currentEvent === 'status') {
              setCurrentNodeStatus({ node: String(payload.node ?? ''), msg: String(payload.msg ?? '') })
            } else if (currentEvent === 'token') {
              setMessages(prev => {
                const last = prev[prev.length - 1]
                if (last?.role === 'assistant') {
                  return [
                    ...prev.slice(0, -1),
                    { ...last, content: last.content + (payload.delta as string) },
                  ]
                }
                return prev
              })
            } else if (currentEvent === 'discard') {
              // HIB.B: el contrato de citas corre después de generar, así que cuando
              // rechaza sus tokens ya se han pintado. Por SSE no se retira lo enviado, así
              // que el servidor avisa y aquí se vacía la burbuja: el mensaje de rendición
              // llega justo después como un `token` normal.
              //
              // Vaciar y no borrar la burbuja: si se quitara, el `token` siguiente no
              // encontraría un mensaje de asistente al que añadirse y se perdería.
              setMessages(prev => {
                const last = prev[prev.length - 1]
                if (last?.role === 'assistant') {
                  return [...prev.slice(0, -1), { ...last, content: '' }]
                }
                return prev
              })
            } else if (currentEvent === 'done') {
              setSources((payload.sources as SourceRef[]) ?? [])
              setInteractionId(payload.interaction_id as string)
              if (payload.language_fallback) {
                setTranslationWarning(payload.translation_warning as string | null)
              }
              isStreamingRef.current = false
              setIsStreaming(false)
              setCurrentNodeStatus(null)
            } else if (currentEvent === 'error') {
              fallar('generic')
            }
          }
        }
      }
    } catch {
      fallar('generic')
    }
  }, [chatbotId, apiUrl, lang, widgetKey])

  return { messages, error, currentNodeStatus, isStreaming, translationWarning, sources, interactionId, sendMessage, resetConversation }
}
