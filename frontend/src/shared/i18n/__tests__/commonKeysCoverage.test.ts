/**
 * #374 — toda clave de `common` que pide el código existe en las tres lenguas.
 *
 * `tc('invalid_url')` en «Nueva web» pintaba la clave tal cual: no estaba en `common.json` de
 * ninguna lengua, y los guardarraíles de paridad de cada módulo sólo miran su propio namespace.
 * Nació como test de curación; la revisión de la PR #375 señaló que el mismo hueco en admin,
 * redaccion o widget pasaría en verde, así que mira todo `src`.
 */
import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, resolve } from 'node:path'

import es from '@/shared/i18n/locales/es/common.json'
import ca from '@/shared/i18n/locales/ca/common.json'
import en from '@/shared/i18n/locales/en/common.json'

const SRC = resolve(__dirname, '../../..')
const IGNORADOS = new Set(['generated', 'node_modules', '__tests__', 'test-utils'])

type Diccionario = Record<string, unknown>

function claves(objeto: Diccionario, prefijo = ''): string[] {
  return Object.entries(objeto).flatMap(([k, v]) =>
    v && typeof v === 'object' && !Array.isArray(v)
      ? claves(v as Diccionario, `${prefijo}${k}.`)
      : [`${prefijo}${k}`],
  )
}

function ficheros(dir: string): string[] {
  return readdirSync(dir).flatMap((entrada) => {
    const ruta = join(dir, entrada)
    if (statSync(ruta).isDirectory()) return IGNORADOS.has(entrada) ? [] : ficheros(ruta)
    return /\.(ts|tsx)$/.test(entrada) && !/\.test\.tsx?$/.test(entrada) ? [ruta] : []
  })
}

const codigo = ficheros(SRC).map((f) => readFileSync(f, 'utf-8')).join('\n')
const usadas = new Set([...codigo.matchAll(/\btc\(\s*'([\w.]+)'/g)].map((m) => m[1]))

describe('#374 — claves de common', () => {
  it('should_find_tc_calls_to_check', () => {
    expect(usadas.has('invalid_url')).toBe(true)
    expect(usadas.size).toBeGreaterThan(5)
  })

  it('should_find_every_common_key_the_code_uses', () => {
    for (const [lengua, dic] of Object.entries({ es, ca, en })) {
      const existentes = new Set(claves(dic as Diccionario))
      const faltan = [...usadas].filter((k) => !existentes.has(k))
      expect(faltan, `Claves de common que el código usa y faltan en ${lengua}`).toEqual([])
    }
  })
})
