import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { InformeDeAnonimizacion } from '@/shared/api/generated/model'
import { descargarConAutorizacion } from '@/shared/api/download'
import { mensajeDelFallo } from '@/utilidades/mensajeDelFallo'

interface InformeAnonimizacionProps {
  informe: InformeDeAnonimizacion
  proposalId: string
}

/**
 * #255 — qué hizo la anonimización de los datos de prueba y qué quedó, para quien propone y para
 * quien revisa. Sin valores: el servidor no los guarda. Para mirarlo a ojo, el sintético se baja.
 */
export function InformeAnonimizacion({ informe, proposalId }: InformeAnonimizacionProps) {
  const { t, i18n } = useTranslation('scripts')
  const [falloDescarga, setFalloDescarga] = useState('')

  const personales = (informe.mantenidas ?? []).filter(m => m.propuesta !== 'keep')
  const fragmentos = Object.entries(informe.fragmentos ?? {})
  const rechazados = Object.entries(informe.rechazados ?? {})

  function descargar() {
    setFalloDescarga('')
    descargarConAutorizacion(
      `/api/v1/redaccion/scripts/${proposalId}/test-data`,
      'datos_de_prueba_anonimizados',
    ).catch(fallo => setFalloDescarga(mensajeDelFallo(fallo, t('informe_anonimizacion.fallo_descarga'))))
  }

  return (
    <section data-testid="informe-anonimizacion" className="border rounded p-3 space-y-2 text-sm">
      <h3 className="font-medium">{t('informe_anonimizacion.titulo')}</h3>

      {informe.tipo === 'tabular' && (
        <>
          <p>{t('informe_anonimizacion.sustituidas')}</p>
          <ul className="list-disc pl-5 text-xs">
            {(informe.sustituidas ?? []).map(s => (
              <li key={s.columna}>
                <span className="font-mono">{s.columna}</span> → {s.sustituto}
              </li>
            ))}
          </ul>
          {personales.length > 0 && (
            <>
              <p className="text-amber-700">{t('informe_anonimizacion.mantenidas_personales')}</p>
              <ul className="list-disc pl-5 text-xs text-amber-700">
                {personales.map(m => (
                  <li key={m.columna} data-testid={`mantenida-personal-${m.columna}`}>
                    <span className="font-mono">{m.columna}</span>{' '}
                    {t('informe_anonimizacion.proponia', { propuesta: m.propuesta })}
                  </li>
                ))}
              </ul>
            </>
          )}
        </>
      )}

      {informe.tipo === 'pdf' && (
        <>
          <p>{t('informe_anonimizacion.fragmentos')}</p>
          <ul className="list-disc pl-5 text-xs">
            {fragmentos.map(([tipo, n]) => <li key={tipo}>{tipo}: {n}</li>)}
          </ul>
          {rechazados.length > 0 && (
            <>
              <p className="text-amber-700">{t('informe_anonimizacion.rechazados')}</p>
              <ul className="list-disc pl-5 text-xs text-amber-700">
                {rechazados.map(([tipo, n]) => <li key={tipo}>{tipo}: {n}</li>)}
              </ul>
            </>
          )}
        </>
      )}

      <p data-testid="informe-restos" className={informe.restos ? 'text-destructive' : 'text-muted-foreground'}>
        {informe.restos
          ? t('informe_anonimizacion.restos', { count: informe.restos })
          : t('informe_anonimizacion.sin_restos')}
      </p>

      {informe.aceptado_por && (
        <p data-testid="informe-aceptado" className="text-xs text-muted-foreground">
          {t('informe_anonimizacion.aceptado', {
            por: informe.aceptado_por,
            en: informe.aceptado_en ? new Date(informe.aceptado_en).toLocaleString(i18n.language) : '',
          })}
        </p>
      )}

      <button
        type="button"
        data-testid="btn-descargar-sintetico"
        onClick={descargar}
        className="px-3 py-1.5 text-xs border rounded"
      >
        {t('informe_anonimizacion.descargar')}
      </button>
      {falloDescarga && <p className="text-destructive text-xs">{falloDescarga}</p>}
    </section>
  )
}
