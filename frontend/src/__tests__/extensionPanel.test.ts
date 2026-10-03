import { describe, it, expect, beforeEach, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

/**
 * #176 — el panel lateral de la extensión del navegador.
 *
 * Es JavaScript sin empaquetar, que Chrome carga tal cual: aquí se carga con un `chrome` y un
 * `fetch` de mentira y se comprueba lo que hace. Vive fuera de `frontend/` porque es otro producto;
 * se prueba aquí porque aquí hay un motor de JavaScript y un DOM en CI.
 *
 * Lo que fija:
 * - **la dirección del panel la fija la organización** por política y gana a la que escriba la persona;
 * - **conectar** pasa por la página de la plataforma y guarda el token que vuelve en el fragmento;
 * - **el prompt se pide a la API**, que es lo que queda registrado, y se copia tal cual llega;
 * - **un 401 olvida el token** y pide conectar de nuevo;
 * - **no toca ninguna otra página**: no hay `scripting` ni `tabs` entre lo que usa.
 */

const CODIGO = readFileSync(resolve(__dirname, '../../../extension/panel.js'), 'utf-8')
const MANIFIESTO = JSON.parse(readFileSync(resolve(__dirname, '../../../extension/manifest.json'), 'utf-8'))
const MENSAJES: Record<string, { message: string }> = JSON.parse(
  readFileSync(resolve(__dirname, '../../../extension/_locales/es/messages.json'), 'utf-8'),
)

interface Mundo {
  gestionada: Record<string, string>
  local: Record<string, string>
  peticiones: { url: string; metodo: string; cuerpo: unknown; autorizacion?: string }[]
  respuestas: Record<string, { status: number; cuerpo: unknown }>
  copiado: string[]
  flujo: string[]
  vuelta: string
  permiso: boolean
}

const AGENTES = [
  {
    id: 'a1',
    nombre: 'Becas',
    unidad: 'Servicio de Gestión de la Docencia',
    finalidad: 'Resolver dudas de becas.',
    responsable: 'Jefatura',
    version: 2,
    revision_vencida: false,
    espera_adjunto: false,
    indice_sin_actualizar: false,
  },
  {
    id: 'a2',
    nombre: 'Revisión de facturas',
    unidad: 'Servicio de Contratación',
    finalidad: 'Revisar una factura.',
    responsable: 'Jefatura',
    version: 1,
    revision_vencida: true,
    espera_adjunto: true,
    indice_sin_actualizar: false,
  },
]

function mundoBase(): Mundo {
  return {
    gestionada: {},
    local: {},
    peticiones: [],
    respuestas: {
      '/api/v1/agentes/catalogo': { status: 200, cuerpo: AGENTES },
      '/api/v1/agentes/a1/consulta': {
        status: 200,
        cuerpo: { agente: 'Becas', version: 2, prompt: 'PROMPT COMPUESTO', documentos: [], espera_adjunto: false },
      },
      '/api/v1/agentes/a2/consulta': {
        status: 200,
        cuerpo: { agente: 'Revisión de facturas', version: 1, prompt: 'OTRO', documentos: [], espera_adjunto: true },
      },
    },
    copiado: [],
    flujo: [],
    vuelta: 'https://abc.chromiumapp.org/#token=ggai_pat_nuevo',
    permiso: true,
  }
}

function cargar(mundo: Mundo) {
  const chrome = {
    i18n: {
      getUILanguage: () => 'es-ES',
      getMessage: (k: string) => MENSAJES[k]?.message ?? '',
    },
    storage: {
      managed: { get: async () => ({ ...mundo.gestionada }) },
      local: {
        get: async (claves: string[]) => Object.fromEntries(claves.filter((k) => k in mundo.local).map((k) => [k, mundo.local[k]])),
        set: async (o: Record<string, string>) => {
          Object.assign(mundo.local, o)
        },
        remove: async (k: string) => {
          delete mundo.local[k]
        },
      },
    },
    permissions: { request: async () => mundo.permiso },
    identity: {
      getRedirectURL: () => 'https://abc.chromiumapp.org/',
      launchWebAuthFlow: async ({ url }: { url: string }) => {
        mundo.flujo.push(url)
        return mundo.vuelta
      },
    },
  }
  const fetch = async (url: string, opciones: { method: string; headers: Record<string, string>; body?: string }) => {
    const ruta = new URL(url).pathname
    mundo.peticiones.push({
      url,
      metodo: opciones.method,
      cuerpo: opciones.body ? JSON.parse(opciones.body) : null,
      autorizacion: opciones.headers.Authorization,
    })
    const r = mundo.respuestas[ruta] ?? { status: 404, cuerpo: { detail: 'no' } }
    return { status: r.status, ok: r.status < 400, json: async () => r.cuerpo }
  }
  const navigator = {
    clipboard: {
      writeText: async (t: string) => {
        mundo.copiado.push(t)
      },
    },
  }
  const fabrica = new Function('chrome', 'fetch', 'navigator', `${CODIGO}\nreturn { pintar, configuracion };`)
  return fabrica(chrome, fetch, navigator) as { pintar: () => Promise<void>; configuracion: () => Promise<{ panel: string; api: string }> }
}

const esperar = () => new Promise((r) => setTimeout(r, 0))
const boton = (id: string) => document.getElementById(id) as HTMLButtonElement

describe('#176 — el panel de la extensión', () => {
  let mundo: Mundo

  beforeEach(() => {
    document.body.innerHTML = '<main id="raiz"></main>'
    mundo = mundoBase()
  })

  it('no pide más permisos que los suyos: ni scripting ni tabs, y los hosts son opcionales', () => {
    expect(MANIFIESTO.permissions).not.toContain('scripting')
    expect(MANIFIESTO.permissions).not.toContain('tabs')
    expect(MANIFIESTO.host_permissions).toBeUndefined()
    expect(MANIFIESTO.content_scripts).toBeUndefined()
  })

  it('las tres lenguas tienen las mismas claves', () => {
    for (const lengua of ['ca', 'en']) {
      const otras = JSON.parse(readFileSync(resolve(__dirname, `../../../extension/_locales/${lengua}/messages.json`), 'utf-8'))
      expect(Object.keys(otras).sort()).toEqual(Object.keys(MENSAJES).sort())
    }
  })

  it('la dirección que fija la organización gana a la que escribió la persona, y la API sale de su origen', async () => {
    mundo.gestionada = { panel_url: 'https://normativa.uji.es/panel/' }
    mundo.local = { panel_url: 'https://otra.example/panel' }
    const conf = await cargar(mundo).configuracion()
    expect(conf.panel).toBe('https://normativa.uji.es/panel')
    expect(conf.api).toBe('https://normativa.uji.es')
  })

  it('sin dirección, pide escribirla', async () => {
    await cargar(mundo).pintar()
    expect(document.getElementById('panel-url')).not.toBeNull()
  })

  it('conectar pasa por la página de la plataforma y guarda el token del fragmento', async () => {
    mundo.gestionada = { panel_url: 'https://normativa.uji.es/panel' }
    await cargar(mundo).pintar()
    boton('conectar').click()
    await vi.waitFor(() => expect(mundo.local.token).toBe('ggai_pat_nuevo'))
    expect(mundo.flujo[0]).toBe(
      'https://normativa.uji.es/panel/extension/conectar?destino=' + encodeURIComponent('https://abc.chromiumapp.org/'),
    )
    await vi.waitFor(() => expect(document.querySelectorAll('[data-agente]')).toHaveLength(2))
  })

  it('sin permiso de host no se conecta, y lo dice', async () => {
    mundo.gestionada = { panel_url: 'https://normativa.uji.es/panel' }
    mundo.permiso = false
    await cargar(mundo).pintar()
    boton('conectar').click()
    await vi.waitFor(() => expect(document.querySelector('[role="alert"]')?.textContent).toBe(MENSAJES.sinPermiso.message))
    expect(mundo.flujo).toHaveLength(0)
    expect(mundo.local.token).toBeUndefined()
  })

  it('pide el prompt a la API con el token y copia exactamente lo que devuelve', async () => {
    mundo.gestionada = { panel_url: 'https://normativa.uji.es/panel' }
    mundo.local = { token: 'ggai_pat_x' }
    await cargar(mundo).pintar()
    await vi.waitFor(() => expect(document.querySelectorAll('[data-agente]')).toHaveLength(2))

    expect(boton('preparar').disabled).toBe(true)
    const radio = document.querySelector('[data-agente="a1"] input') as HTMLInputElement
    radio.click()
    const pregunta = document.getElementById('pregunta') as HTMLTextAreaElement
    pregunta.value = '  ¿Plazo de la beca?  '
    pregunta.dispatchEvent(new Event('input'))
    expect(boton('preparar').disabled).toBe(false)

    boton('preparar').click()
    await vi.waitFor(() => expect(mundo.copiado).toEqual(['PROMPT COMPUESTO']))
    const consulta = mundo.peticiones.find((p) => p.url.endsWith('/a1/consulta'))
    expect(consulta).toMatchObject({
      metodo: 'POST',
      autorizacion: 'Bearer ggai_pat_x',
      cuerpo: { consulta: '¿Plazo de la beca?', lengua: 'es' },
    })
    expect(document.querySelector('[role="status"]')?.textContent).toBe(MENSAJES.copiado.message)
  })

  it('el agente que pide documento lo avisa, y al copiar recuerda adjuntarlo en el asistente', async () => {
    mundo.gestionada = { panel_url: 'https://normativa.uji.es/panel' }
    mundo.local = { token: 'ggai_pat_x' }
    await cargar(mundo).pintar()
    await vi.waitFor(() => expect(document.querySelectorAll('[data-agente]')).toHaveLength(2))
    const tarjeta = document.querySelector('[data-agente="a2"]') as HTMLElement
    expect(tarjeta.textContent).toContain(MENSAJES.conAdjunto.message)
    expect(tarjeta.textContent).toContain(MENSAJES.revisionVencida.message)

    ;(tarjeta.querySelector('input') as HTMLInputElement).click()
    expect(document.body.textContent).toContain(MENSAJES.describeElAdjunto.message)
    const pregunta = document.getElementById('pregunta') as HTMLTextAreaElement
    pregunta.value = 'Revisa la factura'
    pregunta.dispatchEvent(new Event('input'))
    boton('preparar').click()
    await vi.waitFor(() => expect(document.querySelector('[role="status"]')?.textContent).toBe(MENSAJES.copiadoConAdjunto.message))
  })

  it('un 401 olvida el token y vuelve a pedir conectar', async () => {
    mundo.gestionada = { panel_url: 'https://normativa.uji.es/panel' }
    mundo.local = { token: 'ggai_pat_revocado' }
    mundo.respuestas['/api/v1/agentes/catalogo'] = { status: 401, cuerpo: { detail: 'Invalid token' } }
    await cargar(mundo).pintar()
    await vi.waitFor(() => expect(document.body.textContent).toContain(MENSAJES.reconectar.message))
    expect(mundo.local.token).toBeUndefined()
  })

  it('desconectar borra el token', async () => {
    mundo.gestionada = { panel_url: 'https://normativa.uji.es/panel' }
    mundo.local = { token: 'ggai_pat_x' }
    await cargar(mundo).pintar()
    await vi.waitFor(() => expect(document.querySelectorAll('[data-agente]')).toHaveLength(2))
    const desconectar = [...document.querySelectorAll('button')].find((b) => b.textContent === MENSAJES.desconectar.message)!
    desconectar.click()
    await esperar()
    await vi.waitFor(() => expect(boton('conectar')).not.toBeNull())
    expect(mundo.local.token).toBeUndefined()
  })
})
