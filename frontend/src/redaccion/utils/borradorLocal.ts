/**
 * El borrador de una edición, guardado en el navegador de quien escribe (issue #171).
 *
 * Es lo que queda del autoguardado 1C.1 después de retirarlo: aquella cadena escribía en el
 * servidor por `PATCH /workspaces/{id}/state`, y el contenido de un bloque **ya tiene dueño**
 * —`PATCH /blocks/{id}/edit`, que registra lo que la IA había propuesto (SEG.4)—. Dos caminos de
 * escritura al mismo dato es justo lo que no puede haber.
 *
 * Lo que sí hacía falta conservar es no perder una edición larga si se recarga la pestaña, y eso
 * no necesita servidor: el texto vive en `localStorage`, no sale del navegador, y no toca el
 * bloque hasta que alguien pulsa guardar.
 *
 * **Todo acceso va envuelto**: en una ventana privada, con el almacenamiento bloqueado o con la
 * cuota llena, estas llamadas *lanzan*. Un editor que se cae por no poder guardar un borrador es
 * peor que uno que no lo guarda.
 */

const PREFIJO = 'govgenai.borrador'

function clave(workspaceId: string, blockId: string): string {
  return `${PREFIJO}:${workspaceId}:${blockId}`
}

export function leerBorrador(workspaceId: string, blockId: string): string | null {
  try {
    return window.localStorage.getItem(clave(workspaceId, blockId))
  } catch {
    return null
  }
}

export function guardarBorrador(workspaceId: string, blockId: string, texto: string): void {
  try {
    window.localStorage.setItem(clave(workspaceId, blockId), texto)
  } catch {
    // Sin borrador guardado se sigue pudiendo editar, que es lo que importa.
  }
}

export function olvidarBorrador(workspaceId: string, blockId: string): void {
  try {
    window.localStorage.removeItem(clave(workspaceId, blockId))
  } catch {
    // Nada que hacer: si no se puede leer tampoco se podrá restaurar.
  }
}
