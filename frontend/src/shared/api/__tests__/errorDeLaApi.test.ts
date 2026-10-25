import { describe, it, expect } from 'vitest'

import { errorDeLaApi } from '@/shared/api/errorDeLaApi'

const conDetalle = (detail: unknown) => ({ response: { data: { detail } } })

describe('errorDeLaApi (#276)', () => {
  it('devuelve el error con su code, su message y los campos que añada el endpoint', () => {
    const error = errorDeLaApi(
      conDetalle({ code: 'CONFLICT', message: 'faltan apartados', pending_block_ids: ['b1'] }),
    )
    expect(error?.code).toBe('CONFLICT')
    expect(error?.message).toBe('faltan apartados')
    expect(error?.pending_block_ids).toEqual(['b1'])
  })

  it('la validación de entrada de FastAPI es una lista, no un error con formato único', () => {
    expect(errorDeLaApi(conDetalle([{ loc: ['body', 'n'], msg: 'm', type: 't' }]))).toBeNull()
  })

  it('un fallo sin respuesta —de red— no trae error de la API', () => {
    expect(errorDeLaApi(new Error('Network Error'))).toBeNull()
  })

  it('un objeto sin code o sin message no se da por bueno', () => {
    expect(errorDeLaApi(conDetalle({ message: 'sin código' }))).toBeNull()
  })
})
