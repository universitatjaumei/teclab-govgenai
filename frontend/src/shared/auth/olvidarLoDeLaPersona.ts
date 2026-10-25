import { olvidarTodosLosBorradores } from '@/redaccion/utils/borradorLocal'
import { useFocusStore } from '@/shared/layout/useFocusStore'
import { olvidarLaEleccion } from '@/shared/organizacion/useOrganizacionElegida'
import { CLAVE_DEL_TEMA } from '@/themes/types'

/**
 * Lo que una persona deja en el navegador, fuera al cambiar de sesión (#278).
 *
 * El cierre de sesión sólo quitaba el token. Quedaban los borradores de edición de informes, el
 * tema, la organización elegida y el estado del modo foco: en un equipo compartido —un aula, la
 * biblioteca— quien entraba después recuperaba el borrador de quien había salido.
 */
export function olvidarLoDeLaPersona(): void {
  olvidarTodosLosBorradores()
  olvidarLaEleccion()
  useFocusStore.getState().reset()
  try {
    localStorage.removeItem(CLAVE_DEL_TEMA)
  } catch {
    /* sin almacenamiento no había tema guardado */
  }
}
