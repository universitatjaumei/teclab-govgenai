import { describe, it, expect, beforeEach } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

/**
 * #174 — el guion de Apps Script que mantiene el índice de un agente.
 *
 * Corre en Google, con la cuenta de la unidad, y aquí no hay Apps Script: se carga el `.gs` con
 * dobles de los servicios que usa (`DriveApp`, `SpreadsheetApp`, `UrlFetchApp`…) y se comprueba lo
 * que decide. Vive en el paquete del servidor porque la plataforma lo sirve; se prueba aquí porque
 * aquí hay un motor de JavaScript en CI.
 *
 * Lo que fija:
 * - **sólo resume lo nuevo o cambiado**, y **no regenera solo** al cambiar la versión del prompt;
 * - **para antes del límite de tiempo** y deja hecho lo que hizo: la próxima pasada sigue;
 * - **manda el estado completo** con la forma que espera la API, y cuántos documentos hay;
 * - **respeta lo que la unidad escribe a mano** en la hoja: la vigencia y la fecha de revisión.
 */

const CODIGO = readFileSync(
  resolve(__dirname, '../../../server/app/modules/agentes/guion/indice_desde_drive.gs'),
  'utf-8',
)

type Fichero = { id: string; nombre: string; mime: string; modificado: string; tamano?: number }

interface Mundo {
  ficheros: Fichero[]
  hoja: unknown[][]
  propiedades: Record<string, string>
  peticiones: { url: string; metodo: string; cuerpo: unknown; autorizacion?: string }[]
  resumidos: string[]
  reloj: number
  /** Cuánto avanza el reloj con cada resumen, para probar el límite de tiempo. */
  msPorResumen: number
  promptCaido?: boolean
}

function cargar(mundo: Mundo) {
  const hojaDeCalculo = {
    getSheets: () => [hoja],
  }
  const hoja = {
    getDataRange: () => ({ getValues: () => mundo.hoja.map((f) => [...f]) }),
    clearContents: () => {
      mundo.hoja = []
    },
    getRange: (_f: number, _c: number, filas: number, columnas: number) => ({
      setValues: (valores: unknown[][]) => {
        expect(valores.length).toBe(filas)
        expect(valores[0]?.length ?? columnas).toBe(columnas)
        mundo.hoja = valores.map((v) => [...v])
      },
    }),
  }
  const globales = {
    PropertiesService: {
      getScriptProperties: () => ({
        getProperty: (k: string) => mundo.propiedades[k] ?? null,
        setProperty: (k: string, v: string) => {
          mundo.propiedades[k] = v
        },
      }),
    },
    DriveApp: {
      getFolderById: () => ({
        getFiles: () => {
          let i = 0
          return {
            hasNext: () => i < mundo.ficheros.length,
            next: () => {
              const f = mundo.ficheros[i++]
              return {
                getId: () => f.id,
                getName: () => f.nombre,
                getMimeType: () => f.mime,
                getLastUpdated: () => new Date(f.modificado),
                getSize: () => f.tamano ?? 1000,
                getUrl: () => `https://drive.google.com/file/d/${f.id}/view`,
                getBlob: () => ({ getBytes: () => [1, 2, 3] }),
              }
            },
          }
        },
      }),
    },
    SpreadsheetApp: { openById: () => hojaDeCalculo },
    UrlFetchApp: {
      fetch: (url: string, opciones: { method?: string; payload?: string; headers?: Record<string, string> }) => {
        const metodo = (opciones.method ?? 'get').toLowerCase()
        const cuerpo = opciones.payload ? JSON.parse(opciones.payload) : null
        mundo.peticiones.push({ url, metodo, cuerpo, autorizacion: opciones.headers?.Authorization })
        if (url.includes('/prompt-de-resumen')) {
          if (mundo.promptCaido) return { getResponseCode: () => 503, getContentText: () => 'caído' }
          return {
            getResponseCode: () => 200,
            getContentText: () => JSON.stringify({ version: 'resumen-v2', texto: 'Resume esto.' }),
          }
        }
        if (url.includes(':generateContent')) {
          mundo.reloj += mundo.msPorResumen
          const id = String(cuerpo.contents[0].parts.find((p: { text?: string }) => p.text?.startsWith('Documento:'))?.text ?? '')
          mundo.resumidos.push(id)
          return {
            getResponseCode: () => 200,
            getContentText: () =>
              JSON.stringify({ candidates: [{ content: { parts: [{ text: `Resumen de ${id}` }] } }] }),
          }
        }
        if (url.includes('/export?')) {
          return { getResponseCode: () => 200, getContentText: () => 'texto del documento' }
        }
        if (url.includes('/indice')) {
          return { getResponseCode: () => 200, getContentText: () => '{"nuevas":0}' }
        }
        throw new Error(`petición no esperada: ${url}`)
      },
    },
    ScriptApp: {
      getOAuthToken: () => 'oauth',
      getProjectTriggers: () => [],
      deleteTrigger: () => undefined,
      newTrigger: () => ({ timeBased: () => ({ everyDays: () => ({ atHour: () => ({ create: () => undefined }) }) }) }),
    },
    Utilities: {
      base64Encode: () => 'AQID',
      // Como en Apps Script: la fecha en la zona que se le pide, no en UTC.
      formatDate: (fecha: Date, zona: string) =>
        new Intl.DateTimeFormat('sv-SE', { timeZone: zona, year: 'numeric', month: '2-digit', day: '2-digit' }).format(fecha),
    },
    Session: { getScriptTimeZone: () => 'Europe/Madrid' },
    Logger: { log: () => undefined },
    // El reloj lo lleva el test: `Date.now()` es lo único que el guion mira para el límite.
    Date: class extends Date {
      static now() {
        return mundo.reloj
      }
    },
  }
  const nombres = Object.keys(globales)
  const fabrica = new Function(
    ...nombres,
    `${CODIGO}\nreturn { actualizarIndice, planificar, componerIndice, regenerarResumenes, VERSION_DEL_GUION };`,
  )
  return fabrica(...nombres.map((n) => (globales as Record<string, unknown>)[n]))
}

