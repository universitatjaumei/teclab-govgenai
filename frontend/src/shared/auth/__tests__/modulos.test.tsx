import { describe, it, expect, beforeAll, beforeEach, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import i18n from '@/shared/i18n'
import { primeraRutaConcedida, moduloDeLaRuta } from '../useModulos'
import { RutaDeModulo, Aterrizaje, NoEncontrado } from '../RutaDeModulo'
import { useGetMeApiV1AuthMeGet } from '@/shared/api/generated/auth/auth'

/**
 * INF.7 — el menú y las rutas se generan con lo que el servidor concede.
 *
 * Antes no había nada que generar: todas las rutas iban bajo un `PrivateRoute` que solo
 * comprobaba que hubiera sesión, no existía un `role ===` en la navegación y el aterrizaje era
 * `/hub/chatbots` fijo. Con el módulo de informes abierto a toda la organización, eso
 * significaba que cualquier trabajador con cuenta veía y podía editar los chatbots
 * institucionales.
 */
vi.mock('@/shared/api/generated/auth/auth', () => ({
  useGetMeApiV1AuthMeGet: vi.fn(),
}))

function conModulos(modulos: string[] | undefined, cargando = false) {
  vi.mocked(useGetMeApiV1AuthMeGet).mockReturnValue({
    data: modulos === undefined ? undefined : { modulos },
    isLoading: cargando,
  } as never)
}

beforeAll(async () => {
  await i18n.changeLanguage('es')
})

beforeEach(() => vi.clearAllMocks())

describe('INF.7 — a dónde entra cada persona', () => {
  it('should_land_a_reports_only_worker_in_reports', () => {
    expect(primeraRutaConcedida(['informes'])).toBe('/redaccion')
  })

  it('should_not_land_anyone_in_a_module_they_do_not_have', () => {
    expect(primeraRutaConcedida(['curacion'])).toBe('/curation')
    expect(primeraRutaConcedida([])).toBe('/sin-acceso')
  })

  it('should_know_which_module_protects_each_area', () => {
    expect(moduloDeLaRuta('/hub/chatbots')).toBe('chatbots')
    expect(moduloDeLaRuta('/redaccion/workspaces/abc')).toBe('informes')
    expect(moduloDeLaRuta('/login')).toBeNull()
  })
})

describe('INF.7 — una zona sin su módulo no se abre', () => {
  function pintar(ruta: string) {
    return render(
      <MemoryRouter initialEntries={[ruta]}>
        <Routes>
          <Route
            path="/hub"
            element={<RutaDeModulo modulo="chatbots"><div data-testid="dentro-de-hub" /></RutaDeModulo>}
          />
          <Route path="/sin-acceso" element={<div data-testid="sin-acceso" />} />
          <Route path="/" element={<Aterrizaje />} />
          <Route path="/redaccion" element={<div data-testid="dentro-de-informes" />} />
        </Routes>
      </MemoryRouter>,
    )
  }

  it('should_open_the_area_when_the_module_is_granted', async () => {
    conModulos(['chatbots'])
    pintar('/hub')
    expect(await screen.findByTestId('dentro-de-hub')).toBeDefined()
  })

  it('should_refuse_the_area_without_the_module', async () => {
    conModulos(['informes'])
    pintar('/hub')
    // USR.10 — lo que este test fija es que la zona **no se abre**. A dónde va cambió: quien
    // tiene módulos y no éste ya no aterriza en «no tienes ninguno», que era falso.
    expect(await screen.findByTestId('sin-este-modulo')).toBeDefined()
    expect(screen.queryByTestId('dentro-de-hub')).toBeNull()
  })

  it('should_not_throw_anyone_out_while_the_list_is_loading', async () => {
    // Tratar «todavía no lo sé» como «no tienes acceso» expulsaría a la gente en cada recarga.
    conModulos(undefined, true)
    pintar('/hub')
    expect(screen.queryByTestId('sin-acceso')).toBeNull()
    expect(screen.queryByTestId('dentro-de-hub')).toBeNull()
  })

  it('should_land_on_the_first_granted_module', async () => {
    conModulos(['informes'])
    pintar('/')
    await waitFor(() => expect(screen.getByTestId('dentro-de-informes')).toBeDefined())
  })
})

/**
 * REV.5 — una dirección que no existe se dice, no se redirige.
 *
 * El comodín `*` montaba `Aterrizaje`, así que cualquier URL equivocada acababa en el primer
 * módulo concedido. Lo destapó la cola de vigencia: el enlace de un documento del corpus lleva
 * un nombre de fichero, el navegador lo resolvía como ruta relativa y la pestaña nueva
 * aterrizaba en Informes. Parecía un fallo de Informes y era un 404 disfrazado.
 */
describe('REV.5 — una ruta que no existe', () => {
  function pintarConComodin(ruta: string) {
    return render(
      <MemoryRouter initialEntries={[ruta]}>
        <Routes>
          <Route path="/" element={<Aterrizaje />} />
          <Route path="/redaccion" element={<div data-testid="dentro-de-informes" />} />
          <Route path="*" element={<NoEncontrado />} />
        </Routes>
      </MemoryRouter>,
    )
  }

  it('should_say_the_address_does_not_exist_instead_of_redirecting', async () => {
    conModulos(['informes'])
    pintarConComodin('/hub/20260203_UJI_REC_Resolucio_assimilacio_carrecs.md')

    await waitFor(() => expect(screen.getByTestId('no-encontrado')).toBeDefined())
    expect(screen.queryByTestId('dentro-de-informes')).toBeNull()
  })

  it('should_still_land_on_the_root', async () => {
    // Aterrizar sigue siendo lo correcto donde no se ha pedido nada concreto.
    conModulos(['informes'])
    pintarConComodin('/')

    await waitFor(() => expect(screen.getByTestId('dentro-de-informes')).toBeDefined())
  })
})


/**
 * USR.10 — «no tienes ningún módulo» y «no tienes éste» son dos cosas distintas.
 *
 * `RutaDeModulo` mandaba a `/sin-acceso` en los dos casos, y esa pantalla dice literalmente «tu
 * cuenta existe pero **no tiene ningún módulo concedido**. Pide acceso [...] indicando que
 * necesitas: informes, chatbots o curación». A quien tiene informes y ha pinchado un enlace a
 * Chatbots eso le dice algo que no es verdad, le propone pedir lo que ya tiene y le esconde que
 * su propia pantalla sigue ahí.
 *
 * Se separan las dos: sin ningún módulo, la pantalla de siempre —hay que decir que no hay a
 * dónde ir—; con módulos y sin éste, **la dirección no cambia** y se dice que esta parte no
 * está concedida, con la salida a lo que sí.
 */
describe('USR.10 — una zona sin su módulo, teniendo otros', () => {
  function pintar(ruta: string) {
    return render(
      <MemoryRouter initialEntries={[ruta]}>
        <Routes>
          <Route
            path="/hub"
            element={<RutaDeModulo modulo="chatbots"><div data-testid="dentro-de-hub" /></RutaDeModulo>}
          />
          <Route path="/sin-acceso" element={<div data-testid="sin-acceso" />} />
          <Route path="/redaccion" element={<div data-testid="dentro-de-informes" />} />
        </Routes>
      </MemoryRouter>,
    )
  }

  it('should_not_claim_they_have_no_modules_when_they_do', async () => {
    conModulos(['informes'])
    pintar('/hub')

    expect(await screen.findByTestId('sin-este-modulo')).toBeDefined()
    expect(screen.queryByTestId('sin-acceso')).toBeNull()
  })

  it('should_keep_the_address_of_the_section_they_asked_for', async () => {
    /* La dirección es lo único que dice qué parte pedían; perderla convierte «pide acceso a
       esto» en «pide acceso a algo». */
    conModulos(['informes'])
    pintar('/hub')

    await screen.findByTestId('sin-este-modulo')
    expect(window.location.pathname).not.toBe('/sin-acceso')
  })

  it('should_offer_a_way_to_what_they_can_open', async () => {
    conModulos(['informes'])
    pintar('/hub')

    const salida = await screen.findByRole('link')
    expect(salida.getAttribute('href')).toBe('/redaccion')
  })

  it('should_still_send_someone_with_nothing_to_sin_acceso', async () => {
    conModulos([])
    pintar('/hub')

    expect(await screen.findByTestId('sin-acceso')).toBeDefined()
    expect(screen.queryByTestId('sin-este-modulo')).toBeNull()
  })
})

/**
 * USR.9 — quien sólo administra personas tiene a dónde ir.
 *
 * Es la nota que PLAT.2 dejó escrita en `RUTA_DEL_MODULO`: sin su fila, quien sólo administra
 * la plataforma aterrizaba en `/sin-acceso` teniendo acceso. El módulo nuevo repetiría el fallo.
 */
describe('USR.9 — el aterrizaje de quien sólo administra personas', () => {
  it('should_land_a_personas_only_admin_in_personas', () => {
    expect(primeraRutaConcedida(['personas'])).toBe('/personas')
  })

  it('should_know_which_module_protects_personas', () => {
    expect(moduloDeLaRuta('/personas')).toBe('personas')
  })
})

describe('2026-10-05 — el módulo `automatizacion`', () => {
  it('quien sólo lo tiene aterriza en su sección', () => {
    expect(primeraRutaConcedida(['automatizacion'])).toBe('/automatizacion')
  })

  it('protege sus rutas', () => {
    expect(moduloDeLaRuta('/automatizacion/funciones/revision')).toBe('automatizacion')
  })
})
