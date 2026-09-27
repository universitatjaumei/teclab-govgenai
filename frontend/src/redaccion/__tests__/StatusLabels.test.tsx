/**
 * Tests 9R.7.6 — `statusLabels` + `StatusBadge` + lo que se le dice a quien redacta cuando algo
 * falla.
 *
 * **Reescrito en la issue #98.** Montaba `BlockEditor` y `BlockDebugPanel`, y los dos se
 * retiraron: `BlockEditor` era una bifurcación de `WorkspaceEditor` —misma lista, mismas
 * etiquetas, mismo badge y hasta los mismos `data-testid`— que **no montaba ninguna ruta**, así
 * que sólo se ejecutaba aquí; y `BlockDebugPanel` colgaba de él, lo que dejaba el panel de
 * anonimización inalcanzable desde la aplicación.
 *
 * **Lo que comprobaban se conserva entero**, y era lo que valía la pena: que el estado interno no
 * se le enseña a nadie, que un fallo se traduce a un motivo accionable, y —la importante— que
 * **el mensaje de error literal no sale nunca por la pantalla**. Sólo cambia dónde se comprueba:
 * en `WorkspaceEditor`, que es el componente que la aplicación renderiza de verdad.
 */
import { describe, it, expect, beforeAll } from 'vitest'
import { render, screen } from '@testing-library/react'
import i18n from '@/shared/i18n'
import { I18nextProvider } from 'react-i18next'

import { WorkspaceEditor } from '../components/WorkspaceEditor'
import { mapBlockStatusToUserLabel } from '../utils/statusLabels'
import type { BlockStateOut } from '@/shared/api/generated/model'

// --------------------------------------------------------------------------
// Helpers
// --------------------------------------------------------------------------

function makeBlock(
  id: string,
  status: string,
  extra: Partial<BlockStateOut> = {},
): BlockStateOut {
  return {
    block_id: id,
    kind: 'AI_ASSISTED_TEXT',
    status,
    failure_kind: null,
    last_error_message: null,
    retry_attempts: 0,
    updated_at: '2026-01-01T00:00:00Z',
    ...extra,
  }
}

function pintar(blocks: BlockStateOut[]) {
  return render(
    <I18nextProvider i18n={i18n}>
      <WorkspaceEditor workspace={{ blocks, status: 'in_review' }} />
    </I18nextProvider>,
  )
}

beforeAll(async () => {
  await i18n.changeLanguage('es')
})

// --------------------------------------------------------------------------
// Tests
// --------------------------------------------------------------------------

describe('statusLabels and StatusBadge', () => {
  it('should_render_user_label_not_internal_status', () => {
    pintar([makeBlock('b1', 'needs_review')])

    // El estado interno no puede aparecer como texto visible.
    expect(screen.queryByText('needs_review')).toBeNull()
    expect(screen.getByTestId('block-b1')).toBeDefined()
  })

  it('should_map_failed_to_recoverable_error_tone', () => {
    const result = mapBlockStatusToUserLabel('failed')
    expect(result.tone).toBe('error')
  })

  it('should_not_show_last_error_message_to_regular_user', () => {
    // **La comprobación que había que no perder.** El dato de prueba es un traceback a
    // propósito: `last_error_message` puede traer rutas del contenedor, y enseñárselo a quien
    // redacta es la misma fuga que la issue #147 cerró en el chat público, donde el widget
    // devolvía `str(exc)` a cualquiera.
    //
    // Antes esto se cumplía por rol —el panel hacía `if (!isAdmin) return null`—. Ahora se
    // cumple porque **el mensaje literal no se pinta en ninguna parte**, que es más fuerte: no
    // depende de que nadie se acuerde de comprobar el rol en el siguiente componente.
    const SECRET_ERROR = 'Traceback (most recent call last): RuntimeError at line 42'
    pintar([
      makeBlock('b1', 'failed', {
        failure_kind: 'ai_failed',
        last_error_message: SECRET_ERROR,
      }),
    ])

    expect(screen.queryByText(SECRET_ERROR)).toBeNull()
    expect(document.body.textContent).not.toMatch(/Traceback/)
  })

  it('should_translate_failure_kind_to_friendly_message', () => {
    const SECRET_ERROR = 'Internal: LLM timed out after 30 s'
    pintar([
      makeBlock('b1', 'failed', {
        failure_kind: 'ai_failed',
        last_error_message: SECRET_ERROR,
      }),
    ])

    expect(screen.queryByText(SECRET_ERROR)).toBeNull()
    expect(screen.getByTestId('failure-friendly-message-b1')).toBeDefined()
  })

  it('should_show_the_failure_detail_to_everyone_who_can_open_the_report', () => {
    // Lo que el panel anterior hacía al revés: escondía por rol algo que el servidor ya sirve
    // sólo al dueño del workspace. El frontend no calcula permisos (invariante I6).
    pintar([makeBlock('b1', 'failed', { failure_kind: 'ai_failed', retry_attempts: 3 })])

    expect(screen.getByTestId('block-failure-detail-b1').textContent).toMatch(/3/)
  })
})
