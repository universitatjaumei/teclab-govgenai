import { NavLink, Outlet } from 'react-router-dom'
import { useTranslation } from 'react-i18next'

/**
 * Navegación de Informes.
 *
 * Las pantallas existían desde 9R —plantillas, asistente de informe, borrador con LLM y la
 * cola de revisión de scripts— pero **sus rutas vivían sueltas en `App.tsx`, fuera de todo
 * menú**: sólo se llegaba escribiendo la URL a mano, así que en la práctica la funcionalidad
 * estaba construida y no existía para quien usa el panel.
 */
/**
 * `nav_llm_draft` entra en VER.3 y no es cosmética: el constructor de plantillas guarda
 * `spec_json: {}` —una plantilla sin secciones ni bloques, que no genera nada—, así que
 * proponerla con el modelo es hoy la única vía para obtener una plantilla utilizable desde la
 * interfaz. La pantalla existía entera desde 9R con su ruta fuera de todo menú, y desde VER.2
 * el endpoint que la sostiene ya no devuelve 503.
 */
/**
 * `nav_scripts_new` entra en PRO.2 por la misma razón que `nav_llm_draft` en VER.3: la
 * pantalla existe entera desde 9R y sólo se llegaba escribiendo la URL. Hasta PRO.2 daba
 * igual, porque `POST /scripts/propose` devolvía 503; ahora es la única forma de que alguien
 * pida un script de extracción sin sembrar la propuesta en la base de datos a mano.
 *
 * Va **antes** de la cola de revisión, que es el paso siguiente y no el primero.
 */
const REDACCION_SUBNAV = [
  { key: 'nav_templates', path: '/redaccion/builder' },
  { key: 'nav_llm_draft', path: '/redaccion/draft' },
  { key: 'nav_new_report', path: '/redaccion/wizard' },
  { key: 'nav_scripts_new', path: '/redaccion/scripts/wizard' },
  { key: 'nav_scripts_review', path: '/redaccion/scripts/review' },
  // El catálogo de funciones y su revisión pasaron a «Automatización» el 2026-10-05.
] as const

export function RedaccionLayout() {
  const { t } = useTranslation('redaccion')

  return (
    <div className="space-y-4">
      <nav aria-label={t('nav_aria')} className="flex gap-1 border-b pb-2 flex-wrap">
        {REDACCION_SUBNAV.map(({ key, path }) => (
          <NavLink
            key={path}
            to={path}
            className={({ isActive }) =>
              `px-3 py-1.5 rounded-md text-sm transition-colors ${
                isActive
                  ? 'bg-accent text-accent-foreground font-medium'
                  : 'text-muted-foreground hover:text-foreground hover:bg-accent/50'
              }`
            }
          >
            {t(key)}
          </NavLink>
        ))}
      </nav>
      <Outlet />
    </div>
  )
}
