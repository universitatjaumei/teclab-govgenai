import type { ErrorDeLaApi } from './generated/model'

/**
 * El error de la API en su formato único, `{code, message, …}` (#276), o `null` si el fallo no
 * trae uno: un fallo de red, o la validación de entrada de FastAPI, que es una lista.
 *
 * Antes cada pantalla sacaba el motivo a su manera, porque el servidor mandaba unas veces texto
 * y otras un objeto con `message`, `reason` o ninguno de los dos. El tipo sale del contrato.
 */
export function errorDeLaApi(fallo: unknown): ErrorDeLaApi | null {
  const detalle = (fallo as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  if (!detalle || typeof detalle !== 'object' || Array.isArray(detalle)) return null
  const { code, message } = detalle as Partial<ErrorDeLaApi>
  return typeof code === 'string' && typeof message === 'string' ? (detalle as ErrorDeLaApi) : null
}
