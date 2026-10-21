import type { TFunction } from 'i18next'

/** Los `detail.code` de la subida que tienen texto propio; los demás dicen su `message`. */
const TEXTO_DEL_CODIGO: Record<string, string> = {
  CORPUS_CONTRACT_VIOLATION: 'hub.upload_rechazo.CORPUS_CONTRACT_VIOLATION',
  CORPUS_ACCEPTS_MARKDOWN_ONLY: 'hub.upload_rechazo.CORPUS_ACCEPTS_MARKDOWN_ONLY',
}

/**
 * Por qué el servidor rechazó una subida, en vez del «Request failed with status code 422»
 * de la petición. El servidor manda `detail.code`, que se traduce si hay texto para él (si no,
 * vale su `message`), y en el contrato también `detail.problemas`, los campos que fallan:
 * quien prepara el documento necesita la lista para corregirlo de una pasada.
 */
export function motivoDelRechazo(fallo: Error, t: TFunction<'admin'>): string {
  const detalle = (fallo as { response?: { data?: { detail?: unknown } } }).response?.data?.detail
  if (typeof detalle === 'string') return detalle
  if (!detalle || typeof detalle !== 'object') return fallo.message
  const { code, message, problemas } = detalle as {
    code?: string
    message?: string
    problemas?: { campo: string; problema: string }[]
  }
  const clave = code ? TEXTO_DEL_CODIGO[code] : undefined
  const motivo = clave ? t(clave) : (message ?? fallo.message)
  const campos = (problemas ?? []).map(p => `${p.campo}: ${p.problema}`).join('; ')
  return campos ? `${motivo} ${campos}` : motivo
}