const PROPIEDADES = {
  PLATAFORMA_URL: 'https://plataforma.example/panel',
  AGENTE_ID: 'agente-1',
  TOKEN: 'pat_x_y',
  CARPETA_ID: 'carpeta',
  HOJA_ID: 'hoja',
  PROYECTO_GCP: 'proyecto',
}

let mundo: Mundo

beforeEach(() => {
  mundo = {
    ficheros: [
      { id: 'a', nombre: 'Instrucción.pdf', mime: 'application/pdf', modificado: '2026-09-01T10:00:00Z' },
      { id: 'b', nombre: 'Guía', mime: 'application/vnd.google-apps.document', modificado: '2026-09-02T10:00:00Z' },
      { id: 'c', nombre: 'Foto.jpg', mime: 'image/jpeg', modificado: '2026-09-03T10:00:00Z' },
    ],
    hoja: [],
    propiedades: { ...PROPIEDADES },
    peticiones: [],
    resumidos: [],
    reloj: 0,
    msPorResumen: 1000,
  }
})

function laCarga() {
  return mundo.peticiones.find((p) => p.url.endsWith('/agentes/agente-1/indice') && p.metodo === 'put')
}

describe('guion del índice — la primera pasada', () => {
  it('resume lo que sabe leer y manda el estado completo con cuántos documentos hay', () => {
    cargar(mundo).actualizarIndice()

    expect(mundo.resumidos.sort()).toEqual(['Documento: Guía', 'Documento: Instrucción.pdf'])
    const carga = laCarga()!
    expect(carga.url).toBe('https://plataforma.example/panel/api/v1/agentes/agente-1/indice')
    const cuerpo = carga.cuerpo as { fichas: Record<string, unknown>[]; documentos_en_carpeta: number }
    // La foto no se sabe resumir: no tiene ficha, pero cuenta, y la plataforma dirá que falta.
    expect(cuerpo.documentos_en_carpeta).toBe(3)
    expect(cuerpo.fichas).toHaveLength(2)
    expect(cuerpo.fichas[0]).toEqual({
      url: 'https://drive.google.com/file/d/a/view',
      titulo: 'Instrucción.pdf',
      resumen: 'Resumen de Documento: Instrucción.pdf',
      vigente: true,
      version_prompt_resumen: 'resumen-v2',
      modelo_resumen: 'gemini-2.5-flash',
    })
  })

  it('a la plataforma va con el token del guion, y a Vertex con la cuenta de la unidad', () => {
    cargar(mundo).actualizarIndice()
    const plataforma = mundo.peticiones.filter((p) => p.url.startsWith('https://plataforma.example'))
    expect(plataforma.length).toBeGreaterThan(0)
    expect(plataforma.every((p) => p.autorizacion === 'Bearer pat_x_y')).toBe(true)
    const vertex = mundo.peticiones.filter((p) => p.url.includes(':generateContent'))
    expect(vertex.every((p) => p.autorizacion === 'Bearer oauth')).toBe(true)
    expect(vertex[0].url).toContain('europe-southwest1-aiplatform.googleapis.com')
  })
})

