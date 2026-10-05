import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQueryClient } from '@tanstack/react-query'
import {
  useConversacionesApiV1AgentesAgenteIdConversacionesGet,
  useMotivosDeInformeApiV1AgentesMotivosDeInformeGet,
  useRevisarConversacionApiV1AgentesConsultasConsultaIdRevisionPut,
} from '@/shared/api/generated/agentes/agentes'
import type { ConversacionDelAgente } from '@/shared/api/generated/model'
import { mensajeDelFallo } from '@/utilidades/mensajeDelFallo'

/**
 * La calidad de un agente (#217): sus conversaciones e informes, y el veredicto de quien revisa.
 *
 * Con la pregunta, los documentos que se ofrecieron y la respuesta juntos se ve **dónde está el
 * fallo**: el índice, el prompt o el modelo. La pista por motivo la da el servidor; los motivos y
 * sus etiquetas, también. **No dice quién preguntó**: para corregir el agente no hace falta.
 */
type Filtros = { modo: '' | 'validacion' | 'incidencias'; puntuacion: '' | '1' | '-1'; motivo: string; sinRevisar: boolean }

function lenguaDe(idioma: string | undefined): 'es' | 'ca' | 'en' {
  if (idioma?.startsWith('ca') || idioma?.startsWith('va')) return 'ca'
  if (idioma?.startsWith('en')) return 'en'
  return 'es'
}

