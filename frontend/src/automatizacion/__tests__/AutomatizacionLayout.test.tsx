import { describe, it, expect, beforeAll } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import i18n from '@/shared/i18n'
import { AutomatizacionLayout } from '../AutomatizacionLayout'

/**
 * 2026-10-05 — «Automatización», el módulo del catálogo de funciones (opción A del usuario).
 * Las pantallas son las que estaban en Informes; cambia dónde viven, no lo que hacen.
 */
beforeAll(async () => {
  await i18n.changeLanguage('es')
})

describe('AutomatizacionLayout', () => {
  it('ofrece el catálogo de funciones y su revisión posterior', () => {
    render(
      <MemoryRouter initialEntries={['/automatizacion/funciones']}>
        <AutomatizacionLayout />
      </MemoryRouter>,
    )
    expect(screen.getByRole('link', { name: /^funciones$/i }).getAttribute('href')).toBe('/automatizacion/funciones')
    expect(screen.getByRole('link', { name: /revisión posterior/i }).getAttribute('href')).toBe(
      '/automatizacion/funciones/revision',
    )
  })
})
