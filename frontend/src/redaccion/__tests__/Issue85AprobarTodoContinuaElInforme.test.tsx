import { describe, it, expect, beforeAll, beforeEach, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import i18n from '@/shared/i18n'

/**
 * Issue #85 — aprobar todo tiene que continuar el informe.
 *
 * **El defecto.** El endpoint existe (`POST /{id}/resume`, exige `in_review` y deja `drafting`),
 * el hook está generado, y **nadie lo llamaba**: la única referencia en código escrito a mano
 * era un **mock de test** en `CopilotoAlcanzable.test.tsx`. Aprobadas todas las valoraciones, el
 * informe se quedaba en `in_review` para siempre y la barra de progreso —cuyo `STATUS_ORDER` va
 * `draft → ingesting → extracting → drafting → in_review → assembled → exported`— no pasaba del
 * quinto paso.
 *
 * Vista previa y exportación funcionan igual, así que **el síntoma es sólo que el estado
 * miente**. Eso lo hace fácil de aplazar y caro de aplazar: quien revisa paga atención en cada
 * informe para acordarse de que ese estado no cuenta, y un «no completó» hay que descartarlo a
 * mano.
 *
 * **Botón y no automático**, decidido: un efecto sobre un booleano derivado es cómo se consigue
 * disparar la llamada más de una vez, y el endpoint responde 409 si el workspace ya salió de
 * `in_review` — o sea que el camino automático añade un error que hay que tragarse. Y la
 * pantalla **ya anunciaba** «todos los apartados aprobados», así que el botón cae donde ya
 * estaba el anuncio.
 */

vi.mock('@/shared/api/generated/hub-redaccion/hub-redaccion', () => ({
  useGetWorkspaceById: vi.fn(),
  usePatchWorkspaceBlock: vi.fn(),
  getGetWorkspaceByIdQueryKey: vi.fn(() => ['workspace']),
}))

vi.mock('@/shared/api/generated/redaccion-workspaces/redaccion-workspaces', () => ({
  useEditBlock: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
  useResumeWorkspace: vi.fn(),
}))

import { AIBlockReviewPanel } from '../components/AIBlockReviewPanel'
import {
  useGetWorkspaceById,
  usePatchWorkspaceBlock,
} from '@/shared/api/generated/hub-redaccion/hub-redaccion'
import { useResumeWorkspace } from '@/shared/api/generated/redaccion-workspaces/redaccion-workspaces'

const WS = '22222222-2222-2222-2222-222222222222'

/** Un bloque de IA aprobado: el servidor no ofrece ninguna acción sobre él. */
const APROBADO = {
  block_id: 'v_tesis',
  kind: 'AI_ASSISTED_TEXT',
  status: 'approved',
  content: { text: 'Las tesis leídas suben un 17 %.' },
  retry_attempts: 0,
  updated_at: '2026-09-21T10:00:00Z',
  acciones_permitidas: [],
}

/** Uno que sigue pendiente: el servidor ofrece acciones, así que la revisión no ha acabado. */
const PENDIENTE = {
  block_id: 'v_matricula',
  kind: 'AI_ASSISTED_TEXT',
  status: 'needs_review',
  content: { text: 'La matrícula baja un 3 %.' },
  retry_attempts: 0,
  updated_at: '2026-09-21T10:00:00Z',
  acciones_permitidas: ['approve', 'edit', 'reject'],
}

/**
 * #243 — `acciones` es lo que el servidor dice que se puede hacer con el informe entero. Por
 * defecto, lo que diría de uno en revisión con todo aprobado.
 */
function pintar(
  bloques: object[],
  resumir = vi.fn(),
  { status = 'in_review', acciones = ['ensamblar'] }: { status?: string; acciones?: string[] } = {},
) {
  vi.mocked(useGetWorkspaceById).mockReturnValue({
    data: { id: WS, status, blocks: bloques, acciones_permitidas: acciones },
    isLoading: false,
  } as never)
  vi.mocked(usePatchWorkspaceBlock).mockReturnValue({
    mutate: vi.fn(),
    isPending: false,
  } as never)
  vi.mocked(useResumeWorkspace).mockReturnValue({
    mutate: resumir,
    isPending: false,
  } as never)

  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={qc}>
      <AIBlockReviewPanel workspaceId={WS} />
    </QueryClientProvider>
  )
  return resumir
}

beforeAll(async () => {
  await i18n.changeLanguage('es')
})

beforeEach(() => {
  vi.clearAllMocks()
})

describe('aprobar todo continúa el informe', () => {
  it('con todo aprobado, ofrece continuar', () => {
    pintar([APROBADO])

    expect(screen.getByTestId('ready-for-assembly')).toBeDefined()
    expect(screen.getByTestId('btn-continuar')).toBeDefined()
  })

  it('continuar llama a `resume` con el informe', async () => {
    const resumir = pintar([APROBADO])

    fireEvent.click(screen.getByTestId('btn-continuar'))

    await waitFor(() =>
      expect(resumir).toHaveBeenCalledWith(
        expect.objectContaining({ workspaceId: WS }),
        expect.anything(),
      )
    )
  })

  it('mientras quede algo pendiente, no lo ofrece', () => {
    pintar([APROBADO, PENDIENTE], vi.fn(), { acciones: [] })

    // Lo que decide es `acciones_permitidas`, que la calcula el servidor: el frontend no
    // deduce el estado de la revisión (INF.2).
    expect(screen.queryByTestId('btn-continuar')).toBeNull()
    expect(screen.getByTestId('pending-review-count')).toBeDefined()
  })

  it('si continuar falla, lo dice y no se lo calla', async () => {
    const resumir = vi.fn((_vars, opciones) =>
      opciones?.onError?.(new Error('el informe ya no está en revisión'))
    )
    pintar([APROBADO], resumir)

    fireEvent.click(screen.getByTestId('btn-continuar'))

    await waitFor(() =>
      expect(
        screen
          .getAllByRole('alert')
          .some((n) => n.textContent?.includes('el informe ya no está en revisión'))
      ).toBe(true)
    )
  })

  it('#243: antes de generar no anuncia «todo aprobado» ni ofrece ensamblar', () => {
    // Un informe recién creado: sin bloques y sin acciones. Cero valoraciones no es «todas
    // aprobadas», y era lo que la pantalla deducía.
    pintar([], vi.fn(), { status: 'draft', acciones: [] })

    expect(screen.queryByTestId('ready-for-assembly')).toBeNull()
    expect(screen.queryByTestId('btn-continuar')).toBeNull()
  })

  it('#243: después de ensamblar el botón desaparece', () => {
    // Pulsarlo otra vez daba «Workspace must be in 'in_review' state…».
    pintar([APROBADO], vi.fn(), { status: 'assembled', acciones: [] })

    expect(screen.queryByTestId('btn-continuar')).toBeNull()
    expect(screen.queryByTestId('ready-for-assembly')).toBeNull()
  })

  it('el texto del botón está traducido, no es la clave', () => {
    pintar([APROBADO])

    const texto = screen.getByTestId('btn-continuar').textContent ?? ''
    expect(texto.length).toBeGreaterThan(0)
    expect(texto).not.toContain('review.')
  })
})
