# Gov Gen AI Platform — Presentación del proyecto

> **Naturaleza del documento**: presentación del proyecto para instituciones, fundaciones y
> equipos externos que quieran conocerlo o colaborar. Describe qué hace la plataforma, qué está
> construido y verificado a día de hoy, y qué está previsto. No es documentación técnica: para
> cada tema remite al documento especializado correspondiente (§10).
>
> **Fecha**: 26 de agosto de 2026. Las cifras de este documento corresponden a esa fecha y son
> medidas, no estimadas. Cuando una cifra procede de una ejecución concreta, se dice cuál.
>
> **Revisión del 8 de septiembre de 2026.** La escala de madurez de este documento era propia
> —«prototipo», «piloto en producción»— y no se correspondía con la del Reglamento de IA de la
> Universitat Jaume I, que distingue **experimentación, validación y explotación**. Se ha
> reescrito §5.1 para usar esa escala, §6 para expresar los hitos en ella, y §7.1 para decir
> cuál es el mecanismo que conecta los dos planos de gobernanza —el **estudio de integración**
> del Annex II— y qué control técnico corresponde a cada salto. **Las cifras no se han vuelto a
> medir**: siguen siendo las del 26 de agosto y cada una lleva su fecha.

---

## 1. Qué es y para qué sirve

**Gov Gen AI Platform** es una plataforma de inteligencia artificial diseñada específicamente para
**administraciones públicas**. Su objeto es aplicar IA generativa y automatización a procesos
administrativos reales —atención ciudadana, redacción de informes, extracción de datos de
documentos, tramitación de expedientes— de forma **auditable, trazable y conforme a la normativa
europea y española**: Reglamento (UE) 2024/1689 de IA, RGPD, Leyes 39/2015 y 40/2015, y Esquema
Nacional de Seguridad.

Lo que la diferencia de un despliegue genérico de chatbots es que **la conformidad no es
documentación aparte**: está incorporada al diseño del sistema. Cada actuación asistida por IA
deja evidencia de supervisión humana, de procedencia de la información y del tratamiento de datos
personales aplicado. El principio rector es *compliance-as-code*: las obligaciones legales se
traducen en comprobaciones ejecutables y en pruebas automáticas, no en buena fe ni en auditorías
puntuales.

Conviene decir desde el principio dónde acaba su alcance: la plataforma cubre lo que un sistema
puede garantizar por diseño, no la gobernanza institucional de la IA. El inventario de casos de uso,
el registro de sistemas y la asignación de responsabilidades se gestionan **fuera** de ella, y §7
explica por qué esa separación es deliberada.

El primer despliegue es la **Universitat Jaume I**, hoy en **fase de experimentación** (§5.1),
con tres asistentes en marcha sobre corpus normativo real —uno público sobre normativa propia y dos internos de Gerencia, montados
para comparar dos métodos de recuperación—. El proyecto adoptó en agosto de 2026 la licencia
**AGPL-3.0-or-later** con licencia dual comercial; el repositorio sigue privado hasta la apertura
prevista, de modo que después cualquier institución pueda autoalojarlo.

## 2. Por qué es distinto: cinco decisiones estructurales

Estas cinco decisiones explican casi todo lo demás, y son las que sostienen la conformidad:

**Determinismo primero.** Si un resultado puede obtenerse con reglas, plantillas o extracción
estructurada, se obtiene así, y el modelo generativo se reserva para lo que el determinismo no
alcanza. Cuando el modelo interviene, la vía usada queda registrada. Un proceso determinista es
reproducible y explicable línea a línea; en actuación administrativa, la explicabilidad plena es
un requisito de legalidad, no una preferencia técnica.

**Ninguna afirmación sin fuente.** Los asistentes responden citando el fragmento concreto de la
norma que sostiene cada afirmación. Cuando el sistema no encuentra fundamento suficiente,
**responde que no lo tiene** en lugar de redactar algo plausible: la respuesta de indisponibilidad
es una función del sistema, no un fallo.

**El servidor es la única fuente de verdad.** La interfaz no contiene reglas de negocio: los
formularios y las acciones permitidas los decide el servidor y el cliente solo los dibuja. Esto
hace que el comportamiento del sistema esté descrito por un contrato versionado y auditable, y no
por lo que haga cada pantalla.

**Soberanía del dato por arquitectura, no por contrato.** La plataforma se despliega en dos modos.
En modo *cloud* todo corre en el servidor del proveedor, con disociación previa de datos
personales. En modo *edge + cloud* la lógica y los datos de la institución —conversaciones,
documentos, expedientes, vectores— viven **dentro de su propia infraestructura**, y la parte
central solo conserva configuración y métricas anonimizadas. Esa frontera está implementada en el
código (bases de datos separadas, módulos clasificados, pruebas que la vigilan), no solamente
declarada.

