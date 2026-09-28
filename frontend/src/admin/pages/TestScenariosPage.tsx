import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { useQueryClient } from '@tanstack/react-query'
import {
  useListScenariosApiV1HubChatbotsChatbotIdTestScenariosGet,
  useListRunsApiV1HubChatbotsChatbotIdTestScenariosScenarioIdRunsGet,
  useCreateScenarioApiV1HubChatbotsChatbotIdTestScenariosPost,
  useUpdateScenarioApiV1HubChatbotsChatbotIdTestScenariosScenarioIdPatch,
  useDeleteScenarioApiV1HubChatbotsChatbotIdTestScenariosScenarioIdDelete,
  useRunScenarioApiV1HubChatbotsChatbotIdTestScenariosScenarioIdRunPost,
  useSetVerdictApiV1HubChatbotsChatbotIdTestScenariosRunsRunIdVerdictPatch,
  getListScenariosApiV1HubChatbotsChatbotIdTestScenariosGetQueryKey,
  getListRunsApiV1HubChatbotsChatbotIdTestScenariosScenarioIdRunsGetQueryKey,
} from '@/shared/api/generated/hub-test-scenarios/hub-test-scenarios'
import type { RunRead, ScenarioRead } from '@/shared/api/generated/model'
import { useChatbotsDeLaOrganizacion } from '@/shared/organizacion/useChatbotsDeLaOrganizacion'

/**
 * RAG.13 — escenarios de prueba y veredicto humano.
 *
 * Complementa al dataset dorado: aquel mide recuperación con métricas y bloquea el build;
 * esto registra el juicio de una persona sobre la respuesta, que es lo que ninguna métrica
 * sustituye en un asistente normativo. Lo que aporta frente a probar en el widget es que
 * **queda registro**: la misma consulta, ejecutada antes y después de un cambio, con quién
 * la juzgó y por qué.
 */

const esquemaEscenario = z.object({
  name: z.string().min(1),
  prompt: z.string().min(1),
  expectation_note: z.string().optional(),
})

type FormularioEscenario = z.infer<typeof esquemaEscenario>

const VEREDICTOS = ['good', 'bad', 'mixed'] as const

