# Arquitectura de Gov Gen AI Platform

> **Clase: referencia viva.** Describe la plataforma **como está construida**, no como se
> proyectó. Si contradice al código, es un fallo de este documento y hay que arreglarlo.
>
> **Revisión completa: 2026-09-19.** La versión anterior era el documento de estado objetivo de
> enero de 2026, escrito antes de integrar los dos proyectos de origen, y para entonces afirmaba
> cosas que habían dejado de ser ciertas —Docling en la ingesta, Bitbucket Pipelines, un
> `local-runner/` en el árbol, módulos que no existen— mientras callaba tres módulos construidos.
> §17 cuenta qué se corrigió y por qué se reescribió en lugar de parchearse.
>
> **Qué NO está aquí.** Las **garantías** del sistema, capacidad por capacidad, con sus
> invariantes y dónde se hacen cumplir: [`ESPECIFICACIONES.md`](ESPECIFICACIONES.md) —el
> documento para leer antes de escribir código—. Las **reglas duras** que obligan a un agente de
> programación: [`../AGENTS.md`](../AGENTS.md). El **estado del desarrollo**:
> [`../planificacion/PROJECT_STATE.md`](../planificacion/PROJECT_STATE.md). Este documento
> explica **la forma del sistema y por qué tiene esa forma**.

---

## 1. Para qué existe esta arquitectura

La plataforma tiene que servir a **varias administraciones distintas** sin que ninguna vea los
datos de otra, y tiene que poder desplegarse **dentro de la nube de la institución** cuando el
requisito regulatorio no admite otra cosa. Casi todo lo que sigue sale de ahí.

Un sistema hecho para una sola institución no necesitaría la jerarquía Plataforma → Organización
→ Chatbot, ni dos bases ORM separadas, ni una clasificación de routers en `cloud` y `edge`
vigilada por tests. Las tendría como lujo. Aquí son el requisito.

El segundo motor del diseño es la **conformidad por diseño**: las obligaciones jurídicas
—Reglamento (UE) 2024/1689, RGPD, Leyes 39/2015 y 40/2015, ENS— no se documentan aparte del
sistema, se incorporan a su construcción y se traducen en comprobaciones ejecutables. De ahí
salen decisiones que de otro modo parecerían caprichos: que el determinismo se prefiera al modelo
generativo siempre que alcance, que ninguna afirmación se emita sin cita a su fuente, y que la
respuesta de indisponibilidad sea una función del sistema y no un fallo. El desarrollo del
principio está en [`MARCO_GOBERNANZA_IA.md`](MARCO_GOBERNANZA_IA.md).

---

## 2. La regla que ordena el diseño: el servidor decide, el cliente pinta

Es la restricción de la que se derivan las demás, y está escrita como regla maestra en
`AGENTS.md`:

- El frontend **no calcula qué acciones están permitidas**. No hay código como
  `if (fase === 'revision') mostrarBoton()`. El servidor evalúa estado y rol y manda la lista
  —`acciones_permitidas` cuando exista el gestor de expedientes, banderas por fila en lo que hay
  hoy—; React itera sobre ella.
- El frontend **no conoce a priori los campos** de un formulario de función o de script. Recibe
  un contrato de interfaz y construye el formulario iterando sobre él (*server-driven UI*).
- El frontend **no define tipos de datos a mano**: salen del contrato OpenAPI vía Orval, y un
  trabajo de CI se pone rojo si el cliente generado no cuadra.

La razón no es purismo. Una regla de negocio duplicada en dos lenguajes divergirá, y cuando
divergen **el cliente es el que miente**, porque es el que el usuario ve. Con esto hay un solo
sitio donde una regla puede estar mal.

---

## 3. Principios transversales

### 3.1 Determinista primero

Donde un cálculo puede hacerse con código, se hace con código. El modelo generativo entra donde
hace falta lenguaje: redactar una valoración, proponer una transformación, explicar un hallazgo.

En el módulo de Informes eso es literal: las tablas de un informe las produce una función
determinista y versionada, y lo que escribe el modelo es la **valoración** que acompaña a esa
tabla, sujeta a aprobación humana. Un número que aparece en un informe institucional no sale de
un modelo de lenguaje.

### 3.2 La supervisión humana es estructura, no aviso

No hay un *banner* que diga «revise los resultados». Hay estados en la base de datos que no
avanzan sin que alguien los avance, y registro de quién lo hizo. El borrador de un informe no se
exporta sin aprobación; un documento del corpus tiene cola de vigencia y constancia de quién la
comprobó; una función compartida pasa por revisión posterior que puede pedir correcciones,
reclasificar o suspender.

### 3.3 El contrato es la fuente de verdad

`openapi.json` lo genera el servidor; el cliente TypeScript se deriva de él. No se escribe a
mano. La validación del formulario en el cliente se alinea con el contrato del servidor
(`react-hook-form` + `zodResolver`), no lo reinterpreta.

### 3.4 Conformidad como código

Cada garantía que el sistema promete tiene un sitio donde se hace cumplir y un test que lo
comprueba. La tabla de invariantes de `ESPECIFICACIONES.md` §4 es literalmente esa lista, con la
columna «se hace cumplir en». Un invariante que sólo vive en un documento no es un invariante: es
una intención.

### 3.5 Multiorganización desde la primera tabla

Toda tabla de configuración declara a quién pertenecen sus datos, y una que no lo declare pone
rojo un guardarraíl. No es una capa que se añade: es una columna que se decide al crear la tabla.
El inventario está en [`MULTITENENCIA.md`](MULTITENENCIA.md).

---

## 4. Las dos fronteras

Condicionan cualquier código nuevo. Son independientes entre sí y se confunden con facilidad.

