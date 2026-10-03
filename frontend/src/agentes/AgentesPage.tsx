import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { useForm, useWatch } from 'react-hook-form'
import { z } from 'zod'
import { zodResolver } from '@hookform/resolvers/zod'
import {
  useListarApiV1AgentesGet,
  usePublicarApiV1AgentesPost,
  useVersionarApiV1AgentesAgenteIdVersionesPost,
  useRevisarApiV1AgentesAgenteIdRevisarPost,
  useSuspenderApiV1AgentesAgenteIdSuspenderPost,
  useReactivarApiV1AgentesAgenteIdReactivarPost,
  useRetirarApiV1AgentesAgenteIdRetirarPost,
  useSubirHojaApiV1AgentesAgenteIdIndiceHojaPost,
  useVerIndiceApiV1AgentesAgenteIdIndiceGet,
} from '@/shared/api/generated/agentes/agentes'
import type { AgenteView, InformeDeCarga } from '@/shared/api/generated/model'
import { mensajeDelFallo } from '@/utilidades/mensajeDelFallo'
import { useOrganizacionElegida } from '@/shared/organizacion/useOrganizacionElegida'

/**
 * Los agentes de unidad (#172): publicar, versionar, revisar, suspender y retirar.
 *
 * **Los botones salen de `acciones_permitidas`**, que calcula el servidor (regla maestra 2): aquí
 * no hay ni un `rol === 'admin'`. Y lo que el servidor exige —la declaración entera, el motivo de
 * una suspensión— se pide **antes** de mandar: cambiar un 422 por un formulario que no avisa no
 * ayuda a nadie.
 */

const declaracionSchema = z
  .object({
    nombre: z.string().trim().min(1, 'obligatorio'),
    unidad: z.string().trim().min(1, 'obligatorio'),
    finalidad: z.string().trim().min(1, 'obligatorio'),
    responsable: z.string().trim().min(1, 'obligatorio'),
    prompt: z.string().trim().min(1, 'obligatorio'),
    carpeta_url: z.string().trim().startsWith('https://', 'carpeta_https'),
    colectivo: z.enum(['organizacion', 'grupos']),
    grupos: z.string(),
    revision_prevista_en: z.string().min(1, 'fecha_obligatoria'),
    // #173 — lo declara el agente; el servidor lo vuelve a exigir.
    presupuesto_documentos: z
      .number({ message: 'presupuesto' })
      .int('presupuesto')
      .min(1, 'presupuesto')
      .max(10, 'presupuesto'),
    espera_adjunto: z.boolean(),
  })
  .refine((v) => v.colectivo === 'organizacion' || separarGrupos(v.grupos).length > 0, {
    path: ['grupos'],
    message: 'grupos_obligatorios',
  })
type Declaracion = z.infer<typeof declaracionSchema>

function separarGrupos(texto: string): string[] {
  return texto
    .split(',')
    .map((g) => g.trim())
    .filter(Boolean)
}

const VACIA: Declaracion = {
  nombre: '',
  unidad: '',
  finalidad: '',
  responsable: '',
  prompt: '',
  carpeta_url: '',
  colectivo: 'organizacion',
  grupos: '',
  revision_prevista_en: '',
  presupuesto_documentos: 5,
  espera_adjunto: false,
}

/** Abierta para publicar uno nuevo, o para versionar uno que ya existe. */
type Edicion = { modo: 'publicar' } | { modo: 'versionar'; agente: AgenteView }

