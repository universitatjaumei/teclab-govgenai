# Hoja de ruta

Este documento dice **qué hace hoy la plataforma, qué se está construyendo, qué está previsto,
qué espera una decisión ajena y qué no se va a hacer**. Es la vista pública del plan, por temas y
con estado, y no lleva fechas: las dependencias son ciertas y las fechas no lo serían.

Tres cosas para leerlo bien:

- **El detalle vive en GitHub.** Cada tema enlaza a sus *issues* y a sus hitos; ahí está el
  diseño, la discusión y el cierre. Este documento se actualiza cuando un hito se abre o se
  cierra, no con cada *issue*.
- **Qué garantiza el sistema está en otro sitio.** Un estado «construido» aquí significa que la
  capacidad existe; lo que se puede dar por cierto al construir encima, invariantes incluidos,
  está en [`docs/ESPECIFICACIONES.md`](docs/ESPECIFICACIONES.md). Para una lectura de conjunto,
  [`docs/PRESENTACION_PROYECTO.md`](docs/PRESENTACION_PROYECTO.md).
- **Los planes TDD de `planificacion/` son documentos de diseño con historia**, escritos en
  futuro y antes de decisiones que después se revirtieron. No se enmiendan; se leen para saber
  por qué se decidió lo que se decidió.

## Estados

| Estado | Significa |
|---|---|
| **En producción** | Desplegado y en uso en la instalación de referencia |
| **Construido** | Completo y verificado en la rama de desarrollo; aún sin desplegar |
| **En curso** | Hay trabajo abierto con *issues* asignadas |
| **Previsto** | Diseñado y encolado; no empezado |
| **Bloqueado** | Espera una decisión o un prerrequisito **externo al proyecto** |
| **No se hace** | Descartado a propósito, para que nadie lo construya creyendo que falta |

## Temas

### 1. Asistentes informativos sobre normativa — En producción

Chatbots de recuperación aumentada sobre el corpus normativo de la institución, con citas
resolubles, aviso de vigencia, política de lengua y trazas por petición. Evaluación con lote
dorado y veredicto humano.

