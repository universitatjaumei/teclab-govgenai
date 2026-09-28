import { useMemo, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import {
  useUpdateChatbotApiV1HubChatbotsChatbotIdPatch,
  getListChatbotsApiV1HubChatbotsGetQueryKey,
} from '@/shared/api/generated/hub-chatbots/hub-chatbots'
import {
  useListPromptTemplatesApiV1HubPromptTemplatesGet,
  useCreatePromptTemplateApiV1HubPromptTemplatesPost,
  useUpdatePromptTemplateApiV1HubPromptTemplatesTemplateIdPatch,
  useDeletePromptTemplateApiV1HubPromptTemplatesTemplateIdDelete,
  getListPromptTemplatesApiV1HubPromptTemplatesGetQueryKey,
} from '@/shared/api/generated/hub-prompt-templates/hub-prompt-templates'
import type { ChatbotRead, PromptTemplateRead, PromptTemplateCreate, ChatbotUpdate } from '@/shared/api/generated/model'
import { useChatbotsDeLaOrganizacion } from '@/shared/organizacion/useChatbotsDeLaOrganizacion'

// Render template text with {variable} spans highlighted (for the editor preview)
function HighlightedText({ text }: { text: string }) {
  const parts = text.split(/(\{\w+\})/g)
  return (
    <span>
      {parts.map((part, i) =>
        /^\{\w+\}$/.test(part) ? (
          <span
            key={i}
            data-testid="var-highlight"
            className="bg-yellow-100 rounded px-0.5 font-mono text-yellow-800"
          >
            {part}
          </span>
        ) : (
          <span key={i}>{part}</span>
        ),
      )}
    </span>
  )
}

// Fill {variables} with example values for preview
function buildPreview(text: string): string {
  return text.replace(/\{(\w+)\}/g, (_match, name: string) => `[${name}]`)
}

const TIER_COLORS: Record<number, string> = {
  1: 'bg-green-100 text-green-800',
  2: 'bg-yellow-100 text-yellow-800',
  3: 'bg-red-100 text-red-800',
}

function TierChip({ tier, label }: { tier: number; label?: string }) {
  return (
    <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${TIER_COLORS[tier] ?? 'bg-gray-100 text-gray-700'}`}>
      {label ?? `Tier ${tier}`}
    </span>
  )
}

type PromptUsageFilter = 'all' | 'chatbot_system' | 'template'

export function PromptsPage() {
  const { t } = useTranslation('admin')
  const qc = useQueryClient()

  const [usageFilter, setUsageFilter] = useState<PromptUsageFilter>('all')
  const [chatbotFilter, setChatbotFilter] = useState<string>('all')
  const [search, setSearch] = useState('')

  const [selectedType, setSelectedType] = useState<'chatbot' | 'template' | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)

  const [editText, setEditText] = useState('')
  const [editDefaultTier, setEditDefaultTier] = useState<number | null>(null)
  const [editOverrideTier, setEditOverrideTier] = useState<number | null>(null)

  const [editChatbotPrompt, setEditChatbotPrompt] = useState('')

  const [showCreate, setShowCreate] = useState(false)
  const [newForm, setNewForm] = useState<Partial<Omit<PromptTemplateCreate, 'chatbot_id'>>>({
    language: 'es',
  })

  const selectedChatbotId = chatbotFilter !== 'all' ? chatbotFilter : undefined

  const { data: templates = [] } = useListPromptTemplatesApiV1HubPromptTemplatesGet(
    selectedChatbotId ? { chatbot_id: selectedChatbotId } : undefined,
  )

  // Sin `params`, la clave generada es el prefijo común de todas las variantes por
  // chatbot, así que invalidarla alcanza también a las filtradas.
  const invalidateTemplates = () =>
    qc.invalidateQueries({ queryKey: getListPromptTemplatesApiV1HubPromptTemplatesGetQueryKey() })

  const { data: chatbotsRaw } = useChatbotsDeLaOrganizacion()
  // Memoizado: el `?? []` construía un array nuevo en cada render mientras no hubiera datos, y
  // cualquier hook que lo metiera en sus dependencias se recalculaba siempre. Mismo caso que en
  // `ActivityPromptsPage`.
  const chatbots: ChatbotRead[] = useMemo(
    () => (chatbotsRaw as unknown as ChatbotRead[] | undefined) ?? [],
    [chatbotsRaw],
  )

  const selectedTemplate = selectedType === 'template'
    ? templates.find((tmpl) => tmpl.id === selectedId) ?? null
    : null

  const selectedChatbot = selectedType === 'chatbot'
    ? chatbots.find((cb) => cb.id === selectedId) ?? null
    : null

  const effectiveTier = (tmpl: PromptTemplateRead) => tmpl.override_tier ?? tmpl.default_tier

  function handleSelectTemplate(tmpl: PromptTemplateRead) {
    setSelectedType('template')
    setSelectedId(tmpl.id)
    setEditText(tmpl.template_text)
    setEditDefaultTier(tmpl.default_tier)
    setEditOverrideTier(tmpl.override_tier)
  }

  function handleSelectChatbot(cb: ChatbotRead) {
    setSelectedType('chatbot')
    setSelectedId(cb.id)
    setEditChatbotPrompt(cb.system_prompt)
  }

  const saveTemplateMutation = useUpdatePromptTemplateApiV1HubPromptTemplatesTemplateIdPatch({
    mutation: { onSuccess: invalidateTemplates },
  })

  const saveChatbotPromptMutation = useUpdateChatbotApiV1HubChatbotsChatbotIdPatch({
    mutation: {
      onSuccess: () => {
        qc.invalidateQueries({ queryKey: getListChatbotsApiV1HubChatbotsGetQueryKey() })
      },
    },
  })

  const deleteMutation = useDeletePromptTemplateApiV1HubPromptTemplatesTemplateIdDelete({
    mutation: {
      onSuccess: () => {
        setSelectedType(null)
        setSelectedId(null)
        invalidateTemplates()
      },
    },
  })

  const createMutation = useCreatePromptTemplateApiV1HubPromptTemplatesPost({
    mutation: {
      onSuccess: () => {
        setShowCreate(false)
        setNewForm({ language: 'es' })
        invalidateTemplates()
      },
    },
  })

  const filteredChatbots = useMemo(() => {
    if (usageFilter === 'template') return []
    const q = search.trim().toLowerCase()
    return chatbots.filter((cb) => {
      if (chatbotFilter !== 'all' && cb.id !== chatbotFilter) return false
      if (!q) return true
      return cb.name.toLowerCase().includes(q) || cb.system_prompt.toLowerCase().includes(q)
    })
  }, [chatbots, chatbotFilter, usageFilter, search])

  const filteredTemplates = useMemo(() => {
    if (usageFilter === 'chatbot_system') return []
    const q = search.trim().toLowerCase()
    return templates.filter((tmpl) => {
      if (chatbotFilter !== 'all' && tmpl.chatbot_id !== chatbotFilter) return false
      if (!q) return true
      return (
        tmpl.slug.toLowerCase().includes(q) ||
        tmpl.template_text.toLowerCase().includes(q) ||
        tmpl.language.toLowerCase().includes(q)
      )
    })
  }, [chatbotFilter, templates, usageFilter, search])

  const canCreateTemplate = chatbotFilter !== 'all'

  function handleSaveTemplate() {
    if (!selectedTemplate) return
    saveTemplateMutation.mutate({
      templateId: selectedTemplate.id,
      data: {
        template_text: editText,
        default_tier: editDefaultTier,
        override_tier: editOverrideTier,
      },
    })
  }

  function handleSaveChatbotPrompt() {
    if (!selectedChatbot) return
    saveChatbotPromptMutation.mutate({
      chatbotId: selectedChatbot.id,
      data: { system_prompt: editChatbotPrompt } as ChatbotUpdate,
    })
  }

  return (
    <div className="flex gap-4 h-[calc(100vh-160px)]">
      <aside className="w-80 shrink-0 border rounded-lg overflow-y-auto flex flex-col">
        <div className="p-3 border-b flex flex-col gap-2">
          <span className="font-medium text-sm">{t('hub.prompt_templates')}</span>

          <select
            aria-label={t('hub.filter_usage_aria')}
            value={usageFilter}
            onChange={(e) => setUsageFilter(e.target.value as PromptUsageFilter)}
            className="border rounded px-2 py-1.5 text-xs bg-background"
          >
            <option value="all">Uso: todos</option>
            <option value="chatbot_system">Uso: chatbot (prompt base)</option>
            <option value="template">Uso: plantillas</option>
          </select>

          <select
            aria-label={t('hub.filter_chatbot_aria')}
            value={chatbotFilter}
            onChange={(e) => setChatbotFilter(e.target.value)}
            className="border rounded px-2 py-1.5 text-xs bg-background"
          >
            <option value="all">Servicio: todos</option>
            {chatbots.map((cb) => (
              <option key={cb.id} value={cb.id}>
                {cb.name}
              </option>
            ))}
          </select>

          <input
            aria-label={t('hub.search_prompts_aria')}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Buscar prompt..."
            className="border rounded px-2 py-1.5 text-xs bg-background"
          />

          <button
            onClick={() => setShowCreate(true)}
            disabled={!canCreateTemplate}
            className="text-xs px-2 py-1 rounded bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
          >
            + {t('hub.new_prompt_template')}
          </button>
          {!canCreateTemplate && (
            <p className="text-[11px] text-muted-foreground">
              Selecciona un servicio/chatbot para crear una plantilla asociada.
            </p>
          )}
        </div>

        <div className="px-3 pt-2 text-[11px] uppercase tracking-wide text-muted-foreground">
          Prompts base de chatbot
        </div>
        {filteredChatbots.map((cb) => (
          <button
            key={`cb-${cb.id}`}
            onClick={() => handleSelectChatbot(cb)}
            className={`w-full text-left px-3 py-2 border-b text-sm hover:bg-accent/50 transition-colors ${
              selectedType === 'chatbot' && selectedId === cb.id ? 'bg-accent' : ''
            }`}
          >
            <div className="flex items-center justify-between gap-1">
              <span className="font-medium truncate">{cb.name}</span>
              <span className="shrink-0 text-xs bg-purple-100 text-purple-700 rounded px-1.5">
                base
              </span>
            </div>
            <p className="text-xs text-muted-foreground truncate mt-0.5">{cb.system_prompt}</p>
          </button>
        ))}

        <div className="px-3 pt-2 text-[11px] uppercase tracking-wide text-muted-foreground">
          Plantillas por actividad/fase
        </div>
        {filteredTemplates.length === 0 && usageFilter !== 'chatbot_system' && (
          <p className="p-4 text-sm text-muted-foreground">{t('hub.no_prompt_templates')}</p>
        )}
        {filteredTemplates.map((tmpl) => {
          const tier = effectiveTier(tmpl)
          return (
            <button
              key={tmpl.id}
              onClick={() => handleSelectTemplate(tmpl)}
              className={`w-full text-left px-3 py-2 border-b text-sm hover:bg-accent/50 transition-colors ${
                selectedType === 'template' && selectedId === tmpl.id ? 'bg-accent' : ''
              }`}
            >
              <div className="flex items-center justify-between gap-1">
                <span className="font-medium truncate">{tmpl.slug}</span>
                <span className="shrink-0 text-xs bg-muted text-muted-foreground rounded px-1.5">
                  v{tmpl.version}
                </span>
              </div>
              <div className="flex items-center gap-1 mt-0.5 flex-wrap">
                <span className="text-xs text-muted-foreground">
                  {chatbots.find((c) => c.id === tmpl.chatbot_id)?.name ?? tmpl.chatbot_id.slice(0, 8)}
                </span>
                <span className="text-xs bg-blue-100 text-blue-700 rounded px-1">{tmpl.language}</span>
                {tier !== null && <TierChip tier={tier} />}
              </div>
            </button>
          )
        })}
      </aside>

      {selectedChatbot ? (
        <div className="flex-1 border rounded-lg overflow-y-auto flex flex-col gap-4 p-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <h2 className="font-semibold text-base">{selectedChatbot.name}</h2>
              <span className="text-xs bg-purple-100 text-purple-700 rounded px-1.5">
                Prompt base del chatbot
              </span>
            </div>
          </div>

          <div>
            <p className="text-xs text-muted-foreground mb-1">{t('hub.prompt_text')}</p>
            <textarea
              value={editChatbotPrompt}
              onChange={(e) => setEditChatbotPrompt(e.target.value)}
              rows={12}
              className="w-full rounded border px-3 py-2 text-sm font-mono resize-y focus:outline-none focus:ring-2 focus:ring-ring"
            />
          </div>

          <div>
            <p className="text-xs text-muted-foreground mb-1">{t('hub.prompt_variables')}</p>
            <div className="rounded border px-3 py-2 text-sm font-mono bg-muted/30 whitespace-pre-wrap break-words">
              <HighlightedText text={editChatbotPrompt} />
            </div>
          </div>

          <div>
            <p className="text-xs text-muted-foreground mb-1">{t('hub.prompt_preview')}</p>
            <div
              data-testid="prompt-preview"
              className="rounded border px-3 py-2 text-sm bg-muted/20 whitespace-pre-wrap break-words"
            >
              {buildPreview(editChatbotPrompt)}
            </div>
          </div>

          <div className="flex justify-end">
            <button
              onClick={handleSaveChatbotPrompt}
              disabled={saveChatbotPromptMutation.isPending}
              className="px-4 py-2 rounded bg-primary text-primary-foreground text-sm hover:bg-primary/90 disabled:opacity-50"
            >
              Guardar prompt base
            </button>
          </div>
        </div>
      ) : selectedTemplate ? (
        <div className="flex-1 border rounded-lg overflow-y-auto flex flex-col gap-4 p-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <h2 className="font-semibold text-base">{selectedTemplate.slug}</h2>
              <span className="text-xs bg-muted text-muted-foreground rounded px-1.5">
                v{selectedTemplate.version}
              </span>
              {selectedTemplate.override_tier !== null && (
                <span data-testid="effective-tier">
                  <TierChip
                    tier={selectedTemplate.override_tier}
                    label={`Tier ${selectedTemplate.override_tier} (override)`}
                  />
                </span>
              )}
              {selectedTemplate.override_tier === null && selectedTemplate.default_tier !== null && (
                <span data-testid="effective-tier">
                  <TierChip tier={selectedTemplate.default_tier} />
                </span>
              )}
            </div>
            <button
              onClick={() => deleteMutation.mutate({ templateId: selectedTemplate.id })}
              className="text-xs text-destructive hover:underline"
            >
              {t('hub.delete_prompt_template')}
            </button>
          </div>

          <div className="flex flex-wrap gap-4 text-sm">
            <div>
              <p className="text-xs text-muted-foreground mb-1">{t('hub.prompt_default_tier')}</p>
              <div className="flex gap-1">
                {[1, 2, 3].map((n) => (
                  <button
                    key={n}
                    onClick={() => setEditDefaultTier(n)}
                    className={`px-2 py-0.5 rounded text-xs font-medium border ${editDefaultTier === n ? 'bg-primary text-primary-foreground border-primary' : 'border-border hover:bg-accent/50'}`}
                  >
                    {n}
                  </button>
                ))}
              </div>
            </div>
            <div>
              <p className="text-xs text-muted-foreground mb-1">{t('hub.prompt_override_tier')}</p>
              <div className="flex gap-1 items-center">
                {[null, 1, 2, 3].map((n) => (
                  <button
                    key={n ?? 'none'}
                    onClick={() => setEditOverrideTier(n)}
                    className={`px-2 py-0.5 rounded text-xs font-medium border ${editOverrideTier === n ? 'bg-primary text-primary-foreground border-primary' : 'border-border hover:bg-accent/50'}`}
                  >
                    {n === null ? '—' : n}
                  </button>
                ))}
              </div>
            </div>
          </div>

          <div>
            <p className="text-xs text-muted-foreground mb-1">{t('hub.prompt_text')}</p>
            <textarea
              value={editText}
              onChange={(e) => setEditText(e.target.value)}
              rows={10}
              className="w-full rounded border px-3 py-2 text-sm font-mono resize-y focus:outline-none focus:ring-2 focus:ring-ring"
            />
          </div>

          <div>
            <p className="text-xs text-muted-foreground mb-1">{t('hub.prompt_variables')}</p>
            <div className="rounded border px-3 py-2 text-sm font-mono bg-muted/30 whitespace-pre-wrap break-words">
              <HighlightedText text={editText} />
            </div>
          </div>

          <div>
            <p className="text-xs text-muted-foreground mb-1">{t('hub.prompt_preview')}</p>
            <div
              data-testid="prompt-preview"
              className="rounded border px-3 py-2 text-sm bg-muted/20 whitespace-pre-wrap break-words"
            >
              {buildPreview(editText)}
            </div>
          </div>

          <div className="flex justify-end">
            <button
              onClick={handleSaveTemplate}
              disabled={saveTemplateMutation.isPending}
              className="px-4 py-2 rounded bg-primary text-primary-foreground text-sm hover:bg-primary/90 disabled:opacity-50"
            >
              {t('hub.save_prompt_version')}
            </button>
          </div>
        </div>
      ) : (
        <div className="flex-1 flex items-center justify-center text-muted-foreground text-sm">
          Selecciona un prompt base o una plantilla para editar.
        </div>
      )}

      {showCreate && (
        <div
          className="fixed inset-0 bg-black/50 flex items-center justify-center z-50"
          role="dialog"
          aria-modal="true"
          aria-labelledby="create-template-dialog-title"
        >
          <div className="bg-background rounded-lg p-6 w-full max-w-md flex flex-col gap-4">
            <h3 id="create-template-dialog-title" className="font-semibold text-base">{t('hub.new_prompt_template')}</h3>
            <div className="flex flex-col gap-3 text-sm">
              <label className="flex flex-col gap-1">
                <span className="text-xs text-muted-foreground">Servicio/chatbot</span>
                <input
                  disabled
                  className="border rounded px-2 py-1.5 bg-muted text-muted-foreground"
                  value={chatbots.find((c) => c.id === chatbotFilter)?.name ?? ''}
                />
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-xs text-muted-foreground">{t('hub.prompt_slug')}</span>
                <input
                  className="border rounded px-2 py-1.5"
                  value={newForm.slug ?? ''}
                  onChange={(e) => setNewForm((f) => ({ ...f, slug: e.target.value }))}
                />
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-xs text-muted-foreground">{t('hub.language_label')}</span>
                <select
                  className="border rounded px-2 py-1.5"
                  value={newForm.language ?? 'es'}
                  onChange={(e) => setNewForm((f) => ({ ...f, language: e.target.value }))}
                >
                  <option value="es">es</option>
                  <option value="ca">ca</option>
                  <option value="en">en</option>
                </select>
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-xs text-muted-foreground">{t('hub.prompt_text')}</span>
                <textarea
                  rows={4}
                  className="border rounded px-2 py-1.5 font-mono text-xs resize-y"
                  value={newForm.template_text ?? ''}
                  onChange={(e) => setNewForm((f) => ({ ...f, template_text: e.target.value }))}
                />
              </label>
            </div>
            <div className="flex justify-end gap-2">
              <button
                onClick={() => { setShowCreate(false); setNewForm({ language: 'es' }) }}
                className="px-3 py-1.5 rounded border text-sm"
              >
                {t('hub.cancel')}
              </button>
              <button
                onClick={() => {
                  if (chatbotFilter !== 'all' && newForm.slug && newForm.language && newForm.template_text) {
                    createMutation.mutate({
                      data: {
                        chatbot_id: chatbotFilter,
                        slug: newForm.slug,
                        language: newForm.language,
                        template_text: newForm.template_text,
                      },
                    })
                  }
                }}
                disabled={createMutation.isPending || chatbotFilter === 'all'}
                className="px-3 py-1.5 rounded bg-primary text-primary-foreground text-sm hover:bg-primary/90 disabled:opacity-50"
              >
                {t('hub.create')}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
