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
 * - en Gemini (#215) **inserta**, y si falla **copia y avisa de qué selector** a la plataforma; lee
 *   la respuesta sin bloquear el panel; sin Gemini delante, copia;
 * - **sólo actúa en la página del asistente**, con permiso opcional: ni `tabs` ni scripts fijos.
 */

const CODIGO =
  readFileSync(resolve(__dirname, '../../../extension/asistente.js'), 'utf-8') +
  '\n' +
  readFileSync(resolve(__dirname, '../../../extension/panel.js'), 'utf-8')
const ADAPTADOR = {
  asistente: 'gemini',
  nombre: 'Gemini',
  origen: 'https://gemini.google.com',
  version: 3,
  selectores: { cuadro: 'x', respuesta: 'y', texto: 'z', ocupado: 'aria-busy', fuentes: 'w' },
}
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
  /** La pestaña activa de Gemini, si la hay. */
  pestanaGemini: boolean
  /** Chrome no deja escribir en el portapapeles sin el panel enfocado: las veces que falla. */
  portapapelesSinFoco: number
  /** Para retener la respuesta de la consulta y ver el panel mientras espera. */
  consultaRetenida: Promise<void> | null
  inyectadas: { func: string; args: unknown[] }[]
  insercion: { ok: boolean; selector?: string }
  lectura: Promise<{ ok: boolean; texto?: string; selector?: string; motivo?: string }>
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
    adjunto: 'no',
    indice_sin_actualizar: false,
    modo_registro: 'validacion',
  },
  {
    id: 'a2',
    nombre: 'Revisión de facturas',
    unidad: 'Servicio de Contratación',
    finalidad: 'Revisar una factura.',
    responsable: 'Jefatura',
    version: 1,
    revision_vencida: true,
    adjunto: 'obligatorio',
    indice_sin_actualizar: false,
    modo_registro: 'incidencias',
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
        cuerpo: { agente: 'Becas', version: 2, prompt: 'PROMPT COMPUESTO', documentos: [], espera_adjunto: false, consulta_id: 'c1', modo_registro: 'validacion' },
      },
      '/api/v1/agentes/asistentes/gemini/adaptador': { status: 200, cuerpo: ADAPTADOR },
      '/api/v1/agentes/asistentes/gemini/fallos': { status: 204, cuerpo: null },
      '/api/v1/agentes/consultas/c1/respuesta': { status: 204, cuerpo: null },
      '/api/v1/agentes/consultas/c1/valoracion': { status: 204, cuerpo: null },
      '/api/v1/agentes/consultas/c2/valoracion': { status: 204, cuerpo: null },
      '/api/v1/agentes/motivos-de-informe': {
        status: 200,
        cuerpo: [
          { codigo: 'desactualizado', etiqueta: 'Información desactualizada' },
          { codigo: 'inventa', etiqueta: 'Se inventa cosas' },
        ],
      },
      '/api/v1/agentes/a2/consulta': {
        status: 200,
        cuerpo: { agente: 'Revisión de facturas', version: 1, prompt: 'OTRO', documentos: [], espera_adjunto: true, consulta_id: 'c2', modo_registro: 'incidencias' },
      },
    },
    copiado: [],
    flujo: [],
    vuelta: 'https://abc.chromiumapp.org/#token=ggai_pat_nuevo',
    permiso: true,
    pestanaGemini: true,
    portapapelesSinFoco: 0,
    consultaRetenida: null,
    inyectadas: [],
    insercion: { ok: true },
    lectura: Promise.resolve({ ok: true, texto: 'Respuesta de Gemini.', fuentes: [] }),
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
    tabs: {
      // La pestaña activa de la ventana del panel; la de la última ventana con foco puede ser la
      // de la conexión (visto en la prueba de verdad, 2026-10-04).
      query: async ({ url, currentWindow }: { url: string; currentWindow?: boolean }) =>
        mundo.pestanaGemini && currentWindow === true && url === 'https://gemini.google.com/*' ? [{ id: 7 }] : [],
    },
    scripting: {
      executeScript: async ({ target, func, args }: { target: { tabId: number }; func: { name: string }; args: unknown[] }) => {
        expect(target.tabId).toBe(7)
        mundo.inyectadas.push({ func: func.name, args })
        const resultado =
          func.name === 'contarRespuestas' ? 1 : func.name === 'insertarEnElAsistente' ? mundo.insercion : await mundo.lectura
        return [{ result: resultado }]
      },
    },
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
    if (ruta.endsWith('/consulta') && mundo.consultaRetenida) await mundo.consultaRetenida
    const r = mundo.respuestas[ruta] ?? { status: 404, cuerpo: { detail: 'no' } }
    return { status: r.status, ok: r.status < 400, json: async () => r.cuerpo }
  }
  const navigator = {
    clipboard: {
      writeText: async (t: string) => {
        if (mundo.portapapelesSinFoco > 0) {
          mundo.portapapelesSinFoco--
          throw new Error("Failed to execute 'writeText' on 'Clipboard': Document is not focused.")
        }
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

  it('sólo actúa en la página del asistente, y con permiso opcional: ni tabs ni scripts fijos', () => {
    expect(MANIFIESTO.permissions).toContain('scripting')
    expect(MANIFIESTO.permissions).not.toContain('tabs')
    expect(MANIFIESTO.host_permissions).toBeUndefined()
    expect(MANIFIESTO.content_scripts).toBeUndefined()
    expect(MANIFIESTO.optional_host_permissions).toContain('https://gemini.google.com/*')
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
      cuerpo: { consulta: '¿Plazo de la beca?', lengua: 'es', adjunta: false },
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

  describe('#215 — en Gemini', () => {
    async function preparado(m: Mundo, agente = 'a1') {
      m.gestionada = { panel_url: 'https://normativa.uji.es/panel' }
      m.local = { token: 'ggai_pat_x' }
      await cargar(m).pintar()
      await vi.waitFor(() => expect(document.getElementById('insertar')).not.toBeNull())
      ;(document.querySelector(`[data-agente="${agente}"] input`) as HTMLInputElement).click()
      const pregunta = document.getElementById('pregunta') as HTMLTextAreaElement
      pregunta.value = '¿Plazo?'
      pregunta.dispatchEvent(new Event('input'))
    }
    const estado = () => document.querySelector('[role="status"]')?.textContent
    const fallos = (m: Mundo) => m.peticiones.filter((p) => p.url.endsWith('/fallos')).map((p) => p.cuerpo)

    it('inserta el prompt que da la API, sin enviarlo, y luego lee la respuesta', async () => {
      let terminar: (v: { ok: boolean; texto: string }) => void = () => {}
      mundo.lectura = new Promise((r) => (terminar = r))
      await preparado(mundo)
      boton('insertar').click()
      await vi.waitFor(() => expect(estado()).toBe(MENSAJES.insertado.message))
      expect(mundo.inyectadas.map((i) => i.func)).toEqual(['contarRespuestas', 'insertarEnElAsistente', 'esperarRespuesta'])
      expect(mundo.inyectadas[1].args).toEqual([ADAPTADOR.selectores, 'PROMPT COMPUESTO'])
      // Espera la respuesta siguiente a las que ya había.
      expect(mundo.inyectadas[2].args.slice(0, 2)).toEqual([ADAPTADOR.selectores, 1])
      expect(mundo.copiado).toEqual([])
      // El panel no se queda bloqueado mientras la persona envía.
      expect(boton('insertar').disabled).toBe(false)
      terminar({ ok: true, texto: 'Respuesta de Gemini.' })
      await vi.waitFor(() => expect(document.getElementById('lectura')?.textContent).toBe(MENSAJES.respuestaLeida.message))
      expect(fallos(mundo)).toEqual([])
    })

    it('si no puede insertar, copia, lo dice y avisa a la plataforma de qué selector falló', async () => {
      mundo.insercion = { ok: false, selector: 'cuadro' }
      await preparado(mundo)
      boton('insertar').click()
      await vi.waitFor(() => expect(estado()).toBe(MENSAJES.insercionFallida.message))
      expect(mundo.copiado).toEqual(['PROMPT COMPUESTO'])
      expect(fallos(mundo)).toEqual([{ version: 3, selector: 'cuadro' }])
    })

    it('si no lee la respuesta por un selector, avisa; si es que no se envió, no', async () => {
      mundo.lectura = Promise.resolve({ ok: false, selector: 'texto' })
      await preparado(mundo)
      boton('insertar').click()
      await vi.waitFor(() => expect(document.getElementById('lectura')?.textContent).toBe(MENSAJES.respuestaNoLeida.message))
      await vi.waitFor(() => expect(fallos(mundo)).toEqual([{ version: 3, selector: 'texto' }]))

      const otro = mundoBase()
      otro.lectura = Promise.resolve({ ok: false, motivo: 'sin_respuesta' })
      document.body.innerHTML = '<main id="raiz"></main>'
      await preparado(otro)
      boton('insertar').click()
      await vi.waitFor(() => expect(document.getElementById('lectura')?.textContent).toBe(MENSAJES.respuestaNoLeida.message))
      expect(fallos(otro)).toEqual([])
    })

    it('sin Gemini en la pestaña activa, copia y dice que lo abra', async () => {
      mundo.pestanaGemini = false
      await preparado(mundo)
      boton('insertar').click()
      await vi.waitFor(() => expect(estado()).toBe(MENSAJES.abreElAsistente.message))
      expect(mundo.copiado).toEqual(['PROMPT COMPUESTO'])
      expect(mundo.inyectadas).toEqual([])
    })

    it('sin permiso sobre Gemini no pide nada a la API', async () => {
      mundo.permiso = false
      await preparado(mundo)
      boton('insertar').click()
      await vi.waitFor(() => expect(estado()).toBe(MENSAJES.sinPermisoAsistente.message))
      expect(mundo.peticiones.some((p) => p.url.endsWith('/consulta'))).toBe(false)
    })

    it('al agente que pide documento le recuerda adjuntarlo antes de enviar', async () => {
      await preparado(mundo, 'a2')
      boton('insertar').click()
      await vi.waitFor(() => expect(estado()).toBe(MENSAJES.insertadoConAdjunto.message))
    })

    it('mientras prepara el prompt lo dice, y no se puede pulsar otra vez', async () => {
      let soltar: () => void = () => {}
      mundo.consultaRetenida = new Promise((r) => (soltar = r))
      await preparado(mundo)
      boton('insertar').click()
      await vi.waitFor(() => expect(estado()).toBe(MENSAJES.preparando.message))
      expect(document.querySelector('[role="status"]')?.className).toBe('trabajando')
      expect(boton('insertar').disabled).toBe(true)
      expect(boton('preparar').disabled).toBe(true)
      soltar()
      await vi.waitFor(() => expect(estado()).toBe(MENSAJES.insertado.message))
    })

    it('si Chrome no deja copiar sin foco, enseña el prompt con su botón de copiar', async () => {
      // La prueba de verdad: «Document is not focused» tras esperar a la plataforma.
      mundo.pestanaGemini = false
      mundo.portapapelesSinFoco = 1
      await preparado(mundo)
      boton('insertar').click()
      await vi.waitFor(() => expect(estado()).toBe(MENSAJES.sinAsistente.message))
      expect((document.getElementById('prompt-a-mano') as HTMLTextAreaElement).value).toBe('PROMPT COMPUESTO')
      expect(document.body.textContent).not.toContain('Document is not focused')
      boton('copiar-a-mano').click()
      await vi.waitFor(() => expect(mundo.copiado).toEqual(['PROMPT COMPUESTO']))
      expect(estado()).toBe(MENSAJES.copiado.message)
      expect(document.getElementById('prompt-a-mano')).toBeNull()
    })

    it('copiar a secas también se recupera si Chrome no deja', async () => {
      mundo.portapapelesSinFoco = 1
      await preparado(mundo)
      boton('preparar').click()
      await vi.waitFor(() => expect(estado()).toBe(MENSAJES.preparado.message))
      expect(document.getElementById('copiar-a-mano')).not.toBeNull()
    })

    it('sin adaptador no hay botón de insertar, y copiar sigue siendo lo principal', async () => {
      mundo.respuestas['/api/v1/agentes/asistentes/gemini/adaptador'] = { status: 404, cuerpo: { detail: 'no' } }
      mundo.gestionada = { panel_url: 'https://normativa.uji.es/panel' }
      mundo.local = { token: 'ggai_pat_x' }
      await cargar(mundo).pintar()
      await vi.waitFor(() => expect(document.getElementById('preparar')).not.toBeNull())
      expect(document.getElementById('insertar')).toBeNull()
      expect(boton('preparar').className).toBe('principal')
    })
  })

  describe('#216 — la conversación', () => {
    async function preparado216(m: Mundo, agente = 'a1') {
      m.gestionada = { panel_url: 'https://normativa.uji.es/panel' }
      m.local = { token: 'ggai_pat_x' }
      await cargar(m).pintar()
      await vi.waitFor(() => expect(document.getElementById('insertar')).not.toBeNull())
      ;(document.querySelector(`[data-agente="${agente}"] input`) as HTMLInputElement).click()
      const pregunta = document.getElementById('pregunta') as HTMLTextAreaElement
      pregunta.value = '¿Plazo de la beca?'
      pregunta.dispatchEvent(new Event('input'))
    }
    const enviadas = (m: Mundo, final: string) => m.peticiones.filter((p) => p.url.endsWith(final)).map((p) => p.cuerpo)

    it('la tarjeta del agente en validación lo dice; la del que está en incidencias, no', async () => {
      mundo.gestionada = { panel_url: 'https://normativa.uji.es/panel' }
      mundo.local = { token: 'ggai_pat_x' }
      await cargar(mundo).pintar()
      await vi.waitFor(() => expect(document.querySelectorAll('[data-agente]')).toHaveLength(2))
      expect(document.querySelector('[data-agente="a1"]')?.textContent).toContain(MENSAJES.enValidacion.message)
      expect(document.querySelector('[data-agente="a2"]')?.textContent).not.toContain(MENSAJES.enValidacion.message)
    })

    it('en validación manda a la plataforma la respuesta que leyó, con sus fuentes', async () => {
      mundo.lectura = Promise.resolve({ ok: true, texto: 'Hasta el 30 de octubre.', fuentes: ['https://drive.google.com/file/d/1'] } as never)
      await preparado216(mundo)
      boton('insertar').click()
      await vi.waitFor(() =>
        expect(enviadas(mundo, '/consultas/c1/respuesta')).toEqual([{ texto: 'Hasta el 30 de octubre.', fuentes: ['https://drive.google.com/file/d/1'] }]),
      )
      expect(document.body.textContent).toContain(MENSAJES.seGuardaLaConversacion.message)
    })

    it('si no pudo leerla, manda por qué: cuenta la cobertura', async () => {
      mundo.lectura = Promise.resolve({ ok: false, selector: 'texto' })
      await preparado216(mundo)
      boton('insertar').click()
      await vi.waitFor(() => expect(enviadas(mundo, '/consultas/c1/respuesta')).toEqual([{ no_capturada: 'selector' }]))
    })

    it('en incidencias no manda la respuesta de cada consulta', async () => {
      await preparado216(mundo, 'a2')
      boton('insertar').click()
      await vi.waitFor(() => expect(document.getElementById('lectura')?.textContent).toBe(MENSAJES.respuestaLeida.message))
      expect(enviadas(mundo, '/respuesta')).toEqual([])
      expect(document.body.textContent).not.toContain(MENSAJES.seGuardaLaConversacion.message)
    })

    it('👍 manda la valoración buena', async () => {
      await preparado216(mundo)
      boton('insertar').click()
      await vi.waitFor(() => expect(document.getElementById('util')).not.toBeNull())
      boton('util').click()
      await vi.waitFor(() => expect(enviadas(mundo, '/consultas/c1/valoracion')).toEqual([{ puntuacion: 1 }]))
      await vi.waitFor(() => expect(document.getElementById('estado-valoracion')?.textContent).toBe(MENSAJES.gracias.message))
    })

    it('👎 pide el motivo de los que sirve la plataforma y manda el informe con la pregunta y la respuesta', async () => {
      mundo.lectura = Promise.resolve({ ok: true, texto: 'Respuesta de Gemini.', fuentes: [] })
      await preparado216(mundo, 'a2')
      boton('insertar').click()
      await vi.waitFor(() => expect(document.getElementById('lectura')?.textContent).toBe(MENSAJES.respuestaLeida.message))
      boton('inutil').click()
      await vi.waitFor(() => expect(document.getElementById('motivo')).not.toBeNull())
      const motivo = document.getElementById('motivo') as HTMLSelectElement
      expect([...motivo.options].map((o) => o.textContent)).toEqual(['Información desactualizada', 'Se inventa cosas'])
      motivo.value = 'inventa'
      ;(document.getElementById('comentario') as HTMLTextAreaElement).value = 'Cita una norma que no existe'
      boton('enviar-informe').click()
      await vi.waitFor(() =>
        expect(enviadas(mundo, '/consultas/c2/valoracion')).toEqual([
          { puntuacion: -1, motivo: 'inventa', comentario: 'Cita una norma que no existe', pregunta: '¿Plazo de la beca?', respuesta: 'Respuesta de Gemini.' },
        ]),
      )
      await vi.waitFor(() => expect(document.getElementById('estado-valoracion')?.textContent).toBe(MENSAJES.informeEnviado.message))
    })

    it('con copiar a secas también se puede valorar', async () => {
      await preparado216(mundo)
      boton('preparar').click()
      await vi.waitFor(() => expect(document.getElementById('util')).not.toBeNull())
    })
  })

  describe('#218 — el adjunto opcional', () => {
    function conOpcional(m: Mundo) {
      const opcional = { ...AGENTES[0], id: 'a3', nombre: 'Pliegos', adjunto: 'opcional' }
      m.respuestas['/api/v1/agentes/catalogo'] = { status: 200, cuerpo: [opcional] }
      m.respuestas['/api/v1/agentes/a3/consulta'] = m.respuestas['/api/v1/agentes/a1/consulta']
      m.gestionada = { panel_url: 'https://normativa.uji.es/panel' }
      m.local = { token: 'ggai_pat_x' }
    }
    async function elegir() {
      await vi.waitFor(() => expect(document.querySelectorAll('[data-agente]')).toHaveLength(1))
      ;(document.querySelector('[data-agente="a3"] input') as HTMLInputElement).click()
      const pregunta = document.getElementById('pregunta') as HTMLTextAreaElement
      pregunta.value = 'Revisa este pliego'
      pregunta.dispatchEvent(new Event('input'))
    }
    const casilla = () => document.getElementById('adjunta') as HTMLInputElement

    it('la tarjeta lo dice y la casilla aparece sólo al elegirlo', async () => {
      conOpcional(mundo)
      await cargar(mundo).pintar()
      await vi.waitFor(() => expect(document.querySelector('[data-agente="a3"]')?.textContent).toContain(MENSAJES.adjuntoOpcional.message))
      expect((casilla().parentElement as HTMLElement).hidden).toBe(true)
      await elegir()
      expect((casilla().parentElement as HTMLElement).hidden).toBe(false)
    })

    it('marcada, manda que adjunta y pide describir el documento', async () => {
      conOpcional(mundo)
      await cargar(mundo).pintar()
      await elegir()
      casilla().click()
      expect(document.body.textContent).toContain(MENSAJES.describeElAdjunto.message)
      boton('preparar').click()
      await vi.waitFor(() =>
        expect(mundo.peticiones.find((p) => p.url.endsWith('/a3/consulta'))?.cuerpo).toMatchObject({ adjunta: true }),
      )
    })

    it('sin marcar, no adjunta', async () => {
      conOpcional(mundo)
      await cargar(mundo).pintar()
      await elegir()
      boton('preparar').click()
      await vi.waitFor(() =>
        expect(mundo.peticiones.find((p) => p.url.endsWith('/a3/consulta'))?.cuerpo).toMatchObject({ adjunta: false }),
      )
    })
  })

  describe('#219 — los datos de la consulta', () => {
    const PLIEGOS = {
      ...AGENTES[0],
      id: 'a4',
      nombre: 'Pliegos',
      indicaciones: 'Indica el tipo de contrato y el CPV.',
      datos_consulta: [
        { clave: 'tipo_de_contrato', etiqueta: 'Tipo de contrato', tipo: 'opciones', opciones: ['Obras', 'Servicios'], obligatorio: true, ayuda: null, columna: null, prefijo: false },
        { clave: 'codigo_cpv', etiqueta: 'Código CPV', tipo: 'texto', opciones: [], obligatorio: false, ayuda: 'Ocho cifras', columna: null, prefijo: true },
      ],
    }
    async function conPliegos(m: Mundo) {
      m.respuestas['/api/v1/agentes/catalogo'] = { status: 200, cuerpo: [PLIEGOS] }
      m.respuestas['/api/v1/agentes/a4/consulta'] = m.respuestas['/api/v1/agentes/a1/consulta']
      m.gestionada = { panel_url: 'https://normativa.uji.es/panel' }
      m.local = { token: 'ggai_pat_x' }
      await cargar(m).pintar()
      await vi.waitFor(() => expect(document.querySelectorAll('[data-agente]')).toHaveLength(1))
      ;(document.querySelector('[data-agente="a4"] input') as HTMLInputElement).click()
      const pregunta = document.getElementById('pregunta') as HTMLTextAreaElement
      pregunta.value = '¿Qué solvencia pido?'
      pregunta.dispatchEvent(new Event('input'))
    }
    const tipo = () => document.getElementById('dato_tipo_de_contrato') as HTMLSelectElement
    const cpv = () => document.getElementById('dato_codigo_cpv') as HTMLInputElement

    it('pinta lo que declara el agente, con indicaciones y ayuda', async () => {
      await conPliegos(mundo)
      expect(document.getElementById('indicaciones')?.textContent).toBe('Indica el tipo de contrato y el CPV.')
      expect([...tipo().options].map((o) => o.value)).toEqual(['', 'Obras', 'Servicios'])
      expect(document.querySelector('label[for="dato_tipo_de_contrato"]')?.textContent).toBe('Tipo de contrato *')
      expect(document.body.textContent).toContain('Ocho cifras')
    })

    it('sin el obligatorio no se prepara; con él, manda los datos por su clave', async () => {
      await conPliegos(mundo)
      expect(boton('preparar').disabled).toBe(true)
      tipo().value = 'Servicios'
      tipo().dispatchEvent(new Event('change'))
      cpv().value = '79341000'
      cpv().dispatchEvent(new Event('input'))
      expect(boton('preparar').disabled).toBe(false)
      boton('preparar').click()
      await vi.waitFor(() =>
        expect(mundo.peticiones.find((p) => p.url.endsWith('/a4/consulta'))?.cuerpo).toMatchObject({
          datos: { tipo_de_contrato: 'Servicios', codigo_cpv: '79341000' },
        }),
      )
    })

    it('un dato vacío no se manda', async () => {
      await conPliegos(mundo)
      tipo().value = 'Obras'
      tipo().dispatchEvent(new Event('change'))
      boton('preparar').click()
      await vi.waitFor(() =>
        expect((mundo.peticiones.find((p) => p.url.endsWith('/a4/consulta'))?.cuerpo as { datos: unknown }).datos).toEqual({
          tipo_de_contrato: 'Obras',
        }),
      )
    })
  })
})

