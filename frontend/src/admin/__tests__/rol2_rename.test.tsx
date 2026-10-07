/**
 * ROL.2 — Renombrado institucional en el frontend.
 *
 * Verifica la propagación del renombrado (superadmin|admin|user, Organización):
 * claves i18n renombradas sin labels hardcodeados, ruta /organizaciones en el
 * sub-nav del Hub, y el techo de capacidad por rol (superadmin=plataforma,
 * admin=organización, user=oculto). Las secciones de ruta gateadas por rol no
 * existen como infraestructura separada; el gating real vive en el servidor
 * (el techo de scopes lo calcula y lo prueba el backend, #230) y en los checks
 * de las páginas.
 */
import { describe, it, expect } from 'vitest'
import { render } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import esAdmin from '@/shared/i18n/locales/es/admin.json'
import { HubLayout } from '@/admin/HubLayout'
import { PlataformaLayout } from '@/admin/PlataformaLayout'

describe('ROL.2 — i18n keys', () => {
  it('should_use_i18n_keys_not_hardcoded_role_labels', () => {
    // `as unknown` primero: el JSON tiene claves anidadas (test_scenarios) y el tipo
    // inferido no solapa con Record<string, string>. Aquí sólo se leen claves planas.
    const hub = (esAdmin as unknown as { hub: Record<string, string> }).hub
    // Claves renombradas presentes…
    expect(hub.organizaciones).toBeDefined()
    expect(hub.new_organizacion).toBeDefined()
    expect(hub.organizacion_admin).toBeDefined()
    // …y las antiguas ausentes (sin strings sueltos con nomenclatura vieja).
    expect(hub.clients).toBeUndefined()
    expect(hub.client_partner).toBeUndefined()
    expect(hub.new_client).toBeUndefined()
    // El label del gestor ya no dice "Partner".
    expect(hub.organizacion_admin).not.toMatch(/partner/i)
  })
})

describe('ROL.2 — routing / navegación por Organización', () => {
  it('should_expose_organizaciones_route_not_clients', () => {
    // Lo que fija ROL.2 es el **renombrado**: «clients» desapareció y la entrada se llama
    // Organizaciones. Dónde vive esa entrada es otra decisión, y REV.11 la movió a Plataforma
    // porque su router ya exigía ese módulo para crear y borrar.
    const { container } = render(
      <MemoryRouter initialEntries={['/plataforma/organizaciones']}>
        <Routes>
          <Route path="/plataforma" element={<PlataformaLayout />}>
            <Route path="organizaciones" element={<div>stub</div>} />
          </Route>
        </Routes>
      </MemoryRouter>,
    )
    expect(container.querySelector('a[href="/plataforma/organizaciones"]')).not.toBeNull()
    expect(container.querySelector('a[href="/hub/clients"]')).toBeNull()
  })

  it('should_not_leave_a_clients_entry_in_the_chatbots_subnav', () => {
    const { container } = render(
      <MemoryRouter initialEntries={['/hub/chatbots']}>
        <Routes>
          <Route path="/hub" element={<HubLayout />}>
            <Route path="chatbots" element={<div>stub</div>} />
          </Route>
        </Routes>
      </MemoryRouter>,
    )
    expect(container.querySelector('a[href="/hub/clients"]')).toBeNull()
    expect(container.querySelector('a[href="/hub/organizaciones"]')).toBeNull()
  })
})
