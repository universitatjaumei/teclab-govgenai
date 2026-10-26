import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, act } from '@testing-library/react'
import { AuthProvider } from '../AuthContext'
import { useAuth } from '../useAuth'
import { avisaDeSesionCaducada, SESION_CADUCADA } from '../sesionCaducada'
import { olvidarLoDeLaPersona } from '../olvidarLoDeLaPersona'
import { guardarBorrador, leerBorrador } from '@/redaccion/utils/borradorLocal'
import { CLAVE_GUARDADA } from '@/shared/organizacion/useOrganizacionElegida'
import { useFocusStore } from '@/shared/layout/useFocusStore'
import { TEMA_OLVIDADO } from '@/themes/types'

/**
 * #278 — tras caducar el token, la SPA seguía «conectada» y cada pantalla fallaba con un 401 hasta
 * recargar; y al salir quedaban en el navegador los borradores y las elecciones de quien salió.
 *
 * La revisión de la PR #311 corrigió el primer arreglo: olvidaba lo de la persona también cuando
 * la sesión caducaba y en cada login, así que un borrador a medias se perdía justo en el caso
 * para el que existe el borrador local.
 */
afterEach(() => {
  localStorage.clear()
})

function tokenDe(persona: string): string {
  const cuerpo = btoa(JSON.stringify({ user_id: persona, email: `${persona}@uji.es`, role: 'user', exp: 9999999999 }))
  return `x.${cuerpo}.y`
}

function QuienSoy() {
  const { isAuthenticated, user, login, logout } = useAuth()
  return (
    <div>
      <p>{isAuthenticated ? `dentro ${user?.user_id}` : 'fuera'}</p>
      <button onClick={() => login(tokenDe('ana'))}>entra ana</button>
      <button onClick={() => login(tokenDe('bea'))}>entra bea</button>
      <button onClick={logout}>sal</button>
    </div>
  )
}

function montar(alOlvidarALaPersona = vi.fn()) {
  render(
    <AuthProvider alOlvidarALaPersona={alOlvidarALaPersona}>
      <QuienSoy />
    </AuthProvider>,
  )
  return alOlvidarALaPersona
}

describe('avisaDeSesionCaducada', () => {
  it('should_announce_a_401_sent_with_the_current_token', () => {
    localStorage.setItem('access_token', tokenDe('ana'))
    const oyente = vi.fn()
    window.addEventListener(SESION_CADUCADA, oyente)
    expect(avisaDeSesionCaducada('/api/v1/hub/chatbots', `Bearer ${tokenDe('ana')}`)).toBe(true)
    window.removeEventListener(SESION_CADUCADA, oyente)
    expect(oyente).toHaveBeenCalledTimes(1)
  })

  it('should_not_announce_a_401_of_a_request_sent_with_a_previous_token', () => {
    localStorage.setItem('access_token', tokenDe('bea'))
    expect(avisaDeSesionCaducada('/api/v1/hub/chatbots', `Bearer ${tokenDe('ana')}`)).toBe(false)
  })

  it('should_not_announce_a_wrong_password', () => {
    localStorage.setItem('access_token', tokenDe('ana'))
    expect(avisaDeSesionCaducada('/api/v1/auth/me/password', `Bearer ${tokenDe('ana')}`)).toBe(false)
    expect(avisaDeSesionCaducada('/api/v1/auth/user/login', `Bearer ${tokenDe('ana')}`)).toBe(false)
    expect(avisaDeSesionCaducada('/api/v1/auth/user/login', undefined)).toBe(false)
  })

  it('should_announce_a_route_that_only_contains_login_in_its_name', () => {
    localStorage.setItem('access_token', tokenDe('ana'))
    expect(avisaDeSesionCaducada('/api/v1/hub/login-history', `Bearer ${tokenDe('ana')}`)).toBe(true)
  })
})

describe('sesión caducada', () => {
  it('should_log_out_without_forgetting_the_person', () => {
    localStorage.setItem('access_token', tokenDe('ana'))
    const alOlvidar = montar()
    expect(screen.getByText('dentro ana')).toBeInTheDocument()

    act(() => {
      window.dispatchEvent(new Event(SESION_CADUCADA))
    })

    expect(screen.getByText('fuera')).toBeInTheDocument()
    expect(localStorage.getItem('access_token')).toBeNull()
    expect(alOlvidar).not.toHaveBeenCalled()
  })

  it('should_keep_the_person_when_the_same_one_comes_back', () => {
    const alOlvidar = montar()
    act(() => screen.getByText('entra ana').click())
    act(() => {
      window.dispatchEvent(new Event(SESION_CADUCADA))
    })
    act(() => screen.getByText('entra ana').click())

    expect(screen.getByText('dentro ana')).toBeInTheDocument()
    expect(alOlvidar).not.toHaveBeenCalled()
  })

  it('should_forget_the_person_when_another_one_comes_in', () => {
    const alOlvidar = montar()
    act(() => screen.getByText('entra ana').click())
    act(() => {
      window.dispatchEvent(new Event(SESION_CADUCADA))
    })
    act(() => screen.getByText('entra bea').click())

    expect(screen.getByText('dentro bea')).toBeInTheDocument()
    expect(alOlvidar).toHaveBeenCalledTimes(1)
  })

  it('should_forget_the_person_on_an_explicit_logout', () => {
    const alOlvidar = montar()
    act(() => screen.getByText('entra ana').click())
    act(() => screen.getByText('sal').click())

    expect(screen.getByText('fuera')).toBeInTheDocument()
    expect(alOlvidar).toHaveBeenCalledTimes(1)
  })
})

describe('olvidarLoDeLaPersona', () => {
  it('should_forget_drafts_choice_theme_and_focus', () => {
    guardarBorrador('ws-1', 'b-1', 'texto de quien salió')
    localStorage.setItem(CLAVE_GUARDADA, 'org-1')
    localStorage.setItem('chatbot-theme', '{}')
    localStorage.setItem('otra-cosa', 'se queda')
    useFocusStore.getState().setViewMode('focus')
    const temaOlvidado = vi.fn()
    window.addEventListener(TEMA_OLVIDADO, temaOlvidado)

    olvidarLoDeLaPersona()
    window.removeEventListener(TEMA_OLVIDADO, temaOlvidado)

    expect(leerBorrador('ws-1', 'b-1')).toBeNull()
    expect(localStorage.getItem(CLAVE_GUARDADA)).toBeNull()
    expect(localStorage.getItem('chatbot-theme')).toBeNull()
    expect(localStorage.getItem('otra-cosa')).toBe('se queda')
    expect(useFocusStore.getState().viewMode).toBe('standard')
    // El tema montado vuelve al de serie, no sólo el guardado.
    expect(temaOlvidado).toHaveBeenCalledTimes(1)
  })
})
