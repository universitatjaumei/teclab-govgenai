# Especificaciones de Gov Gen AI Platform

> **Lo vigila un test.** `server/tests/infra/test_especificaciones_no_miente.py` comprueba que
> todo lo que este documento nombra existe y que los vocabularios que enumera son los que el
> código declara. Si algo de aquí deja de ser verdad, la suite se pone roja. Ver §11.

## 1. Qué es y qué no es este documento

Es la **especificación por capacidad**: para cada cosa que la plataforma sabe hacer, qué garantiza,
dónde se hace cumplir esa garantía, qué la demuestra, y qué queda abierto.

Existe porque faltaba una frase que no está escrita en ningún otro sitio: **«el sistema garantiza
Y»**. Los planes de `planificacion/` dicen «haz X» —son *prompts*, ordenados por ejecución—, y de
ahí no se deduce qué se puede cambiar sin romper nada. Esa deducción es justo lo que necesita quien
llega de fuera a continuar un desarrollo.

**Qué no es, y dónde está en su lugar:**

| No es | Está en |
|---|---|
| Una presentación del proyecto | [`PRESENTACION_PROYECTO.md`](PRESENTACION_PROYECTO.md) |
| El diseño y sus principios | [`Arquitectura.md`](Arquitectura.md) |
| El estado del desarrollo hoy | [`../planificacion/PROJECT_STATE.md`](../planificacion/PROJECT_STATE.md) |
| Por qué algo se hizo así | [`../planificacion/HISTORIAL.md`](../planificacion/HISTORIAL.md) y los docstrings |
| Las reglas de cómo se trabaja | [`../AGENTS.md`](../AGENTS.md), [`../CONTRIBUTING.md`](../CONTRIBUTING.md) |
| El plan de lo que falta | `planificacion/Plan_TDD_Fase1.md` y siguientes |

**Este documento apunta, no copia.** La regla es dura y tiene motivo: el proyecto persigue las
dobles fuentes de verdad —el vocabulario del corpus es dato y no `Enum`, el inventario de
multitenencia lo vigila un test— y un documento que repitiera el estado del desarrollo divergiría
en semanas y mentiría con autoridad. Aquí va lo **estable**: capacidades, contratos, invariantes.
Lo **volátil** —qué bloque está en curso, qué prompt viene— vive en `PROJECT_STATE.md` y aquí sólo
se enlaza.

---

## 2. Cómo leer una capacidad

Cada capacidad de §5 a §7 se describe con el mismo esqueleto:

- **Qué hace** — en una o dos frases, sin jerga.
- **Garantiza** — las afirmaciones que se pueden dar por ciertas al construir encima. Si una es
  falsa, es un defecto, no una decisión.
- **Superficie** — endpoints, tablas y componentes por los que se toca.
- **Invariantes** — lo que no se puede romper, con el sitio donde se hace cumplir.
- **Madurez** — `producción` (desplegado y en uso), `construido` (completo y probado, sin uso
  real todavía), `parcial` (funciona con límites conocidos) o `previsto` (especificado, sin
  construir).
- **Abierto** — lo que falta o está decidido a medias, con el bloque del plan que lo aborda.

**La madurez es deliberadamente gruesa.** El detalle fino (qué prompt, qué fecha) está en
`PROJECT_STATE.md`, que es lo que se actualiza a diario; si se repitiera aquí, este documento sería
viejo la semana que viene.

---

## 3. El sistema en una página

Gov Gen AI Platform da a una administración pública cuatro cosas sobre una misma base:

1. **Asistentes informativos** que responden sobre su normativa **citando la norma**, y que
   **callan** cuando no tienen fundamento.
2. **Curación de contenido**: rastrear su portal, revisar qué ha cambiado y decidir qué entra al
   corpus.
3. **Informes y automatización**: plantillas con datos deterministas y valoración de la IA sujeta
   a aprobación humana.
4. **Administración multiorganización**: una instalación sirve a varias organizaciones sin que se
   vean entre ellas.

```
┌─ frontend/src ────────────────────────────────────────────────┐
│  admin · curation · redaccion · widget                        │
└───────────────────────┬───────────────────────────────────────┘
                        │  contrato OpenAPI → cliente generado (Orval)
┌───────────────────────┴───────────────────────────────────────┐
│  server/app/routers · api/v1        registrados en main.py     │
├───────────────────────────────────────────────────────────────┤
│  server/app/modules/                                          │
│    agents_hub   asistentes, corpus, ingesta, evaluación       │
│    curation     rastreo de portales y revisión                │
│    redaccion    informes, plantillas, scripts, sandbox        │
│    automation   flujos, ETL, PDF                              │
├───────────────────────────────────────────────────────────────┤
│  server/app/core/    auth · tenancy · ámbito · storage ·      │
│                      llm gateway · language_mode · llm_text   │
├───────────────────────────────────────────────────────────────┤
│  PostgreSQL 16 + pgvector   ·   almacenamiento vía fsspec     │
└───────────────────────────────────────────────────────────────┘
```

**Dos fronteras estructurales** que condicionan cualquier código nuevo, y que están explicadas en
`AGENTS.md`:

- **Cloud / Edge.** La configuración administrativa vive en el cloud; los datos del cliente
  —conversaciones, documentos, expedientes— pueden vivir en un *edge node* dentro de su nube. Dos
  `DeclarativeBase` separadas (`HubConfigBase`, `HubOperationalBase`), sin `relationship()` que
  las cruce, y `ConfigProvider` como único camino del edge a la configuración.
- **Organización.** Toda tabla de configuración declara su ámbito en `__ambito__`, y hay
  **cuatro** posibles: `plataforma`, `organizacion`, `heredable` (nulo = plataforma, y se hereda)
  y `derivada` (la organización se alcanza por otra tabla). Son cuatro y no tres porque tres
  serían una mentira. El inventario tabla por tabla está en
  [`MULTITENENCIA.md`](MULTITENENCIA.md), y lo vigila su propio test.

---

## 4. Invariantes de plataforma

Lo que no se puede romper. Cada uno dice **dónde se hace cumplir**, porque un invariante que sólo
vive en un documento no es un invariante: es una intención.

