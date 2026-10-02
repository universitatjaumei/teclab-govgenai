import { describe, it, expect, vi, beforeAll, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import i18n from '@/shared/i18n'
import {
  useListarApiV1AgentesGet,
  usePublicarApiV1AgentesPost,
  useVersionarApiV1AgentesAgenteIdVersionesPost,
  useRevisarApiV1AgentesAgenteIdRevisarPost,
  useSuspenderApiV1AgentesAgenteIdSuspenderPost,
  useReactivarApiV1AgentesAgenteIdReactivarPost,
  useRetirarApiV1AgentesAgenteIdRetirarPost,
  useSubirHojaApiV1AgentesAgenteIdIndiceHojaPost,
  useVerIndiceApiV1AgentesAgenteIdIndiceGet,
} from '@/shared/api/generated/agentes/agentes'
import { AgentesPage } from '../AgentesPage'

/**
 * #172 — la pantalla de los agentes de unidad.
 *
 * **Los botones salen de `acciones_permitidas`**: si la pantalla decidiera por el rol, la
 * autorización estaría escrita dos veces. Y lo que exige el servidor —la declaración, el motivo de
 * una suspensión— se pide **antes** de mandar.
 */
vi.mock('@/shared/api/generated/agentes/agentes', () => ({
  useListarApiV1AgentesGet: vi.fn(),
  usePublicarApiV1AgentesPost: vi.fn(),
  useVersionarApiV1AgentesAgenteIdVersionesPost: vi.fn(),
  useRevisarApiV1AgentesAgenteIdRevisarPost: vi.fn(),
  useSuspenderApiV1AgentesAgenteIdSuspenderPost: vi.fn(),
  useReactivarApiV1AgentesAgenteIdReactivarPost: vi.fn(),
  useRetirarApiV1AgentesAgenteIdRetirarPost: vi.fn(),
  useSubirHojaApiV1AgentesAgenteIdIndiceHojaPost: vi.fn(),
  useVerIndiceApiV1AgentesAgenteIdIndiceGet: vi.fn(),
}))

function version(extra: Record<string, unknown> = {}) {
  return {
    version: 1,
    estado: 'registrada',
    prompt: 'Eres el asistente de contratación.',
    carpeta_url: 'https://drive.google.com/drive/folders/abc',
    finalidad: 'Orientar sobre el contrato menor',
    responsable: 'Jefatura de Contratación',
    colectivo: 'organizacion',
    grupos: [],
    revision_prevista_en: '2027-04-01',
    revision_vencida: false,
    presupuesto_documentos: 5,
    espera_adjunto: false,
    declarada_en: '2026-10-02T10:00:00Z',
    revisada_en: null,
    revision_resultado: null,
    revision_nota: null,
    motivo_suspension: null,
    acciones_permitidas: ['versionar', 'revisar', 'suspender', 'retirar'],
    ...extra,
  }
}

function agente(extra: Record<string, unknown> = {}, v: Record<string, unknown> = {}) {
  return {
    id: 'a1',
    nombre: 'Contratación menor',
    unidad: 'Servicio de Contratación',
    es_mio: false,
    fichas: 0,
    version: version(v),
    ...extra,
  }
}

const mutaciones = {
  publicar: vi.fn(),
  versionar: vi.fn(),
  revisar: vi.fn(),
  suspender: vi.fn(),
  reactivar: vi.fn(),
  retirar: vi.fn(),
  subirHoja: vi.fn(),
}

function montar(agentes = [agente()], gruposDelIdp = true) {
  vi.mocked(useListarApiV1AgentesGet).mockReturnValue({
    data: { agentes, grupos_del_idp: gruposDelIdp },
    isLoading: false,
  } as never)
  vi.mocked(usePublicarApiV1AgentesPost).mockReturnValue({ mutate: mutaciones.publicar, isPending: false } as never)
  vi.mocked(useVersionarApiV1AgentesAgenteIdVersionesPost).mockReturnValue({ mutate: mutaciones.versionar, isPending: false } as never)
  vi.mocked(useRevisarApiV1AgentesAgenteIdRevisarPost).mockReturnValue({ mutate: mutaciones.revisar, isPending: false } as never)
  vi.mocked(useSuspenderApiV1AgentesAgenteIdSuspenderPost).mockReturnValue({ mutate: mutaciones.suspender, isPending: false } as never)
  vi.mocked(useReactivarApiV1AgentesAgenteIdReactivarPost).mockReturnValue({ mutate: mutaciones.reactivar, isPending: false } as never)
  vi.mocked(useRetirarApiV1AgentesAgenteIdRetirarPost).mockReturnValue({ mutate: mutaciones.retirar, isPending: false } as never)
  vi.mocked(useSubirHojaApiV1AgentesAgenteIdIndiceHojaPost).mockReturnValue({ mutate: mutaciones.subirHoja, isPending: false } as never)
  vi.mocked(useVerIndiceApiV1AgentesAgenteIdIndiceGet).mockReturnValue({ data: FICHAS, isLoading: false } as never)

  return render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <AgentesPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const FICHAS = [
  {
    url: 'https://drive.google.com/file/d/1',
    titulo: 'Instrucción de contrato menor',
    resumen: 'Trata del contrato menor.',
    vigente: true,
    revision_prevista_en: null,
    metadatos: {},
    version_prompt_resumen: null,
    modelo_resumen: null,
    updated_at: '2026-10-02T10:00:00Z',
  },
  {
    url: 'https://drive.google.com/file/d/2',
    titulo: 'Guía de viajes de 2019',
    resumen: 'Trata de viajes.',
    vigente: false,
    revision_prevista_en: null,
    metadatos: {},
    version_prompt_resumen: null,
    modelo_resumen: null,
    updated_at: '2026-10-02T10:00:00Z',
  },
]

function rellenar(campos: Record<string, string>) {
  for (const [etiqueta, valor] of Object.entries(campos)) {
    fireEvent.change(screen.getByLabelText(etiqueta), { target: { value: valor } })
  }
}

const DECLARACION = {
  Nombre: 'Control interno',
  Unidad: 'Servicio de Control Interno',
  Finalidad: 'Responder sobre el plan de control',
  Responsable: 'Jefatura de Control Interno',
  Prompt: 'Eres el asistente de control interno.',
  'Carpeta de documentos': 'https://drive.google.com/drive/folders/xyz',
  'Fecha de revisión prevista': '2027-06-30',
}

beforeAll(async () => {
  await i18n.changeLanguage('es')
})

beforeEach(() => {
  Object.values(mutaciones).forEach((m) => m.mockClear())
})

describe('#172 — los botones salen de acciones_permitidas', () => {
  it('ofrece exactamente las acciones que manda el servidor', () => {
    montar([agente({}, { acciones_permitidas: ['versionar', 'retirar'] })])
    const ficha = screen.getByTestId('agente')
    expect(within(ficha).getByRole('button', { name: 'Nueva versión' })).toBeInTheDocument()
    expect(within(ficha).getByRole('button', { name: 'Retirar' })).toBeInTheDocument()
    expect(within(ficha).queryByRole('button', { name: 'Suspender' })).not.toBeInTheDocument()
    expect(within(ficha).queryByRole('button', { name: 'Revisar' })).not.toBeInTheDocument()
  })

  it('un agente retirado no ofrece nada', () => {
    montar([agente({}, { estado: 'retirada', acciones_permitidas: [] })])
    expect(within(screen.getByTestId('agente')).queryAllByRole('button')).toHaveLength(0)
  })
})

describe('#172 — publicar exige la declaración', () => {
  it('manda la declaración completa con el colectivo de toda la organización', async () => {
    montar([])
    fireEvent.click(screen.getByRole('button', { name: 'Publicar un agente' }))
    rellenar(DECLARACION)
    fireEvent.click(screen.getByRole('button', { name: 'Publicar' }))

    await waitFor(() => expect(mutaciones.publicar).toHaveBeenCalledTimes(1))
    expect(mutaciones.publicar.mock.calls[0][0].data).toEqual({
      nombre: 'Control interno',
      unidad: 'Servicio de Control Interno',
      finalidad: 'Responder sobre el plan de control',
      responsable: 'Jefatura de Control Interno',
      prompt: 'Eres el asistente de control interno.',
      carpeta_url: 'https://drive.google.com/drive/folders/xyz',
      colectivo: 'organizacion',
      grupos: [],
      revision_prevista_en: '2027-06-30',
      presupuesto_documentos: 5,
      espera_adjunto: false,
    })
  })

  it('un agente de revisión declara que quien consulta adjuntará un documento', async () => {
    montar([])
    fireEvent.click(screen.getByRole('button', { name: 'Publicar un agente' }))
    rellenar(DECLARACION)
    fireEvent.click(screen.getByLabelText('Quien consulta adjuntará un documento'))
    fireEvent.click(screen.getByRole('button', { name: 'Publicar' }))

    await waitFor(() => expect(mutaciones.publicar).toHaveBeenCalledTimes(1))
    expect(mutaciones.publicar.mock.calls[0][0].data.espera_adjunto).toBe(true)
  })

  it('el presupuesto de documentos se declara, y fuera de 1 a 10 no se manda', async () => {
    montar([])
    fireEvent.click(screen.getByRole('button', { name: 'Publicar un agente' }))
    rellenar({ ...DECLARACION, 'Documentos por consulta': '12' })
    fireEvent.click(screen.getByRole('button', { name: 'Publicar' }))

    expect(await screen.findByText('Entre 1 y 10 documentos.')).toBeInTheDocument()
    expect(mutaciones.publicar).not.toHaveBeenCalled()
  })

  it('por grupos, manda la lista separada por comas', async () => {
    montar([])
    fireEvent.click(screen.getByRole('button', { name: 'Publicar un agente' }))
    rellenar(DECLARACION)
    fireEvent.click(screen.getByLabelText('Unos grupos del proveedor de identidad'))
    rellenar({ Grupos: 'PDI, PTGAS' })
    fireEvent.click(screen.getByRole('button', { name: 'Publicar' }))

    await waitFor(() => expect(mutaciones.publicar).toHaveBeenCalledTimes(1))
    expect(mutaciones.publicar.mock.calls[0][0].data.colectivo).toBe('grupos')
    expect(mutaciones.publicar.mock.calls[0][0].data.grupos).toEqual(['PDI', 'PTGAS'])
  })

  it('sin fecha de revisión no manda nada', async () => {
    montar([])
    fireEvent.click(screen.getByRole('button', { name: 'Publicar un agente' }))
    const { 'Fecha de revisión prevista': _, ...sinFecha } = DECLARACION
    rellenar(sinFecha)
    fireEvent.click(screen.getByRole('button', { name: 'Publicar' }))

    expect(await screen.findByText('Indica cuándo se volverá a revisar.')).toBeInTheDocument()
    expect(mutaciones.publicar).not.toHaveBeenCalled()
  })

  it('una carpeta que no es https no se manda', async () => {
    montar([])
    fireEvent.click(screen.getByRole('button', { name: 'Publicar un agente' }))
    rellenar({ ...DECLARACION, 'Carpeta de documentos': 'C:\\carpeta' })
    fireEvent.click(screen.getByRole('button', { name: 'Publicar' }))

    expect(await screen.findByText(/https/)).toBeInTheDocument()
    expect(mutaciones.publicar).not.toHaveBeenCalled()
  })

  it('avisa de que sin SAML no llegan grupos', () => {
    montar([], false)
    fireEvent.click(screen.getByRole('button', { name: 'Publicar un agente' }))
    expect(screen.getByTestId('aviso-sin-grupos')).toBeInTheDocument()
  })
})

describe('#172 — suspender pide el motivo antes de mandar', () => {
  it('no manda sin motivo y lo manda con él', () => {
    montar()
    fireEvent.click(screen.getByRole('button', { name: 'Suspender' }))
    const confirmar = screen.getByRole('button', { name: 'Confirmar la suspensión' })
    expect(confirmar).toBeDisabled()

    rellenar({ 'Motivo de la suspensión': 'cita un criterio de 2019' })
    fireEvent.click(confirmar)
    expect(mutaciones.suspender).toHaveBeenCalledWith(
      { agenteId: 'a1', data: { motivo: 'cita un criterio de 2019' } },
      expect.anything(),
    )
  })
})

describe('#172 — lo que la ficha dice', () => {
  it('una revisión vencida se ve, y el agente sigue ahí', () => {
    montar([agente({}, { revision_vencida: true })])
    expect(screen.getByTestId('revision-vencida')).toBeInTheDocument()
  })

  it('un agente suspendido dice por qué', () => {
    montar([agente({}, { estado: 'suspendida', motivo_suspension: 'anexo superado', acciones_permitidas: ['reactivar'] })])
    expect(screen.getByText(/anexo superado/)).toBeInTheDocument()
  })

  it('reactivado, el motivo de la suspensión ya no se enseña como si siguiera suspendido', () => {
    // Lo destapó la verificación en navegador: el motivo se conserva en la base como historia.
    montar([agente({}, { estado: 'registrada', motivo_suspension: 'anexo superado' })])
    expect(screen.queryByText(/anexo superado/)).not.toBeInTheDocument()
  })

  it('revisar manda el resultado elegido', () => {
    montar()
    fireEvent.click(screen.getByRole('button', { name: 'Revisar' }))
    fireEvent.change(screen.getByLabelText('Resultado'), { target: { value: 'correcciones' } })
    rellenar({ Nota: 'falta el anexo III' })
    fireEvent.click(screen.getByRole('button', { name: 'Guardar la revisión' }))
    expect(mutaciones.revisar).toHaveBeenCalledWith(
      { agenteId: 'a1', data: { resultado: 'correcciones', nota: 'falta el anexo III' } },
      expect.anything(),
    )
  })
})

describe('#173 — el índice', () => {
  it('la ficha dice cuántas fichas tiene su índice', () => {
    montar([agente({ fichas: 12 })])
    expect(within(screen.getByTestId('agente')).getByText(/12 fichas/)).toBeInTheDocument()
  })

  it('cargar el índice sube la hoja elegida y enseña el informe', () => {
    mutaciones.subirHoja.mockImplementation((_vars, opciones) =>
      opciones.onSuccess({ nuevas: 2, actualizadas: 1, sin_cambios: 3, retiradas: 1 }),
    )
    montar([agente({}, { acciones_permitidas: ['versionar', 'cargar_indice', 'retirar'] })])
    fireEvent.click(screen.getByRole('button', { name: 'Cargar el índice' }))

    const hoja = new File(['url;titulo;resumen'], 'indice.csv', { type: 'text/csv' })
    fireEvent.change(screen.getByLabelText('Hoja del índice'), { target: { files: [hoja] } })

    expect(mutaciones.subirHoja).toHaveBeenCalledWith(
      { agenteId: 'a1', data: { file: hoja } },
      expect.anything(),
    )
    expect(screen.getByTestId('informe-de-carga')).toHaveTextContent('2 nuevas')
    expect(screen.getByTestId('informe-de-carga')).toHaveTextContent('1 retirada')
  })

  it('sin la acción, no se ofrece cargar', () => {
    montar([agente({}, { acciones_permitidas: ['revisar'] })])
    expect(screen.queryByRole('button', { name: 'Cargar el índice' })).not.toBeInTheDocument()
  })

  it('ver el índice lista las fichas y marca las no vigentes', () => {
    montar([agente({ fichas: 2 })])
    fireEvent.click(screen.getByRole('button', { name: 'Ver el índice' }))
    const lista = screen.getByTestId('indice')
    expect(within(lista).getByRole('link', { name: 'Instrucción de contrato menor' })).toHaveAttribute(
      'href',
      'https://drive.google.com/file/d/1',
    )
    expect(within(lista).getByText('No vigente')).toBeInTheDocument()
  })
})

describe('#175 — el agente que espera un adjunto', () => {
  it('su ficha lo dice', () => {
    montar([agente({}, { espera_adjunto: true })])
    expect(within(screen.getByTestId('agente')).getByText('Quien consulta adjunta un documento')).toBeInTheDocument()
  })
})
