# Guía de uso: qué hace cada quien con la plataforma

> **Clase: referencia viva.** Escrita el 2026-09-19; el 2026-10-05 se añadieron Automatización,
> Utilidades y Agentes de unidad. Describe cómo se usa la plataforma **ya
> instalada y arrancada**: qué hace un superadministrador el primer día, y cómo se llega desde
> ahí a un asistente publicado, un informe aprobado o un portal curado.
>
> **Esto no es la instalación.** Para levantarla, [`INSTALACION.md`](INSTALACION.md) —incluida la
> elección de modelos locales o por API—. Para el despliegue del prototipo,
> [`DESPLIEGUE_PROTOTIPO_GCP.md`](DESPLIEGUE_PROTOTIPO_GCP.md).
>
> **Esto tampoco es la especificación.** Aquí está el recorrido; lo que el sistema **garantiza**,
> capacidad por capacidad, está en [`ESPECIFICACIONES.md`](ESPECIFICACIONES.md).

---

## 1. Lo primero: quién puede hacer qué

Dos cosas distintas deciden si alguien ve una pantalla, y confundirlas es la causa más habitual
de «tengo el rol y no me deja»:

- **El rol** dice qué clase de persona eres.
- **El módulo concedido** dice a qué partes de la instalación entras. Es una **unidad de
  licencia**: una organización puede tener contratados Chatbots e Informes y no Curación.

| Rol | Qué le corresponde |
|---|---|
| `superadmin` | La plataforma entera: organizaciones, proveedores y modelos de LLM, módulos, tokens. Entra en todos los módulos **sin concesión explícita** —si dependiera de una fila, una instalación recién creada dejaría a su administrador encerrado fuera—. |
| `admin` | Crea y configura los asistentes, informes y portales de **sus** organizaciones. |
| `informer` | Supervisa y valida lo que responde la IA. |
| `user` | Usa los asistentes y trabaja los informes. |

Los diez módulos: `chatbots`, `curacion`, `informes`, `automatizacion`, `personas`, `registro`,
`utilidades`, `agentes`, `consulta_agentes` y `plataforma`.

`personas` está separado de `plataforma` a propósito: administrar a la gente de tu organización
no es administrar la plataforma, y meterlo ahí obligaba a dar los modelos de LLM y los tokens
para poder dar lo primero. Con `registro` pasa lo mismo.

**Dos módulos son de oficio**: `utilidades` y `consulta_agentes` los tiene cualquier persona de
la plataforma, también quien se dé de alta mañana, sin concesión. Concederlos se rechaza porque
no cambiaría nada.

`automatizacion` salió de `informes` el 2026-10-05: una función de origen externo no produce
ningún informe. Los scripts que quien redacta propone para su plantilla siguen en `informes`
(§4.3).

**Al entrar, la aplicación aterriza en el primer módulo concedido**, no en una pantalla fija.
Quien sólo hace informes entra en informes.

---

## 2. El primer día: lo que hace el superadministrador

La instalación recién sembrada trae **una organización de ejemplo, un chatbot de ejemplo y sus
prompts de bienvenida** en castellano, catalán e inglés. Sirve para comprobar que todo responde;
no sirve como punto de partida de nada real.

### 2.1 Dar de alta la organización

`/plataforma/organizaciones`. Una organización es el eje sobre el que se acota todo lo demás: un
asistente, un portal curado o un informe pertenecen siempre a una.

Si la instalación va a servir a varias —el caso de una diputación con sus municipios—, se crean
todas aquí. **No se ven entre ellas**, y eso no es una opción de configuración: es cómo está
construido el acceso a datos ([`MULTITENENCIA.md`](MULTITENENCIA.md)).

### 2.2 Conectar un proveedor de modelos

`/plataforma/modelos`. Dos pasos que conviene no mezclar:

1. **La credencial del proveedor.** Se guarda **por referencia, no por valor**: lo que se declara
   es *dónde* está el secreto —el nombre de una variable de entorno, o las credenciales por
   defecto de la nube—, nunca el secreto en sí. Así un volcado de la base de datos deja de ser
   sensible.
2. **Las configuraciones de modelo**, que son las que usa el sistema. Cada una declara su
   **propósito** y su **nivel**.

