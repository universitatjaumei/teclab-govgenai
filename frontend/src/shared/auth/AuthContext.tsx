/**
 * El proveedor de sesión, y sólo él (issue #47).
 *
 * El contexto, los tipos y el troceado del token están en `authState.ts`, y el hook en
 * `useAuth.ts`. El corte es por Fast Refresh: un fichero que exporta componentes **y otra cosa**
 * remonta el árbol entero en cada cambio, y se pierde el estado de la pantalla. Quien consume
 * esto entra por `@/shared/auth`, así que el reparto no se nota desde fuera.
 */
import { useState, useCallback, type ReactNode } from 'react'

import { AuthContext, TOKEN_KEY, loadStoredUser, parseJwtPayload, type AuthUser } from './authState'

export function AuthProvider({
  children,
  alCambiarDeSesion,
}: {
  children: ReactNode
  /**
   * Se llama al entrar y al salir. `App` vacía con esto la caché de consultas: sin ello, quien
   * entraba sin recargar veía los módulos y las acciones permitidas de la cuenta anterior
   * (#172, lo destapó la verificación en navegador). El proveedor no la vacía él mismo para no
   * depender de react-query, que no todos los que lo montan tienen.
   */
  alCambiarDeSesion?: () => void
}) {
  const [user, setUser] = useState<AuthUser | null>(loadStoredUser)

  const login = useCallback((token: string) => {
    const parsed = parseJwtPayload(token)
    if (parsed) {
      localStorage.setItem(TOKEN_KEY, token)
      alCambiarDeSesion?.()
      setUser(parsed)
    }
  }, [alCambiarDeSesion])

  const logout = useCallback(() => {
    localStorage.removeItem(TOKEN_KEY)
    alCambiarDeSesion?.()
    setUser(null)
  }, [alCambiarDeSesion])

  return (
    <AuthContext.Provider value={{ user, isAuthenticated: user !== null, login, logout }}>
      {children}
    </AuthContext.Provider>
  )
}
