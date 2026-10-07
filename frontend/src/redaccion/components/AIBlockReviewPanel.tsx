import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQueryClient } from '@tanstack/react-query'
import {
  useGetWorkspaceById,
  usePatchWorkspaceBlock,
  getGetWorkspaceByIdQueryKey,
} from '@/shared/api/generated/hub-redaccion/hub-redaccion'
import {
  useEditBlock,
  useResumeWorkspace,
} from '@/shared/api/generated/redaccion-workspaces/redaccion-workspaces'
import type { WorkspaceOut } from '@/shared/api/generated/model'
import { StatusBadge } from '@/shared/components/StatusBadge'
import { guardarBorrador, leerBorrador, olvidarBorrador } from '../utils/borradorLocal'
import { mapBlockStatusToUserLabel } from '../utils/statusLabels'

interface Props {
  workspaceId: string
}

/** Las acciones que son una transición de estado; `edit` no lo es (sobreescribe el contenido). */
type AccionDeTransicion = 'approve' | 'reject' | 'regenerate'

/**
 * Cómo se pinta cada acción. INF.2 — el catálogo es **presentación**: qué acciones existen y
 * cuáles caben en este bloque lo decide el servidor (`acciones_permitidas`). El `testid` de
 * editar es `btn-editar` y no `btn-edit` porque así lo llamaban los tests de SEG.4.
 */
const BOTONES: Record<string, { testid: string; clave: string; clase: string }> = {
  approve: {
    testid: 'btn-approve',
    clave: 'review.approve',
    clase: 'px-2 py-1 text-xs bg-green-600 text-white rounded disabled:opacity-50',
  },
  edit: {
    testid: 'btn-editar',
    clave: 'review.edit',
    clase: 'px-2 py-1 text-xs border rounded hover:bg-accent disabled:opacity-50',
  },
  reject: {
    testid: 'btn-reject',
    clave: 'review.reject',
    clase: 'px-2 py-1 text-xs bg-destructive text-destructive-foreground rounded disabled:opacity-50',
  },
  regenerate: {
    testid: 'btn-regenerate',
    clave: 'review.regenerate',
    clase: 'px-2 py-1 text-xs border rounded disabled:opacity-50',
  },
}

/**
 * Revisión de los apartados escritos por la IA (SEG.4).
 *
 * Antes sólo se podía aprobar, rechazar o regenerar. Editar **ya existía en el backend** —el
 * endpoint sobreescribe el contenido y guarda el original en un evento de auditoría con su
 * actor— y el hook generado no lo llamaba ninguna pantalla, así que la supervisión se reducía a
 * un sí o un no sobre un texto que además se mostraba recortado a tres líneas.
 *
 * Tres cosas que esta pantalla enseña y antes no: el texto completo, **de qué tabla se apoya la
 * valoración** (lo que SEG.1 dejó en el bloque) y quién editó, si alguien editó.
 */
