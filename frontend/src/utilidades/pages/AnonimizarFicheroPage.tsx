import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { descargarConAutorizacion } from '@/shared/api/download'
import { conLaOrganizacion } from '@/utilidades/conLaOrganizacion'
import { useOrganizacionElegida } from '@/shared/organizacion/useOrganizacionElegida'
import type { AnalisisDeFichero, VistaPrevia } from '@/shared/api/generated/model'
import {
  useAnalizarFicheroParaAnonimizar,
  useVistaPreviaAnonimizacion,
} from '@/shared/api/generated/utilidades/utilidades'
import { mensajeDelFallo } from '@/utilidades/mensajeDelFallo'

type Regla = { tipo: string; modo: string }

/**
 * Anonimizar un fichero para compartirlo (UTL.2, issue #191).
 *
 * Subir → analizar → ajustar la regla de cada columna → ver cómo queda → descargar.
 *
 * **Lo que se puede elegir lo dice el servidor**: los tipos y las reglas de cada tipo llegan en el
 * análisis (`tipos`), y esta pantalla los pinta sin conocerlos. Qué es un DNI, qué admite un nombre
 * o qué hace el modo AEPD no está aquí.
 *
 * **La descarga exige haber visto la vista previa de las reglas actuales**, y confirmarlo. Cambiar
 * una regla después invalida la confirmación. El servidor lo exige igualmente; aquí se evita
 * pedirle algo que va a rechazar.
 */
