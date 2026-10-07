import { describe, it, expect, beforeEach, beforeAll, vi } from 'vitest'
import { render, screen, within, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import i18n from '@/shared/i18n'
import { UsuariosPage } from '../pages/UsuariosPage'
import {
  useListUsersApiV1HubUsersGet,
  useCreateUserApiV1HubUsersPost,
  useUpdateUserApiV1HubUsersUserIdPatch,
  useDeleteUserApiV1HubUsersUserIdDelete as useBorrar,
  useSetUsuarioPassword,
  useCapacidadesDePersonas,
} from '@/shared/api/generated/hub-users/hub-users'
import type { UsuarioRead } from '@/shared/api/generated/model'
import { useAutoridadDelRol } from '@/shared/auth/useAutoridadDelRol'
import { useOrganizacionElegida } from '@/shared/organizacion/useOrganizacionElegida'

/**
 * IDE.4 — quién existe en esta plataforma.
 *
 * No había ninguna pantalla de usuarios: quien administra no sabía quién tenía cuenta, ni con
 * qué rol, ni si había entrado alguna vez, y para averiguarlo necesitaba acceso a Postgres —
 * que es justo lo que no se le puede pedir a otra administración que despliegue esto.
 *
 * Dos cosas que la pantalla tiene que **decir**, no solo hacer:
 *
 * - **Quién manda sobre el rol en este despliegue.** Con `IDENTITY_ROLE_AUTHORITY=idp`, editar
 *   el rol a mano es tirar el trabajo: lo pisa el siguiente inicio de sesión. La pantalla lo
 *   avisa en vez de dejar que se descubra solo.
 * - **Que este listado no son todas las cuentas.** Las otras tres tablas de identidad siguen
 *   sin unificar (IDE.2), y un listado que se lee como completo miente por omisión.
 */
vi.mock('@/shared/api/generated/hub-users/hub-users', () => ({
  useListUsersApiV1HubUsersGet: vi.fn(),
  useCreateUserApiV1HubUsersPost: vi.fn(),
  useUpdateUserApiV1HubUsersUserIdPatch: vi.fn(),
  useDeleteUserApiV1HubUsersUserIdDelete: vi.fn(),
  useSetUsuarioPassword: vi.fn(),
  useCapacidadesDePersonas: vi.fn(),
  getListUsersApiV1HubUsersGetQueryKey: () => ['usuarios'],
}))

// La autoridad del rol la resuelve la pantalla contra el servidor, no la recibe por prop: un
// componente de ruta tiene que poder cargarse por separado (CAL.5), y un envoltorio en
// `App.tsx` que le pasara el dato rompía esa carga perezosa.
vi.mock('@/shared/auth/useAutoridadDelRol', () => ({
  useAutoridadDelRol: vi.fn(),
}))

vi.mock('@/shared/api/generated/hub-organizaciones/hub-organizaciones', () => ({
  useListOrganizacionesApiV1HubOrganizacionesGet: () => ({
    data: [
      { id: 'org-uji', name: 'Universitat Jaume I' },
      { id: 'org-dipu', name: 'Diputación de Castellón' },
    ],
  }),
}))

const PERSONAS: UsuarioRead[] = [
  {
    id: '11111111-1111-1111-1111-111111111111',
    email: 'manual@uji.es',
    display_name: 'Alta Manual',
    role: 'admin',
    organizacion_id: null,
    is_active: true,
    origen: 'manual',
    created_at: '2026-08-22T09:00:00Z',
    created_by: 'root',
    last_login_at: null,
    puede_borrarse: true,
    motivo_no_borrable: null,
    puede_fijar_contrasena: true,
  },
  {
    id: '22222222-2222-2222-2222-222222222222',
    email: 'porsso@uji.es',
    display_name: 'Llegó Por SSO',
    role: 'user',
    organizacion_id: null,
    is_active: false,
    origen: 'sso',
    created_at: '2026-08-01T09:00:00Z',
    created_by: null,
    last_login_at: '2026-08-20T10:00:00Z',
    puede_borrarse: false,
    motivo_no_borrable: 'Esta persona ya ha entrado.',
    puede_fijar_contrasena: true,
  },
]

const mutar = vi.fn()
const borrar = vi.fn()
const fijarContrasena = vi.fn()

function conPersonas(
  personas: UsuarioRead[] = PERSONAS,
  autoridad = 'app',
  fuera = 0,
) {
  vi.mocked(useListUsersApiV1HubUsersGet).mockReturnValue({
    // MT.9 — el listado viene en un sobre con el recuento de lo que el filtro deja fuera.
    data: { personas, de_plataforma_no_mostradas: fuera },
    isLoading: false,
    error: null,
  } as never)
  vi.mocked(useCreateUserApiV1HubUsersPost).mockReturnValue({
    mutate: mutar,
    isPending: false,
  } as never)
  vi.mocked(useUpdateUserApiV1HubUsersUserIdPatch).mockReturnValue({
    mutate: mutar,
    isPending: false,
  } as never)
  vi.mocked(useBorrar).mockReturnValue({ mutate: borrar, isPending: false } as never)
  vi.mocked(useSetUsuarioPassword).mockReturnValue({
    mutate: fijarContrasena,
    isPending: false,
  } as never)
  conCapacidades(['listar', 'crear', 'editar', 'borrar', 'fijar_contrasena'])
  return autoridad
}

/** Las acciones que el servidor concede a quien mira (USR.9). La pantalla no las calcula. */
function conCapacidades(acciones: string[]) {
  vi.mocked(useCapacidadesDePersonas).mockReturnValue({
    data: { acciones_permitidas: acciones },
    isLoading: false,
  } as never)
}

beforeAll(async () => {
  await i18n.changeLanguage('es')
})

beforeEach(() => {
  localStorage.clear()
  mutar.mockClear()
  borrar.mockClear()
  fijarContrasena.mockClear()
  conPersonas()
})

/** Cambia la organización elegida como lo hace la cabecera: por la elección compartida. */
function CambiadorDeOrganizacion() {
  const { elegir } = useOrganizacionElegida()
  return (
    <button type="button" data-testid="elegir-otra" onClick={() => elegir('org-dipu')}>
      otra
    </button>
  )
}

function renderPage(autoridadDelRol: 'app' | 'idp' = 'app') {
  vi.mocked(useAutoridadDelRol).mockReturnValue(autoridadDelRol)
  // Los hooks generados están doblados, pero la pantalla usa `useQueryClient` para invalidar
  // el listado tras un alta, y eso sí exige el proveedor de verdad.
  const cliente = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={cliente}>
      <MemoryRouter>
        <UsuariosPage />
      </MemoryRouter>
    </QueryClientProvider>
  )
}

