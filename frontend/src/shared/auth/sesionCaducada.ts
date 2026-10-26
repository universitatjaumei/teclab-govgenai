import { TOKEN_KEY } from './authState'

/**
 * El aviso de que el servidor ya no acepta la sesión (#278).
 *
 * `authState` sólo mira la caducidad del token al cargar la página, y no había nada que mirara
 * las respuestas: tras caducar, la SPA seguía «conectada» y cada pantalla fallaba con un 401 hasta
 * recargar. El interceptor del cliente lo emite y el `AuthProvider` cierra la sesión, que lleva al
 * login. Va por un evento porque el cliente vive fuera de React.
 */
export const SESION_CADUCADA = 'govgenai:sesion-caducada'

/**
 * Las rutas cuyo 401 significa «esas credenciales no valen» y no «la sesión caducó»: el login
 * mismo y el cambio de contraseña con la actual equivocada. Cerrar la sesión ahí echaría a quien
 * sólo se ha equivocado al teclear. Por segmento entero: `/hub/login-history` no es un login.
 */
function suFalloEsDeCredenciales(url: string): boolean {
  const ruta = url.split('?')[0]
  return /\/login(\/|$)/.test(ruta) || ruta.endsWith('/auth/me/password')
}

/**
 * Avisa si el 401 es de la sesión **vigente**. Una petición que salió con el token anterior —la
 * persona volvió a entrar mientras estaba en vuelo— no tiene que cerrar la sesión nueva.
 */
export function avisaDeSesionCaducada(url: string | undefined, autorizacion: unknown): boolean {
  if (typeof autorizacion !== 'string' || !autorizacion) return false
  if (autorizacion !== `Bearer ${localStorage.getItem(TOKEN_KEY)}`) return false
  if (url && suFalloEsDeCredenciales(url)) return false
  window.dispatchEvent(new Event(SESION_CADUCADA))
  return true
}
