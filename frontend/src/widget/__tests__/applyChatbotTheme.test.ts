import { describe, it, expect, afterEach, vi } from 'vitest'
import { applyChatbotTheme, type WidgetConfig } from '../main'

/**
 * Hallazgo #3 de MAN.2: el widget publico no consumia ningun tema de chatbot/organizacion.
 *
 * `applyChatbotTheme` es la unica pieza de logica nueva en `main.tsx` -- el resto es
 * `injectThemeCSS`, ya cubierto donde vive (`injectThemeCSS.ts`). Lo que hace falta fijar
 * aqui es el contrato con el backend: cabecera `X-Widget-Key` solo si hay credencial de
 * sitio (SEC.8.5), y que un 403/404/red caida deja el widget con los colores por defecto
 * en vez de romper el montaje.
 */

const CONFIG: WidgetConfig = {
  chatbotId: '11111111-1111-1111-1111-111111111111',
  lang: 'es',
  apiUrl: 'https://example.org/api/v1',
}

function mockFetchOnce(response: { ok: boolean; json?: () => Promise<unknown> }) {
  const fetchMock = vi.fn().mockResolvedValue(response)
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

afterEach(() => {
  vi.unstubAllGlobals()
  document.getElementById('chatbot-theme-vars')?.remove()
})

describe('applyChatbotTheme', () => {
  it('calls the resolved-theme endpoint for this chatbot without credentials when none was configured', async () => {
    const fetchMock = mockFetchOnce({ ok: true, json: async () => ({ config: {} }) })

    await applyChatbotTheme(CONFIG)

    expect(fetchMock).toHaveBeenCalledWith(
      'https://example.org/api/v1/hub/themes/for-chatbot/11111111-1111-1111-1111-111111111111',
      { headers: {} },
    )
  })

  it('sends the site credential header when the widget was embedded with one', async () => {
    const fetchMock = mockFetchOnce({ ok: true, json: async () => ({ config: {} }) })

    await applyChatbotTheme({ ...CONFIG, widgetKey: 'wk-123' })

    expect(fetchMock).toHaveBeenCalledWith(expect.any(String), {
      headers: { 'X-Widget-Key': 'wk-123' },
    })
  })

  it('injects the resolved colors as CSS custom properties on :root', async () => {
    mockFetchOnce({
      ok: true,
      json: async () => ({ config: { colors: { primary: '#ff0000' } } }),
    })

    await applyChatbotTheme(CONFIG)

    const css = document.getElementById('chatbot-theme-vars')?.textContent ?? ''
    expect(css).toContain('--color-primary: #ff0000;')
  })

  it('leaves the widget on default colors when the chatbot has no theme applied', async () => {
    mockFetchOnce({ ok: true, json: async () => ({ config: {} }) })

    await applyChatbotTheme(CONFIG)

    const css = document.getElementById('chatbot-theme-vars')?.textContent ?? ''
    // DEFAULT_THEME.colors.primary tal y como lo fija frontend/src/themes/types.ts
    expect(css).toContain('--color-primary: #0066cc;')
  })

  it('does not throw and leaves defaults untouched when access is forbidden (SEC.2.1)', async () => {
    mockFetchOnce({ ok: false })

    await expect(applyChatbotTheme(CONFIG)).resolves.toBeUndefined()
    expect(document.getElementById('chatbot-theme-vars')).toBeNull()
  })

  it('does not throw when the network request fails outright', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('network down')))

    await expect(applyChatbotTheme(CONFIG)).resolves.toBeUndefined()
  })
})
