/**
 * #243 y #245 — ninguna llamada a t() lleva un texto de reserva literal.
 *
 * Un texto de reserva tapa la clave que falta: `tc('close', 'Cerrar')` pintaba «Cerrar» en
 * valenciano porque la clave no existía en ningún idioma, y lo mismo «Crear informe» en Informes.
 * Sin reserva, una clave que falta se ve en pantalla y la paridad de idiomas la caza.
 *
 * Empezó en curación y en Informes (#243). #245 lo extiende a todo `src/` y caza también la
 * llamada partida en varias líneas, que es como se escapó `sample_help`: la única clave de las
 * 34 reservas que no existía, y que en valenciano e inglés salía en castellano.
 *
 * Lo que sí vale es `{ defaultValue: codigo }` con una clave construida a partir de un código del
 * servidor: la reserva es el propio código, no un texto en un idioma.
 */
import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, relative, resolve } from 'node:path'

const SRC = resolve(__dirname, '../../..')

function ficherosFuente(dir: string): string[] {
  const out: string[] = []
  for (const entrada of readdirSync(dir)) {
    const ruta = join(dir, entrada)
    if (statSync(ruta).isDirectory()) {
      if (entrada !== '__tests__' && entrada !== 'generated') out.push(...ficherosFuente(ruta))
    } else if (/\.(ts|tsx)$/.test(entrada) && !/\.test\.tsx?$/.test(entrada)) {
      out.push(ruta)
    }
  }
  return out
}

// `t('clave', 'texto')`, `tc("clave", "texto")` o `t('clave', `texto`)`, en una línea o en varias.
const CON_RESERVA = /\bt[A-Za-z]*\(\s*(['"])[^'"\n]+\1\s*,\s*['"`]/g

describe('#245 — ninguna llamada a t() lleva un texto de reserva', () => {
  it('en todo frontend/src', () => {
    const hallados: string[] = []
    for (const fichero of ficherosFuente(SRC)) {
      const codigo = readFileSync(fichero, 'utf-8')
      for (const m of codigo.matchAll(CON_RESERVA)) {
        const linea = codigo.slice(0, m.index).split('\n').length
        hallados.push(`${relative(SRC, fichero)}:${linea}`)
      }
    }
    expect(hallados).toEqual([])
  })
})
