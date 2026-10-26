import { useGetMeApiV1AuthMeGet } from '@/shared/api/generated/auth/auth'
import { UsuarioActualIdentityRoleAuthority } from '@/shared/api/generated/model'

/**
 * Quién manda sobre el rol en este despliegue (IDE.1).
 *
 * Lo dice el servidor, como los módulos concedidos: adivinarlo en el cliente sería inventarlo,
 * y de ese dato depende que la pantalla de personas avise —o no— de que editar un rol a mano no
 * sirve de nada porque lo pisa el siguiente inicio de sesión.
 *
 * Mientras no se sabe se asume `app`, que es el defecto del servidor: enseñar el aviso durante
 * la carga y quitarlo después haría parpadear una advertencia que puede no aplicar.
 */
export function useAutoridadDelRol(): UsuarioActualIdentityRoleAuthority {
  const { data } = useGetMeApiV1AuthMeGet()
  return data?.identity_role_authority ?? UsuarioActualIdentityRoleAuthority.app
}
