import { describe, it, expect } from 'vitest'
import i18n from '@/shared/i18n'

/**
 * Revisión de la PR #227 — la ayuda de la hoja del índice nombra las columnas **tal y como las
 * reconoce el servidor**, en cualquier lengua de la pantalla. Traducirlas hacía que quien seguía la
 * ayuda en valenciano o en inglés pusiera `títol`, `resum` o `priority`, columnas que el servidor no
 * conoce: la hoja se rechazaba o la prioridad no se aplicaba nunca.
 */
describe('la ayuda de la hoja del índice', () => {
  it.each(['es', 'ca', 'en'])('en %s nombra las columnas con su nombre literal', (lengua) => {
    const ayuda = i18n.getFixedT(lengua, 'agentes')('pistas.hoja_del_indice')
    for (const columna of ['url', 'titulo', 'resumen', 'vigente', 'revision_prevista_en', 'prioritario']) {
      expect(ayuda).toContain(columna)
    }
  })
})
