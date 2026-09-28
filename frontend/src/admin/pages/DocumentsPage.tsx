import { useState, useCallback, useRef } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'

import {
  useRecalculateCorpusEndpointApiV1HubChatbotsChatbotIdRecalculateCorpusPost,
} from '@/shared/api/generated/hub-chatbots/hub-chatbots'
import {
  useListDocumentsApiV1HubIngestionChatbotIdDocumentsGet,
  useGetDocumentApiV1HubIngestionChatbotIdDocumentsDocumentIdGet,
  useGetIngestionJobsApiV1HubIngestionChatbotIdJobsGet,
  useDeleteIngestionJobApiV1HubIngestionChatbotIdJobsJobIdDelete,
  useUploadDocumentApiV1HubIngestionUploadPost,
  useClearChatbotCollectionApiV1HubIngestionChatbotIdChunksDelete,
  getListDocumentsApiV1HubIngestionChatbotIdDocumentsGetQueryKey,
  getGetIngestionJobsApiV1HubIngestionChatbotIdJobsGetQueryKey,
} from '@/shared/api/generated/hub-ingestion/hub-ingestion'
import type {
  ChatbotRead,
  RecalculateCorpusOut,
  HubDocumentOut,
} from '@/shared/api/generated/model'

import { DeleteDocumentDialog } from '@/admin/documents/DeleteDocumentDialog'
import { DocumentPreviewModal } from '@/admin/documents/DocumentPreviewModal'
import { DocumentsTable } from '@/admin/documents/DocumentsTable'
import { IngestionJobsPanel } from '@/admin/documents/IngestionJobsPanel'
import { RechunkConfirmDialog, RechunkControls, RechunkStatus } from '@/admin/documents/RechunkControls'
import { RetrievalBanner } from '@/admin/documents/RetrievalBanner'
import { UploadDropzone } from '@/admin/documents/UploadDropzone'
import { useBorradoDeDocumento } from '@/admin/documents/useBorradoDeDocumento'
import { useChatbotsDeLaOrganizacion } from '@/shared/organizacion/useChatbotsDeLaOrganizacion'
import { useSeleccionValida } from '@/shared/organizacion/useSeleccionValida'

const MAX_UPLOAD_BYTES = 10 * 1024 * 1024

/**
 * Orquestador de la pantalla de documentos: estado, hooks del contrato y composición.
 *
 * Todo lo que pinta vive en `admin/documents/`. Lo que se queda aquí es lo que sólo puede
 * decidirse con el corpus entero a la vista —los idiomas del filtro, el total de tokens, el
 * texto de la advertencia al recalcular— y la invalidación de las consultas.
 */