| # | Invariante | Se hace cumplir en |
|---|---|---|
| I1 | **Una respuesta sin cita válida no se entrega.** Si no hay fundamento en el corpus recuperado, el asistente se rinde con el mensaje del chatbot | `agent/citation_validator.py` (`enforce_citation_contract`) |
| I2 | **Sólo se cita lo que se recuperó.** Un ancla que no se recuperó se degrada al documento; lo que apunta fuera del conjunto pierde el enlace, no la mención | `degradar_anclas` + `despojar_remisiones`, en ese orden |
| I3 | **La taxonomía nunca entra en el texto que se embebe.** En `embedding_text` sólo va contexto estructural. Reclasificar tiene que costar un `UPDATE`, no un reindexado | contrato del corpus + guardarraíles de ingesta |
| I4 | **El vocabulario es dato, no código.** Ámbitos, submaterias, módulos y categorías de datos viven en tabla versionada; prohibido `Enum` de Python o `CheckConstraint` para ellos. Los **ejes** sí son estructura y van en `StrEnum`: añadir uno exige código que lo consuma | `core/auth/modulos.py`, `vocabulary_service.py`, vocabulario del corpus |
| I5 | **Quien no gestiona una organización no ve sus datos.** Y una lista de organizaciones vacía significa «ninguna», no «todas» | `core/auth/tenancy.py`; `test_tenant_isolation.py` |
| I6 | **El frontend no calcula permisos.** El servidor manda `acciones_permitidas` o banderas por fila; React itera | reglas maestras de `AGENTS.md`; DTOs de cada router |
| I7 | **El frontend no define tipos de datos a mano.** Todo sale del contrato OpenAPI vía Orval | job `API Contract` de CI |
| I8 | **Ningún router sirve datos sin acotar por tenencia, o declara por qué no.** | `test_router_inventory_is_walked.py` |
| I9 | **Un docstring no autoriza nada.** Declarar un módulo obliga a exigirlo con `require_module` | el mismo test |
| I10 | **El contenido del modelo se lee con `texto_de`.** Gemini devuelve `content` como lista de bloques en cuanto hay más de una parte, y quien asume `str` falla más tarde y en otro sitio | `core/llm_text.py` + guardarraíl de USR.8 |
| I11 | **Los ficheros de negocio se guardan por `StorageService`**, nunca con `open()`: el contenedor es efímero y el proveedor, cambiable | `core/storage.py`; regla de portabilidad |
| I12 | **Todo lo que va al LLM desde el edge va anonimizado**, y el `model_factory` no anonimiza: recibe datos ya limpios | frontera edge/cloud de `AGENTS.md` |
| I13 | **Código que no ha pasado el filtro no se ejecuta.** Auditoría AST sin hallazgos críticos + prueba en sandbox + declaración responsable, **y el filtro es automático**: la aprobación humana previa dejó de ser la puerta en FUN.3/FUN.4, porque la Instrucció 02/2026 la prohíbe como condición para compartir dentro del servicio. La persona entra **después**, en la revisión posterior, que puede pedir correcciones, reclasificar o suspender. La única aprobación previa que queda es el paso a nivel 3 | `redaccion/services/script_auditor.py`, `redaccion/funciones_service.py`, `redaccion/funciones_acciones.py`, `SANDBOX_SECURITY.md`, `CATALOGO_FUNCIONES.md` |
| I14 | **El esquema lo define Alembic, y sólo Alembic.** La aplicación no crea tablas al arrancar; un modelo cambiado sin su migración es un fallo de CI, no una tabla aparecida | `alembic check` en CI tras `upgrade head`; `test_bd2_alembic_es_la_unica_fuente.py` |
| I15 | **El servidor sólo pide URL de la red pública, y lo comprueba en cada salto.** Una dirección privada, de *loopback* o de enlace local —el servidor de metadatos de la nube, los contenedores vecinos— no se pide, ni directamente ni **llegando a ella por una redirección**. La forma de la URL la validan los contratos de entrada (422 con motivo); el destino resuelto, cada petición. Hay una válvula de desarrollo, `CRAWLER_ALLOW_PRIVATE_TARGETS`, y **producción se niega a arrancar con ella puesta** | `core/red_publica.py` + `cliente_de_rastreo` en `modules/curation/spider.py`; los cuatro gates de `core/config.py`; `test_aper1_*` |
| I16 | **Lo que corre dentro del servidor registra, no imprime.** Un `print()` en producción sale sin nivel, sin marca de tiempo y sin nombre de módulo: no se puede filtrar por severidad ni subir el detalle de un servicio sin subirlo de todos. Una herramienta de consola **sí** imprime —le habla a quien la acaba de ejecutar— y se distingue por serlo (`typer.Typer()`, `__main__`, `argparse`), no por declararlo | `configurar_logging` en `main.py` (nivel por `LOG_LEVEL`); `test_issue18_lo_que_corre_en_el_servidor_no_imprime.py` |

**Cómo se usa esta tabla.** Al escribir código nuevo, si tocas algo que aparece en la columna
derecha, el test correspondiente es el que te dirá si te has pasado. Si crees que un invariante
debe cambiar, es una decisión de arquitectura: va con su documento en `docs/`, no con un *commit*.

---

## 5. Capacidades — Fase 1

### 5.1 Asistentes informativos

**Qué hace.** Responde preguntas sobre la normativa de una organización citando el artículo, y
declina cuando no tiene con qué responder.

**Garantiza.**
- Toda afirmación entregada lleva cita a un documento **efectivamente recuperado** (I1, I2).
- La respuesta no presenta como vigente lo que no lo está; la preferencia de lengua opera
  **dentro** de la misma vigencia, nunca por encima.
- El flujo termina siempre: o `done` con `interaction_id`, o `error`. Nunca silencio.
- Cada turno queda registrado con su consumo, y es valorable por `interaction_id`.

**Superficie.** `POST /api/v1/hub/chat/{chatbot_id}` (SSE: `status`, `token`, `discard`, `done`,
`error`) · `hub_feedback_router` · `HubChatbot`, `HubInteraction`, `HubDocumentChunk`.

**Cómo está construido.** Un `CoreGraph` de LangGraph con cuatro estrategias enchufables por eje:
recuperación, fusión, plantilla y **política de lengua**. Dos modos de recuperación en uso: `RAG`
(híbrido vectorial + texto completo, con desempate determinista) y `MD_AGENT_SELECTOR` (el modelo
lee documentos enteros con *tools*).

**Invariantes.** I1, I2, I10.

**Madurez**: `producción` — cuatro asistentes sirviendo en el piloto.

**Abierto.**
- **Declinar es el hueco medido**, no recuperar: 21 de 21 escenarios bien anotados recuperan la
  norma correcta, y el umbral de calidad no arregla la abstención. Bloque **RHR** (revisión humana
  de respuestas) es el camino elegido.
- La comprobación de fundamento está **apagada por medición**: rechazaba 10 de 30 respuestas
  buenas. Reactivarla exige otro mecanismo, no otro número.
- Perfiles `router` y `aggregator` declarados y **sin implementar**: sus factorías lanzan
  `NotImplementedError` a propósito, para no construir un grafo que recuperaría vacío en silencio.

---

### 5.2 Política de lengua

**Qué hace.** Decide en qué lengua responde un asistente y qué versión de una norma bilingüe
prefiere.

**Garantiza.** Tres modos y sólo tres, configurables en cascada y validados al escribirse:

| Modo | Qué hace |
|---|---|
| `prefer` | Detecta la lengua de la pregunta, responde en ella y prefiere esa versión. **Es el defecto** |
| `none` | Sin política: ni detección, ni orden por lengua, ni instrucción en el prompt |
| `fixed:<código>` | Responde siempre en esa lengua, pregunten como pregunten |

- Un valor que no sea uno de los tres da **422 con los modos enumerados**. Antes era texto libre y
  un typo caía a `prefer` sin avisar a nadie.
- El panel **no escribe la lista**: la pide a `GET /api/v1/hub/opciones/lengua`.
- Los códigos que ofrece el catálogo son los **del corpus** (`val`, no `ca`), y **`ca` y `val` son
  la misma lengua en todo el sistema**: se traduce a `val` en las cuatro puertas por las que entra
  una lengua —la detección de la pregunta, el `language:` del front-matter de un `.md`, el
  `idioma` del manifiesto de un paquete de corpus y el `fixed:<código>` de la API—. Antes sólo se
  traducía en la detección, así que un `fixed:ca` pasaba la validación de forma y daba una
  preferencia que no prefiere ninguna versión de ninguna norma, en silencio, y un documento
  ingerido como `ca` quedaba con un código que no usaba nadie más.

Y dos garantías más, que son las que deciden qué lee quien pregunta:

