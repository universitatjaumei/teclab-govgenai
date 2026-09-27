/**
 * Issue #98 (4ª parte) — por qué falló un bloque se ve en el bloque que falló.
 *
 * **Lo que había, medido.** `failure_kind`, `last_error_message` y `retry_attempts` vienen en el
 * contrato (`BlockStateOut`) y **no aparecían en ningún sitio de la aplicación viva**:
 * `WorkspacePage` pinta un `t('workspace_error')` genérico para todo el informe y
 * `WorkspaceEditor` sólo la etiqueta de estado. Los tres campos se enseñaban únicamente en
 * `BlockDebugPanel`, que colgaba de `BlockEditor`, **que no lo montaba ninguna ruta**.
 *
 * Así que quien redacta, cuando un bloque fallaba, no podía saber si reintentar, cambiar el
 * documento o avisar a alguien.
 *
 * **Lo que NO cambia, y casi se rompe al escribir esto**: `last_error_message` sigue sin
 * enseñarse. Puede traer un traceback con rutas del contenedor, y ocultárselo a quien redacta era
 * una decisión ya tomada —la fijaba `should_not_show_last_error_message_to_regular_user`, con un
 * traceback literal como dato de prueba—. Es la misma fuga que la issue #147 cerró en el chat
 * público. Lo que se enseña es el motivo traducido y cuántas veces se reintentó; el error literal
 * vive en el registro del servidor, que desde la issue #18 sale con nivel, marca de tiempo y
 * módulo.
 *
 * **Tres cosas inutilizaban el panel anterior y ninguna sobrevive**: se llamaba «depuración»,
 * que le dice a quien lo ve que no es para él; hacía `if (!isAdmin) return null`, que se lo
 * quitaba justo a quien tiene el problema delante; y se repetía por bloque detrás de un enlace
 * plegado en vez de salir en el bloque que había fallado.
 *
 * Sin condicionar por rol, a propósito: si el servidor te deja abrir el informe, te deja saber
 * por qué falló tu propio bloque.
 */
import { existsSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import { describe, it, expect, beforeAll } from 'vitest'
import { render, screen } from '@testing-library/react'
import i18n from '@/shared/i18n'
import { I18nextProvider } from 'react-i18next'
import { WorkspaceEditor } from '../WorkspaceEditor'
import type { BlockStateOut } from '@/shared/api/generated/model'

const OK: BlockStateOut = {
  block_id: 'b_datos',
  kind: 'DETERMINISTIC_DATA',
  status: 'approved',
  updated_at: '2026-09-26T10:00:00Z',
}

const FALLADO: BlockStateOut = {
  block_id: 'b_resumen',
  kind: 'AI_ASSISTED_TEXT',
  status: 'failed',
  failure_kind: 'llm_timeout',
  last_error_message: 'Deadline exceeded al llamar al modelo',
  retry_attempts: 2,
  updated_at: '2026-09-26T10:05:00Z',
}

beforeAll(async () => {
  await i18n.changeLanguage('es')
})

function pintar(blocks: BlockStateOut[]) {
  return render(
    <I18nextProvider i18n={i18n}>
      <WorkspaceEditor workspace={{ blocks, status: 'error' }} />
    </I18nextProvider>,
  )
}

describe('Issue #98 — el detalle del fallo, en el bloque que falló', () => {
  it('should_show_why_the_block_failed_in_words_the_person_can_act_on', () => {
    pintar([OK, FALLADO])

    expect(screen.getByTestId('block-failure-detail-b_resumen')).toBeDefined()
    expect(screen.getByTestId('failure-friendly-message-b_resumen')).toBeDefined()
  })

  it('should_never_show_the_raw_error_message', () => {
    // **Decisión anterior, conservada.** `last_error_message` puede traer un traceback con
    // rutas del contenedor, y esconderlo a quien redacta ya estaba fijado por
    // `should_not_show_last_error_message_to_regular_user`. Es la misma fuga que la issue #147
    // cerró en el chat público, donde el widget devolvía `str(exc)` a cualquiera.
    //
    // El error literal no se pierde: vive en el registro del servidor, que desde la issue #18
    // sale con nivel, marca de tiempo y nombre de módulo.
    pintar([FALLADO])

    expect(screen.queryByText(/Deadline exceeded/)).toBeNull()
    expect(document.body.textContent).not.toMatch(/Deadline exceeded/)
  })

  it('should_say_how_many_times_it_was_retried', () => {
    // Sin esto, «ha fallado» no distingue un fallo puntual de uno que ya no se va a arreglar
    // reintentando, que es la única decisión que quien redacta puede tomar aquí.
    pintar([FALLADO])

    expect(screen.getByTestId('block-failure-detail-b_resumen').textContent).toMatch(/2/)
  })

  it('should_not_show_the_detail_on_a_block_that_did_not_fail', () => {
    pintar([OK])

    expect(screen.queryByTestId('block-failure-detail-b_datos')).toBeNull()
  })

  it('should_not_hide_it_behind_a_role', () => {
    // `WorkspaceEditor` no consulta `useAuth`: si lo hiciera, el frontend estaría calculando
    // permisos, que es el invariante I6 y es lo que hacía el panel anterior — al revés que el
    // servidor, además.
    pintar([FALLADO])

    expect(screen.getByTestId('block-failure-detail-b_resumen')).toBeDefined()
  })
})

describe('Issue #98 — el código muerto se retira', () => {
  it('should_have_removed_the_duplicate_block_list_and_its_debug_panel', () => {
    // `BlockEditor` era una bifurcación de `WorkspaceEditor` —misma lista, mismas etiquetas,
    // mismo badge y hasta los mismos `data-testid`— que **sólo aparecía en tests**. Dos
    // componentes que dibujan lo mismo y uno no se renderiza es la receta de que un arreglo
    // caiga en el equivocado.
    //
    // Se comprueba contra el sistema de ficheros y **no** con `import()`: Vite resuelve los
    // imports al transformar, así que pedir un módulo que no existe no da una promesa
    // rechazada — rompe el fichero entero antes de ejecutar ni un test. Con esa forma, estas
    // comprobaciones no llegaban a correr y el fichero aparecía como suite fallida.
    const dir = dirname(fileURLToPath(import.meta.url))
    expect(existsSync(resolve(dir, '..', 'BlockEditor.tsx'))).toBe(false)
    expect(existsSync(resolve(dir, '..', 'BlockDebugPanel.tsx'))).toBe(false)
  })
})