describe('IDE.4 — el listado de personas', () => {
  it('should_show_every_person_with_their_origin', () => {
    renderPage()

    expect(screen.getByText('manual@uji.es')).toBeDefined()
    expect(screen.getByText('porsso@uji.es')).toBeDefined()
  })

  it('should_distinguish_a_manual_row_from_one_provisioned_by_sso', () => {
    // Sin esta columna no se puede saber si el rol lo puso alguien o lo trajo el IdP.
    renderPage()

    const fila = screen.getByRole('row', { name: /manual@uji\.es/ })
    expect(fila.textContent).toMatch(/manual/i)
    const otra = screen.getByRole('row', { name: /porsso@uji\.es/ })
    expect(otra.textContent).toMatch(/sso/i)
  })

  it('should_say_when_someone_never_logged_in', () => {
    // Una fila creada a mano y sin entrada todavía es lo normal: hay que decirlo, no dejar
    // la celda vacía como si fuera un dato que falta.
    renderPage()

    const fila = screen.getByRole('row', { name: /manual@uji\.es/ })
    expect(fila.textContent).toMatch(/nunca/i)
  })

  it('should_mark_a_deactivated_person', () => {
    renderPage()

    const fila = screen.getByRole('row', { name: /porsso@uji\.es/ })
    expect(fila.textContent).toMatch(/desactivad|inactiv/i)
  })

  it('should_build_the_columns_from_the_server_response', () => {
    // El contrato manda: si el servidor deja de enviar a alguien, la fila desaparece.
    conPersonas([PERSONAS[0]])
    renderPage()

    expect(screen.queryByText('porsso@uji.es')).toBeNull()
  })
})