### 4.1 Cloud / Edge — qué puede salir de la institución

El sistema se despliega de dos maneras con **el mismo código**:

| Modo | Dónde corre la lógica que toca datos del cliente | Qué guarda el cloud |
|---|---|---|
| **Cloud-only** | En el servidor del proveedor. Los datos se anonimizan antes de llegar al modelo. | Todo. Protección de datos por contrato. |
| **Edge + Cloud** | En un *edge node* dentro de la nube de la institución. | Sólo configuración administrativa y métricas anonimizadas. |

Lo que sostiene la frontera, y no es una promesa contractual sino código:

- **Dos `DeclarativeBase` separadas.** `HubConfigBase` (14 modelos) es configuración y se
  sincroniza cloud→edge. `HubOperationalBase` (24 modelos: 15 de `agents_hub` y 9 de
  `redaccion`) son datos del cliente y viven sólo en el edge. **Sin `relationship()` que las cruce**: si un servicio operacional necesita un
  chatbot, consulta por `chatbot_id`; no navega por `.chatbot`. Las FK con `ondelete="CASCADE"`
  se conservan, la navegación ORM no.
- **`DEPLOY_MODE`** (`cloud` | `edge` | `all`, por omisión `all`) decide qué routers se registran
  en el arranque. `server/app/main.py` los reparte en `_register_cloud` (16 routers) y
  `_register_edge` (22). Un router nuevo se etiqueta en su docstring —`Deploy: cloud|edge|shared`—
  y se registra en una de las dos funciones o en las dos.
- **Un módulo edge no importa desde un módulo cloud.** La configuración se lee por
  `ConfigProvider` (`modules/agents_hub/services/config_provider.py`), no importando modelos de
  configuración. Lo comprueba `test_ais3_direccion_de_los_imports.py`.
- **`edge_sync_router`** (`/api/v1/edge/config`, `/api/v1/edge/telemetry`) es la única superficie
  que ve los dos mundos. Está servida por el cloud y consumida por el edge.
- **La anonimización previa al LLM es responsabilidad del edge.** `model_factory` recibe datos ya
  anonimizados; no anonimiza.

Qué está en cada lado: los grafos de LangGraph, el *task runner*, la ingesta, la recuperación,
`modules/redaccion/` y `modules/automation/` íntegros son **edge**, porque tocan documentos y
expedientes del cliente. La gestión de organizaciones, chatbots, modelos, prompts, temas,
personas y tokens es **cloud**, porque es configuración. Si algo toca las dos cosas, casi siempre
hay que partirlo en dos servicios.

### 4.2 Organización — quién puede ver qué

Toda tabla de `HubConfigBase` declara su ámbito en `__ambito__`, y hay **cuatro**:

| Ámbito | Qué significa | Columna |
|---|---|---|
| `plataforma` | Una sola configuración para la instalación entera. | — |
| `organizacion` | Siempre de una organización. | `organizacion_id` NOT NULL |
| `heredable` | **Nulo = de la plataforma, y se hereda.** | `organizacion_id` nullable |
| `derivada` | La organización se alcanza por otra tabla. | la que diga `via` |

Son cuatro y no tres porque varias tablas llegan a su organización por otra tabla
(`hub_prompt_templates` por su chatbot), y meterlas en «de organización» diría que tienen una
columna que no tienen.

**Dos capas que no se confunden**, y es el error más fácil de cometer aquí:

- `core/auth/tenancy.py` decide **quién puede ver qué** —403 y acotación de listados—. Recibe un
  principal.
- `core/ambito.py` decide **qué fila gana** cuando la configuración está puesta en dos niveles.
  No recibe principal. Resuelve **campo a campo**, no fila entera: con reemplazo de fila, una
  organización que quisiera cambiar un color tendría que repetir la configuración completa.

El objetivo de diseño, dicho en concreto: **que una Diputación pueda desplegar una instancia para
varios municipios**. Lo que no es: esto no convierte la instalación en multiinstancia. Sigue
siendo una base de datos con organizaciones dentro; la separación **física** es el modo edge.

---

## 5. Los módulos

Ficheros versionados el 2026-10-05, para dar escala. Lo que importa de estas cifras es que
`redaccion/` es casi tan grande como `agents_hub/` y que `automation/` no es un módulo, son cinco
ficheros.

| Módulo | Backend | Frontend | Qué es |
|---|---|---|---|
| `agents_hub` | 111 | `admin/` 65 · `widget/` 6 | Asistentes, corpus, ingesta, recuperación, evaluación |
| `redaccion` | 104 | `redaccion/` 56 · `automatizacion/` 2 | Informes, plantillas, funciones, scripts, anonimización |
| `curation` | 31 | `curation/` 27 | Rastreo de portales, hallazgos, publicación |
| `agentes` | 10 | `agentes/` 17 · `extension/` 13 | Agentes de unidad: catálogo, índice de fichas, consulta |
| `utilidades` | 3 | `utilidades/` 8 | PDF y anonimización de un fichero, sin guardar nada |
| `automation` | 5 | — | Infraestructura que consume Informes; **no es módulo de usuario** |

El código del catálogo de funciones sigue en `redaccion/` —servicios y páginas—, aunque desde el
2026-10-05 se sirve en su propio menú, «Automatización» (`/automatizacion`, módulo
`automatizacion`). `extension/` está en la raíz del repositorio, no en `frontend/`.

### 5.1 Chatbots — `modules/agents_hub/`

Asistentes que responden sobre la normativa de una organización **citando la norma**, y que
**callan** cuando no tienen fundamento. Publicables como widget embebible en una web ajena o
como agente identificado dentro del panel.

