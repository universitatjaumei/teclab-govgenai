import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import {
  useListarFunciones,
  useSuspenderVersion,
  useReactivarVersion,
  useRetirarVersion,
  useSolicitarPromocionDeFuncion,
  usePromoverFuncion,
} from '@/shared/api/generated/funciones/funciones'
import type { FuncionView, VersionView } from '@/shared/api/generated/model'

/**
 * El catálogo de funciones (FUN.4).
 *
 * **Los botones salen de `acciones_permitidas`**, que calcula el servidor (regla maestra 2).
 * Aquí no hay ni un `rol === 'admin'`: si lo hubiera, la autorización estaría escrita dos veces
 * —en `funciones_acciones.py` y aquí— y el día que una de las dos cambiara dirían cosas
 * distintas, que es exactamente cómo aparecen los botones que dan 403.
 *
 * Las dos acciones con cuerpo obligatorio —suspender y promover— piden su texto **antes** de
 * mandar nada: el motivo de una suspensión viaja hasta el fallo del bloque anclado, y la
 * valoración de una promoción es la única aprobación previa del catálogo. Dejar mandar sin ellos
 * sería cambiar un 422 del servidor por un formulario que no avisa.
 */

/** Las acciones que se resuelven en esta pantalla. `adoptar_version` y `versionar` no: se ejercen
 *  desde el constructor de plantillas y desde el asistente de scripts, que es donde se está
 *  trabajando cuando tienen sentido. */
const ACCIONES_CON_BOTON = [
  'revisar',
  'solicitar_promocion',
  'promover',
  'suspender',
  'reactivar',
  'retirar',
] as const

type AccionConBoton = (typeof ACCIONES_CON_BOTON)[number]

interface FichaProps {
  funcion: FuncionView
  navegarARevision: () => void
}

