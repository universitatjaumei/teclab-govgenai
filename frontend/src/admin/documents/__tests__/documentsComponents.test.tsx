/**
 * CAL.3 — Los subcomponentes de la pantalla de documentos existen y se renderizan solos.
 *
 * `DocumentsPage` era un fichero de 1.019 líneas que CAL.2 dejó en 696 al retirar el panel
 * de fuentes. Aquí se parte en piezas con una responsabilidad cada una, y la página queda
 * como orquestador: estado, hooks de Orval y composición.
 *
 * Estos tests prueban las piezas **por separado**, con props explícitas y sin servidor. El
 * que sigue garantizando que la pantalla completa se comporta igual es
 * `admin/pages/__tests__/DocumentsPage.test.tsx`, que no cambia de asserts en este prompt:
 * un refactor de composición que necesita reescribir sus propios tests de comportamiento no
 * ha demostrado que el comportamiento se conserve.
 */
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { readFileSync } from 'node:fs'
import { join, resolve } from 'node:path'

import { UploadDropzone } from '../UploadDropzone'
import { DocumentsTable } from '../DocumentsTable'
import { IngestionJobsPanel } from '../IngestionJobsPanel'
import { RechunkControls, RechunkStatus } from '../RechunkControls'
import type { HubDocumentOut, IngestionJob } from '@/shared/api/generated/model'

// Resuelve contra el diccionario castellano real (ver la nota del test de DocumentsPage).
vi.mock('react-i18next', async () => {
  const es = (await import('@/shared/i18n/locales/es/admin.json')).default as Record<string, unknown>
  const resolver = (clave: string) =>
    clave.split('.').reduce<unknown>((o, p) => (o as Record<string, unknown>)?.[p], es)
  return {
    useTranslation: () => ({
      t: (key: string, defaultText?: string) => (resolver(key) as string) ?? defaultText ?? key,
      i18n: { changeLanguage: vi.fn() },
    }),
  }
})

vi.mock('react-dropzone', () => ({
  useDropzone: () => ({
    getRootProps: () => ({}),
    getInputProps: () => ({ type: 'file', accept: 'application/pdf,.pdf' }),
    isDragActive: false,
  }),
}))

vi.mock('@/components/ui/progress', () => ({
  Progress: () => <div data-testid="progress" />,
}))

const DOC: HubDocumentOut = {
  id: 'doc-es',
  chatbot_id: 'bot-1',
  title: 'Normativa Española',
  canonical_url: 'https://example.com/normativa-es.pdf',
  language: 'es',
  source_kind: 'upload',
  token_count: 1200,
  created_at: '2024-01-01T00:00:00Z',
  updated_at: '2024-01-01T00:00:00Z',
}

const JOB: IngestionJob = {
  id: 'job-1',
  chatbot_id: 'bot-1',
  source_url: 'ingestion/bot-1/job-1.pdf',
  original_filename: 'normativa.pdf',
  canonical_url: null,
  language: 'es',
  status: 'completed',
  acciones_permitidas: ['borrar'],
  avisos: [],
  chunks_processed: 12,
  error_message: null,
  created_at: '2024-01-01T00:00:00Z',
}

