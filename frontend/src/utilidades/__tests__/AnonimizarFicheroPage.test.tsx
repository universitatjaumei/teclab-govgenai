import { describe, it, expect, vi, beforeAll, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import i18n from '@/shared/i18n'

const descargar = vi.fn()
vi.mock('@/shared/api/download', () => ({
  descargarConAutorizacion: (...args: unknown[]) => descargar(...args),
}))

const analizar = vi.fn()
const previsualizar = vi.fn()
vi.mock('@/shared/api/generated/utilidades/utilidades', () => ({
  useAnalizarFicheroParaAnonimizar: () => ({ mutate: analizar, isPending: false }),
  useVistaPreviaAnonimizacion: () => ({ mutate: previsualizar, isPending: false }),
}))

import { AnonimizarFicheroPage } from '@/utilidades/pages/AnonimizarFicheroPage'

/**
 * El análisis lo hace el servidor, y con él dice qué tipos y qué reglas hay. La pantalla los pinta
 * sin conocerlos: si este análisis trajera un tipo inventado, también aparecería.
 */
const ANALISIS = {
  formato: 'csv',
  filas: 2,
  hojas: 1,
  semilla: 1234,
  tipos: {
    NONE: ['NINGUNO'],
    DNI: ['AEPD', 'MASK', 'FAKER', 'NINGUNO'],
    EMAIL: ['MASK', 'FAKER', 'NINGUNO'],
    TIPO_DE_PRUEBA: ['REGLA_DE_PRUEBA', 'NINGUNO'],
  },
  columnas: [
    { columna: 'DNI', tipo: 'DNI', modo: 'AEPD', modos_posibles: ['AEPD', 'MASK', 'FAKER', 'NINGUNO'], confianza: 1, ejemplos: ['12345678Z'] },
    { columna: 'Importe', tipo: 'NONE', modo: 'NINGUNO', modos_posibles: ['NINGUNO'], confianza: 0, ejemplos: ['12,50'] },
  ],
}

const VISTA = {
  columnas: ['DNI', 'Importe'],
  antes: [['12345678Z', '12,50']],
  despues: [['***4567**', '12,50']],
}

function montar() {
  return render(
    <MemoryRouter>
      <AnonimizarFicheroPage />
    </MemoryRouter>,
  )
}

function subir() {
  fireEvent.change(screen.getByTestId('input-anon'), {
    target: { files: [new File(['DNI;Importe'], 'listado.csv', { type: 'text/csv' })] },
  })
}

describe('AnonimizarFicheroPage (UTL.2, #191)', () => {
  beforeAll(async () => {
    await i18n.changeLanguage('es')
  })
  beforeEach(() => {
    descargar.mockReset()
    descargar.mockResolvedValue(undefined)
    analizar.mockReset()
    analizar.mockImplementation((_vars, opciones) => opciones.onSuccess(ANALISIS))
    previsualizar.mockReset()
    previsualizar.mockImplementation((_vars, opciones) => opciones.onSuccess(VISTA))
  })

  it('dice desde el principio que no es anonimato garantizado', () => {
    montar()
    expect(screen.getByRole('note')).toHaveTextContent('seudonimización asistida, no anonimato garantizado')
  })

  it('los tipos y las reglas salen del análisis del servidor, incluido uno que la pantalla no conoce', () => {
    montar()
    subir()

    const tipos = Array.from(screen.getByLabelText('Qué contiene: DNI').querySelectorAll('option')).map((o) => o.value)
    expect(tipos).toEqual(['NONE', 'DNI', 'EMAIL', 'TIPO_DE_PRUEBA'])
    const reglas = Array.from(screen.getByLabelText('Regla: DNI').querySelectorAll('option')).map((o) => o.value)
    expect(reglas).toEqual(['AEPD', 'MASK', 'FAKER', 'NINGUNO'])
  })

  it('al cambiar el tipo, la regla pasa a una que ese tipo admite', () => {
    montar()
    subir()
    fireEvent.change(screen.getByLabelText('Qué contiene: DNI'), { target: { value: 'EMAIL' } })

    expect((screen.getByLabelText('Regla: DNI') as HTMLSelectElement).value).toBe('MASK')
  })

  it('no deja descargar sin vista previa ni sin confirmar la revisión', async () => {
    montar()
    subir()
    expect(screen.queryByRole('button', { name: 'Descargar el fichero anonimizado' })).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Ver cómo queda' }))
    const boton = screen.getByRole('button', { name: 'Descargar el fichero anonimizado' })
    expect(boton).toBeDisabled()

    fireEvent.click(screen.getByRole('checkbox'))
    expect(boton).toBeEnabled()
    fireEvent.click(boton)

    await waitFor(() => expect(descargar).toHaveBeenCalled())
    const [ruta, , cuerpo] = descargar.mock.calls[0]
    expect(ruta).toBe('/api/v1/utilidades/anonimizar/descargar')
    expect((cuerpo as FormData).get('revisado')).toBe('true')
    expect((cuerpo as FormData).get('semilla')).toBe('1234')
    expect(JSON.parse((cuerpo as FormData).get('reglas') as string)).toEqual({
      DNI: { tipo: 'DNI', modo: 'AEPD' },
      Importe: { tipo: 'NONE', modo: 'NINGUNO' },
    })
  })

  it('la vista previa y la descarga usan la misma semilla', () => {
    montar()
    subir()
    fireEvent.click(screen.getByRole('button', { name: 'Ver cómo queda' }))

    expect(previsualizar.mock.calls[0][0].data.semilla).toBe(1234)
  })

  it('cambiar una regla después de ver la vista previa obliga a volver a verla', () => {
    montar()
    subir()
    fireEvent.click(screen.getByRole('button', { name: 'Ver cómo queda' }))
    fireEvent.click(screen.getByRole('checkbox'))

    fireEvent.change(screen.getByLabelText('Regla: DNI'), { target: { value: 'MASK' } })

    expect(screen.getByRole('checkbox')).not.toBeChecked()
    expect(screen.getByRole('checkbox')).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Descargar el fichero anonimizado' })).toBeDisabled()
    expect(screen.getByText(/Has cambiado las reglas/)).toBeInTheDocument()
  })

  it('avisa cuando el Excel tiene más de una hoja', () => {
    analizar.mockImplementation((_vars, opciones) => opciones.onSuccess({ ...ANALISIS, formato: 'xlsx', hojas: 3 }))
    montar()
    subir()

    expect(screen.getByText(/tiene 3 hojas y sólo se anonimiza la primera/)).toBeInTheDocument()
  })
})