**Portabilidad deliberada.** Almacenamiento, base de datos y proveedor de modelos se cambian por
configuración, sin tocar código. La dependencia de un proveedor concreto es un riesgo de soberanía
y de competencia en la compra pública, así que se trata como tal.

## 3. Los módulos: lo que hay hoy

Cuatro módulos funcionales —asistentes, informes, automatización (los dos en §3.2, cada uno con
su menú y su módulo de acceso) y curación— y dos capacidades más pequeñas —agentes de unidad y
utilidades (§3.5)— sobre una base común (identidad institucional, pasarela de modelos multiproveedor, almacenamiento
portable, frontera edge/cloud):

### 3.1 Asistentes informativos

Chatbots multilingües (valenciano, castellano, inglés) sobre corpus documental propio, con
**citas trazables al fragmento de origen**. Incluye:

- **Búsqueda híbrida** (semántica y léxica combinadas) con **reordenación** de los resultados por
  un reordenador multilingüe de nube —verificado sobre valenciano— y **reescritura conversacional**
  de la consulta.
- **Segunda búsqueda cuando la primera no basta**: si el filtro de calidad rechaza lo recuperado,
  la consulta se traduce al vocabulario de la norma y se vuelve a buscar una sola vez. Se paga
  solo cuando hace falta —el 28 % de las consultas del asistente público y el 71 % de las del
  interno—, y existe porque una pregunta escrita como intención («quiero tramitar una compra de
  6.500 euros») no comparte ni una palabra con el texto que la regula.
- **Un umbral de calidad que decide con la mejor fuente**, no con el promedio de todas. Promediar
  hacía que la cola de resultados votara sobre si hay respuesta, y convertía un parámetro de
  amplitud en el mando que decidía cuántas preguntas se contestan.
- **Selección escalonada por metadatos**, en tres niveles: un índice de materias acota primero el
  ámbito, se elige el subconjunto pertinente y solo entonces se consulta. Evita que una pregunta de
  un área traiga fundamento de otra, y reduce lo que viaja al modelo.
- **Vigencia garantizada en la recuperación**: una sola versión canónica por documento, lo derogado
  fuera del índice consultable y aviso explícito cuando la norma aplicable ha sido desplazada. El
  desempate entre fragmentos equivalentes es determinista, para que la misma consulta cite siempre
  las mismas fuentes en el mismo orden.
- **Calidad medida, no supuesta**, en dos niveles que conviene no confundir. En **integración
  continua** hay una puerta que mide el *mecanismo* de recuperación —fusión híbrida, filtros,
  ranking— sobre un corpus de prueba con un embedding determinista: corre en segundos y falla si
  la exhaustividad o el orden empeoran más de 0,02 respecto a la línea base versionada. La calidad
  **sobre el corpus real** se mide aparte y a mano, con un lote de consultas reales que llevan el
  veredicto escrito por la persona que las hizo (§5).
- **Widget embebible** en webs institucionales y **modo identificado** para personal interno.
- **Preguntas frecuentes como contenido citable**, con autoridad propia frente al resto del
  corpus.
- **Vigencia del corpus**: cada documento lleva fecha de revisión prevista; cuando vence, el
  sistema lo señala. Una respuesta correcta sobre una norma derogada es un daño, no un acierto.

### 3.2 Informes y automatización

Generación asistida de informes a partir de documentos y hojas de cálculo reales:

- **Plantillas definidas por contrato**: el formulario de entrada de cada informe lo genera el
  servidor a partir de la plantilla, no está escrito en la interfaz.
- **Extracción determinista** de hojas de cálculo y PDF, con **transformación declarativa de
  datos**: veinte operaciones (limpieza, cálculo de columnas derivadas, conversión de importes
  escritos como texto, reordenación, pivotado) que se ejecutan sin generar código y se pueden
  mostrar al usuario antes de aplicarlas.
- **Once tipos de gráfico** deterministas con su presentación completa (título, etiquetas, cifras,
  orden), en formato numérico local.
- **Redacción asistida con revisión humana obligatoria** antes de que el informe se considere
  terminado, y **exportación a documento de oficina** con tablas e imágenes reales.
- **Manifiesto de ejecución**: cada informe registra qué modelo y qué versión de instrucciones
  intervinieron en cada apartado.
- **Ejecución aislada de código**: cuando un documento es tan irregular que requiere programar su
  lectura, el código se audita de forma determinista (tres niveles de severidad, con número de
  línea), lo revisa además un modelo supervisor, y se ejecuta en un **microservicio sin acceso a
  red** que vuelve a auditarlo antes de ejecutarlo. Ningún código de usuario corre en el proceso
  del servidor.
- **Catálogo de funciones, en su propio menú «Automatización»**: una extracción se escribe una vez,
  con su contrato y su declaración responsable, y las plantillas la referencian por versión. Se
  registra sin aprobación previa y se revisa después; las de origen externo —un cuaderno que corre
  fuera— se registran por su hash sin que la plataforma las ejecute (§6).