describe('IDE.4 — lo que la pantalla tiene que advertir', () => {
  it('should_warn_that_the_idp_owns_the_role_when_it_does', () => {
    renderPage('idp')

    expect(screen.getByRole('status').textContent).toMatch(/IdP|proveedor de identidad/i)
  })

  it('should_not_warn_when_the_application_owns_the_role', () => {
    renderPage('app')

    const aviso = screen.queryByRole('status')
    expect(aviso?.textContent ?? '').not.toMatch(/IdP|proveedor de identidad/i)
  })

  it('should_say_the_listing_is_not_every_account', () => {
    // Las otras tres tablas de identidad siguen sin unificar (IDE.2).
    renderPage()

    expect(document.body.textContent).toMatch(/no.*todas las cuentas|no incluye/i)
  })
})

describe('IDE.4 — alta y edición', () => {
  it('si el servidor rechaza el alta, la pantalla dice por qué (2026-10-07)', async () => {
    // En producción «el botón no hacía nada»: la persona ya había entrado con Google, el
    // servidor respondía 409 y la mutación no tenía `onError`. El mismo defecto que FIX.1.
    mutar.mockImplementation((_vars: unknown, opciones?: { onError?: (e: unknown) => void }) =>
      opciones?.onError?.({
        response: { data: { detail: 'Ya hay una persona con el correo ya@uji.es' } },
      })
    )
    renderPage()

    fireEvent.change(screen.getByLabelText(/correo/i), { target: { value: 'ya@uji.es' } })
    fireEvent.click(screen.getByRole('button', { name: /dar de alta/i }))

    const aviso = await screen.findByRole('alert')
    expect(aviso.textContent).toContain('Ya hay una persona con el correo ya@uji.es')
    mutar.mockReset()
  })

  it('should_create_a_person_with_the_role_chosen', () => {
    renderPage()

    fireEvent.change(screen.getByLabelText(/correo/i), { target: { value: 'nueva@uji.es' } })
    fireEvent.change(screen.getByLabelText(/^rol/i), { target: { value: 'admin' } })
    fireEvent.click(screen.getByRole('button', { name: /dar de alta/i }))

    expect(mutar).toHaveBeenCalledWith(
      expect.objectContaining({ data: expect.objectContaining({ email: 'nueva@uji.es', role: 'admin' }) }),
      expect.anything()
    )
  })

  it('should_not_offer_a_password_field', () => {
    // El alta crea identidad y permisos, no una credencial: quien entra, entra por SSO.
    renderPage()

    expect(screen.queryByLabelText(/contraseña/i)).toBeNull()
  })

  it('should_deactivate_a_person_without_deleting_them', () => {
    renderPage()

    const fila = screen.getByRole('row', { name: /manual@uji\.es/ })
    fireEvent.click(within(fila).getByRole('button', { name: /desactivar/i }))

    expect(mutar).toHaveBeenCalledWith(
      expect.objectContaining({ data: expect.objectContaining({ is_active: false }) }),
      expect.anything()
    )
  })

  it('should_not_offer_a_delete_action_for_someone_who_has_used_the_platform', () => {
    // Una persona que ya entró tiene rastro en interacciones, informes y concesiones.
    //
    // REV.8 acota este «no hay borrado» en vez de tirarlo: sigue siendo cierto para quien ya
    // entró —que es de quien hablaba IDE.4— y deja de serlo para una fila creada a mano que
    // nadie ha usado. Se comprueba **sobre esa fila** y no sobre la pantalla entera, que es
    // lo que hacía este test cuando el borrado no existía para nadie.
    renderPage()

    const yaEntro = screen.getByTestId('persona-porsso@uji.es')
    expect(
      within(yaEntro).queryByRole('button', { name: /eliminar|borrar/i })
    ).toBeNull()
  })
})

/**
 * REV.8 — borrar, y ver al superadministrador.
 *
 * IDE.4 decidió «desactivar, nunca borrar», con buen motivo: quien ya entró tiene rastro. Era
 * absoluto de más — una fila creada a mano que nadie ha usado no tiene rastro de nada, y un
 * correo mal escrito se quedaba en el listado para siempre.
 *
 * Y el superadministrador principal no aparecía: vive en `superadminaccount` y el listado leía
 * sólo `hub_users`, así que la única cuenta real de una instalación nueva era invisible.
 */
