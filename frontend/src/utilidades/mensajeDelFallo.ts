import { errorDeLaApi } from '@/shared/api/errorDeLaApi'

/**
 * El motivo de un fallo, tal como lo dice el servidor.
 *
 * El interceptor del cliente ya lo pasa a `message`, pero las descargas no pasan por él: su error
 * viene en `response.data` una vez `descargarConAutorizacion` ha reconstruido el JSON del Blob.
 */
export function mensajeDelFallo(fallo: unknown, porDefecto: string): string {
  const delServidor = errorDeLaApi(fallo)?.message
  if (delServidor) return delServidor
  const mensaje = (fallo as Error)?.message
  // El genérico de axios no dice nada que la pantalla no diga mejor.
  if (mensaje && !mensaje.startsWith('Request failed with status code')) return mensaje
  return porDefecto
}