Abierto: revisión humana de las respuestas ([#8](https://github.com/universitatjaumei/teclab-govgenai/issues/8));
el catálogo de procedimientos en el mismo asistente ([#12](https://github.com/universitatjaumei/teclab-govgenai/issues/12),
**bloqueado** por las fichas validadas y la consulta de descarga); orden vigencia→lengua y aviso
de traducción ([#9](https://github.com/universitatjaumei/teclab-govgenai/issues/9)); reordenador
por API y su medición en valenciano ([#10](https://github.com/universitatjaumei/teclab-govgenai/issues/10)).

### 2. Corpus normativo y curación de portales — En producción

El corpus entra como Markdown conforme a contrato, con vocabulario versionado como dato y
taxonomía nunca embebida, de modo que reclasificar cuesta un `UPDATE` y no un reindexado. La
curación rastrea portales públicos con cadencia, detecta huecos y propone secciones.

Sin trabajo abierto de alcance nuevo. El vocabulario está **pendiente de validación** por la
secretaría general de la instalación de referencia, y el diseño está hecho para que ese cambio sea
barato.

### 3. Informes deterministas y catálogo de funciones — En producción (informes) · Construido (catálogo)

Informes con tablas que calcula código y valoración de la IA sujeta a aprobación humana. Las
extracciones deterministas se escriben una vez como **funciones** con contrato declarado,
versionadas e inmutables, con dos orígenes (autoservicio con *sandbox*; paquete por *entry
point*), registro sin aprobación previa y revisión posterior por muestreo. Detalle en
[`docs/CATALOGO_FUNCIONES.md`](docs/CATALOGO_FUNCIONES.md).

Abierto: los campos de entrada manual de una plantilla sin dónde rellenarse
([#86](https://github.com/universitatjaumei/teclab-govgenai/issues/86)). La ampliación del
catálogo a tareas completas es el tema 4.

### 4. Automatización gobernada — En curso

**Sustituye a la «Fase 2: Automatización y Thin Client»** del plan original. De aquélla, la
migración de la interfaz quedó vacía al retirar el cliente antiguo, y la migración de servicios
se hizo bajo otros nombres (el catálogo de funciones, el *sandbox*, el `RunManifest`, el registro
de actividad y las verificaciones por API y MCP). Lo único que quedaba vivo era el agente de
ejecución local, y **se descarta**: los agentes de propósito general con acceso al navegador y al
escritorio ya cubren ese terreno, en el régimen que las normas de desarrollo ciudadano reservan al
uso personal. Lo que esos agentes no dan, y la plataforma sí, es **registro, ecosistema
autorizado, revisión posterior y anonimización**. A eso se dedican los cuatro hitos.

| Hito | Estado | Qué entrega | Issues |
|---|---|---|---|
| [1 — Cerrar lo que ya no se hace](https://github.com/universitatjaumei/teclab-govgenai/milestone/9) | ✅ Completo | La especificación declara como límite deliberado que no se ejecuta nada en el equipo de quien la usa; los planes de fase 2 se cierran | [#112](https://github.com/universitatjaumei/teclab-govgenai/issues/112), [#113](https://github.com/universitatjaumei/teclab-govgenai/issues/113) |
| [2 — Registrar lo que corre fuera](https://github.com/universitatjaumei/teclab-govgenai/milestone/10) | ✅ Completo | Funciones de **origen externo** (un cuaderno se registra por su hash sin ejecutarlo); paquete MCP y *skill* de gobernanza para agentes de código; registro de la ejecución de un cuaderno en tres líneas; depósito del manifiesto de una ejecución hecha fuera | [#114](https://github.com/universitatjaumei/teclab-govgenai/issues/114), [#115](https://github.com/universitatjaumei/teclab-govgenai/issues/115), [#124](https://github.com/universitatjaumei/teclab-govgenai/issues/124), [#116](https://github.com/universitatjaumei/teclab-govgenai/issues/116) |
| [3 — Funciones de tarea](https://github.com/universitatjaumei/teclab-govgenai/milestone/11) | En curso | Una función produce **ficheros**; red saliente sólo hacia **orígenes declarados**; el ecosistema de módulos ampliado y vigilado; el cuaderno del presupuesto propio como caso guía, partido en dos funciones —anonimizar, y luego CSV limpio y Word— y con datos sintéticos. El de las subvenciones nominativas **se aplaza** ([#211](https://github.com/universitatjaumei/teclab-govgenai/issues/211)): tiene que bajar decenas de PDF y no cabe en una URL por slot | [#117](https://github.com/universitatjaumei/teclab-govgenai/issues/117), [#118](https://github.com/universitatjaumei/teclab-govgenai/issues/118), [#119](https://github.com/universitatjaumei/teclab-govgenai/issues/119), [#120](https://github.com/universitatjaumei/teclab-govgenai/issues/120) |
| [4 — Decisiones de la institución](https://github.com/universitatjaumei/teclab-govgenai/milestone/12) | ✅ Completo | El régimen de ejecución frente a la regla de soberanía local; la lista del ecosistema autorizado y el plazo de revisión; quién revisa, quién suspende y la ruta a protección de datos | [#121](https://github.com/universitatjaumei/teclab-govgenai/issues/121), [#122](https://github.com/universitatjaumei/teclab-govgenai/issues/122), [#123](https://github.com/universitatjaumei/teclab-govgenai/issues/123) |
| [5 — Agentes de unidad sobre el asistente general](https://github.com/universitatjaumei/teclab-govgenai/milestone/17) | Previsto | Una unidad publica un **agente** —prompt, carpeta de documentos, índice y colectivo— y la plataforma lo cataloga, lo acota, selecciona los documentos de cada consulta y registra el uso; el modelo lo ejecuta el asistente general de la organización | [#172](https://github.com/universitatjaumei/teclab-govgenai/issues/172), [#173](https://github.com/universitatjaumei/teclab-govgenai/issues/173), [#174](https://github.com/universitatjaumei/teclab-govgenai/issues/174), [#175](https://github.com/universitatjaumei/teclab-govgenai/issues/175), [#176](https://github.com/universitatjaumei/teclab-govgenai/issues/176) |

**El hito 4 se resolvió el 2026-09-29, y con él la pregunta que condicionaba a los demás.** La
institución no ha tenido que declarar equivalente la ejecución central, porque la pregunta no se
plantea así: la regla de soberanía local de su norma es **un suelo y no un techo** — no obliga a
ejecutar en la plataforma y tampoco lo impide, así que no hacía falta ninguna excepción escrita.
Como ejecutar dentro da más control, es **preferible**; y como es voluntario, **las funciones de
origen externo del hito 2 no son un plan B, son la otra mitad permanente**: quien prefiera seguir
ejecutando en su equipo registra ahí, y la institución sabe igualmente qué circula.

Con la misma decisión quedaron fijados el **ecosistema autorizado** —los módulos que una función
puede usar, ampliados y, desde el hito 3, vigilados para que la lista y lo que la imagen instala
no se separen—, un **plazo de revisión posterior de 30 días naturales** que avisa sin bloquear, y
**quién revisa y suspende**. La **red saliente** se decidió un día después, el 2026-09-30, y se
abrió con dos cerrojos: **sólo lectura** y **sólo hacia los servidores que cada función declara**.
No hizo falta tocar la respuesta anterior, porque quien baja el documento es la plataforma y no
el guion: una función sigue sin poder hablar con nada, y lo que necesita de fuera se lo piden por
ella.

Queda el **hito 3**, el de más diseño, con tres de sus cuatro issues por delante.

#### El hito 5, y por qué encaja aquí

Muchas organizaciones ya tienen un asistente general contratado —con su protección de datos
acordada y su cuota de tokens incluida— y su gente lo usa a diario. Levantar otro asistente al
lado, para lo mismo, es pelearse con esa realidad; y dar licencias de una herramienta distinta a
todo el personal, cuando ya se paga una, es difícil de justificar.

**El hito 5 asume el asistente que la organización ya tiene y le añade lo que le falta.** Una
unidad —contratación, control interno, calidad de la docencia— reúne los documentos que gobiernan
su materia en una carpeta, un guion mantiene un **índice** con una ficha por documento, y la
plataforma guarda el **prompt** que convierte todo eso en un agente. Cuando alguien pregunta, la
plataforma elige los documentos pertinentes, compone el prompt con sus enlaces y registra el uso;
el asistente general abre esos documentos con la identidad de quien pregunta y responde con la
cuota que la organización ya paga.

El reparto es deliberado, y cada pieza está donde sale más barata y más segura:

| | Dónde |
|---|---|
| Documentos e índice | El almacén de la unidad. **La plataforma no custodia copias** |
| Permisos | Los del almacén y el rol del proveedor de identidad. Dos puertas independientes |
| Prompt, catálogo y selección | La plataforma |
| Cómputo del modelo | El asistente general, con la cuota de la organización |
| Registro | La plataforma, y **sólo metadatos** |

**Lo barato es lo que hace esto viable.** Indexar una ficha por documento son tres órdenes de
magnitud menos que trocear y embeber el texto completo, y no es una versión degradada: la
maquinaria del corpus normativo existe para poder citar el artículo exacto y no presentar como
vigente lo derogado, y un agente de unidad no promete eso. Cuando la promesa es más modesta, la
infraestructura también.

**Lo que se gana** es lo que un asistente general no da por sí solo: saber qué agentes existen y
de quién son, que dejen de usarse cuando su responsable los suspende, que no devuelvan documentos
superados, y que el uso quede registrado. La extensión de navegador es la pieza que cierra ese
circuito — sin ella, quien copia un prompt una vez puede reutilizarlo durante meses sin volver a
pasar por la plataforma, y el registro contaría un uso en vez de cincuenta.

**Lo que no promete, y conviene leerlo antes que lo anterior**: no es un control de acceso —
cualquiera puede abrir el asistente general sin pasar por aquí— y la plataforma registra lo que
ofreció, no lo que el modelo respondió.

### 5. Registro de actividad IA y gobernanza por API — En producción

La plataforma como registro de la actividad con IA de la institución, también de lo que se
construye fuera: evento de gobernanza por HTTP y MCP (metadatos, nunca contenido), catálogo de
categorías que se anuncia sin imponerse, y verificaciones como servicio (citas, vigencia,
auditoría estática de código). Detalle en
[`docs/REGISTRO_ACTIVIDAD_IA.md`](docs/REGISTRO_ACTIVIDAD_IA.md) y
[`docs/GOVERNANCA_PER_API.md`](docs/GOVERNANCA_PER_API.md).

Abierto: los candidatos de §4 de ese último documento que no están hechos; el depósito de
manifiestos entra por el hito 2 del tema 4. **No hay política de retención** del registro, y hace
falta una.

### 6. Identidad, roles, módulos y multitenencia — En producción

Entrada con la cuenta institucional, roles separados de los módulos concedidos, aislamiento por
organización con inventario tabla a tabla y cascada de configuración plataforma → organización →
chatbot. Detalle en [`docs/MULTITENENCIA.md`](docs/MULTITENENCIA.md).

Abierto, en el hito [Bloque 1 — dar de alta a una persona](https://github.com/universitatjaumei/teclab-govgenai/milestone/5):
conceder módulos donde se da de alta ([#100](https://github.com/universitatjaumei/teclab-govgenai/issues/100)),
la siembra del catálogo sin contraseña ([#97](https://github.com/universitatjaumei/teclab-govgenai/issues/97)) y
el guion de emergencia del superadministrador ([#96](https://github.com/universitatjaumei/teclab-govgenai/issues/96)).
La segunda fase de la multitenencia, vista y permisos por organización, espera al piloto
([#11](https://github.com/universitatjaumei/teclab-govgenai/issues/11)).

### 7. Operación, despliegue y apertura del repositorio — En curso

Despliegue en máquina virtual con imágenes construidas y arrancadas en CI, esquema gobernado sólo
por Alembic, dependencias auditadas por lotes y reversión automática. Los hitos
[Bloque 2 — lo que ya costó una caída](https://github.com/universitatjaumei/teclab-govgenai/milestone/6) y
[Bloque 3 — lo que verá quien instale](https://github.com/universitatjaumei/teclab-govgenai/milestone/7)
recogen lo que queda antes y después de abrir. La numeración es `0.x` a propósito y no se promete
cadencia ni soporte: [`docs/VERSIONADO.md`](docs/VERSIONADO.md).

### 8. Trámites asistidos con IA — En curso

**Sustituye al «Gestor de expedientes» de la fase 3 del plan original.** Las administraciones ya
tienen un gestor de expedientes, y es la fuente de verdad del procedimiento: sus fases, su estado,
quién firma, la notificación, la evidencia de interoperabilidad. Construir otro era duplicarlo.
Lo que hace falta, y lo que la plataforma aporta, es un conjunto de **trámites con IA**
—baremación, informe de fase, redacción de resolución— que siguen las pautas del módulo de
informes y que se pueden **crear a mano en la plataforma o desde el gestor por API**. Las
primeras pruebas se hacen a mano.

El vínculo entre los dos sistemas se resuelve con un principio: **el estado del procedimiento
tiene un solo dueño, el gestor, y la plataforma nunca lo cambia.** La plataforma posee sólo la
ejecución del trámite —que es un workspace del motor de informes con referencia al expediente—
y su evidencia. Validar en la plataforma es validar el contenido generado; el acto administrativo
sigue en el gestor.

| Hito | Estado | Qué entrega | Issues |
|---|---|---|---|
| [1 — Cerrar el gestor de expedientes como producto](https://github.com/universitatjaumei/teclab-govgenai/milestone/13) | ✅ Completo | La especificación, la presentación y el plan de fase 3 describen trámites asistidos; el documento del gestor híbrido se retira y lo sustituye una decisión fechada | [#126](https://github.com/universitatjaumei/teclab-govgenai/issues/126), [#127](https://github.com/universitatjaumei/teclab-govgenai/issues/127) |
| [2 — El trámite invocable, a mano y desde el gestor](https://github.com/universitatjaumei/teclab-govgenai/milestone/14) | Previsto | Contrato y catálogo de trámites; creación a mano o por API con referencia externa e idempotencia; estado con `acciones_permitidas` y callback firmado; enlace profundo de revisión, semántica de «validar» y retención; salida estructurada con hash | [#128](https://github.com/universitatjaumei/teclab-govgenai/issues/128), [#129](https://github.com/universitatjaumei/teclab-govgenai/issues/129), [#130](https://github.com/universitatjaumei/teclab-govgenai/issues/130), [#131](https://github.com/universitatjaumei/teclab-govgenai/issues/131), [#132](https://github.com/universitatjaumei/teclab-govgenai/issues/132) |
| [3 — Las tres clases de trámite](https://github.com/universitatjaumei/teclab-govgenai/milestone/15) | Previsto | **Baremación determinista y siempre verificada por una persona** (el modelo extrae hechos, la persona los verifica, una función puntúa con el baremo como dato, el modelo motiva leyendo la tabla); informe de fase; resolución con la normativa aplicable a fecha de referencia. Todas con datos sintéticos | [#138](https://github.com/universitatjaumei/teclab-govgenai/issues/138), [#133](https://github.com/universitatjaumei/teclab-govgenai/issues/133), [#134](https://github.com/universitatjaumei/teclab-govgenai/issues/134) |
| [4 — Decisiones de la institución](https://github.com/universitatjaumei/teclab-govgenai/milestone/16) | **Bloqueado** | Qué gestor, qué puede hacer y con qué entorno de pruebas; clasificación de riesgo de la baremación y evaluación de impacto antes de cualquier dato real; qué vale «validar» en el procedimiento y cuánto se conservan los documentos | [#135](https://github.com/universitatjaumei/teclab-govgenai/issues/135), [#136](https://github.com/universitatjaumei/teclab-govgenai/issues/136), [#137](https://github.com/universitatjaumei/teclab-govgenai/issues/137) |

Orden recomendado: 1, y después 2 y 3 en paralelo con datos sintéticos, empezando por el informe
de fase, que es la clase de menor riesgo y con la que se prueban los dos modos. El hito 4 no
bloquea el diseño; bloquea el paso a datos reales y al modo API. Si el gestor institucional no
puede llamar hacia fuera, **el modo manual es el vínculo**, y se construye igual.

Lo que se conserva del plan de la fase 3 y condiciona el diseño:

- el frontend **nunca** calcula qué acciones caben; el servidor devuelve `acciones_permitidas`,
  ahora sobre la ejecución del trámite, que es lo único que la plataforma posee;
- **el cloud orquesta, el edge ejecuta**, donde «edge» es el servidor desplegado en la nube de la
  institución; con el gestor en el mismo perímetro se cumple sin agente;
- los trámites referencian `plantilla@versión` y `función@versión`, nunca código incrustado;
- el agente analista y la vigencia a fecha de referencia sobreviven como **bloques de plantilla**
  de la resolución; la auditoría de equidad se aplaza hasta que haya base jurídica para los datos
  de colectivo.

Y la advertencia que conviene no descubrir después: este tema **sí toca actuación
administrativa**, y la baremación evalúa a personas, así que no hereda la clasificación de riesgo
de los asistentes informativos. Recorre su propio procedimiento, y ningún dato real entra antes.

El razonamiento completo, con las cinco piezas del vínculo y cómo se dan de alta más tipos de
trámite, está en [`docs/DECISION_TRAMITES_ASISTIDOS.md`](docs/DECISION_TRAMITES_ASISTIDOS.md).

### 9. Utilidades de uso directo — Previsto

Los otros ocho temas son capacidades que la plataforma construye. Éste es más corto de explicar:
hay operaciones que la gente necesita a diario y que **hoy resuelve subiendo el documento a una
aplicación online que no asegura el cumplimiento del RGPD**. Unir cinco anexos en un PDF. Partir
un expediente. Quitarle los datos personales a un listado antes de mandárselo a otra unidad.

No es un problema de capacidad —las dos cosas ya se saben hacer aquí, y las dos existían en la
aplicación anterior— sino de **trayecto**: mientras no estén donde la persona las necesita, la
alternativa es la web. Y el documento suele llevar datos personales, a menudo de terceros.

| Hito | Estado | Qué entrega | Issues |
|---|---|---|---|
| [1 — Lo que hoy se hace fuera](https://github.com/universitatjaumei/teclab-govgenai/milestone/18) | Previsto | Unir, dividir y optimizar PDF sin que el fichero salga; anonimizar un fichero tabular y descargarlo, como utilidad suelta y no como paso de un flujo | [#190](https://github.com/universitatjaumei/teclab-govgenai/issues/190), [#191](https://github.com/universitatjaumei/teclab-govgenai/issues/191) |

Las dos issues llevan **lo que hay que decidir antes de escribir**, y no es poco: si van como
funciones del catálogo —con declaración, auditoría y registro, pero entonces dependen de que una
función pueda producir ficheros— o como utilidad aparte; si queda constancia de que un documento
pasó por aquí; y, en la anonimización, qué se le promete a quien descarga. **Lo que no se
promete es que el resultado sea anónimo**: es seudonimización asistida, y la responsabilidad de
publicar sigue siendo de quien publica.

## Lo que no se hace

Límites deliberados, con su razón en
[`docs/ESPECIFICACIONES.md` §10](docs/ESPECIFICACIONES.md#10-qué-no-hace-la-plataforma):

- **Ejecutar en el equipo de quien la usa**: ni agente local, ni RPA, ni vigilantes de carpeta,
  correo o web, ni programador de flujos locales, ni *thin client*. Es la decisión del tema 4 y
  entra en la especificación con [#112](https://github.com/universitatjaumei/teclab-govgenai/issues/112).
- **Acceder a la nube personal de la persona con credenciales centralizadas** (unidades y
  documentos compartidos). La persona sube y descarga; lo que necesite sus credenciales corre
  fuera y se registra.
- **Un gestor de expedientes propio.** El de la institución es la fuente de verdad del
  procedimiento y la plataforma no cambia nunca su estado: entrega trámites asistidos y su
  evidencia. Es la decisión del tema 8 y entra en la especificación con
  [#126](https://github.com/universitatjaumei/teclab-govgenai/issues/126).
- **Puntuar personas con un modelo.** La baremación es determinista, con el baremo como dato y una
  función que puntúa hechos verificados por una persona; el modelo extrae y motiva, nunca puntúa.
- Asesoramiento jurídico, decisiones automáticas, código de motor generado en tiempo de
  ejecución, corpus compartido entre chatbots, conversión de documentos en el servidor, rastreo de
  redes internas, capas de compatibilidad.

## Cómo contribuir

Las *issues* marcadas
[`good first issue`](https://github.com/universitatjaumei/teclab-govgenai/issues?q=is%3Aopen+label%3A%22good+first+issue%22)
son puntos de entrada con alcance cerrado. Las marcadas `blocked` esperan algo externo y no
admiten código todavía. El método de trabajo, la firma de los *commits* y las reglas de la casa
están en [`CONTRIBUTING.md`](CONTRIBUTING.md) y [`AGENTS.md`](AGENTS.md).
