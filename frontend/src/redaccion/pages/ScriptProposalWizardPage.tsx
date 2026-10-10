import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  useProposeScript,
  useDescribeTestData,
  usePreviewPdfSpans,
  useAnonymizeTestData,
  useTestScriptProposal,
  useValidateTestResult,
  useSaveScriptToPrivateTemplate,
  useSubmitScriptForReview,
} from '@/shared/api/generated/redaccion-scripts/redaccion-scripts'
import { useCategoriasDeDatos } from '@/shared/api/generated/actividad/actividad'
import type {
  AnonymizeTestDataResponse,
  ColumnSubstitution,
  DescribeColumnsResponse,
  ProposeResponse,
  StorageRef,
  TestProposalResponse,
  ValidateTestResultResponse,
} from '@/shared/api/generated/model'
import { ScriptCodePreview } from '../components/ScriptCodePreview'
import { ModelAuditVerdict } from '../components/ModelAuditVerdict'
import { TestDataAnonymizerForm } from '../components/TestDataAnonymizerForm'
import { sustitutoDe } from '../components/sustitutoDe'
import { SandboxTestResultViewer } from '../components/SandboxTestResultViewer'
import { InformeAnonimizacion } from '../components/InformeAnonimizacion'

type TargetOwnerKind = 'user' | 'platform'
type WizardStep = 1 | 2 | 3 | 4 | 5 | 6 | 7
type TestDataKind = 'xlsx' | 'csv' | 'pdf_text'

const STEP_COUNT = 7

/** La semilla del vocabulario de categorías de datos, para cuando el catálogo de la organización
 *  está vacío. **No es la lista cerrada**: el servidor acepta cualquier código y esta pantalla
 *  deja escribir uno que no esté. Está aquí sólo para que la primera persona que declare no se
 *  encuentre un formulario sin opciones. */
const CATEGORIAS_SEMILLA = [
  'sin_datos_personales',
  'datos_identificativos',
  'datos_academicos',
  'datos_economicos_y_financieros',
  'datos_de_contacto',
  'sin_declarar',
]

/** El tipo con el que la plataforma trata el fichero de prueba, por su extensión.
 *
 * `kind` iba fijo a `'csv'` en la llamada de anonimización, así que un `.xlsx` se
 * anonimizaba como si fuera texto separado por comas. */
function tipoDeFichero(nombre: string): TestDataKind {
  const extension = nombre.toLowerCase().split('.').pop() ?? ''
  if (extension === 'pdf') return 'pdf_text'
  if (extension === 'csv') return 'csv'
  return 'xlsx'
}