function VersionFila({
  funcion,
  version,
  navegarARevision,
}: {
  funcion: FuncionView
  version: VersionView
  navegarARevision: () => void
}) {
  const { t } = useTranslation('redaccion')
  const [pidiendo, setPidiendo] = useState<AccionConBoton | null>(null)
  const [texto, setTexto] = useState('')

  // Tras cualquier mutación hay que **invalidar**, no confiar en que la pantalla ya lo sabe:
  // suspender respondía 200 y la ficha seguía diciendo «Registrada», así que quien pulsaba el
  // botón no tenía forma de saber si había pasado algo — y lo natural entonces es volver a
  // pulsar. Lo destapó la verificación en navegador de FUN.4.
  //
  // Se invalida por prefijo de ruta y no por clave exacta: así se ponen al día el catálogo, la
  // ficha y la cola de revisión, que miran la misma realidad desde tres sitios.
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

  const suspender = useSuspenderVersion(alCambiar)
  const reactivar = useReactivarVersion(alCambiar)
  const retirar = useRetirarVersion(alCambiar)
  const solicitar = useSolicitarPromocionDeFuncion(alCambiar)
  const promover = usePromoverFuncion(alCambiar)

  const permitidas = (version.acciones_permitidas ?? []) as string[]
  const ofrecidas = ACCIONES_CON_BOTON.filter(a => permitidas.includes(a))

  function pedir(accion: AccionConBoton) {
    if (accion === 'revisar') {
      navegarARevision()
      return
    }
    if (accion === 'reactivar') {
      reactivar.mutate({ funcionId: funcion.id, numero: version.version })
      return
    }
    if (accion === 'retirar') {
      retirar.mutate({ funcionId: funcion.id, numero: version.version })
      return
    }
    // Suspender, promover y solicitar la promoción exigen texto: se abre el formulario.
    setTexto('')
    setPidiendo(accion)
  }

  function confirmar(accion: AccionConBoton) {
    const escrito = texto.trim()
    if (!escrito) return
    if (accion === 'suspender') {
      suspender.mutate({
        funcionId: funcion.id,
        numero: version.version,
        data: { motivo: escrito },
      })
    } else if (accion === 'promover') {
      promover.mutate({ funcionId: funcion.id, data: { valoracion: escrito } })
    } else if (accion === 'solicitar_promocion') {
      solicitar.mutate({ funcionId: funcion.id, data: { motivo: escrito } })
    }
    setPidiendo(null)
    setTexto('')
  }

  return (
    <li className="border rounded p-3 space-y-2 bg-card" data-testid="version">
      <div className="flex items-center gap-2 flex-wrap text-sm">
        <span className="font-mono">v{version.version}</span>
        <span
          data-testid="estado-version"
          data-estado={version.estado}
          className="px-2 py-0.5 rounded bg-muted text-xs"
        >
          {t(`funciones.estado_${version.estado}`, version.estado)}
        </span>
        <span className="text-xs text-muted-foreground">
          {t(`funciones.autoria_${version.autoria ?? 'ia'}`, version.autoria ?? '')}
        </span>
      </div>

      {version.finalidad && (
        <p className="text-sm">
          <span className="text-muted-foreground">{t('funciones.finalidad')}: </span>
          {version.finalidad}
        </p>
      )}
      {(version.categorias_datos ?? []).length > 0 && (
        <p className="text-xs text-muted-foreground">
          {t('funciones.categorias_datos')}: {(version.categorias_datos ?? []).join(', ')}
        </p>
      )}

      {/* Los avisos del auditor que **no** bloquearon: es lo que la revisión posterior lee. */}
      {(version.hallazgos ?? []).length > 0 && (
        <ul className="text-xs space-y-1" data-testid="hallazgos">
          {(version.hallazgos ?? []).map((hallazgo, i) => (
            <li key={i} className="text-amber-700 dark:text-amber-400">
              {String((hallazgo as Record<string, unknown>).code ?? '')}
              {(hallazgo as Record<string, unknown>).message
                ? ` — ${String((hallazgo as Record<string, unknown>).message)}`
                : ''}
            </li>
          ))}
        </ul>
      )}

      {version.revision_resultado && (
        <p className="text-xs" data-testid="revision">
          {t('funciones.revisada_como')}:{' '}
          {t(`funciones.resultado_${version.revision_resultado}`, version.revision_resultado)}
          {version.revision_nota ? ` — ${version.revision_nota}` : ''}
        </p>
      )}

      {version.motivo_suspension && (
        <p className="text-xs text-destructive" data-testid="motivo-suspension-visible">
          {t('funciones.suspendida_porque')}: {version.motivo_suspension}
        </p>
      )}

      {ofrecidas.length > 0 && (
        <div className="flex gap-2 flex-wrap pt-1">
          {ofrecidas.map(accion => (
            <button
              key={accion}
              type="button"
              data-testid={`accion-${accion}`}
              onClick={() => pedir(accion)}
              className="text-xs px-2 py-1 rounded border hover:bg-accent"
            >
              {t(`funciones.accion_${accion}`)}
            </button>
          ))}
        </div>
      )}

      {pidiendo && (
        <div className="space-y-2 pt-1">
          <label className="block text-xs text-muted-foreground" htmlFor={`texto-${accionId(pidiendo, version)}`}>
            {t(`funciones.pide_${pidiendo}`)}
          </label>
          <textarea
            id={`texto-${accionId(pidiendo, version)}`}
            data-testid={
              pidiendo === 'suspender'
                ? 'motivo-suspension'
                : pidiendo === 'promover'
                  ? 'valoracion-promocion'
                  : 'motivo-promocion'
            }
            value={texto}
            onChange={e => setTexto(e.target.value)}
            rows={2}
            className="w-full text-sm border rounded p-2 bg-background"
          />
          <div className="flex gap-2">
            <button
              type="button"
              data-testid={`confirmar-${pidiendo}`}
              onClick={() => confirmar(pidiendo)}
              className="text-xs px-2 py-1 rounded bg-primary text-primary-foreground"
            >
              {t('funciones.confirmar')}
            </button>
            <button
              type="button"
              onClick={() => setPidiendo(null)}
              className="text-xs px-2 py-1 rounded border"
            >
              {t('funciones.cancelar')}
            </button>
          </div>
        </div>
      )}
    </li>
  )
}

