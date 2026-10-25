import { useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import { useTranslation } from 'react-i18next'
import { useChat, type SourceRef } from '../hooks/useChat'
import { EnlaceAlFuente } from '@/shared/licencia/EnlaceAlFuente'
import { enlaceExterno } from '@/shared/enlaces/enlaceExterno'

// Identidad del proyecto (UX.2). Los mismos valores que usa el resto de la plataforma;
// `--color-primary` los pisa cuando el chatbot trae tema propio (SEC.8.6).
const AZUL = '#0b5394'
const AZUL_CLARO = '#e8f0f8'
const BORDE_AZUL_CLARO = '#c7dcf0'
const GRIS = '#5b6570'
const TEXTO = '#1f2933'

// Tope de crecimiento de la caja de texto: a partir de aquí, scroll vertical dentro del
// propio campo. Sin tope, una pregunta larga se come el widget entero.
const ALTURA_MAXIMA_CAJA = 140

interface Props {
  chatbotId: string
  apiUrl: string
  lang: string
  widgetKey?: string
  /** Modelo que responde, para decirlo en el aviso. Lo declara la página que incrusta el
   *  widget (`data-model`): es información de quien despliega, no del visitante. */
  model?: string
  /** Nombre del asistente en la cabecera (`data-title`). Sin él se usa la traducción
   *  genérica, que basta cuando la página publica un solo asistente. */
  title?: string
}

interface StarRatingProps {
  interactionId: string
  apiUrl: string
}

interface SourcePillsProps {
  sources: SourceRef[]
}

/** El ancla de la URL, que es la parte que dice QUÉ artículo se ha citado.
 *
 * UX.6: la píldora enseñaba solo el título del documento, así que el ancla —que sí viaja
 * en el enlace— no se veía. Todo el esfuerzo de generar anclas en el corpus se perdía en
 * el último centímetro.
 */
function anclaDe(url: string): string | null {
  const almohadilla = url.indexOf('#')
  if (almohadilla === -1) return null
  const ancla = url.slice(almohadilla + 1).trim()
  return ancla === '' ? null : ancla
}

function SourcePills({ sources }: SourcePillsProps) {
  const { t } = useTranslation('chat')
  if (sources.length === 0) return null
  return (
    <nav aria-label={t('sources')} style={{ display: 'flex', flexWrap: 'wrap', gap: '0.375rem', marginTop: '0.5rem' }}>
      {sources.map(src => (
        <a
          key={src.document_id}
          href={enlaceExterno(src.url)}
          target="_blank"
          rel="noopener noreferrer"
          style={{
            background: 'var(--source-pill-bg, var(--color-primary-light, #e0f2fe))',
            color: 'var(--source-pill-fg, var(--color-primary, #0369a1))',
            border: '1px solid var(--source-pill-border, var(--color-primary, #7dd3fc))',
            borderRadius: '999px',
            padding: '0.2rem 0.65rem',
            fontSize: '0.75rem',
            textDecoration: 'none',
            // El título de una norma no cabe en 380 px. Con `nowrap` la píldora sacaba una
            // barra de desplazamiento horizontal dentro del widget, que es de lo peor que
            // se puede pedir a quien lee.
            overflowWrap: 'anywhere',
            lineHeight: 1.35,
          }}
        >
          {src.title}
          {anclaDe(src.url) && (
            <span style={{ opacity: 0.75, marginLeft: '0.3rem' }}>· {anclaDe(src.url)}</span>
          )}
        </a>
      ))}
    </nav>
  )
}

function StarRating({ interactionId, apiUrl }: StarRatingProps) {
  const [selected, setSelected] = useState<number | null>(null)
  const { t } = useTranslation('chat')

  const handleClick = async (score: number) => {
    setSelected(score)
    // #278 — si la valoración no llega, la estrella no se queda marcada como si hubiera llegado.
    try {
      const respuesta = await fetch(`${apiUrl}/hub/feedback/${interactionId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ score }),
      })
      if (!respuesta.ok) setSelected(null)
    } catch {
      setSelected(null)
    }
  }

  return (
    <div role="group" aria-label={t('feedback_rate')}>
      {[1, 2, 3, 4, 5].map(star => (
        <button
          key={star}
          type="button"
          aria-label={`${star} ${t('feedback_stars')}`}
          aria-pressed={selected === star}
          onClick={() => handleClick(star)}
          style={{ cursor: 'pointer', background: 'none', border: 'none', fontSize: '1.25rem' }}
        >
          {star <= (selected ?? 0) ? '★' : '☆'}
        </button>
      ))}
    </div>
  )
}

function IconoChatbot({ tamano = 22, color = '#ffffff' }: { tamano?: number; color?: string }) {
  return (
    <svg width={tamano} height={tamano} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M4 5.5A2.5 2.5 0 0 1 6.5 3h11A2.5 2.5 0 0 1 20 5.5v8a2.5 2.5 0 0 1-2.5 2.5H9l-4.2 3.5A.5.5 0 0 1 4 19.1V5.5Z"
        fill={color}
      />
      <circle cx="9" cy="9.5" r="1.2" fill={AZUL} />
      <circle cx="12" cy="9.5" r="1.2" fill={AZUL} />
      <circle cx="15" cy="9.5" r="1.2" fill={AZUL} />
    </svg>
  )
}

export function ChatWidget({ chatbotId, apiUrl, lang, widgetKey, model, title }: Props) {
  // UX.1: arranca CERRADO. Un widget embebido enseña su botón y el visitante decide; que
  // se despliegue solo se come la página que lo aloja.
  const [open, setOpen] = useState(false)
  const [input, setInput] = useState('')
  const finDelHilo = useRef<HTMLDivElement>(null)
  const cajaDeTexto = useRef<HTMLTextAreaElement>(null)
  const { t } = useTranslation('chat')
  const {
    messages,
    error,
    currentNodeStatus,
    isStreaming,
    translationWarning,
    sources,
    interactionId,
    sendMessage,
    resetConversation,
  } = useChat(chatbotId, apiUrl, lang, widgetKey)

  const lastAssistantIdx = [...messages].map((m, i) => ({ m, i })).reverse().find(({ m }) => m.role === 'assistant')?.i ?? -1
  const showRating = !isStreaming && interactionId !== null && lastAssistantIdx !== -1

  // UX.1: el hilo baja solo hasta lo último que ha llegado. Hacerlo a mano en cada
  // respuesta es de las cosas que más molestan de un chat, y con streaming pasa en cada
  // trozo, no solo al final: por eso depende también de `messages`.
  useEffect(() => {
    if (!open) return
    // `?.()` sobre el método y no solo sobre el nodo: jsdom no implementa `scrollIntoView`,
    // y sin esto cualquier test que monte el widget revienta por algo que en un navegador
    // real existe siempre.
    finDelHilo.current?.scrollIntoView?.({ behavior: 'smooth', block: 'end' })
  }, [messages, isStreaming, open])

  // UX.1: la caja crece con la pregunta en vez de desplazarse de lado. Se recalcula desde
  // `auto` porque, si no, el alto anterior actúa de suelo y la caja nunca vuelve a encoger.
  const ajustarAltura = (el: HTMLTextAreaElement | null) => {
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, ALTURA_MAXIMA_CAJA)}px`
  }

  const handleSend = async () => {
    const text = input.trim()
    if (!text || isStreaming) return
    setInput('')
    if (cajaDeTexto.current) {
      cajaDeTexto.current.style.height = 'auto'
    }
    await sendMessage(text)
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    // Enter envía y Mayús+Enter hace salto de línea: es lo que la gente espera de un chat,
    // y ahora que la caja crece el salto de línea sirve para algo.
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      void handleSend()
    }
  }

  if (!open) {
    return (
      <button
        type="button"
        data-testid="widget-launcher"
        onClick={() => setOpen(true)}
        aria-label={t('widget_open')}
        style={{
          position: 'fixed',
          bottom: 'var(--widget-bottom, 1.5rem)',
          right: 'var(--widget-right, 1.5rem)',
          width: '3.5rem',
          height: '3.5rem',
          borderRadius: '999px',
          border: 'none',
          background: 'var(--color-primary, ' + AZUL + ')',
          boxShadow: '0 6px 16px rgba(11, 83, 148, .35)',
          cursor: 'pointer',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          zIndex: 2147483000,
        }}
      >
        <IconoChatbot tamano={26} />
      </button>
    )
  }

  return (
    <div
      role="dialog"
      aria-label={t('widget_open')}
      style={{
        // UX.1: el widget trae SU PROPIA CAJA. Antes se renderizaba con `height: 100%`
        // dentro del contenedor y heredaba lo que le diera la página anfitriona, así que
        // en un `<div>` pelado —que es lo que da el fragmento de instalación— se estiraba
        // a ancho completo al final del documento.
        position: 'fixed',
        bottom: 'var(--widget-bottom, 1.5rem)',
        right: 'var(--widget-right, 1.5rem)',
        width: '380px',
        maxWidth: 'calc(100vw - 2rem)',
        height: '560px',
        maxHeight: 'calc(100vh - 3rem)',
        display: 'flex',
        flexDirection: 'column',
        background: '#ffffff',
        borderTop: `4px solid var(--color-primary, ${AZUL})`,
        borderRadius: '10px',
        boxShadow: '0 12px 32px rgba(0, 0, 0, .22)',
        overflow: 'hidden',
        zIndex: 2147483000,
        // UX.1: la letra era demasiado grande. La caja fija su propia escala en vez de
        // heredar la de la página, que en un portal institucional suele ser mayor.
        fontFamily: '-apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif',
        fontSize: '0.875rem',
        lineHeight: 1.5,
        color: TEXTO,
      }}
    >
      <header
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '0.5rem',
          padding: '0.6rem 0.75rem',
          background: `var(--color-primary, ${AZUL})`,
          color: '#ffffff',
        }}
      >
        <IconoChatbot />
        {/* Título propio y no `widget_open`: esa es la etiqueta del botón que abre —«Obri
            el xat»—, y como encabezado del panel ya abierto no dice nada. */}
        {/* El nombre declarado manda sobre la traducción genérica: con dos asistentes sobre
            el mismo corpus, «Asistente» a secas no dice cuál está contestando. */}
        <span
          data-testid="widget-header-title"
          style={{ fontWeight: 600, fontSize: '0.9rem', flex: 1 }}
        >
          {title || t('widget_title')}
        </span>
        {/* HIB.C — empezar de cero. Necesario desde que el historial viaja al servidor: sin
            esto, una pregunta de otro tema se reescribe contra el tema anterior. Sólo se
            ofrece si hay algo que reiniciar, para no poner un mando inerte en la cabecera. */}
        {messages.length > 0 && (
          <button
            type="button"
            onClick={resetConversation}
            aria-label={t('widget_new_conversation')}
            title={t('widget_new_conversation')}
            style={{
              background: 'none',
              border: 'none',
              color: '#ffffff',
              cursor: 'pointer',
              fontSize: '1rem',
              lineHeight: 1,
              padding: '0.15rem 0.3rem',
            }}
          >
            &#8635;
          </button>
        )}
        <button
          type="button"
          onClick={() => setOpen(false)}
          aria-label={t('widget_close')}
          style={{
            background: 'none',
            border: 'none',
            color: '#ffffff',
            cursor: 'pointer',
            fontSize: '1.1rem',
            lineHeight: 1,
            padding: '0.15rem 0.3rem',
          }}
        >
          ✕
        </button>
      </header>

      <div
        role="log"
        aria-live="polite"
        style={{ flex: 1, overflowY: 'auto', padding: '0.75rem' }}
      >
        {messages.map((msg, i) => (
          <div
            key={i}
            data-role={msg.role}
            data-testid={`turn-${msg.role}`}
            style={
              msg.role === 'user'
                ? {
                    // UX.2: la pregunta va enmarcada en azul claro. Antes pregunta y
                    // respuesta se pintaban igual y el hilo era un muro de texto.
                    background: AZUL_CLARO,
                    border: `1px solid ${BORDE_AZUL_CLARO}`,
                    borderRadius: '10px 10px 2px 10px',
                    padding: '0.5rem 0.7rem',
                    marginTop: i === 0 ? '0' : '1.25rem',
                    marginLeft: '1.5rem',
                  }
                : { marginTop: '0.75rem', padding: '0 0.15rem' }
            }
          >
            {msg.role === 'assistant' && translationWarning && i === lastAssistantIdx && (
              <div role="alert" style={{ background: '#fef3c7', padding: '0.5rem', borderRadius: '6px', marginBottom: '0.5rem' }}>
                {translationWarning}
              </div>
            )}
            {msg.role === 'assistant'
              ? <ReactMarkdown>{msg.content}</ReactMarkdown>
              : <p style={{ margin: 0 }}>{msg.content}</p>
            }
            {msg.role === 'assistant' && i === lastAssistantIdx && !isStreaming && (
              <SourcePills sources={sources} />
            )}
          </div>
        ))}
        {/* Ancla del autoscroll: es lo último del hilo, así que llevarla a la vista deja
            visible el final de la respuesta. */}
        <div ref={finDelHilo} />
      </div>

      {isStreaming && (
        <p aria-live="polite" style={{ margin: 0, padding: '0 0.75rem 0.4rem', color: GRIS, fontSize: '0.8rem' }}>
          {currentNodeStatus ? (
            /* UX.3: se traduce el NODO. El texto del servidor solo se usa si ese nodo aún
               no tiene traducción; venía siempre en castellano y se colaba en un widget
               en valenciano. */
            <em>{t(`status.${currentNodeStatus.node}`, { defaultValue: currentNodeStatus.msg })}</em>
          ) : (
            /* UX.7: el primer `status` del servidor tarda unos segundos —hay que resolver
               configuración, detectar idioma y embeber la pregunta antes de poder decir
               nada—. Hasta que llega, quien pregunta no tenía ninguna señal de que se
               hubiera enviado, que es cuando la gente vuelve a pulsar Enviar. */
            <em data-testid="widget-pensando">
              {t('thinking')}
              <span style={{ animation: 'govgenai-parpadeo 1.2s ease-in-out infinite' }}>…</span>
            </em>
          )}
        </p>
      )}

      {isStreaming && (
        <div role="status" aria-label={t('widget_loading')} aria-busy="true" />
      )}

      {/* #278 — el fallo se dice. Antes se tragaba y quedaba una burbuja vacía. */}
      {error && (
        <p
          role="alert"
          data-testid="widget-error"
          style={{ margin: 0, padding: '0 0.75rem 0.4rem', color: '#b42318', fontSize: '0.8rem' }}
        >
          {t(`error_${error}`)}
        </p>
      )}

      {showRating && (
        <div style={{ padding: '0 0.75rem' }}>
          <StarRating interactionId={interactionId!} apiUrl={apiUrl} />
        </div>
      )}

      <div
        style={{
          display: 'flex',
          gap: '0.5rem',
          alignItems: 'flex-end',
          padding: '0.6rem 0.75rem',
          borderTop: '1px solid #e2e6ea',
        }}
      >
        <textarea
          ref={cajaDeTexto}
          rows={1}
          value={input}
          onChange={e => {
            setInput(e.target.value)
            ajustarAltura(e.target)
          }}
          onKeyDown={handleKeyDown}
          placeholder={t('placeholder')}
          disabled={isStreaming}
          style={{
            flex: 1,
            // UX.1: crece con la pregunta. Antes era un `<input>` de una línea y una
            // pregunta larga se leía desplazándose de lado, que es ilegible.
            resize: 'none',
            overflowY: 'auto',
            maxHeight: `${ALTURA_MAXIMA_CAJA}px`,
            padding: '0.45rem 0.6rem',
            border: '1px solid #cbd5e1',
            borderRadius: '8px',
            fontFamily: 'inherit',
            fontSize: '0.875rem',
            lineHeight: 1.4,
            color: TEXTO,
          }}
        />
        <button
          type="button"
          onClick={() => void handleSend()}
          disabled={isStreaming || !input.trim()}
          style={{
            background: `var(--color-primary, ${AZUL})`,
            color: '#ffffff',
            border: 'none',
            borderRadius: '8px',
            padding: '0.45rem 0.85rem',
            fontSize: '0.85rem',
            fontFamily: 'inherit',
            cursor: isStreaming || !input.trim() ? 'default' : 'pointer',
            opacity: isStreaming || !input.trim() ? 0.55 : 1,
          }}
        >
          {t('send')}
        </button>
      </div>

      {/* UX.7: quien pregunta tiene que saber que le contesta una máquina y que puede
          equivocarse. Va al pie y siempre visible, no en un aviso que se cierra: si sólo
          se ve una vez, la mitad de las visitas no lo ve nunca. */}
      <p
        data-testid="widget-aviso-ia"
        style={{
          margin: 0,
          padding: '0 0.75rem 0.6rem',
          color: GRIS,
          fontSize: '0.7rem',
          lineHeight: 1.35,
        }}
      >
        {model ? t('ai_disclaimer_model', { model }) : t('ai_disclaimer')}
      </p>

      {/* AIS.6 — el §13 de la AGPL, y **éste es el caso que se olvida**: la obligación es
          frente a quien usa el programa por red, y la ciudadanía que escribe en este widget lo
          está usando. Ponerlo sólo en el panel dejaría fuera justo a los usuarios más
          numerosos. Vacío `SOURCE_URL`, no se pinta nada. */}
      <div style={{ padding: '0 0.75rem 0.6rem' }}>
        <EnlaceAlFuente
          className=""
          style={{ color: GRIS, fontSize: '0.7rem', textDecoration: 'underline' }}
        />
      </div>

      {/* La animación necesita `@keyframes`, que un `style` en línea no puede declarar. */}
      <style>{'@keyframes govgenai-parpadeo{0%,100%{opacity:.25}50%{opacity:1}}'}</style>
    </div>
  )
}