**El nivel es un papel, no un modelo.** Dos niveles pueden apuntar al mismo modelo; lo que cambia
es para qué se usa. Qué actividad consume cada nivel:
[`NIVELES_DE_MODELO.md`](NIVELES_DE_MODELO.md).

Hay un propósito aparte, `embedding`, que decide con qué se vectoriza el corpus. Sin ninguna fila
de ese propósito, el sistema usa el modelo local. **Cambiarlo no es inocuo**: el corpus ya
indexado quedaría en un espacio vectorial distinto del de las preguntas, y eso no da error, da
respuestas malas. Por eso hay un guardarraíl que lo impide y obliga a reindexar a propósito.

### 2.3 Conceder módulos

`/plataforma/modulos`. Sin concesión no hay acceso, para cualquier rol que no sea
`superadmin`. Es aquí donde se decide qué tiene contratado cada organización.

### 2.4 Dar de alta a las personas

`/personas`. Alta manual, con contraseña local, mientras el SSO institucional no esté conectado.
Cuando lo esté, las personas llegan del IdP y esta pantalla pasa a ser el sitio donde se revisa
lo que el IdP declara.

Se puede crear, editar, cambiar la contraseña y dar de baja. La pantalla no deja quedarse sin
ningún superadministrador activo: es la comprobación que evita cerrar la puerta desde dentro.

### 2.5 Identidad visual y tokens

`/plataforma/identidad-visual` aplica la cascada **Plataforma → Organización → Chatbot**: lo que
se fija arriba se hereda abajo, y cada nivel puede cambiar **campos sueltos** sin repetir la
configuración entera. Un valor vacío y un valor sin poner significan cosas distintas: sin poner
es «hereda», vacío es «lo quiero vacío».

`/plataforma/tokens` emite **tokens de acceso personal** revocables, con *scopes*. Son lo que
consumen las integraciones máquina, incluido el servidor MCP
([`MCP_SERVER.md`](MCP_SERVER.md)). No son la credencial del widget público, que es otra cosa
(§3.5).

---

## 3. Chatbots: de cero a un asistente publicado

Módulo `chatbots`, rutas bajo `/hub`.

### 3.1 Crear el asistente

`/hub/chatbots`. Lo que hay que decidir al crearlo: a qué organización pertenece, qué
configuración de modelo usa, su *system prompt*, y su **modo de recuperación**.

Dos modos en uso:

- **`RAG`** — búsqueda híbrida (vectorial + texto completo) sobre los fragmentos del corpus. Es
  el modo por defecto y el adecuado para un corpus grande.
- **`MD_AGENT_SELECTOR`** — el modelo lee documentos enteros con *tools*. Sirve cuando el corpus
  es pequeño y la granularidad de documento importa más que la de fragmento.

Los perfiles de grafo público y qué hace cada uno: [`GRAPH_PROFILES.md`](GRAPH_PROFILES.md).

`/hub/valores-por-defecto` fija los valores de la organización que heredan sus asistentes
—troceado, presupuesto de contexto, reescritura de la consulta, lengua—, para no repetir la misma
configuración en cada uno. Un campo que se deja sin poner **vuelve a heredar** el defecto de
plataforma, que no es lo mismo que ponerlo a cero.

### 3.2 Cargar el corpus

`/hub/documents`. **Al corpus sólo entra Markdown conforme al contrato**
([`CONTRATO_MD_CORPUS.md`](CONTRATO_MD_CORPUS.md)). Un PDF devuelve **415** y dice a dónde ir.

No es una limitación técnica sino la frontera del diseño: lo que sale de convertir un PDF no
tiene *front-matter*, ni anclas de artículo, ni estado de vigencia, o sea que es contenido que el
asistente no puede citar como norma, entrando por la misma puerta que el corpus curado y
quedando indistinguible de él. La conversión vive en el pipeline de curación (§5), que es donde
está el OCR y donde se declara lo que se ha transcrito automáticamente.

Cada documento declara su procedencia —URL de origen, idioma, vigencia— y eso es lo que permite
que la respuesta cite el artículo exacto y avise cuando una norma ha sido desplazada.