- **La preferencia de lengua opera DENTRO de la misma vigencia, no por encima de ella** (VIS.4).
  Entre dos versiones de una norma manda primero la vigencia y después la lengua: si la versión
  confirmada por una persona sólo está en la otra lengua, se cita ésa y se advierte de la lengua;
  nunca al revés. Citar en la lengua correcta algo que nadie ha confirmado que rija es un error de
  fondo; citar lo confirmado en otra lengua es una incomodidad, y encima se avisa. `fixed:` no
  entra en esto: filtra a una lengua por definición y ahí la vigencia no compite con nada.
- **Si la norma citada está en otra lengua, se dice — en la lengua de la pregunta y en las dos
  direcciones** (VIS.5). El aviso sale de la lengua de la **fuente**, no de la de la pregunta:
  quien escribe en valencià ya sabe en qué lengua escribe, y lo que necesita saber es que el
  enlace le lleva a un documento en castellano. Preguntar en castellano y recibir una norma en
  valencià es el caso mayoritario del corpus real —232 de 334 documentos del asistente normativo
  están en `val`— y antes era justo el que no avisaba.
- **Y el aviso dice qué se está leyendo, no sólo adónde lleva el enlace.** Al corpus sólo entran
  originales: no se sube ni una traducción. Así que cuando la norma citada está en la otra lengua,
  lo que lee quien pregunta es una traducción que **el modelo acaba de hacer, que nadie ha
  revisado y que no está publicada en ningún sitio**, y el aviso lo dice con esas palabras. Va en
  el aviso condicional y no en el permanente de contenido generado por IA —que ya advierte de que
  las respuestas no han pasado revisión lingüística— porque sale sólo cuando es verdad: en una
  norma que sólo existe en valencià, preguntada en valencià, no hay traducción ninguna, y un aviso
  que sale siempre se aprende a ignorar.

**Superficie.** `core/language_mode.py` · `hub_opciones_router` · `HubOrganizacion.default_language_mode`
· `HubChatbot.language_mode` · `PreferLanguagePolicy` en `strategies/protocols.py` (el orden) ·
`_build_translation_warning` en `api/v1/hub_chat.py` (el aviso) ·
`services/language_detector.py` (el único punto que produce la lengua de una pregunta) ·
`core/lengua_del_corpus.py` (el único sitio donde está escrito que `ca` y `val` son la misma
lengua, compartido por la detección, los modos, la ingesta y el manifiesto del corpus).

**Madurez**: `producción` — desplegado el 2026-09-07 (bloque LANG, 2026-09-03). El orden por
vigencia y el aviso de lengua entraron antes, el 2026-08-25 (VIS.4 y VIS.5), y llevan en `main`
desde entonces; lo que faltaba no era el despliegue, era escribir aquí qué garantizan.

**Abierto.** Ningún despliegue monolingüe real lo ha usado todavía; el juicio sobre si el
castellano de una respuesta fijada suena institucional o a traducción automática está pendiente de
una persona (`pruebas_manuales/pruebas_manuales_bloqueLANG.bat`).

Y el orden por vigencia **todavía no decide nada en el corpus de hoy**, porque casi ninguna norma
tiene sus dos versiones emparejadas: 47 traducciones no declaran de qué norma son versión
(`versio_idiomatica_de` nulo). La regla está escrita antes de que el corpus la necesite, a
propósito — cuando lleguen los emparejamientos, nadie va a estar mirando esta parte del código.

---

### 5.3 Corpus normativo y su ciclo de vida

**Qué hace.** Mantiene el cuerpo normativo que citan los asistentes: qué entra, en qué lengua, con
qué clasificación y hasta cuándo vale.

**Garantiza.**
- Al corpus **sólo entra `.md`** conforme a [`CONTRATO_MD_CORPUS.md`](CONTRATO_MD_CORPUS.md). La
  conversión ocurre **fuera** de la aplicación; el servidor no lleva conversor de documentos.
- Clasificación por **ámbito** y **submaterias** desde vocabulario en tabla, con `vigent` y
  `substituit_per_codi` para renombrar y fusionar sin reindexar (I3, I4).
- **Una versión por norma y lengua**; `ca` ≡ `val`; la vigencia se expresa con un eje, y la
  validación y la caducidad se comparten entre versiones.
- Reingesta **idempotente**: volver a ingerir lo mismo no duplica ni reembebe.
- Recuperación en **tres niveles** (fragmento, documento, índice), ya implementada.

**Superficie.** `agents_hub/ingestion/` · `services/retrieval/` · `HubDocument`, `HubDocumentChunk`
· `ingestion_router`, `hub_tasks_router`.

**Invariantes.** I3, I4.

**Madurez**: `producción` — corpus real de normativa propia ingerido en los cuatro asistentes.

**Abierto.**
- **Catálogo de procedimientos** (bloque **PRC**): el piloto no contesta plazos, silencio ni canal
  porque eso no está en la normativa. Bloqueado por dos prerrequisitos externos —fichas validadas
  por los servicios y una consulta de descarga que debe habilitar el equipo del catálogo—.
- El vocabulario **está pendiente de validación por Secretaría General**: va a cambiar, y por eso
  I3 y I4 no son negociables.

---

### 5.4 Curación de portales

**Qué hace.** Rastrea un portal institucional real, detecta qué ha cambiado y presenta hallazgos
para que una persona decida qué entra al corpus.

**Garantiza.**
- Rastreo con cadencia, alta automática de páginas nuevas y reingesta de las cambiadas.
- Los hallazgos se revisan **uno a uno**; nada entra al corpus sin decisión humana.
- Salvaguardas contra el vaciado: una pasada parcial no puede dar de baja el resto del portal.
- **El rastreo no sale de la red pública** (I15). Quien da de alta un sitio decide a dónde pide
  el servidor, y basta ser administrador de una organización: hasta APER.1 eso alcanzaba la red
  interna del despliegue y el texto volvía en el informe de reconocimiento. Ahora la dirección se
  comprueba en **cada petición y cada redirección**, y una raíz privada se rechaza al darla de
  alta con un 422 que dice por qué.

**Superficie.** `modules/curation/` (`site_crawler.py`) · `curation_router` · pantallas
`/curation/*` · `core/red_publica.py` y `cliente_de_rastreo`, el único sitio del módulo donde se
construye un cliente HTTP.

**Madurez**: `producción` — el portal real de la UJI, con sus trampas inventariadas (conmutador de
idioma, http+https duplicados, la misma sección bajo dos prefijos, archivo por curso académico).

**Y encima de esto**, §5.11 añade el apartado que se mantiene solo: la misma curación, acotada a
una sección del portal y con el ciclo de vida cerrado.

---

### 5.5 Informes, scripts y ejecución determinista

**Qué hace.** Compone informes con tablas deterministas por plantilla y valoración de la IA sujeta
a aprobación o edición humana.

**Garantiza.**
- **Las tablas las calcula código, no el modelo.** La IA valora; no inventa cifras.
- Ningún script se ejecuta sin **auditoría AST + sandbox + aprobación** (I13).
- El formulario de un script se pinta desde un `ui_contract` que manda el servidor: el frontend no
  conoce los campos a priori (I6).
- Toda ejecución deja `RunManifest`: qué se ejecutó, con qué versión y con qué datos.

**Superficie.** `modules/redaccion/` · `redaccion_*_router` (plantillas, workspaces, scripts,
gráficos, manifiestos) · [`REDACCION_CONTRACT_FIRST.md`](REDACCION_CONTRACT_FIRST.md).

