import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { useFieldArray, useForm, useWatch, type Control, type FieldErrors, type UseFormRegister } from 'react-hook-form'
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
  useCambiarRegistroApiV1AgentesAgenteIdRegistroPost,
  useProponerPromptApiV1AgentesProponerPromptPost,
  useVerIndiceApiV1AgentesAgenteIdIndiceGet,
} from '@/shared/api/generated/agentes/agentes'
import type { AgenteView, DatoDeLaConsulta, DatoDeLaConsultaView, EstadoDelIndice, PropuestaDePrompt } from '@/shared/api/generated/model'
import { ActualizacionDelIndice } from './ActualizacionDelIndice'
import { CalidadDelAgente } from './CalidadDelAgente'
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
    // #218 — declaraciones del agente: la plataforma las convierte en instrucciones del prompt.
    adjunto: z.enum(['no', 'opcional', 'obligatorio']),
    lengua_respuesta: z.enum(['pregunta', 'es', 'ca']),
    // #219 — los datos que tiene que dar quien pregunta. Las opciones, separadas por comas.
    datos_consulta: z
      .array(
        z.object({
          etiqueta: z.string().trim().min(1, 'obligatorio'),
          tipo: z.enum(['opciones', 'texto']),
          opciones: z.string(),
          ayuda: z.string(),
          columna: z.string(),
          obligatorio: z.boolean(),
          prefijo: z.boolean(),
        }),
      )
      .max(8),
    indicaciones: z.string(),
    // #228 — plazas reservadas por capa del índice; el servidor las vuelve a exigir.
    reservas: z
      .array(
        z.object({
          capa: z.string().trim().min(1, 'obligatorio'),
          plazas: z.number({ message: 'plazas' }).int('plazas').min(1, 'plazas').max(10, 'plazas'),
        }),
      )
      .max(10),
  })
  .superRefine((v, ctx) => {
    v.datos_consulta.forEach((d, i) => {
      if (d.tipo === 'opciones' && separarOpciones(d.opciones).length < 2) {
        ctx.addIssue({ code: 'custom', path: ['datos_consulta', i, 'opciones'], message: 'opciones_minimas' })
      }
    })
    const capas = v.reservas.map((r) => r.capa.trim().toLowerCase())
    if (new Set(capas).size < capas.length) {
      ctx.addIssue({ code: 'custom', path: ['reservas'], message: 'reservas_repetidas' })
    }
    const total = v.reservas.reduce((suma, r) => suma + (Number.isFinite(r.plazas) ? r.plazas : 0), 0)
    if (total > v.presupuesto_documentos) {
      ctx.addIssue({ code: 'custom', path: ['reservas'], message: 'reservas_suman' })
    }
  })
  .refine((v) => v.colectivo === 'organizacion' || separarGrupos(v.grupos).length > 0, {
    path: ['grupos'],
    message: 'grupos_obligatorios',
  })
type Declaracion = z.infer<typeof declaracionSchema>

function separarOpciones(texto: string): string[] {
  return texto
    .split(',')
    .map((o) => o.trim())
    .filter(Boolean)
}

type DatoEditable = Declaracion['datos_consulta'][number]

const DATO_NUEVO: DatoEditable = {
  etiqueta: '',
  tipo: 'texto',
  opciones: '',
  ayuda: '',
  columna: '',
  obligatorio: false,
  prefijo: false,
}

/** Del formulario al contrato: las opciones en lista, y lo vacío como nulo. */
function aContrato(d: DatoEditable): DatoDeLaConsulta {
  return {
    etiqueta: d.etiqueta.trim(),
    tipo: d.tipo,
    ayuda: d.ayuda.trim() || null,
    opciones: d.tipo === 'opciones' ? separarOpciones(d.opciones) : [],
    obligatorio: d.obligatorio,
    columna: d.columna.trim() || null,
    prefijo: d.tipo === 'texto' && d.prefijo,
  }
}

