import { describe, it, expect, vi } from 'vitest'
import { useState } from 'react'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
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
    render(<Modal onClose={null} ariaLabel="Nueva web" header={<h2>T</h2>} footer={<button>Guardar</button>}><p>campos</p></Modal>)

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
    render(<Modal onClose={null} header={<h2>Título</h2>} footer={<button>Guardar</button>}><p>campos</p></Modal>)

    const cuerpo = document.querySelector('[data-modal-body]') as HTMLElement
    expect(cuerpo).not.toContainElement(screen.getByText('Título'))
    expect(cuerpo).not.toContainElement(screen.getByRole('button', { name: 'Guardar' }))
  })

  it('should_make_the_whole_panel_the_form_so_the_footer_button_submits', () => {
    const onSubmit = vi.fn((e: { preventDefault: () => void }) => e.preventDefault())
    render(
      <Modal onClose={null} form={{ onSubmit, 'data-testid': 'f' }} footer={<button type="submit">Guardar</button>}>
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
    render(<Modal onClose={null} onBackdropClick={onBackdropClick}><p>dentro</p></Modal>)

    fireEvent.click(screen.getByText('dentro'))
    expect(onBackdropClick).not.toHaveBeenCalled()
    fireEvent.mouseDown(screen.getByRole('dialog'))
    fireEvent.click(screen.getByRole('dialog'))
    expect(onBackdropClick).toHaveBeenCalledOnce()
  })

  it('should_not_close_when_a_drag_starts_inside_and_ends_on_the_backdrop', () => {
    // Revisión de la PR #375: seleccionar texto en un campo y soltar sobre la capa manda el
    // `click` a la capa —el ancestro común— y cerraba el chatbot perdiendo lo escrito.
    const onBackdropClick = vi.fn()
    render(<Modal onClose={null} onBackdropClick={onBackdropClick}><textarea aria-label="prompt" /></Modal>)

    fireEvent.mouseDown(screen.getByRole('textbox', { name: 'prompt' }))
    fireEvent.click(screen.getByRole('dialog'))
    expect(onBackdropClick).not.toHaveBeenCalled()
  })

  it('should_name_the_dialog_after_its_header_by_default', () => {
    render(<Modal onClose={null} header={<h3>Borrar sitio</h3>}><p>¿Seguro?</p></Modal>)
    expect(screen.getByRole('dialog', { name: 'Borrar sitio' })).toBeInTheDocument()
  })

  it('should_name_the_dialog_after_the_heading_not_the_whole_header', () => {
    // #376, visto en el navegador: el chatbot se llamaba «Nou chatbot ✕» porque la cabecera
    // lleva también el aspa de cerrar.
    render(
      <Modal onClose={null} header={<><h2>Nou chatbot</h2><button aria-label="Cancel·lar">✕</button></>}>
        <p>x</p>
      </Modal>,
    )
    expect(screen.getByRole('dialog', { name: 'Nou chatbot' })).toBeInTheDocument()
  })

  it('should_prefer_an_explicit_label_over_the_header', () => {
    render(<Modal onClose={null} ariaLabel="Nombre explícito" header={<h3>Cabecera</h3>}><p>x</p></Modal>)
    expect(screen.getByRole('dialog', { name: 'Nombre explícito' })).toBeInTheDocument()
  })
})

/**
 * #376 — con teclado se entra, se queda dentro y se sale.
 *
 * Las ventanas declaraban `aria-modal="true"` pero Tab llevaba el foco a la página de detrás,
 * Escape no hacía nada y al cerrar el foco caía en `<body>`. Es el defecto que DrawerHub ya
 * arregló con `FocusLock returnFocus` y un Escape (INF.8).
 */