**Invariantes.** I13, I6.

**Madurez**: `construido` — utilizable de punta a punta; el caso guía es el informe de seguimiento.

**Cerrado por el bloque FUN**, y merece recordarse porque explica §5.12: hasta entonces el código
aprobado **se incrustaba copiado** en cada plantilla, así que dos plantillas con la misma
extracción eran dos copias y dos aprobaciones, y un error se arreglaba N veces. Hoy se referencia
por `funcion_id@versión`.

---

### 5.6 Identidad, roles y multitenencia

**Qué hace.** Dice quién es cada quien, qué puede hacer y a qué organización pertenece.

**Garantiza.**
- Cuatro roles: `superadmin` (plataforma), `admin` (una organización), `informer` (valida
  respuestas), `user`.
- **La identidad de administración es `HubUser` con `role='admin'`**, con lo que varias personas
  pueden administrar la misma organización. `AdminAccount` se queda con el partner y la
  facturación. Decisión escrita en [`DECISION_IDENTIDAD_DE_ADMINISTRACION.md`](DECISION_IDENTIDAD_DE_ADMINISTRACION.md).
- **Acceso por módulos concedidos, no por roles nuevos**: `chatbots`, `curacion`, `informes`,
  `personas`, `registro`, `plataforma`. El catálogo es tabla (I4). El superadmin no necesita
  concesión.
- Toda consulta que sirva datos de inquilino se acota con `scope_query_to_orgs`, y **la lista vacía
  significa «ninguna»** (I5, I8).
- Contraseña local para personas, con interruptor `LOCAL_USER_LOGIN_ENABLED` para apagarla cuando
  llegue el SSO. Cualquiera puede cambiar la suya, exigiendo siempre la actual.

**Superficie.** `core/auth/` (`tenancy.py`, `modulos.py`, `pat/`) · `core/ambito.py` ·
`auth_router`, `hub_users_router`, `hub_modulos_router` · `saml_auth_router`.

**Invariantes.** I5, I6, I8, I9.

**Madurez**: `producción`.

**Abierto.**
- **El SSO institucional no tiene fecha.** El mecanismo está (`resolve_role` con tres niveles,
  grupos en el claim), pero sin IdP configurado no se puede cerrar.
- **Una persona administrando varias organizaciones** no es representable hoy: `organizacion_id`
  es una columna. El camino está escrito (tabla puente que la sustituya), y nadie lo pide aún.
- **Cuatro tablas de identidad sin unificar** (`SuperAdminAccount`, `AdminAccount`,
  `ClientAccount`, `HubUser`). Merece bloque propio con inventario delante; es la parte con riesgo
  real.

---

### 5.7 Administración de plataforma y cascada de configuración

**Qué hace.** Permite configurar la plataforma sin acceso a la base de datos, que es lo que no se
le puede pedir a otra administración que despliegue esto.

**Garantiza.**
- Cascada **plataforma → organización → chatbot → configuración efectiva**. En una tabla
  `heredable`, **nulo significa «hereda de plataforma»**, y se puede **volver a heredar** por API.
- `core/auth/tenancy.py` decide **quién puede ver qué**; `core/ambito.py` decide **qué fila gana**.
  Son dos capas y no se confunden.
- El panel ofrece siempre lo que el contrato declara (I7), y las acciones que el servidor concede
  (I6).

**Superficie.** `hub_organizaciones_router` (valores por defecto), `hub_llm_configs_router`,
`hub_prompts_catalog_router`, `hub_themes_router`, `hub_opciones_router` · pantallas
`/plataforma/*`.

**Madurez**: `producción`.

**Abierto.** Bloque **PLG**: los perfiles de grafo son un `Enum` cerrado, así que **un perfil de
terceros no cabe por construcción** —contradice I4—, y las estrategias no son seleccionables por
configuración. El bloque las abre por *entry points*, con el núcleo entrando por el mismo
mecanismo, y declara los protocolos **inestables (0.x)** a propósito: han cambiado dos veces en un
mes por medición, y congelarlos hoy sería congelar errores conocidos.

---

### 5.8 Publicación, despliegue y operación

**Qué hace.** Sirve lo público en un dominio institucional y despliega sin intervención manual.

**Garantiza.**
- Reparto de rutas en un solo fragmento de Caddy: `/` portada del corpus, `/cercador` y
  `/gerencia` los buscadores, `/html/<norma>.html#art-63` sin cambiar de forma, `/api/*` y
  `/health` la aplicación, `/panel/` el panel y su login.
- **El despliegue sólo dispara con `push` a `main`.** El trabajo va en `desarrollo`; CI y DCO
  corren en las dos ramas.
- Las migraciones se aplican **antes** de cambiar la imagen, con `alembic current` en el log, y hay
  vuelta atrás si el servicio no responde.
- **Portabilidad**: el DSN por variable de entorno y los ficheros por `fsspec` (I11), así que el
  mismo código sirve en GCP, en MinIO local o en AWS cambiando variables.

**Superficie.** `deploy/vm/Caddyfile` · `.github/workflows/ci.yml`, `.github/workflows/deploy.yml` y `.github/workflows/dco.yml` ·
[`DESPLIEGUE_PROTOTIPO_GCP.md`](DESPLIEGUE_PROTOTIPO_GCP.md).

**Madurez**: `producción` — sirviendo desde el 2026-08-31; dominio institucional desde el
2026-09-02.

**Abierto.**
- El certificado caduca el **19-03-2027** y no se renueva solo.
- **Dominio y sitio de corpus por organización**: hoy es un despliegue, un dominio, un sitio
  (`CORPUS_SITE_BASE_URL` es global). Sería una columna anulable con la cascada existente.
- La pila local de `torch` se paga entera en memoria y arranque aunque se usen embeddings por API;
  hacerla extra opcional está anotado como candidato, no hecho. **El modo edge sigue
  necesitándola**, así que puede volverse opcional pero no desaparecer.

---

### 5.9 Registro de actividad IA y servicios hacia fuera

**Qué hace.** Da a una organización un sitio donde las herramientas de IA que usa **fuera** de la
plataforma —asistentes de escritorio, agentes de código, integraciones propias— declaren qué
usaron, para qué y sobre qué categorías de datos; y les ofrece la anonimización de la plataforma
para que no tengan que resolver la PII por su cuenta.

Es **registro de gobernanza**, al servicio de la conservación de registros del AI Act (arts. 12 y
26) y del registro de actividades de tratamiento del RGPD (art. 30). No es trazado técnico: el
detalle de lo que pasa dentro de la plataforma lo cubre la observabilidad interna, que desde
la issue #18 es una y no dos — hasta entonces 72 mensajes de diez módulos que corren en el
servidor salían por la salida estándar sin pasar por ella (I16).

**Garantiza.**
- **Metadatos sí, payloads no.** El contrato del evento no declara ningún campo de contenido y
  rechaza los que no declara. Mandar el prompt no lo registra: **falla con 422**. Si hace falta
  evidencia, va el **SHA-256** validado en forma, nunca el texto.
- **El servicio de anonimización no registra el texto** que recibe: ni en la base ni en el log,
  tampoco a nivel DEBUG.
- **La organización del evento se deriva del token**, no viaja en el cuerpo: mandarla es 422 y no
  se ignora en silencio.