export function ScriptProposalWizardPage() {
  const { t } = useTranslation('scripts')

  const [step, setStep] = useState<WizardStep>(1)
  const [targetOwnerKind, setTargetOwnerKind] = useState<TargetOwnerKind>('user')
  const [promptNl, setPromptNl] = useState('')
  const [activeProposalId, setActiveProposalId] = useState<string | null>(null)
  // PRO.2 — el fichero de prueba y su tipo, que hasta aquí no se guardaban en ninguna
  // parte: la subida devolvía su `file_ref` y se tiraba, así que los pasos siguientes
  // mandaban `{bucket:'', key:''}` y el script se ejecutaba sin fichero.
  const [testDataKind, setTestDataKind] = useState<TestDataKind | null>(null)
  const [pdfElegido, setPdfElegido] = useState<File | null>(null)
  // #255 — lo que la persona cambia en el paso 4; el resto de columnas sigue la propuesta del
  // servidor, y al anonimizar se mandan todas, que es lo que la pantalla enseña.
  const [sustituciones, setSustituciones] = useState<ColumnSubstitution[]>([])
  // #255 — si la anonimización dejó algo personal, pedir revisión de plantilla global exige
  // aceptarlo; lo decide el informe del servidor, no esta pantalla.
  const [aceptoRestos, setAceptoRestos] = useState(false)
  // La declaración responsable (Instrucció 02/2026 §8.2). Vive aquí y no en la propuesta porque
  // declarar es el acto de compartir: mientras el script es una propuesta sigue en el nivel 1,
  // que es libre y no se declara. Sin esto, `save-to-private-template` respondía **422
  // DECLARACION_INCOMPLETA** desde FUN.3 y el botón «Guardar» no guardaba nada.
  const [finalidad, setFinalidad] = useState('')
  const [nombreDeLaFuncion, setNombreDeLaFuncion] = useState('')
  const [categorias, setCategorias] = useState<string[]>([])
  const [otraCategoria, setOtraCategoria] = useState('')

  // El catálogo de REG: se anuncia, no se impone. Si la consulta no trae nada —organización sin
  // actividad registrada todavía— se ofrece la semilla del vocabulario, porque una lista vacía
  // dejaría a la persona sin poder declarar y por tanto sin poder compartir.
  const categoriasHook = useCategoriasDeDatos()
  const delServidor = (
    (categoriasHook.data as unknown as { codigo: string }[] | undefined) ?? []
  ).map(c => c.codigo)
  const categoriasConocidas = delServidor.length > 0 ? delServidor : CATEGORIAS_SEMILLA

  const proposeHook = useProposeScript()
  const describeHook = useDescribeTestData()
  const previewHook = usePreviewPdfSpans()
  const anonymizeHook = useAnonymizeTestData()
  const testHook = useTestScriptProposal()
  const validateHook = useValidateTestResult()
  const saveHook = useSaveScriptToPrivateTemplate()
  const submitHook = useSubmitScriptForReview()

  const proposal = proposeHook.data as unknown as ProposeResponse | undefined
  const testResult = testHook.data as unknown as TestProposalResponse | undefined
  const validated = validateHook.data as unknown as ValidateTestResultResponse | undefined
  const subida = describeHook.data as unknown as DescribeColumnsResponse | undefined
  const anonimizado = anonymizeHook.data as unknown as AnonymizeTestDataResponse | undefined
  const spansPdf = previewHook.data as unknown as { file_ref: StorageRef } | undefined

  // El fichero original sale de la subida tabular o de la vista previa del PDF; el que se
  // ejecuta es el sintético si se ha anonimizado, y el original si se omitió.
  const refOriginal: StorageRef | undefined = subida?.file_ref ?? spansPdf?.file_ref
  const refDePrueba: StorageRef | undefined = anonimizado?.synthetic_ref ?? refOriginal
  const hayFicheroDePrueba = !!refDePrueba?.key
  const pideAceptarRestos = anonimizado?.informe?.requiere_aceptacion === true

  const auditPassed = proposal?.audit_result?.approved === true
  // **La declaración es parte de poder guardar**, no una validación de formulario: el servidor
  // la exige y sin ella la llamada es un 422. Comprobarla aquí cambia «el botón falla» por «el
  // botón dice qué falta».
  const declaracionCompleta = finalidad.trim().length > 0 && categorias.length > 0
  const canSave = !!validated && declaracionCompleta

  // Auto-advance from step 1 → 2 when proposal arrives
  useEffect(() => {
    if (proposeHook.isSuccess && proposal) {
      setActiveProposalId(proposal.proposal_id)
      setStep(prev => (prev === 1 ? 2 : prev))
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [proposeHook.isSuccess])

  // Auto-advance to step 7 (save/submit) when test result arrives
  useEffect(() => {
    if (testHook.isSuccess && testResult && activeProposalId) {
      setStep(7)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [testHook.isSuccess, activeProposalId])

  function handlePropose() {
    if (!promptNl) return
    proposeHook.mutate({ data: { prompt_nl: promptNl, target_owner_kind: targetOwnerKind } })
  }

  function handleRegenerate() {
    proposeHook.reset()
    setActiveProposalId(null)
    setStep(1)
  }

  function handleTest() {
    if (!activeProposalId || !refDePrueba) return
    testHook.mutate({
      proposalId: activeProposalId,
      data: {
        test_data_ref: refDePrueba,
        // Si no se anonimizó, lo que se va a leer son los datos de verdad. Decirlo es lo
        // que permite al servidor prohibirlo cuando el destino es una plantilla global.
        use_real_data: !anonimizado,
      },
    })
  }

  /** El fichero de prueba, por la vía que le corresponde a su tipo.
   *
   * Mandaba `new Blob()` —un blob vacío— en vez del fichero elegido, y el `file_ref` que
   * devolvía la subida no se guardaba. Los dos endpoints existen desde 9R.5.5: uno describe
   * columnas de un tabular y el otro detecta datos personales en un PDF. */
  function handleFicheroDePrueba(fichero: File | undefined) {
    if (!fichero || !activeProposalId) return
    const kind = tipoDeFichero(fichero.name)
    setTestDataKind(kind)
    setSustituciones([])

    if (kind === 'pdf_text') {
      setPdfElegido(fichero)
      previewHook.mutate({ proposalId: activeProposalId, data: { file: fichero } })
      return
    }
    setPdfElegido(null)
    describeHook.mutate({ proposalId: activeProposalId, data: { file: fichero } })
  }

  function handleValidate() {
    if (!activeProposalId) return
    validateHook.mutate({ proposalId: activeProposalId })
  }

  /** La declaración, tal como la espera el registro. Se compone en un sitio para que los dos
   *  caminos —guardar en plantilla propia y enviar a revisión de plataforma— manden lo mismo:
   *  `approve` también registra en el catálogo desde FUN.3, así que si uno declarara y el otro
   *  no, el hueco se mudaría de sitio en vez de cerrarse. */
  function declaracion() {
    return {
      finalidad: finalidad.trim(),
      categorias_datos: categorias,
      nombre: nombreDeLaFuncion.trim() || null,
    }
  }

  function handleSave() {
    if (!activeProposalId || !canSave) return
    saveHook.mutate({ proposalId: activeProposalId, data: declaracion() }, {})
  }

  function handleSubmitForReview() {
    if (!activeProposalId || !canSave) return
    submitHook.mutate({ proposalId: activeProposalId, data: { acepto_restos: aceptoRestos } }, {})
  }

  return (
    <div className="space-y-6 p-4 max-w-2xl">
      {/* Stepper — always in DOM */}
      <div className="flex items-center gap-1">
        {Array.from({ length: STEP_COUNT }, (_, i) => {
          const n = (i + 1) as WizardStep
          return (
            <div
              key={n}
              data-testid={`wizard-step-${n}`}
              className={`flex-1 h-1.5 rounded-full transition-colors ${
                n < step ? 'bg-primary' : n === step ? 'bg-primary/60' : 'bg-muted'
              }`}
            />
          )
        })}
      </div>

      {/* Persistent target selector */}
      <div className="flex items-center gap-3">
        <label htmlFor="target-owner-kind" className="text-sm font-medium shrink-0">
          {t('target.label')}
        </label>
        <select
          id="target-owner-kind"
          data-testid="select-target-owner-kind"
          value={targetOwnerKind}
          onChange={e => setTargetOwnerKind(e.target.value as TargetOwnerKind)}
          className="text-sm border rounded px-2 py-1"
        >
          <option value="user">{t('target.user')}</option>
          <option value="platform">{t('target.platform')}</option>
        </select>
      </div>

      {/* Step 1: Describe */}
      {step === 1 && (
        <div className="space-y-3">
          <textarea
            data-testid="input-prompt-nl"
            value={promptNl}
            onChange={e => setPromptNl(e.target.value)}
            rows={4}
            placeholder={t('wizard.prompt_placeholder')}
            className="w-full border rounded p-2 text-sm resize-none"
          />
          <button
            type="button"
            data-testid="btn-propose"
            disabled={proposeHook.isPending || !promptNl}
            onClick={handlePropose}
            className="px-4 py-2 text-sm bg-primary text-primary-foreground rounded disabled:opacity-50"
          >
            {proposeHook.isPending ? t('btn.propose') + '…' : t('btn.propose')}
          </button>
        </div>
      )}

      {/* Step 2: Code review */}
      {step === 2 && proposal && (
        <div className="space-y-4">
          <ScriptCodePreview code={proposal.code} auditResult={proposal.audit_result} />
          {proposal.revision_del_modelo && (
            <ModelAuditVerdict revision={proposal.revision_del_modelo} />
          )}
          <div className="flex gap-2">
            <button
              type="button"
              data-testid="btn-regenerate"
              onClick={handleRegenerate}
              className="px-3 py-1.5 text-sm border rounded hover:bg-accent/30"
            >
              {t('btn.regenerate')}
            </button>
            <button
              type="button"
              data-testid="btn-next-step-2"
              aria-disabled={!auditPassed}
              disabled={!auditPassed}
              onClick={() => auditPassed && setStep(3)}
              className="px-3 py-1.5 text-sm bg-primary text-primary-foreground rounded disabled:opacity-50"
            >
              {t('btn.next')}
            </button>
          </div>
        </div>
      )}

      {/* Step 3: Upload test data */}
      {step === 3 && (
        <div className="space-y-3">
          <input
            type="file"
            data-testid="input-test-data-file"
            accept=".csv,.xlsx,.pdf"
            onChange={e => handleFicheroDePrueba(e.target.files?.[0])}
            className="text-sm"
          />
          {hayFicheroDePrueba && (
            <p data-testid="test-data-ready" className="text-xs text-muted-foreground">
              {t('wizard.test_data_ready', { key: refOriginal?.key ?? '' })}
            </p>
          )}
          <button
            type="button"
            data-testid="btn-next-step-3"
            onClick={() => setStep(4)}
            className="px-3 py-1.5 text-sm bg-primary text-primary-foreground rounded"
          >
            {t('btn.next')}
          </button>
        </div>
      )}

      {/* Step 4: Anonymize */}
      {step === 4 && (
        <div className="space-y-4">
          <TestDataAnonymizerForm
            columns={subida?.columns ?? []}
            value={sustituciones}
            onChange={setSustituciones}
          />
          <div className="flex gap-2">
            <button
              type="button"
              data-testid="btn-skip-anonymization"
              aria-disabled={targetOwnerKind === 'platform'}
              disabled={targetOwnerKind === 'platform'}
              onClick={() => targetOwnerKind !== 'platform' && setStep(5)}
              className="px-3 py-1.5 text-sm border rounded disabled:opacity-50"
            >
              {t('btn.skip_anonymization')}
            </button>
            <button
              type="button"
              data-testid="btn-next-step-4"
              onClick={() => {
                if (activeProposalId && refOriginal && testDataKind) {
                  anonymizeHook.mutate({
                    proposalId: activeProposalId,
                    data: {
                      file_ref: refOriginal,
                      kind: testDataKind,
                      ...(subida?.columns?.length
                        ? {
                            substitutions: subida.columns.map(c => ({
                              column_name: c.name,
                              faker_provider: sustitutoDe(c, sustituciones) as ColumnSubstitution['faker_provider'],
                            })),
                          }
                        : {}),
                    },
                  })
                }
                setStep(5)
              }}
              className="px-3 py-1.5 text-sm bg-primary text-primary-foreground rounded"
            >
              {t('btn.next')}
            </button>
          </div>
        </div>
      )}

      {step >= 5 && activeProposalId && anonimizado?.informe && (
        <InformeAnonimizacion informe={anonimizado.informe} proposalId={activeProposalId} />
      )}

      {/* Step 5: PDF preview (optional) */}
      {step === 5 && (
        <div className="space-y-3">
          <p className="text-sm text-muted-foreground">
            {pdfElegido ? t('wizard.step5') : t('wizard.step5_no_aplica')}
          </p>
          <div className="flex gap-2">
            {/* El botón sólo existe con un PDF delante: mandaba un blob vacío, y con un
                fichero tabular no hay nada que previsualizar. */}
            {pdfElegido && (
              <button
                type="button"
                data-testid="btn-preview-pdf"
                onClick={() => {
                  if (activeProposalId) {
                    previewHook.mutate({
                      proposalId: activeProposalId,
                      data: { file: pdfElegido },
                    })
                  }
                }}
                className="px-3 py-1.5 text-sm border rounded"
              >
                {t('wizard.step5')}
              </button>
            )}
            <button
              type="button"
              data-testid="btn-next-step-5"
              onClick={() => setStep(6)}
              className="px-3 py-1.5 text-sm bg-primary text-primary-foreground rounded"
            >
              {t('btn.next')}
            </button>
          </div>
        </div>
      )}

      {/* Step 6: Run test */}
      {step === 6 && (
        <div className="space-y-3">
          <button
            type="button"
            data-testid="btn-run-test"
            aria-disabled={!hayFicheroDePrueba || !activeProposalId}
            disabled={testHook.isPending || !activeProposalId || !hayFicheroDePrueba}
            onClick={handleTest}
            className="px-4 py-2 text-sm bg-primary text-primary-foreground rounded disabled:opacity-50"
          >
            {testHook.isPending ? t('btn.test') + '…' : t('btn.test')}
          </button>
          {!hayFicheroDePrueba && (
            <p data-testid="test-data-missing" className="text-xs text-amber-700">
              {t('wizard.test_data_missing')}
            </p>
          )}
        </div>
      )}

      {/* Step 7: Validate + save/submit */}
      {step === 7 && (
        <div className="space-y-4">
          {testResult && <SandboxTestResultViewer result={testResult} />}

          {/* La declaración responsable. Va **antes** de los botones a propósito: es la condición
              para compartir, no una confirmación posterior. */}
          <fieldset className="border rounded p-3 space-y-3">
            <legend className="text-sm font-medium px-1">{t('declaracion.titulo')}</legend>

            <p className="text-xs text-muted-foreground" data-testid="declaracion-porque">
              {t('declaracion.porque')}
            </p>

            <label className="block space-y-1">
              <span className="text-xs text-muted-foreground">{t('declaracion.finalidad')}</span>
              <textarea
                data-testid="declaracion-finalidad"
                value={finalidad}
                onChange={e => setFinalidad(e.target.value)}
                rows={2}
                placeholder={t('declaracion.finalidad_ejemplo')}
                className="w-full text-sm border rounded p-2 bg-background"
              />
            </label>

            <label className="block space-y-1">
              <span className="text-xs text-muted-foreground">{t('declaracion.nombre')}</span>
              <input
                data-testid="declaracion-nombre"
                value={nombreDeLaFuncion}
                onChange={e => setNombreDeLaFuncion(e.target.value)}
                placeholder={t('declaracion.nombre_ejemplo')}
                className="w-full text-sm border rounded p-2 bg-background"
              />
            </label>

            <div className="space-y-2" data-testid="declaracion-categorias">
              <span className="text-xs text-muted-foreground">
                {t('declaracion.categorias')}
              </span>
              <div className="flex gap-2 flex-wrap">
                {categoriasConocidas.map(codigo => (
                  <button
                    key={codigo}
                    type="button"
                    data-testid={`categoria-${codigo}`}
                    aria-pressed={categorias.includes(codigo)}
                    onClick={() =>
                      setCategorias(previas =>
                        previas.includes(codigo)
                          ? previas.filter(c => c !== codigo)
                          : [...previas, codigo],
                      )
                    }
                    className={`text-xs px-2 py-1 rounded border ${
                      categorias.includes(codigo) ? 'bg-accent font-medium' : 'hover:bg-accent/50'
                    }`}
                  >
                    {codigo}
                  </button>
                ))}
              </div>
              {/* El vocabulario es **abierto** (I4): si la categoría no está, se escribe. Cerrar
                  la lista aquí convertiría algo que está para revisarse en un `Enum` de React. */}
              <div className="flex gap-2 items-center">
                <input
                  data-testid="categoria-otra"
                  value={otraCategoria}
                  onChange={e => setOtraCategoria(e.target.value)}
                  placeholder={t('declaracion.otra_categoria')}
                  className="text-xs border rounded px-2 py-1 bg-background flex-1"
                />
                <button
                  type="button"
                  data-testid="categoria-otra-anadir"
                  disabled={!otraCategoria.trim()}
                  onClick={() => {
                    const codigo = otraCategoria.trim()
                    if (!codigo) return
                    setCategorias(previas =>
                      previas.includes(codigo) ? previas : [...previas, codigo],
                    )
                    setOtraCategoria('')
                  }}
                  className="text-xs px-2 py-1 rounded border disabled:opacity-50"
                >
                  {t('declaracion.anadir')}
                </button>
              </div>
            </div>

            {!declaracionCompleta && (
              <p className="text-xs text-amber-700" data-testid="declaracion-incompleta">
                {t('declaracion.incompleta')}
              </p>
            )}
          </fieldset>

          <button
            type="button"
            data-testid="btn-validate"
            disabled={validateHook.isPending || !testResult || !!validated}
            onClick={handleValidate}
            className="px-3 py-1.5 text-sm border rounded disabled:opacity-50"
          >
            {t('btn.validate')}
          </button>

          {targetOwnerKind === 'user' && (
            <button
              type="button"
              data-testid="btn-save"
              aria-disabled={!canSave}
              disabled={!canSave || saveHook.isPending}
              onClick={handleSave}
              className="px-4 py-2 text-sm bg-green-600 text-white rounded disabled:opacity-50"
            >
              {t('btn.save')}
            </button>
          )}

          {targetOwnerKind === 'platform' && pideAceptarRestos && (
            <label className="flex items-start gap-2 text-sm">
              <input
                type="checkbox"
                data-testid="acepto-restos"
                checked={aceptoRestos}
                onChange={e => setAceptoRestos(e.target.checked)}
              />
              <span>{t('informe_anonimizacion.acepto_restos')}</span>
            </label>
          )}

          {targetOwnerKind === 'platform' && (
            <button
              type="button"
              data-testid="btn-submit-for-review"
              aria-disabled={!canSave || (pideAceptarRestos && !aceptoRestos)}
              disabled={!canSave || (pideAceptarRestos && !aceptoRestos) || submitHook.isPending}
              onClick={handleSubmitForReview}
              className="px-4 py-2 text-sm bg-blue-600 text-white rounded disabled:opacity-50"
            >
              {t('btn.submit_for_review')}
            </button>
          )}
        </div>
      )}
    </div>
  )
}
