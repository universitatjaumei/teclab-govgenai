import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import {
  useGetCatalogoApiV1HubModulosCatalogoGet,
  useListConcesionesApiV1HubModulosGet,
  useConcederApiV1HubModulosPost,
  useRetirarApiV1HubModulosConcesionIdDelete,
  getListConcesionesApiV1HubModulosGetQueryKey,
} from '@/shared/api/generated/hub-modulos/hub-modulos'
import { useListUsersApiV1HubUsersGet } from '@/shared/api/generated/hub-users/hub-users'
import type { ConcesionRead } from '@/shared/api/generated/model'

/**
 * Conceder y retirar módulos, a una persona o a un grupo del IdP (IDE.5).
 *
 * Las concesiones eran filas de `hub_module_grants` que solo se ponían conectándose a Postgres.
 * Una plataforma que se entrega a otra administración no puede pedir eso: quien la administra no
 * tiene por qué tener acceso a la base de datos, y no debería tenerlo.
 *
 * **El catálogo de módulos se itera, no se escribe.** Los códigos vienen del servidor: si
 * estuvieran aquí, añadir un módulo exigiría tocar el frontend, que es justo lo que la regla del
 * catálogo-como-dato viene a evitar.
 *
 * **Retirar la concesión de un grupo afecta a todo el grupo**, así que se confirma con un
 * número y no con un «¿seguro?» a secas.
 */