Si hay que cargar el vocabulario de ámbitos y submaterias:
[`CARGA_VOCABULARIO.md`](CARGA_VOCABULARIO.md). Si hay que reingerir todo:
[`RUNBOOK_REINGESTA.md`](RUNBOOK_REINGESTA.md).

### 3.3 Ajustar los prompts

`/hub/prompts`. Las plantillas cuelgan del chatbot, están versionadas y van por idioma.

### 3.4 Probarlo antes de enseñarlo

Dos pantallas, y hacen cosas distintas:

- `/hub/test-scenarios` — escenarios de prueba guardados: preguntas con lo que debería
  contestarse. Sirven para ver si un cambio de configuración mejora o empeora, en vez de
  juzgarlo por una pregunta suelta.
- `/hub/revision` — revisión de las interacciones reales, con su valoración. Es donde se ve qué
  está contestando de verdad.

**Lo que más cuesta afinar no es que recupere, es que calle.** Está medido: los escenarios bien
anotados recuperan la norma correcta, y el hueco es declinar cuando no hay fundamento. Subir el
umbral de calidad no lo arregla. Si el asistente contesta cosas que no debería, el camino es la
revisión humana de respuestas, no el número.

### 3.5 Publicarlo

`/hub/chatbots`, en el propio asistente, se emite una **credencial de sitio** para el widget. Es
distinta de un token personal: **aparece en el HTML de quien publique la página**, y eso es el
diseño, no un descuido —por eso sólo abre chatbots públicos anónimos y nada más—.

Dos consecuencias prácticas: **una credencial por sitio** (si la misma está en dos, revocar por
abuso de uno apaga el otro), y **la que uses en local acaba dentro del HTML generado**, así que
emite una nueva para publicar y revoca la de pruebas.

El fragmento a pegar, los atributos y cómo se revoca:
[`WIDGET_INCRUSTACION.md`](WIDGET_INCRUSTACION.md). Plantilla de estilos y página de
demostración: [`chatbots-publicos/`](chatbots-publicos/).

### 3.6 Mantenerlo vivo

`/hub/vigencia` es la cola de documentos cuya vigencia toca comprobar. Se puede **tachar**: queda
constancia de que una persona lo revisó y cuándo. Una cola que no se puede tachar deja de
mirarse.

---

## 4. Informes: de una plantilla a un documento aprobado

Módulo `informes`, rutas bajo `/redaccion`. El contrato completo está en
[`REDACCION_CONTRACT_FIRST.md`](REDACCION_CONTRACT_FIRST.md); el caso guía que originó las dos
reglas duras del módulo, en [`CASO_INFORME_SEGUIMIENTO.md`](CASO_INFORME_SEGUIMIENTO.md).

### 4.1 La plantilla

`/redaccion/builder`. Una plantilla define los bloques del informe: texto, tablas, gráficos,
transformaciones de datos. Está **versionada**, y un informe se crea siempre a partir de una
versión concreta: así un cambio de plantilla no altera retroactivamente lo ya redactado.

### 4.2 El informe

`/redaccion/wizard` lista las plantillas disponibles y crea un **espacio de trabajo** a partir de
la que elijas; de ahí se entra en `/redaccion/workspaces/{id}`, que es donde se trabaja: se
suben los documentos de origen, se ejecutan los bloques y se revisa lo que sale.

La regla que ordena todo el módulo: **los números los produce código determinista; lo que escribe
el modelo es la valoración**, y va sujeta a aprobación humana antes de exportar. Un dato de un
informe institucional no sale de un modelo de lenguaje.

`/redaccion/workspaces/{id}/preview` es la vista de impresión, sin navegación.

### 4.3 Cuando hace falta calcular algo que no está

Tres caminos, en este orden:

1. **El catálogo de funciones** — `/automatizacion/funciones`, en el módulo `automatizacion`
   (§7). Funciones deterministas, versionadas y compartidas entre organizaciones. Antes de
   escribir código, mirar si ya existe.
2. **Proponer una función o un script** — **Informes → Pedir un script**
   (`/redaccion/scripts/wizard`). El código se **audita automáticamente** (auditoría estática
   graduada: aceptable, advertencia, crítico, con número de línea) y se prueba en un **sandbox
   sin red**. El filtro es automático, no una aprobación previa de nadie. Al declararlo, el
   script queda registrado como función del catálogo.