- **Escribir exige un PAT y leer exige una sesión**, y en los dos casos al revés no se puede. Una
  sesión de navegador que escribiera permitiría fabricar entradas del registro; un PAT que leyera
  daría a cada integración una ventana a la actividad de toda la organización.
- **El MCP remoto no tiene credencial propia**: el token es el que presenta cada petición
  entrante. Un PAT en el entorno del servicio uniformaría a todos sus clientes bajo una identidad
  y el registro no distinguiría a nadie.
- **Paginar no repite ni pierde filas**: `ocurrido_en` lo declara quien registra y los empates son
  normales, así que el orden lleva desempate por `id`.
- **Quien integra recibe el contrato por el canal que use**: el esquema de la tool MCP declara
  campo a campo lo que el evento admite, y un guardarraíl impide que se separe del contrato del
  servidor. Los códigos de `categorias_datos` los sirve
  `GET /api/v1/actividad/categorias`, y el rechazo de un campo de contenido **explica la regla y
  señala `payload_hash`** en vez de decir «campo no permitido».
- **El catálogo de categorías se anuncia y no se impone**: el `POST` acepta códigos que no estén
  en él, y los sin catalogar se ven en el panel tal como llegaron. Rechazarlos convertiría «esta
  categoría no está dada de alta» en «este uso de IA no queda registrado».

**Superficie.** `contracts/actividad.py`, tabla `hub_actividad_ia` (operacional) ·
`actividad_router` y `anonimizacion_router` (`Deploy: edge`) · `mcp_server/http_server.py` y
`mcp_server/tools/actividad.py` · catálogo de categorías en `hub_vocabulary_terms`, eje
`categoria_dades`, con su semilla en `core/actividad_categorias.py` · pantalla `/registro`
(módulo `registro`) · [`REGISTRO_ACTIVIDAD_IA.md`](REGISTRO_ACTIVIDAD_IA.md).

**Invariantes.** I5, I8, I12.

**Madurez**: `producción` — desplegado el 2026-09-07, junto con VAS. El registro de actividad IA
sirve en la VM y sus rutas responden autenticadas.

**Abierto.**
- **Nadie ha registrado nada real todavía.** Lo que falta no es código: es que una herramienta
  externa se conecte con un PAT y confirme que el contrato le sirve tal como está.
- **Sin política de retención.** Un registro de conservación acabará necesitando decir cuánto se
  guarda y qué pasa después; hoy crece sin límite y sin purga.
- **Las categorías sembradas están pendientes de validación** por quien lleve el registro de actividades
  de tratamiento. Son un punto de partida convencional; cambiarlas es un `UPDATE`, y por eso el
  catálogo vive en tabla y no en código.
- **Una organización creada después de la migración nace sin catálogo** y recibe una lista vacía.
  Asumido: sembrarlo en el alta fijaría en código un vocabulario que va a cambiar.
- **La anonimización no ofrece elegir política**, a propósito: se añade cuando un consumidor real
  diga qué necesita.
- **Sin token de servicio no personal.** El PAT pertenece a una persona, así que la actividad de
  una integración cuelga de quien emitió su token; si la reunión lo pide, es un prompt, no un
  rediseño.

---

### 5.10 Verificaciones como servicio

**Qué hace.** Presta a quien desarrolla fuera tres comprobaciones que la plataforma ya se aplica a
sí misma: el contrato de citas, el estado de vigencia de un documento del corpus y la auditoría
estática de código. Es lo que hace literal la frase «definidos los parámetros de gobernanza, la
UADTI desarrolla fuera con registro por API dentro».

Las tres son **deterministas** —la misma entrada da la misma salida—, así que exponerlas no crea
una segunda fuente de verdad.

**Garantiza.**
- **No hay segunda implementación.** Cada servicio envuelve la función que usa el motor
  (`aplicar_contrato`, `marca_de_vigencia`/`aviso_para`, `ScriptSecurityAuditor.audit`), y un test
  de paridad por servicio compara el veredicto de la API con el de la función. Si el servicio
  necesita algo que la función no da, se cambia la función y el motor lo hereda.
- **El texto no se guarda.** Ni la respuesta que se verifica ni el código que se audita tocan
  registros ni base de datos; de la auditoría se conserva sólo el SHA-256. Los dos endpoints que
  reciben material ajeno **no piden sesión de base de datos**, que es más fuerte que recordar no
  escribir.
- **Sólo la auditoría registra evento.** Auditar es un acto de gobernanza y tiene que constar
  —quién auditó qué hash, con qué nivel y cuándo—; verificar citas o consultar vigencia son
  comprobaciones sin estado, y un evento por comprobación duplicaría el registro sin decir nada
  nuevo. Está en un test para que no se «arregle» en ninguno de los dos sentidos.
- **La vigencia respeta la tenencia y el filtro cerrado**, y lo que no cumple da **404 y no «no
  validado»**: el propio título de la respuesta confirmaría que el documento existe.
- **Las reglas del auditor se publican desde el código**, leyendo sus `frozenset`. Es lo que
  permite pedirle a la UADTI que las contraste con las Guías Operativas Técnicas sin que el
  documento y el sistema puedan divergir.
- **Un scope para los tres**, `verificaciones:use`: son la misma capacidad, y partirlo obligaría a
  pedir tres permisos para un caso de uso.

**Superficie.** `verificaciones_router` (`Deploy: edge`) · `agent/citation_validator.py`
(`aplicar_contrato`), `services/retrieval/vigencia.py`, `redaccion/services/script_auditor.py`
(`REGLAS`, `caja_de_herramientas`) · `core/urls.py` · `mcp_server/tools/verificaciones.py` ·
[`GOVERNANCA_PER_API.md`](GOVERNANCA_PER_API.md) §4.4-4.6.

**Invariantes.** I1, I2, I5, I8, I13.

**Madurez**: `producción` — desplegado el 2026-09-07, junto con REG, del que es prerrequisito.
Probado y verificado en vivo con un PAT real y una sesión MCP real.

**Abierto.**
- **Nadie ha desarrollado nada fuera todavía.** Lo que falta no es código: es que la UADTI diga si
  quiere la auditoría como servicio, que es la pregunta que `GOVERNANCA_PER_API.md` §5 le hace.
- **Quedan tres candidatos** sin planificar (§4.1, §4.2 y §4.3 de ese documento): los parámetros
  de gobernanza de un caso de uso, el depósito de manifiestos y los asistentes externos
  registrados con escenarios. Esperan a la primera aplicación externa real.
- **La cuota no se consume.** El plan decía «cuenta como interacción del PAT en la cuota de
  organización/mes», y el contador de SEC.4 está en **tokens**: una verificación no consume
  ninguno, y sumarle tokens falsos haría que el presupuesto que un administrador fijó en tokens se
  lo comieran operaciones que no llaman a ningún modelo. Se respeta el límite y no se inventa
  consumo. **Consecuencia asumida y anotada**: acotar el volumen bruto necesitaría un límite de
  frecuencia, que la plataforma no tiene.

---

---

### 5.11 Apartados que se mantienen solos

**Qué hace.** Un apartado del portal que se actualiza de forma permanente —jornadas, eventos,
becas— se parametriza como **sección** dentro del proceso de curación, con su patrón, su cadencia
y su responsable, y a partir de ahí la plataforma lo mantiene: ingiere lo nuevo, reingiere lo que
cambió y retira lo que desapareció.