Un `CoreGraph` de LangGraph con cuatro **estrategias enchufables por eje**: recuperación, fusión,
plantilla de respuesta y política de lengua. Los perfiles públicos y qué hace cada uno:
[`GRAPH_PROFILES.md`](GRAPH_PROFILES.md).

Dos modos de recuperación en uso: `RAG` —híbrido vectorial + texto completo, con desempate
determinista— y `MD_AGENT_SELECTOR`, donde el modelo lee documentos enteros con *tools*. Detalle
en §9.

### 5.2 Informes — `modules/redaccion/`

Abarca más de lo que su nombre sugiere: sirve a las fases de cualquier expediente, no sólo a un
documento suelto. Su contrato completo está en
[`REDACCION_CONTRACT_FIRST.md`](REDACCION_CONTRACT_FIRST.md).

Las piezas: contratos de plantilla, extracción determinista de PDF (`pdfplumber`) y hojas de
cálculo, transformación declarativa de datos, gráficos, `DraftingCoreGraph` para la redacción
asistida, `LLMSpecService` y un `RunManifest` firmado que deja constancia de qué produjo cada
ejecución.

Cuando un documento es tan irregular que hay que **programar su lectura**, ese código pasa por
auditoría estática graduada (aceptable / advertencia / crítico, con número de línea) y se ejecuta
en un **sandbox sin red** —`services/script_sandbox`, un microservicio aparte—. El filtro es
automático; la persona entra después, en la revisión posterior. El catálogo de funciones
compartidas y sus tres niveles: [`CATALOGO_FUNCIONES.md`](CATALOGO_FUNCIONES.md); su pantalla
está en el menú «Automatización», no en Informes (§5.6).

### 5.3 Curación — `modules/curation/`

Es **previa** al asistente, y por eso es módulo propio y no una utilidad del RAG
([`DECISION_CURACION_SEPARADA.md`](DECISION_CURACION_SEPARADA.md)): rastrea el portal
institucional, detecta contenido caducado o contradictorio, y sostiene la decisión de qué entra
al corpus.

**Curación una vez, automatización después.** No hay ingesta automática **de nada que nadie haya
aprobado**; hay **mantenimiento automático dentro del ámbito que una persona aprobó una vez**, que
es lo que añadió el bloque DIN: un apartado del portal —jornadas, becas— nace en modo `manual` y
pasa a `automatic` a mano, y mientras está en `manual` una baja deja un aviso y no toca el corpus.
Una página nueva fuera de ese ámbito es una señal para quien cura, no
un disparador. La salida principal es el informe de auditoría, que vale por sí solo sin que haya
ningún chatbot detrás; la higiene del corpus es el efecto secundario.

Los apartados de un sitio son parametrizables y tienen ciclo de vida propio:
[`SECCIONES_DINAMICAS.md`](SECCIONES_DINAMICAS.md). Con varias organizaciones:
[`CURACION_MULTIORGANIZACION.md`](CURACION_MULTIORGANIZACION.md).

### 5.4 `automation`, que no es un módulo de usuario

Cinco ficheros —`cortex.py`, `extraction_strategies.py` y el `llm_gateway` de
`infrastructure/`— que consume Informes. **No tiene routers registrados ni interfaz.** Lo que la
planificación llamaba «automatización» aterrizó en `redaccion/`, y es la ruta que más veces se
escribe de memoria y no existe.

### 5.5 Registro de actividad y verificaciones

Dos capacidades que la plataforma ofrece **hacia fuera**, para aplicaciones desarrolladas por
otros equipos de la institución:

- **Registro de actividad IA** —`routers/actividad_router.py` y `core/actividad_categorias.py`—:
  una herramienta de fuera declara que ha usado IA y queda registrada. Metadatos sí, *payloads*
  no. Detalle en [`REGISTRO_ACTIVIDAD_IA.md`](REGISTRO_ACTIVIDAD_IA.md).
- **Verificaciones como servicio** —`routers/verificaciones_router.py`—: comprobar citas,
  vigencia y auditoría estática por API, con *scope* propio.

Su «módulo» no es un paquete Python: es una fila de `hub_platform_modules`, o sea una unidad de
licencia. Qué comprueba y registra la plataforma, y qué de ello es accesible por API:
[`GOVERNANCA_PER_API.md`](GOVERNANCA_PER_API.md).

### 5.6 Automatización gobernada — el menú «Automatización»

No es un ejecutor de flujos: es **gobernar** las automatizaciones que circulan —qué hay, quién
las usa, con qué versión—. Su núcleo es el catálogo de funciones, con tres orígenes por el mismo
contrato: *autoservicio* (el código vive en el catálogo y corre en el sandbox), *paquete* (llega
por *entry point* desde el repositorio de un equipo) y *externa* (un cuaderno o un guion que
corre fuera se **registra por su hash, sin ejecutarlo**). Las funciones de tarea añaden
artefactos de salida y red saliente sólo hacia orígenes declarados. El código sigue en
`modules/redaccion/funciones_*.py` y en `routers/redaccion/funciones_router.py` y
`funciones_run_router.py`; la pantalla es `/automatizacion`, con el módulo `automatizacion`.
Contrato: [`CATALOGO_FUNCIONES.md`](CATALOGO_FUNCIONES.md).

**No hay agente de ejecución local, y es una decisión** (2026-09-23), no un hueco: ni RPA, ni
vigilancia de carpetas, correo o web, ni programador de flujos locales, ni *thin client*. Lo
cubren los agentes de propósito general; la plataforma aporta la gobernanza
([`ESPECIFICACIONES.md`](ESPECIFICACIONES.md) §10). Lo que hubo en el cliente NiceGUI, retirado
el 2026-09-04, está fichero a fichero en
[`INVENTARIO_RETIRADA_LEGACY.md`](INVENTARIO_RETIRADA_LEGACY.md).

