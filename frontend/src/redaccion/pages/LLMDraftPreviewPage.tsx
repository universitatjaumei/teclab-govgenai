import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import {
  useProposeLlmDraft,
  useValidateLlmDraft,
  useApproveAsTemplate,
  useApproveAsWorkspace,
  useDescribeSampleFile,
} from '@/shared/api/generated/redaccion-llm-drafts/redaccion-llm-drafts'
// `ReportTemplateDraft`, uno y no dos. Hasta `fastapi` 0.141 el esquema emitía
// `…Input` y `…Output` para este modelo, y eran **idénticos campo por campo**: la partición
// venía de un `DataTransformBlock` que también se duplicaba sin diferencia. La versión nueva lo
// reconoce y emite un solo esquema, así que el formato del dato **no ha cambiado**; lo que
// cambia es el nombre que genera Orval. Comprobado comparando los tres ficheros generados.
import type {
  ReportTemplateDraft,
  ReportTemplateDraftValidationResult,
  MuestraDeDatos,
} from '@/shared/api/generated/model'
import { useAuth } from '@/shared/auth'
import {
  aplicarArreglo,
  arregloMecanico,
  bloqueDelError,
  claveDelMensaje,
} from '../utils/erroresDeLaPropuesta'

export function LLMDraftPreviewPage() {
  const { t } = useTranslation('common')
  const { t: tR } = useTranslation('redaccion')
  const navigate = useNavigate()
  const { user } = useAuth()
  const isAdmin = user?.role === 'superadmin' || user?.role === 'admin'

  const [promptText, setPromptText] = useState('')
  const [draftName, setDraftName] = useState('')
  // INF.9 — **plantilla por defecto para quien puede elegir**. Del usuario: «por el principio
  // de determinista first deberia sugerirse plantilla por defecto si se va a repetir el
  // informe»; marcarla como recomendada y arrancar en la otra es recomendar de boquilla.
  //
  // Para quien **no** puede elegir —el selector solo se ofrece a admin y superadmin— el defecto
  // tiene que ser el informe suelto: publicar una plantilla es una decision de plataforma, y
  // dejarla como defecto invisible haria que un trabajador creara plantillas sin saberlo.
  const [mode, setMode] = useState<'template' | 'workspace'>(isAdmin ? 'template' : 'workspace')

  /**
   * INF.4 — la estructura del fichero sobre el que va el informe.
   *
   * Se ofrece **antes** del prompt a propósito: sin ella el modelo no conoce las columnas y
   * tiene que adivinarlas, que es lo que hizo fracasar la propuesta en las pruebas del
   * 2026-08-20. El servidor la resume y **anonimiza los valores**, y aquí se enseña lo que se
   * va a enviar: quien pide el informe puede ver qué sale de su organización antes de que
   * salga.
   */
  const [muestra, setMuestra] = useState<MuestraDeDatos | null>(null)
  const [errorDeMuestra, setErrorDeMuestra] = useState('')
  /** Issue #87 — un fallo al aprobar tambien era invisible. Misma convencion que arriba. */
  const [errorDeAprobacion, setErrorDeAprobacion] = useState('')
  const { mutate: describirFichero, isPending: leyendoFichero } = useDescribeSampleFile()

  function elegirFichero(fichero: File | undefined) {
    setErrorDeMuestra('')
    setMuestra(null)
    if (!fichero) return
    describirFichero(
      { data: { file: fichero } },
      {
        onSuccess: (resumen) => setMuestra(resumen as unknown as MuestraDeDatos),
        onError: (fallo: unknown) =>
          setErrorDeMuestra((fallo as Error)?.message || t('error')),
      },
    )
  }

  const { mutate: propose, data: proposedRaw, isPending: isProposing } = useProposeLlmDraft()
  const { mutate: validateMutate, data: validationRaw, isPending: isValidating } = useValidateLlmDraft()
  const { mutate: approveTemplate, isPending: isApprovingTemplate } = useApproveAsTemplate()
  const { mutate: approveWorkspace, isPending: isApprovingWorkspace } = useApproveAsWorkspace()

  /**
   * INF.6 — la propuesta es **editable en la pantalla**.
   *
   * Antes se usaba directamente lo que devolvió el modelo, así que una propuesta rechazada solo
   * se podía tirar: había que volver a escribir el prompt entero. Con una copia local, corregir
   * una referencia y revalidar cuesta una llamada barata a `/validate` y ninguna al modelo.
   */
  const propuestaDelModelo = proposedRaw as unknown as ReportTemplateDraft | undefined

  // **El estado inicial se siembra aquí, y no es un detalle**: si la propuesta ya está en el
  // primer render —una respuesta cacheada, o un test que la inyecta— el `if` de abajo no
  // dispara nunca, porque `propuestaSembrada` nace con ese mismo valor. Sin esta línea el
  // borrador se quedaba en `null` para siempre y la pantalla no mostraba nada: 16 tests lo
  // cazaron.
  const [borrador, setBorrador] = useState<ReportTemplateDraft | null>(
    propuestaDelModelo ?? null,
  )
  const validation = validationRaw as unknown as ReportTemplateDraftValidationResult | undefined
  const isApproving = isApprovingTemplate || isApprovingWorkspace
  const canApprove = !!borrador && !isValidating && (!validation || validation.ok === true)

  // Y cuando la propuesta llega **después** —el caso normal, es una petición—, se siembra
  // durante el render. Es el patrón de React para «reiniciar estado cuando cambia un valor», y
  // quita un hueco que se veía: con el efecto, la pantalla pintaba un fotograma con el borrador
  // vacío —y por tanto con «Aprobar» deshabilitado, porque `canApprove` mira `!!borrador`—
  // justo después de que la propuesta hubiera llegado.
  const [propuestaSembrada, setPropuestaSembrada] = useState(propuestaDelModelo)
  if (propuestaDelModelo !== propuestaSembrada) {
    setPropuestaSembrada(propuestaDelModelo)
    if (propuestaDelModelo) setBorrador(propuestaDelModelo)
  }

  useEffect(() => {
    if (borrador) {
      validateMutate({ data: borrador as unknown as ReportTemplateDraft })
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [borrador])

  /** Aplica el arreglo que el error admite y revalida. Sin volver a consultar al modelo. */
  function corregir(error: { field: string; message: string }) {
    if (!borrador) return
    const arreglo = arregloMecanico(borrador as never, error)
    if (!arreglo) return
    setBorrador(aplicarArreglo(borrador as never, arreglo) as never)
  }

  function handlePropose() {
    if (!promptText) return
    propose({
      data: {
        prompt_nl: promptText,
        mode: mode === 'template' ? 'admin_template' : 'user_workspace',
        // Si no hay fichero va `null` y el servidor se comporta como antes.
        muestra,
      },
    })
  }

  /**
   * Aprobar lleva a lo que se acaba de crear (issue #87).
   *
   * Antes esto disparaba la mutación y terminaba: la plantilla se creaba de verdad y en pantalla
   * no cambiaba nada, así que había que ir a `/redaccion/builder` para saber si había
   * funcionado. El único cambio visible era que el botón se rehabilitaba — indistinguible de un
   * botón roto. Es el mismo fallo que VER.4 arregló en `GenericReportWizard`, y el remedio se
   * copia de allí.
   *
   * **Los dos destinos no son el mismo.** Una plantilla se va a ver al catálogo; un informe se
   * abre por su identificador, que es lo que devuelve `ApproveAsWorkspaceResponse`.
   *
   * Y el error va aquí y no aparte porque tenía la misma forma: un fallo de la mutación también
   * era invisible.
   */
  function handleApprove() {
    if (!borrador || !canApprove) return
    setErrorDeAprobacion('')
    // Se aprueba **el borrador corregido**, no lo que devolvió el modelo.
    const name = draftName || tR('draft_default_name')
    const data = { draft: borrador as unknown as ReportTemplateDraft, name }
    const alFallar = {
      onError: (fallo: unknown) =>
        setErrorDeAprobacion((fallo as Error)?.message || t('error')),
    }
    if (mode === 'template') {
      approveTemplate(
        { data },
        { ...alFallar, onSuccess: () => navigate('/redaccion/builder') },
      )
    } else {
      approveWorkspace(
        { data },
        {
          ...alFallar,
          onSuccess: (creado) =>
            navigate(`/redaccion/workspaces/${(creado as { workspace_id: string }).workspace_id}`),
        },
      )
    }
  }

  return (
    <div className="space-y-4 p-4 max-w-2xl">
      {/* INF.4 — el fichero va antes del prompt: describir un informe sobre datos que el modelo
          no ha visto es pedirle que adivine los nombres de las columnas. Es opcional. */}
      <div className="space-y-2 border rounded p-3 bg-card">
        <label htmlFor="fichero-de-muestra" className="text-sm font-medium block">
          {t('sample_label')}
        </label>
        <p className="text-xs text-muted-foreground">
          {t('sample_help')}
        </p>
        {/* La misma zona que la pantalla del informe (INF.8). Aqui se me habia colado un
            `<input type="file">` desnudo, o sea el navegador pintando su control **en su
            idioma** —«Tria un fitxer» en una pantalla en castellano—, que es exactamente el
            defecto que el usuario reporto. El input sigue recibiendo el fichero y se oculta
            con `sr-only`, no con `display:none`, para no sacarlo del teclado. */}
        <label
          htmlFor="fichero-de-muestra"
          data-testid="zona-muestra"
          className="flex flex-col items-center justify-center gap-1 w-full px-4 py-5 border-2 border-dashed border-input rounded-md cursor-pointer text-center hover:border-primary hover:bg-accent/40 transition-colors"
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault()
            elegirFichero(e.dataTransfer.files?.[0])
          }}
        >
          <span className="text-sm font-medium">{tR('inputs.drop_here')}</span>
          <span className="text-xs text-muted-foreground">
            {tR('inputs.accepted_formats', { formatos: '.csv, .xlsx, .xls' })}
          </span>
        </label>
        <input
          id="fichero-de-muestra"
          data-testid="input-muestra"
          type="file"
          accept=".csv,.xlsx,.xls"
          onChange={(e) => elegirFichero(e.target.files?.[0])}
          className="sr-only"
        />
        {leyendoFichero && <p className="text-xs text-muted-foreground">{t('loading')}</p>}
        {errorDeMuestra && (
          <p role="alert" className="text-xs text-destructive">{errorDeMuestra}</p>
        )}
        {muestra && (
          <div data-testid="resumen-de-muestra" className="text-xs space-y-1">
            <p>
              <strong>{muestra.nombre_del_fichero}</strong> — {muestra.filas_totales}{' '}
              {t('sample_rows')}
            </p>
            {/* Lo que se va a enviar, a la vista. */}
            <p className="text-muted-foreground">{muestra.columnas.join(' · ')}</p>
          </div>
        )}
      </div>

      {/* Prompt input */}
      <div className="space-y-2">
        <textarea
          data-testid="input-prompt"
          value={promptText}
          onChange={e => setPromptText(e.target.value)}
          rows={3}
          placeholder={tR('draft_prompt_placeholder')}
          className="w-full border rounded p-2 text-sm resize-none"
        />
        <button
          type="button"
          data-testid="btn-propose"
          disabled={isProposing || !promptText}
          onClick={handlePropose}
          className="px-4 py-2 text-sm bg-primary text-primary-foreground rounded disabled:opacity-50"
        >
          {isProposing ? t('loading') : tR('draft_propose')}
        </button>
        {/* INF.6 — una espera de treinta segundos con el boton deshabilitado y nada mas se lee
            como una pantalla colgada, y asi la leyo el usuario. Se dice que hay un modelo
            trabajando y que tarda. */}
        {isProposing && (
          <p data-testid="proponiendo" role="status" className="text-xs text-muted-foreground">
            {tR('draft_proposing')}
          </p>
        )}
      </div>

      {/* Draft preview */}
      {borrador && (
        <div data-testid="draft-preview" className="border rounded p-4 space-y-3 bg-card">
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <span>{tR('draft_profile')}: <strong>{borrador.proposed_profile}</strong></span>
            <span>·</span>
            <span>{tR('draft_sections')}: {borrador.proposed_sections?.length ?? 0}</span>
            <span>·</span>
            <span>{tR('draft_model')}: {borrador.model_used}</span>
          </div>

          {borrador.rationale && (
            <p className="text-xs text-muted-foreground italic">{borrador.rationale}</p>
          )}

          {/* INF.6 — los apartados de la propuesta, cada uno con lo que le pasa.
              Antes los errores salían en una lista suelta arriba, con el `field` crudo
              (`blocks[b6].data_block_refs`) y sin nada que tocar: la única salida era volver a
              escribir el prompt. */}
          <ul data-testid="bloques-propuestos" className="space-y-2">
            {(borrador.proposed_blocks ?? []).map((bloque) => {
              const id = (bloque as { id: string }).id
              const suyos = (validation?.errors ?? []).filter((e) => bloqueDelError(e.field) === id)
              return (
                <li
                  key={id}
                  data-testid={`bloque-propuesto-${id}`}
                  className={`border rounded p-2 text-xs ${suyos.length ? 'border-destructive' : ''}`}
                >
                  <div className="flex items-center gap-2">
                    <span className="font-medium">{(bloque as { title?: string }).title ?? id}</span>
                    <span className="text-muted-foreground">{(bloque as { kind: string }).kind}</span>
                  </div>

                  {suyos.map((error, i) => {
                    const clave = claveDelMensaje(error)
                    const arreglo = arregloMecanico(borrador as never, error)
                    return (
                      <div key={i} data-testid={`error-${id}-${i}`} className="mt-1 space-y-1">
                        {/* En lenguaje de quien pide un informe cuando se reconoce el caso; si
                            no, el mensaje del servidor, que es peor que una frase pensada pero
                            mucho mejor que esconderlo. */}
                        <p role="alert" className="text-destructive">
                          {clave ? tR(clave) : error.message}
                        </p>
                        {arreglo && (
                          <button
                            type="button"
                            data-testid={`btn-corregir-${id}`}
                            onClick={() => corregir(error)}
                            className="px-2 py-0.5 border rounded hover:bg-accent"
                          >
                            {tR('draft_error.fix', { de: arreglo.de, a: arreglo.a })}
                          </button>
                        )}
                      </div>
                    )
                  })}
                </li>
              )
            })}
          </ul>

          {/* Los que no hablan de un bloque concreto siguen necesitando un sitio. */}
          {validation && !validation.ok && (
            <ul data-testid="validation-errors" className="space-y-1">
              {(validation.errors ?? [])
                .filter((e) => bloqueDelError(e.field) === null)
                .map((e, i) => (
                  <li key={i} data-testid={`error-${e.field}`} className="text-xs text-destructive">
                    <span className="font-medium">{e.field}</span>: {e.message}
                  </li>
                ))}
            </ul>
          )}

          {/* INF.9 — la eleccion importa y la pantalla no la explicaba: ofrecia «Crear
              workspace» y «Crear plantilla» como equivalentes, con vocabulario interno. Una
              plantilla se reusa y su parte determinista se ejecuta igual cada vez; un informe
              suelto se tira. Es la diferencia entre pagar el LLM una vez y pagarlo cada mes,
              que es el principio determinista-primero del proyecto. */}
          {isAdmin && (
            <div className="space-y-2" data-testid="eleccion-de-modo">
              <div className="flex gap-2">
                <button
                  type="button"
                  data-testid="mode-template"
                  onClick={() => setMode('template')}
                  className={`px-3 py-1 text-xs rounded border transition-colors ${
                    mode === 'template' ? 'bg-primary text-primary-foreground' : 'hover:bg-accent/30'
                  }`}
                >
                  {tR('draft_mode_template')}
                  {/* La recomendacion, marcada: recomendar sin decirlo no es recomendar. */}
                  <span className="ml-1 opacity-80">({tR('draft_recommended')})</span>
                </button>
                <button
                  type="button"
                  data-testid="mode-workspace"
                  onClick={() => setMode('workspace')}
                  className={`px-3 py-1 text-xs rounded border transition-colors ${
                    mode === 'workspace' ? 'bg-primary text-primary-foreground' : 'hover:bg-accent/30'
                  }`}
                >
                  {tR('draft_mode_workspace')}
                </button>
              </div>
              <p data-testid="ayuda-del-modo" className="text-xs text-muted-foreground">
                {mode === 'template' ? tR('draft_mode_help_template') : tR('draft_mode_help_workspace')}
              </p>
            </div>
          )}

          {/* Name input */}
          <input
            data-testid="input-draft-name"
            value={draftName}
            onChange={e => setDraftName(e.target.value)}
            placeholder={mode === 'template' ? tR('draft_name_template') : tR('draft_name_report')}
            className="w-full border rounded px-3 py-1.5 text-sm"
          />

          {/* Approve button */}
          <button
            type="button"
            data-testid="btn-approve"
            disabled={!canApprove || isApproving}
            onClick={handleApprove}
            className="px-4 py-2 text-sm bg-green-600 text-white rounded disabled:opacity-50"
          >
            {isApproving ? t('loading') : tR('draft_approve')}
          </button>

          {/* Issue #87 — un fallo al aprobar se dice aquí, donde se pulsó. Mismo `role="alert"`
              que el error del fichero de muestra: la página ya tenía convención. */}
          {errorDeAprobacion && (
            <p data-testid="error-de-aprobacion" role="alert" className="text-xs text-destructive">
              {errorDeAprobacion}
            </p>
          )}
        </div>
      )}
    </div>
  )
}
