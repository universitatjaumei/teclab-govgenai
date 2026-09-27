import { useCallback, useEffect, useRef, useState } from 'react'

export type AutosaveStatus = 'saved' | 'saving' | 'offline' | 'conflict'

export interface AutosaveBlockUpdate {
  block_id: string
  state?: string | null
  content?: Record<string, unknown> | null
  expected_block_version: number
}

export interface AutosavePatchInput {
  blockUpdates: AutosaveBlockUpdate[]
  version: number
}

export interface AutosavePatchResult {
  workspace_version: number
  updated_block_versions?: Record<string, number>
  saved_at?: string
}

export interface AutosaveConflictBody {
  current_workspace_version: number
  conflicting_block_ids: string[]
}

export interface AutosavePatchError {
  status?: number
  body?: AutosaveConflictBody
}

export type AutosavePatchFn = (
  workspaceId: string,
  payload: AutosavePatchInput,
) => Promise<AutosavePatchResult>

export interface UseAutosaveOptions {
  onConflict?: (body: AutosaveConflictBody) => void
  debounceMs?: number
  maxRetries?: number
  backoffBaseMs?: number
}

export interface UseAutosaveReturn {
  markDirty: () => void
  status: AutosaveStatus
  workspaceVersion: number
  lastSavedAt: Date | null
}

/**
 * Autosave optimista del workspace (1C.1).
 *
 * - Debounce: agrupa cambios consecutivos en una sola petición tras `debounceMs` (default 1500ms).
 * - Concurrencia optimista: el backend valida `expected_workspace_version` y devuelve 409 si está stale.
 *   En 409 se llama a `onConflict(body)` y el status pasa a 'conflict' (no se reintenta).
 * - Resiliencia: en errores de red se reintenta con backoff exponencial hasta `maxRetries` (default 3).
 *   Si todos fallan, status='offline'.
 */
export function useAutosave(
  workspaceId: string,
  getState: () => AutosavePatchInput,
  patchFn: AutosavePatchFn,
  options: UseAutosaveOptions = {},
): UseAutosaveReturn {
  const debounceMs = options.debounceMs ?? 1500
  const maxRetries = options.maxRetries ?? 3
  const backoffBaseMs = options.backoffBaseMs ?? 1000

  const [status, setStatus] = useState<AutosaveStatus>('saved')
  const [workspaceVersion, setWorkspaceVersion] = useState<number>(() => getState().version)
  const [lastSavedAt, setLastSavedAt] = useState<Date | null>(null)

  // Refs to avoid stale closures: callers can change getState/onConflict freely.
  //
  // **La asignación va en un efecto y no en el cuerpo del componente.** Escribir un ref durante
  // el render es lo que señala `react-hooks/refs`, y no es una formalidad: con el render doble
  // de StrictMode y con las funciones concurrentes de React, el cuerpo puede ejecutarse sin que
  // ese render llegue a confirmarse, así que un ref escrito ahí puede quedar adelantado respecto
  // a lo que hay en pantalla.
  //
  // Aquí es seguro moverlo porque **ninguno de los tres se lee durante el render**: sólo dentro
  // de `runSave` y del temporizador del debounce, que corren después de que los efectos se hayan
  // ejecutado. Comprobado uno a uno antes de tocarlo; si alguno se leyera al renderizar, este
  // cambio le daría el valor del render anterior.
  const getStateRef = useRef(getState)
  const patchFnRef = useRef(patchFn)
  const onConflictRef = useRef(options.onConflict)

  useEffect(() => {
    getStateRef.current = getState
    patchFnRef.current = patchFn
    onConflictRef.current = options.onConflict
  })

  const debounceTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const inFlight = useRef(false)

  const runSave = useCallback(async () => {
    if (inFlight.current) return
    inFlight.current = true
    setStatus('saving')

    try {
      for (let attempt = 0; attempt < maxRetries; attempt++) {
        try {
          const result = await patchFnRef.current(workspaceId, getStateRef.current())
          setWorkspaceVersion(result.workspace_version)
          setLastSavedAt(new Date())
          setStatus('saved')
          return
        } catch (raw) {
          const err = raw as AutosavePatchError
          if (err && err.status === 409 && err.body) {
            setStatus('conflict')
            onConflictRef.current?.(err.body)
            return
          }
          // Network/server error → exponential backoff before retrying.
          if (attempt < maxRetries - 1) {
            const wait = backoffBaseMs * Math.pow(2, attempt)
            await new Promise<void>((resolve) => setTimeout(resolve, wait))
          }
        }
      }
      setStatus('offline')
    } finally {
      inFlight.current = false
    }
  }, [workspaceId, maxRetries, backoffBaseMs])

  const markDirty = useCallback(() => {
    if (debounceTimer.current) clearTimeout(debounceTimer.current)
    debounceTimer.current = setTimeout(() => {
      debounceTimer.current = null
      void runSave()
    }, debounceMs)
  }, [debounceMs, runSave])

  useEffect(() => {
    return () => {
      if (debounceTimer.current) clearTimeout(debounceTimer.current)
    }
  }, [])

  return { markDirty, status, workspaceVersion, lastSavedAt }
}