const SUPERADMIN_DE_ARRANQUE: UsuarioRead = {
  id: '33333333-3333-3333-3333-333333333333',
  email: 'root@uji.es',
  display_name: 'SuperAdmin de arranque',
  role: 'superadmin',
  organizacion_id: null,
  is_active: true,
  origen: 'superadmin',
  created_at: '2026-01-01T09:00:00Z',
  created_by: null,
  last_login_at: null,
  puede_borrarse: false,
  motivo_no_borrable: 'Vive en otra tabla y se gestiona desde el servidor.',
}

describe('REV.8 — borrar a quien nunca entró', () => {
  it('should_offer_deleting_someone_the_server_says_can_be_deleted', () => {
    renderPage()

    const fila = screen.getByTestId('persona-manual@uji.es')
    expect(within(fila).getByRole('button', { name: /eliminar|borrar/i })).toBeDefined()
  })

  it('should_delete_after_confirming', () => {
    // Con confirmación: es la única acción de esta pantalla que no se puede deshacer.
    renderPage()

    const fila = screen.getByTestId('persona-manual@uji.es')
    fireEvent.click(within(fila).getByRole('button', { name: /eliminar|borrar/i }))
    fireEvent.click(screen.getByRole('button', { name: /confirmar/i }))

    expect(borrar).toHaveBeenCalledWith(
      { userId: '11111111-1111-1111-1111-111111111111' },
      expect.anything()
    )
  })

  it('should_not_delete_if_the_confirmation_is_dismissed', () => {
    renderPage()

    const fila = screen.getByTestId('persona-manual@uji.es')
    fireEvent.click(within(fila).getByRole('button', { name: /eliminar|borrar/i }))
    fireEvent.click(screen.getByRole('button', { name: /cancelar/i }))

    expect(borrar).not.toHaveBeenCalled()
  })

  it('should_say_why_a_row_cannot_be_deleted', () => {
    // No basta con esconder el botón: sin el motivo, la fila se lee como «aquí no se puede
    // hacer nada» y quien administra no sabe si es una regla o un fallo.
    renderPage()

    const fila = screen.getByTestId('persona-porsso@uji.es')
    expect(fila.textContent).toMatch(/ya ha entrado/i)
  })

  it('should_take_the_decision_from_the_server_and_not_from_last_login', () => {
    // **El test del prompt.** Si el React decidiera por `last_login_at`, esa regla viviría en
    // dos sitios. Aquí el servidor dice que NO se puede borrar a alguien que nunca entró —un
    // caso que hoy no se da, pero que llegará el día que haya más motivos— y la pantalla
    // obedece en vez de recalcular.
    conPersonas([
      { ...PERSONAS[0], last_login_at: null, puede_borrarse: false, motivo_no_borrable: 'Da igual el motivo.' },
    ])
    renderPage()

    const fila = screen.getByTestId('persona-manual@uji.es')
    expect(within(fila).queryByRole('button', { name: /eliminar|borrar/i })).toBeNull()
  })
})

describe('REV.8 — el superadministrador de arranque', () => {
  it('should_show_it_in_the_listing', () => {
    conPersonas([SUPERADMIN_DE_ARRANQUE, ...PERSONAS])
    renderPage()

    expect(screen.getByText('root@uji.es')).toBeDefined()
  })

  it('should_not_offer_deleting_or_deactivating_it', () => {
    // Vive en otra tabla: los dos botones darían un 404 y parecerían un fallo.
    conPersonas([SUPERADMIN_DE_ARRANQUE, ...PERSONAS])
    renderPage()

    const fila = screen.getByTestId('persona-root@uji.es')
    expect(within(fila).queryByRole('button', { name: /eliminar|borrar/i })).toBeNull()
    expect(within(fila).queryByRole('button', { name: /desactivar/i })).toBeNull()
  })
})

/**
 * REV.10 — a qué organización pertenece cada persona.
 *
 * `HubUser.organizacion_id` existe con su clave ajena desde AUTH.2 y **la pantalla no lo
 * enseñaba ni lo pedía**: se podía dar de alta a gente sin organización sin enterarse, y no
 * había forma de saber de quién era nadie. El usuario lo dijo así: «en personas no veo el
 * selector de la organización».
 */
