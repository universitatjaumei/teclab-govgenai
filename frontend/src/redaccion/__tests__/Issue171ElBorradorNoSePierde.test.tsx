import { describe, it, expect, beforeAll, beforeEach, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import i18n from '@/shared/i18n'
import { AIBlockReviewPanel } from '../components/AIBlockReviewPanel'
import {
  useGetWorkspaceById,
  usePatchWorkspaceBlock,
} from '@/shared/api/generated/hub-redaccion/hub-redaccion'
import { useEditBlock } from '@/shared/api/generated/redaccion-workspaces/redaccion-workspaces'

/**
 * Issue #171 — lo tecleado no se pierde al recargar.
 *
 * Es la contrapartida de retirar la cadena del autoguardado (1C.1), que estaba entera y sin
 * cablear. No se cableó porque el contenido de un bloque **ya tiene dueño**: `PATCH
 * /blocks/{id}/edit`, que además registra lo que la IA había propuesto para poder volver atrás
 * (SEG.4). Autoguardar por `PATCH /state` habría sido un segundo camino de escritura al mismo
 * dato, saltándose ese registro — dos caminos con uno vivo es lo que esta issue existe para
 * evitar.
 *
 * Lo que sí protegía el autoguardado, y hay que conservar, es no perder una edición larga si se
 * recarga la pestaña. Eso se resuelve **en el navegador**: el borrador vive en `localStorage` de
 * quien escribe, no viaja a ninguna parte y no toca el contenido del bloque hasta que se pulsa
 * guardar.
 *
 * Y se restaura **diciéndolo**. Restaurar en silencio enseñaría un texto que no es el guardado
 * sin que nadie pueda saber por qué, que es peor que perderlo.
 */
// `getGetWorkspaceByIdQueryKey` **tiene que estar en el doble**: el panel la llama al invalidar
// la caché tras guardar. Sin ella el doble no era el módulo, era un módulo incompleto, y la
// llamada lanzaba dentro del `onSuccess` abortándolo a mitad — el borrador no se olvidaba y el
// test culpaba al código. Un doble al que le faltan exportaciones miente sobre lo que sustituye.
vi.mock('@/shared/api/generated/hub-redaccion/hub-redaccion', () => ({
  getGetWorkspaceByIdQueryKey: (id: string) => ['workspace', id],
  useGetWorkspaceById: vi.fn(),
  usePatchWorkspaceBlock: vi.fn(),
}))

vi.mock('@/shared/api/generated/redaccion-workspaces/redaccion-workspaces', () => ({
  useResumeWorkspace: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
  useEditBlock: vi.fn(),
}))

const WS = '22222222-2222-2222-2222-222222222222'
const TEXTO_GUARDADO = 'La matrícula desciende un 6 % respecto al curso anterior.'

const BLOQUE = {
  block_id: 'v_matricula',
  kind: 'AI_ASSISTED_TEXT',
  status: 'needs_review',
  content: {
    text: TEXTO_GUARDADO,
    model_used: 'gemini-2.5-flash',
    prompt_version: 'valoracion_v1',
    context_scope: 'full',
    context_block_ids: [],
  },
  retry_attempts: 0,
  updated_at: '2026-09-27T10:00:00Z',
  acciones_permitidas: ['approve', 'edit', 'reject'],
}

function mockearApi(edit = vi.fn()) {
  vi.mocked(useGetWorkspaceById).mockReturnValue({
    data: { id: WS, status: 'in_review', blocks: [BLOQUE] },
    isLoading: false,
  } as never)
  vi.mocked(usePatchWorkspaceBlock).mockReturnValue({ mutate: vi.fn(), isPending: false } as never)
  vi.mocked(useEditBlock).mockReturnValue({ mutate: edit, isPending: false } as never)
  return edit
}

function pintar() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <AIBlockReviewPanel workspaceId={WS} />
    </QueryClientProvider>,
  )
}

function escribir(texto: string) {
  fireEvent.change(screen.getByTestId('editor-v_matricula'), { target: { value: texto } })
}

beforeAll(async () => {
  await i18n.changeLanguage('es')
})

beforeEach(() => {
  vi.clearAllMocks()
  window.localStorage.clear()
})

