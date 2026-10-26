import type { WorkspaceData } from '@/redaccion/components/WorkspaceEditor'
import type { PreviewPayload } from '@/shared/api/generated/model'

interface MockWorkspaceOptions {
  block1State?: string
}

export function mockWorkspaceWithMixedBlocks(
  options: MockWorkspaceOptions = {},
): WorkspaceData {
  const block1State = options.block1State ?? 'needs_review'
  return {
    status: 'in_review',
    blocks: [
      {
        block_id: 'block-1',
        kind: 'AI_ASSISTED_TEXT',
        status: block1State,
        content: null,
        failure_kind: null,
        last_error_message: null,
        retry_attempts: 0,
        updated_at: '2026-01-01T00:00:00Z',
      },
      {
        block_id: 'block-2',
        kind: 'STATIC_TEXT',
        status: 'approved',
        content: { text: 'Static content' },
        failure_kind: null,
        last_error_message: null,
        retry_attempts: 0,
        updated_at: '2026-01-01T00:00:00Z',
      },
      {
        block_id: 'block-3',
        kind: 'DETERMINISTIC_DATA',
        status: 'extracted',
        content: null,
        failure_kind: null,
        last_error_message: null,
        retry_attempts: 0,
        updated_at: '2026-01-01T00:00:00Z',
      },
    ],
  }
}

interface SamplePreviewOptions {
  bodyBlockHtml?: string
  withCitations?: boolean
}

export function samplePreviewPayload(opts: SamplePreviewOptions = {}): PreviewPayload {
  const chunkId = 'a1b2c3d4-e5f6-7890-abcd-ef1234567890'
  const blockHtml = opts.bodyBlockHtml ?? '<p>Contenido del bloque aprobado.</p>'
  const citations = opts.withCitations ? [chunkId] : []

  return {
    workspace_id: 'ws-0000-0000-0000-000000000001',
    template_version_id: 'tv-0000-0000-0000-000000000001',
    cover: {
      level: 0,
      title: 'Informe de prueba',
      blocks: [],
    },
    toc: [{ level: 1, title: 'Sección principal' }],
    body: [
      {
        level: 1,
        title: 'Sección principal',
        blocks: [
          {
            block_id: 'block-1',
            kind: 'AI_ASSISTED_TEXT',
            state: 'approved',
            html: blockHtml,
            citations,
          },
        ],
      },
    ],
    audit_annex: opts.withCitations
      ? [
          {
            chunk_id: chunkId,
            source_url: null,
            source_filename: 'documento.pdf',
            page: 1,
            model_used: 'claude-sonnet-4-6',
            prompt_version: 'v1',
            approvals: ['block-1'],
          },
        ]
      : [],
    manifest_id: 'mf-0000-0000-0000-000000000001',
    generated_at: '2026-05-20T10:00:00Z',
  }
}
