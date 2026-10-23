# 🛠️ CONTRIBUTING — Manual de desarrollo de Gov Gen AI Platform

Normas obligatorias para evolucionar y mantener la plataforma. Aplican a todo colaborador,
humano o agente de IA.

> **Fuentes de verdad** (este manual las resume; no las sustituye):
> - `docs/Arquitectura.md` — **qué** es la plataforma y qué principios la rigen (módulos, roles, privacidad, frontera Cloud/Edge, stack). Decisiones estructurales.
> - `planificacion/PLAN_DESARROLLO.md` — **cuándo y en qué orden** se construye (3 Fases Funcionales, calendario).
> - `planificacion/Plan_TDD_Fase1.md` / `planificacion/Plan_TDD_Fase2.md` / `planificacion/Plan_TDD_Fase3.md` — **cómo** se construye cada pieza (prompts TDD Red/Green).
> - `AGENTS.md` — **reglas operativas** para agentes de programación, cualquiera que uses (retirada de legacy, frontera edge/cloud, portabilidad, shell, migraciones). En caso de conflicto, **AGENTS.md manda**. El `CLAUDE.md` de la raíz solo lo importa, porque Claude Code busca ese nombre.
> - Las *issues* y los hitos de GitHub — el estado del desarrollo: qué está hecho, en curso y pendiente.

---

## 🌐 Dónde trabajas: principal y fork

Antes de *cómo* se contribuye, **dónde**.

| Repositorio | Papel | Qué entra |
|---|---|---|
| GitHub — `universitatjaumei/teclab-govgenai` | **Principal** (*upstream*) | Lo que sirve a cualquier organización que despliegue la plataforma. |
| El fork de cada organización que despliega | **Despliegue y desarrollo propio** | Su configuración, sus integraciones internas, y los desarrollos que responden a necesidades suyas. |

El proyecto nace de la actividad investigadora del grupo **INNOVAP** (Derecho Público e Innovación)
y está destinado a varias administraciones —con atención particular a las entidades locales—, no a
una sola institución. **La regla vale igual para todas, incluida la universidad donde nació**: no
hay fork privilegiado.

**Y que el principal viva en la organización de la UJI no se lo da** (REPO.4). Alojar no es
dirigir: la UJI contribuye por *pull request* y se somete a la misma regla dura de abajo que
cualquier otra administración, y sus necesidades específicas viven en su fork igual que las de
cualquiera. Decirlo aquí importa porque el lugar del repositorio se lee como jerarquía si nadie
lo desmiente — y hasta este cambio el principal no estaba en ninguna institución, así que la
pregunta no se planteaba. De ahí sale la única regla dura de esta sección:

**Lo específico de una institución no entra en el principal.** Se queda en su fork y sube por
*pull request* sólo si se puede generalizar. Si las necesidades de una institución entraran directas
en el principal, el principal acabaría siendo el sistema de esa institución.

> **Esto es una convención de gobernanza, no una obligación de la licencia.** La AGPL exige dar el
> fuente de tu versión **a los usuarios de tu despliegue** (§13), y distribuirla bajo AGPL si la
> distribuyes. **No exige enviar nada aguas arriba**: ningún copyleft obliga a contribuir al
> proyecto de origen. Lo que la licencia garantiza es que ninguna mejora quede cerrada y que el
> principal **pueda** incorporarla; el *pull request* es lo que evita tener que ir a buscarla.

### Qué se puede generalizar (y sube), y qué no

| Sube al principal | Se queda en el fork |
|---|---|
| Un módulo nuevo, o una capacidad que cualquier organización pueda activar. | Configuración de la institución: organizaciones, chatbots, temas visuales, prompts propios. |
| Un arreglo de un defecto real, con su test. | Integraciones con sistemas internos que sólo esa institución tiene. |
| Una opción de configuración que hace parametrizable algo que estaba fijo. | Corpus, datos y credenciales. Nunca salen del fork ni del despliegue. |
| Mejoras de accesibilidad, i18n, rendimiento, seguridad. | Cambios que presuponen la estructura organizativa de una institución concreta. |

Antes de abrir un *pull request* hacia el principal, pregúntate si otra administración querría ese
cambio. Si la respuesta es «le daría igual», es material de fork; si es «lo necesita pero al revés»,
lo que sube es la **opción de configuración**, no la decisión.

