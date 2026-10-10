/**
 * CUR.2 — Cobertura i18n de la superficie propia de curación.
 *
 * Extiende el guardarraíl que CAL.4 escribió para `admin` (paridad es/ca/en + sin claves
 * muertas) al árbol nuevo `frontend/src/curation/`, y añade el cuarto test que pide el
 * prompt: `should_have_no_hardcoded_strings`, ausente hasta ahora porque `contentQuality`
 * vivía repartido entre `admin/pages` sin un guardarraíl propio.
 */
import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, resolve } from 'node:path'

import es from '@/shared/i18n/locales/es/curation.json'
import ca from '@/shared/i18n/locales/ca/curation.json'
import en from '@/shared/i18n/locales/en/curation.json'

const CURATION_SRC = resolve(__dirname, '../../../curation')

type Diccionario = Record<string, unknown>

function claves(objeto: Diccionario, prefijo = ''): string[] {
  return Object.entries(objeto).flatMap(([k, v]) =>
    v && typeof v === 'object' && !Array.isArray(v)
      ? claves(v as Diccionario, `${prefijo}${k}.`)
      : [`${prefijo}${k}`],
  )
}

function ficherosFuente(dir: string): string[] {
  const out: string[] = []
  const walk = (d: string) => {
    for (const entry of readdirSync(d)) {
      const full = join(d, entry)
      if (statSync(full).isDirectory()) {
        if (entry === 'node_modules' || entry === '__tests__') continue
        walk(full)
        continue
      }
      if (/\.(ts|tsx)$/.test(entry)) out.push(full)
    }
  }
  walk(dir)
  return out
}

const ficherosCuracion = ficherosFuente(CURATION_SRC)
const codigoCuracion = ficherosCuracion.map((f) => readFileSync(f, 'utf-8')).join('\n')

describe('CUR.2 — i18n de curación', () => {
  it('should_have_key_parity_across_es_ca_en_curation_namespace', () => {
    const kEs = claves(es as Diccionario).sort()
    const kCa = claves(ca as Diccionario).sort()
    const kEn = claves(en as Diccionario).sort()

    const faltanCa = kEs.filter((k) => !kCa.includes(k))
    const sobranCa = kCa.filter((k) => !kEs.includes(k))
    const faltanEn = kEs.filter((k) => !kEn.includes(k))
    const sobranEn = kEn.filter((k) => !kEs.includes(k))

    expect(faltanCa, `Claves sin traducir al catalán:\n  ${faltanCa.join('\n  ')}`).toEqual([])
    expect(sobranCa, `Claves en catalán que ya no existen en castellano: ${sobranCa.join(', ')}`).toEqual([])
    expect(faltanEn, `Claves sin traducir al inglés:\n  ${faltanEn.join('\n  ')}`).toEqual([])
    expect(sobranEn, `Claves en inglés que ya no existen en castellano: ${sobranEn.join(', ')}`).toEqual([])
  })

  it('should_not_keep_unused_curation_i18n_keys', () => {
    // type_*, severity_* y status_* se arman con una plantilla (`t(\`type_${x}\`)`) y no
    // aparecen literales en el código: se comprueban por prefijo, como hace CAL.4 con
    // hub.availability_* en el namespace admin.
    const PREFIJOS_DINAMICOS = ['type_', 'severity_', 'status_']

    // Las clases de error del rastreo (RAS.3) se traducen igual, con
    // `t(\`reason_error_${clase}\`)` en `razonDelHallazgo.ts`, así que tampoco aparecen
    // literales. Se enumeran una a una en vez de exentar el prefijo `reason_error_`
    // completo: `reason_error_attempts` SÍ se escribe literal y debe seguir vigilada.
    // La lista espeja `conocidas` en `curation/razonDelHallazgo.ts`.
    const CLAVES_DINAMICAS = [
      'reason_error_not_found',
      'reason_error_transient',
      'reason_error_client_error',
      'reason_error_unknown',
    ]

    const muertas = claves(es as Diccionario).filter((k) => {
      if (PREFIJOS_DINAMICOS.some((p) => k.startsWith(p))) return false
      if (CLAVES_DINAMICAS.includes(k)) return false
      return !codigoCuracion.includes(`'${k}'`) && !codigoCuracion.includes(`"${k}"`)
    })

    expect(
      muertas,
      `Claves del diccionario de curación sin ningún consumidor en el código:\n  ${muertas.join('\n  ')}`,
    ).toEqual([])
  })

  it('should_not_keep_curation_keys_only_as_inline_default', () => {
    // Mismo guardarraíl que CAL.4.1 para admin: un default que nunca se usa se desincroniza
    // del diccionario sin que nadie lo note.
    const kEs = new Set(claves(es as Diccionario))
    const patron = /t\(\s*'([\w.]+)'\s*,\s*'/g

    const huerfanas = new Set<string>()
    for (const m of codigoCuracion.matchAll(patron)) {
      if (!kEs.has(m[1])) huerfanas.add(m[1])
    }

    expect([...huerfanas]).toEqual([])
  })

  it('should_have_no_hardcoded_strings', () => {
    // Literales castellanos que ya se sabe que NO deben volver a aparecer incrustados en JSX:
    // son justo los que existían como texto de UI antes de que CUR.2 diera a la curación su
    // propio diccionario. Un `grep` de todo el árbol por comillas + mayúscula inicial daría
    // muchos falsos positivos (valores de enum, claves de i18n); comprobar frases concretas
    // es lo que de verdad distingue "hay un string suelto" de "hay código".
    const LITERALES = [
      'Nuevo sitio',
      'Rastrear ahora',
      'Analizar ahora',
      'Nueva selección',
      'Sitios web',
      'Calidad de contenido',
      'Auditoría de calidad web',
    ]
    const presentes = LITERALES.filter((l) => codigoCuracion.includes(`'${l}'`) || codigoCuracion.includes(`"${l}"`) || codigoCuracion.includes(`>${l}<`))
    expect(
      presentes,
      `Literales en castellano incrustados en frontend/src/curation:\n  ${presentes.join('\n  ')}`,
    ).toEqual([])
  })
})