describe('#376 — Modal y el teclado', () => {
  it('should_close_with_escape', () => {
    const onClose = vi.fn()
    render(<Modal onClose={onClose}><input aria-label="campo" /></Modal>)

    fireEvent.keyDown(screen.getByRole('textbox', { name: 'campo' }), { key: 'Escape' })
    expect(onClose).toHaveBeenCalledOnce()
  })

  it('should_not_close_with_escape_while_it_cannot_close', () => {
    // `ConfirmDialog` bloquea Cancelar mientras borra: Escape tampoco puede cerrar entonces.
    render(<Modal onClose={null}><input aria-label="campo" /></Modal>)
    expect(() => fireEvent.keyDown(screen.getByRole('textbox', { name: 'campo' }), { key: 'Escape' })).not.toThrow()
    expect(screen.getByRole('dialog')).toBeInTheDocument()
  })

  it('should_close_only_the_topmost_dialog_with_escape', () => {
    const exterior = vi.fn()
    const interior = vi.fn()
    render(
      <Modal onClose={exterior}>
        <Modal onClose={interior}><input aria-label="dentro" /></Modal>
      </Modal>,
    )
    fireEvent.keyDown(screen.getByRole('textbox', { name: 'dentro' }), { key: 'Escape' })
    expect(interior).toHaveBeenCalledOnce()
    expect(exterior).not.toHaveBeenCalled()
  })

  it('should_move_focus_inside_when_it_opens', async () => {
    render(<Modal onClose={null}><input aria-label="primero" /></Modal>)
    await waitFor(() => expect(screen.getByRole('dialog')).toContainElement(document.activeElement as HTMLElement))
  })

  it('should_return_focus_to_the_opener_when_it_closes', async () => {
    function Pagina() {
      const [abierta, setAbierta] = useState(false)
      return (
        <>
          <button onClick={() => setAbierta(true)}>Abrir</button>
          {abierta && (
            <Modal onClose={() => setAbierta(false)}><input aria-label="campo" /></Modal>
          )}
        </>
      )
    }
    render(<Pagina />)
    const abrir = screen.getByRole('button', { name: 'Abrir' })
    abrir.focus()
    fireEvent.click(abrir)
    await waitFor(() => expect(screen.getByRole('dialog')).toHaveFocus())

    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' })
    expect(screen.queryByRole('dialog')).toBeNull()
    await waitFor(() => expect(abrir).toHaveFocus())
  })

  it('should_focus_the_dialog_itself_not_its_first_button', async () => {
    // Revisión de la PR #377: «Retirar» va primero en el pie de archivar una plantilla, y un
    // segundo Enter —o el autorrepetir de la tecla— archivaba sin elegirlo.
    render(
      <Modal onClose={null} header={<h2>Retirar plantilla</h2>} footer={<button>Retirar</button>}><p>x</p></Modal>,
    )
    await waitFor(() => expect(screen.getByRole('dialog', { name: 'Retirar plantilla' })).toHaveFocus())
  })

  it('should_leave_escape_to_a_child_that_already_used_it', () => {
    const onClose = vi.fn()
    render(
      <Modal onClose={onClose}>
        <input aria-label="combo" onKeyDown={(e) => { if (e.key === 'Escape') e.preventDefault() }} />
      </Modal>,
    )
    fireEvent.keyDown(screen.getByRole('textbox', { name: 'combo' }), { key: 'Escape' })
    expect(onClose).not.toHaveBeenCalled()
  })

  it('should_not_close_while_an_ime_composition_is_cancelled', () => {
    const onClose = vi.fn()
    render(<Modal onClose={onClose}><textarea aria-label="prompt" /></Modal>)
    fireEvent.keyDown(screen.getByRole('textbox', { name: 'prompt' }), { key: 'Escape', isComposing: true })
    expect(onClose).not.toHaveBeenCalled()
  })

  it('should_not_close_on_the_safari_ime_escape', () => {
    // Safari marca la tecla que cancela la composición con keyCode 229, no con isComposing.
    const onClose = vi.fn()
    render(<Modal onClose={onClose}><textarea aria-label="prompt" /></Modal>)
    fireEvent.keyDown(screen.getByRole('textbox', { name: 'prompt' }), { key: 'Escape', keyCode: 229 })
    expect(onClose).not.toHaveBeenCalled()
  })

  it('should_keep_an_escape_a_child_used_from_reaching_window', () => {
    // DrawerHub escucha Escape en window: el que se quedó un hijo no debe cerrar el cajón.
    const enWindow = vi.fn()
    window.addEventListener('keydown', enWindow)
    render(
      <Modal onClose={vi.fn()}>
        <input aria-label="combo" onKeyDown={(e) => { if (e.key === 'Escape') e.preventDefault() }} />
      </Modal>,
    )
    fireEvent.keyDown(screen.getByRole('textbox', { name: 'combo' }), { key: 'Escape' })
    window.removeEventListener('keydown', enWindow)
    expect(enWindow).not.toHaveBeenCalled()
  })

  it('should_keep_focus_on_a_field_that_takes_it_with_autofocus', async () => {
    render(<Modal onClose={null} footer={<button>Guardar</button>}><input aria-label="nombre" autoFocus /></Modal>)
    await waitFor(() => expect(screen.getByRole('textbox', { name: 'nombre' })).toHaveFocus())
  })

  it('should_take_focus_back_when_its_content_drops_it', async () => {
    // Tercera revisión de la PR #377: en Tokens el panel pasa de <form> a <div> al crear el
    // token y el botón enfocado desaparece. FocusLock recupera el foco —en Chrome cae en
    // «Copiar»—; esto fija que no se quede en <body>.
    function Pagina() {
      const [hecho, setHecho] = useState(false)
      return (
        <Modal onClose={null} ariaLabel="Token" form={hecho ? undefined : { onSubmit: (e) => { e.preventDefault(); setHecho(true) } }}>
          {hecho ? <p>creado</p> : <button type="submit">Crear</button>}
        </Modal>
      )
    }
    render(<Pagina />)
    const crear = screen.getByRole('button', { name: 'Crear' })
    crear.focus()
    fireEvent.click(crear)
    await waitFor(() => expect(screen.getByText('creado')).toBeInTheDocument())
    await waitFor(() => expect(screen.getByRole('dialog', { name: 'Token' })).toHaveFocus())
  })

  it('should_return_focus_to_the_opener_when_its_content_is_replaced', async () => {
    // Revisión de la PR #377: crear un token cierra el formulario y abre el del token en el
    // mismo render; al cerrar éste el foco caía en <body>.
    function Pagina() {
      const [paso, setPaso] = useState<'nada' | 'form' | 'hecho'>('nada')
      return (
        <>
          <button onClick={() => setPaso('form')}>Nuevo</button>
          {/* La misma Modal con otro contenido, no dos: así se escribe una sustitución. */}
          {paso !== 'nada' && (
            <Modal onClose={() => setPaso('nada')}>
              {paso === 'form' ? <button onClick={() => setPaso('hecho')}>Crear</button> : <p>creado</p>}
            </Modal>
          )}
        </>
      )
    }
    render(<Pagina />)
    const nuevo = screen.getByRole('button', { name: 'Nuevo' })
    nuevo.focus()
    fireEvent.click(nuevo)
    await waitFor(() => expect(screen.getByRole('dialog')).toHaveFocus())
    const crear = screen.getByRole('button', { name: 'Crear' })
    crear.focus()
    fireEvent.click(crear)
    await waitFor(() => expect(screen.getByText('creado')).toBeInTheDocument())
    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' })
    await waitFor(() => expect(nuevo).toHaveFocus())
  })
})