### Certificado de origen (DCO): cada commit va firmado

Toda contribución al principal exige un **DCO** — *Developer Certificate of Origin* 1.1, el mismo
que usa el kernel de Linux. En la práctica es una línea al final del mensaje de cada commit:

```
Signed-off-by: Nombre Apellidos <correo@ejemplo.org>
```

Se añade sola con `git commit -s`. Si ya has commiteado sin ella:

```bash
git commit --amend -s                      # el último commit
git rebase --signoff origin/main           # toda la rama
```

**Qué certificas al firmar** (texto íntegro en el fichero `DCO`): que el código es tuyo o que tienes
derecho a aportarlo bajo esta licencia, y que entiendes que la contribución y tu firma quedan en un
registro público indefinido.

**Qué NO es.** No cedes derechos: **conservas tu copyright** sobre lo que aportas. El DCO no es un
CLA; no transfiere nada ni permite relicenciar tu código. Se pide precisamente porque es la opción
ligera: una línea, sin firmar papeles ni ceder titularidad.

**Por qué se pide.** Sin él, dentro de dos años nadie puede acreditar que quien aportó un módulo
tenía derecho a aportarlo — y un proyecto que van a usar administraciones públicas necesita poder
demostrar la procedencia de su código. Usa **tu nombre real**: el DCO habla de *real name*, y un
seudónimo no certifica nada.

**Se exige también en el principal.** No sólo a quien contribuye: los commits de este repositorio
van firmados igual. Un mantenedor que se exceptúa de su propia política la deja sin fuerza.

**Se comprueba en CI.** El *workflow* `.github/workflows/dco.yml` revisa los commits de cada *pull
request* y también los de cada *push* a `main`, y falla si falta la firma o si no coincide con el
autor del commit. Queda fuera el historial anterior al 2026-08-21, que es cuando se adoptó la
política. Una política que nadie comprueba se incumple sin que nadie lo note.

**La única excepción son los robots, y tiene una razón.** Los commits cuyo autor es una cuenta de
robot de GitHub —`…[bot]@users.noreply.github.com`, en la práctica Dependabot— están exentos. Lo
que el DCO certifica es «tengo derecho a aportar esto bajo la licencia del fichero», y eso lo
afirma **una persona** sobre código que aporta; un robot que sube un número de versión en un
`uv.lock` no aporta código de nadie, reordena una resolución de dependencias. No hay autoría que
certificar.

Y exigírselo tenía un precio medido: el 2026-09-19 había **trece *pull requests* de Dependabot
abiertas y ninguna se podía mezclar**, todas en rojo por esta línea. Un requisito que hace
imposible el camino bueno se acaba apagando entero, y eso sí habría sido perder el DCO.

Lo que **no** se relaja: la exención va por **correo** y no por nombre —el nombre de autor lo
elige quien commitea—, se deja constancia en el registro de CI cada vez que se aplica, sus *pull
requests* pasan los mismos checks que las demás, y **la responsabilidad es de quien mezcla**. Lo
vigila `server/tests/infra/test_aper13_el_dco_exime_a_los_robots_y_a_nadie_mas.py`, que comprueba
además que para las personas no ha cambiado nada.

### Dónde está cada pieza del proceso

| Fichero | Para qué |
|---|---|
| [`.github/PULL_REQUEST_TEMPLATE.md`](.github/PULL_REQUEST_TEMPLATE.md) | La plantilla del *pull request*. Su primera pregunta es «¿por qué esto es generalizable?», que es la que decide si el cambio entra en el principal o se queda en el fork. |
| [`.github/ISSUE_TEMPLATE/`](.github/ISSUE_TEMPLATE) | Fallo y propuesta. Preguntan por el fork y el modo de despliegue, que es lo primero que hace falta saber en un proyecto multiorganización: el mismo código se comporta distinto según cómo esté configurado. |
| [`SECURITY.md`](SECURITY.md) | Cómo comunicar un fallo de seguridad **en privado**. No abras un issue público para algo explotable: lo convierte en instrucciones para quien todavía no ha actualizado. |
| [`.github/CODEOWNERS`](.github/CODEOWNERS) | A quién se le **pide** revisión automáticamente: el núcleo, la frontera entre organizaciones, las migraciones y los guardarraíles. Romper cualquiera de esos afecta a todos los despliegues a la vez. Pedirla no es exigirla — ver «Cómo está protegida `main`» aquí debajo. |
| [`DCO`](DCO) | El certificado de origen, explicado más arriba. |

