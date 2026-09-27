import { useCallback, useEffect, useMemo, useState } from 'react'
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

  const [elegida, setElegida] = useState<string>(() => {
    try {
      return localStorage.getItem(CLAVE_GUARDADA) ?? ''
    } catch {
      // Un navegador con el almacenamiento bloqueado no es motivo para no funcionar.
      return ''
    }
  })

  const elegir = useCallback((id: string) => {
    setElegida(id)
    try {
      localStorage.setItem(CLAVE_GUARDADA, id)
    } catch {
      /* sin persistencia, pero con elección */
    }
  }, [])

  // **La corrección se queda en un efecto, y NO es por no haberlo intentado.** Derivarla
  // —devolver la primera cuando la guardada ya no existe— quita un render y evita escribir en
  // `localStorage` una elección que nadie hizo. Pero rompe
  // `should_ask_for_nothing_in_particular_when_none_is_chosen`, y al mirar por qué aparece una
  // contradicción que no es de este código: ese test dice que sin elección se pide la marca de
  // PLATAFORMA, y con el efecto eso sólo es cierto durante un render — inmediatamente después
  // el efecto elige la primera organización y la marca pasa a ser la suya. El test pasaba por
  // ese instante, no por el comportamiento estable.
  //
  // Qué debe ver quien no ha elegido —la marca de la plataforma o la de la primera
  // organización— es una decisión de producto, no una de refactor. Hasta que se tome, se
  // conserva el comportamiento actual.
  useEffect(() => {
    if (organizaciones.length === 0) return
    const sigueExistiendo = organizaciones.some((o) => o.id === elegida)
    if (!sigueExistiendo) elegir(organizaciones[0].id)
  }, [organizaciones, elegida, elegir])

  return {
    organizaciones,
    elegida: organizaciones.some((o) => o.id === elegida) ? elegida : '',
    elegir,
    hayVarias: organizaciones.length > 1,
  }
}
