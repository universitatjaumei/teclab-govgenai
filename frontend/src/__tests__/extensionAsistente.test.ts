import { describe, it, expect, beforeEach } from 'vitest'
import { readFileSync, readdirSync } from 'node:fs'
import { resolve } from 'node:path'

/**
 * #215 — insertar el prompt en Gemini y leer la respuesta, contra la página de verdad.
 *
 * Las instantáneas de `extension/instantaneas/` son el esqueleto de gemini.google.com capturado
 * de una conversación real. **El adaptador vigente tiene que casar con todas**: cuando Gemini
 * cambie se añade una nueva, y una corrección de selectores que rompa las anteriores no pasa.
 *
 * Lo que fija:
 * - inserta en el cuadro y lo coteja, y dice qué selector falló si no lo encuentra;
 * - espera a que el panel deje de estar ocupado y el texto deje de crecer;
 * - lee el panel del mensaje y **no** el aviso para lectores de pantalla, que también es `aria-live`;
 * - una respuesta cuyo texto no se encuentra es un selector roto; una que no llega, no.
 */

const RAIZ = resolve(__dirname, '../../..')
const CODIGO = readFileSync(resolve(RAIZ, 'extension/asistente.js'), 'utf-8')
const ADAPTADOR = JSON.parse(readFileSync(resolve(RAIZ, 'extension/adaptadores/gemini.json'), 'utf-8'))
const SEL = ADAPTADOR.selectores
const INSTANTANEAS = readdirSync(resolve(RAIZ, 'extension/instantaneas')).filter((f) => f.startsWith('gemini-'))

type Resultado = { ok: boolean; selector?: string; motivo?: string; texto?: string; fuentes?: string[] }
const { insertarEnElAsistente, contarRespuestas, esperarRespuesta } = new Function(
  `${CODIGO}\nreturn { insertarEnElAsistente, contarRespuestas, esperarRespuesta };`,
)() as {
  insertarEnElAsistente: (s: typeof SEL, t: string) => Resultado
  contarRespuestas: (s: typeof SEL) => number
  esperarRespuesta: (s: typeof SEL, previas: number, limiteMs: number, cadaMs?: number, estableMs?: number) => Promise<Resultado & { porEstabilidad?: boolean }>
}

function cargar(fichero = INSTANTANEAS[INSTANTANEAS.length - 1]) {
  document.body.innerHTML = readFileSync(resolve(RAIZ, 'extension/instantaneas', fichero), 'utf-8')
}

/** jsdom no tiene `execCommand`: se imita lo que hace el editor de Gemini, un párrafo por línea. */
function conEditor() {
  document.execCommand = ((orden: string, _ui: boolean, valor: string) => {
    if (orden !== 'insertText') return false
    const destino = window.getSelection()!.getRangeAt(0).startContainer as HTMLElement
    destino.innerHTML = valor.split('\n').map((l) => `<p>${l}</p>`).join('')
    return true
  }) as typeof document.execCommand
}

beforeEach(() => {
  conEditor()
})

describe('#215 — el adaptador vigente casa con todas las instantáneas', () => {
  it.each(INSTANTANEAS)('%s', (fichero) => {
    cargar(fichero)
    expect(document.querySelectorAll(SEL.cuadro)).toHaveLength(1)
    const ultima = [...document.querySelectorAll(SEL.respuesta)].pop()!
    expect(ultima.querySelector(SEL.texto)?.getAttribute(SEL.ocupado)).toBe('false')
  })
})

describe('#215 — insertar', () => {
  it('pone el prompt en el cuadro, línea a línea', () => {
    cargar()
    const r = insertarEnElAsistente(SEL, 'Eres el asistente de contratación.\nPregunta: ¿importe?')
    expect(r).toEqual({ ok: true })
    const cuadro = document.querySelector(SEL.cuadro)!
    expect(cuadro.querySelectorAll('p')).toHaveLength(2)
    expect(cuadro.textContent).toContain('Pregunta: ¿importe?')
  })

  it('si el cuadro no está, dice que falló el selector del cuadro', () => {
    cargar()
    document.querySelector('rich-textarea')!.remove()
    expect(insertarEnElAsistente(SEL, 'hola')).toEqual({ ok: false, selector: 'cuadro' })
  })

  it('si el editor no acepta el texto, lo dice en vez de darlo por insertado', () => {
    cargar()
    document.execCommand = (() => false) as typeof document.execCommand
    expect(insertarEnElAsistente(SEL, 'hola')).toEqual({ ok: false, selector: 'insercion' })
  })
})

describe('#215 — leer la respuesta', () => {
  it('cuenta las que ya hay, para esperar la siguiente', () => {
    cargar()
    expect(contarRespuestas(SEL)).toBe(1)
  })

  it('espera a que deje de estar ocupada y lee el mensaje, no el aviso para lectores de pantalla', async () => {
    cargar()
    const panel = document.querySelector(`model-response ${SEL.texto}`)!
    panel.setAttribute('aria-busy', 'true')
    panel.textContent = 'Un índice'
    const espera = esperarRespuesta(SEL, 0, 5000, 10)
    setTimeout(() => {
      panel.textContent = 'Un índice de documentos es una lista.'
    }, 30)
    setTimeout(() => panel.setAttribute('aria-busy', 'false'), 60)
    const r = await espera
    expect(r.ok).toBe(true)
    expect(r.texto).toBe('Un índice de documentos es una lista.')
    expect(r.texto).not.toContain('Gemini ha dicho')
    expect(r.fuentes).toEqual([])
  })

  it('con la pestaña oculta Gemini no baja aria-busy: un texto que ya no cambia se da por terminado', async () => {
    // Visto en la página de verdad: Gemini quita aria-busy al pintar, y una pestaña oculta no pinta.
    cargar()
    const panel = document.querySelector(`model-response ${SEL.texto}`)!
    panel.setAttribute('aria-busy', 'true')
    const r = await esperarRespuesta(SEL, 0, 5000, 10, 100)
    expect(r).toMatchObject({ ok: true, porEstabilidad: true })
    expect(r.texto).toContain('Un índice de documentos')
  })

  it('mientras el texto crece, no se da por terminado aunque pase el plazo de estabilidad', async () => {
    cargar()
    const panel = document.querySelector(`model-response ${SEL.texto}`)!
    panel.setAttribute('aria-busy', 'true')
    let n = 0
    const crecer = setInterval(() => (panel.textContent = 'x'.repeat(++n)), 20)
    const r = await esperarRespuesta(SEL, 0, 300, 10, 100)
    clearInterval(crecer)
    expect(r).toEqual({ ok: false, motivo: 'sin_terminar' })
  })

  it('recoge los enlaces de las fuentes que cita', async () => {
    cargar()
    document.querySelector('sources-list')!.innerHTML = '<a href="https://drive.google.com/file/d/1">Instrucción</a>'
    const r = await esperarRespuesta(SEL, 0, 5000, 10)
    expect(r.fuentes).toEqual(['https://drive.google.com/file/d/1'])
  })

  it('si no llega ninguna respuesta nueva, no es un selector roto: no se envió', async () => {
    cargar()
    const r = await esperarRespuesta(SEL, 1, 50, 10)
    expect(r).toEqual({ ok: false, motivo: 'sin_respuesta' })
  })
})