### Cómo está protegida `main`

`main` **es el disparador del despliegue**: `deploy.yml` arranca con `push: branches: [main]` y
sólo con eso. Por eso el trabajo se empuja a `desarrollo` —que se comprueba y no despliega— y
pasar a `main` es una decisión aparte. Lo hace cumplir un *ruleset* de GitHub que exige:

- **Pull request siempre.** No se empuja a `main` directamente, ni se borra, ni se reescribe
  (`deletion` y `non_fast_forward`).
- **Tres comprobaciones en verde**: `Lint & Test (Python 3.13)`, `API Contract (OpenAPI → Orval →
  TypeScript)` y `signed-off-by`.
- **Cero aprobaciones**, y esto necesita explicación.

**Por qué cero y no una.** Hasta el 2026-09-18 pedía una aprobación y revisión de propietario de
código. Con **un solo mantenedor** eso es imposible de cumplir —en GitHub nadie aprueba su propia
*pull request*—, así que la única salida era el *bypass* de administrador… **que no se salta la
aprobación: se salta el ruleset entero, comprobaciones incluidas**. O sea que el único camino
practicable era el que además apagaba CI.

Con las aprobaciones en cero se mezcla por el camino normal y **las tres comprobaciones pasan a
ser obligatorias de verdad**. Es más estricto en la práctica que exigir una revisión que nadie
puede dar.

**Esto se revierte en cuanto haya un segundo mantenedor**: se vuelve a
`required_approving_review_count: 1` y a `require_code_owner_review: true`. Es una línea en el
ruleset y es lo primero que hay que hacer al ampliar el equipo.

**Y no afecta a quien contribuye desde fuera.** Sin permiso de escritura no se mezcla nada: una
contribución externa llega como *pull request* desde un *fork* y la mezcla alguien del proyecto,
con las tres comprobaciones en verde. Lo que se ha quitado es la ficción de un segundo revisor
que hoy no existe, no la revisión.

### Cómo se prepara la contribución

- Se sincroniza con el principal antes de empezar, y se trabaja sobre rama, no sobre `main`.
- Se respeta todo lo de este manual: **TDD** (no hay PR sin tests), Conventional Commits, retirada
  del legacy, frontera edge/cloud y estándares técnicos.
- El *pull request* explica **qué problema resuelve para cualquier organización**, no sólo para la
  que lo envía.
- Nada de secretos, datos reales ni corpus institucional en el diff. Ver §6.
- **Todos los commits llevan `Signed-off-by`** (`git commit -s`). Ver el apartado del DCO más arriba.

---

## 🎯 0. Pre-flight (obligatorio)

- **Lee [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md).** Es corto y se aplica igual a quien mantiene
  el proyecto que a quien contribuye una vez — la misma regla que el DCO y que la de no tener un
  *fork* privilegiado. Si algo de lo que pasa aquí lo incumple, ahí dice a dónde se escribe.
- **Entorno Python con `uv`.** Toda ejecución de backend, tests o scripts se hace vía `uv run …`. En Windows, **nunca** invoques `python` directamente (te redirige a la Microsoft Store); usa el ejecutor `uv`.
- **`uv sync` siempre desde un proyecto, nunca desde la raíz.** Desde NIC.4 (2026-09-04) la raíz **no tiene `pyproject.toml`**: los proyectos son `server/`, `mcp_server/` y `services/script_sandbox/`. Y si tocas dependencias, **`uv lock` va en el mismo commit** — CI instala con `uv sync --locked`, que falla si el lock no corresponde a su manifiesto. Comprueba con `uv lock --check`, no con `uv sync` a secas, que vuelve a resolver en silencio y por eso siempre pasa.
- **Shell del proyecto: PowerShell 5.1.** El operador `&&` **no existe** y provoca error de parseo. Encadena con `;` o `; if ($?) { … }`. Usa rutas absolutas al cambiar de directorio (ver `AGENTS.md` → "Reglas de comandos de shell").
- **Stack local**: `docker compose up -d` levanta PostgreSQL+pgvector, MinIO y el microservicio `script-sandbox`. Backend: `cd server; uv run pytest`. Frontend: `cd frontend; npm test`.
- **Dependencia de sistema (SSO SAML)**: el SP SAML usa `python3-saml`, que depende de `xmlsec` (libxml2 + libxmlsec1). En Windows el wheel de `xmlsec` ya las incluye; en imágenes Docker Debian/Ubuntu añade `libxml2-dev libxmlsec1-dev pkg-config` (apt) antes de `uv sync`.

