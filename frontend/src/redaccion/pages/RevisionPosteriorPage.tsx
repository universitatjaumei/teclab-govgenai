import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import {
  useColaDeRevision,
  useRevisarVersion,
  useSuspenderVersion,
} from '@/shared/api/generated/funciones/funciones'
import type { VersionEnRevision } from '@/shared/api/generated/model'

/**
 * La cola de la revisión posterior (FUN.4, §8.4 de la Instrucció 02/2026).
 *
 * Lo que esta pantalla tiene que dejar claro, y no es cosmética: **la versión que aparece aquí
 * se está ejecutando**. Una cola que pareciera una bandeja de aprobaciones haría creer a quien
 * revisa que su firma es lo que pone la función en marcha, y eso es aprobación previa con otro
 * nombre — justo lo que el nivel 2 prohíbe y lo que empuja al *Shadow IT*.
 *
 * Por eso cada fila lleva el distintivo «en uso» y el recuento de plantillas que dependen de
 * ella: eso es lo que dice si revisarla es urgente, y es lo único que la pantalla necesita para
 * ordenar el trabajo.
 *
 * **«Aprobada» no está entre los resultados**, y no está a propósito: en el nivel 2 no hay nada
 * que aprobar. Los cuatro que hay vienen del servidor (`RESULTADOS_DE_REVISION`) y se escriben
 * aquí en el mismo orden.
 */
const RESULTADOS = ['conforme', 'correcciones', 'reclasificada', 'suspendida'] as const

type Resultado = (typeof RESULTADOS)[number]

function FilaDeRevision({ fila }: { fila: VersionEnRevision }) {
  const { t } = useTranslation('redaccion')
  const [resultado, setResultado] = useState<Resultado>('conforme')
  const [nota, setNota] = useState('')

  // Igual que en el catálogo: al sellar una revisión la fila tiene que salir de la cola. Si no,
  // la persona que revisa vuelve a encontrarse delante lo que acaba de firmar.
  const queryClient = useQueryClient()
  const alCambiar = {
    mutation: {
      onSuccess: () => {
        queryClient.invalidateQueries({
          predicate: consulta =>
            String(consulta.queryKey[0] ?? '').startsWith('/api/v1/funciones'),
        })
      },
    },
  }

  const revisar = useRevisarVersion(alCambiar)
  const suspender = useSuspenderVersion(alCambiar)

  const permitidas = (fila.acciones_permitidas ?? []) as string[]
  const puedeRevisar = permitidas.includes('revisar')
  // `suspendida` deja la versión sin ejecutar, así que exige motivo escrito igual que el endpoint
  // de suspender: mandarlo vacío sería cambiar el 422 del servidor por un formulario que no avisa.
  const notaObligatoria = resultado === 'suspendida'

  function confirmar() {
    if (!puedeRevisar) return
    if (notaObligatoria && !nota.trim()) return
    revisar.mutate({
      funcionId: fila.funcion_id,
      numero: fila.version,
      data: { resultado, nota: nota.trim() || null },
    })
  }

  return (
    <li
      className="border rounded p-4 space-y-3"
      data-testid="fila-revision"
      data-plantillas={String(fila.plantillas_que_la_usan ?? 0)}
      data-dias={String(fila.dias_desde_el_registro ?? 0)}
    >
      <header className="space-y-1">
        <div className="flex items-center gap-2 flex-wrap">
          <h3 className="font-medium text-sm">
            {fila.funcion_nombre} <span className="font-mono">v{fila.version}</span>
          </h3>
          {fila.estado === 'registrada' && (
            <span
              data-testid="en-uso"
              className="text-xs px-2 py-0.5 rounded bg-emerald-100 text-emerald-900 dark:bg-emerald-900 dark:text-emerald-100"
            >
              {t('funciones.en_uso')}
            </span>
          )}
        </div>
        <p className="text-xs text-muted-foreground">
          {t('funciones.usada_por_plantillas', { count: fila.plantillas_que_la_usan ?? 0 })} ·{' '}
          {t('funciones.registrada_hace', { dias: fila.dias_desde_el_registro ?? 0 })} ·{' '}
          {t(`funciones.autoria_${fila.autoria ?? 'ia'}`, fila.autoria ?? '')}
        </p>
      </header>

      <div className="text-sm space-y-1">
        {fila.finalidad && (
          <p>
            <span className="text-muted-foreground">{t('funciones.finalidad')}: </span>
            {fila.finalidad}
          </p>
        )}
        {(fila.categorias_datos ?? []).length > 0 && (
          <p className="text-xs text-muted-foreground">
            {t('funciones.categorias_datos')}: {(fila.categorias_datos ?? []).join(', ')}
          </p>
        )}
      </div>

      {/* Lo que el auditor vio y no bloqueó. Sin esto, revisar sería leer el código a ciegas. */}
      {(fila.hallazgos ?? []).length > 0 && (
        <ul className="text-xs space-y-1" data-testid="hallazgos">
          {(fila.hallazgos ?? []).map((hallazgo, i) => (
            <li key={i} className="text-amber-700 dark:text-amber-400">
              {String((hallazgo as Record<string, unknown>).code ?? '')}
              {(hallazgo as Record<string, unknown>).message
                ? ` — ${String((hallazgo as Record<string, unknown>).message)}`
                : ''}
            </li>
          ))}
        </ul>
      )}

      {puedeRevisar ? (
        <div className="space-y-2">
          <div className="flex gap-2 flex-wrap" role="group" aria-label={t('funciones.resultado')}>
            {RESULTADOS.map(opcion => (
              <button
                key={opcion}
                type="button"
                data-testid={`resultado-${opcion}`}
                data-resultado={opcion}
                aria-pressed={resultado === opcion}
                onClick={() => setResultado(opcion)}
                className={`text-xs px-2 py-1 rounded border ${
                  resultado === opcion ? 'bg-accent font-medium' : 'hover:bg-accent/50'
                }`}
              >
                {t(`funciones.resultado_${opcion}`)}
              </button>
            ))}
          </div>

          <textarea
            data-testid="nota-revision"
            aria-label={t('funciones.nota')}
            value={nota}
            onChange={e => setNota(e.target.value)}
            rows={2}
            placeholder={
              notaObligatoria
                ? t('funciones.nota_obligatoria')
                : t('funciones.nota_placeholder')
            }
            className="w-full text-sm border rounded p-2 bg-background"
          />

          <button
            type="button"
            data-testid="confirmar-revision"
            onClick={confirmar}
            disabled={revisar.isPending}
            className="text-xs px-3 py-1.5 rounded bg-primary text-primary-foreground disabled:opacity-50"
          >
            {t('funciones.sellar_revision')}
          </button>

          {/* `correcciones` y `reclasificada` no frenan nada: se dice, para que quien revisa no
              crea que ha parado algo. */}
          {(resultado === 'correcciones' || resultado === 'reclasificada') && (
            <p className="text-xs text-muted-foreground" data-testid="sigue-en-uso">
              {t('funciones.sigue_en_uso')}
            </p>
          )}
        </div>
      ) : (
        <p className="text-xs text-muted-foreground" data-testid="no-puedes-revisar">
          {t('funciones.no_puedes_revisar')}
        </p>
      )}

      {permitidas.includes('suspender') && suspender.isPending && (
        <p className="text-xs text-muted-foreground">{t('funciones.suspendiendo')}</p>
      )}
    </li>
  )
}

