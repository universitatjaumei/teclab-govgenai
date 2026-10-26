import { describe, it, expect } from 'vitest'
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative, resolve } from 'node:path'
import { codigoSinComentarios } from '@/test-utils/codigoSinComentarios'

/**
 * #277 — el panel no esquiva el contrato con `as unknown as`.
 *
 * Había 41 en código de producción, varios al mismo tipo que el hook generado ya devolvía —el
 * bloque `chatbotsRaw as unknown as ChatbotRead[]` estaba copiado en cinco páginas— y otros a
 * tipos escritos a mano que sombreaban los generados. Al quitarlos aparecieron los huecos que
 * tapaban: un `null` sin comprobar en el borrador de plantilla, campos opcionales del contrato
 * tratados como obligatorios en la vista previa, y `/auth/me` sin modelo de respuesta.
 *
 * Si un tipo generado no sirve, lo que se arregla es el contrato en el servidor.
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

describe('#277 — sin casts dobles en el panel', () => {
  it('should_not_cast_through_unknown', () => {
    const culpables = ficherosDeCodigo(SRC).filter((ruta) =>
      /\bas unknown as\b/.test(codigoSinComentarios(readFileSync(ruta, 'utf-8'))),
    )
    expect(culpables.map((ruta) => relative(SRC, ruta))).toEqual([])
  })
})
