/**
 * Por dónde se entra en el módulo de Informes (#243).
 *
 * Era «Plantillas», que es de administración: a quien sólo redacta informes el módulo lo
 * recibía con «esta pantalla es sólo para administradores». «Nuevo informe» lo puede usar
 * cualquiera que tenga el módulo. Módulo aparte para que `App.tsx` lo importe sin arrastrar
 * el layout, que se carga perezoso.
 */
export const ENTRADA_DE_INFORMES = '/redaccion/wizard'
