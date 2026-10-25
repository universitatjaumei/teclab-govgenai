import { useGetMeApiV1AuthMeGet } from '@/shared/api/generated/auth/auth'
import type { UsuarioActualCapacidadesItem } from '@/shared/api/generated/model'

/**
 * Si esta sesión puede hacer algo, según el servidor (#277).
 *
 * Cinco pantallas lo deducían del rol leído del JWT —`user?.role === 'superadmin'`—, que es
 * justo lo que la regla de AGENTS.md prohíbe: el frontend no calcula permisos. El servidor manda
 * en `/auth/me` las capacidades, calculadas con la misma comprobación que hace cada endpoint, y
 * aquí sólo se pregunta si está la que se pide.
 *
 * `cargando` importa por lo mismo que en `useModulos`: mientras no se sabe, una pantalla que
 * niega el acceso no puede decidir, y tratar «no lo sé» como «no» echaría a la gente de su propia
 * pantalla en cada recarga. Mientras carga, `tiene` es `false`, que no enseña lo que puede no estar.
 */
export function useCapacidad(capacidad: UsuarioActualCapacidadesItem): {
  tiene: boolean
  cargando: boolean
} {
  const { data, isLoading } = useGetMeApiV1AuthMeGet()
  return { tiene: data?.capacidades.includes(capacidad) ?? false, cargando: isLoading }
}