export function CalidadDelAgente({ agenteId }: { agenteId: string }) {
  const { t, i18n } = useTranslation('agentes')
  const [filtros, setFiltros] = useState<Filtros>({ modo: '', puntuacion: '', motivo: '', sinRevisar: false })
  const { data: motivos } = useMotivosDeInformeApiV1AgentesMotivosDeInformeGet({ lengua: lenguaDe(i18n.language) })
  const { data: conversaciones, isLoading } = useConversacionesApiV1AgentesAgenteIdConversacionesGet(agenteId, {
    modo: filtros.modo || undefined,
    puntuacion: filtros.puntuacion ? Number(filtros.puntuacion) : undefined,
    motivo: filtros.motivo || undefined,
    sin_revisar: filtros.sinRevisar || undefined,
  })
  const etiquetaDe = (codigo: string | null | undefined) => motivos?.find((m) => m.codigo === codigo)?.etiqueta ?? codigo

  return (
    <section className="space-y-3 rounded-md border p-3" data-testid="calidad">
      <h3 className="text-sm font-medium">{t('calidad.titulo')}</h3>
      <div className="flex flex-wrap gap-3 text-xs">
        <label className="flex items-center gap-1">
          {t('calidad.filtro_modo')}
          <select value={filtros.modo} onChange={(e) => setFiltros({ ...filtros, modo: e.target.value as Filtros['modo'] })} className="rounded-md border px-1 py-0.5">
            <option value="">{t('calidad.todos')}</option>
            <option value="validacion">{t('registro_corto.validacion')}</option>
            <option value="incidencias">{t('registro_corto.incidencias')}</option>
          </select>
        </label>
        <label className="flex items-center gap-1">
          {t('calidad.filtro_valoracion')}
          <select value={filtros.puntuacion} onChange={(e) => setFiltros({ ...filtros, puntuacion: e.target.value as Filtros['puntuacion'] })} className="rounded-md border px-1 py-0.5">
            <option value="">{t('calidad.todas')}</option>
            <option value="1">👍</option>
            <option value="-1">👎</option>
          </select>
        </label>
        <label className="flex items-center gap-1">
          {t('calidad.filtro_motivo')}
          <select value={filtros.motivo} onChange={(e) => setFiltros({ ...filtros, motivo: e.target.value })} className="rounded-md border px-1 py-0.5">
            <option value="">{t('calidad.todos')}</option>
            {(motivos ?? []).map((m) => (
              <option key={m.codigo} value={m.codigo}>{m.etiqueta}</option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-1">
          <input type="checkbox" checked={filtros.sinRevisar} onChange={(e) => setFiltros({ ...filtros, sinRevisar: e.target.checked })} />
          {t('calidad.sin_revisar')}
        </label>
      </div>
      {isLoading ? (
        <p className="text-sm text-muted-foreground">{t('cargando')}</p>
      ) : (conversaciones ?? []).length === 0 ? (
        <p className="text-sm text-muted-foreground">{t('calidad.ninguna')}</p>
      ) : (
        <ul className="space-y-2">
          {enConversaciones(conversaciones ?? []).map(({ conversacion: c, ampliacion }) => (
            <Conversacion key={c.id} conversacion={c} ampliacion={ampliacion} etiquetaDelMotivo={etiquetaDe(c.motivo)} />
          ))}
        </ul>
      )}
    </section>
  )
}

/**
 * #225 — cada ampliación («Buscar más documentos») justo después de su consulta, en el orden en que
 * se pidieron: es la misma conversación. Si su consulta no está en la página, va suelta.
 */
function enConversaciones(lista: ConversacionDelAgente[]) {
  const ids = new Set(lista.map((c) => c.id))
  const deLaMadre = (c: ConversacionDelAgente) => (c.consulta_madre_id && ids.has(c.consulta_madre_id) ? c.consulta_madre_id : null)
  return lista
    .filter((c) => !deLaMadre(c))
    .flatMap((madre) => [
      { conversacion: madre, ampliacion: Boolean(madre.consulta_madre_id) },
      ...lista
        .filter((c) => deLaMadre(c) === madre.id)
        .sort((a, b) => a.ocurrido_en.localeCompare(b.ocurrido_en))
        .map((c) => ({ conversacion: c, ampliacion: true })),
    ])
}

function Conversacion({
  conversacion: c,
  ampliacion = false,
  etiquetaDelMotivo,
}: {
  conversacion: ConversacionDelAgente
  ampliacion?: boolean
  etiquetaDelMotivo?: string | null
}) {
  const { t } = useTranslation('agentes')
  const queryClient = useQueryClient()
  const revisar = useRevisarConversacionApiV1AgentesConsultasConsultaIdRevisionPut()
  const [veredicto, setVeredicto] = useState<'' | 'good' | 'bad' | 'mixed'>(c.veredicto ?? '')
  const [nota, setNota] = useState(c.nota_revision ?? '')
  const [fallo, setFallo] = useState<string | null>(null)

  function guardar() {
    if (!veredicto) return
    setFallo(null)
    revisar.mutate(
      { consultaId: c.id, data: { veredicto, nota: nota.trim() || null } },
      {
        onSuccess: () =>
          void queryClient.invalidateQueries({
            predicate: (consulta) => String(consulta.queryKey[0] ?? '').startsWith('/api/v1/agentes'),
          }),
        onError: (e: unknown) => setFallo(mensajeDelFallo(e, t('fallo'))),
      },
    )
  }

  return (
    <li className={`space-y-1 rounded-md bg-muted/40 p-2 text-sm ${ampliacion ? 'ml-6' : ''}`} data-testid={`conversacion-${c.id}`}>
      <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        {ampliacion && (
          <span data-testid="ampliacion" className="rounded bg-sky-100 px-1 text-sky-900">
            {t('calidad.ampliacion')}
          </span>
        )}
        <span>{new Date(c.ocurrido_en).toLocaleString()}</span>
        <span>v{c.version}</span>
        <span>{t(`registro_corto.${c.modo}`)}</span>
        {c.puntuacion === 1 && <span>👍</span>}
        {c.puntuacion === -1 && (
          <span data-testid="informe" className="rounded bg-red-100 px-1 text-red-900">👎 {etiquetaDelMotivo}</span>
        )}
        {c.veredicto && <span data-testid="veredicto">{t(`calidad.veredictos.${c.veredicto}`)}</span>}
      </div>
      {c.pregunta && <p className="font-medium">{c.pregunta}</p>}
      {c.datos && Object.keys(c.datos).length > 0 && (
        <p className="text-xs">{Object.entries(c.datos).map(([k, v]) => `${k}: ${v}`).join(' · ')}</p>
      )}
      {c.comentario && <p className="text-xs italic">«{c.comentario}»</p>}
      {c.pista && (
        <p className="text-xs" data-testid="pista">
          {t('calidad.mira_primero')} {t(`calidad.pistas.${c.pista}`)}
        </p>
      )}
      <details className="text-xs">
        <summary className="cursor-pointer">{t('calidad.documentos_ofrecidos', { count: c.documentos.length })}</summary>
        <ul className="ml-4 list-disc">
          {c.documentos.map((d) => (
            <li key={d.url}>
              <a href={d.url} target="_blank" rel="noreferrer" className="underline">{d.titulo ?? d.url}</a> ({d.score.toFixed(2)})
            </li>
          ))}
        </ul>
      </details>
      {c.respuesta ? (
        <details className="text-xs">
          <summary className="cursor-pointer">{t('calidad.respuesta')}</summary>
          <p className="whitespace-pre-wrap">{c.respuesta}</p>
          {(c.fuentes ?? []).length > 0 && (
            <p className="text-muted-foreground">{t('calidad.fuentes_citadas')} {(c.fuentes ?? []).join(', ')}</p>
          )}
        </details>
      ) : c.respuesta_no_capturada ? (
        <p className="text-xs text-muted-foreground">{t(`calidad.sin_captura.${c.respuesta_no_capturada}`)}</p>
      ) : null}
      <div className="flex flex-wrap items-center gap-2 pt-1 text-xs">
        <select
          aria-label={t('calidad.veredicto')}
          value={veredicto}
          onChange={(e) => setVeredicto(e.target.value as typeof veredicto)}
          className="rounded-md border px-1 py-0.5"
        >
          <option value="">{t('calidad.sin_veredicto')}</option>
          <option value="good">{t('calidad.veredictos.good')}</option>
          <option value="mixed">{t('calidad.veredictos.mixed')}</option>
          <option value="bad">{t('calidad.veredictos.bad')}</option>
        </select>
        <input
          aria-label={t('calidad.nota')}
          placeholder={t('calidad.nota')}
          value={nota}
          maxLength={4000}
          onChange={(e) => setNota(e.target.value)}
          className="min-w-40 flex-1 rounded-md border px-1 py-0.5"
        />
        <button type="button" onClick={guardar} disabled={!veredicto || revisar.isPending} className="rounded-md border px-2 py-0.5 disabled:opacity-50">
          {t('calidad.guardar')}
        </button>
      </div>
      {fallo && <p role="alert" className="text-xs text-destructive">{fallo}</p>}
    </li>
  )
}