### 3.3 Curación de contenido

Módulo propio, porque la calidad del corpus es una cuestión de gobernanza y no de higiene técnica:

- **Rastreo de sitios web institucionales** y detección de patologías documentales: contenido
  obsoleto, sustituido, duplicado o contradictorio.
- **Informes de calidad** del corpus y exclusión registrada del contenido patológico.
- **Detección de huecos**: las consultas que el sistema no logra fundamentar alimentan una cola de
  revisión de contenido. El sistema dice qué documentación falta.
- **Publicación controlada** del contenido curado hacia el corpus de los asistentes.

### 3.4 Base común

Identidad institucional (**SSO SAML 2.0** con aprovisionamiento automático y tokens personales de
alcance limitado para clientes máquina), **personalización visual en cascada**
(plataforma → organización → asistente), **accesibilidad WCAG verificada en integración continua**,
**disociación de datos personales previa al envío al modelo** con cuatro modos graduados, y un
**servidor MCP** (16 herramientas) que permite administrar la plataforma desde agentes de IA con
confirmación humana en las operaciones sensibles.

A esa base se le añadieron en agosto de 2026 dos piezas que el modelo multiinstitución exigía:

- **Frontera entre organizaciones explícita.** Cada tabla declara a qué ámbito pertenece
  —plataforma, organización, heredable o derivada— y una prueba lo vigila. Proveedores, modelos,
  prompts y permisos dejaron de ser globales: un ayuntamiento puede escribir sus propias
  instrucciones sin tocar las de otro, y lo que no está definido a su nivel se hereda del
  superior. El inventario tabla por tabla está escrito y comprobado por prueba, no deducido.
- **Administración separada por planos**: la gestión de la plataforma (organizaciones, personas,
  módulos concedidos) se separó de la administración de cada asistente, con concesión de módulos
  a una persona o a un grupo del proveedor de identidad.

### 3.5 Agentes de unidad y utilidades

**Agentes de unidad.** Una unidad —contratación, calidad— publica un agente: un prompt, una carpeta
de documentos en el almacén de la organización y el colectivo que puede usarlo, sin escribir código.
La plataforma guarda un índice de fichas —enlace, título, resumen—, **nunca los documentos**; en cada
consulta selecciona los pertinentes y compone el prompt con sus enlaces. El agente es el asistente
general de la organización (Gemini), que abre los documentos con la cuenta de quien pregunta, y una
extensión del navegador hace de puente: inserta el prompt sin enviarlo y, en validación, devuelve
la respuesta para revisarla. Cada uso queda en el registro de actividad.

**Utilidades.** Unir, dividir y optimizar PDF, y anonimizar un CSV o un Excel para compartirlo:
lo que hoy se hace en webs que no aseguran la protección de datos. El fichero entra en la petición
y sale en la respuesta, sin guardarse, y sólo quedan metadatos del uso.

## 4. Arquitectura y despliegue

Monorepo con backend **FastAPI** (Python asíncrono, contrato OpenAPI como única fuente de verdad),
frontend **React** generado contra ese contrato, y **PostgreSQL con pgvector**. El detalle está en
`Arquitectura.md`.

El despliegue actual —«producción» en el sentido de infraestructura, no de fase de madurez: lo
que corre ahí es la experimentación de §5.1— es una **máquina virtual en Google Cloud Platform**
con Docker Compose, base de datos gestionada y almacenamiento de objetos. Se descartó una arquitectura sin
servidor porque el sistema tiene procesos de ingesta programados que no encajan con el escalado a
cero, y porque a igualdad de coste añadía restricciones. La aplicación pesa ~345 MB y cabe en una
instancia pequeña: los modelos de embeddings locales son una dependencia **opcional**, necesaria
solo cuando la institución exige que el cálculo no salga de su perímetro.

## 5. Estado de desarrollo y fase de madurez

### 5.1 En qué fase está, y qué exige la siguiente

La escala que usa este documento es la del **Reglamento de IA de la Universitat Jaume I**, y no
una propia. Tiene tres fases, y lo que las separa no es cuánto software hay construido sino
**quién usa el sistema y con qué datos**:

| Fase | Qué la define | Qué exige para entrar |
|---|---|---|
| **Experimentación** | Entorno controlado, datos sintéticos o públicos, sin audiencia abierta | Alta del uso y registro inicial |
| **Validación** | Audiencia limitada y real, con medición de calidad, sesgo y deriva del modelo | **Estudio de integración** aprobado |
| **Explotación** | Uso general y sostenido, incorporado a la operación de la institución | **Auditoría de seguridad independiente** e integración plena en el SGSI/ENS |

**Hoy el proyecto está en experimentación**, y lo que está pedido es el paso a validación. Es
importante no leer la tabla de más abajo como si dijera otra cosa: que una capacidad esté
construida y verificada **no la pone en fase de validación**. Un módulo funcionalmente completo
sigue en experimentación mientras no lo use gente real bajo un estudio de integración aprobado,
y la distancia entre las dos cosas es precisamente lo que la escala existe para no confundir.

