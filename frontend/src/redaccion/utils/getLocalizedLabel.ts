export function getLocalizedLabel(
  dict: Record<string, string>,
  locale: string,
): string {
  return dict[locale] ?? dict['es'] ?? dict['en'] ?? Object.values(dict)[0] ?? ''
}