describe('REV.10 — la organización de cada persona', () => {
  it('should_show_which_organisation_each_person_belongs_to', () => {
    conPersonas([{ ...PERSONAS[0], organizacion_id: 'org-uji' }])
    renderPage()

    const fila = screen.getByTestId('persona-manual@uji.es')
    expect(fila.textContent).toMatch(/Universitat Jaume I/)
  })

  it('should_say_when_someone_has_no_organisation', () => {
    // Una celda vacía se lee como un dato que falta; esto es una fila que nadie asignó, y hay
    // que poder verla para arreglarla.
    conPersonas([{ ...PERSONAS[0], organizacion_id: null }])
    renderPage()

    const fila = screen.getByTestId('persona-manual@uji.es')
    expect(fila.textContent).toMatch(/sin organización/i)
  })

  it('should_let_the_alta_choose_an_organisation', () => {
    renderPage()

    fireEvent.change(screen.getByLabelText(/correo/i), { target: { value: 'nueva@uji.es' } })
    fireEvent.change(screen.getByLabelText(/^organización/i), { target: { value: 'org-dipu' } })
    fireEvent.click(screen.getByRole('button', { name: /dar de alta/i }))

    expect(mutar).toHaveBeenCalledWith(
      expect.objectContaining({
        data: expect.objectContaining({ organizacion_id: 'org-dipu' }),
      }),
      expect.anything()
    )
  })

  it('should_default_the_alta_to_the_organisation_chosen_in_the_panel', () => {
    // La elección compartida de REV.10: si ya se está trabajando sobre una organización, el
    // alta no tiene que volver a preguntarlo.
    localStorage.setItem('organizacion-elegida', 'org-dipu')
    renderPage()

    expect((screen.getByLabelText(/^organización/i) as HTMLSelectElement).value).toBe('org-dipu')
  })
})

/**
 * USR.3 — fijar la contraseña de una persona desde el panel.
 *
 * Es la contrapartida de que `hashed_password` nazca en NULL: sin esta acción, una persona dada
 * de alta a mano no tiene forma de entrar mientras el IdP no esté configurado, y el arreglo de
 * USR.1 sería una puerta cerrada con la llave dentro.
 *
 * **Quién puede lo dice el servidor.** `puede_fijar_contrasena` viene en el contrato, y el botón
 * se pinta iterando la respuesta. Un `if (rol === 'superadmin')` aquí sería la autorización
 * escrita por segunda vez (regla maestra 2), y el día que un admin gestione su organización las
 * dos copias dirían cosas distintas.
 */
