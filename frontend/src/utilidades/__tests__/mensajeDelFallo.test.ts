import { describe, it, expect } from 'vitest'

import { mensajeDelFallo } from '@/utilidades/mensajeDelFallo'

describe('mensajeDelFallo', () => {
  it('la validación de entrada no es un error con formato único: se usa el mensaje del interceptor', () => {
    // #276 — todo error sale como `{code, message}` salvo la validación de FastAPI, que es una
    // lista; de ella el interceptor ya ha compuesto `message`.
    const fallo = Object.assign(new Error('n: debe ser un número'), {
      response: { data: { detail: [{ loc: ['body', 'n'], msg: 'debe ser un número', type: 'int' }] } },
    })
    expect(mensajeDelFallo(fallo, 'genérico')).toBe('n: debe ser un número')
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
