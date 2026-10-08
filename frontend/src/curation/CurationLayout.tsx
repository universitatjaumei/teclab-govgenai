import { NavLink, Outlet } from 'react-router-dom'
import { useTranslation } from 'react-i18next'

const CURATION_SUBNAV = [
  { key: 'nav_sites', path: '/curation/sites' },
  { key: 'nav_audit', path: '/curation/audit' },
  { key: 'nav_findings', path: '/curation/findings' },
  // 2026-10-08 — proponer páginas para un asistente mientras se cura, antes de publicar.
  { key: 'nav_pages', path: '/curation/pages' },
  { key: 'nav_publish', path: '/curation/publish' },
] as const

/**
 * Navegación propia de la curación (CUR.2): no cuelga de ningún chatbot ni de ningún
 * documento. `docs/DECISION_CURACION_SEPARADA.md` — separar la curación es sobre todo dejar
 * de prometer «apunta al sitio web y el asistente aprende». Mientras esto viviera como
 * pestañas dentro del panel de documentos de un chatbot, esa promesa seguía implícita.
 */
export function CurationLayout() {
  const { t } = useTranslation('curation')

  return (
    <div className="space-y-4">
      <nav aria-label={t('subnav_aria')} className="flex gap-1 border-b pb-2 flex-wrap">
        {CURATION_SUBNAV.map(({ key, path }) => (
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
