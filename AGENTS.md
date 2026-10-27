# Instrucciones para agentes de programación

## Contexto del proyecto

Gov Gen AI Platform es el resultado de integrar **AI Agents Hub** (chatbots RAG, LangGraph) y **AutomatIA**
(automatización, scripts, RPA) en un monorepo. El plan de desarrollo completo está en `planificacion/PLAN_DESARROLLO.md`.

**El cliente NiceGUI se retiró completo el 2026-09-04** (bloque NIC): `client_app/` y `_legacy_nicegui/` ya no existen, y con ellos 574 ficheros. Nada en producción dependía de él, y lo que hubo está fichero a fichero en `docs/INVENTARIO_RETIRADA_LEGACY.md`.

**El agente de ejecución local no se hace, y es una decisión del 2026-09-23**, no un hueco: ni RPA, ni vigilantes de carpeta, correo o web, ni programador de flujos locales, ni *thin client*. Lo cubren los agentes de propósito general; lo que la plataforma aporta es gobernanza. **No lo propongas.** Razón en `docs/ESPECIFICACIONES.md` §10 y tema 4 de `ROADMAP.md`.

**Tampoco se hace un gestor de expedientes** (misma fecha): el de la institución es la fuente de verdad y la plataforma **nunca cambia su estado**. Lo que se construye son **trámites asistidos** —un workspace de Informes con referencia al expediente—. Tema 8 de `ROADMAP.md`.

**La hoja de ruta pública es `ROADMAP.md`**: `planificacion/` dirige el desarrollo y `ROADMAP.md` lo cuenta fuera.

---

## Ejecución agéntica por bloques

El desarrollo se ejecuta **de forma autónoma y secuencial, por bloques**. Un bloque es un **hito de
GitHub con sus *issues***, y el alcance de cada paso está en el cuerpo de su *issue*. El estado
del desarrollo se lee de ahí, no de un fichero. La Fase 1 se escribió como prompts en
`planificacion/fase1/`, con un cursor en `planificacion/PROJECT_STATE.md` que ya no se actualiza.

**El bloque es la unidad de interacción: una vez arrancado, no informes hasta cerrarlo.** No pidas
confirmación entre pasos. El protocolo completo —qué es un bloque, cómo se arranca, el informe de
cierre— está en `docs/METODOLOGIA_AGENTICA.md`.

### El bucle por paso

```
RED → GREEN → REFACTOR → verificaciones de cierre → actualizar el estado → un commit firmado
```

**Actualizar el estado** es que el commit cierre su *issue* y escribir la fila del historial: ver
«Seguimiento del estado del proyecto», más abajo.

Las **verificaciones de cierre** son: suite verde en los directorios tocados, migración aplicada,
contrato regenerado si cambió la API, retirada del legacy comprobada con `grep -r` a cero, y
verificación en navegador si toca UI.

**Un commit Conventional por paso**, con el número de la *issue* en el asunto —o el identificador
del prompt en la Fase 1—, **firmado** (`git commit -s`), sin `Co-Authored-By` y **sin push**. Es lo
que hace reversible un bloque largo: si el paso 5 rompe lo que hizo el 3, hay un punto exacto al
que volver.

**Si el commit resuelve una issue, lleva `Closes #N`** en su cuerpo o en el de la PR. Un asunto
`fix(#92):` no cierra nada, y se acumulan resueltas y abiertas: pasó con once. Lo comprueba CI.

**Los avisos de GitHub los revisa `avisos.yml`, no tu memoria**: alertas de Dependabot al
desplegar, hilos de Copilot al mezclar. Tras decidir sobre un comentario de Copilot —arreglarlo o
rebatirlo— **resuelve el hilo**; si no, la PR queda roja. Razón en el test homónimo.

**Una issue resuelta a medias se retitula por lo que queda, no por lo que se encontró**, y lo ya
hecho va **arriba del cuerpo**, no en un comentario al final. Una issue abierta cuyo título dice
«Ningún contenedor tiene límite de memoria» afirma eso mientras siga abierta, aunque los techos
lleven dos días desplegados — y el backlog es lo primero que lee quien evalúa el proyecto. Pasó:
un análisis externo puntuó la disponibilidad sobre un defecto corregido, leyendo #149 y #2. Es el
mismo defecto que obligó a renombrar un hito, y la misma regla que `docs/ESPECIFICACIONES.md`:
**un rótulo que miente hace que nadie mire lo que hay dentro.**

### Se trabaja en `desarrollo`; `main` es para desplegar

**Nunca commitees ni empujes a `main`.** `deploy.yml` dispara con `push: branches: [main]` y sólo
con eso, así que empujar a `desarrollo` comprueba pero no despliega. El paso a `main` es decisión
del usuario, por bloque o conjunto de bloques.

CI y DCO **sí** corren en `desarrollo`. Y **`deploy.yml` no lleva esa rama**: si alguna vez aparece
ahí, desaparece la separación. La regla nació el 2026-09-02, después de que un commit que sólo
tocaba un guion de publicación desplegara producción entera.

### Todos los commits van firmados (DCO)