**Garantiza.**
- **Curación una vez, automatización después.** Una sección nace en modo `manual` y sólo automatiza
  cuando alguien lo dice. En `manual`, una baja deja un aviso y **no toca el corpus**.
- **El censo se acota al ámbito rastreado.** Una pasada de sección compara contra las páginas de
  esa sección; fuera del ámbito no declara nada, ni baja ni cambio.
- **Nada entra al corpus con hallazgos bloqueantes**: la automatización no tiene menos criterio
  que el curador al que sustituye. La página bloqueada sigue siendo candidata.
- **Ninguna retirada masiva silenciosa**: por encima del umbral del ámbito (30 % por defecto) no
  se retira nada y queda el aviso con las cifras.
- **Todo lo que hace queda escrito** en un diario por pasada, con el ámbito que cubrió.
- Los parámetros de una sección **heredan del sitio**: nulo hereda, y lo puesto gana.

**Superficie.** `modules/curation/secciones.py`, `quality_job.py`, `diario.py` ·
`hub_web_sections`, `hub_crawl_runs` · `hub_sites_router` (`/hub/sites/{id}/sections`, `/runs`) ·
panel de secciones y diario en `/curation/sites`.

**Madurez**: `construido` — ciclo completo verificado contra un portal controlado (nueva que
entra, cambiada que se reingiere, desaparecida que se retira, y el resto del sitio intacto). Sin
desplegar. La receta está en `docs/SECCIONES_DINAMICAS.md`.

**Abierto.** La **caducidad editorial**: un evento que ya ocurrió sigue publicado, así que para la
plataforma no ha desaparecido y el asistente puede citarlo. No se implementa porque no es una
decisión técnica — depende de quien publica el contenido. Las cuatro opciones y a quién le toca,
en `docs/SECCIONES_DINAMICAS.md` §6.

### 5.12 El catálogo de funciones

**Qué hace.** Una extracción determinista —contar las filas de un fichero de gastos, leer los
importes de un PDF— se escribe **una vez** como *función* con su contrato declarado, y las
plantillas de informe la **referencian** por `función@versión` en vez de llevar el código
copiado. Antes de FUN, aprobar un script lo incrustaba en el bloque de cada plantilla: dos
plantillas con la misma extracción eran dos copias y dos aprobaciones, y un error se arreglaba N
veces.

**Lo que garantiza.**

- **Registrar es compartir, y es automático** (nivel 2 de la Instrucció 02/2026): declaración
  responsable + auditoría sin hallazgos críticos + sandbox superado, y la versión queda usable de
  inmediato **sin que nadie la apruebe**. La revisión humana viene después, con muestreo
  aleatorio, y puede pedir correcciones, reclasificar el alcance o suspender.
- **Una versión registrada es inmutable y el anclaje aguanta**: publicar la v2 **no cambia
  ninguna plantilla** anclada a la v1. Adoptar es una decisión de quien mantiene la plantilla.
- **Nada falla en silencio**: una función retirada o suspendida hace fallar el bloque anclado en
  alto, con el nombre y el motivo.
- **Dos responsabilidades separadas**: suspender es de quien revisa, retirar de quien escribe, y
  revisar es siempre de otra persona.
- **Dos orígenes por el mismo camino**: *autoservicio* (el código vive en el catálogo, con
  sandbox) y *empaquetado* (el código vive en el repositorio de un equipo y llega por *entry
  point* `govgenai.funciones`, con anclaje por mayor de semver). Un solo contrato, un solo
  validador, un solo resolutor.
- **Se puede ejecutar desde fuera** con un PAT y el scope `funciones:execute`, con versión
  explícita y un evento en el registro de actividad de IA — metadatos, nunca payloads.

**Dónde vive.** `modules/redaccion/funciones_service.py`, `funciones_acciones.py`,
`funciones_resolver.py`, `funciones_paquete.py`, `contracts/funciones.py`; routers
`/api/v1/funciones` y `/api/v1/funciones/{id}/run`; catálogo y cola de revisión en
`/redaccion/funciones`.

**Madurez**: `construido` — ciclo completo recorrido contra la base de desarrollo (registrar sin
aprobación, dos plantillas ancladas a v1, publicar v2 sin tocarlas, adoptar v2 en una, suspender
con motivo y ver fallar sólo esa, reactivar), más el paquete demo instalado y desinstalado de
verdad. Sin desplegar. El contrato completo está en `docs/CATALOGO_FUNCIONES.md`.

**Abierto.** La **equivalencia con la regla 2 de la Instrucció** necesita un «sí» explícito de la
UADTI y de la OIATI: la Instrucció prevé que el código del desarrollo ciudadano se quede en el
equipo de la persona, y aquí se registra en la plataforma y corre sobre los datos
institucionales. Es un régimen distinto —más controlado en unas cosas y más expuesto en otras— y
la plataforma no puede decidir por su cuenta que equivale. La comparación honesta está en
`docs/CATALOGO_FUNCIONES.md` §4. También pendiente: contrastar las reglas del auditor AST con las
Guías Operativas Técnicas de la UADTI.

---

## 6. Automatización gobernada

**Propósito.** Que una organización sepa qué automatizaciones circulan, quién las usa y con qué
versión, sin ejecutarlas necesariamente. **Sustituye a la «Fase 2 — Automatización documental»**
el 2026-09-23: de aquel plan, la migración de la interfaz quedó vacía al retirar el cliente
NiceGUI, y la de servicios está hecha bajo otros nombres —el catálogo de funciones (§5.12), el
sandbox, el `RunManifest`, el registro de actividad y las verificaciones por API y MCP (§5.9,
§5.10)—. Lo único que quedaba era el agente de ejecución local, y **se descarta** (§10).

**Lo que falta, y que es el tema 4 de [`ROADMAP.md`](../ROADMAP.md)**:

- **Funciones de origen externo**: un cuaderno o un script que corre fuera se registra por su
  hash, con declaración responsable y sin ejecutarlo. Registrar es el canal de compartición; la
  plataforma no puede impedir que se ejecute fuera, y lo dice.
- **Gobernanza para agentes de código**: configuración MCP y *skill* publicadas, para que usar
  `auditar_codigo`, `anonimizar_texto` y `registrar_actividad` sea el camino fácil. Por MCP el
  cumplimiento es **voluntario**, y eso no se disimula.
- **Funciones de tarea**: artefactos de salida, red saliente sólo hacia **orígenes declarados** y
  el ecosistema de módulos ampliado. Abrir la red debilita el argumento de §5.12 («una función no
  puede hablar con nada»), así que es una **clase distinta**, visible y con revisión en plazo.

**Madurez**: `previsto`, sobre una base `construido`: lo que ejecuta ya existe.

**Abierto.** El régimen de ejecución, la lista del ecosistema autorizado y quién asume la
revisión posterior son decisiones de la institución, no del código.

---

## 7. Trámites asistidos con IA

**Propósito.** Que una fase de un procedimiento pueda apoyarse en la IA —baremar, redactar un
informe técnico, redactar una resolución— con las garantías del módulo de informes, y que el
resultado vuelva al expediente. **Sustituye al «Gestor de expedientes» de la Fase 3** el
2026-09-23: las administraciones ya tienen gestor, y construir otro lo duplicaba. El plan
anterior lo había adoptado a medias —su nota del 2026-09-01 ya hacía del gestor institucional la
fuente de verdad— pero seguía construyendo tablas de expedientes, grafo con checkpointing,
bandeja de aprobaciones y adaptadores que leen y publican.

