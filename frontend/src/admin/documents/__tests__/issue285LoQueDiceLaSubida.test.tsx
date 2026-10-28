import { describe, it, expect, beforeAll } from 'vitest'
import { render, screen } from '@testing-library/react'
import i18n from '@/shared/i18n'
import { motivoDelRechazo } from '../motivoDelRechazo'
import { JobStatusBadge } from '../DocumentBadges'

/**
 * #285 — dos cosas que el panel no decía de una subida.
 *
 * El 422 de validación de FastAPI llega como una lista `[{loc, msg, type}]`, y como no era el
 * formato `{code, message}` el panel enseñaba «Request failed with status code 422». Y un
 * trabajo completado que omitió algo a propósito —`us_assistents: no`— no lo decía en ninguna
 * parte: la nota iba en `error_message`, que el panel sólo pinta en los fallidos.
 */
beforeAll(async () => {
  await i18n.changeLanguage('es')
})

function falloCon(detail: unknown): Error {
  return Object.assign(new Error('Request failed with status code 422'), {
    response: { data: { detail } },
  })
}

describe('motivoDelRechazo', () => {
  it('should_explain_the_fastapi_validation_list', () => {
    const t = i18n.getFixedT('es', 'admin')
    const motivo = motivoDelRechazo(
      falloCon([{ loc: ['body', 'language'], msg: 'Input should be a valid string', type: 'string_type' }]),
      t,
    )

    expect(motivo).not.toContain('Request failed')
    expect(motivo).toContain('language: Input should be a valid string')
  })

  it('should_keep_explaining_the_contract_violation', () => {
    const t = i18n.getFixedT('es', 'admin')
    const motivo = motivoDelRechazo(
      falloCon({
        code: 'CORPUS_CONTRACT_VIOLATION',
        message: 'x',
        problemas: [{ campo: 'title', problema: 'falta' }],
      }),
      t,
    )

    expect(motivo).toContain('title: falta')
  })
})

describe('JobStatusBadge', () => {
  it('should_show_the_notes_of_a_completed_job', () => {
    render(<JobStatusBadge status="completed" error={null} avisos={['norma.md: us_assistents=no (derogada)']} />)

    expect(screen.getByText('norma.md: us_assistents=no (derogada)')).toBeInTheDocument()
  })
})