export function AIBlockReviewPanel({ workspaceId }: Props) {
  const { t } = useTranslation('common')
  const { t: tR } = useTranslation('redaccion')
  const qc = useQueryClient()

  const [editando, setEditando] = useState<string | null>(null)
  /** INF.3 — bloque cuya regeneración se acaba de pedir, para poder decir qué pasa ahora. */
  const [regenerado, setRegenerado] = useState<string | null>(null)
  const [borrador, setBorrador] = useState('')
  // Issue #171 — el texto que estaba guardado cuando se abrió el editor, para poder volver
  // a él al descartar un borrador recuperado.
  const [textoGuardado, setTextoGuardado] = useState('')
  const [borradorRecuperado, setBorradorRecuperado] = useState(false)
  const [errorAlGuardar, setErrorAlGuardar] = useState<string | null>(null)

  const { data: workspaceRaw, isLoading } = useGetWorkspaceById(workspaceId)
  const workspace = workspaceRaw as unknown as WorkspaceOut | undefined
  const { mutate: patchBlock, isPending } = usePatchWorkspaceBlock()
  const { mutate: editarBloque, isPending: guardando } = useEditBlock()
  /**
   * Issue #85 — continuar el informe cuando la revisión ha acabado.
   *
   * El endpoint existía, el hook estaba generado y **nadie lo llamaba**: el informe se
   * quedaba en `in_review` para siempre y la barra de progreso no pasaba de ahí. Vista
   * previa y exportación funcionaban igual, así que el síntoma era sólo que el estado
   * mentía — y un estado que miente contamina todo lo que se observe después.
   */
  const { mutate: continuar, isPending: continuando } = useResumeWorkspace()
  const [errorAlContinuar, setErrorAlContinuar] = useState('')

  if (isLoading) return <div>{t('loading')}</div>
  if (!workspace) return null

  // INF.2 — se pinta lo que **el servidor** dice que se puede hacer. Antes se filtraba por
  // `status === 'needs_review'`, así que un bloque de IA en `failed` no aparecía y el panel
  // anunciaba «todos aprobados» mientras la exportación devolvía 409 por ese mismo bloque:
  // quien revisaba se quedaba sin nada que pulsar. El frontend no decide estados.
  const pendientes = workspace.blocks.filter((b) => (b.acciones_permitidas ?? []).length > 0)
  // #243 — si se puede ensamblar **lo dice el servidor**. Deducirlo de que no quede nada
  // pendiente anunciaba «todos aprobados» antes de generar nada y dejaba el botón a la vista
  // después de ensamblar, cuando el servidor ya lo rechazaba.
  const puedeEnsamblar = (workspace.acciones_permitidas ?? []).includes('ensamblar')
  const refrescar = {
    onSuccess: () => qc.invalidateQueries({ queryKey: getGetWorkspaceByIdQueryKey(workspaceId) }),
  }

  function actuar(blockId: string, action: AccionDeTransicion) {
    patchBlock({ workspaceId, blockId, data: { action } }, {
      ...refrescar,
      onSuccess: () => {
        refrescar.onSuccess()
        // INF.3 — regenerar **no reescribe el texto en el momento**: saca el bloque de `failed`
        // y el modelo lo redacta en la siguiente generación. Sin decirlo, se lee como un botón
        // que no hizo nada, que es el malentendido que este bloque está arreglando.
        if (action === 'regenerate') setRegenerado(blockId)
      },
    })
  }

  function empezarAEditar(blockId: string, texto: string) {
    // Issue #171 — si quedó un borrador sin guardar (una recarga, una pestaña cerrada), se
    // recupera **diciéndolo**: enseñar un texto que no es el guardado sin avisar es peor que
    // perderlo, porque quien revisa no puede saber qué está leyendo.
    const pendiente = leerBorrador(workspaceId, blockId)
    const hayBorrador = pendiente !== null && pendiente !== texto

    setEditando(blockId)
    setErrorAlGuardar(null)
    setTextoGuardado(texto)
    setBorradorRecuperado(hayBorrador)
    setBorrador(hayBorrador ? (pendiente as string) : texto)
  }

  function escribir(blockId: string, texto: string) {
    setBorrador(texto)
    guardarBorrador(workspaceId, blockId, texto)
  }

  function descartarBorrador(blockId: string) {
    olvidarBorrador(workspaceId, blockId)
    setBorrador(textoGuardado)
    setBorradorRecuperado(false)
  }

  function cerrarEditor(blockId: string) {
    // Cancelar es descartar: el borrador protege de una recarga, no de cambiar de opinión.
    olvidarBorrador(workspaceId, blockId)
    setBorradorRecuperado(false)
    setErrorAlGuardar(null)
    setEditando(null)
  }

  function guardar(blockId: string) {
    setErrorAlGuardar(null)
    editarBloque(
      { workspaceId, blockId, data: { content: { text: borrador.trim() } } },
      {
        // **`onSuccess`, no `onSettled`.** Aquél corre también al fallar, así que un error de
        // red borraba el borrador y cerraba el editor: perdía justo el texto que el borrador
        // existe para no perder. Si el guardado falla, todo se queda como está y se dice.
        onSuccess: () => {
          // **El orden importa.** Primero lo local: si invalidar la caché fallara, el borrador
          // ya guardado se quedaría en el navegador para siempre y la próxima apertura
          // enseñaría un «borrador sin guardar» que sí se había guardado.
          olvidarBorrador(workspaceId, blockId)
          setBorradorRecuperado(false)
          setEditando(null)
          refrescar.onSuccess()
        },
        onError: (error: unknown) => {
          setErrorAlGuardar(error instanceof Error ? error.message : String(error))
        },
      },
    )
  }

  return (
    <div className="space-y-3 p-4">
      {pendientes.length > 0 && (
        <p data-testid="pending-review-count" className="text-sm text-muted-foreground">
          {tR('review.pending', { count: pendientes.length })}
        </p>
      )}

      {puedeEnsamblar && (
        <div className="space-y-2">
          <p data-testid="ready-for-assembly" className="text-sm text-green-700 font-medium">
            {tR('review.all_approved')}
          </p>
          {/* Botón y no automático (issue #85): un efecto sobre `puedeEnsamblar` se dispararía
              más de una vez y el endpoint responde 409 en cuanto el informe sale de
              `in_review`. Quien revisa decide cuándo seguir.

              **El rótulo dice «ensamblar», no «continuar» ni «generar».** Los dos están ya
              cogidos y se pintan en esta misma pantalla —`common.continue` es el botón del
              formulario de datos de partida y `workspace_generate` es «Generar informe»—, así
              que habría habido dos botones con nombre accesible ambiguo a la vez. Lo destapó
              `WorkspacePage.test.tsx` con «Found multiple elements with the role button and
              name /continuar/i», que era un problema de interfaz antes que de test. Y
              «ensamblar» es el verbo que este panel ya usa: el anuncio de al lado dice «listo
              para ensamblar». */}
          <button
            type="button"
            data-testid="btn-continuar"
            disabled={continuando}
            onClick={() => {
              setErrorAlContinuar('')
              continuar(
                { workspaceId },
                {
                  ...refrescar,
                  onError: (fallo: unknown) =>
                    setErrorAlContinuar((fallo as Error)?.message || t('error')),
                },
              )
            }}
            className="px-3 py-1.5 text-sm bg-green-600 text-white rounded disabled:opacity-50"
          >
            {continuando ? t('loading') : tR('review.assemble')}
          </button>
          {errorAlContinuar && (
            <p
              data-testid="error-al-continuar"
              role="alert"
              className="text-xs text-destructive"
            >
              {errorAlContinuar}
            </p>
          )}
        </div>
      )}

      {regenerado && (
        <p data-testid="aviso-regenerado" role="status" className="text-sm text-muted-foreground">
          {tR('review.regenerate_queued', { block: regenerado })}
        </p>
      )}

      {pendientes.map((block) => {
        const contenido = (block.content ?? {}) as Record<string, unknown>
        const texto = typeof contenido.text === 'string' ? contenido.text : ''
        const originalIA =
          typeof contenido.original_ai_text === 'string' ? contenido.original_ai_text : null
        const editadoPor = typeof contenido.edited_by === 'string' ? contenido.edited_by : null
        const fuentes = Array.isArray(contenido.context_block_ids)
          ? (contenido.context_block_ids as string[])
          : []
        const anclado = contenido.context_scope === 'anchored' && fuentes.length > 0

        return (
          <div
            key={block.block_id}
            data-testid={`review-block-${block.block_id}`}
            className="border rounded-md p-3 space-y-2 bg-card"
          >
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium">{block.block_id}</span>
              <div className="flex items-center gap-2">
                <span className="text-xs text-muted-foreground">{block.kind}</span>
                <StatusBadge
                  label={tR(mapBlockStatusToUserLabel(block.status).labelKey)}
                  tone={mapBlockStatusToUserLabel(block.status).tone}
                />
              </div>
            </div>

            {/* De qué se apoyó la valoración. Sin esto, quien revisa no sabe qué debería decir
                el texto — y un apartado que leyó todo el informe merece un aviso, porque es el
                caso que produce resúmenes que omiten. */}
            <p data-testid={`fuente-${block.block_id}`} className="text-xs text-muted-foreground">
              {anclado
                ? tR('review.source_anchored', { tables: fuentes.join(', ') })
                : tR('review.source_full')}
            </p>

            {editando === block.block_id ? (
              <div className="space-y-2">
                {borradorRecuperado && (
                  <p
                    data-testid={`aviso-borrador-${block.block_id}`}
                    className="flex items-center gap-2 text-xs text-amber-600"
                  >
                    {tR('review.draft_recovered')}
                    <button
                      type="button"
                      data-testid={`btn-descartar-borrador-${block.block_id}`}
                      onClick={() => descartarBorrador(block.block_id)}
                      className="underline"
                    >
                      {tR('review.draft_discard')}
                    </button>
                  </p>
                )}
                <textarea
                  data-testid={`editor-${block.block_id}`}
                  value={borrador}
                  onChange={(e) => escribir(block.block_id, e.target.value)}
                  rows={8}
                  aria-label={tR('review.edit_label')}
                  className="w-full border rounded p-2 text-sm resize-y font-serif"
                />
                {errorAlGuardar && (
                  <p
                    data-testid={`error-guardar-${block.block_id}`}
                    className="text-xs text-destructive"
                  >
                    {tR('review.save_failed')}
                  </p>
                )}
                <div className="flex gap-2">
                  <button
                    type="button"
                    data-testid={`btn-guardar-${block.block_id}`}
                    disabled={!borrador.trim() || guardando}
                    onClick={() => guardar(block.block_id)}
                    className="px-2 py-1 text-xs bg-primary text-primary-foreground rounded disabled:opacity-50"
                  >
                    {tR('review.save')}
                  </button>
                  <button
                    type="button"
                    data-testid={`btn-cancelar-${block.block_id}`}
                    onClick={() => cerrarEditor(block.block_id)}
                    className="px-2 py-1 text-xs border rounded"
                  >
                    {t('cancel', 'Cancelar')}
                  </button>
                </div>
              </div>
            ) : (
              <>
                <p className="text-sm whitespace-pre-wrap">{texto}</p>

                {editadoPor && (
                  <p
                    data-testid={`editado-por-${block.block_id}`}
                    className="text-xs text-muted-foreground italic"
                  >
                    {tR('review.edited_by', { who: editadoPor })}
                  </p>
                )}

                {/* El original de la IA sigue a la vista: si no, la edición es irreversible en
                    la práctica, y la evidencia de qué propuso el modelo vive sólo en el
                    registro de auditoría, que ninguna pantalla expone. */}
                {originalIA && (
                  <details className="text-xs">
                    <summary className="cursor-pointer text-muted-foreground">
                      {tR('review.show_original')}
                    </summary>
                    <p
                      data-testid={`original-ia-${block.block_id}`}
                      className="mt-1 p-2 bg-muted rounded whitespace-pre-wrap"
                    >
                      {originalIA}
                    </p>
                  </details>
                )}

                {/* INF.2 — un botón por acción que el servidor permite, **en su orden**. Los
                    cuatro estaban escritos a mano, así que se pintaba «Regenerar» sobre un
                    bloque `needs_review` y esa transición no existe. Si no está en la lista,
                    no hay botón; y si está, el endpoint no puede rechazarla. */}
                <div className="flex gap-2 flex-wrap">
                  {(block.acciones_permitidas ?? []).map((accion) => {
                    const boton = BOTONES[accion]
                    if (!boton) return null
                    return (
                      <button
                        key={accion}
                        type="button"
                        data-testid={`${boton.testid}-${block.block_id}`}
                        disabled={isPending}
                        onClick={() =>
                          accion === 'edit'
                            ? empezarAEditar(block.block_id, texto)
                            : actuar(block.block_id, accion as AccionDeTransicion)
                        }
                        className={boton.clase}
                      >
                        {tR(boton.clave)}
                      </button>
                    )
                  })}
                </div>
              </>
            )}
          </div>
        )
      })}
    </div>
  )
}