export function AgentesPage() {
  const { t } = useTranslation('agentes')
  const { data, isLoading } = useListarApiV1AgentesGet()
  const [edicion, setEdicion] = useState<Edicion | null>(null)

  const agentes = data?.agentes ?? []
  const gruposDelIdp = data?.grupos_del_idp ?? false

  return (
    <div className="space-y-6">
      <header className="space-y-2">
        <h1 className="text-xl font-semibold">{t('titulo')}</h1>
        <p className="text-sm text-muted-foreground">{t('intro')}</p>
        {!edicion && (
          <button
            type="button"
            onClick={() => setEdicion({ modo: 'publicar' })}
            className="rounded-md bg-primary px-3 py-1.5 text-sm text-primary-foreground"
          >
            {t('publicar_uno')}
          </button>
        )}
      </header>

      {edicion && (
        <FormularioDeDeclaracion
          edicion={edicion}
          gruposDelIdp={gruposDelIdp}
          alTerminar={() => setEdicion(null)}
        />
      )}

      {isLoading ? (
        <p className="text-sm text-muted-foreground">{t('cargando')}</p>
      ) : agentes.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t('ninguno')}</p>
      ) : (
        <ul className="space-y-3">
          {agentes.map((a) => (
            <FichaDelAgente
              key={a.id}
              agente={a}
              alVersionar={() => setEdicion({ modo: 'versionar', agente: a })}
            />
          ))}
        </ul>
      )}
    </div>
  )
}

/** Tras cualquier cambio se invalida por prefijo: el listado y el catálogo miran lo mismo. */
function useAlCambiar(alTerminar?: () => void) {
  const queryClient = useQueryClient()
  return {
    onSuccess: () => {
      void queryClient.invalidateQueries({
        predicate: (consulta) => String(consulta.queryKey[0] ?? '').startsWith('/api/v1/agentes'),
      })
      alTerminar?.()
    },
  }
}