3. **La revisión posterior** — `/automatizacion/funciones/revision` para las funciones y
   `/redaccion/scripts/review` para los scripts. Es donde entra la persona: puede pedir
   correcciones, reclasificar o suspender una función ya publicada.

Por qué la persona entra **después** y no antes: la Instrucció 02/2026 prohíbe la aprobación
previa como condición para compartir dentro del servicio. La única aprobación previa que queda es
el paso al nivel 3. El aislamiento del sandbox, capa por capa:
[`SANDBOX_SECURITY.md`](SANDBOX_SECURITY.md).

### 4.4 Datos personales

La anonimización es **selectiva y por políticas**, no automática en todo. En informes y espacios
de trabajo hay NER reversible: se anonimiza antes de que el texto llegue al modelo y se
restituye después. El chatbot público no la lleva porque no recibe datos personales por diseño.

---

## 5. Curación: del portal al corpus

Módulo `curacion`, rutas bajo `/curation`. Es **previa** al asistente y vale por sí sola: el
entregable principal es el informe de auditoría del portal, tenga o no un chatbot detrás.

| Pantalla | Qué se hace |
|---|---|
| `/curation/sites` | Dar de alta el portal y sus **apartados**, que son parametrizables y tienen cadencia propia |
| `/curation/audit` | Lanzar y seguir el rastreo |
| `/curation/findings` | Los hallazgos: contenido caducado, contradictorio, insuficiente, con revisión vencida |
| `/curation/publish` | Decidir qué se publica y qué entra al corpus |

**Curación una vez, automatización después.** No hay ingesta automática de nada que nadie haya
aprobado: quien decide qué entra es una persona, y una página nueva es una señal para quien cura,
no un disparador.

Lo que sí hay, desde el bloque DIN, es **mantenimiento automático dentro del ámbito que alguien
aprobó una vez**. Un apartado que se renueva solo —jornadas, eventos, becas— se parametriza en
**Sitios → Secciones del sitio**, **nace en modo `manual`** y hay que pasarlo a `automatic` a
mano. En `manual`, una baja deja un aviso y no toca el corpus. Paso a paso:
[`SECCIONES_DINAMICAS.md`](SECCIONES_DINAMICAS.md).

El rastreo es cortés por construcción —pausa por *host*, `robots.txt` leído una vez por hora— y
el servidor **sólo pide direcciones de la red pública**, comprobado en cada salto y también a
través de redirecciones.

Recorrido completo y real: [`CASO_CURACION_ESCOLA_DOCTORAT.md`](CASO_CURACION_ESCOLA_DOCTORAT.md).
Con varias organizaciones: [`CURACION_MULTIORGANIZACION.md`](CURACION_MULTIORGANIZACION.md).
Cómo probarlo sin salir a internet:
[`../pruebas_manuales/`](../pruebas_manuales/) y el guion del bloque de curación.

---

## 6. Registro de actividad IA

Módulo `registro`, ruta `/registro`. No es para las respuestas de esta plataforma —ésas se
registran solas— sino para que **otras herramientas de la institución declaren que han usado IA**
y quede constancia en un sitio único.

Se registran **metadatos, no *payloads***: qué sistema, qué categoría de actividad, cuándo, con
qué modelo y con qué supervisión. El catálogo de categorías se anuncia, no se impone.
[`REGISTRO_ACTIVIDAD_IA.md`](REGISTRO_ACTIVIDAD_IA.md).

Junto a él hay **verificaciones como servicio**: comprobar citas, vigencia o auditoría estática
de código desde una aplicación de fuera, por API y con *scope* propio. El inventario de qué
comprueba y registra la plataforma, y qué de ello es accesible desde fuera:
[`GOVERNANCA_PER_API.md`](GOVERNANCA_PER_API.md).

---

## 7. Automatización: el catálogo de funciones

Módulo `automatizacion`, entrada **Automatización** del menú, con dos pestañas: **Funciones**
(`/automatizacion/funciones`) y **Revisión posterior** (`/automatizacion/funciones/revision`).
El contrato completo, campo a campo: [`CATALOGO_FUNCIONES.md`](CATALOGO_FUNCIONES.md).

### 7.1 Qué es una función

