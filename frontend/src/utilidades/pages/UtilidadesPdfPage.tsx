import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { descargarConAutorizacion } from '@/shared/api/download'
import { NivelDeOptimizacion, BodyPartirPdfModo } from '@/shared/api/generated/model'
import { mensajeDelFallo } from '@/utilidades/mensajeDelFallo'

type Operacion = 'unir' | 'partir' | 'optimizar'
type Modo = (typeof BodyPartirPdfModo)[keyof typeof BodyPartirPdfModo]
type Nivel = (typeof NivelDeOptimizacion)[keyof typeof NivelDeOptimizacion]

const OPERACIONES: Operacion[] = ['unir', 'partir', 'optimizar']
// Los modos y los niveles salen del contrato: un nivel nuevo en el servidor aparece aquí solo.
const MODOS = Object.values(BodyPartirPdfModo) as Modo[]
const NIVELES = Object.values(NivelDeOptimizacion) as Nivel[]

/**
 * Unir, dividir y optimizar PDF (UTL.1, issue #190).
 *
 * **La pantalla no decide nada**: qué rangos son válidos, cuántas páginas tiene el documento o si
 * un fichero es un PDF lo comprueba el servidor y lo dice. Aquí se elige la operación, se sube y
 * se descarga lo que vuelve.
 */
