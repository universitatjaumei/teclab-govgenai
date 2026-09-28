import { describe, it, expect, beforeEach, vi } from 'vitest'
import { renderHook, act } from '@testing-library/react'

import {
  CLAVE_GUARDADA,
  useOrganizacionElegida,
} from '../useOrganizacionElegida'
import { useListOrganizacionesApiV1HubOrganizacionesGet } from '@/shared/api/generated/hub-organizaciones/hub-organizaciones'

/**
 * REV.10 — de qué organización se está hablando en el panel.
 *
 * Antes no existía y cada pantalla lo resolvía a su manera: «Valores por defecto» con su propio
 * selector, «Identidad visual» con otro, Vigencia por *chatbot*, y Personas sin ninguno. Cambiar
 * de organización obligaba a repetir la elección pantalla por pantalla.
 */
vi.mock('@/shared/api/generated/hub-organizaciones/hub-organizaciones', () => ({
  useListOrganizacionesApiV1HubOrganizacionesGet: vi.fn(),
}))

const UJI = { id: 'org-uji', name: 'Universitat Jaume I' }
const DIPU = { id: 'org-dipu', name: 'Diputación de Castellón' }

function conOrganizaciones(lista: { id: string; name: string }[]) {
  vi.mocked(useListOrganizacionesApiV1HubOrganizacionesGet).mockReturnValue({
    data: lista,
  } as never)
}

beforeEach(() => {
  localStorage.clear()
  vi.clearAllMocks()
})

describe('REV.10 — la organización elegida', () => {
  it('should_fall_back_to_the_first_one_when_nothing_was_chosen', () => {
    conOrganizaciones([UJI, DIPU])

    const { result } = renderHook(() => useOrganizacionElegida())

    expect(result.current.elegida).toBe('org-uji')
  })

  it('should_remember_the_choice_across_reloads', () => {
    // Es una preferencia de quien usa el panel: perderla en cada recarga convierte el selector
    // en un estorbo en vez de un atajo.
    conOrganizaciones([UJI, DIPU])
    const primero = renderHook(() => useOrganizacionElegida())
    act(() => primero.result.current.elegir('org-dipu'))

    const segundo = renderHook(() => useOrganizacionElegida())

    expect(segundo.result.current.elegida).toBe('org-dipu')
    expect(localStorage.getItem(CLAVE_GUARDADA)).toBe('org-dipu')
  })

  it('should_not_get_stuck_on_an_organisation_that_no_longer_exists', () => {
    // **El test del prompt.** Una organización borrada, o alguien que ha cambiado de permisos,
    // dejaría el panel apuntando a un id fantasma: todas las pantallas pedirían datos de algo
    // que no está y no habría forma de salir de ahí desde la interfaz.
    localStorage.setItem(CLAVE_GUARDADA, 'org-que-ya-no-esta')
    conOrganizaciones([UJI])

    const { result } = renderHook(() => useOrganizacionElegida())

    expect(result.current.elegida).toBe('org-uji')
  })

  it('should_say_there_is_nothing_to_choose_with_a_single_organisation', () => {
    // Con una sola, un selector es ruido. Es el mismo criterio que el buscador de REV.7.
    conOrganizaciones([UJI])

    const { result } = renderHook(() => useOrganizacionElegida())

    expect(result.current.hayVarias).toBe(false)
  })

  it('should_offer_the_choice_with_more_than_one', () => {
    conOrganizaciones([UJI, DIPU])

    const { result } = renderHook(() => useOrganizacionElegida())

    expect(result.current.hayVarias).toBe(true)
  })

  it('should_report_no_choice_while_the_list_is_empty', () => {
    // Sin lista todavía, devolver un id inventado haría que las pantallas pidieran datos de
    // una organización que no se sabe si existe.
    conOrganizaciones([])

    const { result } = renderHook(() => useOrganizacionElegida())

    expect(result.current.elegida).toBe('')
  })

  it('should_survive_a_browser_with_storage_blocked', () => {
    conOrganizaciones([UJI, DIPU])
    const original = Storage.prototype.setItem
    Storage.prototype.setItem = () => {
      throw new Error('almacenamiento bloqueado')
    }
    try {
      const { result } = renderHook(() => useOrganizacionElegida())
      act(() => result.current.elegir('org-dipu'))
      expect(result.current.elegida).toBe('org-dipu')
    } finally {
      Storage.prototype.setItem = original
    }
  })
})

describe('la elección es una sola para todo el panel', () => {
  /**
   * **Issue #11, y lo encontró el navegador.** El hook guardaba la elección en un `useState`
   * propio, así que **cada llamada tenía la suya**: la cabecera cambiaba la suya y la escribía en
   * `localStorage`, y el consumidor de otra parte del árbol seguía con la anterior hasta que se
   * volviera a montar. En el panel se veía exactamente así — el selector cambiaba, el
   * almacenamiento cambiaba, y **no salía ninguna petición nueva**.
   *
   * Los tests no podían verlo: el de `useChatbotsDeLaOrganizacion` dobla este hook, y los de
   * aquí montaban un consumidor solo. Hace falta montar **dos** y elegir en uno.
   */
  it('should_propagar_la_eleccion_a_los_demas_consumidores', () => {
    conOrganizaciones([UJI, DIPU])
    const cabecera = renderHook(() => useOrganizacionElegida())
    const pantalla = renderHook(() => useOrganizacionElegida())

    act(() => cabecera.result.current.elegir(DIPU.id))

    expect(cabecera.result.current.elegida).toBe(DIPU.id)
    expect(pantalla.result.current.elegida).toBe(DIPU.id)
  })

  it('should_seguir_recordandola_entre_sesiones', () => {
    /** El camino bueno de siempre: compartirla no puede costar la persistencia. */
    conOrganizaciones([UJI, DIPU])
    const { result } = renderHook(() => useOrganizacionElegida())

    act(() => result.current.elegir(DIPU.id))

    expect(localStorage.getItem(CLAVE_GUARDADA)).toBe(DIPU.id)
  })
})
