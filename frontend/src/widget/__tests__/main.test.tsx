import { describe, test, expect, vi, beforeAll, beforeEach, afterEach } from 'vitest'
import { act } from '@testing-library/react'
import { readConfig, mountWidget } from '../main'
import i18n from '@/shared/i18n'

beforeAll(async () => {
  await i18n.changeLanguage('es')
})

describe('Widget main', () => {
  let changeLanguageSpy: any

  beforeEach(() => {
    // mountWidget dispara applyChatbotTheme (fetch al tema del chatbot) sin esperarlo:
    // sin este stub, cada test golpearía la red de verdad -- lento y no determinista.
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false }))
  })

  afterEach(() => {
    document.body.innerHTML = ''
    changeLanguageSpy?.mockRestore()
    vi.unstubAllGlobals()
  })

  test('should_mount_widget_from_data_attributes', async () => {
    const container = document.createElement('div')
    container.setAttribute('data-chatbot-id', 'abc-123')
    container.setAttribute('data-lang', 'es')
    container.setAttribute('data-api-url', 'https://api.example.com')
    document.body.appendChild(container)

    const config = readConfig(container)
    expect(config).not.toBeNull()

    await act(async () => {
      mountWidget(container, config!)
    })

    // UX.1: recién montado el widget está CERRADO, así que lo que prueba que ha montado
    // es su lanzador, no el diálogo. Antes arrancaba abierto y se desplegaba solo sobre
    // la página anfitriona.
    expect(container.querySelector('[data-testid="widget-launcher"]')).not.toBeNull()
  })

  test('should_use_lang_from_data_attribute', async () => {
    changeLanguageSpy = vi.spyOn(i18n, 'changeLanguage')

    const container = document.createElement('div')
    container.setAttribute('data-chatbot-id', 'abc-123')
    container.setAttribute('data-lang', 'ca')
    document.body.appendChild(container)

    const config = readConfig(container)

    await act(async () => {
      mountWidget(container, config!)
    })

    expect(changeLanguageSpy).toHaveBeenCalledWith('ca')
  })

  test('should_update_lang_on_postmessage_from_parent', async () => {
    changeLanguageSpy = vi.spyOn(i18n, 'changeLanguage')

    const container = document.createElement('div')
    container.setAttribute('data-chatbot-id', 'abc-123')
    container.setAttribute('data-lang', 'es')
    document.body.appendChild(container)

    const config = readConfig(container)
    let cleanup: (() => void) | undefined

    await act(async () => {
      cleanup = mountWidget(container, config!)
    })

    changeLanguageSpy.mockClear()

    window.dispatchEvent(
      new MessageEvent('message', {
        data: { type: 'govgenai:setLang', lang: 'en' },
        origin: window.location.origin,
      }),
    )

    expect(changeLanguageSpy).toHaveBeenCalledWith('en')
    cleanup?.()
  })

  // #278 — el `listener` no miraba el origen: cualquier iframe de la página podía cambiarle el
  // idioma, y el siguiente tipo de mensaje que se añadiera heredaría el mismo agujero.
  test('should_ignore_a_message_from_another_origin', async () => {
    changeLanguageSpy = vi.spyOn(i18n, 'changeLanguage')

    const container = document.createElement('div')
    container.setAttribute('data-chatbot-id', 'abc-123')
    container.setAttribute('data-lang', 'es')
    document.body.appendChild(container)

    let cleanup: (() => void) | undefined
    await act(async () => {
      cleanup = mountWidget(container, readConfig(container)!)
    })
    changeLanguageSpy.mockClear()

    window.dispatchEvent(
      new MessageEvent('message', {
        data: { type: 'govgenai:setLang', lang: 'en' },
        origin: 'https://otra-web.example',
      }),
    )

    expect(changeLanguageSpy).not.toHaveBeenCalled()
    cleanup?.()
  })

  test('should_hide_widget_if_chatbot_id_missing', () => {
    const container = document.createElement('div')

    const config = readConfig(container)
    expect(config).toBeNull()
  })

  // Con dos asistentes publicados sobre el mismo corpus, una cabecera que dice sólo
  // «Asistente» no permite saber cuál se está probando, y las valoraciones del piloto se
  // atribuyen a ciegas. El nombre lo declara la página, como `data-model`: es información
  // de quien despliega, y el texto que se quiere mostrar no es el nombre interno del
  // chatbot en el panel.
  test('should_read_title_from_data_attribute', () => {
    const container = document.createElement('div')
    container.setAttribute('data-chatbot-id', 'abc-123')
    container.setAttribute('data-title', 'Assistent econòmic-administratiu')

    const config = readConfig(container)
    expect(config?.title).toBe('Assistent econòmic-administratiu')
  })

  test('should_leave_title_undefined_when_attribute_absent', () => {
    const container = document.createElement('div')
    container.setAttribute('data-chatbot-id', 'abc-123')

    const config = readConfig(container)
    expect(config?.title).toBeUndefined()
  })
})
