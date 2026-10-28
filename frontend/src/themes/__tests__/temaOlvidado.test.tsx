import { describe, it, expect, afterEach } from 'vitest'
import { render, screen, act } from '@testing-library/react'
import { ThemeProvider } from '../ThemeProvider'
import { useTheme } from '../ThemeContext'
import { DEFAULT_THEME, TEMA_OLVIDADO } from '../types'
import { DARK_THEME } from '../presets'

/**
 * Revisión de la PR #311 — el cierre de sesión borraba el tema guardado, pero el proveedor lo
 * conservaba en su estado: quien entraba después en la misma pestaña veía el de quien salió.
 */
afterEach(() => {
  localStorage.clear()
})

function NombreDelTema() {
  const { theme, setTheme } = useTheme()
  return (
    <div>
      <p>{theme.name}</p>
      <button onClick={() => setTheme(DARK_THEME)}>cambia</button>
    </div>
  )
}

describe('el tema olvidado', () => {
  it('should_go_back_to_the_default_theme_in_memory', () => {
    render(
      <ThemeProvider>
        <NombreDelTema />
      </ThemeProvider>,
    )
    act(() => screen.getByText('cambia').click())
    expect(screen.queryByText(DEFAULT_THEME.name)).toBeNull()

    act(() => {
      window.dispatchEvent(new Event(TEMA_OLVIDADO))
    })

    expect(screen.getByText(DEFAULT_THEME.name)).toBeInTheDocument()
  })
})