export function ModulosPage() {
  const { t } = useTranslation('admin')
  const queryClient = useQueryClient()

  const { data: catalogo } = useGetCatalogoApiV1HubModulosCatalogoGet()
  const { data: concesiones } = useListConcesionesApiV1HubModulosGet()
  // MT.9 — el listado pasó a venir en un sobre con el recuento de lo que el filtro deja
  // fuera. Aquí no se filtra: esta pantalla concede módulos a cualquier persona.
  const { data: listado } = useListUsersApiV1HubUsersGet()
  const { mutate: conceder, isPending: concediendo } = useConcederApiV1HubModulosPost()
  const { mutate: retirar } = useRetirarApiV1HubModulosConcesionIdDelete()

  const invalidar = () =>
    void queryClient.invalidateQueries({
      queryKey: getListConcesionesApiV1HubModulosGetQueryKey(),
    })

  const [tipo, setTipo] = useState<'usuario' | 'grupo'>('grupo')
  const [sujeto, setSujeto] = useState('')
  const [modulo, setModulo] = useState('')

  // Un módulo de oficio lo tiene cualquier persona sin concesión: no se ofrece para conceder,
  // y se dice aparte para que nadie lo busque en las concesiones.
  const vigentes = (catalogo ?? []).filter((m) => m.vigente && !m.de_oficio)
  const deOficio = (catalogo ?? []).filter((m) => m.vigente && m.de_oficio)

  function enviar(evento: React.FormEvent) {
    evento.preventDefault()
    conceder(
      { data: { subject_type: tipo, subject_id: sujeto, module_code: modulo } },
      {
        onSuccess: () => {
          setSujeto('')
          setModulo('')
          invalidar()
        },
      }
    )
  }

  function quitar(concesion: ConcesionRead) {
    retirar({ concesionId: concesion.id }, { onSuccess: invalidar })
  }

  return (
    <div className="space-y-6">
      <header>
        <h2 className="text-lg font-semibold">{t('plataforma.modulos.titulo')}</h2>
        {/* El superadministrador no tiene fila: entra en todo por su rol. Dicho aquí para que
            nadie la busque en la tabla y crea que falta. */}
        <p className="text-sm text-muted-foreground">{t('plataforma.modulos.nota_superadmin')}</p>
        {/* Lo de oficio tampoco tiene fila: lo tiene todo el mundo. Dicho por la misma razón. */}
        {deOficio.length > 0 && (
          <p className="text-sm text-muted-foreground" data-testid="nota-de-oficio">
            {t('plataforma.modulos.nota_de_oficio', { modulos: deOficio.map((m) => m.label).join(', ') })}
          </p>
        )}
      </header>

      <form onSubmit={enviar} className="flex flex-wrap items-end gap-3 rounded-md border p-4">
        <div className="flex flex-col gap-1">
          <label htmlFor="concesion_tipo" className="text-sm font-medium">
            {t('plataforma.modulos.tipo')}
          </label>
          <select
            id="concesion_tipo"
            value={tipo}
            onChange={(e) => setTipo(e.target.value as 'usuario' | 'grupo')}
            className="rounded-md border px-2 py-1 text-sm"
          >
            <option value="grupo">{t('plataforma.modulos.tipos.grupo')}</option>
            <option value="usuario">{t('plataforma.modulos.tipos.usuario')}</option>
          </select>
        </div>

        <div className="flex flex-col gap-1">
          <label htmlFor="concesion_sujeto" className="text-sm font-medium">
            {tipo === 'grupo'
              ? t('plataforma.modulos.nombre_del_grupo')
              : t('plataforma.modulos.persona')}
          </label>
          {tipo === 'grupo' ? (
            <input
              id="concesion_sujeto"
              required
              value={sujeto}
              onChange={(e) => setSujeto(e.target.value)}
              className="rounded-md border px-2 py-1 text-sm"
            />
          ) : (
            <select
              id="concesion_sujeto"
              required
              value={sujeto}
              onChange={(e) => setSujeto(e.target.value)}
              className="rounded-md border px-2 py-1 text-sm"
            >
              <option value="">—</option>
              {(listado?.personas ?? []).map((p) => (
                <option key={p.id} value={p.id}>
                  {p.email}
                </option>
              ))}
            </select>
          )}
        </div>

        <div className="flex flex-col gap-1">
          <label htmlFor="concesion_modulo" className="text-sm font-medium">
            {t('plataforma.modulos.modulo')}
          </label>
          {/* Iterando el catálogo del servidor: los códigos no se escriben aquí. */}
          <select
            id="concesion_modulo"
            required
            value={modulo}
            onChange={(e) => setModulo(e.target.value)}
            className="rounded-md border px-2 py-1 text-sm"
          >
            <option value="">—</option>
            {vigentes.map((m) => (
              <option key={m.code} value={m.code}>
                {m.label}
              </option>
            ))}
          </select>
        </div>

        <button
          type="submit"
          disabled={concediendo}
          className="rounded-md bg-primary px-3 py-1.5 text-sm text-primary-foreground disabled:opacity-50"
        >
          {t('plataforma.modulos.conceder')}
        </button>

        {tipo === 'grupo' && (
          <p className="w-full text-xs text-muted-foreground">
            {t('plataforma.modulos.pista_grupo')}
          </p>
        )}
      </form>

      <table className="w-full text-sm">
        <thead>
          <tr className="border-b text-left">
            <th className="py-2">{t('plataforma.modulos.tipo')}</th>
            <th>{t('plataforma.modulos.sujeto')}</th>
            <th>{t('plataforma.modulos.modulo')}</th>
            <th>{t('plataforma.modulos.concedido_por')}</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {(concesiones ?? []).map((concesion) => (
            <tr key={concesion.id} className="border-b">
              <td className="py-2">
                {t(
                  `plataforma.modulos.tipos.${concesion.subject_type}` as Parameters<typeof t>[0]
                )}
              </td>
              <td>{concesion.subject_id}</td>
              <td>{concesion.module_code}</td>
              <td>{concesion.granted_by ?? '—'}</td>
              <td className="text-right">
                <button
                  type="button"
                  onClick={() => quitar(concesion)}
                  className="text-xs underline"
                >
                  {concesion.subject_type === 'grupo'
                    ? t('plataforma.modulos.retirar_del_grupo')
                    : t('plataforma.modulos.retirar')}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
