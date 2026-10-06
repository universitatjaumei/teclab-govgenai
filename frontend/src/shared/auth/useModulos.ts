import { useGetMeApiV1AuthMeGet } from '@/shared/api/generated/auth/auth'

/**
 * Los módulos que el servidor concede a quien está dentro (INF.7).
 *
 * **El frontend no decide.** Antes no había nada que decidir: `App.tsx` metía todas las rutas
 * bajo un `PrivateRoute` que solo comprobaba que hubiera sesión, no existía un solo `role ===`
 * en la capa de navegación, y el aterrizaje era `/hub/chatbots` fijo. Con el módulo de informes
 * abierto a toda la organización, eso significaba que cualquier trabajador con cuenta veía
 * —y podía editar— los chatbots institucionales.
 *
 * Ahora la lista viene de `/auth/me` y el menú y las rutas se generan iterándola. Es el mismo
 * patrón que `acciones_permitidas` en los bloques: el servidor calcula, el cliente pinta.
 *
 * `cargando` importa: mientras no se sabe qué hay concedido no se puede decidir si una ruta
 * está prohibida, y tratar «no lo sé» como «no» echaría a la gente de su propia pantalla en
 * cada recarga.
 */
export function useModulos(): { modulos: string[]; cargando: boolean } {
  const { data, isLoading } = useGetMeApiV1AuthMeGet()
  const modulos = (data as { modulos?: unknown } | undefined)?.modulos
  return {
    modulos: Array.isArray(modulos) ? modulos.map(String) : [],
    cargando: isLoading,
  }
}

/** La primera ruta a la que puede ir esta persona, para el aterrizaje. */
export function primeraRutaConcedida(modulos: string[]): string {
  for (const [codigo, ruta] of RUTA_DEL_MODULO) {
    if (modulos.includes(codigo)) return ruta
  }
  // Sin ningún módulo no hay a dónde ir: la pantalla lo dice en vez de rebotar en bucle.
  return '/sin-acceso'
}

/** Qué módulo abre cada zona de la aplicación. El orden es el del aterrizaje.
 *
 * `plataforma` va **última** (PLAT.2): quien tenga informes y plataforma entra a trabajar, no a
 * configurar. Pero tiene que estar, porque sin ella quien solo administra la plataforma
 * aterrizaba en `/sin-acceso` teniendo acceso.
 */
export const RUTA_DEL_MODULO: ReadonlyArray<readonly [string, string]> = [
  ['informes', '/redaccion'],
  // 2026-10-05 — el catálogo de funciones; sin esta fila, quien sólo lo tuviera aterrizaría en
  // `/sin-acceso` teniendo acceso.
  ['automatizacion', '/automatizacion'],
  ['chatbots', '/hub'],
  ['curacion', '/curation'],
  // UTL — trabajo y no administración, así que va con los de trabajo. Sin esta fila, quien sólo
  // tuviera utilidades aterrizaría en `/sin-acceso` teniendo acceso.
  ['utilidades', '/utilidades'],
  // #172 — sin esta fila, quien sólo tuviera `agentes` aterrizaría en `/sin-acceso`.
  ['consulta_agentes', '/agentes/consultar'],
  ['agentes', '/agentes/gestion'],
  // USR.9 — antes de `plataforma` y después del trabajo: administrar a las personas de tu
  // organización es administración, pero es la única que tiene quien no administra la
  // plataforma, y sin esta fila aterrizaría en `/sin-acceso` teniendo acceso.
  ['personas', '/personas'],
  ['plataforma', '/plataforma'],
]

/** El módulo que protege una ruta, si la protege alguno. */
export function moduloDeLaRuta(pathname: string): string | null {
  for (const [codigo, ruta] of RUTA_DEL_MODULO) {
    if (pathname === ruta || pathname.startsWith(`${ruta}/`)) return codigo
  }
  return null
}
