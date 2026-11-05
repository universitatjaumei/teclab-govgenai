/**
 * Lo que se manda al guardar un proveedor (SEC.9.2).
 *
 * Dejar el campo de la clave vacío significa «no la cambies», **no «bórrala»**. Desde que la
 * clave dejó de viajar en el contrato, el formulario arranca vacío al editar, así que sin esto
 * cambiarle el nombre a un proveedor le borraría la credencial — y el fallo no aparecería al
 * guardar, sino en la siguiente llamada al modelo.
 *
 * Función pura y exportada a propósito: es una decisión con consecuencias y así se puede fijar
 * con un test.
 */
export function payloadDeProveedor<T extends { api_key?: string | null; location?: string | null }>(
  values: T,
) {
  // #372 — la región vacía es **nula**, que significa «la del entorno»; una cadena vacía se
  // guardaría tal cual y la tabla diría que hay una región puesta.
  const conRegion = { ...values, location: values.location?.trim() || null }
  if (conRegion.api_key) return conRegion
  const { api_key: _omitida, ...resto } = conRegion
  return resto
}