`git commit -s`, que añade `Signed-off-by: <autor>`. Certifica que quien commitea tiene derecho a
aportar ese código bajo la licencia del proyecto (AGPL-3.0-or-later).

**La firma es del autor humano, no del agente**, y por eso no se añade `Co-Authored-By`: la línea
que importa certifica procedencia, y sólo la puede certificar una persona. Se exige también al
mantenedor —quien se exceptúa de su propia política la deja sin fuerza— y lo comprueba
`.github/workflows/dco.yml`. Detalle en `DCO` y `CONTRIBUTING.md`.

### Qué tests ejecutar y cuándo (escalonado)

| Cuándo | Qué | Coste |
|---|---|---|
| **Durante el prompt** | Solo el fichero de tests que estás escribiendo | segundos |
| **Al cerrar el prompt** | Los directorios que el prompt toca + `tests/infra/test_suite_hygiene.py` | segundos a 1 min |
| **Al cerrar el bloque** | `uv run pytest tests` completo, **desde Git Bash** | minutos a una hora |

- `test_suite_hygiene.py` va en el nivel intermedio porque tarda medio segundo y caza lo que se
  escapa de un subconjunto: mocks sobre clases, `create_all` sobre la BD del desarrollador,
  imports a módulos que ya no existen.
- **Desde Git Bash, no desde PowerShell**: `test_setup_script.py` invoca `bash`, que en PowerShell
  resuelve al lanzador de WSL y da diez rojos de entorno.
- **CI corre con `-n0` a propósito.** El paralelismo esconde el estado filtrado entre tests, que es
  justo lo que se quiere cazar. En local manda la velocidad; en CI, la detección. No añadas
  `-n auto` a CI.
- **Si una cifra de tests no se ha medido, no se reporta como medida.**

### Cuándo SÍ interrumpir a mitad de bloque

Solo por estas cuatro causas. Detalle en `docs/METODOLOGIA_AGENTICA.md` §3.

1. **Operación de riesgo** — la detecta la guarda. No la fuerces ni busques rodeos.
2. **Decisión de criterio** — ambigüedad que llevaría a productos distintos, arquitectura que el
   plan no cierra, o alcance que excede el bloque. Usa `AskUserQuestion` con recomendación.
3. **Fallo persistente** — un RED que no llega a GREEN, o suite en rojo por causa no atribuible al
   prompt. Para y reporta **con el output real**; no marques el prompt como cerrado.
4. **Prerrequisito externo ausente** — BD apagada, Docker cerrado, credencial que falta.

### Cuándo NO interrumpir

- **Desviaciones entre el plan y el código real.** Aplica la interpretación más fiel al espíritu
  del prompt, sin inventar infraestructura ni añadir features no pedidas; regístralo como
  *«desviación documentada»* en `planificacion/HISTORIAL.md` y sigue.
- Fallos de test preexistentes ya inventariados.
- Dudas de estilo o estructura resolubles con las reglas de este documento.

Enumerar cuándo **no** interrumpir es tan importante como lo contrario: sin esta lista se pregunta
por todo, y la supervisión se degrada a aprobación automática.

### Al arrancar y al cerrar

- **Al arrancar**: lee las *issues* del hito verbatim (`gh issue list --milestone`), y si alguna
  sugiere un modelo más capaz que el de la sesión, dilo **una sola vez antes de empezar**.
- **Al cerrar**: un solo informe con los ocho puntos de `docs/METODOLOGIA_AGENTICA.md` §7 —el
  octavo es la línea sobre `docs/ESPECIFICACIONES.md`—. Después **espera**: el siguiente bloque no
  arranca solo.

---

## Regla crítica: migración = código nuevo + retirada del legacy

Una tarea de migración **no está completa** hasta que el código original quede retirado.
No dejes código muerto, imports sin usar, archivos vacíos ni comentarios `# TODO: migrate`.

**Se retira borrando.** El historial de git es la fuente de verdad del pasado: los ficheros
siguen ahí con su contexto y sus mensajes de commit, y esa referencia viaja con el repositorio y no
se puede perder.

**Hubo una cuarentena, `_legacy_nicegui/`, y se retiró el 2026-09-04 junto con `client_app/`.**
Dejó de servir cuando se midió: 48 de los 67 ficheros candidatos tenían quien los importara, así
que no se vaciaba fichero a fichero, y el propio `client_app/` ya no compilaba. Una cuarentena que
nadie puede vaciar y que contiene código que no arranca no es referencia, es ruido con aspecto de
código vivo. La medición está en `docs/INVENTARIO_RETIRADA_LEGACY.md` §4 y §5.

**No la reconstruyas.** Si necesitas ver cómo lo hacía el NiceGUI: `git log --diff-filter=D --
client_app/`, la carpeta `AutomatIA` o el *bundle* de GenGov. Lo que **no** se hace es volver a
crear un directorio de código muerto dentro del árbol.

### Definición de "migración completa" (checklist obligatorio)

Antes de cerrar cualquier tarea de migración, verifica y ejecuta cada punto:

- [ ] La nueva implementación tiene tests que pasan (`pytest` o equivalente)
- [ ] El endpoint o servicio nuevo está integrado y verificado end-to-end
- [ ] El archivo o módulo legacy está **eliminado** del árbol de trabajo
- [ ] Los imports del legacy han sido eliminados de todos los ficheros que los referenciaban
- [ ] No quedan referencias al código eliminado en ningún fichero del proyecto (`grep -r` antes de cerrar)
- [ ] El `docker compose up` + suite de tests completa sigue pasando tras la retirada

---

## Normas generales de limpieza

**Borra, no comentes.**
Si el código ya no se usa, elimínalo. Los comentarios `# deprecated`, `# old version` o `# legacy`
son deuda técnica disfrazada. El historial de git es la fuente de verdad del pasado.

**No hay directorio de cuarentena.** `_legacy_archive/` y `_legacy_nicegui/` ya no existen, y no
se crea otro: lo retirado se borra.

**Sin backwards-compatibility shims.**
No renombres variables a `_old_foo`, no re-exportes símbolos eliminados, no añadas
comentarios `# removed` donde había código. Si algo se elimina, se elimina limpiamente.

**Sin código muerto especulativo.**
No dejes funciones, clases o módulos "por si acaso se necesitan en el futuro".
Si no se usa ahora, no existe.

---

## Estructura de módulos y dónde vive cada cosa

```
server/app/modules/agents_hub/   ← RAG, LangGraph, chatbots, ingesta del corpus (105)
server/app/modules/redaccion/    ← informes, plantillas, scripts, ETL, anonimización (96)
server/app/modules/curation/     ← curación de portales (29)
server/app/modules/automation/   ← estrategias de extracción, llm_gateway (4)
server/app/core/                 ← servicios compartidos: LLM gateway, auth, tenancy, storage
server/app/routers/              ← la superficie HTTP, etiquetada `Deploy: cloud|edge|shared`
frontend/src/admin/              ← panel admin hub + plataforma (64)
frontend/src/shared/             ← i18n, cliente generado por Orval, componentes comunes (61)
frontend/src/redaccion/          ← UI de informes, scripts y anonimización (53)
frontend/src/curation/           ← UI de curación de portales (22)
frontend/src/widget/             ← chatbot público embebible (6)
mcp_server/                      ← servidor MCP, stdio y remoto. NO importa `server/app`
```

Las cifras son ficheros versionados y están para dar escala, no para cuadrar: lo que importa es que
`redaccion/` es casi tan grande como `agents_hub/` y `automation/` no es un módulo, son cuatro
ficheros.

**Tres advertencias, y las tres son rutas que se escriben de memoria y no existen.**
`server/app/modules/automation/` tiene **cuatro** ficheros: lo que la planificación llamaba
«automatización» aterrizó en `redaccion/`. **No hay** un `automation/` ni un `agent/` bajo
`frontend/src/`. Y **el bloque REG no dejó un paquete Python**: su «módulo registro» es una fila de
`hub_modules` —una unidad de licencia, lo que comprueba `require_module` con la clave `registro`—,
y su código son `routers/actividad_router.py` y `core/actividad_categorias.py`. Los tres son rutas
que se escriben de memoria; un guardarraíl comprueba que las que cita este fichero existan, y
saltó con las tres.

**Si un plan da por hecho el nodo de ejecución local, el plan está desactualizado.**

---

## Verificación de UI: navegador primero, humano al final del bloque

Cuando un prompt toca frontend, **el agente lo verifica él mismo en el navegador** con la extensión de Chrome (`mcp__claude-in-chrome__*`), dentro del bloque y sin pedir permiso: navega a la URL, comprueba el contenido con `read_page`/`find`, interactúa con `computer`/`form_input`, y revisa `read_console_messages` y `read_network_requests` en busca de errores que los tests unitarios no ven. Detalle del protocolo en `docs/METODOLOGIA_AGENTICA.md` §4.

Las **pruebas manuales humanas se reservan para el cierre del bloque** y se limitan a lo imprescindible: SSO SAML real, sistemas externos no simulables (G400, ENI, APIs UJI), juicio subjetivo de identidad visual, accesibilidad con lector de pantalla real y cualquier cosa con datos personales o credenciales reales.

### Qué exige pruebas manuales humanas

Solo lo que el agente **no puede** verificar con el navegador:

- Flujos con credenciales reales o IdP institucional.
- Integración con sistemas externos no disponibles en local.
- Valoración subjetiva: identidad visual, tipografía, tono del texto institucional.
- Accesibilidad con lector de pantalla real.

### Qué NO necesita pruebas manuales

- Código exclusivamente backend: tests unitarios, tests de integración, servicios, modelos ORM, workers, migraciones de BD, endpoints de API sin UI asociada.
- Comprobaciones que ya cubren los tests automáticos.
- **Todo lo que el agente ya verificó en navegador**: no se repite en el `.bat`; se menciona como verificado en el informe de cierre.
- Infraestructura, configuración o scripts sin impacto visual.


### El `.bat` de pruebas manuales

- **Uno por bloque, no por prompt**, en `pruebas_manuales/`, y **ninguno si el bloque es
  exclusivamente backend**.
