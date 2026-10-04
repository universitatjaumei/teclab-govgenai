import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  useCatalogoApiV1AgentesCatalogoGet,
  useConsultarApiV1AgentesAgenteIdConsultaPost,
} from '@/shared/api/generated/agentes/agentes'
import type { ConsultaLengua, RespuestaDeConsulta } from '@/shared/api/generated/model'
import { mensajeDelFallo } from '@/utilidades/mensajeDelFallo'
import { ConexionesDeLaExtension } from './ConexionesDeLaExtension'

/**
 * Consultar un agente de unidad y copiar el prompt (#175; decisión del usuario, 2026-10-02).
 *
 * Es el circuito que valida la idea antes de la extensión (#176): la plataforma selecciona los
 * documentos y compone el prompt con los enlaces; la persona lo copia y lo pega en el asistente
 * general de la organización, que los abre con su identidad. **Aquí no se compone nada**: se
 * pinta lo que devuelve el servidor, y cada consulta queda registrada allí.
 */

/** Cuánto se espera al portapapeles antes de dar el copiado por fallido. Sin permiso, algunos
 *  navegadores no rechazan la promesa: la dejan colgada, y la pantalla callaba. */
const ESPERA_DEL_PORTAPAPELES_MS = 3000

/** La lengua de las instrucciones fijas que añade el servidor: la de la pantalla. */
function lenguaDe(idioma: string | undefined): ConsultaLengua {
  if (idioma?.startsWith('ca') || idioma?.startsWith('va')) return 'ca'
  if (idioma?.startsWith('en')) return 'en'
  return 'es'
}