function deContrato(d: DatoDeLaConsultaView): DatoEditable {
  return {
    etiqueta: d.etiqueta,
    tipo: d.tipo,
    opciones: (d.opciones ?? []).join(', '),
    ayuda: d.ayuda ?? '',
    columna: d.columna ?? '',
    obligatorio: d.obligatorio ?? false,
    prefijo: d.prefijo ?? false,
  }
}

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
  adjunto: 'no',
  lengua_respuesta: 'pregunta',
  datos_consulta: [],
  indicaciones: '',
  reservas: [],
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
  const { t, i18n } = useTranslation('agentes')
  const [fallo, setFallo] = useState<string | null>(null)
  const publicar = usePublicarApiV1AgentesPost()
  // #213 — el asistente que propone el prompt. La propuesta va al campo; publicar sigue siendo
  // de la persona. Si se usa, la versión se declara redactada con ayuda de IA.
  const proponer = useProponerPromptApiV1AgentesProponerPromptPost()
  const [pidiendoPropuesta, setPidiendoPropuesta] = useState(false)
  const [descripcion, setDescripcion] = useState('')
  const [propuesta, setPropuesta] = useState<PropuestaDePrompt | null>(null)
  const [falloPropuesta, setFalloPropuesta] = useState<string | null>(null)
  const [autoria, setAutoria] = useState<'persona' | 'ia'>(
    edicion.modo === 'versionar' && edicion.agente.version.autoria_prompt === 'ia' ? 'ia' : 'persona',
  )
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
          adjunto: edicion.agente.version.adjunto as Declaracion['adjunto'],
          lengua_respuesta: edicion.agente.version.lengua_respuesta as Declaracion['lengua_respuesta'],
          datos_consulta: (edicion.agente.version.datos_consulta ?? []).map(deContrato),
          indicaciones: edicion.agente.version.indicaciones ?? '',
          reservas: (edicion.agente.version.reservas ?? []).map((r) => ({ capa: r.capa, plazas: r.plazas })),
        }
      : VACIA

  const {
    register,
    handleSubmit,
    control,
    getValues,
    setValue,
    formState: { errors },
  } = useForm<Declaracion>({ resolver: zodResolver(declaracionSchema), defaultValues: inicial })

  function pedirPropuesta() {
    const v = getValues()
    setFalloPropuesta(null)
    proponer.mutate(
      {
        data: {
          descripcion: descripcion.trim(),
          nombre: v.nombre.trim() || null,
          unidad: v.unidad.trim() || null,
          finalidad: v.finalidad.trim() || null,
          colectivo: v.colectivo,
          grupos: v.colectivo === 'grupos' ? separarGrupos(v.grupos) : [],
          adjunto: v.adjunto,
          lengua_respuesta: v.lengua_respuesta,
          lengua: lenguaDe(i18n.language),
        },
        params: elegida ? { organizacion_id: elegida } : undefined,
      },
      {
        onSuccess: (r: PropuestaDePrompt) => {
          setValue('prompt', r.prompt, { shouldDirty: true, shouldValidate: true })
          setPropuesta(r)
          setAutoria('ia')
        },
        onError: (e: unknown) => setFalloPropuesta(mensajeDelFallo(e, t('fallo'))),
      },
    )
  }
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
      adjunto: v.adjunto,
      lengua_respuesta: v.lengua_respuesta,
      datos_consulta: v.datos_consulta.map(aContrato),
      indicaciones: v.indicaciones.trim() || null,
      reservas: v.reservas.map((r) => ({ capa: r.capa.trim(), plazas: r.plazas })),
      autoria_prompt: autoria,
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
        <button
          type="button"
          onClick={() => setPidiendoPropuesta((v) => !v)}
          className="rounded-md border px-2 py-1 text-xs"
        >
          {t('propuesta.abrir')}
        </button>
        {pidiendoPropuesta && (
          <div className="space-y-1 rounded-md border bg-muted/40 p-2">
            <label htmlFor="agente_descripcion" className="text-xs font-medium">{t('propuesta.descripcion')}</label>
            <textarea
              id="agente_descripcion"
              rows={3}
              maxLength={4000}
              value={descripcion}
              onChange={(e) => setDescripcion(e.target.value)}
              className={campo}
            />
            <p className="text-xs text-muted-foreground">{t('propuesta.pista')}</p>
            <button
              type="button"
              onClick={pedirPropuesta}
              disabled={descripcion.trim().length < 10 || proponer.isPending}
              className="rounded-md bg-primary px-2 py-1 text-xs text-primary-foreground disabled:opacity-50"
            >
              {t('propuesta.pedir')}
            </button>
            {propuesta && (
              <p className="text-xs font-medium" data-testid="aviso-propuesta">
                {t('propuesta.aviso', { modelo: propuesta.modelo_usado })}
              </p>
            )}
            {falloPropuesta && (
              <p className="text-xs text-destructive" role="alert" data-testid="fallo-propuesta">
                {falloPropuesta}
              </p>
            )}
          </div>
        )}
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
        <label htmlFor="agente_adjunto" className="text-sm font-medium">{t('campos.adjunto')}</label>
        <select id="agente_adjunto" className="block rounded-md border px-2 py-1 text-sm" {...register('adjunto')}>
          {(['no', 'opcional', 'obligatorio'] as const).map((valor) => (
            <option key={valor} value={valor}>{t(`adjuntos.${valor}`)}</option>
          ))}
        </select>
        <p className="text-xs text-muted-foreground">{t('pistas.adjunto')}</p>
      </div>

      <div className="space-y-1">
        <label htmlFor="agente_lengua_respuesta" className="text-sm font-medium">{t('campos.lengua_respuesta')}</label>
        <select id="agente_lengua_respuesta" className="block rounded-md border px-2 py-1 text-sm" {...register('lengua_respuesta')}>
          {(['pregunta', 'es', 'ca'] as const).map((valor) => (
            <option key={valor} value={valor}>{t(`lenguas_respuesta.${valor}`)}</option>
          ))}
        </select>
        <p className="text-xs text-muted-foreground">{t('pistas.lengua_respuesta')}</p>
      </div>

      <EditorDeDatos control={control} register={register} errores={errors.datos_consulta} />

      <EditorDeReservas control={control} register={register} errores={errors.reservas} />

      <div className="space-y-1">
        <label htmlFor="agente_indicaciones" className="text-sm font-medium">{t('campos.indicaciones')}</label>
        <textarea id="agente_indicaciones" rows={2} maxLength={500} className={campo} {...register('indicaciones')} />
        <p className="text-xs text-muted-foreground">{t('pistas.indicaciones')}</p>
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
  const [viendoIndice, setViendoIndice] = useState(false)
  const [viendoCalidad, setViendoCalidad] = useState(false)

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
  const cambiarRegistro = useCambiarRegistroApiV1AgentesAgenteIdRegistroPost()

  function pulsar(accion: string) {
    setFallo(null)
    if (accion === 'versionar') alVersionar()
    else if (accion === 'reactivar') reactivar.mutate({ agenteId: agente.id }, opciones)
    else if (accion === 'retirar') retirar.mutate({ agenteId: agente.id }, opciones)
    else if (accion === 'ver_calidad') setViendoCalidad((v) => !v)
    else if (accion === 'cambiar_registro')
      cambiarRegistro.mutate(
        { agenteId: agente.id, data: { modo: agente.modo_registro === 'validacion' ? 'incidencias' : 'validacion' } },
        opciones,
      )
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
        {v.autoria_prompt === 'ia' && (
          <span data-testid="autoria-ia" className="rounded bg-muted px-2 py-0.5 text-xs">
            {t('propuesta.redactado_con_ia')}
          </span>
        )}
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
        <dt className="text-muted-foreground">{t('campos.lengua_respuesta')}</dt>
        <dd data-testid="lengua-respuesta">{t(`lenguas_respuesta.${v.lengua_respuesta}`)}</dd>
        {(v.datos_consulta ?? []).length > 0 && (
          <>
            <dt className="text-muted-foreground">{t('campos.datos_consulta')}</dt>
            <dd data-testid="datos-consulta">
              {(v.datos_consulta ?? [])
                .map((d) => (d.obligatorio ? t('dato_obligatorio', { etiqueta: d.etiqueta }) : d.etiqueta))
                .join(' · ')}
            </dd>
          </>
        )}
        {(v.reservas ?? []).length > 0 && (
          <>
            <dt className="text-muted-foreground">{t('campos.reservas')}</dt>
            <dd data-testid="reservas">
              {(v.reservas ?? []).map((r) => `${r.capa}: ${r.plazas}`).join(' · ')}
            </dd>
          </>
        )}
        {/* #216 — qué se guarda de sus conversaciones. */}
        {/* #217 — sólo lo trae quien puede ver la calidad. */}
        {agente.calidad && (
          <>
            <dt className="text-muted-foreground">{t('campos.calidad')}</dt>
            <dd data-testid="contadores-calidad">
              {t('calidad.contadores', {
                consultas: agente.calidad.consultas,
                leidas: agente.calidad.respuestas_leidas,
                informes: agente.calidad.informes_sin_revisar,
              })}
            </dd>
          </>
        )}
        <dt className="text-muted-foreground">{t('campos.registro')}</dt>
        <dd data-testid="modo-registro">{t(`registro.${agente.modo_registro}`)}</dd>
        <dt className="text-muted-foreground">{t('campos.indice')}</dt>
        <dd>
          <span data-testid="estado-del-indice">{estadoDelIndice(t, agente.indice)}</span>
          {' · '}
          {t('presupuesto_de', { count: v.presupuesto_documentos })}
          {v.adjunto !== 'no' && (
            <>
              {' · '}
              <span>{t(`adjuntos.${v.adjunto}`)}</span>
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

      {/* Avisan, no ocultan: el agente se sigue ofreciendo. */}
      {(agente.indice.sin_actualizar || (agente.indice.faltan ?? 0) > 0 || agente.indice.desfasadas > 0) && (
        <div className="flex flex-wrap gap-2 text-xs">
          {agente.indice.sin_actualizar && (
            <span data-testid="indice-sin-actualizar" className="rounded bg-amber-100 px-2 py-0.5 text-amber-900">
              {t('indice_sin_actualizar')}
            </span>
          )}
          {(agente.indice.faltan ?? 0) > 0 && (
            <span data-testid="faltan-documentos" className="rounded bg-amber-100 px-2 py-0.5 text-amber-900">
              {t('faltan_documentos', { count: agente.indice.faltan ?? 0, carpeta: agente.indice.documentos_en_carpeta })}
            </span>
          )}
          {agente.indice.desfasadas > 0 && (
            <span data-testid="fichas-desfasadas" className="rounded bg-muted px-2 py-0.5">
              {t('fichas_desfasadas', { count: agente.indice.desfasadas })}
            </span>
          )}
        </div>
      )}

      {(permitidas.length > 0 || agente.indice.fichas > 0) && (
        <div className="flex flex-wrap gap-2">
          {permitidas.map((accion) => (
            <button
              key={accion}
              type="button"
              onClick={() => pulsar(accion)}
              className="rounded-md border px-2 py-1 text-xs"
            >
              {/* El botón del registro dice a qué modo pasa, no el nombre de la acción. */}
              {accion === 'cambiar_registro'
                ? t(`acciones.cambiar_registro_desde_${agente.modo_registro}`)
                : t(`acciones.${accion}`, accion)}
            </button>
          ))}
          {agente.indice.fichas > 0 && (
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

      {pidiendo === 'cargar_indice' && <ActualizacionDelIndice agente={agente} />}

      {viendoIndice && <IndiceDelAgente agenteId={agente.id} />}

      {viendoCalidad && <CalidadDelAgente agenteId={agente.id} />}

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

/** «12 fichas · actualizado automáticamente el …», o que todavía no hay índice. */
function estadoDelIndice(t: (k: string, o?: Record<string, unknown>) => string, indice: EstadoDelIndice): string {
  if (!indice.actualizado_en) return t('todavia_sin_indice')
  const fichas = t('fichas_en_el_indice', { count: indice.fichas })
  const fecha = new Date(indice.actualizado_en).toLocaleString()
  return `${fichas} · ${t(indice.origen === 'guion' ? 'actualizado_por_el_guion' : 'actualizado_desde_una_hoja', { fecha })}`
}

/** La lengua en la que se pide la propuesta: la de la pantalla. */
function lenguaDe(idioma: string | undefined): 'es' | 'ca' | 'en' {
  if (idioma?.startsWith('ca') || idioma?.startsWith('va')) return 'ca'
  if (idioma?.startsWith('en')) return 'en'
  return 'es'
}

/**
 * Los datos de la consulta (#219): qué tiene que indicar quien pregunta. Dos tipos —lista de
 * opciones y texto—; ligados a una columna del índice, filtran en suave. Lo valida el servidor;
 * aquí sólo se pide lo que hace falta antes de mandar.
 */
/** #228 — cuántas plazas de cada consulta se reservan a una capa del índice (columna `capa`). */
function EditorDeReservas({
  control,
  register,
  errores,
}: {
  control: Control<Declaracion>
  register: UseFormRegister<Declaracion>
  errores?: FieldErrors<Declaracion>['reservas']
}) {
  const { t } = useTranslation('agentes')
  const { fields, append, remove } = useFieldArray({ control, name: 'reservas' })
  const campo = 'rounded-md border px-2 py-1 text-sm w-full'
  const delConjunto = errores?.root?.message ?? errores?.message

  return (
    <fieldset className="space-y-2 rounded-md border p-3" data-testid="editor-de-reservas">
      <legend className="px-1 text-sm font-medium">{t('campos.reservas')}</legend>
      <p className="text-xs text-muted-foreground">{t('pistas.reservas')}</p>
      {fields.map((f, i) => {
        const fallo = errores?.[i]?.capa?.message ?? errores?.[i]?.plazas?.message
        return (
          <div key={f.id} className="grid items-end gap-2 rounded-md bg-muted/40 p-2 sm:grid-cols-[1fr_8rem_auto]" data-testid={`reserva-${i}`}>
            <label className="space-y-1 text-xs">
              <span>{t('reserva.capa')}</span>
              <input className={campo} {...register(`reservas.${i}.capa`)} />
            </label>
            <label className="space-y-1 text-xs">
              <span>{t('reserva.plazas')}</span>
              <input type="number" min={1} max={10} className={campo} {...register(`reservas.${i}.plazas`, { valueAsNumber: true })} />
            </label>
            <button type="button" onClick={() => remove(i)} className="rounded-md border px-2 py-1 text-xs">
              {t('reserva.quitar')}
            </button>
            {fallo && <p className="text-xs text-destructive sm:col-span-3">{t(`errores.${fallo}`)}</p>}
          </div>
        )
      })}
      {delConjunto && <p className="text-xs text-destructive" role="alert">{t(`errores.${delConjunto}`)}</p>}
      {fields.length < 10 && (
        <button type="button" onClick={() => append({ capa: '', plazas: 1 })} className="rounded-md border px-2 py-1 text-xs">
          {t('reserva.anadir')}
        </button>
      )}
    </fieldset>
  )
}

function EditorDeDatos({
  control,
  register,
  errores,
}: {
  control: Control<Declaracion>
  register: UseFormRegister<Declaracion>
  errores?: FieldErrors<Declaracion>['datos_consulta']
}) {
  const { t } = useTranslation('agentes')
  const { fields, append, remove } = useFieldArray({ control, name: 'datos_consulta' })
  const datos = useWatch({ control, name: 'datos_consulta' })
  const campo = 'rounded-md border px-2 py-1 text-sm w-full'

  return (
    <fieldset className="space-y-2 rounded-md border p-3" data-testid="editor-de-datos">
      <legend className="px-1 text-sm font-medium">{t('campos.datos_consulta')}</legend>
      <p className="text-xs text-muted-foreground">{t('pistas.datos_consulta')}</p>
      {fields.map((f, i) => {
        const tipo = datos?.[i]?.tipo ?? f.tipo
        const fallo = errores?.[i]?.opciones?.message ?? errores?.[i]?.etiqueta?.message
        return (
          <div key={f.id} className="grid gap-2 rounded-md bg-muted/40 p-2 sm:grid-cols-2" data-testid={`dato-${i}`}>
            <label className="space-y-1 text-xs">
              <span>{t('dato.etiqueta')}</span>
              <input className={campo} {...register(`datos_consulta.${i}.etiqueta`)} />
            </label>
            <label className="space-y-1 text-xs">
              <span>{t('dato.tipo')}</span>
              <select className={campo} {...register(`datos_consulta.${i}.tipo`)}>
                <option value="texto">{t('dato.tipos.texto')}</option>
                <option value="opciones">{t('dato.tipos.opciones')}</option>
              </select>
            </label>
            {tipo === 'opciones' && (
              <label className="space-y-1 text-xs sm:col-span-2">
                <span>{t('dato.opciones')}</span>
                <input className={campo} {...register(`datos_consulta.${i}.opciones`)} />
              </label>
            )}
            <label className="space-y-1 text-xs">
              <span>{t('dato.ayuda')}</span>
              <input className={campo} {...register(`datos_consulta.${i}.ayuda`)} />
            </label>
            <label className="space-y-1 text-xs">
              <span>{t('dato.columna')}</span>
              <input className={campo} {...register(`datos_consulta.${i}.columna`)} />
            </label>
            <div className="flex flex-wrap items-center gap-3 text-xs sm:col-span-2">
              <label className="flex items-center gap-1">
                <input type="checkbox" {...register(`datos_consulta.${i}.obligatorio`)} />
                {t('dato.obligatorio')}
              </label>
              {tipo === 'texto' && (
                <label className="flex items-center gap-1">
                  <input type="checkbox" {...register(`datos_consulta.${i}.prefijo`)} />
                  {t('dato.prefijo')}
                </label>
              )}
              <button type="button" onClick={() => remove(i)} className="ml-auto rounded-md border px-2 py-0.5">
                {t('dato.quitar')}
              </button>
            </div>
            {fallo && <p className="text-xs text-destructive sm:col-span-2">{t(`errores.${fallo}`)}</p>}
          </div>
        )
      })}
      {fields.length < 8 && (
        <button type="button" onClick={() => append({ ...DATO_NUEVO })} className="rounded-md border px-2 py-1 text-xs">
          {t('dato.anadir')}
        </button>
      )}
    </fieldset>
  )
}