- **Se escribe en ANSI cp1252 sin BOM.** `Write` guarda en UTF-8 y CMD interpreta el BOM como
  parte del primer comando (`echo` → `ho`, `pause` → `ause`), así que hay que usar PowerShell y
  comprobar que los primeros bytes son `40 65 63 68`.
- Formato, contenido mínimo y la plantilla de instrucciones al usuario: en
  `docs/METODOLOGIA_AGENTICA.md` §4.3 y §7.1.

---

## Migraciones Alembic: aplicar automáticamente

Cuando un prompt cree o modifique ficheros en `server/migrations/versions/`, **aplica la migración
al terminar** ejecutando desde `server/`:

```
uv run alembic upgrade <revision_id>
```

donde `<revision_id>` es el ID de la última migración creada en ese prompt.

**Si la BD no está arrancada** (error de conexión), detente y pide al usuario que la encienda
antes de continuar:

> "La base de datos no responde. Arranca Docker Desktop y ejecuta `docker compose up -d db`
> (o el servicio equivalente), y dime cuando esté lista para aplicar la migración."

Una vez la BD responda, aplica la migración y muestra el resultado de `alembic current`
para confirmar que la revisión ha quedado registrada.

### El esquema lo define Alembic, y sólo Alembic (BD.2, 2026-09-04)

**La aplicación no crea tablas.** Hasta BD.2 el arranque hacía `create_all` sobre los tres
metadatos además de lo que Alembic aplica en el despliegue, y esa segunda fuente **nunca borra lo
que dejó de estar declarado**: así quedaron 36 tablas de modelos retirados en la base de desarrollo
sin que nada lo dijera, y tres columnas `nullable=True` en su migración y `NOT NULL` en su modelo
durante semanas, también en producción.

Cuatro consecuencias prácticas:

- **Un modelo nuevo o cambiado va con su migración en el mismo commit.** `alembic check` corre en
  CI después de `alembic upgrade head` y se pone rojo si los modelos y la cadena difieren.
  Ejecútalo en local antes del push: `uv run alembic check` desde `server/`, con la BD migrada.
- **`nullable=` se escribe explícito** en las columnas que importan. `Mapped[datetime]` sin él es
  `NOT NULL` por deducción de la anotación, y así nacieron las tres columnas divergentes: el
  modelo lo deducía y la migración a mano decía otra cosa.
- **Datos y esquema, en migraciones separadas, y cada `op.execute` repetible** (`IF [NOT]
  EXISTS`, `ON CONFLICT`): una migración que falla a medias se reintenta. Lo vigila
  `test_issue282_deuda_menor_del_backend.py` para las posteriores a #282.
- **Si la base no está migrada, la primera consulta falla con claridad.** Es mejor que una tabla
  aparecida en silencio. Para arrancar en local: `uv run alembic upgrade head`.

Los tests siguen creando sus bases desechables con `create_all`: eso no es la aplicación, y
`test_bd2_alembic_es_la_unica_fuente.py` vigila la diferencia.

---

## Dependencias: relockear va en el mismo commit

**Si un prompt modifica las dependencias de un `pyproject.toml`, `uv lock` en ese proyecto va en
el mismo commit.**

Lo exige CI, que instala con `uv sync --locked` en sus dos pasos de instalación. El flag está ahí
porque sin él `uv sync` **vuelve a resolver en silencio** —«The project is re-locked before syncing
unless `--locked` or `--frozen` is provided», dice uv— y un lock que no corresponde a su manifiesto
no daba ningún síntoma: el `uv.lock` de la raíz vivió así **17 días** desde que EXT.3 retiró Docling,
visible sólo como un fichero modificado que reaparecía en el árbol y que, por prudencia, nadie
commiteaba.

Corolario práctico: **no compruebes con `uv sync` a secas**, que relockea y por tanto siempre pasa.
Lo que dice la verdad es `uv lock --check` (no escribe) o `uv sync --locked` (falla si no cuadra).
Sin esto, el rojo aparece en el push y no en local.

---

## Estándares de desarrollo

- **TDD obligatorio**: escribe el test antes del código de producción. No hay PR sin tests.
- **Asincronía total**: prohibidos métodos síncronos para I/O en el servidor. Usa `async/await`.
- **Sin instanciar servicios manualmente**: usa inyección de dependencias (FastAPI `Depends`).
- **i18n obligatorio en el frontend**: ningún string hardcodeado en la UI. Usa `i18next`.
- **Sin features no pedidas**: no añadas manejo de errores, validaciones, flags ni abstracciones
  para escenarios que no están en la tarea actual.

# 🏛️ REGLAS MAESTRAS DE ARQUITECTURA Y TDD

Este proyecto (Gov Gen AI Platform) sigue una arquitectura estrictamente "Contract-First". La ÚNICA fuente de verdad es el backend. El frontend es completamente "tonto" y reactivo. 

Bajo NINGUNA circunstancia generarás código en React que contenga lógica de negocio, reglas de estado, o interfaces de datos *hardcodeadas* que no provengan del contrato del servidor.

Al implementar tests (TDD) o escribir código, DEBES aplicar las siguientes restricciones por módulo:

