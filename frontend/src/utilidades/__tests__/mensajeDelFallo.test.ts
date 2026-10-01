import { describe, it, expect } from 'vitest'

import { mensajeDelFallo } from '@/utilidades/mensajeDelFallo'

describe('mensajeDelFallo', () => {
  it('un detail de texto se enseña tal cual', () => {
    expect(mensajeDelFallo({ response: { data: { detail: 'no cabe' } } }, 'genérico')).toBe('no cabe')
  })

  it('un detail objeto enseña su message: el 403 de quien no tiene una sola organización', () => {
    const fallo = {
      response: { data: { detail: { code: 'ORGANIZACION_INDETERMINADA', message: 'entra con una cuenta de una organización' } } },
    }
    expect(mensajeDelFallo(fallo, 'genérico')).toBe('entra con una cuenta de una organización')
  })

  it('el mensaje genérico de axios no se enseña: no dice nada que la pantalla no diga mejor', () => {
    expect(mensajeDelFallo(new Error('Request failed with status code 500'), 'No se ha podido.')).toBe('No se ha podido.')
  })
})
