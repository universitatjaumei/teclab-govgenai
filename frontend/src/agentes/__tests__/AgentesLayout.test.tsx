import { describe, it, expect, vi, beforeAll } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import i18n from '@/shared/i18n'
import { useModulos } from '@/shared/auth/useModulos'
import { AgentesLayout } from '../AgentesLayout'

/**
 * Las dos partes de los agentes bajo una sola entrada del menú (2026-10-03): consultar, que es de
 * cualquiera, y publicar y gestionar, que exige el módulo `agentes`. **La pestaña sale de los
 * módulos que concede el servidor**, como el propio menú.
 */
vi.mock('@/shared/auth/useModulos', () => ({ useModulos: vi.fn() }))
const rol = { actual: 'user' }
vi.mock('@/shared/auth', () => ({ useAuth: () => ({ user: { role: rol.actual } }) }))

function montar(modulos: string[], role = 'user') {
  rol.actual = role
  vi.mocked(useModulos).mockReturnValue({ modulos, cargando: false })
  return render(
    <MemoryRouter initialEntries={['/agentes/consultar']}>
      <AgentesLayout />
    </MemoryRouter>,
  )
}

beforeAll(async () => {
  await i18n.changeLanguage('es')
})

describe('AgentesLayout', () => {
  it('quien sólo consulta ve la pestaña de consultar y no la de gestionar', () => {
    montar(['consulta_agentes'])
    expect(screen.getByRole('link', { name: 'Consultar' })).toHaveAttribute('href', '/agentes/consultar')
    expect(screen.queryByRole('link', { name: 'Publicar y gestionar' })).not.toBeInTheDocument()
  })

  it('quien publica ve las dos', () => {
    montar(['consulta_agentes', 'agentes'])
    expect(screen.getByRole('link', { name: 'Consultar' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Publicar y gestionar' })).toHaveAttribute('href', '/agentes/gestion')
  })

  it('con la consulta retirada, quien publica sólo ve gestionar', () => {
    montar(['agentes'])
    expect(screen.queryByRole('link', { name: 'Consultar' })).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Publicar y gestionar' })).toBeInTheDocument()
  })

  it('la integración con Gemini sólo la ve el superadministrador (#215)', () => {
    montar(['consulta_agentes', 'agentes'], 'admin')
    expect(screen.queryByRole('link', { name: 'Integración con Gemini' })).not.toBeInTheDocument()
    montar(['consulta_agentes'], 'superadmin')
    expect(screen.getByRole('link', { name: 'Integración con Gemini' })).toHaveAttribute('href', '/agentes/integracion')
  })
})