describe('el borrador de una edición sobrevive a recargar la pestaña', () => {
  it('should_guardar_lo_tecleado_en_el_navegador', () => {
    mockearApi()
    pintar()
    fireEvent.click(screen.getByTestId('btn-editar-v_matricula'))

    escribir('La matrícula desciende un 6 %, y en primero un 11 %.')

    const guardado = JSON.stringify(window.localStorage)
    expect(guardado).toContain('en primero un 11 %')
  })

  it('should_recuperar_el_borrador_al_volver_a_abrir_el_editor', () => {
    /** Es el caso real: se recarga la pestaña y el componente se monta de cero. */
    mockearApi()
    const primera = pintar()
    fireEvent.click(screen.getByTestId('btn-editar-v_matricula'))
    escribir('Un párrafo largo que costó escribir.')
    primera.unmount()

    pintar()
    fireEvent.click(screen.getByTestId('btn-editar-v_matricula'))

    expect(screen.getByTestId('editor-v_matricula')).toHaveValue(
      'Un párrafo largo que costó escribir.',
    )
  })

  it('should_avisar_de_que_lo_que_se_ve_es_un_borrador_sin_guardar', () => {
    mockearApi()
    const primera = pintar()
    fireEvent.click(screen.getByTestId('btn-editar-v_matricula'))
    escribir('Un párrafo largo que costó escribir.')
    primera.unmount()

    pintar()
    fireEvent.click(screen.getByTestId('btn-editar-v_matricula'))

    expect(screen.getByTestId('aviso-borrador-v_matricula')).toBeInTheDocument()
  })

  it('should_poder_descartarlo_y_volver_al_texto_guardado', () => {
    mockearApi()
    const primera = pintar()
    fireEvent.click(screen.getByTestId('btn-editar-v_matricula'))
    escribir('Algo que ya no quiero.')
    primera.unmount()

    pintar()
    fireEvent.click(screen.getByTestId('btn-editar-v_matricula'))
    fireEvent.click(screen.getByTestId('btn-descartar-borrador-v_matricula'))

    expect(screen.getByTestId('editor-v_matricula')).toHaveValue(TEXTO_GUARDADO)
    expect(screen.queryByTestId('aviso-borrador-v_matricula')).not.toBeInTheDocument()
    expect(JSON.stringify(window.localStorage)).not.toContain('Algo que ya no quiero')
  })

  it('should_olvidar_el_borrador_cuando_se_guarda_de_verdad', () => {
    // `onSuccess` y no `onSettled`: desde la revisión de la PR #178 el olvido del borrador
    // cuelga del éxito, porque `onSettled` corría también al fallar.
    const edit = mockearApi(vi.fn((_vars, opts) => opts?.onSuccess?.()))
    pintar()
    fireEvent.click(screen.getByTestId('btn-editar-v_matricula'))
    escribir('El texto definitivo.')
    fireEvent.click(screen.getByTestId('btn-guardar-v_matricula'))

    expect(edit).toHaveBeenCalledTimes(1)
    expect(JSON.stringify(window.localStorage)).not.toContain('El texto definitivo')
  })

  it('should_conservar_el_borrador_si_el_guardado_falla', () => {
    /**
     * El olvido estaba en `onSettled`, que corre **también al fallar**. Un error de red borraba
     * el borrador y cerraba el editor, o sea que perdía exactamente el texto que esta pieza
     * existe para no perder. Lo encontró la revisión automática de la PR #178.
     */
    const edit = mockearApi(vi.fn((_vars, opts) => opts?.onError?.(new Error('sin red'))))
    pintar()
    fireEvent.click(screen.getByTestId('btn-editar-v_matricula'))
    escribir('Lo que costó escribir y el servidor no aceptó.')
    fireEvent.click(screen.getByTestId('btn-guardar-v_matricula'))

    expect(edit).toHaveBeenCalledTimes(1)
    expect(JSON.stringify(window.localStorage)).toContain('el servidor no aceptó')
    expect(screen.getByTestId('editor-v_matricula')).toHaveValue(
      'Lo que costó escribir y el servidor no aceptó.',
    )
  })

  it('should_avisar_de_que_el_guardado_ha_fallado', () => {
    /** Conservar el borrador y no decir nada se lee como que sí se guardó. */
    mockearApi(vi.fn((_vars, opts) => opts?.onError?.(new Error('sin red'))))
    pintar()
    fireEvent.click(screen.getByTestId('btn-editar-v_matricula'))
    escribir('Texto que no se guarda.')
    fireEvent.click(screen.getByTestId('btn-guardar-v_matricula'))

    expect(screen.getByTestId('error-guardar-v_matricula')).toBeInTheDocument()
  })

  it('should_seguir_funcionando_si_el_navegador_no_deja_guardar', () => {
    /**
     * Ventana privada, almacenamiento bloqueado, cuota llena: el acceso **lanza**. Un editor que
     * se cae por no poder guardar un borrador es peor que uno que no lo guarda.
     */
    mockearApi()
    const setItem = vi
      .spyOn(Storage.prototype, 'setItem')
      .mockImplementation(() => {
        throw new DOMException('QuotaExceededError')
      })
    try {
      pintar()
      fireEvent.click(screen.getByTestId('btn-editar-v_matricula'))
      escribir('Se escribe igual.')

      expect(screen.getByTestId('editor-v_matricula')).toHaveValue('Se escribe igual.')
    } finally {
      setItem.mockRestore()
    }
  })

  it('should_no_confundir_el_borrador_de_un_bloque_con_el_de_otro', () => {
    mockearApi()
    const primera = pintar()
    fireEvent.click(screen.getByTestId('btn-editar-v_matricula'))
    escribir('Borrador del bloque de matrícula.')
    primera.unmount()

    // El mismo informe, otro bloque: no puede heredar el borrador del anterior.
    vi.mocked(useGetWorkspaceById).mockReturnValue({
      data: {
        id: WS,
        status: 'in_review',
        blocks: [{ ...BLOQUE, block_id: 'v_tasas', content: { ...BLOQUE.content, text: 'Otro.' } }],
      },
      isLoading: false,
    } as never)
    pintar()
    fireEvent.click(screen.getByTestId('btn-editar-v_tasas'))

    expect(screen.getByTestId('editor-v_tasas')).toHaveValue('Otro.')
  })
})