---

## 🤖 1. Reglas para agentes de IA

- **Análisis previo obligatorio**: antes de proponer cambios, lee `docs/Arquitectura.md` (soberanía del dato, jerarquía de servicios, frontera Cloud/Edge) y `AGENTS.md` (reglas duras). Localiza la *issue* y su hito.
- **Inyección de dependencias, no instanciación manual**: en el servidor FastAPI usa `Depends`. **No** instancies servicios a mano ni accedas a sus métodos privados a través de la frontera HTTP.
- **Autonomía con responsabilidad**: ejecuta cambios alineados con la arquitectura y reporta tras la ejecución. Si detectas código que viola los estándares, propón la refactorización.
- **Divide y vencerás**: descompón tareas complejas en pasos pequeños y verificables.
- **Cierra la *issue* desde el commit o la PR** (`Closes #N`) al terminar el paso que resuelve.

---

## 🧱 2. Estructura del monorepo

```
server/        FastAPI (AGPLv3) — modules/{automation,agents_hub,redaccion,expedientes}, core/, services/, api/, routers/, migrations/
frontend/      React + Vite + TS (MIT) — src/{admin,curation,redaccion,widget,shared}
mcp_server/    Servidor MCP, stdio y remoto (paquete uv autocontenido, sin imports de server/app)
```

**No hay cliente de escritorio ni agente de ejecución local, y no va a haberlo.** La aplicación
NiceGUI original (`client_app/`) y su cuarentena (`_legacy_nicegui/`) **se retiraron completas el
2026-09-04**, 574 ficheros: llevaba tiempo sin compilar y nada en producción dependía de ella. El
**2026-09-23 se decidió no reconstruirlo**: es un límite deliberado (`docs/ESPECIFICACIONES.md`
§10), no una tarea pendiente, así que no hace falta proponerlo. El mapa de lo que hubo está en
`docs/INVENTARIO_RETIRADA_LEGACY.md`.

---

## 🔄 3. Ciclo de trabajo (TDD + Git)

- 🔴 **RED**: escribe el test en la carpeta `tests/` correspondiente y comprueba que falla. No hay PR sin tests.
- 🟢 **GREEN**: implementa el mínimo necesario para pasar.
- 🔵 **REFACTOR**: limpia manteniendo los tests en verde.
- 💾 **COMMIT**: commit inmediato tras GREEN, con **Conventional Commits** (`feat:`, `fix:`, `test:`, `refactor:`, `docs:`, `chore:`) y **firmado** (`git commit -s`). Menciona qué tests pasan. **No** incluyas líneas `Co-Authored-By` de Claude.

---

## 💻 4. Estándares técnicos

- **Asincronía total**: prohibido I/O síncrono en el servidor. Usa `async/await`; envuelve librerías síncronas (Docling, LibreOffice, etc.) en `asyncio.to_thread`.
- **Tipado estricto**: type hints en todas las funciones (Python) y sin `any` implícito (TypeScript).
- **Contract-First (frontend)**: la única fuente de verdad de datos es el backend. Usa los tipos y hooks generados por **Orval** desde `openapi.json`; **prohibido** definir interfaces de datos a mano o hacer `fetch` crudo saltándose el cliente generado. Formularios con `react-hook-form` + `zodResolver` alineados al contrato.
- **SDUI / HATEOAS**: el frontend no conoce campos a priori ni calcula permisos. Renderiza formularios iterando el `ui_contract` del backend y botones iterando `acciones_permitidas`. Nada de `if (rol === …) mostrarBoton()`.
- **i18n obligatorio**: ningún string hardcodeado en la UI. Usa `i18next` con locales `ca` / `es` / `en` en `frontend/src/shared/i18n/`. (El antiguo `translations.json` de NiceGUI es legacy.)
- **Sin features no pedidas**: no añadas manejo de errores, validaciones, flags ni abstracciones para escenarios fuera de la tarea.
- **Migraciones**: cuando toques `server/migrations/versions/`, aplica la migración con `uv run alembic upgrade <rev>` (ver `AGENTS.md`).

