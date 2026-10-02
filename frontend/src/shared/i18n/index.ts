import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'
import LanguageDetector from 'i18next-browser-languagedetector'

import esCommon from './locales/es/common.json'
import esChat from './locales/es/chat.json'
import esAdmin from './locales/es/admin.json'
import esScripts from './locales/es/scripts.json'
import esRedaccion from './locales/es/redaccion.json'
import esCuration from './locales/es/curation.json'
import esAuth from './locales/es/auth.json'
import esUtilidades from './locales/es/utilidades.json'
import enCommon from './locales/en/common.json'
import enChat from './locales/en/chat.json'
import enAdmin from './locales/en/admin.json'
import enScripts from './locales/en/scripts.json'
import enRedaccion from './locales/en/redaccion.json'
import enCuration from './locales/en/curation.json'
import enAuth from './locales/en/auth.json'
import enUtilidades from './locales/en/utilidades.json'
import caCommon from './locales/ca/common.json'
import caChat from './locales/ca/chat.json'
import caAdmin from './locales/ca/admin.json'
import caScripts from './locales/ca/scripts.json'
import caRedaccion from './locales/ca/redaccion.json'
import caCuration from './locales/ca/curation.json'
import caAuth from './locales/ca/auth.json'
import caUtilidades from './locales/ca/utilidades.json'

export const SUPPORTED_LANGUAGES = ['es', 'ca', 'en'] as const
export type SupportedLanguage = (typeof SUPPORTED_LANGUAGES)[number]

/**
 * La configuración de i18next, exportada para que se pueda **probar la de verdad**.
 *
 * Lo señaló la revisión de la PR #168: el test de la issue #16 montaba su propia instancia con
 * las opciones copiadas a mano, así que seguía en verde aunque aquí cambiara el orden de
 * detección, el idioma de reserva o el tratamiento de las variantes regionales. Comprobaba una
 * copia, que es una forma cómoda de no comprobar nada.
 */
export const OPCIONES_I18N = {
  resources: {
      es: { common: esCommon, chat: esChat, admin: esAdmin, scripts: esScripts, redaccion: esRedaccion, curation: esCuration, auth: esAuth, utilidades: esUtilidades },
      ca: { common: caCommon, chat: caChat, admin: caAdmin, scripts: caScripts, redaccion: caRedaccion, curation: caCuration, auth: caAuth, utilidades: caUtilidades },
      en: { common: enCommon, chat: enChat, admin: enAdmin, scripts: enScripts, redaccion: enRedaccion, curation: enCuration, auth: enAuth, utilidades: enUtilidades },
    },
    fallbackLng: {
      'ca-ES': ['ca', 'es'],
      default: ['es'],
    },
    supportedLngs: [...SUPPORTED_LANGUAGES],
    ns: ['common', 'chat', 'admin', 'scripts', 'redaccion', 'curation', 'auth', 'utilidades'],
    defaultNS: 'common',
    interpolation: { escapeValue: false },
    detection: {
      order: ['localStorage', 'navigator'],
      caches: ['localStorage'],
    },
}

i18n.use(LanguageDetector).use(initReactI18next).init(OPCIONES_I18N)

export default i18n