## 1. AutomatIA (Scripts y Flujos) - Contrato SDUI (Server-Driven UI)
* **Regla:** El frontend NO conoce los campos de un script a priori. 
* **Implementación:** El backend debe devolver un `ui_contract` (JSON Schema o similar). El frontend debe construir los formularios dinámicamente iterando sobre ese contrato.
* **TDD:** Los tests de React deben fallar si intentan buscar un campo hardcodeado (ej. `input name="email"`). Deben probar que el componente se renderiza basándose en el JSON recibido.

## 2. Gestor de Expedientes - Contrato de Estado (HATEOAS)
* **Regla:** El frontend NUNCA calcula qué acciones están permitidas (ej. no debe existir código como `if (fase === 'revision') mostrarBoton()`).
* **Implementación:** El backend es la máquina de estado. El DTO de respuesta del expediente debe incluir un array `acciones_permitidas: list[str]`, calculado en el servidor evaluando fase, estado y rol del usuario.
* **TDD:** Los tests de backend deben verificar que los usuarios sin permisos reciben un array de acciones vacío. Los tests de frontend deben verificar que los botones se generan iterando sobre `acciones_permitidas`.

## 3. LangGraph y Malla Agéntica
* **Regla de Estado:** El `ExpedienteState` o `WorkspaceState` es inmutable fuera de los contratos tipados. Los nodos solo leen y escriben sobre los campos explícitamente definidos en el `TypedDict` o Pydantic.
* **Regla de Ejecución (Invariante):** Cualquier ejecución determinista (extracción, scripts) orquestada por el grafo en el cloud DEBE delegarse al Edge Node vía WebSocket. El cloud orquesta, el Edge ejecuta.

## 4. Frontend y OpenAPI
* Usa siempre los tipos y hooks generados por Orval a partir de `openapi.json`. 
* Usa `react-hook-form` y `zodResolver`. La validación del cliente debe derivarse o estar estrictamente alineada con el contrato del backend.

## 5. Corpus normativo: clasificación revisable y coste de reindexado