Dos matices que conviene decir, porque en este proyecto no coinciden con lo que se supondría:

- **Hay ya un despliegue accesible desde internet** —`normativa.uji.es`, con dominio y
  certificado institucionales— y eso **no significa explotación**. Es el entorno donde se
  experimenta, sobre corpus normativo público y con un grupo reducido de personas.
- **Las fases se recorren por caso de uso, no por plataforma.** El asistente sobre normativa
  propia puede estar en validación mientras el módulo de informes sigue en experimentación. La
  clasificación de riesgo se hace en la misma unidad y por la misma razón
  (`MARCO_GOBERNANZA_IA.md` §6).

**Lo que el proyecto se compromete a que ocurra antes de cada salto**, y que la versión anterior
de este documento no decía:

- **Antes de validación**: estudio de integración aprobado, identidad institucional conectada
  (SSO SAML contra el IdP de la universidad, sin cuentas locales), y revisión técnica del código
  sobre un repositorio al que la institución tenga acceso.
- **Antes de explotación**: **auditoría de seguridad independiente**, con el precedente del voto
  electrónico. La versión anterior de este documento preveía pasar de la validación de pilotos
  al despliegue sin ese paso intermedio, y era una omisión: en un sistema llamado a ser la base
  sobre la que se construyan otros aplicativos de la institución, la auditoría no es un trámite,
  es lo que permite que los siguientes se apoyen en él. También es lo que sostiene la calidad
  percibida por otra administración que reutilice el código bajo la AGPL.

Como preparación de esa auditoría, la integración continua produce desde septiembre de 2026 el
**inventario de dependencias (SBOM)** de los tres árboles del proyecto —servidor, servidor MCP y
frontend—, el informe de vulnerabilidades conocidas de cada uno, y un escaneo de secretos que
pone el check en rojo cuando encuentra algo en el árbol de trabajo. Los informes de
vulnerabilidades **no bloquean todavía**: sobre cuatrocientas dependencias transitivas aparece
antes o después un aviso sin versión corregida publicada, y un guardarraíl que se pone rojo por
algo que quien lo lee no puede arreglar acaba desactivado. Primero medir, y con la medida, fijar
el umbral que bloquea.

Nada de esto sustituye a la auditoría: le ahorra el trabajo que una herramienta hace mejor, para
que mire lo que sólo mira una persona.

### 5.2 Lo construido y lo medido (26 de agosto de 2026)

El proyecto se ha desarrollado **en solitario**, con disciplina de desarrollo guiado por pruebas
(la prueba antes del código) y asistencia de agentes de programación sujetos a reglas de
arquitectura escritas y verificables.

**Cifras medidas.** La última ejecución completa de la suite de backend, el 25 de agosto, dio
**3.166 pruebas en verde**, una omitida y una en rojo —un guardarraíl de arquitectura, corregido
acto seguido; la suite completa no se ha vuelto a ejecutar después del arreglo, así que la última
sin ningún rojo es la del día anterior, con **3.107**—. En frontend, **661 pruebas en verde** el
26 de agosto. Desde el 22 de agosto la **integración continua ejecuta la suite entera**: hasta
entonces corría el 42 % de ella, y lo hace sin paralelismo a propósito, porque repartir las
pruebas entre procesos esconde el estado que se filtra de una a otra.

La verificación no es solo automática: cada módulo con interfaz se recorre en navegador antes de
darlo por cerrado, y las pruebas manuales humanas se reservan para lo que una máquina no puede
juzgar (identidad visual, calidad editorial, sistemas externos reales).

**Funcionalmente completo y verificado:**

| Área | Estado |
|---|---|
| Asistentes informativos con citas | ✅ En marcha sobre corpus real |
| Búsqueda híbrida, selección por metadatos y calidad medida | ✅ Puerta de regresión del mecanismo en integración continua; la calidad sobre el corpus real se mide a mano con el lote de consultas reales |
| Curación de contenido web | ✅ Módulo propio completo |
| Informes: plantillas, extracción, transformación, gráficos, exportación | ✅ Recorrido completo verificado de punta a punta |
| Ejecución aislada de código generado | ✅ Microservicio endurecido, doble auditoría |
| Identidad institucional (SSO SAML + tokens) | ✅ |
| Disociación de datos personales previa al modelo | ✅ Cuatro modos graduados |
| Frontera edge/cloud | ✅ Implementada y vigilada por pruebas |
| Accesibilidad WCAG | ✅ Puerta automática en integración continua |
| Personalización visual institucional | ✅ |
| Servidor MCP para administración asistida | ✅ 16 herramientas |
| Autoinstalación y distribución | ✅ Instalación en un paso, prerrequisito del software libre |
| Endurecimiento de seguridad | ✅ Tres rondas de auditoría cerradas, la última previa al despliegue |
| Frontera entre organizaciones | ✅ Ámbito declarado tabla por tabla, con inventario escrito y vigilado por prueba |
| Administración de plataforma e identidad | ✅ Organizaciones, personas y concesión de módulos, separadas de la administración de cada asistente |

