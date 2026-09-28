import { useListChatbotsApiV1HubChatbotsGet } from '@/shared/api/generated/hub-chatbots/hub-chatbots'
import { useOrganizacionElegida } from './useOrganizacionElegida'

/**
 * La lista de chatbots del panel, acotada a la organización elegida en la cabecera (issue #11).
 *
 * **Por qué existe este envoltorio en vez de repetir el parámetro en cada pantalla.** Nueve
 * pantallas listan chatbots —unas para gestionarlos y la mayoría para elegir uno y pedir después
 * sus documentos, sus escenarios o sus interacciones—, y ninguna pasaba la organización elegida.
 * Repetir la misma línea nueve veces garantiza que la décima se olvide; aquí el acotado vive en
 * un sitio y se hereda.
 *
 * **Sin organización no se manda filtro, y no es lo mismo que mandarlo vacío.** `elegida` sale de
 * una petición, así que entre el primer render y su respuesta vale `''`. Pedir
 * `organizacion_id: ''` sería preguntar por una organización que no existe; sin parámetro, el
 * servidor devuelve lo que la tenencia permita, que es exactamente el comportamiento anterior.
 *
 * **El acotado de verdad lo hace el servidor.** Este hook sólo dice de qué organización se está
 * hablando: el endpoint aplica primero `scope_query_to_orgs` —la frontera, que no se negocia— y
 * después el filtro, y responde 403 si se le pide una organización ajena. Filtrar en el cliente
 * habría traído a la pantalla datos que no se van a enseñar, que es la otra forma de hacerlo y
 * la que este proyecto no usa desde SEC.8.1.
 */
export function useChatbotsDeLaOrganizacion() {
  const { elegida } = useOrganizacionElegida()

  // **Y no se pregunta hasta saber de qué organización** (revisión de la PR #187). Mientras
  // `useOrganizacionElegida` carga la lista, `elegida` vale `''`, y una consulta sin filtro que
  // llegara antes que esa lista permitiría a una pantalla autoseleccionar un chatbot de otra
  // organización y seguir cargando sus datos después de aplicarse el filtro. Sin organización no
  // hay pregunta que hacer.
  return useListChatbotsApiV1HubChatbotsGet(
    elegida ? { organizacion_id: elegida } : undefined,
    { query: { enabled: Boolean(elegida) } },
  )
}
