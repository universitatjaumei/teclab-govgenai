/**
 * Si una cadena que viene de un dato es una dirección a la que se puede ir.
 *
 * Sólo `http` y `https`. Un `href` construido con un dato —la URL de un documento del corpus, la
 * de una página rastreada, la de una fuente del asistente— puede traer `javascript:` o `data:`, y
 * un enlace así se ejecuta al pulsarlo: en el panel, desde nuestro propio origen; en el widget,
 * en la web de quien lo embebe. Tampoco pasa lo que no es una URL: para los documentos cargados
 * desde carpeta, `canonical_url` es el nombre del fichero o la clave de almacenamiento.
 *
 * Nació en la cola de vigencia (REV.5) y se movió aquí el 2026-10-22, cuando se vio que diez
 * pantallas y el widget pintaban el dato tal cual.
 */
export function esEnlaceExterno(url: string | null | undefined): url is string {
  return typeof url === 'string' && /^https?:\/\//i.test(url)
}

/** El `href` que se puede pintar, o `undefined` si el dato no es un enlace seguro. */
export function enlaceExterno(url: string | null | undefined): string | undefined {
  return esEnlaceExterno(url) ? url : undefined
}
