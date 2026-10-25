import { describe, it, expect } from 'vitest'
import i18n from '../i18n'

/**
 * #279 — el widget importaba `@/shared/i18n`, que mete en el bundle público las cadenas de todo
 * el panel: administración, curación, redacción… Sólo necesita `chat` y `common`.
 */
describe('las traducciones del widget', () => {
  it('should_carry_only_chat_and_common', () => {
    for (const lengua of ['es', 'ca', 'en']) {
      expect(Object.keys(i18n.store.data[lengua]).sort()).toEqual(['chat', 'common'])
    }
  })
})
