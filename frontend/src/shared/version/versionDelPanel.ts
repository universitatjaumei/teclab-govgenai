/**
 * #248 — qué versión del panel se está ejecutando y cuál se sirve.
 *
 * La versión es el script principal del `index.html`: Vite lo nombra con el hash de su contenido,
 * así que cambia en cada despliegue que cambie el panel y en ninguno más. No depende de que nadie
 * suba el número de `VERSION`, que va por su cuenta y no se toca en cada despliegue.
 */

const SCRIPT_PRINCIPAL = /<script\b[^>]*\btype="module"[^>]*\bsrc="([^"]+)"/

export function scriptPrincipal(html: string): string | null {
  return SCRIPT_PRINCIPAL.exec(html)?.[1] ?? null
}

/** El de esta pestaña, tal como lo escribió el `index.html` que la cargó. */
export function scriptEnEjecucion(): string | null {
  return document.querySelector('script[type="module"][src]')?.getAttribute('src') ?? null
}

/**
 * El que se sirve ahora. `null` si no se puede saber: un fallo de red no es una versión nueva, y
 * avisar por él sería pedir que recarguen justo cuando recargar no va a funcionar.
 */
export async function scriptServido(): Promise<string | null> {
  try {
    const respuesta = await fetch(import.meta.env.BASE_URL, { cache: 'no-store' })
    if (!respuesta.ok) return null
    return scriptPrincipal(await respuesta.text())
  } catch {
    return null
  }
}
