import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, act } from '@testing-library/react'
import { AuthProvider } from '../AuthContext'
import { useAuth } from '../useAuth'
import { avisaDeSesionCaducada, SESION_CADUCADA } from '../sesionCaducada'
import { olvidarLoDeLaPersona } from '../olvidarLoDeLaPersona'
import { guardarBorrador, leerBorrador } from '@/redaccion/utils/borradorLocal'
import { CLAVE_GUARDADA } from '@/shared/organizacion/useOrganizacionElegida'
import { useFocusStore } from '@/shared/layout/useFocusStore'

/**
 * #278 — tras caducar el token, la SPA seguía «conectada» y cada pantalla fallaba con un 401 hasta
 * recargar; y al salir quedaban en el navegador los borradores y las elecciones de quien salió.
 */
afterEach(() => {
  localStorage.clear()
})

describe('sesión caducada', () => {
  it('should_announce_a_401_sent_with_a_token', () => {
    const oyente = vi.fn()
    window.addEventListener(SESION_CADUCADA, oyente)
    expect(avisaDeSesionCaducada('/api/v1/hub/chatbots', true)).toBe(true)
    window.removeEventListener(SESION_CADUCADA, oyente)
    expect(oyente).toHaveBeenCalledTimes(1)
  })

  it('should_not_announce_a_wrong_password', () => {
    expect(avisaDeSesionCaducada('/api/v1/auth/me/password', true)).toBe(false)
    expect(avisaDeSesionCaducada('/api/v1/auth/user/login', false)).toBe(false)
  })

  it('should_log_out_when_announced', () => {
    function QuienSoy() {
      const { isAuthenticated } = useAuth()
      return <p>{isAuthenticated ? 'dentro' : 'fuera'}</p>
    }
    const cuerpo = btoa(JSON.stringify({ user_id: 'u', email: 'u@uji.es', role: 'user', exp: 9999999999 }))
    localStorage.setItem('access_token', `x.${cuerpo}.y`)
    render(
      <AuthProvider>
        <QuienSoy />
      </AuthProvider>,
    )
    expect(screen.getByText('dentro')).toBeInTheDocument()

    act(() => {
      window.dispatchEvent(new Event(SESION_CADUCADA))
    })

    expect(screen.getByText('fuera')).toBeInTheDocument()
    expect(localStorage.getItem('access_token')).toBeNull()
  })
})

describe('olvidarLoDeLaPersona', () => {
  it('should_forget_drafts_choice_theme_and_focus', () => {
    guardarBorrador('ws-1', 'b-1', 'texto de quien salió')
    localStorage.setItem(CLAVE_GUARDADA, 'org-1')
    localStorage.setItem('chatbot-theme', '{}')
    localStorage.setItem('otra-cosa', 'se queda')
    useFocusStore.getState().setViewMode('focus')

    olvidarLoDeLaPersona()

    expect(leerBorrador('ws-1', 'b-1')).toBeNull()
    expect(localStorage.getItem(CLAVE_GUARDADA)).toBeNull()
    expect(localStorage.getItem('chatbot-theme')).toBeNull()
    expect(localStorage.getItem('otra-cosa')).toBe('se queda')
    expect(useFocusStore.getState().viewMode).toBe('standard')
  })
})
