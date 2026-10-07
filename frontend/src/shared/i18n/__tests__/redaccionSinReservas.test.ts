/**
 * #243 — en Informes, ninguna llamada a t() lleva un texto de reserva.
 *
 * La revisión de la PR #244 lo encontró en la pantalla que #243 acababa de hacer de entrada:
 * «Nuevo informe» pintaba `t('create_report', 'Crear informe')`, y como la clave no existía en
 * ningún idioma, en valenciano y en inglés salía «Crear informe». Es el mismo defecto que el
 * «Cerrar» de curación: el texto de reserva tapa la clave que falta. Sin él, una clave que falta
 * se ve en pantalla y la paridad de idiomas la caza.
 */
import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, resolve } from 'node:path'

const REDACCION_SRC = resolve(__dirname, '../../../redaccion')

function ficherosFuente(dir: string): string[] {
  const out: string[] = []
  for (const entrada of readdirSync(dir)) {
    const ruta = join(dir, entrada)
    if (statSync(ruta).isDirectory()) {
      if (entrada !== '__tests__') out.push(...ficherosFuente(ruta))
    } else if (/\.(ts|tsx)$/.test(entrada)) {
      out.push(ruta)
    }
  }
  return out
}

describe('#243 — Informes sin textos de reserva en t()', () => {
  it('ninguna llamada a t() de Informes lleva un texto por defecto', () => {
    const codigo = ficherosFuente(REDACCION_SRC).map((f) => readFileSync(f, 'utf-8')).join('\n')
    const conReserva = codigo.match(/\bt[A-Za-z]*\(\s*'[^']+'\s*,\s*'[^']*'\s*\)/g) ?? []
    expect(conReserva).toEqual([])
  })
})
