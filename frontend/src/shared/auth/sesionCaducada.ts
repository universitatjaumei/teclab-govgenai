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
 * sólo se ha equivocado al teclear.
 */
const SU_401_ES_DE_CREDENCIALES = ['/login', '/auth/me/password']

export function avisaDeSesionCaducada(url: string | undefined, conToken: boolean): boolean {
  if (!conToken) return false
  if (url && SU_401_ES_DE_CREDENCIALES.some((ruta) => url.includes(ruta))) return false
  window.dispatchEvent(new Event(SESION_CADUCADA))
  return true
}