export function ConsultarAgentesPage() {
  const { t, i18n } = useTranslation('agentes')
  const { data: catalogo, isLoading } = useCatalogoApiV1AgentesCatalogoGet()
  const consultar = useConsultarApiV1AgentesAgenteIdConsultaPost()

  const [elegido, setElegido] = useState<string | null>(null)
  const [pregunta, setPregunta] = useState('')
  const [respuesta, setRespuesta] = useState<RespuestaDeConsulta | null>(null)
  const [fallo, setFallo] = useState<string | null>(null)
  const [copiado, setCopiado] = useState<'si' | 'no' | null>(null)
  const cajaDelPrompt = useRef<HTMLTextAreaElement>(null)

  const agentes = catalogo ?? []
  const elegidoEsperaAdjunto = agentes.find((a) => a.id === elegido)?.espera_adjunto ?? false

  function preparar() {
    if (!elegido || !pregunta.trim()) return
    setFallo(null)
    setRespuesta(null)
    setCopiado(null)
    consultar.mutate(
      { agenteId: elegido, data: { consulta: pregunta.trim(), lengua: lenguaDe(i18n.language) } },
      {
        onSuccess: (r: RespuestaDeConsulta) => setRespuesta(r),
        onError: (e: unknown) => setFallo(mensajeDelFallo(e, t('consulta.fallo'))),
      },
    )
  }

  async function copiar() {
    if (!respuesta) return
    try {
      if (!navigator.clipboard) throw new Error('sin portapapeles')
      await Promise.race([
        navigator.clipboard.writeText(respuesta.prompt),
        new Promise((_, rechazar) =>
          setTimeout(() => rechazar(new Error('sin respuesta')), ESPERA_DEL_PORTAPAPELES_MS),
        ),
      ])
      setCopiado('si')
    } catch {
      // Sin permiso, o fuera de https: se deja seleccionado para copiarlo a mano, y se dice.
      cajaDelPrompt.current?.focus()
      cajaDelPrompt.current?.setSelectionRange(0, respuesta.prompt.length)
      setCopiado('no')
    }
  }

  return (
    <div className="space-y-6">
      <header className="space-y-2">
        <h1 className="text-xl font-semibold">{t('consulta.titulo')}</h1>
        <p className="text-sm text-muted-foreground">{t('consulta.intro')}</p>
      </header>

      {isLoading ? (
        <p className="text-sm text-muted-foreground">{t('cargando')}</p>
      ) : agentes.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t('consulta.ninguno')}</p>
      ) : (
        <fieldset className="space-y-2">
          <legend className="text-sm font-medium">{t('consulta.elige')}</legend>
          {agentes.map((a) => (
            <label
              key={a.id}
              data-testid={`agente-${a.id}`}
              className="flex cursor-pointer gap-3 rounded-md border bg-card p-3"
            >
              <input
                type="radio"
                name="agente"
                value={a.id}
                checked={elegido === a.id}
                onChange={() => setElegido(a.id)}
                aria-label={`${a.nombre} — ${a.unidad}`}
              />
              <span className="space-y-1 text-sm">
                <span className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">{a.nombre}</span>
                  <span className="text-xs text-muted-foreground">{a.unidad}</span>
                  {a.espera_adjunto && (
                    <span className="rounded bg-muted px-2 py-0.5 text-xs">{t('consulta.con_adjunto')}</span>
                  )}
                  {a.modo_registro === 'validacion' && (
                    <span data-testid="en-validacion" className="rounded bg-sky-100 px-2 py-0.5 text-xs text-sky-900">
                      {t('consulta.en_validacion')}
                    </span>
                  )}
                  {a.indice_sin_actualizar && (
                    <span
                      data-testid="indice-sin-actualizar"
                      className="rounded bg-amber-100 px-2 py-0.5 text-xs text-amber-900"
                    >
                      {t('consulta.indice_sin_actualizar')}
                    </span>
                  )}
                  {a.revision_vencida && (
                    <span
                      data-testid="revision-vencida"
                      className="rounded bg-amber-100 px-2 py-0.5 text-xs text-amber-900"
                    >
                      {t('consulta.revision_vencida')}
                    </span>
                  )}
                </span>
                <span className="block">{a.finalidad}</span>
                <span className="block text-xs text-muted-foreground">
                  {t('consulta.responsable', { responsable: a.responsable })}
                </span>
              </span>
            </label>
          ))}
        </fieldset>
      )}

      {agentes.length > 0 && (
        <div className="space-y-2">
          <label htmlFor="consulta_pregunta" className="text-sm font-medium">
            {t('consulta.pregunta')}
          </label>
          <textarea
            id="consulta_pregunta"
            rows={3}
            maxLength={2000}
            value={pregunta}
            onChange={(e) => setPregunta(e.target.value)}
            className="w-full rounded-md border px-2 py-1 text-sm"
          />
          {/* La selección sólo ve la pregunta: sin saber de qué trata el adjunto, no acierta. */}
          {elegidoEsperaAdjunto && (
            <p className="text-xs text-muted-foreground">{t('consulta.describe_el_adjunto')}</p>
          )}
          <button
            type="button"
            onClick={preparar}
            disabled={!elegido || !pregunta.trim() || consultar.isPending}
            className="rounded-md bg-primary px-3 py-1.5 text-sm text-primary-foreground disabled:opacity-50"
          >
            {t('consulta.preparar')}
          </button>
        </div>
      )}

      {fallo && (
        <p className="text-sm text-destructive" role="alert">
          {fallo}
        </p>
      )}

      {respuesta && (
        <section className="space-y-3 rounded-md border p-4">
          <h2 className="font-medium">{t('consulta.listo', { agente: respuesta.agente })}</h2>
          <p className="text-xs text-muted-foreground">{t('consulta.como_usarlo')}</p>
          {respuesta.modo_registro === 'validacion' && (
            <p className="text-xs text-muted-foreground" data-testid="aviso-validacion">
              {t('consulta.se_guarda_la_conversacion')}
            </p>
          )}
          {respuesta.espera_adjunto && (
            <p className="text-sm font-medium" data-testid="recordatorio-adjunto">
              {t('consulta.adjunta_el_documento')}
            </p>
          )}
          <textarea
            ref={cajaDelPrompt}
            readOnly
            data-testid="prompt"
            aria-label={t('consulta.prompt')}
            rows={10}
            value={respuesta.prompt}
            className="w-full rounded-md border bg-muted px-2 py-1 font-mono text-xs"
          />
          <div className="flex flex-wrap items-center gap-3">
            <button
              type="button"
              onClick={() => void copiar()}
              className="rounded-md bg-primary px-3 py-1.5 text-sm text-primary-foreground"
            >
              {t('consulta.copiar')}
            </button>
            {copiado && (
              <span className="text-sm" role="status">
                {t(copiado === 'si' ? 'consulta.copiado' : 'consulta.no_copiado')}
              </span>
            )}
          </div>
          {respuesta.documentos.length > 0 && (
            <ul className="space-y-1 text-sm">
              {respuesta.documentos.map((d) => (
                <li key={d.url}>
                  <a href={d.url} target="_blank" rel="noreferrer" className="underline">
                    {d.titulo}
                  </a>
                  {d.revision_vencida && (
                    <span className="ml-2 text-xs text-muted-foreground">
                      {t('consulta.documento_pendiente')}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      <ConexionesDeLaExtension />
    </div>
  )
}
