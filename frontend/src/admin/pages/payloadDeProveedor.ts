/**
 * Lo que se manda al guardar un proveedor (SEC.9.2).
 *
 * Dejar el campo de la clave vacío significa «no la cambies», **no «bórrala»**. Desde que la
 * clave dejó de viajar en el contrato, el formulario arranca vacío al editar, así que sin esto
 * cambiarle el nombre a un proveedor le borraría la credencial — y el fallo no aparecería al
 * guardar, sino en la siguiente llamada al modelo.
 *
 * La región se manda tal cual: limpiarla y anularla fuera de Vertex es del servidor, que es
 * donde vale para todos los clientes (revisión de la PR #373).
 *
 * Función pura y exportada a propósito: es una decisión con consecuencias y así se puede fijar
 * con un test.
 */
export function payloadDeProveedor<T extends { api_key?: string | null }>(values: T) {
  if (values.api_key) return values
  const { api_key: _omitida, ...resto } = values
  return resto
}