describe('USR.3 — fijar la contraseña de una persona', () => {
  function abrirFormulario(email = 'manual@uji.es') {
    const fila = screen.getByTestId(`persona-${email}`)
    fireEvent.click(within(fila).getByRole('button', { name: /contraseña/i }))
    return fila
  }

  it('should_offer_the_action_only_when_the_server_allows_it', () => {
    conPersonas([
      { ...PERSONAS[0], puede_fijar_contrasena: true },
      { ...PERSONAS[1], puede_fijar_contrasena: false },
    ])
    renderPage()

    const permitida = screen.getByTestId('persona-manual@uji.es')
    const negada = screen.getByTestId('persona-porsso@uji.es')
    expect(within(permitida).getByRole('button', { name: /contraseña/i })).toBeDefined()
    expect(within(negada).queryByRole('button', { name: /contraseña/i })).toBeNull()
  })

  it('should_send_the_password_for_that_person', async () => {
    renderPage()
    const fila = abrirFormulario()

    fireEvent.change(within(fila).getByLabelText(/contraseña nueva/i), {
      target: { value: 'una-contrasena-larga' },
    })
    fireEvent.click(within(fila).getByRole('button', { name: /guardar/i }))

    await waitFor(() => expect(fijarContrasena).toHaveBeenCalled())
    expect(fijarContrasena).toHaveBeenCalledWith(
      expect.objectContaining({
        userId: PERSONAS[0].id,
        data: { password: 'una-contrasena-larga' },
      }),
      expect.anything()
    )
  })

  it('should_refuse_a_password_shorter_than_the_contract', async () => {
    // La validación del cliente se alinea con el contrato del servidor (min_length=12); no es
    // una regla nueva, es la misma dicha antes de gastar una petición.
    renderPage()
    const fila = abrirFormulario()

    fireEvent.change(within(fila).getByLabelText(/contraseña nueva/i), {
      target: { value: 'corta' },
    })
    fireEvent.click(within(fila).getByRole('button', { name: /guardar/i }))

    await waitFor(() => expect(within(fila).getByRole('alert')).toBeDefined())
    expect(fijarContrasena).not.toHaveBeenCalled()
  })

  it('should_never_show_the_value_again_after_saving', async () => {
    renderPage()
    const fila = abrirFormulario()

    fireEvent.change(within(fila).getByLabelText(/contraseña nueva/i), {
      target: { value: 'una-contrasena-larga' },
    })
    fireEvent.click(within(fila).getByRole('button', { name: /guardar/i }))

    await waitFor(() => expect(fijarContrasena).toHaveBeenCalled())
    // El doble no dispara `onSuccess`, así que se comprueba lo que sí depende de la pantalla:
    // el campo no conserva el valor escrito.
    const campo = within(fila).queryByLabelText(/contraseña nueva/i) as HTMLInputElement | null
    expect(campo?.value ?? '').not.toBe('una-contrasena-larga')
  })

  it('should_hide_the_typed_password', () => {
    renderPage()
    const fila = abrirFormulario()

    expect(within(fila).getByLabelText(/contraseña nueva/i).getAttribute('type')).toBe('password')
  })

  it('should_let_the_form_be_closed_without_saving', () => {
    renderPage()
    const fila = abrirFormulario()

    fireEvent.click(within(fila).getByRole('button', { name: /cancelar/i }))

    expect(within(fila).queryByLabelText(/contraseña nueva/i)).toBeNull()
    expect(fijarContrasena).not.toHaveBeenCalled()
  })
})


/**
 * USR.9 — la pantalla la comparten dos clases de administrador, y el servidor dice qué puede
 * hacer cada una.
 *
 * Hasta aquí era sólo de superadministrador, así que la capacidad que USR.1 dio a quien
 * administra una organización —fijar la contraseña de alguien de su organización— existía por
 * API y no por pantalla: para usarla había que saberse el UUID de la persona.
 *
 * **Se parte, no se abre**, y el reparto **no se calcula aquí**: un `rol === 'superadmin'` en
 * React sería la autorización escrita por segunda vez, que es la regla maestra 2 y ya se rompió
 * una vez con `puede_fijar_contrasena` antes de USR.3.
 */
