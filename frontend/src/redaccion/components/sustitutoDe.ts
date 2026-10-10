import type { ColumnInfo, ColumnSubstitution } from '@/shared/api/generated/model'
import { ColumnSubstitutionFakerProvider } from '@/shared/api/generated/model'

/** #255 — lo elegido para una columna, o lo que propuso el servidor si nadie lo ha cambiado. */
export function sustitutoDe(columna: ColumnInfo, elegidas: ColumnSubstitution[]): string {
  return (
    elegidas.find(s => s.column_name === columna.name)?.faker_provider
    ?? columna.inferred_faker_provider
    ?? ColumnSubstitutionFakerProvider.keep
  )
}