describe('guion del índice — las pasadas siguientes', () => {
  it('no vuelve a resumir lo que no ha cambiado, pero sigue mandando el índice', () => {
    cargar(mundo).actualizarIndice()
    mundo.resumidos = []
    mundo.peticiones = []
    cargar(mundo).actualizarIndice()

    expect(mundo.resumidos).toEqual([])
    expect((laCarga()!.cuerpo as { fichas: unknown[] }).fichas).toHaveLength(2)
  })

  it('resume otra vez el documento que ha cambiado', () => {
    cargar(mundo).actualizarIndice()
    mundo.resumidos = []
    mundo.ficheros[0].modificado = '2026-10-01T10:00:00Z'
    cargar(mundo).actualizarIndice()
    expect(mundo.resumidos).toEqual(['Documento: Instrucción.pdf'])
  })

  it('lo que se borra de la carpeta sale del índice', () => {
    cargar(mundo).actualizarIndice()
    mundo.ficheros = mundo.ficheros.filter((f) => f.id !== 'b')
    mundo.peticiones = []
    cargar(mundo).actualizarIndice()
    const cuerpo = laCarga()!.cuerpo as { fichas: { titulo: string }[]; documentos_en_carpeta: number }
    expect(cuerpo.fichas.map((f) => f.titulo)).toEqual(['Instrucción.pdf'])
    expect(cuerpo.documentos_en_carpeta).toBe(2)
  })

  it('respeta la vigencia y la fecha que la unidad escribe a mano en la hoja', () => {
    const guion = cargar(mundo)
    guion.actualizarIndice()
    const cabecera = mundo.hoja[0] as string[]
    const fila = mundo.hoja.findIndex((f) => f[cabecera.indexOf('id_fichero')] === 'a')
    mundo.hoja[fila][cabecera.indexOf('vigente')] = 'no'
    // Medianoche del 31 en Madrid, que en UTC es aún el 30: lo que guarda una celda de fecha.
    mundo.hoja[fila][cabecera.indexOf('revision_prevista_en')] = new Date('2027-01-30T23:00:00Z')
    mundo.peticiones = []
    cargar(mundo).actualizarIndice()

    const ficha = (laCarga()!.cuerpo as { fichas: Record<string, unknown>[] }).fichas.find(
      (f) => f.titulo === 'Instrucción.pdf',
    )!
    expect(ficha.vigente).toBe(false)
    expect(ficha.revision_prevista_en).toBe('2027-01-31')
  })
})

describe('guion del índice — el prompt de resumen', () => {
  it('al cambiar la versión del prompt no regenera solo: es decisión de la unidad', () => {
    cargar(mundo).actualizarIndice()
    mundo.resumidos = []
    mundo.propiedades.PROMPT_CACHEADO = JSON.stringify({ version: 'resumen-v1', texto: 'viejo' })
    cargar(mundo).actualizarIndice()
    expect(mundo.resumidos).toEqual([])
  })

  it('regenerar lo desfasado es una pasada deliberada', () => {
    cargar(mundo).actualizarIndice()
    const cabecera = mundo.hoja[0] as string[]
    mundo.hoja[1][cabecera.indexOf('version_prompt_resumen')] = 'resumen-v1'
    mundo.resumidos = []
    cargar(mundo).regenerarResumenes()
    expect(mundo.resumidos).toHaveLength(1)
  })

  it('si la plataforma no responde, usa el último prompt guardado y escribe esa versión', () => {
    mundo.propiedades.PROMPT_CACHEADO = JSON.stringify({ version: 'resumen-v1', texto: 'Guardado.' })
    mundo.promptCaido = true
    cargar(mundo).actualizarIndice()
    const fichas = (laCarga()!.cuerpo as { fichas: { version_prompt_resumen: string }[] }).fichas
    expect(fichas.every((f) => f.version_prompt_resumen === 'resumen-v1')).toBe(true)
  })
})

describe('guion del índice — el límite de tiempo', () => {
  it('para antes del límite, deja escrito lo hecho y la siguiente pasada sigue', () => {
    mundo.msPorResumen = 3 * 60 * 1000 // cada resumen se come tres minutos
    cargar(mundo).actualizarIndice()
    expect(mundo.resumidos).toHaveLength(2) // el segundo pasa del límite y es el último que empieza

    for (const id of ['d', 'e', 'f']) {
      mundo.ficheros.push({ id, nombre: `${id}.pdf`, mime: 'application/pdf', modificado: '2026-09-05T10:00:00Z' })
    }
    mundo.resumidos = []
    mundo.peticiones = []
    mundo.reloj = 0
    cargar(mundo).actualizarIndice()
    // Tres nuevos a tres minutos cada uno: empiezan dos (a 0 y a 3 minutos); el tercero ya no.
    expect(mundo.resumidos).toHaveLength(2)
    // Y aun así manda lo que tiene: un índice a medias es mejor que ninguno.
    expect((laCarga()!.cuerpo as { fichas: unknown[] }).fichas).toHaveLength(4)

    mundo.resumidos = []
    mundo.reloj = 0
    cargar(mundo).actualizarIndice()
    expect(mundo.resumidos).toHaveLength(1)
  })
})
