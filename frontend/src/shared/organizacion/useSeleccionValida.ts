import { useEffect } from 'react'

/**
 * Olvida una selección que ya no está en la lista (issue #11).
 *
 * **El defecto que arregla.** Las pantallas guardan el chatbot elegido en su propio estado y sólo
 * lo fijan si está vacío. Al cambiar de organización en la cabecera, el desplegable pasa a
 * enseñar los de la nueva y ese estado sigue apuntando al de la anterior: la consulta
 * dependiente y las mutaciones seguían yendo contra un chatbot de **otra** organización.
 * Enseñar B y trabajar sobre A es peor que no acotar nada, porque parece correcto.
 *
 * Lo señaló la revisión de la PR #187. Mi verificación en el navegador no lo vio porque **no
 * llegué a elegir un chatbot antes de cambiar de organización**, que es justo el paso que lo
 * destapa.
 *
 * **Una lista vacía no vacía la selección**, y esa es la distinción que hace que esto no rompa
 * nada: vacía significa «todavía no ha llegado» —la consulta está en vuelo, o desactivada
 * mientras no hay organización—, no «ese chatbot ya no existe». Confundirlas borraría la
 * selección en cada carga.
 *
 * Vive aquí y no repetido en cada pantalla porque son ocho, y la novena se olvidaría.
 */
export function useSeleccionValida(
  disponibles: { id: string }[],
  seleccionada: string,
  fijar: (id: string) => void,
): void {
  useEffect(() => {
    if (!seleccionada || disponibles.length === 0) return
    if (!disponibles.some((x) => String(x.id) === seleccionada)) fijar('')
  }, [disponibles, seleccionada, fijar])
}