export function RevisionPosteriorPage() {
  const { t } = useTranslation('redaccion')
  const [estado, setEstado] = useState<'sin_revisar' | 'todas'>('sin_revisar')
  const [muestra, setMuestra] = useState<number | undefined>(undefined)

  const { data, isLoading } = useColaDeRevision(
    { estado, ...(muestra ? { muestra } : {}) },
    { query: { enabled: true } },
  )
  const filas = data ?? []

  return (
    <section className="space-y-4">
      <header className="space-y-1">
        <h2 className="text-lg font-semibold">{t('funciones.titulo_revision')}</h2>
        <p className="text-sm text-muted-foreground">{t('funciones.subtitulo_revision')}</p>
      </header>

      <div className="flex gap-4 items-end flex-wrap">
        <label className="text-sm space-y-1">
          <span className="block text-xs text-muted-foreground">{t('funciones.filtro_estado')}</span>
          <select
            data-testid="filtro-estado"
            value={estado}
            onChange={e => setEstado(e.target.value as 'sin_revisar' | 'todas')}
            className="border rounded px-2 py-1 text-sm bg-background"
          >
            <option value="sin_revisar">{t('funciones.filtro_sin_revisar')}</option>
            <option value="todas">{t('funciones.filtro_todas')}</option>
          </select>
        </label>

        {/* El muestreo de §8.4: revisar no exige leerlo todo, y la muestra es **al azar**, que es
            lo que impide que la cola de siempre se revise y la de nunca no. */}
        <label className="text-sm space-y-1">
          <span className="block text-xs text-muted-foreground">{t('funciones.tamano_muestra')}</span>
          <input
            data-testid="tamano-muestra"
            type="number"
            min={1}
            max={100}
            value={muestra ?? ''}
            onChange={e => {
              const valor = Number(e.target.value)
              setMuestra(Number.isFinite(valor) && valor > 0 ? valor : undefined)
            }}
            placeholder={t('funciones.todas_las_filas')}
            className="border rounded px-2 py-1 text-sm bg-background w-28"
          />
        </label>
      </div>

      {isLoading && <p className="text-sm text-muted-foreground">{t('funciones.cargando')}</p>}

      {!isLoading && filas.length === 0 && (
        <p className="text-sm text-muted-foreground" data-testid="cola-vacia">
          {t('funciones.cola_vacia')}
        </p>
      )}

      <ul className="space-y-3">
        {filas.map(fila => (
          <FilaDeRevision key={`${fila.funcion_id}-${fila.version}`} fila={fila} />
        ))}
      </ul>
    </section>
  )
}
