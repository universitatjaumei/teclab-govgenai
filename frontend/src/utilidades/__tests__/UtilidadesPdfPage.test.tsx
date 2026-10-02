import { describe, it, expect, vi, beforeAll, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import i18n from '@/shared/i18n'

const descargar = vi.fn()
vi.mock('@/shared/api/download', () => ({
  descargarConAutorizacion: (...args: unknown[]) => descargar(...args),
}))

import { UtilidadesPdfPage } from '@/utilidades/pages/UtilidadesPdfPage'

function pdf(nombre: string) {
  return new File(['%PDF-1.7'], nombre, { type: 'application/pdf' })
}

function montar() {
  return render(
    <MemoryRouter>
      <UtilidadesPdfPage />
    </MemoryRouter>,
  )
}

describe('UtilidadesPdfPage (UTL.1, #190)', () => {
  beforeAll(async () => {
    await i18n.changeLanguage('es')
  })
  beforeEach(() => {
    descargar.mockReset()
    descargar.mockResolvedValue(undefined)
  })

  it('unir pide al menos dos PDF antes de dejar pulsar', () => {
    montar()
    const boton = screen.getByRole('button', { name: 'Unir y descargar' })
    expect(boton).toBeDisabled()

    fireEvent.change(screen.getByTestId('input-pdf'), { target: { files: [pdf('a.pdf')] } })
    expect(boton).toBeDisabled()
    expect(screen.getByText('Para unir hacen falta al menos dos PDF.')).toBeInTheDocument()

    fireEvent.change(screen.getByTestId('input-pdf'), { target: { files: [pdf('b.pdf')] } })
    expect(boton).toBeEnabled()
  })

  it('manda los ficheros en el orden de la lista, también después de reordenarlos', async () => {
    montar()
    fireEvent.change(screen.getByTestId('input-pdf'), { target: { files: [pdf('a.pdf'), pdf('b.pdf')] } })
    fireEvent.click(screen.getAllByRole('button', { name: 'Bajar' })[0])
    fireEvent.click(screen.getByRole('button', { name: 'Unir y descargar' }))

    await waitFor(() => expect(descargar).toHaveBeenCalled())
    const [ruta, , cuerpo] = descargar.mock.calls[0]
    expect(ruta).toBe('/api/v1/utilidades/pdf/unir')
    const nombres = (cuerpo as FormData).getAll('files').map((f) => (f as File).name)
    expect(nombres).toEqual(['b.pdf', 'a.pdf'])
  })

  it('dividir manda el modo y los rangos tal como se escriben: los valida el servidor', async () => {
    montar()
    fireEvent.click(screen.getByText('Dividir'))
    fireEvent.change(screen.getByTestId('input-pdf'), { target: { files: [pdf('exp.pdf')] } })
    fireEvent.change(screen.getByLabelText('Páginas o rangos'), { target: { value: '1-3, 5' } })
    fireEvent.click(screen.getByRole('button', { name: 'Dividir y descargar' }))

    await waitFor(() => expect(descargar).toHaveBeenCalled())
    const cuerpo = descargar.mock.calls[0][2] as FormData
    expect(cuerpo.get('modo')).toBe('rangos')
    expect(cuerpo.get('rangos')).toBe('1-3, 5')
  })

  it('los niveles de optimizar salen del contrato', () => {
    montar()
    fireEvent.click(screen.getByText('Optimizar'))
    const opciones = Array.from(screen.getByLabelText('Nivel').querySelectorAll('option')).map((o) => o.value)
    expect(opciones).toEqual(['1', '2', '3', '4'])
  })

  it('enseña el motivo que da el servidor cuando algo no se puede hacer', async () => {
    descargar.mockRejectedValue({
      response: { data: { detail: 'el rango 2-9 no cabe: el documento tiene 3 páginas' } },
    })
    montar()
    fireEvent.click(screen.getByText('Dividir'))
    fireEvent.change(screen.getByTestId('input-pdf'), { target: { files: [pdf('exp.pdf')] } })
    fireEvent.click(screen.getByRole('button', { name: 'Dividir y descargar' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('el documento tiene 3 páginas')
  })
})
