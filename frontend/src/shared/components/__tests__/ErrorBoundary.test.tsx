import { useState } from 'react'
import { describe, it, expect, vi, beforeAll } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import i18n from '@/shared/i18n'
import { ErrorBoundary } from '../ErrorBoundary'

/** #278 — un error al pintar una pantalla dejaba la SPA entera en blanco, menú incluido. */
beforeAll(async () => {
  await i18n.changeLanguage('es')
})

let revienta = true
function Pantalla() {
  if (revienta) throw new Error('fallo al pintar')
  return <p>pantalla bien</p>
}

describe('ErrorBoundary', () => {
  it('should_replace_only_the_broken_screen_with_a_notice', () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    render(
      <div>
        <nav>menú</nav>
        <ErrorBoundary>
          <Pantalla />
        </ErrorBoundary>
      </div>,
    )

    expect(screen.getByTestId('pantalla-con-fallo')).toHaveTextContent(i18n.t('common:error_boundary_title'))
    expect(screen.getByText('menú')).toBeInTheDocument()
  })

  it('should_try_again_when_asked', () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    revienta = true
    render(
      <ErrorBoundary>
        <Pantalla />
      </ErrorBoundary>,
    )
    revienta = false
    fireEvent.click(screen.getByRole('button', { name: i18n.t('common:error_boundary_retry') }))

    expect(screen.getByText('pantalla bien')).toBeInTheDocument()
  })

  // Revisión de la PR #311 — con `key` por ruta, la pantalla se remontaba en cada navegación
  // aunque no hubiera fallado nada, y se perdía el estado de los layouts anidados.
  it('should_keep_the_screen_mounted_when_the_key_changes_without_a_failure', () => {
    function Contador() {
      const [n, setN] = useState(0)
      return <button onClick={() => setN(n + 1)}>pulsado {n}</button>
    }
    const { rerender } = render(
      <ErrorBoundary clave="/a">
        <Contador />
      </ErrorBoundary>,
    )
    fireEvent.click(screen.getByText('pulsado 0'))
    rerender(
      <ErrorBoundary clave="/b">
        <Contador />
      </ErrorBoundary>,
    )

    expect(screen.getByText('pulsado 1')).toBeInTheDocument()
  })

  it('should_clear_the_failure_when_the_key_changes', () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    revienta = true
    const { rerender } = render(
      <ErrorBoundary clave="/a">
        <Pantalla />
      </ErrorBoundary>,
    )
    expect(screen.getByTestId('pantalla-con-fallo')).toBeInTheDocument()
    revienta = false
    rerender(
      <ErrorBoundary clave="/b">
        <Pantalla />
      </ErrorBoundary>,
    )

    expect(screen.getByText('pantalla bien')).toBeInTheDocument()
  })
})