Una extracción o una tarea determinista —contar las filas de un fichero de gastos, leer los
importes de un PDF, sacar un CSV limpio— escrita **una vez**, con su contrato y una
**declaración responsable**: para qué sirve y qué categorías de datos trata. Las plantillas de
informe la **referencian** por `función@versión` en vez de llevar el código copiado.

Una versión registrada **no cambia nunca**: corregir es publicar otra, y las plantillas ancladas
a la anterior siguen ejecutándola hasta que su responsable decida adoptar la nueva. Una función
suspendida o retirada hace fallar en alto el bloque que la usa, con su nombre y el motivo.

### 7.2 Tres orígenes

| Origen | Dónde vive el código | Quién lo ejecuta |
|---|---|---|
| `autoservicio` | En el catálogo | La plataforma, en el sandbox |
| `paquete` | En el repositorio de un equipo, instalado con `pip` | La plataforma, en su proceso |
| `externa` | Donde lo tenga su autora: un cuaderno o un script | **Nadie desde aquí**: corre fuera |

Las de autoservicio pueden además **producir ficheros** —un Excel, un Word, un CSV— y **leer
documentos de fuera**, sólo por `GET`, sólo `https` y sólo de los servidores que declaren en el
contrato. Las dos cosas se declaran; lo que no se declara no se puede hacer.

### 7.3 Registrar una función externa

Para el cuaderno que circula por la unidad sin que nadie sepa cuántas copias hay ni de qué
versión. Se registra por API (`POST /api/v1/funciones/externas`) con el fichero entero —`.py` o
`.ipynb`—, la declaración responsable y **dónde corre**: con la sesión de una persona o con un
token con `funciones:register`, que es como lo registra el agente de código que acaba de
escribirlo. Por MCP, la herramienta `registrar_cuaderno` (`MCP_SERVER.md`). En el catálogo aparece como «Se ejecuta
fuera, registrada aquí».

**La plataforma no lo ejecuta**, y es a propósito: el código sigue corriendo donde corría, con
las credenciales de quien lo usa, y la plataforma no toca el dato. Sabe que existe, de qué
versión, para qué se declaró y quién responde de él. Dos consecuencias que conviene saber:

- **La auditoría es informativa**: sus hallazgos llegan a la revisión y no bloquean el registro,
  porque un programa que corre fuera usa red y disco legítimamente.
- **Suspenderla es un aviso, no un cerrojo**: la plataforma la marca y deja de recomendarla, y no
  puede impedir que alguien la ejecute fuera.

### 7.4 La revisión posterior

Registrar es compartir, y es automático. En una función de **autoservicio** basta con la
declaración completa, una auditoría sin hallazgos críticos y el sandbox superado; una **externa**
se registra con su declaración, su auditoría es sólo informativa y no pasa por el sandbox, porque
no se ejecuta aquí (§7.3). En los dos casos, **nadie lo aprueba antes**: la Instrucció 02/2026 prohíbe la aprobación previa
como condición para compartir dentro del servicio. La persona entra después, en **Revisión
posterior**, con un plazo de 30 días naturales que avisa sin bloquear.

Revisa y suspende el administrador de la organización autora o el superadministrador, **nunca
quien la escribió**. Retirar es de quien la escribe. Las decisiones de la institución que fijan
este régimen —el ecosistema de módulos autorizado, el plazo, quién revisa— están en
`CATALOGO_FUNCIONES.md` §4.

### 7.5 Ejecutarla desde fuera, y que conste

Una aplicación externa ejecuta una función con un token personal con el *scope*
`funciones:execute` (§2.5), **indicando siempre la versión**. Cada ejecución deja un evento en el
registro de actividad (§6) con la finalidad y las categorías que **la función declaró**, sin
*payloads*. Una función externa responde **409** y dice dónde corre de verdad.

El cuaderno externo cierra el circuito por su lado: al ejecutarse, calcula el hash de su propio
fichero y lo manda al registro de actividad en el campo `funcion_sha256`. Ese hash es el que el
catálogo guardó al registrarlo, así que **el catálogo dice qué cuadernos existen y el registro
dice cuándo corrieron**. Si el cuaderno no está registrado, el uso consta igual, y eso también es
información. El ejemplo de código: [`REGISTRO_ACTIVIDAD_IA.md`](REGISTRO_ACTIVIDAD_IA.md).