### 5.7 Agentes de unidad — `modules/agentes/` y `extension/`

Una unidad publica un **agente**: un prompt, una carpeta de documentos en el almacén de la
organización y un colectivo que puede usarlo. Ninguna de las tres cosas es código. El reparto es
lo que define la arquitectura:

- **La plataforma selecciona y compone.** Guarda un **índice de fichas** —URL, título, resumen,
  vigencia— y, en cada consulta, elige los documentos y compone el prompt con los enlaces y una
  instrucción de abstención. **Nunca guarda los documentos**: el vector de cada ficha se hace sólo
  del título y el resumen.
- **El asistente general es el agente.** Gemini abre los documentos en Drive **con la cuenta de
  quien pregunta**: la plataforma selecciona y el almacén autoriza, dos puertas independientes.
- **La extensión del navegador es el puente** (`extension/`, fuera del panel): pide la consulta a
  la API —que es lo que queda registrado—, inserta el prompt en Gemini sin enviarlo y lee la
  respuesta.
- **El índice lo mantiene un guion de Apps Script** que la plataforma sirve con su huella
  (`modules/agentes/guion/`): corre en el Drive de la unidad, resume con Gemini y manda las
  fichas. Los documentos no salen de Google.

Código en `modules/agentes/` (`acciones.py`, `indice.py`, `consulta.py`) y
`routers/agentes_router.py`; pantallas en `frontend/src/agentes/`. Publicar exige el módulo
`agentes`; consultar, `consulta_agentes`, que es de oficio. Garantías:
[`ESPECIFICACIONES.md`](ESPECIFICACIONES.md) §5.14.

### 5.8 Utilidades — `modules/utilidades/`

Operaciones sueltas sobre un fichero: unir, dividir y optimizar PDF, y anonimizar un CSV o un
Excel. El fichero entra en la petición y sale en la respuesta, **sin `StorageService`**, y queda
constancia sólo de metadatos. Router `routers/utilidades_router.py`, pantallas en
`frontend/src/utilidades/`, módulo `utilidades` de oficio. Garantías:
[`ESPECIFICACIONES.md`](ESPECIFICACIONES.md) §5.13.

### 5.9 Qué está previsto y no tiene código

- **Trámites asistidos con IA** —baremación, informe de fase, redacción de resolución— que el
  gestor de expedientes de la institución invoca, o que se crean a mano. **No se construye un
  gestor**: el suyo es la fuente de verdad del procedimiento y la plataforma no cambia nunca su
  estado. [`DECISION_TRAMITES_ASISTIDOS.md`](DECISION_TRAMITES_ASISTIDOS.md).

Que no esté escrito no es un retraso. **Qué tiene que hacer exactamente lo definen un despliegue
real y una necesidad identificada**, y escribirlo antes sería adivinarlo.

---

## 6. Roles, módulos de licencia y cascada

**Cuatro roles** (`core/auth/models.py`):

| Rol | Alcance |
|---|---|
| `superadmin` | La plataforma: proveedores de LLM, organizaciones, módulos, tokens. |
| `admin` | Crea y configura asistentes de **sus** organizaciones. |
| `informer` | Supervisa y valida respuestas de la IA. |
| `user` | Usuario final del asistente o del informe. |

Una lista de organizaciones vacía significa **cosas opuestas según el rol**, y es deliberado: en
un `superadmin` es el comodín «todas»; en cualquier otro es «ninguna». Si «vacío = todas» valiera
para todos, un `admin` al que se le olvidara poblar el *claim* volvería a verlo todo.

**Diez módulos de licencia** (`core/auth/modulos.py`), que son filas de catálogo y no `Enum`:
`chatbots`, `curacion`, `informes`, `automatizacion`, `personas`, `registro`, `utilidades`,
`agentes`, `consulta_agentes` y `plataforma`. `utilidades` y `consulta_agentes` son **de oficio**:
los tiene cualquier persona sin concesión, y retirarlos del catálogo los apaga para todos. Se exigen con
`require_module`, y **un docstring no autoriza nada**: declarar un módulo obliga a exigirlo. El
`superadmin` entra en todos sin concesión explícita —hacerlo depender de una fila deja una
instalación recién creada con su superadministrador encerrado fuera—.

`personas` y `registro` están separados de `plataforma` por el mismo criterio: administrar a las
personas de tu organización no es administrar la plataforma, y meterlo ahí obligaba a dar los
modelos de LLM y los tokens para poder dar lo primero.

**La cascada de configuración** es Plataforma → Organización → Chatbot, y la resuelve
`core/ambito.py` campo a campo, distinguiendo `None` («heredar») de `""` («lo quiero vacío») —sin
lo cual no se puede vaciar un valor heredado desde la pantalla—.

---

## 7. Anatomía del backend

```
server/app/
├── main.py            reparte los routers en _register_cloud / _register_edge según DEPLOY_MODE
├── routers/           la superficie HTTP, cada uno etiquetado `Deploy: cloud|edge|shared`
│   └── redaccion/     los routers del módulo de Informes
├── core/              lo compartido: auth, ambito, storage, config, red_publica,
│                      language_mode, llm_text, sandbox_client, quotas, rate_limit
├── modules/
│   ├── agents_hub/    database/ (los dos Base) · agent/ (grafos) · ingestion/ · services/
│   ├── redaccion/     contracts/ · database/ · pipelines/ · graph/ · services/
│   ├── curation/      spider, calidad de contenido, publicación
│   ├── agentes/       agentes de unidad: acciones, índice, consulta, guion del índice
│   ├── utilidades/    PDF y anonimización de un fichero
│   └── automation/    cortex, estrategias de extracción, llm_gateway
├── services/          agent, library, pricing, scheduler, token, manifest_signature
└── scripts/           bootstrap.py — sembrado idempotente de primera instalación

server/migrations/     99 revisiones de Alembic (fuera de `app/`, que es donde se busca)
```

