/**
 * Tests 9R.7.1 (RED → GREEN)
 * ReportUIContractRenderer + DynamicUploadSlots + DynamicFieldRenderer
 */
import { describe, it, expect, vi, beforeAll } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import i18n from '@/shared/i18n'

import { ReportUIContractRenderer } from '../components/ReportUIContractRenderer'
import type { ReportUIContract } from '@/shared/api/generated/model'

beforeAll(async () => {
  await i18n.changeLanguage('es')
})

const SAMPLE_CONTRACT: ReportUIContract = {
  wizard_steps: [
    { id: 'step1', title: 'Datos', order: 0, block_ids: ['b1'] },
  ],
  dropzones: [
    {
      slot_id: 'excel_input',
      label: { es: 'Archivo Excel', en: 'Excel File' },
      accept: ['.xlsx', '.xls'],
      multiple: false,
      max_size_mb: 10,
    },
  ],
  manual_fields: [
    {
      slot_id: 'titulo',
      label: { es: 'Título del informe', en: 'Report title' },
      field_type: 'text',
      placeholder: { es: 'Introduce el título', en: 'Enter title' },
      required: true,
    },
    {
      slot_id: 'notas',
      label: { es: 'Notas adicionales', en: 'Additional notes' },
      field_type: 'text',
      placeholder: { es: 'Opcional', en: 'Optional' },
      required: false,
    },
  ],
  block_editor_enabled: false,
  ai_review_panel_enabled: false,
  preview_layout: 'markdown',
}

describe('DynamicUploadSlots', () => {
  it('should_render_upload_slots_from_ui_contract', () => {
    render(
      <ReportUIContractRenderer
        contract={SAMPLE_CONTRACT}
        onSubmit={vi.fn()}
      />
    )
    // The dropzone label should be rendered
    expect(screen.getByText('Archivo Excel')).toBeDefined()
    // File input with correct accept attribute
    const fileInput = screen.getByLabelText('Archivo Excel') as HTMLInputElement
    expect(fileInput.accept).toBe('.xlsx,.xls')
  })
})

describe('DynamicFieldRenderer', () => {
  it('should_render_dynamic_fields_from_ui_contract', () => {
    render(
      <ReportUIContractRenderer
        contract={SAMPLE_CONTRACT}
        onSubmit={vi.fn()}
      />
    )
    expect(screen.getByLabelText(/Título del informe/)).toBeDefined()
    expect(screen.getByLabelText('Notas adicionales')).toBeDefined()
  })

  it('should_block_continue_when_required_input_missing', async () => {
    const onSubmit = vi.fn()
    render(
      <ReportUIContractRenderer
        contract={SAMPLE_CONTRACT}
        onSubmit={onSubmit}
      />
    )

    // Click submit without filling required field
    fireEvent.click(screen.getByRole('button', { name: /continuar/i }))

    // onSubmit must not be called
    await waitFor(() => {
      expect(onSubmit).not.toHaveBeenCalled()
    })
  })

  it('should_show_validation_error_on_invalid_field', async () => {
    render(
      <ReportUIContractRenderer
        contract={SAMPLE_CONTRACT}
        onSubmit={vi.fn()}
      />
    )

    const titleInput = screen.getByLabelText(/Título del informe/)
    // Touch the field and leave empty
    fireEvent.blur(titleInput)
    fireEvent.click(screen.getByRole('button', { name: /continuar/i }))

    await waitFor(() => {
      expect(screen.getByRole('alert')).toBeDefined()
    })
  })

  it('should_render_localized_labels_from_dict', () => {
    render(
      <ReportUIContractRenderer
        contract={SAMPLE_CONTRACT}
        onSubmit={vi.fn()}
      />
    )
    // i18n is set to 'es' — Spanish labels must be visible
    expect(screen.getByText('Título del informe')).toBeDefined()
    expect(screen.getByText('Notas adicionales')).toBeDefined()
    expect(screen.getByText('Archivo Excel')).toBeDefined()
    // English labels must NOT be visible
    expect(screen.queryByText('Report title')).toBeNull()
    expect(screen.queryByText('Excel File')).toBeNull()
  })
})

