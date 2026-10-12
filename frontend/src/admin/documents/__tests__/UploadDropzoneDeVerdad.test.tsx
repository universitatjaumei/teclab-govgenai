/**
 * La zona de arrastre con `react-dropzone` de verdad, sin mock.
 *
 * Los demás tests de documentos simulan la librería, así que una versión mayor nueva pasaba
 * en verde sin que nadie la ejecutara. Este es el que lo hace, con el caso que la 18 cambió:
 * dejó de traer la tabla extensión→MIME, y un `.md` llega a menudo del navegador con el tipo
 * vacío. Tiene que entrar por la extensión, y un PDF tiene que quedarse fuera (EXT.1).
 */
import { describe, it, expect, vi } from 'vitest'
import { render, fireEvent, waitFor } from '@testing-library/react'

import { UploadDropzone } from '../UploadDropzone'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}))

describe('UploadDropzone con react-dropzone sin simular', () => {
  it('acepta un .md sin tipo MIME y rechaza un PDF', async () => {
    const onDrop = vi.fn()
    const { container } = render(
      <UploadDropzone
        canonicalUrl=""
        onCanonicalUrlChange={vi.fn()}
        uploadLanguage=""
        onUploadLanguageChange={vi.fn()}
        substituteDoc={null}
        onCancelSubstitute={vi.fn()}
        onDrop={onDrop}
        uploadError=""
      />,
    )
    const md = new File(['# Norma\n'], 'norma.md', { type: '' })
    const pdf = new File(['%PDF-1.4'], 'norma.pdf', { type: 'application/pdf' })

    const entrada = container.querySelector('input[type="file"]') as HTMLInputElement
    fireEvent.change(entrada, { target: { files: [md, pdf] } })

    await waitFor(() => expect(onDrop).toHaveBeenCalledTimes(1))
    const [aceptados, rechazados] = onDrop.mock.calls[0]
    expect(aceptados.map((f: File) => f.name)).toEqual(['norma.md'])
    expect(rechazados.map((r: { file: File }) => r.file.name)).toEqual(['norma.pdf'])
  })
})