Tres piezas que conviene localizar porque se buscan en el sitio equivocado:

- `model_factory`, `embedding_service`, `embedding_resolver` y `config_provider` viven en
  `modules/agents_hub/services/`, no en `core/`.
- El *LLM gateway* está en `modules/automation/infrastructure/llm_gateway.py`.
- El **registro** (bloque REG) no dejó paquete: su código son `routers/actividad_router.py` y
  `core/actividad_categorias.py`.

**Asincronía total**: prohibidos los métodos síncronos para I/O en el servidor. **Sin instanciar
servicios a mano**: inyección con `Depends`.

---

## 8. Datos

**PostgreSQL 16 + pgvector.** La URL se lee **únicamente** de `DATABASE_URL` (async) y
`DATABASE_URL_SYNC` (Alembic): no hay host, puerto, usuario ni contraseña en el código.

**El esquema lo define Alembic, y sólo Alembic** (invariante I14, bloque BD.2). La aplicación
**no crea tablas al arrancar**. Hasta BD.2 el arranque hacía `create_all` además de lo que
Alembic aplica, y esa segunda fuente **nunca borra lo que dejó de estar declarado**: así quedaron
36 tablas de modelos retirados en la base de desarrollo sin que nada lo dijera, y tres columnas
`nullable=True` en su migración y `NOT NULL` en su modelo durante semanas, también en producción.

Consecuencias prácticas: un modelo nuevo o cambiado va **con su migración en el mismo commit**
—`alembic check` corre en CI después de `alembic upgrade head`—, y `nullable=` se escribe
explícito en las columnas que importan, porque `Mapped[datetime]` sin él es `NOT NULL` por
deducción de la anotación y así nacieron las tres columnas divergentes.

Los tests siguen creando sus bases desechables con `create_all`; eso no es la aplicación, y un
guardarraíl vigila la diferencia.

**Ficheros de negocio: `fsspec` obligatorio.** Nada de `open()` para PDFs subidos, resultados de
procesamiento o adjuntos: se usa `StorageService` (`core/storage.py`) inyectado con `Depends`. El
proveedor se elige por variable de entorno —`file`, `s3`/MinIO o `gcs`— y el código no se acopla
a ninguno. Las escrituras en `/tmp` sólo valen como buffer dentro de una misma petición y se
borran al terminar.

---

## 9. Recuperación

La estrategia completa, con sus mediciones, está en los bloques ING.0, VIS y SYNC de
`planificacion/Plan_TDD_Fase1.md`; aquí va lo que condiciona el código.

**Tres niveles**: fragmento, documento e índice de materias. La selección escalonada por
metadatos acota primero por materia y sólo después busca dentro, que es lo que permite que un
corpus normativo grande no devuelva ruido.

**Híbrido**: búsqueda vectorial (pgvector, índice HNSW, coseno) fusionada por RRF con búsqueda
léxica de PostgreSQL (`tsvector` + GIN), y **desempate determinista** para que dos fragmentos
empatados no cambien de orden entre ejecuciones.

**Embeddings a 1024 dimensiones**, y no es un número arbitrario: es el único valor que sirve a la
vez a BGE-M3 en local (nativo) y a Google en la nube (rango flexible), así que cambiar de
proveedor no obliga a migrar la columna `Vector(1024)` ni a reconstruir el índice. El servicio se
**resuelve desde la configuración** (`embedding_resolver.py`): sin configuración, el local; con
una fila de `hub_llm_configs` de propósito `embedding`, el adaptador del tipo de proveedor que
diga. Misma imagen, distinta fila. **Sin *fallback* silencioso**: si el proveedor configurado no
se sabe hablar, error explícito, porque degradar a local sin avisar dejaría medio corpus en un
espacio vectorial y medio en otro, y el coseno entre ambos no da error, da resultados malos.

**El reranker es opcional por chatbot** y hoy está **apagado en el asistente de normativa por
medición**, no por omisión. [`DECISION_MODELOS_EMBEDDING_RERANKER.md`](DECISION_MODELOS_EMBEDDING_RERANKER.md).

Dos reglas duras del corpus, y violar cualquiera convierte «reclasificar» en «reindexar»:

- **El vocabulario es dato, no código.** Ámbitos, submaterias, rangos y colectivos viven en tabla
  versionada, con `vigent` y `substituit_per_codi` para renombrar y fusionar. Prohibido
  expresarlos como `Enum` de Python, `CheckConstraint` o lista literal. Los **ejes** sí son
  estructura y van en `StrEnum`: añadir un eje exige de todos modos código que lo consuma.
- **La taxonomía nunca entra en el texto que se embebe.** En `embedding_text` sólo va contexto
  **estructural** —título del documento y jerarquía de encabezados—, que es estable. Reclasificar
  debe costar un `UPDATE`; si un cambio de etiqueta obliga a re-embeber, algo se ha colado en el
  texto embebido. Los pares bilingües del dominio (`despesa`/`gasto`) son puente **léxico** y van
  al `tsvector`, que se regenera con una sentencia SQL; un embedding necesita GPU y horas.