function accionId(accion: string, version: VersionView) {
  return `${accion}-${version.version}`
}

function FichaDeFuncion({ funcion, navegarARevision }: FichaProps) {
  const { t } = useTranslation('redaccion')

  return (
    <article className="border rounded p-4 space-y-3" data-testid="ficha-funcion">
      <header className="space-y-1">
        <h3 className="font-medium">{funcion.nombre}</h3>
        <div className="flex gap-2 items-center flex-wrap text-xs text-muted-foreground">
          {/* El nivel lo dice el servidor; la pantalla no lo deduce del origen ni de la fecha. */}
          <span
            data-testid="nivel"
            data-nivel={String(funcion.nivel)}
            className="px-2 py-0.5 rounded bg-muted"
          >
            {t('funciones.nivel', { nivel: funcion.nivel })}
          </span>
          <span data-testid="origen" data-origen={funcion.origen}>
            {t(`funciones.origen_${funcion.origen}`, funcion.origen)}
          </span>
          {/* FUN.5 — de una función empaquetada lo que hace falta saber no es su ordinal
              interno: es de qué paquete pip viene y qué versión está instalada. Sin eso, ante un
              informe raro no hay forma de decidir si mirar el repositorio del equipo que la
              mantiene o el despliegue que la instaló. */}
          {funcion.origen === 'paquete' && funcion.distribucion && (
            <span
              data-testid="paquete"
              data-distribucion={funcion.distribucion}
              data-version-instalada={funcion.version_paquete_instalada ?? ''}
              className="font-mono"
            >
              {funcion.distribucion}
              {funcion.version_paquete_instalada ? ` ${funcion.version_paquete_instalada}` : ''}
            </span>
          )}
          {funcion.origen !== 'paquete' && funcion.entry_point && (
            <code className="font-mono">{funcion.entry_point}</code>
          )}
        </div>
        {funcion.descripcion && <p className="text-sm">{funcion.descripcion}</p>}
      </header>

      {/* Señal, no decisión: la Instrucció deja la valoración a personas. */}
      {funcion.candidata_nivel_3 && (
        <div
          data-testid="candidata-nivel-3"
          className="text-xs border-l-2 border-amber-500 pl-2 space-y-1"
        >
          <p className="font-medium">{t('funciones.candidata_nivel_3')}</p>
          <ul>
            {(funcion.motivos_nivel_3 ?? []).map(motivo => (
              <li key={motivo}>{motivo}</li>
            ))}
          </ul>
        </div>
      )}

      {funcion.valoracion_promocion && (
        <p className="text-xs" data-testid="valoracion-promocion-visible">
          {t('funciones.valorada_como')}: {funcion.valoracion_promocion}
        </p>
      )}

      <ul className="space-y-2">
        {(funcion.versiones ?? []).map(version => (
          <VersionFila
            key={version.version}
            funcion={funcion}
            version={version}
            navegarARevision={navegarARevision}
          />
        ))}
      </ul>
    </article>
  )
}

export function CatalogoDeFuncionesPage() {
  const { t } = useTranslation('redaccion')
  const navigate = useNavigate()
  const { data, isLoading } = useListarFunciones()
  const funciones = (data as unknown as FuncionView[] | undefined) ?? []

  return (
    <section className="space-y-4">
      <header className="space-y-1">
        <h2 className="text-lg font-semibold">{t('funciones.titulo_catalogo')}</h2>
        <p className="text-sm text-muted-foreground">{t('funciones.subtitulo_catalogo')}</p>
      </header>

      {isLoading && <p className="text-sm text-muted-foreground">{t('funciones.cargando')}</p>}

      {!isLoading && funciones.length === 0 && (
        <p className="text-sm text-muted-foreground" data-testid="catalogo-vacio">
          {t('funciones.catalogo_vacio')}
        </p>
      )}

      <div className="space-y-4">
        {funciones.map(funcion => (
          <FichaDeFuncion
            key={funcion.id}
            funcion={funcion}
            navegarARevision={() => navigate('/automatizacion/funciones/revision')}
          />
        ))}
      </div>
    </section>
  )
}