**Garantías que el módulo debe cumplir**, y que condicionan el diseño de hoy:

- **El estado del procedimiento tiene un solo dueño, el gestor.** La plataforma **no lo cambia
  nunca**: entrega un resultado y su evidencia. Validar aquí valida el contenido generado; el
  acto administrativo —firmar, notificar, avanzar de fase— sigue en el gestor.
- **HATEOAS estricto**: el frontend **nunca** calcula qué acciones caben. El servidor devuelve
  `acciones_permitidas` sobre la ejecución del trámite, que es lo único que la plataforma posee,
  evaluando estado, clase y rol (I6). Quien no tenga el módulo recibe un array vacío.
- **El cloud orquesta, el edge ejecuta**: con el gestor y la plataforma en el mismo perímetro
  institucional se cumple sin agente ni WebSocket. Es dónde está la máquina, no un programa en el
  escritorio (§10).
- **Un trámite referencia `plantilla@versión` y `función@versión`**, nunca código incrustado.
- **Dos modos de creación y el mismo rastro**: a mano en la plataforma, indicando la referencia
  del expediente, o desde el gestor por API. El manual es el primero y es también el repliegue si
  el gestor no puede llamar hacia fuera.
- **La baremación es determinista y siempre verificada por una persona** (§10).

**Madurez**: `previsto`. Prerrequisito externo: qué gestor, qué puede hacer y con qué entorno de
pruebas. **Ningún dato real entra** antes de que el uso esté clasificado: este módulo sí toca
actuación administrativa y la baremación evalúa a personas, así que no hereda la clasificación de
riesgo de los asistentes informativos.

El detalle, con sus hitos, en el tema 8 de [`ROADMAP.md`](../ROADMAP.md).

---

## 8. Lo pendiente, y por qué está donde está

El detalle vivo —qué bloque, qué prompt, qué modelo sugerido— está en
[`PROJECT_STATE.md`](../planificacion/PROJECT_STATE.md), que es la fuente de verdad del progreso.
Aquí sólo el mapa, para que quien llegue sepa dónde puede aportar:

La vista pública, por temas y con estado, es [`ROADMAP.md`](../ROADMAP.md), que enlaza cada tema
con sus *issues* y sus hitos. Aquí sólo lo que queda por construir y de qué depende:

| Qué | Qué resuelve | Depende de |
|---|---|---|
| **Automatización gobernada** (§6) | Registrar lo que corre fuera y ampliar el catálogo a tareas completas | Decisiones de la institución para el paso a régimen definitivo |
| **Trámites asistidos** (§7) | Baremación, informe de fase y resolución invocables desde el gestor | Qué gestor y con qué entorno; clasificación de riesgo antes de datos reales |
| **RHR** | Revisión humana de respuestas — **el hueco medido de la abstención** | Anotación por lotes |
| **PRC** | El catálogo de procedimientos en el asistente | **Bloqueado**: fichas validadas + consulta de descarga |
| **MT.8** | Vista y permisos por organización, segunda fase de la multitenencia | El piloto en marcha |

**Los mejores puntos de entrada para alguien de fuera**, por criterio de alcance cerrado y riesgo
bajo: el **registro de cuadernos externos** del tema 4 (no ejecuta nada, y ataca un problema real
de cualquier organización que trabaje con cuadernos) y el **informe de fase** del tema 8, que
reutiliza entero el módulo de informes y sirve para probar lo demás.

---

## 9. Cómo se prueba lo que aquí se afirma

**TDD obligatorio**: el test antes del código de producción. Y una jerarquía deliberada:

| Nivel | Qué corre | Cuándo |
|---|---|---|
| Ficheros de test tocados | segundos | durante el desarrollo |
| Directorios tocados + `tests/infra/test_suite_hygiene.py` | segundos a 1 min | al cerrar un cambio |
| `uv run pytest tests` completo | 15-100 min | al cerrar un bloque |

**Guardarraíles que hacen cumplir los invariantes**, y que son la parte de la suite que más protege
a quien llega de fuera:

- `tests/api/test_router_inventory_is_walked.py` — I8 e I9: ningún router sirve datos sin acotar ni
  declara un módulo que no exige.
- `tests/api/test_tenant_isolation.py` y `test_mt16_aislamiento_dos_organizaciones.py` — I5.
- `tests/core/test_mt7_el_inventario_esta_escrito.py` — el inventario de multitenencia no puede
  quedarse viejo.
- `tests/infra/test_el_indice_de_docs_esta_completo.py` — que el índice de `docs/` los liste a
  todos y que ninguna página mande a leer una ruta `docs/…` que quien clona no tiene. Es la otra
  mitad de la pregunta que hacía el de REPO.3, que sólo miraba los enlaces markdown: las dos
  referencias muertas de la portada estaban escritas entre acentos graves y **pasaban en verde**.
- `tests/infra/test_suite_hygiene.py` — mocks sobre clases, `create_all` sobre la base del
  desarrollador, imports a módulos que ya no existen.
- El guardarraíl de I10 en `test_usr8_el_flujo_del_chat_siempre_termina.py`.
- `test_reg3_anonimizacion_servicio.py` — el centinela que comprueba, con `caplog` a **DEBUG**,
  que el texto que se manda a anonimizar no llega a ningún registro.
- `test_reg4_el_mcp_remoto_esta_declarado.py` — que el despliegue del MCP remoto no reciba un
  PAT por entorno. Es el cambio más razonable del mundo para quien no sepa por qué no está.
- `test_reg7_la_tool_declara_el_contrato.py` — que las firmas de las tools MCP y los contratos
  del servidor no divergan (el evento de REG y las peticiones de VAS). Vive del lado del servidor
  porque `mcp_server/` no puede importar `server.app`, y comprobarlo exige tener los dos delante.
- Los tres tests de paridad de VAS: `test_vas1_citas.py`, `test_vas2_vigencia.py` y
  `test_vas3_codigo.py` comparan el veredicto de cada servicio con el de la función que usa el
  motor. Son lo que impide que la comprobación de fuera deje de ser la de dentro.
- `test_vas2_el_pat_lleva_su_organizacion.py` — recorre `PatService.verify` **sin sobreescribir
  el principal**, que es el camino que ningún test de PAT recorría y por donde se colaron dos
  defectos: un PAT sin organización y, con él, `POST /actividad` respondiendo 403 a todo
  integrador real.
- `test_profile_contract.py` — todo perfil que no esté declarado sin configurar tiene que compilar
  y ejecutar.
- `test_img1_ci_construye_y_arranca_la_imagen.py` — que el job `imagen` siga construyendo **los
  `Dockerfile` del despliegue**, sin extras y sin dependencias de desarrollo, y arrancando el
  contenedor hasta `/health`. El conjunto de dependencias que se despliega era el único que no
  probaba nadie, y eso costó 35 minutos de producción caída el 2026-09-15.
- Gate de regresión de recuperación: falla si `recall@5`, `recall@10` o `MRR` bajan más de 0,02
  respecto a la línea base versionada.

**Dos trampas del entorno que cuestan una tarde si nadie las dice:**

- La suite se ejecuta **desde Git Bash**, no desde PowerShell: `test_setup_script.py` invoca `bash`,
  que en PowerShell resuelve al lanzador de WSL y da diez rojos de entorno.
- **CI corre con `-n0` a propósito.** El paralelismo esconde el estado filtrado entre tests, que es
  justo lo que se quiere cazar. En local manda la velocidad; en CI, la detección.

