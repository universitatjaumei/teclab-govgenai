/**
 * La ruta de una operación que se anota en el registro de una organización, con la elegida en el
 * panel si la hay (2026-10-03).
 *
 * Quien pertenece a una sola no tiene elegida —no puede listar organizaciones— y la ruta va tal
 * cual: el servidor usa la suya. Quien no pertenece a una sola —el superadministrador— dice cuál,
 * y el servidor comprueba que pueda.
 */
export function conLaOrganizacion(ruta: string, elegida: string): string {
  if (!elegida) return ruta
  const separador = ruta.includes('?') ? '&' : '?'
  return `${ruta}${separador}organizacion_id=${encodeURIComponent(elegida)}`
}