---

## 8. Utilidades

Módulo `utilidades`, **de oficio**, ruta `/utilidades`. Operaciones sueltas sobre un fichero que
hoy se hacen en webs que no aseguran el RGPD:

- **PDF** (`/utilidades/pdf`): unir varios, dividir uno —por rangos, extrayendo páginas sueltas o
  un fichero por página— y optimizarlo para que ocupe menos.
- **Anonimizar un fichero** (`/utilidades/anonimizar`): un CSV o un Excel. La pantalla propone una
  regla para cada columna, se revisa, se ve la vista previa y se descarga. **No se descarga sin
  haber visto la vista previa**, y lo comprueba el servidor. Es **seudonimización asistida, no
  anonimato garantizado**: lo que el detector no vea sale con el fichero, y la responsabilidad de
  lo que se comparte es de quien lo comparte.

**Nada se guarda**: el fichero entra en la petición y sale en la respuesta. Queda constancia del
uso en el registro de la organización —quién, cuándo, qué operación, cuántas páginas o filas—,
**nunca el nombre del fichero ni su contenido**. Quien no pertenece a una sola organización, como
el superadministrador, tiene que elegir una en el selector del panel antes de operar.

---

## 9. Agentes de unidad

Una unidad —contratación, control interno, calidad— publica un **agente**: un prompt, una carpeta
de documentos en el Drive de la organización y el colectivo que puede usarlo. **Nada de eso es
código**, y el modelo lo pone el asistente general de la organización (Gemini). La plataforma
cataloga, acota, guarda el **índice** de los documentos y, en cada consulta, elige cuáles tocan y
devuelve el prompt con sus enlaces.

**La plataforma no guarda ningún documento ni ve los adjuntos.** Guarda la URL y un resumen de
cada uno. Quien abre los enlaces es Gemini, **con la cuenta de quien pregunta**: la plataforma
selecciona y el Drive autoriza. Garantías completas: `ESPECIFICACIONES.md` §5.14.

Entrada **Agentes** del menú, con dos pestañas: **Consultar**, para cualquiera (módulo
`consulta_agentes`, de oficio), y la de publicar y gestionar, con el módulo `agentes`.

### 9.1 Publicar un agente

**Publicar un agente**, en la pestaña de gestión. Publicar es registrar: se ofrece desde ya, sin
aprobación previa, y quien revisa puede suspenderlo después. Lo que se declara:

| Campo | Qué es |
|---|---|
| Nombre, unidad, finalidad, responsable | La declaración. Sin ella no se publica. La unidad es texto: la plataforma no tiene unidades. |
| Prompt | Las instrucciones del agente. **Proponer un prompt** pide al modelo una propuesta a partir de lo que describas; se edita antes de publicar, y la versión publicada con ella consta como redactada con ayuda de IA. |
| Carpeta de documentos | La dirección de la carpeta de Drive. |
| Quién puede usarlo | Toda la organización o unos grupos del proveedor de identidad. Con el inicio de sesión de Google no llegan grupos, así que un agente por grupos no se le ofrecería a nadie; la pantalla lo avisa. |
| Fecha de revisión prevista | Cuándo volverá a mirarlo la unidad. **Se vuelve a escribir en cada versión nueva**: versionar es volver a mirarlo. Si vence, el agente se sigue ofreciendo, marcado. |
| Lengua de la respuesta | La de la pregunta, siempre castellano o siempre valenciano. La instrucción la añade la plataforma; no hace falta escribirla en el prompt. |
| Documento adjunto | Sin adjunto, puede adjuntar (quien pregunta lo dice en cada consulta) o siempre adjunta, que es un agente de revisión. Con adjunto, los documentos de la carpeta son **el criterio** con el que se analiza. |
| Documentos por consulta | Entre 1 y 10, 5 por defecto. Son los enlaces que Gemini abrirá de una vez. |
| Datos de la consulta | Lo esencial que tiene que dar quien pregunta —en un agente de pliegos, el tipo de contrato y qué se contrata—, como lista de opciones o como texto. Si se liga a una **columna del índice**, filtra en suave (§9.3). |
| Indicaciones para quien pregunta | Una línea que se ve al consultar. |
| Plazas reservadas por capa | Cuántas plazas de cada consulta van, como mínimo, a una capa del índice (§9.3). No pueden sumar más que los documentos por consulta. |
| Registro de conversaciones | **En validación**, el modo de partida, se guarda cada pregunta con su respuesta; en **sólo incidencias**, sólo lo que se informa como inadecuado. |

