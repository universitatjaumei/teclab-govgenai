import { useMemo } from 'react'
import { create } from 'zustand'
import { useListOrganizacionesApiV1HubOrganizacionesGet } from '@/shared/api/generated/hub-organizaciones/hub-organizaciones'

/** Dónde se recuerda la elección. Por navegador y por persona que usa ese navegador. */
export const CLAVE_GUARDADA = 'organizacion-elegida'

export interface OrganizacionBreve {
  id: string
  name: string
}

export interface EleccionDeOrganizacion {
  organizaciones: OrganizacionBreve[]
  /** El id elegido, o `''` mientras no hay ninguna organización cargada. */
  elegida: string
  elegir: (id: string) => void
  /** Si merece la pena ofrecer el selector: con una sola organización es ruido. */
  hayVarias: boolean
}

/**
 * De qué organización se está hablando en el panel (REV.10).
 *
 * Antes esto no existía y **cada pantalla lo resolvía a su manera**: «Valores por defecto» tenía
 * su propio selector, «Identidad visual» otro, Vigencia elegía por *chatbot*, y Personas y
 * Prompts de actividad no tenían ninguno —una porque le faltaba, la otra porque no le hace
 * falta—. El resultado es que cambiar de organización obligaba a repetir la elección en cada
 * pantalla, y no había forma de saber si una pantalla sin selector era de plataforma o estaba
 * incompleta.
 *
 * **La elección se recuerda** en `localStorage`: es una preferencia de quien usa el panel, no un
 * dato del servidor, y perderla en cada recarga convierte el selector en un estorbo. Si la
 * guardada ya no existe —organización borrada, o alguien que ha cambiado de permisos— se cae a la
 * primera disponible en vez de quedarse en un id fantasma que no resuelve nada.
 *
 * Se lee con el hook que ya existía para listar organizaciones, así que no añade una petición:
 * react-query devuelve la consulta cacheada.
 */
function _leerGuardada(): string {
  try {
    return localStorage.getItem(CLAVE_GUARDADA) ?? ''
  } catch {
    // Un navegador con el almacenamiento bloqueado no es motivo para no funcionar.
    return ''
  }
}

/**
 * La elección, **compartida por todo el panel** (issue #11).
 *
 * Estaba en un `useState` dentro del hook, así que **cada llamada tenía la suya**: la cabecera
 * cambiaba la suya y la escribía en `localStorage`, y el consumidor de otra parte del árbol
 * seguía con la anterior hasta volver a montarse. En el panel se veía exactamente así — el
 * selector cambiaba, el almacenamiento cambiaba, y no salía ninguna petición nueva. Lo encontró
 * la verificación en el navegador; los tests no podían, porque montaban un consumidor solo.
 *
 * `zustand` y no un contexto porque ya es el patrón del proyecto (`useFocusStore`) y no obliga a
 * envolver el árbol en un proveedor más.
 */
const _usarEleccion = create<{ elegida: string; elegir: (id: string) => void }>((set) => ({
  // Arranca **vacía**, no con lo guardado, y el hook cae a `localStorage` mientras siga así.
  //
  // Es la diferencia entre «nadie ha elegido en esta sesión» y «no hay elección guardada». Leer
  // aquí ataría el valor al instante en que se **importa el módulo**, y entonces cualquier
  // escritura posterior —otra pestaña, o un test que prepara el estado antes de pintar— quedaría
  // invisible para siempre. Así la tienda manda en cuanto alguien elige, y hasta entonces manda
  // lo guardado, que es el comportamiento de siempre.
  elegida: '',
  elegir: (id: string) => {
    set({ elegida: id })
    try {
      localStorage.setItem(CLAVE_GUARDADA, id)
    } catch {
      /* sin persistencia, pero con elección */
    }
  },
}))

export function useOrganizacionElegida(): EleccionDeOrganizacion {
  const { data } = useListOrganizacionesApiV1HubOrganizacionesGet()

  // **Memoizado, y no es optimización prematura.** Sin esto, el `.map()` construía un array
  // nuevo en CADA render, así que las dependencias del efecto de abajo cambiaban siempre y el
  // efecto corría en todos ellos — y lo mismo le pasaba a cualquier consumidor que metiera
  // `organizaciones` en sus propias dependencias, que es un hook compartido multiplicando el
  // problema por sus llamadores.
  const organizaciones: OrganizacionBreve[] = useMemo(
    () =>
      ((data ?? []) as { id: string; name: string }[]).map((o) => ({
        id: String(o.id),
        name: o.name,
      })),
    [data],
  )

  const elegidaEnSesion = _usarEleccion((s) => s.elegida)
  const elegir = _usarEleccion((s) => s.elegir)
  const elegida = elegidaEnSesion || _leerGuardada()

  // **Cuál rige ahora mismo: la guardada si sigue existiendo y, si no, la primera.** Se
  // DERIVA; no se guarda.
  //
  // Antes era un efecto que llamaba a `elegir(organizaciones[0].id)`, y tenía dos costes. Uno,
  // un render de más: se pintaba un fotograma con la organización que ya no existe —o con
  // ninguna— antes de corregirlo. Y dos, escribía en `localStorage` una elección **que nadie
  // había hecho**, así que a quien perdía el acceso a una organización se le grababa su
  // sustituta como si la hubiera elegido.
  //
  // **Decisión de producto (2026-09-27)**: sin elección previa se aterriza en la primera
  // organización, cambiable desde el desplegable de la cabecera. Una pantalla de selección se
  // justificaría si elegir mal tuviera consecuencia, y aquí sólo afecta a qué se ve y con qué
  // marca, se cambia en un clic, y la mayoría pertenece a una sola organización — para esas
  // personas sería una pulsación de más en cada sesión a cambio de nada.
  //
  // Con cero organizaciones se devuelve `''`, que los consumidores traducen a «la marca de la
  // plataforma» (`elegida || undefined`). `elegir` sigue persistiendo cuando la elección es de
  // una persona, que es cuando tiene sentido recordarla.
  const efectiva = organizaciones.some((o) => o.id === elegida)
    ? elegida
    : (organizaciones[0]?.id ?? '')

  return {
    organizaciones,
    elegida: efectiva,
    elegir,
    hayVarias: organizaciones.length > 1,
  }
}
