/**
 * El contrato de la sesión y el contexto que lo transporta, sin componentes (issue #47).
 *
 * Vive aparte de `AuthContext.tsx` por una razón concreta: **Fast Refresh sólo funciona si un
 * fichero exporta componentes y nada más**. Con el proveedor, el hook y el contexto en el mismo
 * módulo, cualquier cambio en uno de ellos remonta el árbol entero en desarrollo y se pierde el
 * estado de la pantalla en la que estabas. Es ergonomía, no corrección, pero es la que se paga
 * cien veces al día.
 *
 * Aquí no hay lógica: sólo los tipos, la clave de almacenamiento y el contexto. Quien consuma
 * esto sigue entrando por `@/shared/auth`, que es lo que hace que este corte no le cueste nada a
 * nadie: **ningún fichero importaba de `AuthContext` directamente**, se comprobó antes de mover.
 */
import { createContext } from 'react'

export interface AuthUser {
  user_id: string
  email: string
  role: string
  /** La contraseña la puso otra persona y está pendiente de cambio (issue #94). */
  cambio_pendiente: boolean
}

export interface AuthState {
  user: AuthUser | null
  isAuthenticated: boolean
  login: (token: string) => void
  logout: () => void
}

export const AuthContext = createContext<AuthState | null>(null)

/** Dónde vive el token. Lo leen el proveedor y el cliente de la API. */
export const TOKEN_KEY = 'access_token'

/**
 * Los datos de sesión que lleva el token, o `null` si no se puede confiar en él.
 *
 * Devuelve `null` también cuando el token **ha caducado**, y eso no es cortesía: sin esa
 * comprobación, una pestaña abierta desde ayer arrancaría con la sesión pintada y fallando en
 * cada petición, que es peor que pedir credenciales.
 */
export function parseJwtPayload(token: string): AuthUser | null {
  try {
    const base64 = token.split('.')[1]
    const json = atob(base64.replace(/-/g, '+').replace(/_/g, '/'))
    const payload = JSON.parse(json) as Record<string, unknown>
    const user_id = (payload['user_id'] ?? payload['sub']) as unknown
    const { email, role, exp } = payload
    if (typeof user_id !== 'string' || typeof email !== 'string' || typeof role !== 'string') {
      return null
    }
    if (typeof exp === 'number' && exp * 1000 < Date.now()) {
      return null
    }
    // Issue #94 — ausente es «nada pendiente», igual que lo lee el servidor: un token emitido
    // antes de esto no puede echar a nadie por no traer un claim que no existía.
    return { user_id, email, role, cambio_pendiente: payload['cambio_pendiente'] === true }
  } catch {
    return null
  }
}

export function loadStoredUser(): AuthUser | null {
  const token = localStorage.getItem(TOKEN_KEY)
  return token ? parseJwtPayload(token) : null
}