function FormularioDeDeclaracion({
  edicion,
  gruposDelIdp,
  alTerminar,
}: {
  edicion: Edicion
  gruposDelIdp: boolean
  alTerminar: () => void
}) {
  const { t } = useTranslation('agentes')
  const [fallo, setFallo] = useState<string | null>(null)
  const publicar = usePublicarApiV1AgentesPost()
  // Un agente es de una organización: la elegida en el panel, si quien publica no es de una sola.
  const { elegida } = useOrganizacionElegida()
  const versionar = useVersionarApiV1AgentesAgenteIdVersionesPost()
  const alCambiar = useAlCambiar(alTerminar)

  const inicial: Declaracion =
    edicion.modo === 'versionar'
      ? {
          nombre: edicion.agente.nombre,
          unidad: edicion.agente.unidad,
          finalidad: edicion.agente.version.finalidad,
          responsable: edicion.agente.version.responsable,
          prompt: edicion.agente.version.prompt,
          carpeta_url: edicion.agente.version.carpeta_url,
          colectivo: edicion.agente.version.colectivo as Declaracion['colectivo'],
          grupos: (edicion.agente.version.grupos ?? []).join(', '),
          // La fecha se vuelve a declarar: versionar es volver a mirarlo.
          revision_prevista_en: '',
          presupuesto_documentos: edicion.agente.version.presupuesto_documentos,
          espera_adjunto: edicion.agente.version.espera_adjunto,
        }
      : VACIA

  const {
    register,
    handleSubmit,
    control,
    formState: { errors },
  } = useForm<Declaracion>({ resolver: zodResolver(declaracionSchema), defaultValues: inicial })
  const colectivo = useWatch({ control, name: 'colectivo' })

  function enviar(v: Declaracion) {
    setFallo(null)
    const declaracion = {
      finalidad: v.finalidad.trim(),
      responsable: v.responsable.trim(),
      prompt: v.prompt.trim(),
      carpeta_url: v.carpeta_url.trim(),
      colectivo: v.colectivo,
      grupos: v.colectivo === 'grupos' ? separarGrupos(v.grupos) : [],
      revision_prevista_en: v.revision_prevista_en,
      presupuesto_documentos: v.presupuesto_documentos,
      espera_adjunto: v.espera_adjunto,
    }
    const alFallar = { onError: (e: unknown) => setFallo(mensajeDelFallo(e, t('fallo'))) }
    if (edicion.modo === 'versionar') {
      versionar.mutate(
        { agenteId: edicion.agente.id, data: declaracion },
        { ...alCambiar, ...alFallar },
      )
    } else {
      publicar.mutate(
        {
          data: { nombre: v.nombre.trim(), unidad: v.unidad.trim(), ...declaracion },
          params: elegida ? { organizacion_id: elegida } : undefined,
        },
        { ...alCambiar, ...alFallar },
      )
    }
  }

  const error = (campo: keyof Declaracion) => {
    const mensaje = errors[campo]?.message
    return mensaje ? (
      <p className="text-xs text-destructive">{t(`errores.${mensaje}`)}</p>
    ) : null
  }

  const campo = 'rounded-md border px-2 py-1 text-sm w-full'

  return (
    <form
      onSubmit={handleSubmit(enviar)}
      className="space-y-3 rounded-md border p-4"
      aria-label={t(edicion.modo === 'publicar' ? 'publicar_uno' : 'nueva_version')}
    >
      <h2 className="font-medium">
        {edicion.modo === 'publicar'
          ? t('publicar_uno')
          : t('nueva_version_de', { nombre: edicion.agente.nombre })}
      </h2>

      {edicion.modo === 'publicar' && (
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="space-y-1">
            <label htmlFor="agente_nombre" className="text-sm font-medium">{t('campos.nombre')}</label>
            <input id="agente_nombre" className={campo} {...register('nombre')} />
            {error('nombre')}
          </div>
          <div className="space-y-1">
            <label htmlFor="agente_unidad" className="text-sm font-medium">{t('campos.unidad')}</label>
            <input id="agente_unidad" className={campo} {...register('unidad')} />
            {error('unidad')}
          </div>
        </div>
      )}

      <div className="space-y-1">
        <label htmlFor="agente_finalidad" className="text-sm font-medium">{t('campos.finalidad')}</label>
        <input id="agente_finalidad" className={campo} {...register('finalidad')} />
        {error('finalidad')}
      </div>
      <div className="space-y-1">
        <label htmlFor="agente_responsable" className="text-sm font-medium">{t('campos.responsable')}</label>
        <input id="agente_responsable" className={campo} {...register('responsable')} />
        {error('responsable')}
      </div>
      <div className="space-y-1">
        <label htmlFor="agente_prompt" className="text-sm font-medium">{t('campos.prompt')}</label>
        <textarea id="agente_prompt" rows={5} className={campo} {...register('prompt')} />
        {error('prompt')}
      </div>
      <div className="space-y-1">
        <label htmlFor="agente_carpeta" className="text-sm font-medium">{t('campos.carpeta_url')}</label>
        <input id="agente_carpeta" className={campo} {...register('carpeta_url')} />
        <p className="text-xs text-muted-foreground">{t('pistas.carpeta_url')}</p>
        {error('carpeta_url')}
      </div>

      <fieldset className="space-y-1">
        <legend className="text-sm font-medium">{t('campos.colectivo')}</legend>
        <label className="flex items-center gap-2 text-sm">
          <input type="radio" value="organizacion" {...register('colectivo')} />
          {t('colectivos.organizacion')}
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input type="radio" value="grupos" {...register('colectivo')} />
          {t('colectivos.grupos')}
        </label>
        {!gruposDelIdp && (
          <p className="text-xs text-muted-foreground" data-testid="aviso-sin-grupos">
            {t('aviso_sin_grupos')}
          </p>
        )}
      </fieldset>

      {colectivo === 'grupos' && (
        <div className="space-y-1">
          <label htmlFor="agente_grupos" className="text-sm font-medium">{t('campos.grupos')}</label>
          <input id="agente_grupos" className={campo} {...register('grupos')} />
          <p className="text-xs text-muted-foreground">{t('pistas.grupos')}</p>
          {error('grupos')}
        </div>
      )}

      <div className="space-y-1">
        <label htmlFor="agente_revision" className="text-sm font-medium">{t('campos.revision_prevista_en')}</label>
        <input id="agente_revision" type="date" className={campo} {...register('revision_prevista_en')} />
        <p className="text-xs text-muted-foreground">{t('pistas.revision_prevista_en')}</p>
        {error('revision_prevista_en')}
      </div>

      <div className="space-y-1">
        <label htmlFor="agente_presupuesto" className="text-sm font-medium">{t('campos.presupuesto_documentos')}</label>
        <input
          id="agente_presupuesto"
          type="number"
          className="w-24 rounded-md border px-2 py-1 text-sm"
          {...register('presupuesto_documentos', { valueAsNumber: true })}
        />
        <p className="text-xs text-muted-foreground">{t('pistas.presupuesto_documentos')}</p>
        {error('presupuesto_documentos')}
      </div>

      <div className="space-y-1">
        <label className="flex items-center gap-2 text-sm font-medium">
          <input type="checkbox" {...register('espera_adjunto')} />
          {t('campos.espera_adjunto')}
        </label>
        <p className="text-xs text-muted-foreground">{t('pistas.espera_adjunto')}</p>
      </div>

      {fallo && <p className="text-sm text-destructive" role="alert">{fallo}</p>}

      <div className="flex gap-2">
        <button
          type="submit"
          disabled={publicar.isPending || versionar.isPending}
          className="rounded-md bg-primary px-3 py-1.5 text-sm text-primary-foreground disabled:opacity-50"
        >
          {t(edicion.modo === 'publicar' ? 'publicar' : 'registrar_version')}
        </button>
        <button type="button" onClick={alTerminar} className="rounded-md border px-3 py-1.5 text-sm">
          {t('cancelar')}
        </button>
      </div>
    </form>
  )
}

