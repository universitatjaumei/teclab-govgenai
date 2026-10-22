import { describe, expect, it } from 'vitest'
import { enlaceExterno } from '../enlaceExterno'

// Un `href` que sale de un dato —la URL de un documento del corpus, la de una página rastreada—
// no se pinta tal cual: `javascript:` en un enlace se ejecuta al pulsarlo, y en el widget se
// ejecutaría en la web de quien lo embebe.
describe('enlaceExterno', () => {
  it.each([
    'https://www.uji.es/norma',
    'http://www.uji.es/norma',
    'HTTPS://www.uji.es/NORMA',
  ])('deja pasar %s', (url) => {
    expect(enlaceExterno(url)).toBe(url)
  })

  it.each([
    'javascript:alert(1)',
    ' javascript:alert(1)',
    'JaVaScRiPt:alert(1)',
    'data:text/html,<script>alert(1)</script>',
    'vbscript:msgbox(1)',
    'ingestion/abc/def.md',
    '',
    null,
    undefined,
  ])('no deja pasar %s', (url) => {
    expect(enlaceExterno(url)).toBeUndefined()
  })
})
