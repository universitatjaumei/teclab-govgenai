import { NavLink, Outlet } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useModulos } from '@/shared/auth/useModulos'
import { useAuth } from '@/shared/auth'

/**
 * Los agentes de unidad, bajo una sola entrada del menú (2026-10-03).
 *
 * Dos partes con públicos distintos: **consultar** es de cualquiera (`consulta_agentes`, de
 * oficio) y **publicar y gestionar** exige el módulo `agentes`. Cada pestaña sale de los módulos
 * que concede el servidor, como el propio menú; la ruta de cada una lleva además su guarda, porque
 * quitar el enlace no impide escribir la dirección.
 *
 * La integración con el asistente (#215) es del superadministrador: corrige algo que usan todas las
 * organizaciones. El servidor lo exige igualmente; aquí sólo se evita enseñar una pestaña que daría 403.
 */
const PESTANAS: { key: string; path: string; modulo: string; rol?: string }[] = [
  { key: 'nav_consultar', path: '/agentes/consultar', modulo: 'consulta_agentes' },
  { key: 'nav_gestion', path: '/agentes/gestion', modulo: 'agentes' },
  { key: 'nav_integracion', path: '/agentes/integracion', modulo: 'consulta_agentes', rol: 'superadmin' },
]

export function AgentesLayout() {
  const { t } = useTranslation('agentes')
  const { modulos } = useModulos()
  const { user } = useAuth()
  const visibles = PESTANAS.filter((p) => modulos.includes(p.modulo) && (!p.rol || user?.role === p.rol))

  return (
    <div className="space-y-4">
      <nav aria-label={t('nav_aria')} className="flex gap-1 border-b pb-2 flex-wrap">
        {visibles.map(({ key, path }) => (
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