---

## 🚧 5. Frontera Edge/Cloud y desacoplamiento (muro de seguridad)

Regulado en runtime por `DEPLOY_MODE=cloud|edge|all`. Ver el detalle completo en `AGENTS.md` → "Frontera Edge-Cloud".

- **Dos `DeclarativeBase`**: `HubConfigBase` (config, se sincroniza cloud→edge) y `HubOperationalBase` (solo edge). **Sin `relationship()` cross-base**; navega por `*_id` con query explícito.
- **Un módulo edge no importa de un módulo cloud.** La configuración se lee vía `ConfigProvider`, no importando modelos de config directamente.
- **Etiqueta cada router nuevo** con `Deploy: cloud|edge|shared` en su docstring y regístralo en `_register_cloud`/`_register_edge`.

---

## 🔒 6. Seguridad y privacidad

- **Aislamiento multi-tenant**: cada consulta de datos de una Organización se filtra por el claim de organización del principal; ningún acceso cruzado sin rol global. Es una regla dura verificada por tests de aislamiento en CI.
- **Scripts generados por IA**: pasan por el `ScriptSecurityAuditor` (análisis AST) y se ejecutan en el **microservicio `script-sandbox`** (aislado, sin red, sin FS del host, no-root). El servidor no ejecuta código generado in-process.
- **Datos PII y anonimización**: los servicios edge entregan datos ya anonimizados al `model_factory` antes de cualquier LLM externo. En despliegue Edge, el Vault de identidades no sale del nodo institucional. No aplica al chatbot público de información pública.
- **Secretos por variable de entorno**: nunca hardcodees claves, DSN ni contraseñas. `DATABASE_URL` (async) y `DATABASE_URL_SYNC` (Alembic) solo desde env. En producción, Secret Manager.
- **Almacenamiento de ficheros de negocio**: siempre vía `StorageService` (`fsspec`), nunca `open()`/`shutil` directos a disco (rompe Cloud Run y acopla al SO).

---

## 🧹 7. Retirada de legacy (borra, no comentes)

- Una migración **no está completa** hasta retirar el código original. Sin código muerto, imports sin usar ni comentarios `# TODO: migrate`.
- **Se retira borrando**, y el historial de git es la fuente de verdad del pasado. Hubo una
  cuarentena, `_legacy_nicegui/`, retirada el 2026-09-04 con el resto del NiceGUI; no se
  reconstruye. Tampoco entra nada nuevo en `_legacy_archive/`.
- Sin shims de retrocompatibilidad ni alias `_old_*`.

Ver el procedimiento completo en `AGENTS.md` → "Regla crítica: migración = código nuevo + retirada del legacy".

---

## 🧭 8. La metodología, en una página

El desarrollo de este proyecto sigue un método propio, pensado para que lo ejecute un agente de
programación y para que un humano pueda auditar lo que hizo. No hay que adoptarlo entero para
contribuir —al final de esta sección se dice qué parte no se te pide— pero sí conviene entenderlo,
porque explica la forma de los ficheros que vas a encontrar.

### Las tres piezas, y una cuarta del principio

| Pieza | Qué es | Se lee cuando |
|---|---|---|
| **Las *issues* y los hitos** (GitHub, ordenados por temas en [`ROADMAP.md`](ROADMAP.md)) | El trabajo pendiente y su estado. Cada *issue* es un paso, con su alcance, sus tests y su verificación; un hito agrupa los de un **bloque** | Vas a implementar algo, o quieres saber dónde está el desarrollo |
| **El historial** (`planificacion/HISTORIAL.md`) | Una fila por paso cerrado, con **qué se midió, qué se desvió del plan y qué defecto apareció al verificar** | Quieres saber por qué algo está así antes de cambiarlo |
| **Las especificaciones** ([`docs/ESPECIFICACIONES.md`](docs/ESPECIFICACIONES.md)) | Qué **garantiza** el sistema, capacidad por capacidad, con sus invariantes y dónde se hacen cumplir | Vas a tocar código y no quieres romper una garantía |