export function AnonimizarFicheroPage() {
  const { t } = useTranslation('utilidades')
  // La descarga se anota en el registro de una organización: la elegida, si no es de una sola.
  const { elegida } = useOrganizacionElegida()
  const [fichero, setFichero] = useState<File | null>(null)
  const [analisis, setAnalisis] = useState<AnalisisDeFichero | null>(null)
  const [reglas, setReglas] = useState<Record<string, Regla>>({})
  const [vista, setVista] = useState<VistaPrevia | null>(null)
  const [vistaAlDia, setVistaAlDia] = useState(false)
  const [revisado, setRevisado] = useState(false)
  const [descargando, setDescargando] = useState(false)
  const [error, setError] = useState('')

  const { mutate: analizar, isPending: analizando } = useAnalizarFicheroParaAnonimizar()
  const { mutate: previsualizar, isPending: generando } = useVistaPreviaAnonimizacion()

  function elegir(nuevo: File | undefined) {
    setError('')
    setAnalisis(null)
    setVista(null)
    setVistaAlDia(false)
    setRevisado(false)
    if (!nuevo) return
    setFichero(nuevo)
    analizar(
      { data: { file: nuevo } },
      {
        onSuccess: (resultado) => {
          setAnalisis(resultado)
          setReglas(
            Object.fromEntries(resultado.columnas.map((c) => [c.columna, { tipo: c.tipo, modo: c.modo }])),
          )
        },
        onError: (fallo) => setError(mensajeDelFallo(fallo, t('error'))),
      },
    )
  }

  function cambiarRegla(columna: string, cambio: Partial<Regla>) {
    setReglas((actuales) => {
      const anterior = actuales[columna]
      const siguiente = { ...anterior, ...cambio }
      // Al cambiar el tipo, la regla pasa a la primera que ese tipo admite: la de antes puede
      // no valer (AEPD no es una regla de un correo).
      if (cambio.tipo && analisis) {
        siguiente.modo = analisis.tipos[cambio.tipo]?.[0] ?? siguiente.modo
      }
      return { ...actuales, [columna]: siguiente }
    })
    setVistaAlDia(false)
    setRevisado(false)
  }

  function reglasComoJson() {
    return JSON.stringify(reglas)
  }

  function verComoQueda() {
    if (!fichero || !analisis) return
    setError('')
    previsualizar(
      { data: { file: fichero, reglas: reglasComoJson(), semilla: analisis.semilla } },
      {
        onSuccess: (resultado) => {
          setVista(resultado)
          setVistaAlDia(true)
        },
        onError: (fallo) => setError(mensajeDelFallo(fallo, t('error'))),
      },
    )
  }

  async function descargar() {
    if (!fichero || !analisis || !revisado || !vistaAlDia) return
    setError('')
    const cuerpo = new FormData()
    cuerpo.append('file', fichero)
    cuerpo.append('reglas', reglasComoJson())
    cuerpo.append('semilla', String(analisis.semilla))
    cuerpo.append('revisado', 'true')
    setDescargando(true)
    try {
      await descargarConAutorizacion(
        conLaOrganizacion('/api/v1/utilidades/anonimizar/descargar', elegida),
        `anonimizado.${analisis.formato}`,
        cuerpo,
      )
    } catch (fallo) {
      setError(mensajeDelFallo(fallo, t('error')))
    } finally {
      setDescargando(false)
    }
  }

  const tipos = analisis ? Object.keys(analisis.tipos) : []

  return (
    <div className="space-y-4 max-w-5xl">
      <header>
        <h2 className="text-lg font-semibold">{t('anon.titulo')}</h2>
        <p className="text-sm text-muted-foreground">{t('anon.descripcion')}</p>
      </header>

      <div role="note" className="rounded-md border border-amber-500/60 bg-amber-50 dark:bg-amber-950/30 p-3 text-sm space-y-1">
        <p className="font-medium">{t('anon.aviso_titulo')}</p>
        <p>{t('anon.aviso')}</p>
      </div>

      <label
        htmlFor="anon-fichero"
        data-testid="zona-anon"
        className="flex flex-col items-center justify-center gap-1 w-full px-4 py-6 border-2 border-dashed border-input rounded-md cursor-pointer text-center hover:border-primary hover:bg-accent/40 transition-colors"
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => {
          e.preventDefault()
          elegir(e.dataTransfer.files?.[0])
        }}
      >
        <span className="text-sm font-medium">{fichero ? fichero.name : t('anon.soltar')}</span>
        <span className="text-xs text-muted-foreground">{t('anon.formatos')}</span>
      </label>
      <input
        id="anon-fichero"
        data-testid="input-anon"
        type="file"
        accept=".csv,.xlsx"
        onChange={(e) => {
          elegir(e.target.files?.[0])
          e.target.value = ''
        }}
        className="sr-only"
      />

      {analizando && <p role="status" className="text-sm text-muted-foreground">{t('anon.analizando')}</p>}

      {analisis && (
        <section className="space-y-3">
          <p className="text-sm">{t('anon.resumen', { filas: analisis.filas, formato: analisis.formato.toUpperCase() })}</p>
          {analisis.hojas > 1 && (
            <p role="alert" className="text-sm text-amber-700 dark:text-amber-400">
              {t('anon.hojas_aviso', { hojas: analisis.hojas })}
            </p>
          )}

          <div className="overflow-x-auto">
            <table className="w-full text-sm border">
              <thead className="bg-muted/50">
                <tr>
                  <th className="text-left p-2">{t('anon.col_columna')}</th>
                  <th className="text-left p-2">{t('anon.col_ejemplos')}</th>
                  <th className="text-left p-2">{t('anon.col_tipo')}</th>
                  <th className="text-left p-2">{t('anon.col_regla')}</th>
                  <th className="text-right p-2">{t('anon.col_confianza')}</th>
                </tr>
              </thead>
              <tbody>
                {analisis.columnas.map((c) => {
                  const regla = reglas[c.columna]
                  const modos = analisis.tipos[regla?.tipo ?? c.tipo] ?? []
                  return (
                    <tr key={c.columna} className="border-t align-top">
                      <td className="p-2 font-medium">{c.columna}</td>
                      <td className="p-2 text-xs text-muted-foreground">{c.ejemplos.join(' · ')}</td>
                      <td className="p-2">
                        <select
                          aria-label={`${t('anon.col_tipo')}: ${c.columna}`}
                          value={regla?.tipo}
                          onChange={(e) => cambiarRegla(c.columna, { tipo: e.target.value })}
                          className="rounded-md border border-input bg-background px-2 py-1 text-sm"
                        >
                          {tipos.map((tipo) => (
                            <option key={tipo} value={tipo}>
                              {t(`anon.tipo.${tipo}`, { defaultValue: tipo })}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td className="p-2">
                        <select
                          aria-label={`${t('anon.col_regla')}: ${c.columna}`}
                          value={regla?.modo}
                          onChange={(e) => cambiarRegla(c.columna, { modo: e.target.value })}
                          className="rounded-md border border-input bg-background px-2 py-1 text-sm"
                        >
                          {modos.map((modo) => (
                            <option key={modo} value={modo}>
                              {t(`anon.modo.${modo}`, { defaultValue: modo })}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td className="p-2 text-right tabular-nums">{Math.round(c.confianza * 100)} %</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>

          <button
            type="button"
            onClick={verComoQueda}
            disabled={generando}
            className="rounded-md border px-4 py-2 text-sm font-medium hover:bg-accent disabled:opacity-50"
          >
            {generando ? t('anon.generando') : t('anon.vista_previa')}
          </button>
        </section>
      )}

      {vista && (
        <section className="space-y-3" aria-label={t('anon.vista_previa')}>
          {!vistaAlDia && (
            <p role="alert" className="text-sm text-amber-700 dark:text-amber-400">{t('anon.reglas_cambiadas')}</p>
          )}
          <p className="text-xs text-muted-foreground">{t('anon.filas_de_muestra', { n: vista.despues.length })}</p>
          <div className="grid gap-3 lg:grid-cols-2">
            {(['antes', 'despues'] as const).map((lado) => (
              <div key={lado} className="overflow-x-auto">
                <p className="text-sm font-medium mb-1">{t(`anon.${lado}`)}</p>
                <table className="w-full text-xs border" data-testid={`vista-${lado}`}>
                  <thead className="bg-muted/50">
                    <tr>
                      {vista.columnas.map((col) => (
                        <th key={col} className="text-left p-1">{col}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {vista[lado].map((fila, i) => (
                      <tr key={i} className="border-t">
                        {fila.map((celda, j) => (
                          <td
                            key={j}
                            className={`p-1 ${
                              lado === 'despues' && celda !== vista.antes[i]?.[j] ? 'bg-green-50 dark:bg-green-950/30' : ''
                            }`}
                          >
                            {celda}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ))}
          </div>

          <label className="flex items-start gap-2 text-sm">
            <input
              type="checkbox"
              checked={revisado}
              disabled={!vistaAlDia}
              onChange={(e) => setRevisado(e.target.checked)}
              className="mt-0.5"
            />
            {t('anon.revisado')}
          </label>
          <button
            type="button"
            onClick={() => void descargar()}
            disabled={!revisado || !vistaAlDia || descargando}
            className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50"
          >
            {descargando ? t('anon.descargando') : t('anon.descargar')}
          </button>
        </section>
      )}

      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    </div>
  )
}
