/**
 * El proveedor de sesión, y sólo él (issue #47).
 *
 * El contexto, los tipos y el troceado del token están en `authState.ts`, y el hook en
 * `useAuth.ts`. El corte es por Fast Refresh: un fichero que exporta componentes **y otra cosa**
 * remonta el árbol entero en cada cambio, y se pierde el estado de la pantalla. Quien consume
 * esto entra por `@/shared/auth`, así que el reparto no se nota desde fuera.
 */
import { useState, useCallback, useEffect, type ReactNode } from 'react'

import {
  AuthContext,
  CLAVE_DE_LA_ULTIMA_PERSONA,
  TOKEN_KEY,
  loadStoredUser,
  parseJwtPayload,
  type AuthUser,
} from './authState'
import { SESION_CADUCADA } from './sesionCaducada'

export function AuthProvider({
  children,
  alCambiarDeSesion,
  alOlvidarALaPersona,
}: {
  children: ReactNode
  /**
   * Se llama al entrar y al salir. `App` vacía con esto la caché de consultas: sin ello, quien
   * entraba sin recargar veía los módulos y las acciones permitidas de la cuenta anterior
   * (#172, lo destapó la verificación en navegador). El proveedor no la vacía él mismo para no
   * depender de react-query, que no todos los que lo montan tienen.
   */
  alCambiarDeSesion?: () => void
  /**
   * Se llama al salir a propósito y al entrar otra persona, **no** cuando la sesión caduca: quien
   * está editando un informe y ve caducar su sesión vuelve a entrar y sigue con su borrador (#278).
   */
  alOlvidarALaPersona?: () => void
}) {
  const [user, setUser] = useState<AuthUser | null>(loadStoredUser)

  const login = useCallback((token: string) => {
    const parsed = parseJwtPayload(token)
    if (parsed) {
      const anterior = localStorage.getItem(CLAVE_DE_LA_ULTIMA_PERSONA)
      if (anterior && anterior !== parsed.user_id) alOlvidarALaPersona?.()
      localStorage.setItem(CLAVE_DE_LA_ULTIMA_PERSONA, parsed.user_id)
      localStorage.setItem(TOKEN_KEY, token)
      alCambiarDeSesion?.()
      setUser(parsed)
    }
  }, [alCambiarDeSesion, alOlvidarALaPersona])

  const salirSinOlvidar = useCallback(() => {
    localStorage.removeItem(TOKEN_KEY)
    alCambiarDeSesion?.()
    setUser(null)
  }, [alCambiarDeSesion])

  const logout = useCallback(() => {
    alOlvidarALaPersona?.()
    localStorage.removeItem(CLAVE_DE_LA_ULTIMA_PERSONA)
    salirSinOlvidar()
  }, [alOlvidarALaPersona, salirSinOlvidar])

  // #278 — el cliente avisa cuando el servidor deja de aceptar el token; salir lleva al login.
  // Sin olvidar nada: la sesión caducó, la persona no se ha ido.
  useEffect(() => {
    window.addEventListener(SESION_CADUCADA, salirSinOlvidar)
    return () => window.removeEventListener(SESION_CADUCADA, salirSinOlvidar)
  }, [salirSinOlvidar])

  return (
    <AuthContext.Provider value={{ user, isAuthenticated: user !== null, login, logout }}>
      {children}
    </AuthContext.Provider>
  )
}