**La experimentación, con datos reales.** El corpus normativo de la Universitat Jaume I está
cargado y clasificado por ámbito y materia:

| Asistente | Acceso | Corpus |
|---|---|---|
| Normativa propia | Público, sin identificarse | 297 documentos / 23.306 fragmentos |
| Gerencia — económico-administrativo | Personal identificado | 124 documentos / 14.198 fragmentos |
| Gerencia — selección de documentos completos (pruebas) | Personal identificado | 127 documentos / 14.208 fragmentos |

Los dos últimos comparten corpus a propósito: existen para comparar **dos métodos de
recuperación** sobre el mismo material. Los embeddings y la reordenación se calculan por API del
proveedor de nube, con adaptador propio y proceso por lotes; los modelos locales siguen siendo una
dependencia opcional para quien exija que el cálculo no salga de su perímetro.

El **sitio de publicación del corpus** —portada, buscador y una página por norma con sus anclas—
está construido y hace de anfitrión del asistente público: quien lee una norma puede preguntar
sobre ella sin salir de la página, y la cita de la respuesta abre el artículo concreto.

**Qué dice la medición del asistente.** Se ha medido con **25 consultas reales del ensayo del
sistema anterior**, cada una con el veredicto escrito por la persona que la hizo, y con las
**7 consultas reales** que el personal de Gerencia hizo a su asistente. Los resultados, y esto es
lo que hay que leer con cuidado:

- El asistente público **contesta 22 de 25** consultas, frente a 18 antes del último bloque de
  trabajo. Contestar no es acertar: con la rúbrica del informador y un juez automático,
  **cumplen 9 de 25**. La distancia entre ambas cifras es el trabajo que queda.
- El asistente interno de Gerencia **contesta 6 de 7**. Su gemelo de pruebas contesta 7 de 7,
  pero **no porque recupere mejor**: su método no puntúa lo que recupera, así que su filtro de
  calidad no puede rechazar nada. Cuál de los dos acierta más lo tiene que decir Gerencia, y para
  eso hay una hoja de validación a ciegas ya generada y pendiente de sus veredictos.
- El defecto dominante del sistema anterior era **citar el curso académico equivocado** —15 de las
  25 consultas—, y eso ordena la configuración actual: se prefiere un contexto estrecho y limpio a
  uno amplio que mezcla normas de cursos distintos.

El detalle, con la configuración de cada asistente y la tabla consulta a consulta, está en
[`docs/mediciones/`](mediciones/README.md) — en particular el cierre del bloque HIB y la
configuración de apertura del piloto, cada una con su fecha.

**Lo que queda para entrar en fase de validación.** Los dos puntos de infraestructura que esta
lista tenía —desplegar en producción y publicar el sitio del corpus— **están hechos** desde el 31
de agosto y el 2 de septiembre de 2026 respectivamente. Lo que queda no es técnico:

1. **Estudio de integración aprobado.** Es el requisito de entrada a la fase, y el mecanismo por
   el que la institución decide alcance, riesgo y responsable (§7.1).
2. **Identidad institucional conectada.** El SSO SAML está implementado y no está enchufado al
   IdP de la universidad; mientras tanto se entra con cuentas locales de la propia plataforma,
   que es aceptable en experimentación y no lo es con audiencia real.
3. **Repositorio en la organización de la universidad**, que es el prerrequisito de cualquier
   revisión técnica del código por parte de la institución.
4. **Validación humana de los asistentes de Gerencia**: la hoja está generada; faltan los
   veredictos, y de lo que marquen saldrán las pruebas de regresión.
5. **Lote de consultas de referencia para Gerencia**: siete preguntas no son una medida. El
   mecanismo de carga es el mismo que ya se usa con el asistente público.
6. **Instrumentación de la medida que la fase exige**: calidad, sesgo y deriva del modelo sobre
   uso real. Hoy la calidad se mide a mano con lotes de consultas anotadas; sesgo y deriva no se
   miden todavía, porque necesitan volumen de uso que la experimentación no da.

El punto 6 es el que conviene no minimizar: es la única obligación de la fase de validación para
la que **no hay mecanismo construido**, y por eso está aquí y no en la tabla de arriba.

## 6. Lo que viene

Las dos líneas que siguen se replantearon el 23 de septiembre de 2026, y lo que cambió no fue el
plazo sino el alcance; la primera ya está construida y desplegada. Merece explicarse, porque el motivo vale para cualquier administración que
se plantee lo mismo: **en los dos casos habíamos previsto construir una pieza que ya existe fuera,
y lo que de verdad faltaba era la gobernanza alrededor.** El detalle, con sus hitos y sus issues,
está en `ROADMAP.md`.

