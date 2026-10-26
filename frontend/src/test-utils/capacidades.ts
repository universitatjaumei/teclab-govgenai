import type { UsuarioActualCapacidadesItem } from '@/shared/api/generated/model'

/**
 * Lo que el servidor concede a cada rol en `/auth/me` (`server/app/core/auth/capacidades.py`),
 * para simularlo en los tests de las pantallas que antes decidían con el rol (#277).
 *
 * Vive en los tests y no en la aplicación a propósito: la pantalla no deduce nada del rol, lo
 * pregunta. Aquí sólo se fabrica la respuesta que daría el servidor.
 */
export function capacidadesDelRol(rol: string | undefined): UsuarioActualCapacidadesItem[] {
  if (rol === 'superadmin') {
    return ['plantillas.publicar', 'scripts.revisar', 'identidad.plataforma', 'agentes.integrar_asistentes']
  }
  if (rol === 'admin') return ['plantillas.publicar', 'scripts.revisar']
  return []
}

/** El doble de `useCapacidad`, con las capacidades del rol que devuelva `rolActual` al llamarlo. */
export function dobleDeUseCapacidad(rolActual: () => string | undefined) {
  return {
    useCapacidad: (capacidad: UsuarioActualCapacidadesItem) => ({
      tiene: capacidadesDelRol(rolActual()).includes(capacidad),
      cargando: false,
    }),
  }
}