/** El guardarraíl: la capa modal se escribe una vez. Las diecisiete que había a mano repetían el
 * defecto doce veces; la próxima que se escriba fuera de `Modal` lo repetiría otra. */
const SRC = resolve(__dirname, '../../..')
const IGNORADOS = new Set(['generated', 'node_modules', '__tests__', 'test-utils'])
const PERMITIDOS = new Set(['shared/components/Modal.tsx'])
/** `fixed` e `inset-0` en el mismo atributo de clases, en cualquier orden (revisión de la PR
 * #375: `fixed z-50 inset-0` pasaba con la expresión anterior). */
function tieneCapaAMano(codigo: string): boolean {
  return [...codigo.matchAll(/className=(?:"([^"]*)"|\{`([^`]*)`\}|'([^']*)')/g)]
    .map((m) => m[1] ?? m[2] ?? m[3])
    .some((clases) => /(^|\s)fixed(\s|$)/.test(clases) && /(^|\s)inset-0(\s|$)/.test(clases))
}

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
      .filter((ruta) => tieneCapaAMano(codigoSinComentarios(readFileSync(join(SRC, ruta), 'utf-8'))))
    expect(culpables).toEqual([])
  })

  it('should_catch_an_overlay_whatever_the_class_order', () => {
    expect(tieneCapaAMano('<div className="fixed z-50 inset-0 bg-black/40">')).toBe(true)
    expect(tieneCapaAMano('<div className={`inset-0 fixed ${x}`}>')).toBe(true)
    expect(tieneCapaAMano('<div className="fixed bottom-4 right-4">')).toBe(false)
    expect(tieneCapaAMano('<div className="absolute inset-0">')).toBe(false)
  })
})