**Automatización gobernada.** La previsión era un cliente ligero instalable en el puesto de
trabajo que ejecutara automatizaciones y capturas de pantalla. Se descarta: los agentes de
propósito general con acceso al navegador y al escritorio ya hacen eso, y además lo hacen en el
régimen que las normas de desarrollo ciudadano reservan al uso personal, en el equipo de la
persona y con sus credenciales. Lo que no dan, y lo que una institución necesita en cuanto una
automatización se comparte, es saber **cuáles circulan, quién las usa y con qué versión**. Es lo
que se construyó, y está desplegado en el menú «Automatización»: un cuaderno se registra por su
hash con su declaración responsable sin que la plataforma lo ejecute, las funciones de tarea
producen ficheros de salida y sólo salen a la red hacia orígenes declarados, un agente puede pasar
el código por la auditoría estática y el texto por la anonimización antes de enviarlo a un modelo,
y cada uso queda en el registro de actividad. **No hay cliente de ejecución local, y no lo habrá.**

**Trámites asistidos con IA.** La previsión era un gestor de expedientes completo. Se descarta por
la misma razón: las administraciones ya tienen uno, y es la fuente de verdad del procedimiento
—sus fases, su estado, quién firma, la notificación, la evidencia de interoperabilidad—. Lo que
falta no es otro gestor sino **fases concretas asistidas**: baremar, redactar un informe técnico,
redactar una resolución, con las mismas garantías del módulo de informes. Un trámite se crea a mano
en la plataforma o lo crea el gestor por API, y el resultado —documento, datos y evidencia— vuelve
al expediente. **La plataforma no cambia nunca el estado del procedimiento**: valida contenido, no
resuelve. Que esa frontera esté escrita es lo que evita gestionar lo mismo desde dos sitios.

Y conviene decirlo aquí y no descubrirlo después: los trámites asistidos **sí tocan actuación
administrativa**, y una baremación evalúa a personas, así que no heredan la clasificación de riesgo
de los asistentes informativos. Tendrán que recorrer el procedimiento desde el principio, con su
propia clasificación y, si esa clasificación lo exige, con evaluación de impacto en la protección
de datos, **antes de que entre ningún dato real**. Los asistentes de hoy no la necesitan porque
informan citando norma publicada; ése es el motivo, y deja de valer en cuanto el sistema participa
en una decisión. De ahí una regla que ya está fijada: en una baremación el modelo extrae hechos y
redacta la motivación, pero **no puntúa nunca** —los hechos los verifica una persona y la
puntuación la calcula una función determinista con el baremo como dato versionado—.

**Hitos orientativos, en la escala de §5.1**: entrada en **validación** de los asistentes
informativos durante el cuarto trimestre de 2026, sujeta al estudio de integración; apertura del
repositorio público en la misma ventana; **explotación** no antes de que exista auditoría de
seguridad independiente; trámites asistidos en experimentación durante 2027-2028. La
automatización gobernada está construida y en producción; su primer agente de unidad, el de
pliegos para grupos de investigación, ha pedido la entrada en la fase de experimento del Teclab.

Las fechas son orientativas y las dependencias no: ninguna de ellas depende sólo del desarrollo,
y decirlas como si fueran hitos de ingeniería sería confundir lo que uno controla con lo que no.

## 7. Dos planos de gobernanza, y dónde acaba esta plataforma

Conviene ser explícito sobre el alcance, porque la gobernanza de la IA en una administración se
juega en **dos planos distintos** y confundirlos lleva a esperar de una herramienta cosas que una
herramienta no puede dar.

**Plano institucional (superior).** El inventario de casos de uso de IA de la organización, su
registro, la clasificación de riesgo de cada uno, la designación del órgano responsable de la
actuación automatizada, la intervención del delegado de protección de datos, las evaluaciones de
impacto, la aprobación del alta de un uso nuevo y su revisión periódica. Son decisiones de
gobierno y actos administrativos: dependen de personas y órganos con competencia, no de una
comprobación en código.

**Plano de la herramienta.** Lo que un sistema puede garantizar por diseño y demostrar por
construcción: que el resultado se obtiene por la vía más verificable disponible, que ninguna
afirmación se emite sin fuente, que existe un punto de supervisión humana instrumentado, que cada
ejecución deja registro de qué modelo y qué fuentes intervinieron, que los datos personales se
disocian antes de salir del perímetro, que el dato no cruza fronteras que no debe cruzar.

