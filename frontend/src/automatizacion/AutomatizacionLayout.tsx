import { NavLink, Outlet } from 'react-router-dom'
import { useTranslation } from 'react-i18next'

/**
 * Navegación de «Automatización» (2026-10-05, opción A del usuario).
 *
 * El catálogo de funciones vivía en las pestañas de Informes, y una función —sobre todo una de
 * origen externo, un cuaderno que corre fuera— no produce ningún informe: es automatización
 * gobernada. Las pantallas son las mismas de antes; cambia dónde viven y el módulo que las abre.
 * Los scripts siguen en Informes, porque quien redacta propone el de su plantilla.
 */
const AUTOMATIZACION_SUBNAV = [
  { key: 'nav_funciones', path: '/automatizacion/funciones', end: true },
  { key: 'nav_funciones_revision', path: '/automatizacion/funciones/revision', end: false },
] as const

export function AutomatizacionLayout() {
  const { t } = useTranslation('redaccion')

  return (
    <div className="space-y-4">
      <nav aria-label={t('automatizacion_nav_aria')} className="flex gap-1 border-b pb-2 flex-wrap">
        {AUTOMATIZACION_SUBNAV.map(({ key, path, end }) => (
          <NavLink
            key={path}
            to={path}
            end={end}
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