Corregir es publicar una **nueva versión**: se ofrece la última. Suspender es de quien revisa —el
administrador de la organización o el superadministrador, nunca quien lo publicó—, y retirar, de
quien lo publicó o del administrador de su organización.

### 9.2 El índice

El índice es una **hoja con una fila por documento**. Columnas obligatorias: `url`, `titulo` y
`resumen`. Opcionales: `vigente`, `revision_prevista_en`, `prioritario` y `capa`. Cualquier otra
columna se guarda como metadato, y es la que se puede ligar a un dato de la consulta. Los nombres
de columna se escriben tal cual, sin traducirlos.

Dos maneras de mantenerlo, desde **Actualización del índice** en la ficha del agente:

1. **El guion de Apps Script**, que es la normal. Se instala en una hoja junto a la carpeta —mejor
   en una unidad compartida: el de una cuenta personal se pierde cuando esa persona se va—, con un
   **token del guion** que se emite ahí mismo y sólo sirve para mandar el índice. Corre cada
   mañana con la cuenta de la unidad, resume con Gemini sólo lo nuevo o cambiado y manda el
   índice. **Los documentos no salen de Google.**
2. **Subir la hoja a mano**, en CSV o Excel.

**La hoja es el índice entero: lo que no venga se retira.** Lo que no cambió no se toca, y una
hoja incoherente no se carga a medias. La ficha del agente avisa si el guion lleva días sin mandar
el índice, cuántos documentos de la carpeta no tienen ficha —un documento sin ficha no existe
para el agente, y nadie recibe un error— y cuántas fichas se resumieron con un prompt anterior.
Regenerarlas es decisión de la unidad.

### 9.3 Cómo se eligen los documentos de una consulta

Cada ficha tiene un vector hecho **sólo del título y el resumen**; la pregunta, junto con los datos
de la consulta, se compara con él. El orden:

1. **Lo no vigente no entra**, ni ocupa plaza.
2. **El filtro suave de los datos de la consulta**: si un dato está ligado a una columna, se
   descarta la ficha cuyo valor lo contradice y se conserva la que no lo dice. Los códigos
   jerárquicos, como el CPV, casan por prefijo.
3. **Las prioritarias** (columna `prioritario`: el pliego tipo, el modelo de la casa) entran
   primero si pasan el filtro, **como mucho la mitad del presupuesto**, y **sin quitar plazas
   reservadas a otra capa**.
4. **Las reservas por capa**: para cada capa con plazas reservadas, las fichas de esa capa más
   parecidas a la pregunta, contando las prioritarias que ya son de ella. Así la ley o la doctrina
   no compiten con cientos de ejemplos. La plaza que una capa no llena vuelve al reparto general.
5. **El resto, por similitud**, hasta el presupuesto del agente.

Un ejemplo real de carpeta por capas: [`ejemplos/agentes/pliegos/`](ejemplos/agentes/pliegos/).

### 9.4 Consultar

**Desde el panel**: **Agentes → Consultar**. Se elige el agente, se escribe la pregunta, se
rellenan los datos que pida, **Preparar el prompt** y **Copiar el prompt**, y se pega en Gemini.
Si el agente espera un adjunto, se describe el documento en la pregunta —es lo que permite elegir
la normativa que toca— y se adjunta en el mismo mensaje.

**Desde la extensión de Chrome**, un panel lateral al lado de Gemini. Se instala desde la carpeta
`extension/` del repositorio ([`../extension/README.md`](../extension/README.md)) y se conecta
con **Conectar**: el panel pide confirmar con tu sesión y emite una conexión que sólo sirve para
consultar y caduca a los 30 días. Las conexiones se ven y se revocan en **Consultar**. Después:
elegir el agente, rellenar los campos y **Insertar en Gemini**, que **inserta sin enviar**: envía
la persona, que en un agente de revisión adjunta antes su documento. En un agente en validación,
la extensión lee la respuesta de Gemini y la manda a la plataforma, o dice por qué no pudo.

