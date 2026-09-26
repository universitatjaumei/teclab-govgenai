import { useEffect, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { useForm } from 'react-hook-form'
import { z } from 'zod'
import { zodResolver } from '@hookform/resolvers/zod'
import {
  useListUsersApiV1HubUsersGet,
  useCreateUserApiV1HubUsersPost,
  useUpdateUserApiV1HubUsersUserIdPatch,
  useDeleteUserApiV1HubUsersUserIdDelete,
  useSetUsuarioPassword,
  useCapacidadesDePersonas,
  getListUsersApiV1HubUsersGetQueryKey,
} from '@/shared/api/generated/hub-users/hub-users'
import { useGetCatalogoApiV1HubModulosCatalogoGet } from '@/shared/api/generated/hub-modulos/hub-modulos'
import type { UsuarioRead } from '@/shared/api/generated/model'
import { useAutoridadDelRol } from '@/shared/auth/useAutoridadDelRol'
import { useOrganizacionElegida } from '@/shared/organizacion/useOrganizacionElegida'

/** El `origen` de las cuentas que vienen de `superadminaccount` y no de `hub_users` (REV.8). */
const ORIGEN_DE_ARRANQUE = 'superadmin'

/** Los roles que ofrece el alta. Salen del contrato del servidor, que los valida. */
const ROLES = ['user', 'informer', 'admin', 'superadmin'] as const

/** El mínimo del contrato (`SetPasswordRequest.min_length`), dicho antes de gastar una petición.
 *
 *  No es una regla nueva del cliente: es la misma del servidor, alineada a mano porque el
 *  esquema generado no trae el `minLength` de Pydantic. Si un día divergen, la que manda es la
 *  del servidor —el 422— y esto sólo deja de avisar antes. */
const MINIMO_CONTRASENA = 12

const esquemaContrasena = z.object({
  password: z.string().min(MINIMO_CONTRASENA),
})
type ValoresContrasena = z.infer<typeof esquemaContrasena>

/**
 * Quién existe en esta plataforma (IDE.4).
 *
 * No había ninguna pantalla de usuarios: para saber quién tenía cuenta, con qué rol o si había
 * entrado alguna vez hacía falta acceso a Postgres — que es justo lo que no se le puede pedir a
 * otra administración que despliegue esto.
 *
 * **Dos cosas que la pantalla dice y no solo hace.** Con la autoridad del rol en el IdP, editar
 * un rol a mano es tirar el trabajo porque lo pisa el siguiente inicio de sesión: se avisa en
 * vez de dejar que se descubra solo. Y el listado **no son todas las cuentas** —siguen
 * existiendo `SuperAdminAccount`, `AdminAccount` y `ClientAccount` sin unificar (IDE.2)—, así
 * que se dice, porque un listado que se lee como completo miente por omisión.
 */
export function UsuariosPage() {
  const { t } = useTranslation('admin')
  // Quién manda sobre el rol lo dice el servidor (IDE.1), como los módulos concedidos.
  const autoridadDelRol = useAutoridadDelRol()
  const queryClient = useQueryClient()
  const { data: personas, isLoading } = useListUsersApiV1HubUsersGet()
  /**
   * Qué puede hacer **quien mira** (USR.9). Lo dice el servidor y la pantalla itera.
   *
   * Desde USR.9 esta pantalla la comparten dos clases de administrador: quien administra la
   * plataforma y quien administra una organización. El segundo puede listar y fijar
   * contraseñas, y no crear personas, cambiar roles ni borrar —quien puede crear personas con
   * rol puede crearse un admin—. Ese reparto **no se calcula aquí**: un `rol === 'superadmin'`
   * sería la autorización escrita por segunda vez, y es la misma razón por la que
   * `puede_borrarse` y `puede_fijar_contrasena` viajan en cada fila.
   *
   * Mientras la respuesta no ha llegado no se concede nada: enseñar el formulario de alta y
   * quitarlo después es peor que enseñarlo un instante más tarde.
   */
  const { data: capacidades } = useCapacidadesDePersonas()
  const puede = (accion: string) =>
    (capacidades?.acciones_permitidas ?? []).includes(accion)
  const invalidar = () =>
    void queryClient.invalidateQueries({ queryKey: getListUsersApiV1HubUsersGetQueryKey() })

  const { mutate: crear, isPending: creando } = useCreateUserApiV1HubUsersPost()
  const { mutate: actualizar } = useUpdateUserApiV1HubUsersUserIdPatch()
  const { mutate: eliminar } = useDeleteUserApiV1HubUsersUserIdDelete()

  const [email, setEmail] = useState('')
  const [rol, setRol] = useState<string>('user')
  const [nombre, setNombre] = useState('')
  // Los módulos que se conceden en el mismo acto (issue #100). Conceder vivía sólo en
  // Plataforma → Módulos, o sea un segundo viaje, y el segundo viaje se olvida: en producción
  // la tabla de concesiones estuvo vacía semanas y nadie podía entrar en nada.
  const [modulosDelAlta, setModulosDelAlta] = useState<string[]>([])
  // El catálogo es dato del servidor. Si los códigos estuvieran escritos aquí, añadir un módulo
  // exigiría tocar el frontend, que es lo que la regla del catálogo-como-dato viene a evitar.
  //
  // **Sólo se pide a quien puede crear.** `get_catalogo` está protegido con
  // `_require_superadmin`, y esta pantalla también la ven los administradores de organización
  // —listan personas y fijan contraseñas (USR.9)—. Sin la condición, el hook les disparaba un
  // 403 en cada carga con los reintentos de React Query encima. Y la condición sale de lo que
  // el servidor concede, no de un `rol === 'superadmin'` escrito aquí.
  const { data: catalogoDeModulos } = useGetCatalogoApiV1HubModulosCatalogoGet({
    query: { enabled: puede('crear') },
  })
  const modulosVigentes = (catalogoDeModulos ?? []).filter((m) => m.vigente)

  function alternarModulo(codigo: string) {
    setModulosDelAlta((antes) =>
      antes.includes(codigo) ? antes.filter((c) => c !== codigo) : [...antes, codigo]
    )
  }
  /** La fila que espera confirmación de borrado. Estado de la pantalla, no del servidor. */
  const [porConfirmar, setPorConfirmar] = useState<string | null>(null)
  /** La fila cuyo formulario de contraseña está abierto, y la que acaba de guardarla (USR.3). */
  const [conFormularioAbierto, setConFormularioAbierto] = useState<string | null>(null)
  const [contrasenaFijadaEn, setContrasenaFijadaEn] = useState<string | null>(null)
  const { mutate: fijarContrasena, isPending: fijando } = useSetUsuarioPassword()
  const {
    register: registrarContrasena,
    handleSubmit: enviarContrasena,
    reset: limpiarContrasena,
    formState: { errors: erroresContrasena },
  } = useForm<ValoresContrasena>({ resolver: zodResolver(esquemaContrasena) })
  /** El alta arranca en la organizacion sobre la que ya se esta trabajando (REV.10). */
  const { organizaciones, elegida } = useOrganizacionElegida()
  const [organizacionDelAlta, setOrganizacionDelAlta] = useState('')
  useEffect(() => {
    if (!organizacionDelAlta && elegida) setOrganizacionDelAlta(elegida)
  }, [elegida, organizacionDelAlta])

  /**
   * El nombre de la organización de una fila, o que no tiene ninguna (REV.10).
   *
   * «Sin organización» y no una celda vacía: es una fila que hay que arreglar, no un dato que
   * falte. Y si el id apunta a algo que ya no está, se enseña el id en bruto en vez de
   * esconderlo: es la pista de que hay una fila huérfana.
   */
  function nombreDeOrganizacion(id: string | null | undefined): string {
    if (!id) return t('plataforma.usuarios.sin_organizacion')
    return organizaciones.find((o) => o.id === id)?.name ?? id
  }

  function darDeAlta(evento: React.FormEvent) {
    evento.preventDefault()
    crear(
      {
        data: {
          email,
          role: rol,
          display_name: nombre || null,
          organizacion_id: organizacionDelAlta || null,
          modulos: modulosDelAlta,
        },
      },
      {
        onSuccess: () => {
          setEmail('')
          setNombre('')
          setRol('user')
          setModulosDelAlta([])
          invalidar()
        },
      }
    )
  }

  function borrarPersona(persona: UsuarioRead) {
    setPorConfirmar(null)
    eliminar({ userId: persona.id }, { onSuccess: invalidar })
  }

  function cambiarActividad(persona: UsuarioRead) {
    actualizar(
      { userId: persona.id, data: { is_active: !persona.is_active } },
      { onSuccess: invalidar }
    )
  }

  function abrirContrasena(persona: UsuarioRead) {
    setContrasenaFijadaEn(null)
    limpiarContrasena({ password: '' })
    setConFormularioAbierto(persona.id)
  }

  function cerrarContrasena() {
    limpiarContrasena({ password: '' })
    setConFormularioAbierto(null)
  }

  /** Guarda la contraseña de esa fila. **El valor no se vuelve a mostrar**: se limpia el campo
   *  y lo que queda es la confirmación de que se guardó. Enseñarlo «para copiarlo» lo dejaría
   *  en el DOM y en el portapapeles de quien administra. */
  function guardarContrasena(persona: UsuarioRead) {
    return enviarContrasena((valores) => {
      fijarContrasena(
        { userId: persona.id, data: { password: valores.password } },
        {
          onSuccess: () => {
            setContrasenaFijadaEn(persona.id)
            cerrarContrasena()
            invalidar()
          },
        }
      )
      limpiarContrasena({ password: '' })
    })
  }

  return (
    <div className="space-y-6">
      {/* USR.9 — la misma pantalla la ven dos clases de administrador y no ven lo mismo. A
          quien administra una organización, «Personas de la plataforma» le nombra algo que no
          es lo que tiene delante: su listado está acotado a sus organizaciones. El criterio
          sale de la capacidad que el servidor concede, no de un `rol ===`. */}
      <header>
        <h2 className="text-lg font-semibold">
          {puede('crear')
            ? t('plataforma.usuarios.titulo')
            : t('plataforma.usuarios.titulo_organizacion')}
        </h2>
        <p className="text-sm text-muted-foreground">
          {puede('crear')
            ? t('plataforma.usuarios.alcance')
            : t('plataforma.usuarios.alcance_organizacion')}
        </p>
      </header>

      {autoridadDelRol === 'idp' && (
        <p role="status" className="rounded-md border border-warning/40 bg-warning/10 p-3 text-sm">
          {t('plataforma.usuarios.aviso_autoridad_idp')}
        </p>
      )}

      {puede('crear') && (
      <form onSubmit={darDeAlta} className="flex flex-wrap items-end gap-3 rounded-md border p-4">
        <div className="flex flex-col gap-1">
          <label htmlFor="usuario_email" className="text-sm font-medium">
            {t('plataforma.usuarios.correo')}
          </label>
          <input
            id="usuario_email"
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="rounded-md border px-2 py-1 text-sm"
          />
        </div>
        <div className="flex flex-col gap-1">
          <label htmlFor="usuario_nombre" className="text-sm font-medium">
            {t('plataforma.usuarios.nombre')}
          </label>
          <input
            id="usuario_nombre"
            value={nombre}
            onChange={(e) => setNombre(e.target.value)}
            className="rounded-md border px-2 py-1 text-sm"
          />
        </div>
        <div className="flex flex-col gap-1">
          <label htmlFor="usuario_rol" className="text-sm font-medium">
            {t('plataforma.usuarios.rol')}
          </label>
          <select
            id="usuario_rol"
            value={rol}
            onChange={(e) => setRol(e.target.value)}
            className="rounded-md border px-2 py-1 text-sm"
          >
            {ROLES.map((r) => (
              <option key={r} value={r}>
                {t(`plataforma.usuarios.roles.${r}` as Parameters<typeof t>[0])}
              </option>
            ))}
          </select>
        </div>
        {organizaciones.length > 0 && (
          <div className="flex flex-col gap-1">
            <label htmlFor="usuario_organizacion" className="text-sm font-medium">
              {t('plataforma.usuarios.organizacion')}
            </label>
            <select
              id="usuario_organizacion"
              value={organizacionDelAlta}
              onChange={(e) => setOrganizacionDelAlta(e.target.value)}
              className="rounded-md border px-2 py-1 text-sm"
            >
              {organizaciones.map((o) => (
                <option key={o.id} value={o.id}>{o.name}</option>
              ))}
            </select>
          </div>
        )}
        {modulosVigentes.length > 0 && (
          <fieldset className="flex w-full flex-col gap-1">
            <legend className="text-sm font-medium">
              {t('plataforma.usuarios.modulos_del_alta')}
            </legend>
            {/* Iterando el catálogo del servidor: los códigos no se escriben aquí. */}
            <div className="flex flex-wrap gap-x-4 gap-y-1">
              {modulosVigentes.map((m) => (
                <label key={m.code} className="flex items-center gap-1.5 text-sm">
                  <input
                    type="checkbox"
                    checked={modulosDelAlta.includes(m.code)}
                    onChange={() => alternarModulo(m.code)}
                  />
                  {m.label}
                </label>
              ))}
            </div>
            <p className="text-xs text-muted-foreground">
              {t('plataforma.usuarios.pista_modulos')}
            </p>
          </fieldset>
        )}

        <button
          type="submit"
          disabled={creando}
          className="rounded-md bg-primary px-3 py-1.5 text-sm text-primary-foreground disabled:opacity-50"
        >
          {t('plataforma.usuarios.dar_de_alta')}
        </button>
        {/* Sin campo de contraseña: el alta crea identidad y permisos, no una credencial.
            Quien entra, entra por SSO. Dicho aquí porque la ausencia se lee como un olvido. */}
        <p className="w-full text-xs text-muted-foreground">
          {t('plataforma.usuarios.sin_contrasena')}
        </p>
      </form>
      )}

      {isLoading ? (
        <p>{t('plataforma.usuarios.cargando')}</p>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b text-left">
              <th className="py-2">{t('plataforma.usuarios.correo')}</th>
              <th>{t('plataforma.usuarios.nombre')}</th>
              <th>{t('plataforma.usuarios.rol')}</th>
              <th>{t('plataforma.usuarios.organizacion')}</th>
              <th>{t('plataforma.usuarios.origen')}</th>
              <th>{t('plataforma.usuarios.modulos')}</th>
              <th>{t('plataforma.usuarios.ultimo_acceso')}</th>
              <th>{t('plataforma.usuarios.estado')}</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {(personas ?? []).map((persona) => (
              <tr
                key={persona.id}
                data-testid={`persona-${persona.email}`}
                className="border-b"
              >
                <td className="py-2">{persona.email}</td>
                <td>{persona.display_name ?? '—'}</td>
                <td>{t(`plataforma.usuarios.roles.${persona.role}` as Parameters<typeof t>[0])}</td>
                {/* REV.10 — la columna que faltaba. `organizacion_id` existía con su clave
                    ajena desde AUTH.2 y la pantalla ni lo enseñaba ni lo pedía, así que se
                    podía dar de alta a gente sin organización sin enterarse. «Sin
                    organización» y no una celda vacía: es una fila que arreglar, no un dato
                    que falte. */}
                <td>{nombreDeOrganizacion(persona.organizacion_id)}</td>
                <td>{t(`plataforma.usuarios.origenes.${persona.origen}` as Parameters<typeof t>[0])}</td>
                {/* En qué módulos puede entrar, y el aviso si en ninguno (issue #100).

                    **El aviso lo decide el servidor**, en `sin_concesion_directa`. Aquí no se
                    mira `modulos_concedidos.length === 0`: el superadministrador entra por su
                    rol con la lista vacía, y esa regla vive en el servidor. Escribirla aquí
                    sería tenerla dos veces. */}
                <td data-testid={`modulos-${persona.id}`}>
                  {persona.sin_concesion_directa ? (
                    <span
                      data-testid={`sin-concesion-directa-${persona.id}`}
                      className="rounded bg-amber-100 px-1.5 py-0.5 text-xs text-amber-900"
                      title={t('plataforma.usuarios.sin_concesion_directa_ayuda')}
                    >
                      {t('plataforma.usuarios.sin_concesion_directa')}
                    </span>
                  ) : (persona.modulos_concedidos ?? []).length > 0 ? (
                    (persona.modulos_concedidos ?? []).join(', ')
                  ) : (
                    '—'
                  )}
                </td>
                {/* «Nunca» y no una celda vacía: que alguien no haya entrado todavía es lo
                    normal en una fila creada a mano, no un dato que falte. */}
                <td>
                  {persona.last_login_at
                    ? new Date(persona.last_login_at).toLocaleDateString()
                    : t('plataforma.usuarios.nunca_entro')}
                </td>
                <td>
                  {persona.is_active
                    ? t('plataforma.usuarios.activa')
                    : t('plataforma.usuarios.desactivada')}
                </td>
                <td className="space-y-1 text-right">
                  {porConfirmar === persona.id ? (
                    /* Confirmación en la propia fila: borrar es la única acción de esta
                       pantalla que no se puede deshacer. */
                    <span className="flex flex-wrap items-center justify-end gap-2">
                      <span className="text-xs text-muted-foreground">
                        {t('plataforma.usuarios.confirmar_pregunta')}
                      </span>
                      <button
                        type="button"
                        onClick={() => borrarPersona(persona)}
                        className="text-xs font-medium text-destructive underline"
                      >
                        {t('plataforma.usuarios.confirmar')}
                      </button>
                      <button
                        type="button"
                        onClick={() => setPorConfirmar(null)}
                        className="text-xs underline"
                      >
                        {t('plataforma.usuarios.cancelar')}
                      </button>
                    </span>
                  ) : (
                    <span className="flex flex-wrap items-center justify-end gap-3">
                      {/* La cuenta de arranque vive en otra tabla: desactivarla desde aquí
                          daría un 404 y parecería un fallo de la pantalla. */}
                      {puede('editar') && persona.origen !== ORIGEN_DE_ARRANQUE && (
                        <button
                          type="button"
                          onClick={() => cambiarActividad(persona)}
                          className="text-xs underline"
                        >
                          {persona.is_active
                            ? t('plataforma.usuarios.desactivar')
                            : t('plataforma.usuarios.reactivar')}
                        </button>
                      )}
                      {/* **Lo decide el servidor**, no esta pantalla: `puede_borrarse` viene en
                          el contrato. Calcularlo aquí por `last_login_at` pondría la misma
                          regla en dos sitios, y un día dirían cosas distintas. */}
                      {puede('borrar') && persona.puede_borrarse && (
                        <button
                          type="button"
                          onClick={() => setPorConfirmar(persona.id)}
                          className="text-xs text-destructive underline"
                        >
                          {t('plataforma.usuarios.eliminar')}
                        </button>
                      )}
                      {/* USR.3 — **lo decide el servidor**: `puede_fijar_contrasena` viene en
                          el contrato, calculado con la misma función que autoriza el endpoint.
                          Un `if (rol === 'superadmin')` aquí sería la autorización escrita por
                          segunda vez. */}
                      {persona.puede_fijar_contrasena && (
                        <button
                          type="button"
                          onClick={() => abrirContrasena(persona)}
                          className="text-xs underline"
                        >
                          {t('plataforma.usuarios.fijar_contrasena')}
                        </button>
                      )}
                    </span>
                  )}
                  {conFormularioAbierto === persona.id && (
                    <form
                      onSubmit={guardarContrasena(persona)}
                      className="mt-1 flex flex-wrap items-end justify-end gap-2"
                    >
                      <span className="flex flex-col gap-1 text-left">
                        <label
                          htmlFor={`contrasena-${persona.id}`}
                          className="text-xs font-medium"
                        >
                          {t('plataforma.usuarios.contrasena_nueva')}
                        </label>
                        <input
                          id={`contrasena-${persona.id}`}
                          type="password"
                          autoComplete="new-password"
                          {...registrarContrasena('password')}
                          className="rounded-md border px-2 py-1 text-sm"
                        />
                      </span>
                      <button
                        type="submit"
                        disabled={fijando}
                        className="text-xs font-medium underline disabled:opacity-50"
                      >
                        {t('plataforma.usuarios.guardar_contrasena')}
                      </button>
                      <button type="button" onClick={cerrarContrasena} className="text-xs underline">
                        {t('plataforma.usuarios.cancelar')}
                      </button>
                      {erroresContrasena.password && (
                        <span role="alert" className="block w-full text-xs text-destructive">
                          {t('plataforma.usuarios.contrasena_corta', { minimo: MINIMO_CONTRASENA })}
                        </span>
                      )}
                    </form>
                  )}
                  {/* La confirmación, y no el valor: lo que se guardó no se vuelve a enseñar. */}
                  {contrasenaFijadaEn === persona.id && (
                    <span role="status" className="block text-xs text-muted-foreground">
                      {t('plataforma.usuarios.contrasena_fijada')}
                    </span>
                  )}
                  {/* El motivo, y no sólo la ausencia del botón: una fila sin acciones y sin
                      explicación se lee como «aquí no se puede hacer nada», y quien administra
                      no sabe si es una regla o algo roto. */}
                  {!persona.puede_borrarse && persona.motivo_no_borrable && (
                    <span className="block text-xs text-muted-foreground">
                      {persona.motivo_no_borrable}
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