**La cuarta pieza es histórica.** La Fase 1 se planificó como prompts en ficheros
(`planificacion/Plan_TDD_Fase1.md` y `planificacion/fase1/`), con un **cursor** en
`planificacion/PROJECT_STATE.md` que el agente movía al cerrar cada prompt. Es un sistema que sólo
funciona cuando trabaja una persona; con más de un escritor se queda atrás, y eso pasó. Ya no se
actualiza: lo que quede pendiente de él se abre como *issue* cuando se retoma.

La distinción que más se confunde: **un plan dice «haz X»; una especificación dice «el sistema
garantiza Y»**. Para saber qué puedes cambiar sin romper nada, la especificación; para saber qué
falta y en qué orden, el plan.

### El bucle, y por qué es así

Un bloque se ejecuta paso a paso, y cada paso cierra igual:

```
RED → GREEN → REFACTOR → verificaciones de cierre → actualizar el estado → un commit firmado
```

Actualizar el estado es que el commit cierre su *issue* y que quede la fila del historial.

Tres cosas de ese bucle no son ceremonia:

- **Un commit por paso, firmado.** Es lo que hace reversible un bloque largo: si el paso 5
  rompe lo que hizo el 3, hay un punto exacto al que volver. Sin eso, un bloque de siete pasos es
  un solo commit gigante que no se puede revertir a medias.
- **Los tests escalonados.** Durante el paso, sólo el fichero que estás escribiendo; al cerrarlo,
  los directorios que toca; al cerrar el bloque, la suite entera. Correr la suite completa después
  de cada cambio cuesta más de una hora y no aporta información nueva.
- **El historial se escribe al cerrar, no al planificar.** Lo que vale de él es lo que sólo se sabe
  después: la cifra que salió, el doble de test que mentía, la alternativa que no funcionó.

### Las dos reglas que más protegen a quien llega

**Escribe el test antes del código, y comprueba que sabe ponerse rojo.** Un test que pasa desde el
primer momento no está probando lo que crees. En este proyecto ha pasado varias veces que un rojo
alarmante era un defecto del instrumento y no del sistema —y una vez peor: un guardarraíl recorría
un directorio inexistente y **pasaba en verde sin mirar nada**—. Ante una cifra extrema o un verde
sospechoso, primero se comprueba el medidor.

**Deja escrito el por qué, no el qué.** El *qué* está en el diff. Lo que se pierde es por qué se
descartó la otra opción, y eso se paga cuando alguien la reimplementa de buena fe dos meses
después. En este proyecto va en tres sitios según su alcance: en el **docstring** si es local, en
`HISTORIAL.md` si es del paso, y en una **decisión de arquitectura** si condiciona al resto —ver
[`docs/DECISIONES.md`](docs/DECISIONES.md), que dice cuándo hace falta una y cuándo basta una fila
del historial—.

### Qué NO se te pide como contribuidor externo

- **No tienes que escribir tus *issues* como prompts.** Enumerar los tests en el cuerpo es la
  herramienta del mantenedor para dirigir a un agente. Tu contribución puede ser un PR normal.
- **No toques `PROJECT_STATE.md`.** Es el cursor de la Fase 1 y ya no se actualiza. Si tu PR
  resuelve una *issue*, basta con `Closes #N`.
- **No tienes que escribir en `HISTORIAL.md`.** Lo relevante de tu cambio va en el PR; el
  mantenedor lo integra donde toque.

Lo que **sí** se te pide, sin excepción: TDD, Conventional Commits, `Signed-off-by`, respetar los
invariantes de la especificación y las fronteras de `AGENTS.md`. Y si tu propuesta deja fuera una
alternativa razonable, acompañarla de una decisión escrita.

### Antes de escribir código: propón

Si lo que traes no es un defecto, **abre una propuesta antes** de escribirlo:
[`.github/ISSUE_TEMPLATE/propuesta.md`](.github/ISSUE_TEMPLATE/propuesta.md). Su pregunta central
—«¿por qué lo necesita **cualquier** organización?»— es la que decide si el cambio es material del
principal o de tu fork, y contestarla antes ahorra escribir código que no puede entrar.
