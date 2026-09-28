import { useTranslation } from 'react-i18next'
import { useForm } from 'react-hook-form'
import { z } from 'zod'
import { zodResolver } from '@hookform/resolvers/zod'

import { useCambiarMiPassword } from '@/shared/api/generated/auth/auth'
import { useAuth } from './useAuth'

/** El mínimo del contrato del servidor (`MINIMO_CONTRASENA` en `auth_router.py`). */
const MINIMO = 12

const esquema = z.object({
  password_actual: z.string().min(1),
  password_nueva: z.string().min(MINIMO),
})
type Valores = z.infer<typeof esquema>

/**
 * La puerta que hay que pasar cuando la contraseña la puso otra persona (issue #94).
 *
 * **No es un aviso, es lo único que hay.** El servidor responde 403 a todo lo demás mientras el
 * cambio siga pendiente, así que un panel que dejara navegar sólo enseñaría una cascada de
 * errores. Aquí se sustituye entero.
 *
 * **Pide también la actual** —la que acaban de darle— porque es lo que `cambiarMiPassword`
 * exige, y esa exigencia es de USR.7: con el token basta para actuar, pero no tiene que bastar
 * para quedarse la cuenta.
 *
 * **Al terminar cierra la sesión.** El endpoint devuelve 204 y no un token nuevo, y el que está
 * en el navegador sigue llevando el pendiente dentro: reutilizarlo devolvería a esta misma
 * pantalla a quien ya ha hecho lo que se le pedía. Se vuelve a entrar, con la suya.
 */
export function CambioObligatorio() {
  const { t } = useTranslation('auth')
  const { logout } = useAuth()
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<Valores>({ resolver: zodResolver(esquema) })

  const { mutate, isPending, isError } = useCambiarMiPassword()

  const enviar = handleSubmit((valores) => {
    mutate({ data: valores }, { onSuccess: () => logout() })
    // El valor no se queda en el formulario ni cuando falla: es una contraseña, no un borrador.
    reset({ password_actual: '', password_nueva: '' })
  })

  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col justify-center gap-4 px-6">
      <h1 className="text-lg font-semibold">{t('cambio_obligatorio.titulo')}</h1>
      <p className="text-sm opacity-80">{t('cambio_obligatorio.motivo')}</p>

      <form onSubmit={enviar} className="space-y-3">
        <div className="space-y-1">
          <label htmlFor="obligatorio_actual" className="block text-sm">
            {t('cambiar_contrasena.actual')}
          </label>
          <input
            id="obligatorio_actual"
            type="password"
            autoComplete="current-password"
            {...register('password_actual')}
            className="w-full rounded-md border px-2 py-1 text-sm text-foreground"
          />
        </div>
        <div className="space-y-1">
          <label htmlFor="obligatorio_nueva" className="block text-sm">
            {t('cambiar_contrasena.nueva')}
          </label>
          <input
            id="obligatorio_nueva"
            type="password"
            autoComplete="new-password"
            {...register('password_nueva')}
            className="w-full rounded-md border px-2 py-1 text-sm text-foreground"
          />
        </div>
        {errors.password_nueva && (
          <p role="alert" className="text-sm">
            {t('cambiar_contrasena.corta', { minimo: MINIMO })}
          </p>
        )}
        {isError && (
          <p role="alert" className="text-sm">
            {t('cambiar_contrasena.actual_incorrecta')}
          </p>
        )}
        <button
          type="submit"
          disabled={isPending}
          className="rounded-md border px-3 py-1 text-sm disabled:opacity-50"
        >
          {t('cambiar_contrasena.guardar')}
        </button>
      </form>
    </main>
  )
}
