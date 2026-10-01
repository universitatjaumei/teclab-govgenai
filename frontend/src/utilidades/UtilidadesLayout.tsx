import { NavLink, Outlet } from 'react-router-dom'
import { useTranslation } from 'react-i18next'

/**
 * Utilidades de uso directo (tema 9 de `ROADMAP.md`).
 *
 * Operaciones sueltas sobre un fichero que alguien tiene en el escritorio y que hoy hace en webs
 * que no aseguran el RGPD. Lo que la plataforma aporta es el trayecto, y por eso cada pantalla
 * lo dice arriba: el documento no sale y no se guarda.
 */
const SUBNAV = [
  { key: 'nav_pdf', path: '/utilidades/pdf' },
  { key: 'nav_anonimizar', path: '/utilidades/anonimizar' },
] as const

export function UtilidadesLayout() {
  const { t } = useTranslation('utilidades')

  return (
    <div className="space-y-4">
      <nav aria-label={t('nav_aria')} className="flex gap-1 border-b pb-2 flex-wrap">
        {SUBNAV.map(({ key, path }) => (
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
      <p className="text-xs text-muted-foreground border-l-2 border-primary pl-3">{t('trayecto')}</p>
      <Outlet />
    </div>
  )
}