export function UtilidadesPdfPage() {
  const { t } = useTranslation('utilidades')
  const [operacion, setOperacion] = useState<Operacion>('unir')
  const [ficheros, setFicheros] = useState<File[]>([])
  const [optimizarSalida, setOptimizarSalida] = useState(true)
  const [modo, setModo] = useState<Modo>(BodyPartirPdfModo.rangos)
  const [rangos, setRangos] = useState('')
  const [nivel, setNivel] = useState<Nivel>(NivelDeOptimizacion.NUMBER_3)
  const [trabajando, setTrabajando] = useState(false)
  const [error, setError] = useState('')
  const [hecho, setHecho] = useState(false)

  const variosFicheros = operacion === 'unir'

  function elegir(lista: FileList | null | undefined) {
    setError('')
    setHecho(false)
    const nuevos = Array.from(lista ?? [])
    setFicheros((actuales) => (variosFicheros ? [...actuales, ...nuevos] : nuevos.slice(0, 1)))
  }

  function cambiarOperacion(nueva: Operacion) {
    setOperacion(nueva)
    setFicheros((actuales) => (nueva === 'unir' ? actuales : actuales.slice(0, 1)))
    setError('')
    setHecho(false)
  }

  function mover(indice: number, paso: -1 | 1) {
    setFicheros((actuales) => {
      const copia = [...actuales]
      const destino = indice + paso
      if (destino < 0 || destino >= copia.length) return actuales
      ;[copia[indice], copia[destino]] = [copia[destino], copia[indice]]
      return copia
    })
  }

  async function ejecutar() {
    setError('')
    setHecho(false)
    const cuerpo = new FormData()
    if (operacion === 'unir') {
      ficheros.forEach((f) => cuerpo.append('files', f))
      cuerpo.append('optimizar', String(optimizarSalida))
    } else if (operacion === 'partir') {
      cuerpo.append('file', ficheros[0])
      cuerpo.append('modo', modo)
      cuerpo.append('rangos', rangos)
      cuerpo.append('optimizar', String(optimizarSalida))
    } else {
      cuerpo.append('file', ficheros[0])
      cuerpo.append('nivel', String(nivel))
    }
    const ruta = `/api/v1/utilidades/pdf/${operacion}`
    setTrabajando(true)
    try {
      await descargarConAutorizacion(ruta, 'resultado.pdf', cuerpo)
      setHecho(true)
    } catch (fallo) {
      setError(mensajeDelFallo(fallo, t('error')))
    } finally {
      setTrabajando(false)
    }
  }

  const faltanFicheros = variosFicheros ? ficheros.length < 2 : ficheros.length < 1
  const boton = t(`pdf.boton_${operacion}`)

  return (
    <div className="space-y-4 max-w-3xl">
      <header>
        <h2 className="text-lg font-semibold">{t('pdf.titulo')}</h2>
        <p className="text-sm text-muted-foreground">{t('pdf.descripcion')}</p>
      </header>

      <fieldset className="flex flex-wrap gap-2">
        <legend className="text-sm font-medium mb-1">{t('pdf.operacion')}</legend>
        {OPERACIONES.map((op) => (
          <label
            key={op}
            className={`px-3 py-1.5 rounded-md border text-sm cursor-pointer ${
              operacion === op ? 'bg-accent font-medium' : 'hover:bg-accent/50'
            }`}
          >
            <input
              type="radio"
              name="operacion"
              value={op}
              checked={operacion === op}
              onChange={() => cambiarOperacion(op)}
              className="sr-only"
            />
            {t(`pdf.op_${op}`)}
          </label>
        ))}
      </fieldset>

      {/* El input se oculta con `sr-only` y la zona es una etiqueta propia: el control nativo se
          pinta en el idioma del navegador y no en el del panel (INF.8). */}
      <label
        htmlFor="pdf-ficheros"
        data-testid="zona-pdf"
        className="flex flex-col items-center justify-center gap-1 w-full px-4 py-6 border-2 border-dashed border-input rounded-md cursor-pointer text-center hover:border-primary hover:bg-accent/40 transition-colors"
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => {
          e.preventDefault()
          elegir(e.dataTransfer.files)
        }}
      >
        <span className="text-sm font-medium">
          {variosFicheros ? t('pdf.soltar') : t('pdf.soltar_uno')}
        </span>
        <span className="text-xs text-muted-foreground">{t('pdf.formatos')}</span>
      </label>
      <input
        id="pdf-ficheros"
        data-testid="input-pdf"
        type="file"
        accept=".pdf,application/pdf"
        multiple={variosFicheros}
        onChange={(e) => {
          elegir(e.target.files)
          e.target.value = ''
        }}
        className="sr-only"
      />

      {ficheros.length > 0 && (
        <div className="space-y-1">
          {variosFicheros && <p className="text-sm font-medium">{t('pdf.elegidos')}</p>}
          <ol className="space-y-1">
            {ficheros.map((f, i) => (
              <li key={`${f.name}-${i}`} className="flex items-center gap-2 text-sm border rounded px-2 py-1">
                <span className="flex-1 truncate">{f.name}</span>
                {variosFicheros && (
                  <>
                    <button type="button" className="text-xs underline" disabled={i === 0} onClick={() => mover(i, -1)}>
                      {t('pdf.subir')}
                    </button>
                    <button
                      type="button"
                      className="text-xs underline"
                      disabled={i === ficheros.length - 1}
                      onClick={() => mover(i, 1)}
                    >
                      {t('pdf.bajar')}
                    </button>
                  </>
                )}
                <button
                  type="button"
                  className="text-xs underline text-destructive"
                  onClick={() => setFicheros((a) => a.filter((_, j) => j !== i))}
                >
                  {t('pdf.quitar')}
                </button>
              </li>
            ))}
          </ol>
        </div>
      )}

      {operacion === 'partir' && (
        <div className="space-y-3 border rounded p-3">
          <fieldset className="space-y-1">
            <legend className="text-sm font-medium">{t('pdf.modo')}</legend>
            {MODOS.map((m) => (
              <label key={m} className="flex items-center gap-2 text-sm">
                <input type="radio" name="modo" value={m} checked={modo === m} onChange={() => setModo(m)} />
                {t(`pdf.modo_${m}`)}
              </label>
            ))}
          </fieldset>
          {modo !== BodyPartirPdfModo.todas && (
            <div className="space-y-1">
              <label htmlFor="pdf-rangos" className="text-sm font-medium block">
                {t('pdf.rangos')}
              </label>
              <input
                id="pdf-rangos"
                type="text"
                value={rangos}
                onChange={(e) => setRangos(e.target.value)}
                className="w-full rounded-md border border-input bg-background px-3 py-1.5 text-sm"
                aria-describedby="pdf-rangos-ayuda"
              />
              <p id="pdf-rangos-ayuda" className="text-xs text-muted-foreground">
                {t('pdf.rangos_ayuda')}
              </p>
            </div>
          )}
        </div>
      )}

      {operacion === 'optimizar' ? (
        <div className="space-y-1">
          <label htmlFor="pdf-nivel" className="text-sm font-medium block">
            {t('pdf.nivel')}
          </label>
          <select
            id="pdf-nivel"
            value={nivel}
            onChange={(e) => setNivel(Number(e.target.value) as Nivel)}
            className="rounded-md border border-input bg-background px-3 py-1.5 text-sm"
          >
            {NIVELES.map((n) => (
              <option key={n} value={n}>
                {t(`pdf.nivel_${n}`)}
              </option>
            ))}
          </select>
        </div>
      ) : (
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={optimizarSalida} onChange={(e) => setOptimizarSalida(e.target.checked)} />
          {t('pdf.optimizar_salida')}
        </label>
      )}

      {operacion === 'unir' && ficheros.length === 1 && (
        <p className="text-xs text-muted-foreground">{t('pdf.faltan_dos')}</p>
      )}

      <button
        type="button"
        onClick={() => void ejecutar()}
        disabled={faltanFicheros || trabajando}
        className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50"
      >
        {trabajando ? t('pdf.procesando') : boton}
      </button>

      {hecho && <p role="status" className="text-sm text-green-700 dark:text-green-400">{t('pdf.hecho')}</p>}
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    </div>
  )
}
