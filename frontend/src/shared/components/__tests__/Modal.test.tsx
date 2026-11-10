import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative, resolve } from 'node:path'

import { Modal } from '../Modal'
import { codigoSinComentarios } from '@/test-utils/codigoSinComentarios'

/**
 * #374 — un formulario más alto que la ventana se puede recorrer.
 *
 * «Nueva web» de Curación salía cortada en un portátil: la capa centraba el panel y el panel no
 * tenía altura máxima, así que lo que sobraba quedaba fuera de la pantalla, botones incluidos.
 * jsdom no maqueta, de modo que lo que se fija aquí son las clases que lo garantizan y que la
 * cabecera y el pie están **fuera** de la zona que se desplaza.
 */
describe('#374 — Modal', () => {
  it('should_cap_the_panel_to_the_window_and_scroll_the_body', () => {
    render(<Modal ariaLabel="Nueva web" header={<h2>T</h2>} footer={<button>Guardar</button>}><p>campos</p></Modal>)

    const capa = screen.getByRole('dialog', { name: 'Nueva web' })
    expect(capa.className).toMatch(/\bfixed\b/)
    expect(capa.className).toMatch(/\bp-4\b/)
    const panel = capa.firstElementChild as HTMLElement
    expect(panel.className).toMatch(/\bmax-h-full\b/)
    expect(panel.className).toMatch(/\bflex-col\b/)

    const cuerpo = capa.querySelector('[data-modal-body]') as HTMLElement
    expect(cuerpo.className).toMatch(/\boverflow-y-auto\b/)
    expect(cuerpo.className).toMatch(/\bmin-h-0\b/)
    expect(cuerpo).toContainElement(screen.getByText('campos'))
  })

  it('should_keep_header_and_footer_out_of_the_scrolling_body', () => {
    render(<Modal header={<h2>Título</h2>} footer={<button>Guardar</button>}><p>campos</p></Modal>)

    const cuerpo = document.querySelector('[data-modal-body]') as HTMLElement
    expect(cuerpo).not.toContainElement(screen.getByText('Título'))
    expect(cuerpo).not.toContainElement(screen.getByRole('button', { name: 'Guardar' }))
  })

  it('should_make_the_whole_panel_the_form_so_the_footer_button_submits', () => {
    const onSubmit = vi.fn((e: { preventDefault: () => void }) => e.preventDefault())
    render(
      <Modal form={{ onSubmit, 'data-testid': 'f' }} footer={<button type="submit">Guardar</button>}>
        <input aria-label="nombre" />
      </Modal>,
    )

    const formulario = screen.getByTestId('f')
    expect(formulario.tagName).toBe('FORM')
    expect(formulario).toContainElement(screen.getByRole('button', { name: 'Guardar' }))
    fireEvent.click(screen.getByRole('button', { name: 'Guardar' }))
    expect(onSubmit).toHaveBeenCalledOnce()
  })

  it('should_close_on_backdrop_click_only', () => {
    const onBackdropClick = vi.fn()
    render(<Modal onBackdropClick={onBackdropClick}><p>dentro</p></Modal>)

    fireEvent.click(screen.getByText('dentro'))
    expect(onBackdropClick).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('dialog'))
    expect(onBackdropClick).toHaveBeenCalledOnce()
  })
})

/** El guardarraíl: la capa modal se escribe una vez. Las diecisiete que había a mano repetían el
 * defecto doce veces; la próxima que se escriba fuera de `Modal` lo repetiría otra. */
const SRC = resolve(__dirname, '../../..')
const IGNORADOS = new Set(['generated', 'node_modules', '__tests__', 'test-utils'])
const PERMITIDOS = new Set(['shared/components/Modal.tsx'])
const CAPA_A_MANO = /fixed\s+inset-0/

function ficherosDeCodigo(directorio: string): string[] {
  return readdirSync(directorio).flatMap((entrada) => {
    const ruta = join(directorio, entrada)
    if (statSync(ruta).isDirectory()) return IGNORADOS.has(entrada) ? [] : ficherosDeCodigo(ruta)
    return /\.tsx$/.test(entrada) && !/\.test\.tsx$/.test(entrada) ? [ruta] : []
  })
}

describe('#374 — ninguna capa modal fuera de Modal', () => {
  it('should_find_code_to_look_at', () => {
    expect(ficherosDeCodigo(SRC).length).toBeGreaterThan(100)
  })

  it('should_not_build_a_fixed_overlay_by_hand', () => {
    const culpables = ficherosDeCodigo(SRC)
      .map((ruta) => relative(SRC, ruta).replaceAll('\\', '/'))
      .filter((ruta) => !PERMITIDOS.has(ruta))
      .filter((ruta) => CAPA_A_MANO.test(codigoSinComentarios(readFileSync(join(SRC, ruta), 'utf-8'))))
    expect(culpables).toEqual([])
  })
})