**Al corpus sólo entra `.md`** conforme a [`CONTRATO_MD_CORPUS.md`](CONTRATO_MD_CORPUS.md). Un
PDF en el endpoint de ingesta devuelve **415** y dice a dónde ir: la conversión vive en el
pipeline de curación, que es donde está el OCR y donde se declara lo transcrito
automáticamente. **Docling se retiró** y no se reintroduce
([`DECISION_EXTRACCION_Y_DESPLIEGUE.md`](DECISION_EXTRACCION_Y_DESPLIEGUE.md)); el contexto
temporal que sube una persona se extrae con `pdfplumber`.

---

## 10. Frontend

React 19 + TypeScript + Vite, Tailwind, `i18next` (`ca` / `es` / `en`), `react-hook-form` con
`zodResolver`, y el cliente de API generado por Orval. **Ningún string de la UI va en el código**:
todo pasa por i18n.

```
frontend/src/
├── admin/       panel de Chatbots y de Plataforma
├── curation/    curación de portales
├── redaccion/   informes y scripts; también las páginas del catálogo de funciones
├── automatizacion/  el menú «Automatización», que monta esas páginas
├── agentes/     agentes de unidad: consultar, publicar, integración con Gemini
├── utilidades/  PDF y anonimización
├── widget/      el chatbot público embebible
├── shared/      i18n, cliente generado, componentes comunes, auth
└── themes/      la cascada visual

extension/       la extensión de Chrome de los agentes de unidad, fuera de `frontend/`
```

El mapa de rutas, que es la forma real del producto:

| Ruta | Módulo exigido | Qué hay |
|---|---|---|
| `/` | — | Aterriza en el **primer módulo concedido**, no en `/hub` fijo: quien sólo hace informes entra en informes |
| `/hub/*` | `chatbots` | chatbots · valores por defecto · documentos · vigencia · revisión de interacciones · prompts · escenarios de prueba |
| `/redaccion/*` | `informes` | *builder* de plantillas · asistente · borrador · scripts (propuesta y revisión) · espacios de trabajo |
| `/automatizacion/*` | `automatizacion` | catálogo de funciones · revisión posterior |
| `/curation/*` | `curacion` | sitios · auditoría · hallazgos · publicación |
| `/agentes/*` | `consulta_agentes` · `agentes` | consultar · publicar y gestionar · integración con Gemini; cada pestaña con su guarda |
| `/utilidades/*` | `utilidades` | PDF · anonimizar un fichero |
| `/extension/conectar` | `consulta_agentes` | conectar la extensión del navegador con la cuenta de la persona |
| `/personas` | `personas` | las personas de la organización |
| `/registro` | `registro` | el registro de actividad IA |
| `/plataforma/*` | `plataforma` | organizaciones · modelos · prompts de actividad · tokens · módulos · identidad visual |

Dos decisiones que se ven en esa tabla. **Las rutas viejas no redirigen**: `AGENTS.md` prohíbe
los *shims*, así que cuando «Modelos LLM» salió de `/hub` a `/plataforma` no quedó una
redirección detrás. Y **una dirección que no existe se dice, no se redirige**: con un aterrizaje
en el comodín, cualquier URL equivocada acababa en el primer módulo concedido, o sea un 404
disfrazado.

El widget se construye aparte (`npm run build:widget`) y se incrusta con una clave pública por
asistente. Cómo: [`WIDGET_INCRUSTACION.md`](WIDGET_INCRUSTACION.md) y
[`chatbots-publicos/`](chatbots-publicos/).

Accesibilidad WCAG 2.2 AA con trabajo propio en CI:
[`A11Y_GUIDELINES.md`](A11Y_GUIDELINES.md) · [`A11Y_CHECKLIST.md`](A11Y_CHECKLIST.md).

---

## 11. Servicios transversales

| Servicio | Dónde | Nota |
|---|---|---|
| **Almacenamiento** | `core/storage.py` | `fsspec`: `file`, S3/MinIO o GCS por configuración |
| **Modelos de chat** | `agents_hub/services/model_factory.py` | Adaptador por `provider_type`; añadir un modelo es un `UPDATE`, sólo un protocolo nuevo exige código |
| **Niveles de modelo** | [`NIVELES_DE_MODELO.md`](NIVELES_DE_MODELO.md) | El nivel es un **papel**, no un modelo: dos niveles pueden apuntar al mismo |
| **Lectura del LLM** | `core/llm_text.py` | `texto_de` obligatorio: Gemini devuelve `content` como lista de bloques en cuanto hay más de una parte |
| **Sandbox de scripts** | `services/script_sandbox` + `core/sandbox_client.py` | Microservicio aislado, ocho capas; la octava (gVisor) la pone el aprovisionamiento de la VM. [`SANDBOX_SECURITY.md`](SANDBOX_SECURITY.md) |
| **Servidor MCP** | `mcp_server/` | Dos transportes, stdio y remoto. **No importa `server/app`**. [`MCP_SERVER.md`](MCP_SERVER.md) |
| **Observabilidad** | Langfuse | Trazas de las llamadas al modelo |

---

## 12. Seguridad y privacidad

- **Tres vías de autenticación**: SSO SAML 2.0 para personas, contraseña local mientras el SSO no
  esté (`LOCAL_USER_LOGIN_ENABLED`), y **PAT revocables** con *scopes* para clientes máquina —que
  es lo que consume el servidor MCP—. OIDC queda como opción futura.
- **Anonimización selectiva por políticas**, no automática en todo: NER reversible en informes y
  espacios de trabajo, y no en el chatbot público, que no recibe datos personales por diseño.
- **Los secretos se guardan por referencia, no por valor.** Una credencial de proveedor declara
  *dónde* está el secreto —nombre de variable de entorno, o ADC—, no el secreto. Así un volcado
  de la base o la sincronización cloud→edge dejan de ser sensibles por construcción.
