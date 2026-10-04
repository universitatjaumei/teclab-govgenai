/**
 * Adónde se vuelve después de entrar (#176).
 *
 * `PrivateRoute` manda a `/login?from=…`, y el formulario de contraseña vuelve a `from`. El
 * inicio de sesión con Google o SAML pasa por el servidor y llega a `/auth/callback`, que no sabe
 * de dónde se venía: se apunta aquí antes de salir. Lo destapó la extensión del navegador, que
 * abre `/extension/conectar?destino=…` y, sin esto, quien no tenía sesión acababa en su primer
 * módulo con la ventana de la extensión esperando.
 */

const CLAVE = 'govgenai.vuelta'

/** Sólo rutas de la propia aplicación: `/algo`, nunca `//otro.sitio` ni una dirección completa. */
export function rutaSegura(ruta: string | null | undefined): string {
  if (!ruta || !ruta.startsWith('/') || ruta.startsWith('//') || ruta.startsWith('/\\')) return '/'
  return ruta
}

export function recordarVuelta(ruta: string | null | undefined): void {
  try {
    sessionStorage.setItem(CLAVE, rutaSegura(ruta))
  } catch {
    // Sin almacenamiento se vuelve a la raíz, que es lo que pasaba antes.
  }
}

/** La ruta apuntada, una sola vez: se borra al leerla. */
export function tomarVuelta(): string {
  try {
    const ruta = sessionStorage.getItem(CLAVE)
    sessionStorage.removeItem(CLAVE)
    return rutaSegura(ruta)
  } catch {
    return '/'
  }
}
