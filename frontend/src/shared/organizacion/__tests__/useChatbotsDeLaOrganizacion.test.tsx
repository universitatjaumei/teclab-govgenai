import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook } from '@testing-library/react'
import { useListChatbotsApiV1HubChatbotsGet } from '@/shared/api/generated/hub-chatbots/hub-chatbots'
import { useOrganizacionElegida } from '../useOrganizacionElegida'
import { useChatbotsDeLaOrganizacion } from '../useChatbotsDeLaOrganizacion'

/**
 * Issue #11 (MT.8) — la organización elegida acota los listados.
 *
 * **Lo que falta, y lo que no.** La frontera de datos está hecha: el servidor decide qué puede
 * ver cada principal. Esto es la capa de encima — que la elección que se hace **una vez** en la
 * cabecera (REV.10) llegue a las pantallas.
 *
 * **Medido el 2026-09-28**: de las pantallas que listan datos de organización acotaba una sola,
 * `SitesPage` de curación. Y casi ninguna de las demás lista «lo suyo»: listan **chatbots** para
 * elegir uno y pedir después sus documentos, sus escenarios o sus interacciones. Así que un
 * superadministrador con la organización A elegida veía los chatbots de B en cada desplegable.
 *
 * Por eso el arreglo es un hook compartido y no nueve cambios repetidos: quien necesite la lista
 * de chatbots del panel llama a éste, y el acotado vive en un sitio.
 *
 * **Y lo que se comprueba aquí es qué se le pide al servidor**, no si la pantalla llama al hook
 * del selector. Un test de lo segundo pasa en verde con el parámetro puesto a `undefined`.
 */
vi.mock('@/shared/api/generated/hub-chatbots/hub-chatbots', () => ({
  useListChatbotsApiV1HubChatbotsGet: vi.fn(() => ({ data: [], isLoading: false })),
}))

vi.mock('../useOrganizacionElegida', () => ({
  useOrganizacionElegida: vi.fn(),
}))

function conOrganizacion(elegida: string, hayVarias = true) {
  vi.mocked(useOrganizacionElegida).mockReturnValue({
    organizaciones: [
      { id: 'org-a', name: 'A' },
      { id: 'org-b', name: 'B' },
    ],
    elegida,
    elegir: vi.fn(),
    hayVarias,
  })
}

function parametrosPedidos() {
  return vi.mocked(useListChatbotsApiV1HubChatbotsGet).mock.calls.at(-1)?.[0]
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('la lista de chatbots del panel va acotada a la organización elegida', () => {
  it('should_pedir_al_servidor_solo_los_de_la_organizacion_elegida', () => {
    conOrganizacion('org-a')

    renderHook(() => useChatbotsDeLaOrganizacion())

    expect(parametrosPedidos()).toEqual({ organizacion_id: 'org-a' })
  })

  it('should_seguir_a_la_organizacion_cuando_se_cambia', () => {
    /** Es el caso de uso entero: cambiar en la cabecera tiene que cambiar lo que se ve. */
    conOrganizacion('org-a')
    const { rerender } = renderHook(() => useChatbotsDeLaOrganizacion())

    conOrganizacion('org-b')
    rerender()

    expect(parametrosPedidos()).toEqual({ organizacion_id: 'org-b' })
  })

  it('should_no_pedir_filtro_mientras_no_haya_organizacion', () => {
    // Y tampoco lanzar la consulta: eso lo fija el bloque de más abajo.
    /**
     * `elegida` viene de una petición, así que entre el primer render y su respuesta vale `''`.
     * Mandar `organizacion_id: ''` sería pedir los chatbots de una organización que no existe;
     * sin parámetro, el servidor devuelve lo que la tenencia permita, que es el comportamiento
     * de siempre.
     */
    conOrganizacion('')

    renderHook(() => useChatbotsDeLaOrganizacion())

    expect(parametrosPedidos()).toBeUndefined()
  })

  it('should_devolver_lo_que_devuelve_el_hook_generado', () => {
    /** Sin esto, el envoltorio podría acotar bien y no entregar nada. */
    conOrganizacion('org-a')
    vi.mocked(useListChatbotsApiV1HubChatbotsGet).mockReturnValue({
      data: [{ id: 'c1', name: 'Uno' }],
      isLoading: false,
    } as never)

    const { result } = renderHook(() => useChatbotsDeLaOrganizacion())

    expect(result.current.data).toEqual([{ id: 'c1', name: 'Uno' }])
  })
})

describe('no se pregunta por chatbots hasta saber de qué organización', () => {
  /**
   * Lo señaló la revisión de la PR #187: mientras `useOrganizacionElegida` carga la lista de
   * organizaciones, `elegida` vale `''` y el hook lanzaba una consulta **sin filtro**. Si esa
   * respuesta llegaba antes que la lista, una pantalla podía autoseleccionar un chatbot de otra
   * organización y seguir cargando sus datos después de aplicarse el filtro.
   *
   * Sin organización no hay pregunta que hacer: la consulta se queda desactivada.
   */
  it('should_no_lanzar_la_consulta_sin_organizacion', () => {
    conOrganizacion('')

    renderHook(() => useChatbotsDeLaOrganizacion())

    const opciones = vi.mocked(useListChatbotsApiV1HubChatbotsGet).mock.calls.at(-1)?.[1]
    expect(opciones?.query?.enabled).toBe(false)
  })

  it('should_lanzarla_en_cuanto_hay_organizacion', () => {
    conOrganizacion('org-a')

    renderHook(() => useChatbotsDeLaOrganizacion())

    const opciones = vi.mocked(useListChatbotsApiV1HubChatbotsGet).mock.calls.at(-1)?.[1]
    expect(opciones?.query?.enabled).toBe(true)
  })
})

describe('una selección que ya no está en la lista no se queda puesta', () => {
  /**
   * El hallazgo más serio de la revisión de la PR #187, y el que mi verificación en el navegador
   * no vio porque **no llegué a elegir un chatbot antes de cambiar de organización**.
   *
   * Las pantallas guardan el chatbot elegido en su propio estado y sólo lo fijan si está vacío.
   * Al cambiar de organización, el desplegable pasa a enseñar los de la nueva y el estado sigue
   * apuntando al de la anterior: la consulta dependiente y las mutaciones seguían yendo contra
   * un chatbot de otra organización. Enseñar B y trabajar sobre A es peor que no acotar.
   */
  it('should_olvidar_la_seleccion_cuando_desaparece_de_la_lista', async () => {
    const { useSeleccionValida } = await import('../useSeleccionValida')
    const fijar = vi.fn()

    renderHook(() =>
      useSeleccionValida([{ id: 'c-de-b' }], 'c-de-a', fijar),
    )

    expect(fijar).toHaveBeenCalledWith('')
  })

  it('should_dejarla_en_paz_cuando_sigue_estando', async () => {
    const { useSeleccionValida } = await import('../useSeleccionValida')
    const fijar = vi.fn()

    renderHook(() => useSeleccionValida([{ id: 'c-de-a' }], 'c-de-a', fijar))

    expect(fijar).not.toHaveBeenCalled()
  })

  it('should_no_tocar_nada_mientras_la_lista_esta_vacia', async () => {
    /** Una lista vacía es «todavía no ha llegado», no «ese chatbot ya no existe». */
    const { useSeleccionValida } = await import('../useSeleccionValida')
    const fijar = vi.fn()

    renderHook(() => useSeleccionValida([], 'c-de-a', fijar))

    expect(fijar).not.toHaveBeenCalled()
  })
})
