import { useState } from 'react'
import { Navigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import {
  useListPendingScripts,
  useAdminRetestScript,
  useApproveScriptProposal,
  useRejectScriptProposal,
} from '@/shared/api/generated/redaccion-scripts/redaccion-scripts'
import { useListTemplates } from '@/shared/api/generated/hub-redaccion/hub-redaccion'
import type {
  PendingProposalOut,
  AdminRetestResponse,
  TemplateOut,
} from '@/shared/api/generated/model'
import { useAuth } from '@/shared/auth'
import { ModelAuditVerdict } from '../components/ModelAuditVerdict'
import { InformeAnonimizacion } from '../components/InformeAnonimizacion'

interface ProposalCardProps {
  proposal: PendingProposalOut
}

function ProposalCard({ proposal }: ProposalCardProps) {
  const { t } = useTranslation('scripts')
  const retestHook = useAdminRetestScript()
  const approveHook = useApproveScriptProposal()
  const rejectHook = useRejectScriptProposal()
  const [targetTemplateId, setTargetTemplateId] = useState('')

  const { data: plantillasRaw } = useListTemplates()
  const plantillasGlobales = (
    (plantillasRaw as unknown as TemplateOut[] | undefined) ?? []
  ).filter(tmpl => tmpl.is_global)

  const retestResult = retestHook.data as unknown as AdminRetestResponse | undefined
  const canApprove = !!retestResult && targetTemplateId.trim().length > 0

  function handleRetest() {
    retestHook.mutate({ proposalId: proposal.proposal_id })
  }

  function handleApprove() {
    if (!canApprove) return
    approveHook.mutate({
      proposalId: proposal.proposal_id,
      data: { target_global_template_id: targetTemplateId.trim() },
    })
  }

  function handleReject() {
    rejectHook.mutate({
      proposalId: proposal.proposal_id,
      data: { review_note: '' },
    })
  }

  return (
    <div className="border rounded p-4 space-y-3 bg-card">
      <div className="space-y-1">
        <p className="text-xs text-muted-foreground">
          {t('admin.proposer')}: {proposal.proposer_user_id}
        </p>
        <p className="text-sm font-medium">{proposal.prompt_nl}</p>
        <pre className="text-xs bg-muted rounded p-2 overflow-auto max-h-32">
          {proposal.code_preview}
        </pre>
      </div>

      {/* PRO.2 — lo que el modelo auditor vio y el AST no puede ver. Va antes del re-test:
          es lo que ayuda a decidir si merece la pena volver a ejecutarlo. */}
      {proposal.model_review && <ModelAuditVerdict revision={proposal.model_review} />}
      {proposal.informe_anonimizacion && (
        <InformeAnonimizacion informe={proposal.informe_anonimizacion} proposalId={proposal.proposal_id} />
      )}

      {/* Retest result */}
      {retestResult && (
        <div className="flex items-center gap-2 text-xs">
          <span
            data-testid="hash-match-indicator"
            className={retestResult.hash_matches ? 'text-green-600 font-medium' : 'text-red-600 font-medium'}
          >
            {retestResult.hash_matches ? '✓' : '✗'}
          </span>
          <span className="text-muted-foreground">{t('test_result.hash')}: {retestResult.hash}</span>
        </div>
      )}

      {/* Desplegable y no texto libre (VER.5): pedía el **UUID** de la plantilla, que nadie
          sabe de memoria, y un UUID mal escrito da un 404 después de haber pulsado aprobar.
          Solo las globales: el script aprobado se incrusta en una plantilla de plataforma. */}
      <div className="space-y-1">
        <label className="text-xs text-muted-foreground" htmlFor={`target-template-${proposal.proposal_id}`}>
          {t('admin.target_template_label')}
        </label>
        <select
          id={`target-template-${proposal.proposal_id}`}
          data-testid={`target-template-${proposal.proposal_id}`}
          value={targetTemplateId}
          onChange={e => setTargetTemplateId(e.target.value)}
          className="w-full text-xs border rounded px-2 py-1 bg-background"
        >
          <option value="">{t('admin.target_template_placeholder')}</option>
          {plantillasGlobales.map(tmpl => (
            <option key={tmpl.id} value={tmpl.id}>{tmpl.name}</option>
          ))}
        </select>
      </div>

      <div className="flex gap-2">
        <button
          type="button"
          data-testid="btn-retest"
          disabled={retestHook.isPending}
          onClick={handleRetest}
          className="px-3 py-1 text-xs border rounded hover:bg-accent/30 disabled:opacity-50"
        >
          {t('btn.retest')}
        </button>
        <button
          type="button"
          data-testid="btn-approve-proposal"
          aria-disabled={!canApprove}
          disabled={!canApprove || approveHook.isPending}
          onClick={handleApprove}
          className="px-3 py-1 text-xs bg-green-600 text-white rounded disabled:opacity-50"
        >
          {t('btn.approve')}
        </button>
        <button
          type="button"
          data-testid="btn-reject-proposal"
          disabled={rejectHook.isPending}
          onClick={handleReject}
          className="px-3 py-1 text-xs bg-red-600 text-white rounded disabled:opacity-50"
        >
          {t('btn.reject')}
        </button>
      </div>
    </div>
  )
}

export function AdminScriptReviewQueuePage() {
  const { t } = useTranslation('scripts')
  const { user } = useAuth()
  const isAdmin = user?.role === 'superadmin' || user?.role === 'admin'

  const listHook = useListPendingScripts()
  const proposals = listHook.data as unknown as PendingProposalOut[] | undefined

  if (!isAdmin) {
    return <Navigate to="/hub" replace />
  }

  return (
    <div data-testid="review-queue-page" className="space-y-4 p-4">
      <h1 className="text-lg font-semibold">{t('admin.queue_title')}</h1>

      {listHook.isPending && (
        <p className="text-sm text-muted-foreground">{t('btn.retest')}…</p>
      )}

      {!listHook.isPending && (!proposals || proposals.length === 0) && (
        <p className="text-sm text-muted-foreground">{t('admin.no_proposals')}</p>
      )}

      {proposals?.map(proposal => (
        <ProposalCard key={proposal.proposal_id} proposal={proposal} />
      ))}
    </div>
  )
}
