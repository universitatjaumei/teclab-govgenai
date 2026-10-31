# Las secciones de un sitio

Dentro de un sitio hay partes que cambian continuamente: jornadas, eventos, becas, convocatorias. Una **sección** permite tratar una de esas partes por separado: qué páginas la forman, cada cuánto se revisa, quién es responsable y, sobre todo, que su actualización en el asistente sea automática. Sin secciones, el sitio se rastrea entero. Para empezar no hace falta ninguna.

## Crear una sección

En **Sitios → Secciones del sitio → Nueva sección** se pide:

- **Nombre** y **Patrón**. El patrón dice qué páginas son de la sección: lo habitual es un prefijo de ruta, aunque también vale una expresión regular. **Probar patrón** dice cuántas de las páginas ya rastreadas casan. La pertenencia no se guarda página a página: se calcula con el patrón cada vez, así que si cambias el patrón, la sección cambia con él.
- **Cadencia propia** y criterios de curación. Un campo vacío hereda el valor del sitio.
- **Responsable**: quien se encarga de esa parte.

## Manual o automático

- **Manual** es el modo de toda sección nueva. La plataforma rastrea y avisa de lo nuevo, lo cambiado y lo desaparecido, pero no toca el contenido de ningún asistente: todo pasa por una persona.
- **Automático**: cuando la sección ya se ha curado, la plataforma la mantiene al día sola. Incorpora las páginas nuevas, actualiza las que han cambiado y retira las que han desaparecido del portal, con dos salvaguardas: no incorpora nada que tenga un hallazgo bloqueante, y **no retira nunca mucho de golpe**. Si un rastreo tuviera que retirar más del 30 % de la sección, no retira nada y avisa con las cifras.

La idea es **curar una vez, automatizar después**: primero la revisa una persona y luego se pasa a automático.

## El diario de pasadas

Cada rastreo de una sección deja constancia en el **Diario de pasadas**: cuántas páginas se ingirieron, reingirieron, retiraron o bloquearon. Así se puede saber por qué una página entró o salió.
