import { describe, it, expect } from 'vitest'
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative, resolve } from 'node:path'
import { codigoSinComentarios } from '@/test-utils/codigoSinComentarios'

/**
 * #277 — el panel no decide con el rol del JWT.
 *
 * Cinco pantallas lo hacían —`user?.role === 'superadmin'`, `['superadmin', 'admin'].includes(
 * user.role)`— para elegir qué enseñar: los niveles de identidad visual, el selector de plantilla,
 * la cola de revisión de scripts, la pestaña de integración de asistentes y el constructor de
 * plantillas. Es lo que la regla de AGENTS.md prohíbe, y la cola además mandaba a `/hub` a quien
 * no era administrador, una ruta que podía no tener. Ahora lo pregunta a `/auth/me` con
 * `useCapacidad`.
 *
 * Pintar el rol —la columna de la tabla de personas— no es decidir con él, y no se mira.
 */
const SRC = resolve(__dirname, '..')
const IGNORADOS = new Set(['generated', 'node_modules', '__tests__', 'test-utils'])

function ficherosDeCodigo(directorio: string): string[] {
  return readdirSync(directorio).flatMap((entrada) => {
    const ruta = join(directorio, entrada)
    if (statSync(ruta).isDirectory()) return IGNORADOS.has(entrada) ? [] : ficherosDeCodigo(ruta)
    return /\.tsx?$/.test(entrada) && !/\.test\.tsx?$/.test(entrada) ? [ruta] : []
  })
}

/** Comparar el rol de la sesión con un literal, o buscarlo en una lista de roles. */
const DECIDE_CON_EL_ROL = /user\??\.role\s*(===|!==|==|!=)|\.includes\(\s*user\??\.role\s*\)/

describe('#277 — el rol no decide en el panel', () => {
  it('should_find_code_to_look_at', () => {
    expect(ficherosDeCodigo(SRC).length).toBeGreaterThan(100)
  })

  it('should_not_compare_the_session_role_anywhere', () => {
    const culpables = ficherosDeCodigo(SRC).filter((ruta) =>
      DECIDE_CON_EL_ROL.test(codigoSinComentarios(readFileSync(ruta, 'utf-8'))),
    )
    expect(culpables.map((ruta) => relative(SRC, ruta))).toEqual([])
  })

  it('should_catch_the_pattern_it_looks_for', () => {
    expect(DECIDE_CON_EL_ROL.test("const x = user?.role === 'superadmin'")).toBe(true)
    expect(DECIDE_CON_EL_ROL.test("['admin'].includes(user.role)")).toBe(true)
    expect(DECIDE_CON_EL_ROL.test('t(`roles.${persona.role}`)')).toBe(false)
  })
})