export function DocumentsPage() {
  const { t } = useTranslation('admin')
  const { t: tc } = useTranslation('common')
  const qc = useQueryClient()

  const [selectedChatbotId, setSelectedChatbotId] = useState<string>('')
  const [jobsOpen, setJobsOpen] = useState(false)
  const [langFilter, setLangFilter] = useState<string>('')
  const [previewDoc, setPreviewDoc] = useState<string | null>(null)
  const [substituteDoc, setSubstituteDoc] = useState<HubDocumentOut | null>(null)
  const [uploadError, setUploadError] = useState<string>('')
  const [recalculateConfirmOpen, setRecalculateConfirmOpen] = useState(false)
  const [recalculateError, setRecalculateError] = useState('')
  const [recalculateResult, setRecalculateResult] = useState<RecalculateCorpusOut | null>(null)
  const [canonicalUrl, setCanonicalUrl] = useState<string>('')
  const [uploadLanguage, setUploadLanguage] = useState<string>('')
  // Los metadatos se congelan al soltar el fichero: la subida es asíncrona y si el usuario
  // sigue tecleando en la URL mientras sube, el job no debe llevarse lo que escriba después.
  const canonicalUrlRef = useRef<string>('')
  const uploadLanguageRef = useRef<string>('')

  const { data: chatbotsRaw, isLoading: isLoadingChatbots } = useChatbotsDeLaOrganizacion()
  const chatbots: ChatbotRead[] = (chatbotsRaw as unknown as ChatbotRead[] | undefined) ?? []

  // Issue #11 — al cambiar de organización, un chatbot de la anterior no puede quedarse
  // elegido: la consulta dependiente y las mutaciones irían contra otra organización.
  useSeleccionValida(chatbots, selectedChatbotId, setSelectedChatbotId)

  if (!selectedChatbotId && chatbots.length > 0) {
    setSelectedChatbotId(chatbots[0].id)
  }

  const selectedChatbot = chatbots.find(c => c.id === selectedChatbotId)

  const documentsQueryKey = getListDocumentsApiV1HubIngestionChatbotIdDocumentsGetQueryKey(selectedChatbotId)
  const jobsQueryKey = getGetIngestionJobsApiV1HubIngestionChatbotIdJobsGetQueryKey(selectedChatbotId)

  const invalidateCorpus = () => {
    qc.invalidateQueries({ queryKey: documentsQueryKey })
    qc.invalidateQueries({ queryKey: jobsQueryKey })
  }

  // Se piden todos y se filtra en cliente: el desplegable de idiomas se construye con los que
  // hay en el corpus, y el total de tokens del banner es el del corpus entero. Filtrar en el
  // servidor dejaría ambas cosas midiendo el subconjunto.
  const { data: documentsData, isLoading: isLoadingDocs } =
    useListDocumentsApiV1HubIngestionChatbotIdDocumentsGet(
      selectedChatbotId,
      undefined,
      { query: { enabled: !!selectedChatbotId } },
    )
  const documents: HubDocumentOut[] = documentsData?.documents ?? []

  const { data: previewDetail, isLoading: isLoadingPreview } =
    useGetDocumentApiV1HubIngestionChatbotIdDocumentsDocumentIdGet(
      selectedChatbotId,
      previewDoc ?? '',
      { query: { enabled: !!previewDoc } },
    )

  const borrado = useBorradoDeDocumento(selectedChatbotId, documentsQueryKey)

  const presentLanguages = Array.from(new Set(documents.map(d => d.language))).sort()
  const filteredDocs = langFilter ? documents.filter(d => d.language === langFilter) : documents
  const totalTokens = documents.reduce((sum, d) => sum + d.token_count, 0)

  const { data: jobsData, isLoading: isLoadingJobs } =
    useGetIngestionJobsApiV1HubIngestionChatbotIdJobsGet(
      selectedChatbotId,
      {
        query: {
          enabled: !!selectedChatbotId && jobsOpen,
          refetchInterval: (query) => {
            const hasActive = query.state.data?.jobs?.some(
              j => j.status === 'pending' || j.status === 'running',
            )
            return hasActive ? 3000 : false
          },
        },
      },
    )

  const deleteJobMutation = useDeleteIngestionJobApiV1HubIngestionChatbotIdJobsJobIdDelete({
    mutation: { onSuccess: () => qc.invalidateQueries({ queryKey: jobsQueryKey }) },
  })

  const uploadMutation = useUploadDocumentApiV1HubIngestionUploadPost({
    mutation: {
      onSuccess: () => {
        invalidateCorpus()
        setUploadError('')
        setSubstituteDoc(null)
      },
      onError: (err: Error) => setUploadError(err.message),
    },
  })

  const clearMutation = useClearChatbotCollectionApiV1HubIngestionChatbotIdChunksDelete({
    mutation: { onSuccess: invalidateCorpus },
  })

  const recalculateMutation =
    useRecalculateCorpusEndpointApiV1HubChatbotsChatbotIdRecalculateCorpusPost({
      mutation: {
        onSuccess: (data) => {
          setRecalculateError('')
          setRecalculateResult(data)
          setRecalculateConfirmOpen(false)
          invalidateCorpus()
        },
        onError: (err: Error) => setRecalculateError(err.message),
      },
    })

  const onDrop = useCallback((acceptedFiles: File[]) => {
    setUploadError('')
    canonicalUrlRef.current = canonicalUrl
    uploadLanguageRef.current = uploadLanguage
    for (const file of acceptedFiles) {
      if (file.size > MAX_UPLOAD_BYTES) { setUploadError('El archivo supera el límite de 10 MB.'); continue }
      uploadMutation.mutate({
        data: {
          chatbot_id: selectedChatbotId,
          file,
          canonical_url: canonicalUrlRef.current || undefined,
          language: uploadLanguageRef.current || undefined,
        },
      })
    }
  }, [uploadMutation, canonicalUrl, uploadLanguage, selectedChatbotId])

  const handleSubstitute = (doc: HubDocumentOut) => {
    setSubstituteDoc(doc)
    setCanonicalUrl(doc.canonical_url)
    setUploadLanguage(doc.language)
    canonicalUrlRef.current = doc.canonical_url
    uploadLanguageRef.current = doc.language
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold">{t('hub.documents_title')}</h1>
          <p className="text-sm text-muted-foreground">{t('hub.documents_desc')}</p>
        </div>
        {chatbots.length > 0 && (
          <select
            value={selectedChatbotId}
            onChange={e => setSelectedChatbotId(e.target.value)}
            className="px-3 py-2 border rounded-md text-sm bg-background w-full sm:w-64"
          >
            {chatbots.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        )}
      </div>

      {!selectedChatbotId ? (
        <div className="p-8 text-center border border-dashed rounded-lg text-muted-foreground">
          {isLoadingChatbots ? tc('loading') : t('hub.select_chatbot_first')}
        </div>
      ) : (
        <div className="space-y-4">
          {selectedChatbot && (
            <RetrievalBanner mode={selectedChatbot.retrieval_mode} totalTokens={totalTokens} />
          )}

          <UploadDropzone
            canonicalUrl={canonicalUrl}
            onCanonicalUrlChange={setCanonicalUrl}
            uploadLanguage={uploadLanguage}
            onUploadLanguageChange={setUploadLanguage}
            substituteDoc={substituteDoc}
            onCancelSubstitute={() => { setSubstituteDoc(null); setCanonicalUrl(''); setUploadLanguage('') }}
            onDrop={onDrop}
            uploadError={uploadError}
          />

          <RechunkStatus
            isRecalculating={recalculateMutation.isPending}
            result={recalculateResult}
            error={recalculateError}
          />

          <DocumentsTable
            documents={filteredDocs}
            isLoading={isLoadingDocs}
            langFilter={langFilter}
            onLangFilterChange={setLangFilter}
            presentLanguages={presentLanguages}
            onPreview={setPreviewDoc}
            onSubstitute={handleSubstitute}
            onDelete={borrado.elegir}
            headerActions={documents.length > 0 && (
              <RechunkControls
                onRecalculate={() => { setRecalculateError(''); setRecalculateConfirmOpen(true) }}
                onClear={() => clearMutation.mutate({ chatbotId: selectedChatbotId })}
                isRecalculating={recalculateMutation.isPending}
                isClearing={clearMutation.isPending}
              />
            )}
          />

          <IngestionJobsPanel
            open={jobsOpen}
            onToggle={() => setJobsOpen(v => !v)}
            jobs={jobsData?.jobs ?? []}
            isLoading={isLoadingJobs}
            onDeleteJob={jobId => deleteJobMutation.mutate({ chatbotId: selectedChatbotId, jobId })}
          />
        </div>
      )}

      {previewDoc && (
        <DocumentPreviewModal
          detail={previewDetail}
          isLoading={isLoadingPreview}
          onClose={() => setPreviewDoc(null)}
        />
      )}

      {/* `hub.delete_doc_confirm` y no `hub.delete_confirm`: esa otra es la *pregunta*
          «¿Eliminar este chatbot?» de la pantalla de chatbots, y reutilizarla ponía ese
          texto —hablando de un chatbot— en el botón de borrar un documento. */}
      {borrado.objetivo && (
        <DeleteDocumentDialog
          documento={borrado.objetivo}
          copiasEnOtrosChatbots={borrado.copiasEnOtrosChatbots}
          borrarEnTodos={borrado.borrarEnTodos}
          onBorrarEnTodosChange={borrado.setBorrarEnTodos}
          isPending={borrado.isPending}
          onConfirm={borrado.confirmar}
          onCancel={borrado.cancelar}
        />
      )}

      {recalculateConfirmOpen && (
        <RechunkConfirmDialog
          retrievalMode={selectedChatbot?.retrieval_mode}
          documentCount={documents.length}
          totalTokens={totalTokens}
          isPending={recalculateMutation.isPending}
          onConfirm={() => recalculateMutation.mutate({ chatbotId: selectedChatbotId })}
          onCancel={() => setRecalculateConfirmOpen(false)}
        />
      )}
    </div>
  )
}