describe('USR.9 — lo que cada administrador puede hacer lo dice el servidor', () => {
  const DE_ORGANIZACION = ['listar', 'fijar_contrasena']

  it('should_hide_the_creation_form_when_creating_is_not_allowed', () => {
    conCapacidades(DE_ORGANIZACION)
    renderPage()

    expect(screen.queryByRole('button', { name: /dar de alta/i })).toBeNull()
  })

  it('should_hide_the_delete_action_when_deleting_is_not_allowed', () => {
    conCapacidades(DE_ORGANIZACION)
    renderPage()

    const fila = screen.getByTestId('persona-manual@uji.es')
    expect(within(fila).queryByRole('button', { name: /eliminar/i })).toBeNull()
  })

  it('should_hide_the_activation_toggle_when_editing_is_not_allowed', () => {
    conCapacidades(DE_ORGANIZACION)
    renderPage()

    const fila = screen.getByTestId('persona-manual@uji.es')
    expect(within(fila).queryByRole('button', { name: /desactivar|reactivar/i })).toBeNull()
  })

  it('should_keep_the_password_action_for_an_organization_admin', () => {
    /** Es la razón de ser del prompt: sin esto la pantalla no le sirve de nada. */
    conCapacidades(DE_ORGANIZACION)
    renderPage()

    const fila = screen.getByTestId('persona-manual@uji.es')
    expect(within(fila).getByRole('button', { name: /contraseña/i })).toBeTruthy()
  })

  it('should_not_call_the_list_platform_wide_for_an_organization_admin', () => {
    /** «Personas de la plataforma» le nombra algo que no es lo que ve: su listado está
     *  acotado a sus organizaciones. */
    conCapacidades(DE_ORGANIZACION)
    renderPage()

    expect(screen.getByRole('heading', { name: /personas de tu organización/i })).toBeTruthy()
    expect(screen.queryByRole('heading', { name: /personas de la plataforma/i })).toBeNull()
  })

  it('should_still_show_everything_to_a_superadmin', () => {
    renderPage()

    expect(screen.getByRole('button', { name: /dar de alta/i })).toBeTruthy()
    const fila = screen.getByTestId('persona-manual@uji.es')
    expect(within(fila).getByRole('button', { name: /eliminar/i })).toBeTruthy()
    expect(within(fila).getByRole('button', { name: /desactivar/i })).toBeTruthy()
  })

  describe('MT.9 — estrechar a la organización elegida (issue #186)', () => {
    it('should_ask_the_server_for_the_chosen_organisation', () => {
      // El control es **el de la cabecera**: MT.8 acabó de hacer que la organización elegida
      // sea una sola para todo el panel, y un selector propio aquí sería una segunda fuente de
      // verdad para la misma pregunta.
      localStorage.setItem('organizacion-elegida', 'org-uji')
      conPersonas()
      renderPage()

      expect(vi.mocked(useListUsersApiV1HubUsersGet)).toHaveBeenCalledWith({
        organizacion_id: 'org-uji',
      })
    })

    it('should_offer_a_way_out_of_the_filter', () => {
      // **Con organizaciones dadas de alta siempre hay una elegida** —sin elección previa se
      // aterriza en la primera—, así que sin esta salida las cuentas que no pertenecen a
      // ninguna dejarían de ser alcanzables desde el panel. Entre ellas la de arranque, que es
      // la única cuenta real de una instalación recién creada y que REV.8 trajo a este listado
      // justo porque no aparecía en ninguna parte. Estrechar no puede convertirse en esconder.
      localStorage.setItem('organizacion-elegida', 'org-uji')
      conPersonas(PERSONAS, 'app', 2)
      renderPage()

      fireEvent.click(screen.getByRole('button', { name: /ver todas/i }))

      expect(vi.mocked(useListUsersApiV1HubUsersGet)).toHaveBeenLastCalledWith(undefined)
      expect(screen.getByTestId('personas-sin-acotar')).toBeTruthy()
    })

    it('should_say_how_many_accounts_the_filter_leaves_out', () => {
      // Estrechar esconde las cuentas que no son de ninguna organización —las de arranque
      // entre otras—, y **ocultar sin decirlo no es acotar**. El recuento lo da el servidor.
      localStorage.setItem('organizacion-elegida', 'org-uji')
      conPersonas(PERSONAS, 'app', 2)
      renderPage()

      expect(screen.getByTestId('personas-fuera-del-filtro').textContent).toMatch(/2/)
    })

    it('should_stay_quiet_when_nothing_is_left_out', () => {
      // Sin esto, lo de arriba se cumpliría enseñando siempre el aviso.
      localStorage.setItem('organizacion-elegida', 'org-uji')
      conPersonas(PERSONAS, 'app', 0)
      renderPage()

      expect(screen.queryByTestId('personas-fuera-del-filtro')).toBeNull()
    })
    it('should_narrow_again_when_another_organisation_is_chosen', () => {
      // Un interruptor suelto sobreviviría al cambio de organización, así que elegir otra no
      // cambiaría nada de lo que se ve: es el mismo defecto que en MT.8 dejaba elegido un
      // chatbot de la organización anterior. Se cambia como en el panel —por la elección
      // compartida—, no manipulando el estado de la pantalla.
      localStorage.setItem('organizacion-elegida', 'org-uji')
      conPersonas(PERSONAS, 'app', 2)
      render(
        <QueryClientProvider client={new QueryClient()}>
          <MemoryRouter>
            <CambiadorDeOrganizacion />
            <UsuariosPage />
          </MemoryRouter>
        </QueryClientProvider>,
      )

      fireEvent.click(screen.getByRole('button', { name: /ver todas/i }))
      expect(screen.getByTestId('personas-sin-acotar')).toBeTruthy()

      fireEvent.click(screen.getByTestId('elegir-otra'))

      expect(screen.queryByTestId('personas-sin-acotar')).toBeNull()
    })

  })
})