- **El servidor sólo pide URL de la red pública**, y lo comprueba **en cada salto**: una
  dirección privada, de *loopback* o de enlace local —el servidor de metadatos de la nube, los
  contenedores vecinos— no se pide, ni directamente ni llegando a ella por una redirección
  (`core/red_publica.py`). Hay una válvula de desarrollo y **producción se niega a arrancar con
  ella puesta**.
- **Cabeceras de seguridad, límites de tasa y cuotas** en `core/security_headers.py`,
  `core/rate_limit.py` y `core/quotas.py`. El límite de saltos de proxy de confianza es
  configuración (`TRUSTED_PROXY_HOPS`), porque suponerlo es como se falsifica una IP de origen.
- **Código que no ha pasado el filtro no se ejecuta** (invariante I13): auditoría AST sin
  hallazgos críticos, prueba en sandbox y declaración responsable.

Quien despliega es responsable de su instancia (`SECURITY.md`).

---

## 13. Despliegue y entrega

**Una VM de GCP con Docker Compose**, y no una plataforma de contenedores efímeros. La decisión
está medida: lo que pesa es `torch`, y con modelos locales el arranque en frío de un contenedor
que puede destruirse en cualquier momento no sale a cuenta. Qué se descartó exactamente y con qué
números, en [`DECISION_EXTRACCION_Y_DESPLIEGUE.md`](DECISION_EXTRACCION_Y_DESPLIEGUE.md) §2 —que
es el documento que puede nombrarlo, porque es el que lo descartó; un guardarraíl impide que el
nombre del destino viejo se cuele en los demás—. El código sigue
siendo portable: nada se acopla al proveedor, y cambiar a MinIO + PostgreSQL local o a AWS es
cambiar variables de entorno.

**Dos ficheros de Compose.** `docker-compose.yml` levanta sólo la infraestructura de desarrollo
—`postgres`, `minio`, `clickhouse`, `redis`, `langfuse`, `script-sandbox`— y la aplicación corre
en la máquina de quien desarrolla. `docker-compose.prod.yml` levanta el conjunto: `app`,
`frontend`, `ollama`, `script-sandbox`, `migrate`, `langfuse`, `postgres`, `minio`.

**Tres *workflows* de GitHub Actions**:

| Workflow | Cuándo | Qué hace |
|---|---|---|
| `ci.yml` | cada *push* y PR | Cinco trabajos: `test` (lint + suite completa + `alembic check` + puertas de control de acceso y regresión de recuperación), `contract` (OpenAPI → Orval → TypeScript + tests de frontend), `a11y`, `supply-chain` (auditoría de dependencias y secretos) e `imagen` (construye las imágenes del despliegue, migra con la recién construida y la arranca hasta `/health`) |
| `dco.yml` | cada PR | Exige `Signed-off-by` en cada commit |
| `deploy.yml` | *push* a `main`, y sólo eso | Despliega la punta de `main` a la VM |

Tres decisiones gobiernan el despliegue, y las tres salen de incidentes reales: **sin claves de
larga vida** (Workload Identity Federation, no un JSON en los secretos del repositorio), **la
etiqueta de la imagen es el SHA del commit y nunca `latest`** —con `latest` no se puede saber qué
corre ni volver atrás, que son las dos preguntas de un incidente—, y **las migraciones van antes
de cambiar la imagen, en un paso propio y visible**.

**Se trabaja en `desarrollo`; `main` es para desplegar.** `deploy.yml` dispara con *push* a
`main` y sólo con eso, así que empujar a `desarrollo` comprueba pero no despliega. CI y DCO sí
corren en `desarrollo`. La regla nació el 2026-09-02, después de que un commit que sólo tocaba un
guion de publicación desplegara producción entera.

**Todos los commits van firmados** (`git commit -s`, DCO 1.1). La firma es del autor humano, no
del agente: la línea que importa certifica procedencia, y sólo la puede certificar una persona.

Para arrancar en local, el `README` de la raíz. El despliegue del prototipo, paso a paso:
[`DESPLIEGUE_PROTOTIPO_GCP.md`](DESPLIEGUE_PROTOTIPO_GCP.md). Cómo se prueba lo que no puede
probar una máquina: [`PRUEBAS_MANUALES.md`](PRUEBAS_MANUALES.md).

---

## 14. Stack, medido el 2026-09-19

| Capa | Qué |
|---|---|
| Lenguaje | **Python 3.13** (`.python-version`, la imagen y CI; el manifiesto declara `>=3.11` como suelo) |
| Paquetes | `uv`. **Cuatro proyectos**: `server/`, `shared/`, `mcp_server/`, `services/script_sandbox/`. **No hay proyecto Python en la raíz** |
| API | FastAPI · SQLAlchemy 2.0 async · Alembic · Pydantic 2 · `uvicorn` |
| Orquestación | LangGraph |
| Base de datos | PostgreSQL 16 + pgvector (HNSW, coseno) + *full-text search* (`tsvector` + GIN) |
| Embeddings | BGE-M3 local o API, a 1024 dimensiones, resuelto por configuración |
| Reordenación | *cross-encoder* BGE-reranker-v2-m3, activable por chatbot |
| Extracción | `pdfplumber`. Web dinámica con Playwright |
| Ficheros | `fsspec`: `file` · S3/MinIO · GCS |
| Frontend | React 19 · TypeScript · Vite · Tailwind 4 · i18next · TanStack Query · Orval · Zod |
| Pruebas | pytest (CI con `-n0` a propósito: el paralelismo esconde el estado filtrado entre tests) · vitest · axe |
| Contenedores | Docker + Compose |
| CI/CD | **GitHub Actions** |
| Observabilidad | Langfuse |

