import type { TFunction } from 'i18next'

import { errorDeLaApi } from '@/shared/api/errorDeLaApi'

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
  const detalle = errorDeLaApi(fallo)
  if (!detalle) return fallo.message
  const { code, message } = detalle
  const problemas = detalle.problemas as { campo: string; problema: string }[] | undefined
  const clave = TEXTO_DEL_CODIGO[code]
  const motivo = clave ? t(clave) : message
  const campos = (problemas ?? []).map(p => `${p.campo}: ${p.problema}`).join('; ')
  return campos ? `${motivo} ${campos}` : motivo
}