**Y una lección del proyecto que conviene leer antes de reportar un hallazgo**: en varias ocasiones
una cifra extrema resultó ser un defecto del instrumento y no del sistema, y un guardarraíl llegó a
pasar en verde **recorriendo un directorio inexistente**. Ante un 0, un 100 % o un verde
sospechoso, primero se comprueba que el test mide lo que dice medir.

---

## 10. Qué NO hace la plataforma

Límites deliberados. Están aquí para que nadie los implemente por iniciativa propia creyendo que
faltan:

- **No da asesoramiento jurídico.** Informa citando la norma; la interpretación es de quien tiene
  competencia.
- **No decide.** La IA propone y valora; aprobar es de una persona, y eso es estructural.
- **No genera código de motor en runtime.** Se descartó explícitamente: las estrategias son
  enchufes y los perfiles colecciones, pero el código llega por instalación, no por formulario.
- **No comparte corpus entre chatbots.** Está decidido y no hay que volver a proponerlo.
- **No lleva conversor de documentos en el servidor.** Al corpus entra `.md` conforme al contrato;
  si algo hay que convertir, se convierte antes de llegar.
- **No rastrea portales de la red interna.** El rastreador sólo pide direcciones públicas (I15).
  Esto **va a hacer falta** algún día —una intranet es un portal institucional como otro—, y
  cuando haga falta es una decisión con su diseño: a quién se le permite, contra qué destinos y
  con qué registro. Lo que no es, es quitar el guardia. La válvula
  `CRAWLER_ALLOW_PRIVATE_TARGETS` existe para el portal de pruebas local y producción no arranca
  con ella.
- **No hay shims de compatibilidad.** Si una ruta o un símbolo se retira, se retira: el historial
  de git es la fuente de verdad del pasado.
- **No aísla el código de una función empaquetada.** Una función que llega por *entry point*
  corre **in-process, sin sandbox y con los datos del cliente**: la confianza está en quien la
  instala en el despliegue, igual que en un plugin de pytest. Está aquí y no en la lista de lo
  que falta porque es una decisión: fingir un aislamiento que no existe sería peor que decirlo.
  Lo que sí se valida siempre es la entrada contra su contrato y la salida como `ExtractionResult`.
- **No ejecuta nada en la máquina de quien la usa.** Sin agente de ejecución local: ni RPA, ni
  vigilancia de carpetas, de correo o de web, ni programador de flujos locales, ni *thin client*.
  **Decidido el 2026-09-23**, y hasta entonces este punto vivía aparte porque era un hueco y no
  una decisión. Lo que lo cierra es que los agentes de propósito general con acceso al navegador
  y al escritorio ya cubren ese terreno, en el régimen que las normas de desarrollo ciudadano
  reservan al uso personal; lo que ellos no dan —registro, ecosistema autorizado, revisión
  posterior, anonimización— es lo que la plataforma aporta, y es el tema 4 de
  [`ROADMAP.md`](../ROADMAP.md). Existió como aplicación NiceGUI y se retiró completa el
  2026-09-04 (574 ficheros), con el mapa fichero a fichero en
  [`INVENTARIO_RETIRADA_LEGACY.md`](INVENTARIO_RETIRADA_LEGACY.md).
- **No accede a la nube personal de quien la usa** con credenciales centralizadas: unidades y
  documentos compartidos. La persona sube y descarga; lo que necesite sus credenciales corre
  fuera y se registra. Es el corolario del punto anterior, y lo que las normas de desarrollo
  ciudadano llaman soberanía local.
- **No lleva un gestor de expedientes.** El de la institución es la fuente de verdad del
  procedimiento, y la plataforma **no cambia nunca su estado**: entrega trámites asistidos
  —baremación, informe de fase, resolución— con su evidencia, y quien decide qué hacer con el
  resultado es el gestor. Decidido el 2026-09-23; es §7 y el tema 8 de [`ROADMAP.md`](../ROADMAP.md).
- **No puntúa personas con un modelo.** En una baremación el modelo extrae hechos y redacta la
  motivación; los hechos los verifica una persona y la puntuación la calcula una función
  determinista con el baremo como dato versionado. Es la regla «las tablas las calcula código»
  (§5.5) aplicada a algo que evalúa a personas, y por tanto no negociable.

**Consecuencia para la frontera edge-cloud**, que conviene no malinterpretar: el «modo edge» de
`AGENTS.md` es el servidor desplegado **en la nube del cliente**, no un proceso en su puesto de
trabajo. Los dos modos de despliegue que existen hoy corren el mismo servidor FastAPI, y la
garantía de que los datos no salen de la institución la da dónde está la máquina, no que haya un
programa en el escritorio.

---

## 11. Cómo mantener este documento honesto

Un documento de especificaciones que envejece es peor que no tenerlo, porque miente con autoridad.
Tres mecanismos, en orden de fuerza:

1. **Un test lo comprueba**: `server/tests/infra/test_especificaciones_no_miente.py`. Verifica
   que todos los ficheros y tests que este documento nombra existen, y que los vocabularios que
   enumera —los cuatro ámbitos, los cuatro roles, los tres modos de lengua, los módulos del
   catálogo, los modos de recuperación, los módulos de negocio— son **exactamente** los que el
   código declara. Un valor nuevo o renombrado pone la suite roja, y entonces alguien actualiza
   la única página donde esto se puede consultar. Es el patrón de
   `test_mt7_el_inventario_esta_escrito.py`, y es lo que convierte este documento en verdad
   comprobable en vez de en una foto vieja.

   **Lo que el test no comprueba es la prosa**, y eso hay que decirlo: puede garantizar que
   `enforce_citation_contract` existe, no que siga rindiéndose sin cita. Para eso están los
   tests de cada capacidad, que §9 enumera.
2. **La regla de qué va aquí.** Si un cambio altera lo que el sistema **garantiza**, se actualiza
   este documento en el mismo *commit*. Si sólo altera **el estado del desarrollo**, no se toca:
   eso es `PROJECT_STATE.md`.
3. **Nada de fechas incrustadas** salvo las que son un hecho (un certificado que caduca, una
   medición). La madurez se expresa en cuatro palabras, no con un porcentaje que hay que revisar.

---

## 12. Glosario

| Término | Qué es |
|---|---|
| **Organización** | El inquilino: una universidad, una diputación, un ayuntamiento. `HubOrganizacion` |
| **Partner** | Quien despliega y factura. Puede tener varias organizaciones |
| **Ámbito** (`__ambito__`) | De qué nivel es una tabla: `plataforma`, `organizacion`, `heredable` o `derivada` |
| **Cascada** | Plataforma → organización → chatbot → configuración efectiva. Nulo hereda |
| **Perfil de grafo** | Qué composición de estrategias monta un asistente (`PUBLIC_KB_RICH`…) |
| **Estrategia** | Un enchufe por eje: recuperación, fusión, plantilla, lengua |
| **Modo de recuperación** | `RAG`, `MD_LONG_CONTEXT` o `MD_AGENT_SELECTOR` |
| **Edge node** | Despliegue en la nube del cliente que ejecuta lo operacional |
| **Curación** | Decidir qué contenido de un portal entra al corpus, y cuándo |
| **`RunManifest`** | El registro de qué se ejecutó, con qué versión y sobre qué datos |
| **Bloque** | Unidad de trabajo del plan: una fila de la tabla de `PROJECT_STATE.md` |
