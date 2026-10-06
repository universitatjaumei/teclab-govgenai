import { describe, it, expect, beforeEach } from 'vitest'
import { readFileSync, readdirSync } from 'node:fs'
import { resolve } from 'node:path'

/**
 * #215 — el canario diario de la integración con Gemini.
 *
 * Una tarea programada abre cada día una conversación temporal de Gemini con el adaptador
 * vigente, comprueba los selectores, inserta una pregunta fija, la envía y lee la respuesta
 * (`extension/canario/CANARIO.md`). Si algo no casa, avisa a la plataforma y guarda el esqueleto
 * de la página nueva para corregir el adaptador y añadir la instantánea.
 *
 * Lo que fija `canario.js`:
 * - **qué selector** falla, por su nombre, que es lo que recibe `POST …/fallos`;
 * - antes de enviar sólo tiene que casar el cuadro; con la respuesta ya dada, todos menos las
 *   fuentes, que una respuesta sin fuentes no tiene;
 * - el esqueleto es el de las instantáneas: sin estilos, imágenes ni scripts, textos cortados a
 *   60 caracteres, y **el adaptador sigue casando con él**, que es para lo que sirve.
 */

const RAIZ = resolve(__dirname, '../../..')
const CODIGO = readFileSync(resolve(RAIZ, 'extension/canario/canario.js'), 'utf-8')
const ADAPTADOR = JSON.parse(readFileSync(resolve(RAIZ, 'extension/adaptadores/gemini.json'), 'utf-8'))
const SEL = ADAPTADOR.selectores
const INSTANTANEAS = readdirSync(resolve(RAIZ, 'extension/instantaneas')).filter((f) => f.startsWith('gemini-'))

type Comprobacion = { ok: boolean; fallan: string[] }
const { comprobarSelectores, instantaneaDeLaPagina } = new Function(
  `${CODIGO}\nreturn { comprobarSelectores, instantaneaDeLaPagina };`,
)() as {
  comprobarSelectores: (s: typeof SEL, conRespuesta: boolean) => Comprobacion
  instantaneaDeLaPagina: (fecha: string) => string
}

function cargar(fichero = INSTANTANEAS[INSTANTANEAS.length - 1]) {
  document.body.innerHTML = readFileSync(resolve(RAIZ, 'extension/instantaneas', fichero), 'utf-8')
}

beforeEach(() => cargar())

describe('#215 — el canario comprueba los selectores', () => {
  it('con la página de verdad casan todos', () => {
    expect(comprobarSelectores(SEL, true)).toEqual({ ok: true, fallan: [] })
  })

  it('antes de enviar sólo exige el cuadro', () => {
    document.querySelectorAll(SEL.respuesta).forEach((r) => r.remove())
    expect(comprobarSelectores(SEL, false)).toEqual({ ok: true, fallan: [] })
    expect(comprobarSelectores(SEL, true).fallan).toEqual(['respuesta'])
  })

  it('dice qué selector falla, por su nombre', () => {
    expect(comprobarSelectores({ ...SEL, cuadro: 'no-existe' }, false)).toEqual({ ok: false, fallan: ['cuadro'] })
    expect(comprobarSelectores({ ...SEL, texto: 'no-existe' }, true).fallan).toEqual(['texto'])
  })

  it('el atributo de ocupado tiene que estar en el panel del texto', () => {
    expect(comprobarSelectores({ ...SEL, ocupado: 'data-no-existe' }, true).fallan).toEqual(['ocupado'])
  })

  it('una respuesta sin fuentes no es un fallo', () => {
    document.querySelectorAll('sources-list').forEach((f) => f.remove())
    expect(comprobarSelectores(SEL, true).ok).toBe(true)
  })
})

describe('#215 — la instantánea de la página nueva', () => {
  it('es el esqueleto: sin estilos, imágenes ni scripts, y textos cortos', () => {
    const extra = document.createElement('div')
    extra.innerHTML = `<style>.x{}</style><script>1</script><img src="a.png"><p style="color:red" data-x="1">${'a'.repeat(200)}</p>`
    document.querySelector('chat-window')!.appendChild(extra)

    const html = instantaneaDeLaPagina('2026-10-06')

    expect(html).not.toMatch(/<style|<script|<img|style=|data-x=/)
    expect(html).not.toContain('a'.repeat(61))
    expect(html).toContain('a'.repeat(60))
  })

  it('quita también de la raíz las clases que genera Angular', () => {
    // Visto en la página real el 2026-10-06: la raíz salía con `ng-tns-…`.
    document.querySelector('chat-window')!.setAttribute('class', 'lm-canvas-styling ng-tns-c37-1 is-temporary-chat')
    const html = instantaneaDeLaPagina('2026-10-06')
    expect(html).toContain('<chat-window class="lm-canvas-styling is-temporary-chat">')
  })

  it('lleva la cabecera con la fecha, como las que hay', () => {
    expect(instantaneaDeLaPagina('2026-10-06')).toMatch(/^<!--[\s\S]*2026-10-06[\s\S]*-->\n<chat-window/)
  })

  it('y el adaptador sigue casando con ella, que es para lo que sirve', () => {
    const html = instantaneaDeLaPagina('2026-10-06')
    document.body.innerHTML = html
    expect(comprobarSelectores(SEL, true)).toEqual({ ok: true, fallan: [] })
  })
})