export function TestScenariosPage() {
  const { t } = useTranslation('admin')
  const qc = useQueryClient()

  const [chatbotId, setChatbotId] = useState('')
  const [creando, setCreando] = useState(false)
  // El PATCH existe desde RAG.13 y no lo usaba nadie: se creaba un escenario y ya no se
  // podía corregir ni una errata. Se reutiliza el mismo formulario, prellenado.
  const [editando, setEditando] = useState<ScenarioRead | null>(null)
  const [capturarContexto, setCapturarContexto] = useState(false)
  const [expandido, setExpandido] = useState<string | null>(null)

  const { data: chatbots = [] } = useChatbotsDeLaOrganizacion()
  const { data: escenarios = [] } =
    useListScenariosApiV1HubChatbotsChatbotIdTestScenariosGet(chatbotId, {
      query: { enabled: !!chatbotId },
    })

  const invalidarEscenarios = () =>
    qc.invalidateQueries({
      queryKey: getListScenariosApiV1HubChatbotsChatbotIdTestScenariosGetQueryKey(chatbotId),
    })

  // FIX.1: hasta aquí las mutaciones fallaban en silencio. Un 500 del backend dejaba la
  // pantalla idéntica, así que «no funciona» era literalmente todo lo que se podía observar.
  const [error, setError] = useState('')
  const alFallar = (err: unknown) =>
    setError(err instanceof Error ? err.message : t('hub.test_scenarios.error_generic'))

  const crear = useCreateScenarioApiV1HubChatbotsChatbotIdTestScenariosPost({
    mutation: {
      onSuccess: () => { setCreando(false); setEditando(null); invalidarEscenarios() },
      onError: alFallar,
    },
  })
  const actualizar = useUpdateScenarioApiV1HubChatbotsChatbotIdTestScenariosScenarioIdPatch({
    mutation: {
      onSuccess: () => { setCreando(false); setEditando(null); invalidarEscenarios() },
      onError: alFallar,
    },
  })
  const borrar = useDeleteScenarioApiV1HubChatbotsChatbotIdTestScenariosScenarioIdDelete({
    mutation: { onSuccess: invalidarEscenarios, onError: alFallar },
  })

  const { register, handleSubmit, reset } = useForm<FormularioEscenario>({
    resolver: zodResolver(esquemaEscenario),
  })

  function abrirEdicion(escenario: ScenarioRead) {
    setError('')
    setEditando(escenario)
    setCreando(true)
    reset({
      name: escenario.name,
      prompt: escenario.prompt,
      expectation_note: escenario.expectation_note ?? '',
    })
  }

  function abrirCreacion() {
    setError('')
    setEditando(null)
    setCreando(true)
    reset({ name: '', prompt: '', expectation_note: '' })
  }

  const enviar = handleSubmit((valores) => {
    setError('')
    if (editando) {
      actualizar.mutate({ chatbotId, scenarioId: editando.id, data: valores })
      return
    }
    crear.mutate({ chatbotId, data: { ...valores, history: null } })
    reset()
  })

  return (
    <div className="p-6 space-y-6">
      <header>
        <h1 className="text-2xl font-semibold">{t('hub.test_scenarios.title')}</h1>
        <p className="text-sm text-gray-600">{t('hub.test_scenarios.subtitle')}</p>
      </header>

      <div className="flex items-end gap-4">
        <label className="flex flex-col text-sm">
          <span className="mb-1">{t('hub.test_scenarios.chatbot')}</span>
          <select
            className="border rounded px-2 py-1"
            value={chatbotId}
            onChange={(e) => setChatbotId(e.target.value)}
            aria-label={t('hub.test_scenarios.chatbot')}
          >
            <option value="">{t('hub.test_scenarios.select_chatbot')}</option>
            {chatbots.map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
        </label>

        {chatbotId && (
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={capturarContexto}
              onChange={(e) => setCapturarContexto(e.target.checked)}
              data-testid="capture-context"
            />
            <span title={t('hub.test_scenarios.capture_context_hint')}>
              {t('hub.test_scenarios.capture_context')}
            </span>
          </label>
        )}

        {chatbotId && !creando && (
          <button className="border rounded px-3 py-1" onClick={abrirCreacion}>
            {t('hub.test_scenarios.new')}
          </button>
        )}
      </div>

      {error && (
        <p role="alert" className="text-sm text-red-700 border border-red-300 rounded p-2">
          {error}
        </p>
      )}

      {creando && (
        <form onSubmit={enviar} className="border rounded p-4 space-y-3 max-w-2xl">
          <label className="block text-sm">
            <span>{t('hub.test_scenarios.name')}</span>
            <input className="border rounded w-full px-2 py-1" {...register('name')} />
          </label>
          <label className="block text-sm">
            <span>{t('hub.test_scenarios.prompt')}</span>
            <textarea className="border rounded w-full px-2 py-1" {...register('prompt')} />
          </label>
          <label className="block text-sm">
            <span>{t('hub.test_scenarios.expectation')}</span>
            <textarea
              className="border rounded w-full px-2 py-1"
              {...register('expectation_note')}
            />
            <span className="text-xs text-gray-500">
              {t('hub.test_scenarios.expectation_hint')}
            </span>
          </label>
          <div className="flex gap-2">
            <button type="submit" className="border rounded px-3 py-1">
              {t('hub.test_scenarios.save')}
            </button>
            <button
              type="button"
              className="px-3 py-1"
              onClick={() => { setCreando(false); setEditando(null) }}
            >
              {t('hub.test_scenarios.cancel')}
            </button>
          </div>
        </form>
      )}

      {chatbotId && escenarios.length === 0 && (
        <p className="text-sm text-gray-500">{t('hub.test_scenarios.empty')}</p>
      )}

      <ul className="space-y-4">
        {escenarios.map((escenario) => (
          <Escenario
            key={escenario.id}
            escenario={escenario}
            chatbotId={chatbotId}
            capturarContexto={capturarContexto}
            expandido={expandido}
            onExpandir={setExpandido}
            onBorrar={() => borrar.mutate({ chatbotId, scenarioId: escenario.id })}
            onEditar={() => abrirEdicion(escenario)}
          />
        ))}
      </ul>
    </div>
  )
}

function Escenario({
  escenario,
  chatbotId,
  capturarContexto,
  expandido,
  onExpandir,
  onBorrar,
  onEditar,
}: {
  escenario: ScenarioRead
  chatbotId: string
  capturarContexto: boolean
  expandido: string | null
  onExpandir: (id: string | null) => void
  onBorrar: () => void
  onEditar: () => void
}) {
  const { t } = useTranslation('admin')
  const qc = useQueryClient()

  const { data: runs = [] } =
    useListRunsApiV1HubChatbotsChatbotIdTestScenariosScenarioIdRunsGet(
      chatbotId,
      escenario.id,
      { query: { enabled: !!chatbotId } }
    )

  const invalidarRuns = () =>
    qc.invalidateQueries({
      queryKey: getListRunsApiV1HubChatbotsChatbotIdTestScenariosScenarioIdRunsGetQueryKey(
        chatbotId,
        escenario.id
      ),
    })

  // FIX.1: el fallo de una ejecución era invisible. El endpoint devuelve 500 cuando el
  // modelo del chatbot no responde —le pasó al usuario con `gemini-2.0-flash` retirado— y
  // sin esto el botón se comporta exactamente igual que si no se hubiera pulsado.
  const [errorEjecucion, setErrorEjecucion] = useState('')
  const ejecutar = useRunScenarioApiV1HubChatbotsChatbotIdTestScenariosScenarioIdRunPost({
    mutation: {
      onSuccess: () => { setErrorEjecucion(''); invalidarRuns() },
      onError: (err: unknown) =>
        setErrorEjecucion(
          err instanceof Error ? err.message : t('hub.test_scenarios.error_run')
        ),
    },
  })
  const veredicto = useSetVerdictApiV1HubChatbotsChatbotIdTestScenariosRunsRunIdVerdictPatch({
    mutation: { onSuccess: invalidarRuns },
  })

  return (
    <li className="border rounded p-4 space-y-3">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="font-medium">{escenario.name}</h2>
          <p className="text-sm text-gray-700">{escenario.prompt}</p>
          {escenario.expectation_note && (
            <p className="text-xs text-gray-500 mt-1">{escenario.expectation_note}</p>
          )}
        </div>
        <div className="flex gap-2 shrink-0">
          <button
            className="border rounded px-3 py-1 text-sm"
            data-testid={`run-${escenario.id}`}
            disabled={ejecutar.isPending}
            onClick={() =>
              ejecutar.mutate({
                chatbotId,
                scenarioId: escenario.id,
                params: { capture_context: capturarContexto },
              })
            }
          >
            {t('hub.test_scenarios.run')}
          </button>
          <button
            className="border rounded px-3 py-1 text-sm"
            data-testid={`edit-${escenario.id}`}
            onClick={onEditar}
          >
            {t('hub.test_scenarios.edit')}
          </button>
          <button className="px-3 py-1 text-sm text-red-700" onClick={onBorrar}>
            {t('hub.test_scenarios.delete')}
          </button>
        </div>
      </div>

      {errorEjecucion && (
        <p role="alert" className="text-sm text-red-700">{errorEjecucion}</p>
      )}

      <section>
        <h3 className="text-sm font-medium">{t('hub.test_scenarios.runs')}</h3>
        {runs.length === 0 ? (
          <p className="text-xs text-gray-500">{t('hub.test_scenarios.no_runs')}</p>
        ) : (
          <ul className="space-y-3">
            {runs.map((run) => (
              <Run
                key={run.id}
                run={run}
                onExpandir={() => onExpandir(expandido === run.id ? null : run.id)}
                onVeredicto={(v) =>
                  veredicto.mutate(
                    { chatbotId, runId: run.id, data: { verdict: v } },
                    { onSuccess: invalidarRuns }
                  )
                }
              />
            ))}
          </ul>
        )}
      </section>
    </li>
  )
}

function Run({
  run,
  onExpandir,
  onVeredicto,
}: {
  run: RunRead
  onExpandir: () => void
  onVeredicto: (v: (typeof VEREDICTOS)[number]) => void
}) {
  const { t } = useTranslation('admin')

  return (
    <li className="border-l-2 pl-3 space-y-2">
      <p className="text-xs text-gray-500">{run.executed_at}</p>
      <p className="text-sm whitespace-pre-wrap">{run.answer}</p>

      {run.sources.length > 0 && (
        <div className="text-xs">
          <span className="text-gray-500">{t('hub.test_scenarios.sources')}: </span>
          {run.sources.map((fuente, i) => {
            const f = fuente as { url?: string | null; title?: string | null }
            return (
              <a
                key={i}
                href={f.url ?? undefined}
                className="underline mr-2"
                target="_blank"
                rel="noreferrer"
              >
                {f.title}
              </a>
            )
          })}
        </div>
      )}

      {run.bypass_snapshot && (
        <details data-testid={`context-${run.id}`}>
          <summary className="text-xs cursor-pointer" onClick={onExpandir}>
            {t('hub.test_scenarios.context')}
          </summary>
          <pre className="text-xs bg-gray-50 p-2 overflow-x-auto">
            {JSON.stringify(run.bypass_snapshot, null, 2)}
          </pre>
        </details>
      )}

      <div className="flex items-center gap-2 text-xs">
        <span className="text-gray-500">{t('hub.test_scenarios.verdict')}:</span>
        {VEREDICTOS.map((v) => (
          <button
            key={v}
            data-testid={`verdict-${v}-${run.id}`}
            className={`border rounded px-2 py-0.5 ${
              run.verdict === v ? 'bg-gray-800 text-white' : ''
            }`}
            onClick={() => onVeredicto(v)}
          >
            {t(`hub.test_scenarios.verdict_${v}`)}
          </button>
        ))}
        {run.verdict_by && (
          <span className="text-gray-500">
            {t('hub.test_scenarios.verdict_by')}: {run.verdict_by}
          </span>
        )}
      </div>
    </li>
  )
}
