/**
 * El motivo de un fallo, tal como lo dice el servidor.
 *
 * El interceptor del cliente ya pasa a `message` un `detail` de texto, pero aquí llegan otras dos
 * formas que no cubre: el `detail` objeto —`{code, message}`, el del 403 de quien no tiene una sola
 * organización— y el de las descargas, que viene en `response.data` una vez `descargarConAutorizacion`
 * ha reconstruido el JSON del Blob.
 */
export function mensajeDelFallo(fallo: unknown, porDefecto: string): string {
  const detalle = (fallo as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  if (typeof detalle === 'string' && detalle) return detalle
  if (detalle && typeof detalle === 'object' && 'message' in detalle) {
    const mensaje = (detalle as { message?: unknown }).message
    if (typeof mensaje === 'string' && mensaje) return mensaje
  }
  const mensaje = (fallo as Error)?.message
  // El genérico de axios no dice nada que la pantalla no diga mejor.
  if (mensaje && !mensaje.startsWith('Request failed with status code')) return mensaje
  return porDefecto
}
