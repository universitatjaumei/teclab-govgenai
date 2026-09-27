import { useEffect, useRef } from 'react'
import { useFocusStore, type CopilotAction, type CopilotActionKind } from '../useFocusStore'

/**
 * Hook que consume `pendingAction` del store cuando coincide con `targetKind`.
 *
 * sin-montar: ninguna pantalla lo llama todavía, y es una espera declarada, no un olvido. GUI.5
 * retiró el botón «Aplicar» del Copiloto porque escribía la propuesta en `pendingAction` y
 * **nadie la leía**: un botón que no hace nada es peor que no tenerlo. La propuesta se copia, que
 * es algo que de verdad ocurre. Aplicarla exige una pantalla que la reciba —el asistente de
 * gráficos, el de ETL o el de scripts—, y esa pantalla es lo que falta. Cuando exista, este hook
 * es lo que tiene que llamar: `useCopilotAction(kind, onApply)`.
 */
export function useCopilotAction(
  targetKind: CopilotActionKind,
  onApply: (action: CopilotAction) => void,
): void {
  const pendingAction = useFocusStore((s) => s.pendingAction)
  const clearPendingAction = useFocusStore((s) => s.clearPendingAction)
  // La asignación va en un efecto y no en el cuerpo: escribir un ref durante el render es lo
  // que señala `react-hooks/refs`, y con el render doble de StrictMode o con las funciones
  // concurrentes el cuerpo puede ejecutarse sin que ese render se confirme, dejando el ref
  // adelantado respecto a lo que hay en pantalla.
  //
  // Es seguro aquí porque `onApplyRef` **no se lee durante el render**: sólo dentro del efecto
  // de abajo, que corre después. Mismo caso que `useAutosave`.
  const onApplyRef = useRef(onApply)
  useEffect(() => {
    onApplyRef.current = onApply
  })

  useEffect(() => {
    if (pendingAction && pendingAction.kind === targetKind) {
      onApplyRef.current(pendingAction)
      clearPendingAction()
    }
  }, [pendingAction, targetKind, clearPendingAction])
}
