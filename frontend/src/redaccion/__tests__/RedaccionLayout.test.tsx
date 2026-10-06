import { describe, it, expect, beforeAll } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import i18n from '@/shared/i18n'
import { RedaccionLayout } from '../RedaccionLayout'

/**
 * VER.3 — la propuesta de plantilla con el modelo tiene que estar en el menú.
 *
 * `LLMDraftPreviewPage` hace el camino entero —describir el informe, validar la propuesta y
 * aprobarla como plantilla o como workspace— y su ruta `/redaccion/draft` estaba **fuera de
 * la navegación**: sólo se llegaba escribiendo la URL. Es la misma enfermedad que tenía el
 * módulo entero antes de existir este layout, y desde VER.2 el endpoint que la sostiene ya
 * no devuelve 503, así que la pantalla dejó de ser decorativa.
 *
 * Importa más de lo que parece: el constructor de plantillas guarda `spec_json: {}`, o sea
 * una plantilla sin secciones ni bloques, que no genera nada. Proponer con el modelo es hoy
 * la única vía para obtener una plantilla utilizable desde la interfaz.
 */
beforeAll(async () => {
  await i18n.changeLanguage('es')
})

function renderLayout() {
  return render(
    <MemoryRouter initialEntries={['/redaccion/builder']}>
      <RedaccionLayout />
    </MemoryRouter>
  )
}

describe('RedaccionLayout', () => {
  it('should_offer_the_llm_draft_screen_in_the_menu', () => {
    renderLayout()

    const enlace = screen.getByRole('link', { name: /proponer con ia/i })
    expect(enlace.getAttribute('href')).toBe('/redaccion/draft')
  })

  it('should_keep_the_screens_that_were_already_there', () => {
    renderLayout()

    expect(screen.getByRole('link', { name: /plantillas/i })).toBeDefined()
    expect(screen.getByRole('link', { name: /nuevo informe/i })).toBeDefined()
    expect(screen.getByRole('link', { name: /revisión de scripts/i })).toBeDefined()
  })
})

describe('2026-10-05 — el catálogo de funciones ya no está en Informes', () => {
  it('no ofrece funciones ni su revisión, que pasaron a «Automatización»', () => {
    renderLayout()
    expect(screen.queryByRole('link', { name: /^funciones$/i })).toBeNull()
    expect(screen.queryByRole('link', { name: /revisión posterior/i })).toBeNull()
    // Los scripts siguen: quien redacta propone el de su plantilla.
    expect(screen.getByRole('link', { name: /revisión de scripts/i })).toBeDefined()
  })
})