**Gov Gen AI Platform cubre el segundo plano, y no el primero.** No mantiene el inventario de casos
de uso ni el registro de sistemas de IA, y no está previsto que lo haga: esa función se gestiona
**al margen de la plataforma**, con aplicaciones y procedimientos propios, igual que la asignación
de responsabilidades. Es una decisión de alcance deliberada, no una carencia pendiente de
desarrollo: un inventario institucional debe abarcar *todos* los sistemas de IA de la
organización, incluidos los que no pasan por esta plataforma, así que alojarlo dentro de una de
las herramientas que debe inventariar sería un error de diseño.

La relación entre ambos planos es de doble sentido, y es el punto de encuentro con una plataforma
orientada al registro:

- **Del plano superior a la herramienta**: las decisiones de gobierno se traducen en
  configuración —qué modelo se asigna a cada actividad, qué modo de disociación se aplica, dónde
  hay puertas de revisión humana, qué umbrales de calidad—. La plataforma es donde esas decisiones
  se ejecutan y se hacen efectivas.
- **De la herramienta al plano superior**: la plataforma produce la evidencia con la que el registro
  se sostiene ante una auditoría. El registro declara qué se hace; la evidencia de ejecución
  demuestra qué se hizo.

Cómo se conecten ambos planos —qué campos describen un uso de IA, cómo se codifica la
clasificación de riesgo, cómo se referencia el órgano responsable— es una decisión de gobernanza
sectorial que conviene tomar de forma compartida, y no algo que deba resolver por su cuenta cada
herramienta. El marco de gobernanza del proyecto (`MARCO_GOBERNANZA_IA.md`) desarrolla esta
distinción de planos y detalla qué obligaciones vive en cada uno.

### 7.1 El mecanismo que conecta los dos planos

Decir que hay dos planos y no decir por dónde se tocan deja el documento a medias, y era el hueco
de la versión anterior. La conexión no la inventa la plataforma: **la pone la institución, y es
un procedimiento administrativo**. En la Universitat Jaume I, que es el primer despliegue, se
llama **estudio de integración** (Annex II, sección 5.1 del Reglamento de IA), y funciona como
puente de doble sentido:

- **Alta y registro inicial.** Cualquier uso de la plataforma, institucional o particular,
  requiere una petición que recoja objetivo, alcance, beneficio, coste estimado de recursos,
  parámetros técnicos y la lista de herramientas empleadas. Es lo que hace que un uso exista para
  la organización antes de existir en un servidor.
- **Graduación por riesgo y madurez.** El estudio define en qué fase entra el caso de uso y con
  qué controles. Los de bajo riesgo pueden resolverse con declaración responsable, para que el
  procedimiento no se coma la experimentación que dice querer fomentar.
- **Evaluación por el órgano competente** —en la UJI, el comité de estrategia digital e
  inteligencia artificial, bajo la coordinación del delegado del rector como responsable
  institucional de IA— en los casos de impacto significativo o de información no pública, con el
  informe de auditoría que corresponda.

**Qué aporta la plataforma a ese procedimiento, y qué no.** Aporta las dos cosas que un
expediente de este tipo no puede fabricar por sí mismo: los **parámetros técnicos** verificables
—modelos, umbrales, modos de disociación, fronteras de datos, dónde hay revisión humana— y la
**evidencia de ejecución** que después demuestra que se hizo lo que se declaró. No aporta, ni
debe, la decisión de si un uso se autoriza, en qué fase entra o quién responde de él.

Este patrón no es específico de una universidad. Cualquier administración que despliegue la
plataforma necesitará su equivalente —un procedimiento propio de alta, clasificación y
autorización de casos de uso— y la plataforma está construida para alimentarlo, no para
sustituirlo.

### 7.2 Lengua: qué decide la institución y qué ejecuta la plataforma

Es un caso pequeño que ilustra bien el reparto, y en un contexto con lengua propia no es menor.

La plataforma **no decide** en qué lengua se atiende: lo ejecuta. La política es configuración en
cascada —plataforma, organización, asistente— con tres modos: responder en la lengua de la
pregunta, no aplicar política, o **fijar una lengua** con independencia de cómo se pregunte
(`server/app/core/language_mode.py`). Una institución cuya normativa establezca una lengua por
defecto la fija ahí, y no hay que tocar código.

Lo que sí es del plano institucional, y conviene no confundirlo con lo anterior, es **qué cuenta
como publicación oficial**. Una respuesta conversacional a una consulta no es una publicación: se
genera para quien pregunta, cita su fuente y no queda como texto de la institución. Un documento
publicado sí lo es, y donde exista un servicio lingüístico con competencia sobre las traducciones
—en la UJI, el Servei de Llengües i Terminologia— la supervisión previa le corresponde a él. En
el corpus normativo esa línea ya está trazada: las traducciones automáticas viven aparte y
**alimentan sólo la búsqueda**; el texto que se publica es el aprobado.

## 8. Licencia y distribución