El corpus del asistente normativo se clasifica por **ámbito** y **submaterias** (vocabulario en
`Descarregar_pdf\normativa_propia\vocabulari\`), y ese vocabulario **está pendiente de validación
por Secretaría General**: va a cambiar. Dos reglas lo mantienen revisable. Violar cualquiera de
las dos convierte «reclasificar el corpus» en «reindexar el corpus», y a partir de ahí el
vocabulario deja de revisarse en la práctica.

* **El vocabulario es dato, no código.** Los términos (ámbitos, submaterias, rangos, colectivos)
  viven en tabla versionada, con `vigent` y `substituit_per_codi` para renombrar y fusionar.
  **Prohibido** expresarlos como `Enum` de Python, `CheckConstraint` de Postgres o lista literal
  en el código. Los **ejes** sí son estructura (pocos y estables): esos van en `StrEnum`, porque
  añadir un eje exige de todos modos código que lo consuma.

* **La taxonomía NUNCA entra en el texto que se embebe.** En `embedding_text` solo va contexto
  **estructural** —título del documento y jerarquía de encabezados (título / capítulo / artículo)—,
  que es estable. Nunca `ambit_principal`, `submateries`, `submateries_internes` ni ninguna etiqueta
  del vocabulario, ni el ancla del artículo. Los pares bilingües del dominio (`despesa`/`gasto`)
  son puente **léxico** y van al `tsvector` de la búsqueda de texto completo, que se regenera con
  una sentencia SQL; un embedding necesita GPU y horas.

  Corolario operativo: reclasificar debe costar un `UPDATE` sobre `hub_documents`. Si un cambio de
  etiqueta te obliga a re-embeber, algo se ha colado en el texto embebido.

Contexto completo de la estrategia de recuperación en tres niveles: bloques **ING.0**, **VIS** y
**SYNC** de `planificacion/Plan_TDD_Fase1.md`.

---

## Frontera entre organizaciones (multitenencia)

**El inventario vive en [`docs/MULTITENENCIA.md`](docs/MULTITENENCIA.md)**: tabla por tabla, qué
ámbito tiene, por qué camino se llega a su organización y qué es de plataforma a propósito. Lo
mantiene honesto un test (`tests/core/test_mt7_el_inventario_esta_escrito.py`), así que se puede
leer como verdad y no como una foto vieja.

Dos reglas duras al escribir código nuevo:

- **Toda tabla de `HubConfigBase` declara su ámbito** en `__ambito__` (`plataforma`,
  `organizacion`, `heredable` o `derivada`). Una que no lo declare pone rojo el guardarraíl de
  MT.1. `hub_llm_configs` nació global sin que nadie lo decidiera, simplemente porque no había
  dónde decir lo contrario, y averiguarlo costó leer 31 tablas y 32 routers.
- **No se confunden las dos capas**: `core/auth/tenancy.py` decide **quién puede ver qué** (403 y
  acotación de listados, recibe un principal) y `core/ambito.py` decide **qué fila gana** cuando la
  configuración está puesta en dos niveles (no recibe principal). En `heredable`, **nulo significa
  plataforma y se hereda**.

## Frontera Edge-Cloud (preparación del despliegue híbrido)

El sistema se despliega en dos modos:

1. **Cloud-only** — toda la lógica corre en el servidor del partner/admin; los
   datos se anonimizan antes de enviarse al LLM. Protección de datos por contrato.
2. **Edge + Cloud** — la lógica operacional (RAG, grafos, ingesta, automation,
   tratamiento de expedientes) corre en un **edge node** dentro de la nube del
   cliente; el **cloud** (admin/partner) sólo conserva configuración
   administrativa y métricas anonimizadas. Requisito regulatorio estricto.

El mismo codebase sirve a ambos modos. Para que eso siga siendo cierto, respeta
**dos fronteras** a la vez: la de datos (modelos ORM) y la de aplicación
(routers y módulos). La línea base de este split se establece en los prompts
**9.6.5** (capa ORM, `ConfigProvider`, sync API) y **9.6.6** (`DEPLOY_MODE`,
clasificación de routers/módulos) del `planificacion/PLAN_TDD_DETALLADO.md`.

### 1. Frontera de datos (modelos ORM)

Dos `DeclarativeBase` separadas:

- **`HubConfigBase`** → se sincroniza cloud→edge. Modelos: `HubClient`,
  `HubChatbot`, `HubLLMConfig`, `HubPromptTemplate`.
- **`HubOperationalBase`** → vive sólo en el edge. Modelos: `HubDocumentChunk`,
  `HubInteraction`, `HubIngestionJob`.

**Reglas duras**:

- **Sin `relationship()` cross-base**. Si un modelo operacional necesita un
  chatbot, consulta por `chatbot_id` con un query explícito — no navegues por
  `.chatbot`. Las FK con `ondelete="CASCADE"` se conservan; la navegación ORM
  no.
- **Los servicios edge no importan modelos de config directamente**. El acceso
  a configuración pasa por `ConfigProvider` (protocolo con `LocalConfigProvider`
  por defecto; `RemoteConfigProvider` llegará cuando se implemente la sync API
  real).
- **El router `edge_sync`** (`/api/v1/edge/config`, `/api/v1/edge/telemetry`)
  es la única superficie que ve ambos mundos.

### 2. Frontera de aplicación (routers y módulos)

Clasificación, regulada en runtime por `DEPLOY_MODE=cloud|edge|all` (default
`all`, comportamiento actual):

| Capa | Cloud (admin/partner) | Edge (cliente) | Compartidos |
|---|---|---|---|
| **Routers HTTP** | `auth_router`, `hub_chatbots_router`, `hub_clients_router`, futuros `/hub/prompts`, `/hub/themes` | `hub_chat_router`, `ingestion_router`, `hub_tasks_router`, `hub_feedback_router`, futuros `/automation/*` | `edge_sync_router` (servido por cloud, consumido por edge) |
| **Módulos lógica** | El CRUD de plantillas de prompt (`server/app/routers/hub_prompt_templates_router.py`), gestión partners / billing | `agents_hub/agent/` (graph, task_runner, tools, hitl), `agents_hub/ingestion/`, `agents_hub/services/retriever`, `agents_hub/evaluation/`, **`modules/automation/` íntegro** | `core/auth`, `agents_hub/services/model_factory`, `agents_hub/services/embedding_service`, `agents_hub/services/config_provider` |

**Reglas duras**:

- **Un módulo edge no puede importar** desde un módulo cloud (ni routers ni
  servicios admin/billing/partners). La configuración se lee vía
  `ConfigProvider`.
- **Los grafos LangGraph, el task runner y los tools** son edge: no leen
  `HubChatbot` ni `HubPromptTemplate` directamente.
- **El módulo `modules/automation/` es edge**: factories, flows, ETL, PDF y
  scripts procesan documentos/expedientes del cliente. No importa routers
  cloud ni gestión admin.
- **El módulo `modules/redaccion/` es edge**: contratos de plantilla, pipelines de
  extracción, DraftingCoreGraph, LLMSpecService y RunManifest procesan documentos y
  expedientes del cliente. Los routers se etiquetan `Deploy: edge` y no importan
  módulos cloud. Ver `docs/REDACCION_CONTRACT_FIRST.md`.
- **Al registrar un router nuevo** en `main.py`, **etiquétalo** en su docstring
  (`Deploy: cloud|edge|shared`) y regístralo en la función `_register_cloud`,
  `_register_edge` o ambas.
- **La anonimización previa al LLM** es responsabilidad edge: los servicios
  edge entregan datos ya anonimizados a `model_factory`; el factory no
  anonimiza.

### Si dudas dónde va algo nuevo

Pregunta:

- ¿Toca datos del cliente final (conversaciones, documentos, expedientes,
  chunks, embeddings)? → **edge**.
- ¿Sólo toca configuración, prompts, chatbots, clientes, partners, billing,
  usuarios? → **cloud**.
- ¿Ambos? Probablemente hay que partir la responsabilidad en dos servicios.

Si violas estas reglas, bloqueas el despliegue edge. Para, reconsidera, o
razona en el PR por qué es inevitable.

---

## Infraestructura objetivo y portabilidad

El primer despliegue de producción usa **Google Cloud Platform**:

- **Base de datos**: Cloud SQL (PostgreSQL 16 + pgvector). Conexión vía Cloud SQL Auth Proxy.
- **Aplicación**: Cloud Run (FastAPI). Sin estado local: el contenedor puede destruirse en cualquier momento.
- **Almacenamiento de documentos**: Google Cloud Storage (GCS).

El codebase debe funcionar sin cambios en un segundo backend (MinIO + PostgreSQL local, AWS S3 + RDS,
etc.) cambiando solo variables de entorno. **No acoples el código a ningún proveedor concreto.**

### Reglas duras de portabilidad

#### 1. Almacenamiento de ficheros: `fsspec` obligatorio

**Prohibido** acceder directamente al sistema de archivos para guardar o leer documentos
que pertenecen al negocio (PDFs subidos, resultados de procesamiento, adjuntos).
**Usa siempre `StorageService`** (wrapper sobre `fsspec`) inyectado vía `Depends`.

```python
# CORRECTO
async def upload_pdf(file: UploadFile, storage: StorageService = Depends(get_storage)):
    await storage.put(f"ingestion/{job_id}.pdf", file)

# PROHIBIDO — rompe Cloud Run (efímero) y acopla al SO local
with open(f"/tmp/{job_id}.pdf", "wb") as f:
    shutil.copyfileobj(file.file, f)
```

El backend se configura por variable de entorno:

| Variable | Desarrollo (local/Docker) | Producción GCP |
|---|---|---|
| `STORAGE_BACKEND` | `file` o `s3` (MinIO) | `gcs` |
| `STORAGE_BUCKET` | `/tmp/govgenai` o `govgenai-dev` | `govgenai-prod` |
| `STORAGE_ENDPOINT` | `http://minio:9000` (solo S3) | — |

El `StorageService` vive en `server/app/core/storage.py`. Si no existe aún, créalo antes de
escribir cualquier código que necesite persistir ficheros.

#### 2. Sin escrituras efímeras fuera del procesamiento en streaming

Cloud Run no garantiza disco persistente entre peticiones. Las escrituras en `/tmp` solo están
permitidas como buffer **temporal dentro de una misma petición/tarea** y deben borrarse
explícitamente al finalizar. Nunca asumas que `/tmp` sobrevive entre llamadas.

#### 3. Base de datos: DSN siempre por variable de entorno

La URL de conexión a la base de datos se lee **únicamente** de `DATABASE_URL` (async) y
`DATABASE_URL_SYNC` (Alembic). No hardcodees host, puerto, usuario ni contraseña en código.
Cloud SQL usa el patrón de socket Unix vía Cloud SQL Auth Proxy:

```
postgresql+asyncpg:///govgenai?host=/cloudsql/PROJECT:REGION:INSTANCE
```

---


## Servicios de computación pesada

**Docling no se reintroduce.** Al corpus solo entra `.md` conforme a `docs/CONTRATO_MD_CORPUS.md`;
el contexto temporal se extrae con **pdfplumber**. Si algo hay que convertir, se convierte antes de
llegar.

**`EmbeddingService` es un protocolo** con implementación local (BGE-M3) y por API. **No se
mezclan**: si un servicio llama al embedding por HTTP, no puede además importar el local como
reserva silenciosa — el fallback se configura en el `Depends`, no en la lógica de negocio. Y **el
modo edge sigue necesitando los modelos locales**, así que pueden hacerse opcionales pero no
desaparecer.

**No anticipes la extracción a microservicios** antes de que el problema aparezca en métricas
reales. Lo que pesa hoy es `torch`, no la extracción, y el razonamiento con las mediciones está en
`docs/DECISION_EXTRACCION_Y_DESPLIEGUE.md` (decisión 4 del registro).

---

## Modelo por prompt

Un prompt o una *issue* puede llevar `**Modelo sugerido**: Opus | Sonnet — <razón corta>`; los de
`planificacion/fase1/` lo llevan bajo el título. Es **una recomendación, no un requisito**: el
modelo lo elige el usuario, por coste y disponibilidad.

Tres reglas al abrir sesión:

1. **Si el modelo de la sesión no coincide con el sugerido, dilo en una línea y espera** — «el
   bloque sugiere Opus y estoy en Sonnet, ¿continúo?».
2. **No intentes cambiar de modelo por tu cuenta.** La elección es del usuario.
3. **En ejecución por bloques la comprobación se hace una sola vez**, al arrancar, sobre el
   conjunto de pasos del bloque. Dentro del bloque no se vuelve a interrumpir por esto.

**Delegar a un sub-agente con otro modelo** vale para tareas autocontenidas —auditar un diff, una
búsqueda compleja, una revisión de seguridad— y **no** para un prompt entero de implementación:
pierde el hilo conversacional y no puede pedir clarificaciones.

---

## Seguimiento del estado del proyecto

**El estado del desarrollo está en las *issues* y los hitos de GitHub**, y `ROADMAP.md` los agrupa
por temas hacia fuera. Es el método estándar y el que admite varios escritores a la vez: personas
y sesiones de agente en paralelo. Razón completa en `docs/MARCO_DESARROLLO_AGENTICO.md` §4.4.

**El proyecto empezó con un cursor**: `planificacion/PROJECT_STATE.md`, un fichero que el agente
actualizaba al cerrar cada prompt. Sólo funciona con un único escritor, y dejó de actualizarse el
2026-09-26. Se conserva como registro de la Fase 1. **No lo actualices**, y si retomas algo que
quedó pendiente en él, ábrelo antes como *issue*.

### Regla obligatoria: al cerrar cada paso

1. **El commit cierra su *issue***: `Closes #N` en el cuerpo del commit o de la PR. Un asunto
   `fix(#N):` no cierra nada, y lo comprueba CI.
2. **Si el paso es parcial**, la *issue* se retitula por lo que queda y lo hecho va arriba de su
   cuerpo (ver «Ejecución agéntica por bloques»).
3. **Añade una fila arriba de la tabla de `planificacion/HISTORIAL.md`** con la fecha de hoy, el
   identificador del paso —el número de la *issue*— y una descripción de una línea. La *issue*
   dice qué se pretendía; la fila, qué se aprendió.
4. **Si un tema del roadmap cambia de estado**, actualiza su fila en `ROADMAP.md`.

Es **obligatorio** incluso en pasos pequeños o de corrección.

### Cuándo NO hace falta

- Cambios de configuración de herramientas (permisos, settings, hooks).
- Consultas o explicaciones sin cambios de código.
- Refactors internos sin *issue* ni relación con el plan.

### Regla: actualizar `docs/ESPECIFICACIONES.md` al cerrar un bloque, si cambió una garantía

El estado se actualiza **siempre**, por paso. La especificación **sólo** cuando el
bloque cambia lo que el sistema garantiza, y entonces **en el mismo commit que lo cambia**.

**Por qué hace falta la regla si ya hay un test.** `test_especificaciones_no_miente.py` caza la
deriva estructural —un ámbito renombrado, una ruta muerta, el índice incompleto— y **no puede
comprobar la prosa**. Lo que se escapa es exactamente lo que hace daño: una capacidad nueva que no
aparece en §5, una garantía que cambia de significado, un «Abierto» que ya se cerró.

**Los cinco disparadores.** Se actualiza si el bloque:

1. hace aparecer o desaparecer una capacidad (una §5.x nueva) — LANG añadió §5.2;
2. añade o retira un invariante, o cambia dónde se hace cumplir — USR.8 añadió I10;
3. cierra un punto de «Abierto» — USR.9 cerró el hueco que la decisión de USR.6 dejaba anotado;
4. mete o saca algo de §10, «qué NO hace la plataforma»;
5. cambia una madurez.

**La madurez la mueve el despliegue, no el cierre del bloque.** Un bloque cerrado y sin empujar a
`main` queda en `construido`; pasa a `producción` cuando se despliega. USR era `construido` al
cerrar y `producción` tras el push; LANG sigue `construido`. Confundirlo deja el documento diciendo
que está en uso algo que nadie ha usado.

**Y en el informe de cierre se dice siempre, en una línea: qué cambió en la especificación o por
qué no cambió nada.** Un bloque puede no tocarla legítimamente —DOM no cambió ninguna garantía,
cambió dónde se sirven las cosas— pero decirlo es lo que impide saltárselo en silencio. Es el mismo
criterio que se aplica a las cifras de tests: si no se ha medido, no se reporta como medida.

**Lo que NO va en la especificación**: el estado del desarrollo, qué prompt viene, qué se midió en
un barrido. Eso son las *issues* y `HISTORIAL.md`. Un documento que repita el estado divergirá
en semanas y mentirá con autoridad, que es peor que no tenerlo.

---

## Reglas de comandos de shell

El entorno de ejecución es **Windows con PowerShell 5.1**. El operador `&&` no existe en PowerShell y provoca un error de parseo.

### Prohibido: `&&` en cualquier comando

**Nunca** uses `&&` para encadenar comandos, ni en la herramienta Bash ni en PowerShell.

```powershell
# PROHIBIDO — falla en PowerShell
cd frontend && npm test

# CORRECTO — encadenamiento incondicional
cd C:/Users/fabra/Documents/AI_agents_hub/frontend; npm test

# CORRECTO — encadenamiento condicional (ejecuta B solo si A tiene éxito)
cd C:/Users/fabra/Documents/AI_agents_hub/frontend; if ($?) { npm test }
```

Si necesitas encadenar comandos en la herramienta Bash, usa también `;` en lugar de `&&` para mantener consistencia y evitar errores si el contexto cambia a PowerShell.

### Navegación de directorios

- Usa siempre **rutas absolutas** al cambiar de directorio: `cd C:/Users/fabra/Documents/AI_agents_hub/frontend`
- No uses `cd` para salir del directorio raíz del proyecto (`C:/Users/fabra/Documents/AI_agents_hub`).
- Para inspeccionar estructura de carpetas, prefiere las herramientas `Glob` y `Read` antes que `ls` o `dir`.