La extensión **no es un control de acceso**: Gemini se usa igual sin ella. Lo que da es que el
camino cómodo sea el que queda registrado.

**Buscar más documentos**, cuando la primera tanda no basta: se escribe qué falta —y se pueden
cambiar los datos—, se busca **con ese texto y no con la pregunta**, y **nunca se repite** lo ya
ofrecido en la conversación. Lo que se pega en la misma conversación de Gemini es corto, el texto
y los enlaces nuevos, sin volver a pegar el prompt del agente.

Cada consulta va al registro de actividad (§6) **sin la pregunta**.

### 9.5 La calidad de un agente

**Ver la calidad**, en la ficha del agente, sólo para quien lo publicó y quien lo revisa. Muestra
las conversaciones de lo más reciente a lo más antiguo, **sin decir quién preguntó**: en
validación, la pregunta, los datos, los documentos ofrecidos con su puntuación y la respuesta que
leyó la extensión. Las ampliaciones de «Buscar más documentos» aparecen bajo su conversación.

Quien consulta puede valorar con 👍/👎; un 👎 pide un motivo y es un **informe**, que en un agente
en sólo incidencias es lo único que se guarda. Quien revisa da a cada conversación un veredicto
—adecuada, en parte, inadecuada— con nota, y cada informe trae una pista de dónde mirar primero:
el permiso del documento, el índice, el prompt o la selección.

Lo que no se puede saber: si la persona regeneró la respuesta o siguió conversando en Gemini,
eso no llega.

---

## 10. Lo que la plataforma no hace, y conviene saber antes

- **No ejecuta nada en la máquina de quien la usa.** No hay agente de escritorio, ni vigilancia
  de carpetas, correo o web, ni programador de flujos locales, y **no los habrá**: se decidió el
  2026-09-23 no construir un agente de ejecución local, porque eso lo cubren los agentes de
  propósito general. Lo que aporta la plataforma es gobernanza: el catálogo de funciones (§7),
  incluidas las que corren fuera y sólo se registran. Tampoco hay gestor de expedientes, y no lo
  habrá: el de la institución es la fuente de verdad.
- **No convierte documentos para el corpus.** Eso es el pipeline de curación, y lo que llega al
  corpus es su salida.
- **No decide por una persona.** Ni qué entra al corpus, ni si una valoración es correcta, ni si
  una función sigue sirviendo.
- **No gobierna la IA de la institución.** El inventario de casos de uso, el registro de sistemas
  y la asignación de responsabilidades se gestionan fuera. Dónde acaba su alcance, y por qué esa
  separación es deliberada: [`MARCO_GOBERNANZA_IA.md`](MARCO_GOBERNANZA_IA.md).

La lista completa y razonada está en `ESPECIFICACIONES.md` §10.

---

## 11. Dónde seguir leyendo

| Si quieres | Lee |
|---|---|
| Saber qué garantiza el sistema y dónde se hace cumplir | [`ESPECIFICACIONES.md`](ESPECIFICACIONES.md) |
| Entender cómo está construido y por qué | [`Arquitectura.md`](Arquitectura.md) |
| Presentar el proyecto a alguien de fuera | [`PRESENTACION_PROYECTO.md`](PRESENTACION_PROYECTO.md) |
| Depurar por qué un asistente contestó lo que contestó | [`DEPURAR_CONTEXTO_RAG.md`](DEPURAR_CONTEXTO_RAG.md) |
| Saber qué se prueba a mano y qué no | [`PRUEBAS_MANUALES.md`](PRUEBAS_MANUALES.md) |
| Contribuir código | [`../CONTRIBUTING.md`](../CONTRIBUTING.md) |

> **Sobre [`chatbots-publicos/guia-pruebas-e2e.md`](chatbots-publicos/guia-pruebas-e2e.md)**: es
> un **guion de pruebas** del módulo de chatbots, pantalla a pantalla, y es **del 2026-05-13**.
> Sigue siendo útil como recorrido exhaustivo, pero es anterior a media docena de bloques —entre
> ellos el módulo Plataforma, las personas con contraseña local y la retirada de la ingesta de
> PDF—, así que sus detalles concretos hay que contrastarlos con esta guía.