/**
 * INF.1 — un fichero obligatorio se exige **antes** de lanzar el informe.
 *
 * `UIFieldDescriptor` tenía `required` y `UIDropzoneDescriptor` no, así que el zod de este
 * componente solo validaba los campos de texto: un informe cuyo dato de partida es un fichero
 * se enviaba vacío. Es la mitad de pantalla del bloqueo A de las pruebas humanas del
 * 2026-08-20 —el usuario lanzó el informe sin fichero y nadie se lo dijo—.
 */
describe('INF.1 — el fichero obligatorio se valida antes de lanzar', () => {
  const CON_FICHERO_OBLIGATORIO: ReportUIContract = {
    ...SAMPLE_CONTRACT,
    dropzones: [
      {
        slot_id: 'datos',
        label: { es: 'Informe resumen', en: 'Summary' },
        accept: ['.md'],
        multiple: false,
        max_size_mb: null,
        required: true,
      },
      {
        slot_id: 'anexo',
        label: { es: 'Anexo opcional', en: 'Optional annex' },
        accept: ['.pdf'],
        multiple: false,
        max_size_mb: null,
        required: false,
      },
    ],
    manual_fields: [],
  }

  it('should_block_the_submit_when_a_required_file_is_missing', async () => {
    const onSubmit = vi.fn()
    render(<ReportUIContractRenderer contract={CON_FICHERO_OBLIGATORIO} onSubmit={onSubmit} />)

    fireEvent.click(screen.getByRole('button', { name: /continuar/i }))

    // Se espera a que **aparezca el aviso** y solo entonces se comprueba que no se envió.
    // Un `waitFor` sobre una aserción negativa se cumple en el instante 0 y da un falso verde
    // aunque el envío ocurra un tick después: hay que anclarlo a algo que sí pasa.
    await screen.findByRole('alert')
    expect(onSubmit).not.toHaveBeenCalled()
  })

  it('should_name_the_missing_file_so_the_user_knows_which_one', async () => {
    render(<ReportUIContractRenderer contract={CON_FICHERO_OBLIGATORIO} onSubmit={vi.fn()} />)

    fireEvent.click(screen.getByRole('button', { name: /continuar/i }))

    // El aviso tiene que estar donde está el campo, y nombrarlo: «falta algo» no sirve.
    const avisos = await screen.findAllByRole('alert')
    expect(avisos.some((a) => /informe resumen/i.test(a.textContent ?? ''))).toBe(true)
  })

  it('should_submit_once_the_required_file_is_chosen', async () => {
    const onSubmit = vi.fn()
    render(<ReportUIContractRenderer contract={CON_FICHERO_OBLIGATORIO} onSubmit={onSubmit} />)

    const entrada = screen.getByLabelText(/informe resumen/i) as HTMLInputElement
    fireEvent.change(entrada, {
      target: { files: [new File(['# tabla'], 'informe.md', { type: 'text/markdown' })] },
    })
    fireEvent.click(screen.getByRole('button', { name: /continuar/i }))

    await waitFor(() => expect(onSubmit).toHaveBeenCalled())
    expect(onSubmit.mock.calls[0][0].files.datos).toHaveLength(1)
  })

  it('should_not_demand_the_optional_file', async () => {
    const onSubmit = vi.fn()
    render(<ReportUIContractRenderer contract={CON_FICHERO_OBLIGATORIO} onSubmit={onSubmit} />)

    fireEvent.change(screen.getByLabelText(/informe resumen/i), {
      target: { files: [new File(['# tabla'], 'informe.md')] },
    })
    fireEvent.click(screen.getByRole('button', { name: /continuar/i }))

    await waitFor(() => expect(onSubmit).toHaveBeenCalled())
  })
})
