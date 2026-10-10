import { useTranslation } from 'react-i18next'
import type { ColumnInfo, ColumnSubstitution } from '@/shared/api/generated/model'
import { ColumnSubstitutionFakerProvider } from '@/shared/api/generated/model'

interface TestDataAnonymizerFormProps {
  /** Las columnas tal como las describió el servidor, con el sustituto que propone. */
  columns: ColumnInfo[]
  /** Lo que la persona ha elegido; lo que no está aquí sigue la propuesta del servidor. */
  value: ColumnSubstitution[]
  onChange: (sustituciones: ColumnSubstitution[]) => void
}

/** Lo elegido para una columna, o lo que propuso el servidor si nadie lo ha cambiado. */
export function sustitutoDe(columna: ColumnInfo, elegidas: ColumnSubstitution[]): string {
  return (
    elegidas.find(s => s.column_name === columna.name)?.faker_provider
    ?? columna.inferred_faker_provider
    ?? ColumnSubstitutionFakerProvider.keep
  )
}

/**
 * #255 — una fila por columna, con el sustituto que el servidor propuso ya elegido. Antes este
 * formulario recibía una lista vacía y tenía su propio catálogo de sustitutos, que no coincidía
 * con el del servidor; los sustitutos salen ahora del contrato.
 */
export function TestDataAnonymizerForm({ columns, value, onChange }: TestDataAnonymizerFormProps) {
  const { t } = useTranslation('scripts')

  function handleChange(columna: string, sustituto: string) {
    const resto = value.filter(s => s.column_name !== columna)
    onChange([
      ...resto,
      { column_name: columna, faker_provider: sustituto as ColumnSubstitution['faker_provider'] },
    ])
  }

  if (columns.length === 0) {
    return <p className="text-sm text-muted-foreground">{t('anonymize.no_columns')}</p>
  }

  return (
    <div className="space-y-2">
      <h3 className="text-sm font-medium">{t('anonymize.title')}</h3>
      <table className="w-full text-sm border rounded">
        <thead>
          <tr className="bg-muted text-left">
            <th className="px-3 py-2">{t('anonymize.column')}</th>
            <th className="px-3 py-2">{t('anonymize.faker_provider')}</th>
          </tr>
        </thead>
        <tbody>
          {columns.map(col => (
            <tr key={col.name} className="border-t">
              <td className="px-3 py-2 font-mono text-xs">{col.name}</td>
              <td className="px-3 py-2">
                <select
                  data-testid={`sustituto-${col.name}`}
                  aria-label={`${t('anonymize.faker_provider')}: ${col.name}`}
                  value={sustitutoDe(col, value)}
                  onChange={e => handleChange(col.name, e.target.value)}
                  className="text-xs border rounded px-2 py-1 w-full"
                >
                  {Object.values(ColumnSubstitutionFakerProvider).map(p => (
                    <option key={p} value={p}>{p}</option>
                  ))}
                </select>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