describe('CAL.3 — subcomponentes de documentos', () => {
  it('should_render_upload_dropzone_component', () => {
    const onDrop = vi.fn()
    render(
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

    // EXT.1: al corpus solo entra Markdown del pipeline de curación, no PDF.
    expect(
      screen.getByText('Arrastra y suelta tus archivos Markdown (.md) aquí'),
    ).toBeInTheDocument()
    expect(screen.getByPlaceholderText('URL pública del documento (opcional)')).toBeInTheDocument()
    expect(screen.getByLabelText('Idioma')).toBeInTheDocument()
  })

  it('should_show_substitution_banner_and_upload_error_in_dropzone', () => {
    const onCancelSubstitute = vi.fn()
    render(
      <UploadDropzone
        canonicalUrl=""
        onCanonicalUrlChange={vi.fn()}
        uploadLanguage=""
        onUploadLanguageChange={vi.fn()}
        substituteDoc={DOC}
        onCancelSubstitute={onCancelSubstitute}
        onDrop={vi.fn()}
        uploadError="El archivo supera el límite de 10 MB."
      />,
    )

    expect(screen.getByText('Normativa Española')).toBeInTheDocument()
    expect(screen.getByText('El archivo supera el límite de 10 MB.')).toBeInTheDocument()

    fireEvent.click(screen.getByText('cancel'))
    expect(onCancelSubstitute).toHaveBeenCalled()
  })

  it('should_render_documents_table_component', () => {
    const onPreview = vi.fn()
    render(
      <DocumentsTable
        documents={[DOC]}
        isLoading={false}
        langFilter=""
        onLangFilterChange={vi.fn()}
        presentLanguages={['ca', 'es']}
        onPreview={onPreview}
        onSubstitute={vi.fn()}
        onDelete={vi.fn()}
      />,
    )

    expect(screen.getByText('Documentos del corpus')).toBeInTheDocument()
    expect(screen.getByText('Normativa Española')).toBeInTheDocument()
    // 1.200 tokens → «1.2 k»
    expect(screen.getByText('1.2 k')).toBeInTheDocument()

    fireEvent.click(screen.getByTitle('Ver contenido'))
    expect(onPreview).toHaveBeenCalledWith('doc-es')
  })

  it('should_not_render_the_whole_corpus_at_once', () => {
    // El corpus real son 297 documentos y la tabla los pintaba todos: ~4.500 nodos y unos
    // 1.500 SVG de golpe, que bloqueaban el navegador entre 30 y 60 segundos. Medido con
    // el corpus del piloto: con 124 iba fina y con 297 se quedaba clavada.
    const muchos = Array.from({ length: 297 }, (_, i) => ({
      ...DOC,
      id: `doc-${i}`,
      title: `Norma numero ${i}`,
    }))

    render(
      <DocumentsTable
        documents={muchos}
        isLoading={false}
        langFilter=""
        onLangFilterChange={vi.fn()}
        presentLanguages={['ca', 'es']}
        onPreview={vi.fn()}
        onSubstitute={vi.fn()}
        onDelete={vi.fn()}
      />,
    )

    const filas = screen.getAllByRole('row')
    // -1 por la fila de encabezados.
    expect(filas.length - 1).toBeLessThanOrEqual(50)
    expect(screen.getByText('Norma numero 0')).toBeInTheDocument()
    expect(screen.queryByText('Norma numero 296')).not.toBeInTheDocument()
  })

  it('should_reach_the_rest_of_the_corpus_by_paging', () => {
    const muchos = Array.from({ length: 297 }, (_, i) => ({
      ...DOC,
      id: `doc-${i}`,
      title: `Norma numero ${i}`,
    }))

    render(
      <DocumentsTable
        documents={muchos}
        isLoading={false}
        langFilter=""
        onLangFilterChange={vi.fn()}
        presentLanguages={[]}
        onPreview={vi.fn()}
        onSubstitute={vi.fn()}
        onDelete={vi.fn()}
      />,
    )

    fireEvent.click(screen.getByTestId('documentos-siguiente'))

    // Paginar sin poder volver sería peor que no paginar: se comprueban las dos direcciones.
    expect(screen.queryByText('Norma numero 0')).not.toBeInTheDocument()
    fireEvent.click(screen.getByTestId('documentos-anterior'))
    expect(screen.getByText('Norma numero 0')).toBeInTheDocument()
  })

  it('should_go_back_to_the_first_page_when_the_filter_changes', () => {
    // Si no, filtrar desde la página 4 deja la tabla vacía y parece que no hay resultados.
    const muchos = Array.from({ length: 297 }, (_, i) => ({
      ...DOC, id: `doc-${i}`, title: `Norma numero ${i}`,
    }))
    const { rerender } = render(
      <DocumentsTable
        documents={muchos} isLoading={false} langFilter="" onLangFilterChange={vi.fn()}
        presentLanguages={[]} onPreview={vi.fn()} onSubstitute={vi.fn()} onDelete={vi.fn()}
      />,
    )
    fireEvent.click(screen.getByTestId('documentos-siguiente'))

    rerender(
      <DocumentsTable
        documents={muchos.slice(0, 30)} isLoading={false} langFilter="es"
        onLangFilterChange={vi.fn()} presentLanguages={[]} onPreview={vi.fn()}
        onSubstitute={vi.fn()} onDelete={vi.fn()}
      />,
    )

    expect(screen.getByText('Norma numero 0')).toBeInTheDocument()
  })

  it('should_render_empty_state_in_documents_table', () => {
    render(
      <DocumentsTable
        documents={[]}
        isLoading={false}
        langFilter=""
        onLangFilterChange={vi.fn()}
        presentLanguages={[]}
        onPreview={vi.fn()}
        onSubstitute={vi.fn()}
        onDelete={vi.fn()}
      />,
    )
    expect(screen.getByText('No hay documentos ingestados para este chatbot.')).toBeInTheDocument()
  })

  it('should_render_jobs_panel_component', () => {
    const onToggle = vi.fn()
    const onDeleteJob = vi.fn()
    render(
      <IngestionJobsPanel
        open
        onToggle={onToggle}
        jobs={[JOB]}
        isLoading={false}
        onDeleteJob={onDeleteJob}
      />,
    )

    expect(screen.getByText('Jobs (técnico)')).toBeInTheDocument()
    expect(screen.getByText('normativa.pdf')).toBeInTheDocument()

    fireEvent.click(screen.getByTitle('Eliminar job'))
    expect(onDeleteJob).toHaveBeenCalledWith('job-1')
  })

  it('should_not_query_jobs_when_panel_is_closed', () => {
    render(
      <IngestionJobsPanel
        open={false}
        onToggle={vi.fn()}
        jobs={[JOB]}
        isLoading={false}
        onDeleteJob={vi.fn()}
      />,
    )
    // La cabecera se ve siempre; la tabla sólo al desplegar.
    expect(screen.getByText('Jobs (técnico)')).toBeInTheDocument()
    expect(screen.queryByText('normativa.pdf')).not.toBeInTheDocument()
  })

  it('should_render_rechunk_controls_component', () => {
    const onRecalculate = vi.fn()
    const onClear = vi.fn()
    render(
      <RechunkControls
        onRecalculate={onRecalculate}
        onClear={onClear}
        isRecalculating={false}
        isClearing={false}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: /recalcular corpus/i }))
    expect(onRecalculate).toHaveBeenCalled()

    fireEvent.click(screen.getByRole('button', { name: /limpiar colección/i }))
    expect(onClear).toHaveBeenCalled()
  })

  it('should_render_rechunk_status_with_result_and_error', () => {
    const { rerender } = render(
      <RechunkStatus
        isRecalculating
        result={null}
        error=""
      />,
    )
    expect(screen.getByText('Recalculando corpus...')).toBeInTheDocument()

    rerender(
      <RechunkStatus
        isRecalculating={false}
        result={{
          task_id: 't-1',
          message: 'Recálculo completado.',
          documents_queued: 2,
          chunks_created: 10,
          chunks_deleted: 3,
        }}
        error=""
      />,
    )
    expect(screen.getByText(/Recálculo completado\./)).toBeInTheDocument()

    rerender(<RechunkStatus isRecalculating={false} result={null} error="Se rompió" />)
    expect(screen.getByText('Se rompió')).toBeInTheDocument()
  })

  /**
   * Sustituye a `should_render_sources_panel_component` del plan: CAL.2 retiró el panel de
   * fuentes web porque mandaba sobre `/hub/ingestion/{id}/sources`, un endpoint eliminado en
   * `0196ff5`. Extraerlo ahora sería resucitar un mando a distancia sin aparato, así que lo
   * que se prueba es lo contrario: que no vuelve.
   */
  it('should_not_reintroduce_sources_panel', () => {
    const dir = resolve(__dirname, '..')
    let existe = true
    try {
      readFileSync(join(dir, 'SourcesPanel.tsx'), 'utf-8')
    } catch {
      existe = false
    }
    expect(
      existe,
      'SourcesPanel resucitaría el endpoint /hub/ingestion/{id}/sources, retirado en 0196ff5. ' +
        'Su sustituto vivo es curation/SitesPage + curation/PublicationPage (CUR.2).',
    ).toBe(false)
  })

  it('should_keep_documents_page_as_orchestrator', () => {
    const page = readFileSync(
      resolve(__dirname, '../../pages/DocumentsPage.tsx'),
      'utf-8',
    )
    const lineas = page.split('\n').length
    expect(
      lineas,
      `DocumentsPage tiene ${lineas} líneas; CAL.3 la deja como orquestador por debajo de 300.`,
    ).toBeLessThan(300)
  })
})
