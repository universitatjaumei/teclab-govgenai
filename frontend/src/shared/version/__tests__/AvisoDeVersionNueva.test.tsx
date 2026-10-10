import { describe, it, expect, beforeAll, beforeEach, afterEach, vi } from 'vitest'
import { render, screen, act } from '@testing-library/react'
import i18n from '@/shared/i18n'

/**
 * #248 — una pestaña abierta antes de un despliegue avisa de que hay versión nueva.
 *
 * Sin esto se queda en el código viejo indefinidamente, y con probadores eso se lee como «no
 * funciona». No se recarga a la fuerza: se perdería un formulario a medias. Lo que dice qué
 * versión está desplegada es el `index.html` que se sirve —el script principal lleva el hash del
 * contenido en el nombre—, así que no hace falta que nadie suba un número de versión.
 */
import { AvisoDeVersionNueva } from '../AvisoDeVersionNueva'
import { scriptPrincipal } from '../versionDelPanel'

const HTML = (script: string) =>
  `<!doctype html><html><head><script type="module" crossorigin src="${script}"></script></head><body><div id="root"></div></body></html>`

let servido = HTML('/panel/assets/index-AAAA.js')

beforeAll(async () => {
  await i18n.changeLanguage('ca')
})

beforeEach(() => {
  const script = document.createElement('script')
  script.type = 'module'
  script.src = '/panel/assets/index-AAAA.js'
  script.dataset.prueba = 'si'
  document.head.appendChild(script)
  servido = HTML('/panel/assets/index-AAAA.js')
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, text: async () => servido })))
})

afterEach(() => {
  document.head.querySelectorAll('script[data-prueba]').forEach((s) => s.remove())
  vi.unstubAllGlobals()
})

async function volverALaPestana() {
  await act(async () => {
    document.dispatchEvent(new Event('visibilitychange'))
  })
}

describe('#248 — aviso de versión nueva', () => {
  it('lee el script principal del index.html', () => {
    expect(scriptPrincipal(HTML('/panel/assets/index-B1c2.js'))).toBe('/panel/assets/index-B1c2.js')
    expect(scriptPrincipal('<html></html>')).toBeNull()
  })

  it('no dice nada mientras lo servido es lo que se está ejecutando', async () => {
    render(<AvisoDeVersionNueva />)
    await volverALaPestana()

    expect(screen.queryByRole('status')).toBeNull()
  })

  it('al volver a la pestaña tras un despliegue, avisa y ofrece recargar', async () => {
    render(<AvisoDeVersionNueva />)
    servido = HTML('/panel/assets/index-BBBB.js')
    await volverALaPestana()

    const aviso = screen.getByRole('status')
    expect(aviso.textContent).toMatch(/versió nova/i)
    expect(screen.getByRole('button', { name: /recarrega/i })).toBeTruthy()
  })

  it('si no carga una pantalla porque su fichero ya no existe, avisa igual', async () => {
    render(<AvisoDeVersionNueva />)
    await act(async () => {
      window.dispatchEvent(new Event('vite:preloadError'))
    })

    expect(screen.getByRole('status')).toBeTruthy()
  })

  it('si no puede preguntar, no avisa: un fallo de red no es una versión nueva', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('sin red') }))
    render(<AvisoDeVersionNueva />)
    await volverALaPestana()

    expect(screen.queryByRole('status')).toBeNull()
  })
})