**AGPL-3.0-or-later**, adoptada en agosto de 2026 con la Universitat Jaume I como titular. Es la
única licencia bajo la que el programa se distribuye hoy; lo que se contrata, si una
administración necesita garantías o acompañamiento, son **servicios** —despliegue, adaptación,
soporte, formación, corpus—, que la licencia permite expresamente. La planificación de enero de
2026 previó además una **licencia dual comercial** para *partners*: sigue siendo posible —la
titularidad es de una sola persona jurídica, que es lo que técnicamente lo permite— y **no se ha
ejercido**. La autoinstalación en un paso ya está resuelta, que era el
prerrequisito real de la distribución: un proyecto que no se puede instalar sin su autor no es
software libre en la práctica. El objetivo es que otra administración pueda levantar la plataforma
en su propia infraestructura, con su corpus y su identidad visual, sin depender del equipo
original.

Dos consecuencias de esa licencia ya están implementadas, y no son trámite: **la procedencia de
cada aportación se certifica** en el propio historial —una comprobación automática rechaza lo que
no la lleve, y la regla se aplica también al mantenedor, porque quien se exceptúa de su política
la deja sin fuerza— y **el enlace al código fuente que exige el artículo 13 de la AGPL lo publica
el servidor y lo enseñan las dos interfaces**: sale de un endpoint público, tomado de la
configuración de cada despliegue y no de una URL fija que haría incumplir a todo fork
modificado, y se pinta en el pie del panel y en el del widget embebido —que es el caso que se
olvida, porque la ciudadanía que escribe en un chatbot puesto en la web de un ayuntamiento
también usa el programa por red—.

El repositorio permanece privado hasta la apertura prevista.

## 9. Cómo verlo

El punto de entrada recomendado para una demostración es el asistente sobre normativa propia
—porque enseña las citas trazables y la respuesta de indisponibilidad, que es lo que más cuesta
creer sin verlo— seguido de la generación de un informe a partir de una hoja de cálculo real, que
enseña el determinismo y la revisión humana en el mismo recorrido.

El asistente se enseña mejor **dentro del sitio de publicación del corpus** que en una pantalla de
administración: se abre el buscador de normativa, se pregunta desde la propia norma que se está
leyendo, y la cita de la respuesta abre el artículo exacto. Ese recorrido enseña de una vez las
tres cosas que distinguen al sistema —fuente verificable, apertura por el artículo y aviso cuando
la norma aplicable ha sido desplazada— sin pedirle a nadie que se fíe.

## 10. Documentación disponible

| Documento | Qué contiene |
|---|---|
| `docs/ESPECIFICACIONES.md` | Qué garantiza el sistema, capacidad por capacidad, con sus invariantes y dónde se hace cumplir cada uno. El documento para quien va a escribir código |
| `docs/Arquitectura.md` | Arquitectura funcional y técnica **como está construida**: módulos, roles, las dos fronteras, datos, recuperación, despliegue y decisiones estructurales |
| `docs/INSTALACION.md` | De clonar a un sistema que responde, con la elección de modelos locales o por API |
| `docs/GUIA_DE_USO.md` | Qué hace cada rol con la plataforma ya instalada, módulo a módulo |
| `docs/MARCO_GOBERNANZA_IA.md` | Marco normativo interno: principios de gobernanza, mecanismos que los implementan, evidencia generada y clasificación de riesgo por caso de uso |
| `docs/mediciones/` | Las mediciones fechadas del piloto: anchura de la recuperación, por qué el asistente no contesta, cuánto contexto conviene inyectar y qué decidió cada valor de apertura |
| `docs/MULTITENENCIA.md` | Inventario del ámbito tabla por tabla: qué es de la plataforma, qué de cada organización y por qué camino se llega a ella |
| `docs/METODOLOGIA_AGENTICA.md` | Cómo se desarrolla: ejecución por bloques, verificación en navegador y qué se reserva al juicio humano |
| `docs/CONTRATO_MD_CORPUS.md` | Contrato del material que entra al corpus, y el pipeline de curación que lo produce |
| `docs/DESPLIEGUE_PROTOTIPO_GCP.md` | Plan del despliegue del piloto: piezas, orden, variables y riesgos |
| `planificacion/PLAN_DESARROLLO.md` | Plan de desarrollo del conjunto y decisiones durables (licencias, stack, identidad) |
| `docs/VALORACION_PROYECTO.md` | Auditoría global del proyecto: calidad, seguridad y sentido de producto |
| `docs/SANDBOX_SECURITY.md` | Aislamiento de la ejecución de código |
| `docs/REDACCION_CONTRACT_FIRST.md` | Contrato del módulo de informes |
| `docs/A11Y_CHECKLIST.md` | Verificación de accesibilidad |
| `planificacion/PROJECT_STATE.md` | Estado vivo del desarrollo, al día |
| `planificacion/HISTORIAL.md` | Por qué cada cosa se hizo como se hizo: desviaciones, defectos encontrados al verificar y decisiones con su razón |

---

*Contacto y demostración: Modesto Fabra (fabra@uji.es), Universitat Jaume I.*
