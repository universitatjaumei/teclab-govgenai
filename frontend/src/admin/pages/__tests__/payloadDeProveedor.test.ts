import { describe, it, expect } from 'vitest'

import { payloadDeProveedor } from '../payloadDeProveedor'

/**
 * SEC.9.2 — la clave del proveedor dejó de viajar en el contrato, porque cualquier administrador
 * de cualquier organización la leía en claro con un `GET`. Como consecuencia, el formulario ya no
 * la precarga al editar, y ahí aparece el riesgo que este fichero fija: si el campo vacío se
 * enviara, cambiarle el nombre a un proveedor le **borraría la credencial**, y el fallo no se
 * vería al guardar sino en la siguiente llamada al modelo.
 */
describe('payloadDeProveedor', () => {
  const base = {
    id: 'google',
    name: 'Google',
    provider_type: 'google_genai',
    base_url: '',
  }

  it('should_omit_the_key_when_left_empty', () => {
    const payload = payloadDeProveedor({ ...base, api_key: '' })
    expect('api_key' in payload).toBe(false)
  })

  it('should_omit_the_key_when_null', () => {
    const payload = payloadDeProveedor({ ...base, api_key: null })
    expect('api_key' in payload).toBe(false)
  })

  it('should_send_the_key_when_a_new_one_is_typed', () => {
    const payload = payloadDeProveedor({ ...base, api_key: 'una-nueva' })
    expect(payload).toHaveProperty('api_key', 'una-nueva')
  })

  it('should_keep_the_rest_of_the_fields_untouched', () => {
    const payload = payloadDeProveedor({ ...base, base_url: 'http://ollama:11434/v1', api_key: '' })
    expect(payload).toMatchObject({
      id: 'google',
      name: 'Google',
      provider_type: 'google_genai',
      base_url: 'http://ollama:11434/v1',
    })
  })
})