Las dependencias se relockean **en el mismo commit** que las cambia: CI instala con
`uv sync --locked`, y sin ese flag `uv sync` vuelve a resolver en silencio. Para comprobar en
local vale `uv lock --check`, no `uv sync` a secas, que relockea y por tanto siempre pasa.

---

## 15. Licencia y distribución

**AGPL-3.0-or-later**, con la **Universitat Jaume I** como titular. El texto vinculante es
`LICENSE`; explicado en español, con lo que obliga y lo que **no** obliga:
[`LICENCIA_ES.md`](LICENCIA_ES.md).

Por qué AGPL y no GPL: por el §13. Quien despliegue una versión modificada **como servicio en
red** tiene que ofrecer su código fuente a quien la use, y siendo el destinatario otras
administraciones, es lo que impide que una mejora pagada con fondos públicos quede cerrada.

Dos consecuencias, y sólo una está entera. La procedencia de cada aportación **se certifica** con
DCO, y lo comprueba un *workflow*. El enlace al fuente **lo sirve el servidor** —`GET
/api/v1/instancia`, público y sin credencial, tomado de `SOURCE_URL` y no de una URL fija, porque
el §13 pide el *Corresponding Source* de esa versión— pero **ninguna interfaz lo enseña
todavía**, ni el panel ni el widget embebido, que es el caso que se olvida. Un enlace que nadie
ve no cumple la obligación: está a medias y así consta en el `README`.

**Gobernanza: un principal y tantos forks como organizaciones.** Cada organización que despliegue
trabaja sobre su fork; lo generalizable se pide que suba al principal por *pull request*. La
regla vale igual para la UJI, donde nació el proyecto: alojar no es dirigir. El detalle está en
el `README` y en `CONTRIBUTING.md`.

**Sobre la licencia dual comercial.** La planificación de enero de 2026 adoptó un modelo
AGPLv3 + licencia comercial para *partners*, y esa posibilidad **sigue abierta y no se ha
ejercido**: la titularidad es de una sola persona jurídica, que es lo que técnicamente la
permite. Lo que hay hoy es una sola licencia, la AGPL, y lo que se contrata son **servicios**
—despliegue, adaptación, soporte, formación, corpus—, que la licencia permite expresamente. Este
documento lo dice porque hasta el 2026-09-19 afirmaba en dos sitios que el modelo *era* dual, sin
que existiera oferta comercial alguna, y en un repositorio público eso es una afirmación que
alguien acabaría citando en un pliego.

---

## 16. Decisiones estructurales

Las decisiones de las secciones 2, 3, 4 y 6 —la regla del servidor que decide, los principios
transversales, las dos fronteras y el modelo de roles— son **estructurales**: un cambio que las
contradiga no es un *commit*, es una decisión de arquitectura con su documento.

El registro numerado, con estado y fecha, está en [`DECISIONES.md`](DECISIONES.md), que también
dice cuándo hace falta un documento de decisión y cuándo basta una fila del historial. Ninguna
decisión se actualiza: si cambia, la sustituye otra que la cite.

**Lo que este documento no decide y conviene no dar por cerrado**: qué trámites asistidos se
escriben primero, y con qué gestor de expedientes de la institución se integran. Las dos esperan
un despliegue real, y §5.9 explica por qué esperar es la decisión y no la falta de ella.

---

## 17. Procedencia de este documento

Hasta el 2026-09-19 esta página era el **estado objetivo** escrito en enero de 2026, antes de
integrar AI Agents Hub y AutomatIA en el monorepo. Se reescribió, y no se parcheó, porque el
problema no eran sus erratas sino su **tiempo verbal**: describía un sistema por construir, con
un roadmap por trimestres y una sección de «decisiones pendientes», mientras el README lo
anunciaba como la puerta técnica de entrada al repositorio.

Lo que decía y no era cierto, para que no vuelva por copia de una versión antigua:

| Decía | Es |
|---|---|
| Ingesta con **Docling** (cinco sitios) | `pdfplumber`; Docling se retiró en EXT.3 y `AGENTS.md` prohíbe reintroducirlo |
| CI/CD con **Bitbucket Pipelines** | GitHub Actions, tres *workflows* |
| **Python 3.11+** | 3.13 en `.python-version`, la imagen y CI |
| Modelo de licenciamiento **dual-license** | Una licencia, AGPL; la dual es una posibilidad abierta y no ejercida (§15) |
| Un árbol con `local-runner/`, `modules/expedientes/`, `frontend/src/agent/`, `frontend/src/automation/` y `server/app/api/` | Ninguno existe. `AGENTS.md` ya advertía que son las rutas que se escriben de memoria |
| Tres módulos: Hub, AutomatIA y Expedientes | Construidos: Chatbots, Informes, Curación, Automatización gobernada, Agentes de unidad y Utilidades; los trámites asistidos, previstos sin código, y sin gestor de expedientes propio |
| «Job Queue propia de AutomatIA» | No existe tal cosa: lo periódico va con APScheduler (`services/scheduler_service.py` para modelos y precios, `curation/quality_scheduler.py` para la revisión de portales) y lo disparado por una petición, con los *background tasks* de FastAPI |
| Un roadmap por trimestres hasta 2028 | El estado vivo está en `PROJECT_STATE.md` y el pendiente, como *issues* |

Y lo que **callaba**: el módulo de Informes entero, la curación como producto propio, el registro
de actividad IA, las verificaciones por API, la multitenencia con sus cuatro ámbitos, la política
de lengua, y que el esquema lo define Alembic y sólo Alembic.

Lo que se conserva del documento original, porque resultó verdadero: los principios
transversales, la frontera Cloud/Edge, el modelo de roles y la orientación servidor-first. El
texto anterior se lee en el historial de git.
