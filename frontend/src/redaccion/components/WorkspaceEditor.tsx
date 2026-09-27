import { useState, useEffect, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { BlockStateAnnouncer } from './BlockStateAnnouncer'
import { StatusBadge } from '@/shared/components/StatusBadge'
import { mapBlockStatusToUserLabel, mapFailureKindToKey } from '../utils/statusLabels'
import type { BlockStateOut } from '@/shared/api/generated/model'

/** El bloque es el del contrato, no una copia a mano.
 *
 * Había aquí una interfaz propia con `[key: string]: unknown`, y ese comodín hacía que
 * `BlockStateOut` —una `interface` generada, sin firma de índice— **no fuera asignable**:
 * `tsc` daba TS2322 en `WorkspacePage` en cuanto se regeneraba el cliente desde
 * `openapi.json`. Usar el tipo generado lo arregla y cumple la regla de contrato: el tipo
 * del componente no puede divergir del servidor porque sale de él. */
export interface WorkspaceData {
  blocks: BlockStateOut[]
  status?: string
}

interface Props {
  workspace: WorkspaceData
}

const ANNOUNCED_STATES = new Set(['extracted', 'ai_generated', 'approved', 'rejected'])

export function WorkspaceEditor({ workspace }: Props) {
  const { t: tR } = useTranslation('redaccion')
  const [announcement, setAnnouncement] = useState('')
  const prevStatusRef = useRef<Map<string, string>>(new Map())

  useEffect(() => {
    const prev = prevStatusRef.current
    let newAnnouncement = ''

    for (const block of workspace.blocks) {
      const blockId = block.block_id
      const currentStatus = block.status
      const prevStatus = prev.get(blockId)

      if (
        prevStatus !== undefined &&
        prevStatus !== currentStatus &&
        ANNOUNCED_STATES.has(currentStatus)
      ) {
        newAnnouncement = tR(`announcer.${currentStatus}`, { label: blockId })
      }
      prev.set(blockId, currentStatus)
    }

    if (newAnnouncement) {
      setAnnouncement(newAnnouncement)
    }
  }, [workspace, tR])

  return (
    <div data-testid="workspace-editor">
      <BlockStateAnnouncer announcement={announcement} />
      <div className="space-y-2">
        {workspace.blocks.map(block => {
          const { labelKey, tone } = mapBlockStatusToUserLabel(
            block.status,
            block.failure_kind ?? null,
          )
          const statusDescId = `block-status-desc-${block.block_id}`
          return (
            <div
              key={block.block_id}
              // INF.3 — el ancla a la que apunta el aviso del 409. Sin ella, «hay que aprobar
              // v_matricula» obliga a buscar el bloque a ojo en una lista larga.
              id={`bloque-${block.block_id}`}
              role="region"
              aria-label={tR('editor.block_region', { type: block.kind, id: block.block_id })}
              aria-describedby={statusDescId}
              data-testid={`block-${block.block_id}`}
              className="flex flex-col px-4 py-3 border rounded-md bg-card"
            >
              <span id={statusDescId} className="sr-only">
                {tR(labelKey)}
              </span>
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <span className="text-sm font-medium">{block.block_id}</span>
                  <span className="text-xs text-muted-foreground">{block.kind}</span>
                </div>
                <StatusBadge label={tR(labelKey)} tone={tone} />
              </div>

              {/* Issue #98 — por que fallo, en el bloque que fallo.
                  `failure_kind`, `last_error_message` y `retry_attempts` vienen en el contrato y
                  no se veian en NINGUN sitio de la aplicacion viva: solo los ensenaba
                  `BlockDebugPanel`, que colgaba de `BlockEditor`, que no montaba ninguna ruta.
                  La pagina decia «ha habido un error» para todo el informe y nada mas, asi que
                  quien redacta no podia decidir si reintentar, cambiar el documento o avisar.

                  **`last_error_message` NO sale, y no es un olvido**: puede traer un traceback
                  con rutas del contenedor, y ocultarselo a quien redacta era una decision
                  tomada —la fijaba `should_not_show_last_error_message_to_regular_user`—. Es la
                  misma fuga que la issue #147 cerro en el chat publico. Lo que se ensena es el
                  motivo traducido y cuantas veces se reintento, que es lo que permite decidir;
                  el error literal vive en el registro del servidor, que desde la issue #18 sale
                  con nivel, marca de tiempo y modulo.

                  Sin condicionar por rol: si el servidor te deja abrir el informe, te deja saber
                  por que fallo tu propio bloque. El panel anterior hacia
                  `if (!isAdmin) return null`, que ademas iba al reves que el servidor. */}
              {block.status === 'failed' && (
                <div
                  data-testid={`block-failure-detail-${block.block_id}`}
                  className="mt-2 rounded-md bg-muted px-3 py-2 text-xs space-y-0.5"
                >
                  <p data-testid={`failure-friendly-message-${block.block_id}`}>
                    {tR(mapFailureKindToKey(block.failure_kind))}
                  </p>
                  <p className="text-muted-foreground">
                    {tR('debug.retry_attempts')}: {block.retry_attempts ?? 0}
                  </p>
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