type Pidiendo = 'suspender' | 'revisar' | 'cargar_indice' | null

function FichaDelAgente({ agente, alVersionar }: { agente: AgenteView; alVersionar: () => void }) {
  const { t } = useTranslation('agentes')
  const v = agente.version
  const permitidas = (v.acciones_permitidas ?? []) as string[]
  const [pidiendo, setPidiendo] = useState<Pidiendo>(null)
  const [motivo, setMotivo] = useState('')
  const [resultado, setResultado] = useState<'conforme' | 'correcciones'>('conforme')
  const [nota, setNota] = useState('')
  const [fallo, setFallo] = useState<string | null>(null)
  const [informe, setInforme] = useState<InformeDeCarga | null>(null)
  const [viendoIndice, setViendoIndice] = useState(false)

  const alCambiar = useAlCambiar(() => {
    setPidiendo(null)
    setMotivo('')
    setNota('')
  })
  const opciones = { ...alCambiar, onError: (e: unknown) => setFallo(mensajeDelFallo(e, t('fallo'))) }

  const revisar = useRevisarApiV1AgentesAgenteIdRevisarPost()
  const suspender = useSuspenderApiV1AgentesAgenteIdSuspenderPost()
  const reactivar = useReactivarApiV1AgentesAgenteIdReactivarPost()
  const retirar = useRetirarApiV1AgentesAgenteIdRetirarPost()
  const subirHoja = useSubirHojaApiV1AgentesAgenteIdIndiceHojaPost()
  const alCargar = useAlCambiar()

  function cargarHoja(fichero: File | undefined) {
    if (!fichero) return
    setFallo(null)
    setInforme(null)
    subirHoja.mutate(
      { agenteId: agente.id, data: { file: fichero } },
      {
        onSuccess: (resultado: InformeDeCarga) => {
          setInforme(resultado)
          setPidiendo(null)
          alCargar.onSuccess()
        },
        onError: (e: unknown) => setFallo(mensajeDelFallo(e, t('fallo'))),
      },
    )
  }

  function pulsar(accion: string) {
    setFallo(null)
    if (accion === 'versionar') alVersionar()
    else if (accion === 'reactivar') reactivar.mutate({ agenteId: agente.id }, opciones)
    else if (accion === 'retirar') retirar.mutate({ agenteId: agente.id }, opciones)
    else if (accion === 'suspender' || accion === 'revisar' || accion === 'cargar_indice') setPidiendo(accion)
  }

  return (
    <li className="space-y-2 rounded-md border bg-card p-3" data-testid="agente">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium">{agente.nombre}</span>
        <span className="text-xs text-muted-foreground">{agente.unidad}</span>
        <span className="font-mono text-xs">v{v.version}</span>
        <span data-estado={v.estado} className="rounded bg-muted px-2 py-0.5 text-xs">
          {t(`estados.${v.estado}`, v.estado)}
        </span>
        {v.revision_vencida && (
          <span data-testid="revision-vencida" className="rounded bg-amber-100 px-2 py-0.5 text-xs text-amber-900">
            {t('revision_vencida', { fecha: v.revision_prevista_en })}
          </span>
        )}
      </div>

      <dl className="grid gap-x-4 gap-y-1 text-sm sm:grid-cols-[max-content_1fr]">
        <dt className="text-muted-foreground">{t('campos.finalidad')}</dt>
        <dd>{v.finalidad}</dd>
        <dt className="text-muted-foreground">{t('campos.responsable')}</dt>
        <dd>{v.responsable}</dd>
        <dt className="text-muted-foreground">{t('campos.colectivo')}</dt>
        <dd>
          {v.colectivo === 'grupos'
            ? t('colectivo_grupos', { grupos: (v.grupos ?? []).join(', ') })
            : t('colectivos.organizacion')}
        </dd>
        <dt className="text-muted-foreground">{t('campos.revision_prevista_en')}</dt>
        <dd>{v.revision_prevista_en}</dd>
        <dt className="text-muted-foreground">{t('campos.indice')}</dt>
        <dd>
          {t('fichas_en_el_indice', { count: agente.fichas })}
          {' · '}
          {t('presupuesto_de', { count: v.presupuesto_documentos })}
          {v.espera_adjunto && (
            <>
              {' · '}
              <span>{t('con_adjunto')}</span>
            </>
          )}
        </dd>
        {v.revision_resultado && (
          <>
            <dt className="text-muted-foreground">{t('ultima_revision')}</dt>
            <dd>
              {t(`resultados.${v.revision_resultado}`, v.revision_resultado)}
              {v.revision_nota ? ` — ${v.revision_nota}` : ''}
            </dd>
          </>
        )}
        {/* Sólo mientras lo esté: tras reactivar, el motivo se conserva como historia en la base,
            pero enseñarlo aquí haría creer que sigue suspendido. */}
        {v.estado === 'suspendida' && v.motivo_suspension && (
          <>
            <dt className="text-muted-foreground">{t('motivo_suspension')}</dt>
            <dd>{v.motivo_suspension}</dd>
          </>
        )}
      </dl>

      {(permitidas.length > 0 || agente.fichas > 0) && (
        <div className="flex flex-wrap gap-2">
          {permitidas.map((accion) => (
            <button
              key={accion}
              type="button"
              onClick={() => pulsar(accion)}
              className="rounded-md border px-2 py-1 text-xs"
            >
              {t(`acciones.${accion}`, accion)}
            </button>
          ))}
          {agente.fichas > 0 && (
            <button
              type="button"
              onClick={() => setViendoIndice((v) => !v)}
              className="rounded-md border px-2 py-1 text-xs"
            >
              {t(viendoIndice ? 'ocultar_indice' : 'ver_indice')}
            </button>
          )}
        </div>
      )}

      {pidiendo === 'cargar_indice' && (
        <div className="space-y-1">
          <label htmlFor={`hoja_${agente.id}`} className="text-sm font-medium">{t('hoja_del_indice')}</label>
          <input
            id={`hoja_${agente.id}`}
            type="file"
            accept=".csv,.xlsx"
            disabled={subirHoja.isPending}
            onChange={(e) => cargarHoja(e.target.files?.[0])}
            className="block text-sm"
          />
          <p className="text-xs text-muted-foreground">{t('pistas.hoja_del_indice')}</p>
        </div>
      )}

      {informe && (
        <p className="text-sm" data-testid="informe-de-carga" role="status">
          {t('informe_de_carga', {
            nuevas: t('nuevas', { count: informe.nuevas }),
            actualizadas: t('actualizadas', { count: informe.actualizadas }),
            sin_cambios: t('sin_cambios', { count: informe.sin_cambios }),
            retiradas: t('retiradas', { count: informe.retiradas }),
          })}
        </p>
      )}

      {viendoIndice && <IndiceDelAgente agenteId={agente.id} />}

      {pidiendo === 'suspender' && (
        <div className="space-y-2">
          <label htmlFor={`motivo_${agente.id}`} className="text-sm font-medium">
            {t('motivo_de_la_suspension')}
          </label>
          <textarea
            id={`motivo_${agente.id}`}
            rows={2}
            value={motivo}
            onChange={(e) => setMotivo(e.target.value)}
            className="w-full rounded-md border px-2 py-1 text-sm"
          />
          <button
            type="button"
            disabled={!motivo.trim() || suspender.isPending}
            onClick={() => suspender.mutate({ agenteId: agente.id, data: { motivo: motivo.trim() } }, opciones)}
            className="rounded-md bg-primary px-3 py-1 text-xs text-primary-foreground disabled:opacity-50"
          >
            {t('confirmar_suspension')}
          </button>
        </div>
      )}

      {pidiendo === 'revisar' && (
        <div className="space-y-2">
          <label htmlFor={`resultado_${agente.id}`} className="text-sm font-medium">{t('resultado')}</label>
          <select
            id={`resultado_${agente.id}`}
            value={resultado}
            onChange={(e) => setResultado(e.target.value as 'conforme' | 'correcciones')}
            className="rounded-md border px-2 py-1 text-sm"
          >
            <option value="conforme">{t('resultados.conforme')}</option>
            <option value="correcciones">{t('resultados.correcciones')}</option>
          </select>
          <label htmlFor={`nota_${agente.id}`} className="block text-sm font-medium">{t('nota')}</label>
          <textarea
            id={`nota_${agente.id}`}
            rows={2}
            value={nota}
            onChange={(e) => setNota(e.target.value)}
            className="w-full rounded-md border px-2 py-1 text-sm"
          />
          <button
            type="button"
            disabled={revisar.isPending}
            onClick={() =>
              revisar.mutate(
                { agenteId: agente.id, data: { resultado, nota: nota.trim() || null } },
                opciones,
              )
            }
            className="rounded-md bg-primary px-3 py-1 text-xs text-primary-foreground disabled:opacity-50"
          >
            {t('guardar_revision')}
          </button>
        </div>
      )}

      {fallo && <p className="text-sm text-destructive" role="alert">{fallo}</p>}
    </li>
  )
}

/** Las fichas del índice: título enlazado a su documento, y lo no vigente marcado. */
function IndiceDelAgente({ agenteId }: { agenteId: string }) {
  const { t } = useTranslation('agentes')
  const { data: fichas, isLoading } = useVerIndiceApiV1AgentesAgenteIdIndiceGet(agenteId)
  if (isLoading) return <p className="text-sm text-muted-foreground">{t('cargando')}</p>
  return (
    <ul className="space-y-1 border-l-2 pl-3 text-sm" data-testid="indice">
      {(fichas ?? []).map((f) => (
        <li key={f.url} className="flex flex-wrap items-center gap-2">
          <a href={f.url} target="_blank" rel="noreferrer" className="underline">
            {f.titulo}
          </a>
          {!f.vigente && (
            <span className="rounded bg-muted px-2 py-0.5 text-xs">{t('no_vigente')}</span>
          )}
          {f.revision_prevista_en && (
            <span className="text-xs text-muted-foreground">
              {t('revision_de_la_ficha', { fecha: f.revision_prevista_en })}
            </span>
          )}
        </li>
      ))}
    </ul>
  )
}
