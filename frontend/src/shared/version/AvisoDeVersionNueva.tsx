import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { scriptEnEjecucion, scriptServido } from './versionDelPanel'

/** Cada cuánto se pregunta con la pestaña a la vista. Volver a ella pregunta además en el acto. */
const CADA = 5 * 60 * 1000

/**
 * #248 — avisa de que hay una versión nueva desplegada, sin recargar a la fuerza.
 *
 * Una pestaña abierta antes de un despliegue seguía en el código viejo indefinidamente. Recargar
 * por ella perdería un formulario a medias, así que se avisa y decide quien está delante.
 *
 * Avisa también si una pantalla no carga porque su fichero ya no existe (`vite:preloadError`):
 * es lo que le pasa a esa pestaña al entrar en una ruta que aún no había abierto, y lo único que
 * lo arregla es recargar.
 */
export function AvisoDeVersionNueva() {
  const { t } = useTranslation('common')
  const [nueva, setNueva] = useState(false)

  useEffect(() => {
    const enEjecucion = scriptEnEjecucion()
    // En desarrollo el script es `/src/main.tsx` y el servidor de Vite recarga solo.
    if (enEjecucion === null) return

    let vigente = true
    const comprobar = async () => {
      const servido = await scriptServido()
      if (vigente && servido !== null && servido !== enEjecucion) setNueva(true)
    }
    const alVolver = () => {
      if (document.visibilityState !== 'hidden') void comprobar()
    }
    const alFallarUnaCarga = () => setNueva(true)

    const intervalo = window.setInterval(alVolver, CADA)
    document.addEventListener('visibilitychange', alVolver)
    window.addEventListener('vite:preloadError', alFallarUnaCarga)
    return () => {
      vigente = false
      window.clearInterval(intervalo)
      document.removeEventListener('visibilitychange', alVolver)
      window.removeEventListener('vite:preloadError', alFallarUnaCarga)
    }
  }, [])

  if (!nueva) return null
  return (
    <div
      role="status"
      className="fixed bottom-4 left-1/2 z-50 flex -translate-x-1/2 items-center gap-3 rounded-md border bg-background px-4 py-2 text-sm shadow-lg"
    >
      <span>{t('new_version')}</span>
      <button
        type="button"
        onClick={() => window.location.reload()}
        className="rounded-md bg-primary px-3 py-1 text-primary-foreground hover:bg-primary/90"
      >
        {t('reload')}
      </button>
    </div>
  )
}
