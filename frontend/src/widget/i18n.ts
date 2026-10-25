import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'

import esChat from '@/shared/i18n/locales/es/chat.json'
import esCommon from '@/shared/i18n/locales/es/common.json'
import caChat from '@/shared/i18n/locales/ca/chat.json'
import caCommon from '@/shared/i18n/locales/ca/common.json'
import enChat from '@/shared/i18n/locales/en/chat.json'
import enCommon from '@/shared/i18n/locales/en/common.json'

/**
 * Las traducciones del widget, y sólo las suyas (#279).
 *
 * Importaba `@/shared/i18n`, que carga de forma estática los 27 JSON del panel —administración,
 * curación, redacción…—, así que el widget público llevaba dentro todas las cadenas del panel
 * para usar dos espacios: `chat`, el suyo, y `common`, el del enlace al código fuente.
 *
 * Sin detector de idioma: la lengua la declara la página que lo embebe con `data-lang`, y
 * `mountWidget` la fija al montarlo.
 */
i18n.use(initReactI18next).init({
  resources: {
    es: { chat: esChat, common: esCommon },
    ca: { chat: caChat, common: caCommon },
    en: { chat: enChat, common: enCommon },
  },
  lng: 'es',
  fallbackLng: { 'ca-ES': ['ca', 'es'], default: ['es'] },
  supportedLngs: ['es', 'ca', 'en'],
  ns: ['chat', 'common'],
  defaultNS: 'chat',
  interpolation: { escapeValue: false },
})

export default i18n
