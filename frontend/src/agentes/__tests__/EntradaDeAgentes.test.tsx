import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { useModulos } from '@/shared/auth/useModulos'
import { EntradaDeAgentes } from '../EntradaDeAgentes'

/**
 * Entrar en «Agentes» lleva a consultar si se puede, y si no a publicar y gestionar. **Se espera a
 * saber los módulos**: al recargar, la lista llega vacía un instante y decidir entonces mandaba a
 * gestionar a quien sólo puede consultar (revisión de la PR #221).
 */
vi.mock('@/shared/auth/useModulos', () => ({ useModulos: vi.fn() }))

function montar(modulos: string[], cargando: boolean) {
  vi.mocked(useModulos).mockReturnValue({ modulos, cargando })
  return render(
    <MemoryRouter initialEntries={['/agentes']}>
      <Routes>
        <Route path="/agentes" element={<EntradaDeAgentes />} />
        <Route path="/agentes/consultar" element={<p>consultar</p>} />
        <Route path="/agentes/gestion" element={<p>gestion</p>} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('EntradaDeAgentes', () => {
  it('mientras no se saben los módulos, no decide', () => {
    montar([], true)
    expect(screen.queryByText('gestion')).not.toBeInTheDocument()
    expect(screen.queryByText('consultar')).not.toBeInTheDocument()
  })

  it('con la consulta, a consultar', () => {
    montar(['consulta_agentes'], false)
    expect(screen.getByText('consultar')).toBeInTheDocument()
  })

  it('sin ella, a gestionar', () => {
    montar(['agentes'], false)
    expect(screen.getByText('gestion')).toBeInTheDocument()
  })
})
