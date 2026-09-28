import { describe, it, expect, beforeAll, beforeEach, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'

import i18n from '@/shared/i18n'
import { AuthProvider, PrivateRoute } from '@/shared/auth'
import { parseJwtPayload, TOKEN_KEY } from '../authState'
import { useCambiarMiPassword } from '@/shared/api/generated/auth/auth'

/**
 * Issue #94 — la contraseña que restablece otra persona vale una sola vez.
 *
 * El servidor ya no deja hacer nada más con ese token (403 en todo salvo `/auth/me` y el propio
 * cambio). Lo que fija esta pantalla es que el panel **no se quede en una cascada de errores**:
 * con el cambio pendiente no se entra a ningún sitio, se pide la contraseña nueva y punto.
 *
 * **Quien manda es el token, no el componente.** El claim lo pone el servidor al emitirlo; aquí
 * sólo se lee, igual que se lee el rol.
 *
 * **Y al cambiarla se cierra la sesión.** El endpoint devuelve 204 y no un token nuevo, así que
 * el que hay en el navegador sigue llevando el pendiente dentro: reutilizarlo dejaría a la
 * persona encerrada en esta misma pantalla después de haber hecho lo que se le pedía.
 */
vi.mock('@/shared/api/generated/auth/auth', () => ({
  useCambiarMiPassword: vi.fn(),
}))

const cambiar = vi.fn()

function conMutacion({ isError = false, isPending = false } = {}) {
  vi.mocked(useCambiarMiPassword).mockReturnValue({
    mutate: cambiar,
    isPending,
    isError,
  } as never)
}

/** Un token con la forma que emite el servidor, sin firmar: sólo se lee la carga. */
function token({ pendiente }: { pendiente: boolean }) {
  const carga: Record<string, unknown> = {
    user_id: 'u-1',
    email: 'persona@uji.es',
    role: 'user',
    exp: Math.floor(Date.now() / 1000) + 3600,
  }
  if (pendiente) carga.cambio_pendiente = true
  const b64 = (o: unknown) => btoa(JSON.stringify(o)).replace(/=+$/, '')
  return `${b64({ alg: 'HS256' })}.${b64(carga)}.firma`
}

function pintarPanel() {
  render(
    <AuthProvider>
      <MemoryRouter initialEntries={['/admin']}>
        <Routes>
          <Route element={<PrivateRoute />}>
            <Route path="/admin" element={<p>El panel de siempre</p>} />
          </Route>
          <Route path="/login" element={<p>La pantalla de entrada</p>} />
        </Routes>
      </MemoryRouter>
    </AuthProvider>,
  )
}

beforeAll(async () => {
  await i18n.changeLanguage('es')
})

beforeEach(() => {
  localStorage.clear()
  cambiar.mockClear()
  conMutacion()
})

describe('#94 — el token dice si el cambio está pendiente', () => {
  it('should_read_the_pending_claim_from_the_token', () => {
    expect(parseJwtPayload(token({ pendiente: true }))?.cambio_pendiente).toBe(true)
  })

  it('should_default_to_not_pending_when_the_claim_is_absent', () => {
    // Un token emitido antes de esto no puede echar a nadie por no traer un claim que no existía.
    expect(parseJwtPayload(token({ pendiente: false }))?.cambio_pendiente).toBe(false)
  })
})

describe('#94 — con el cambio pendiente no se entra a ningún sitio', () => {
  it('should_replace_the_panel_with_the_forced_change', () => {
    localStorage.setItem(TOKEN_KEY, token({ pendiente: true }))

    pintarPanel()

    expect(screen.queryByText('El panel de siempre')).toBeNull()
    expect(screen.getByLabelText(/contraseña nueva/i)).toBeDefined()
  })

  it('should_ask_for_the_current_one_too', () => {
    // El servidor la exige también aquí (USR.7), y no es ceremonia duplicada: es la única ruta
    // de cambio que hay, y con el token basta para actuar pero no para quedarse la cuenta.
    localStorage.setItem(TOKEN_KEY, token({ pendiente: true }))

    pintarPanel()

    expect(screen.getByLabelText(/contraseña actual/i)).toBeDefined()
  })

  it('should_leave_everyone_else_alone', () => {
    // Sin esto, lo de arriba se cumpliría tapando el panel a todo el mundo.
    localStorage.setItem(TOKEN_KEY, token({ pendiente: false }))

    pintarPanel()

    expect(screen.getByText('El panel de siempre')).toBeDefined()
  })

  it('should_end_the_session_once_changed', async () => {
    localStorage.setItem(TOKEN_KEY, token({ pendiente: true }))
    cambiar.mockImplementation((_datos, opciones) => opciones?.onSuccess?.())

    pintarPanel()
    fireEvent.change(screen.getByLabelText(/contraseña actual/i), {
      target: { value: 'la-que-me-pusieron' },
    })
    fireEvent.change(screen.getByLabelText(/contraseña nueva/i), {
      target: { value: 'la-mia-de-verdad-1234' },
    })
    fireEvent.click(screen.getByRole('button', { name: /guardar/i }))

    // **Se espera a la pantalla de entrada, no al token**, aunque el token se borre antes: la
    // navegación de react-router va dentro de una transición, y esperar por algo que ya es
    // cierto devuelve el control con la transición a medias y el árbol pintado en blanco.
    await waitFor(() => {
      expect(screen.getByText('La pantalla de entrada')).toBeDefined()
    })
    expect(localStorage.getItem(TOKEN_KEY)).toBeNull()
  })
})
