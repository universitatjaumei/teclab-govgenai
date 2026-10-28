# Auditoría pre-deploy — Gov Gen AI Platform

> **Fecha:** 2026-08-10 · **Alcance:** backend `server/app/`, frontend `frontend/src/`,
> corpus normativo (`Descarregar_pdf/normativa_propia/publicacio_transparencia_2026-07`),
> y arquitectura de modelos/retrieval. · **Método:** cuatro auditorías de solo lectura en
> paralelo con lectura directa del código (referencias `fichero:línea`), más verificación
> de la validación del corpus ejecutando el pipeline real en seco.
>
> Este documento **fue** la fuente de verdad del estado pre-deploy. Los bloques de remediación
> se planificaron como **SEC.8** en `planificacion/PROJECT_STATE.md`.

> ## ⚠️ Lee esto antes que nada: este documento es un registro histórico
>
> Es la foto del **2026-08-10** y se conserva porque explica **por qué** el código es como es —
> cada gate, cada `assert_org_access` y cada guardarraíl de este repositorio nació de un hallazgo
> de aquí—. **No describe el estado actual.**
>
> Hasta el **2026-09-18** describía como abiertos hallazgos que los bloques SEC cerraron en
> agosto, entre ellos que `SANDBOX_MODE=local` no tenía gate de producción (lo tiene desde
> SEC.8.3, y un segundo desde SEC.9.6). Con el repositorio a punto de hacerse público, eso
> significaba publicar una lista de vulnerabilidades ya cerradas con el aspecto de estar vivas,
> en el documento con más pinta de autoridad del árbol. Es el hallazgo C5 de la auditoría previa
> a abrir, y APER.7 lo cierra con **un estado por hallazgo comprobado contra el código**.
>
> Dónde está la verdad de hoy:
>
> | Para saber… | Mira… |
> |---|---|
> | qué garantiza la plataforma **ahora** | `docs/ESPECIFICACIONES.md` |
> | en qué punto está el desarrollo | `planificacion/PROJECT_STATE.md` |
> | por qué algo se hizo así | `planificacion/HISTORIAL.md` |
> | qué se revisó antes de abrir el repositorio | la auditoría del 2026-09-18, en `_local/` (no viaja en el repositorio: describe dónde es débil el sistema) |
>
> Los marcadores de cada hallazgo (✅ cerrado · ▶ parcial · ⏳ abierto · ℹ️ informativo) son los
> de la revisión del 2026-09-18 y llevan el bloque que lo cerró. Lo vigila
> `server/tests/infra/test_aper7_la_auditoria_vieja_no_miente.py`, que no deja añadir un
> hallazgo sin estado ni un estado sin hallazgo.

## Veredicto

El **núcleo está bien construido** y verificado: autenticación (JWT, PAT, SAML), cuotas,
CORS, cabeceras, `StorageService`, embeddings/reranker locales, contract-first donde importa,
Alembic con un solo head. **No se puede desplegar de cara al público todavía** por dos clases
de fallo: (1) una credencial de superadmin sembrada en todos los entornos —**ya arreglada**,
ver CR-1—, y (2) un IDOR horizontal sistémico en los routers añadidos después del bloque SEC.
El corpus está muy cerca: el bloqueante mecánico de ingesta **ya está resuelto**. El modelo
local encaja en la redacción de informes, no en los chatbots.

> **Actualización 2026-08-10 — el bloque SEC.8 se ejecutó entero.** Los nueve hallazgos
> bloqueantes de este informe están cerrados (suite backend 1782 passed / 0 failed, frontend
> 276 passed). Dos decisiones de arquitectura posteriores, en
> `docs/DECISION_EXTRACCION_Y_DESPLIEGUE.md`, cambian el contexto de algunas conclusiones de
> §4 y §5: **el despliegue pasa a una VM** (el scheduler y el rastreo necesitan proceso vivo)
> y **Docling se retira del servidor** (al corpus solo entra `.md` del pipeline de curación),
> lo que reduce la huella de memoria muy por debajo de lo que este informe estimaba.

**Estado de cada hallazgo, comprobado contra el código el 2026-09-18 (APER.7).**

Lo que sigue no es «lo que se recuerda haber arreglado»: cada fila se verificó abriendo el
fichero. Las que siguen abiertas están abiertas de verdad, y ninguna es de seguridad.

| Hallazgo | Estado | Evidencia / quién lo cerró |
|---|---|---|
| CR-1 · SuperAdmin sembrado en producción | ✅ | gate a `ENVIRONMENT=development` (SEC.8.0) |
| CR-2 · IDOR horizontal sistémico | ✅ | la capa de tenencia (SEC.8.1) y, lo que lo mantiene cerrado, el inventario que **recorre** los routers en vez de listarlos (SEC.9.5) |
| AL-1 · `export_task` cruza organizaciones | ✅ | `assert_chatbot_org_access` en `api/v1/hub_tasks.py:70` |
| AL-2 · `submit_feedback` sin comprobar organización | ✅ | tres comprobaciones en `api/v1/hub_feedback.py` (`:119`, `:150`, `:210`) |
| AL-3 · `routers/redaccion/` sin dueño | ✅ | `es_propietario` en `manifests_router.py:41`; el `_user` sin usar ya no existe; `get_template_version` acota (SEC.8.1) |
| AL-4 · `SANDBOX_MODE=local` sin gate | ✅ | `core/config.py` lo rechaza en producción (SEC.8.3) **y** rechaza `TESTING=1`, que era la otra puerta (SEC.9.6) |
| AL-5 · auditoría AST evadible | ✅ | SEC.8.3, con las evasiones de manual en rojo primero |
| AL-6 · el widget embebe un Bearer privilegiado | ✅ | no queda ningún `Bearer` ni token en `frontend/src/widget/` |
| AL-7 · path traversal en subidas de workspace | ✅ | `sanitizar_nombre` + `read_within_limit` en `workspaces_router.py:405` |
| ME-1 · `X-Forwarded-For` por la izquierda | ✅ | se cuenta desde la derecha con `TRUSTED_PROXY_HOPS` (`core/rate_limit.py`) |
| ME-2 · SAML laxo | ✅ | `strict`, `wantAssertionsSigned` y `validate_cert=True` (`core/auth/saml/settings.py:58,75,93`) |
| ME-3 · `user_upload` sin comprobar el chatbot | ✅ | `api/v1/ingestion.py:40` |
| ME-4 · el bypass admin cruza inquilinos | ✅ | `es_propietario` en `anonymization_router.py:103` |
| ME-5 · subidas sin `validate_upload` | ✅ | SEC.8.6 |
| ME-6 · `JWT_SECRET_KEY` de ejemplo admitido | ✅ | `_SECRETOS_DE_EJEMPLO` y longitud mínima en producción (SEC.8.4) |
| ME-7 · sandbox sin `pids_limit` | ✅ | `pids_limit: 128` en los dos composes de producción |
| BAJO · feedback y temas sin límite de peticiones | ⏳ | sigue sin límite; es el único de §1 que queda, y no es de aislamiento |
| BAJO · `hub_themes` distingue 404/403 | ℹ️ | sigue igual; el UUID no se enumera y no filtra metadatos de organización |
| BAJO · `edge_sync` sin autenticación | ✅ | **APER.2** le puso `Depends(get_current_user)` al router; sigue siendo un stub 501 (ver I4) |
| BAJO · `hub_llm_configs` global | ✅ | una fila sin organización es de plataforma y la reserva el superadministrador (bloques MT) |
| BAJO · bcrypt trunca a 72 bytes | ℹ️ | propiedad de bcrypt, no un defecto de este código |
| B1 · temas en disco local | ✅ | PLAT.7, con `test_plat7_retirada_del_tema_en_json.py` |
| B2 · la curación no podía rastrear | ✅ | SEC.8.8: el rastreo real; `_NullCrawler` sólo se menciona como lo que sustituyó |
| B3 · 14 tests rotos en la raíz `tests/` | ✅ | la raíz `tests/` ya no existe |
| I2 · `hub_ingestion_router` clasificado `cloud` siendo edge | ✅ | **Cerrado en #273** (2026-10-23): `Deploy: edge` y registrado en `_register_edge`. Un guardarraíl impide que un router `cloud` importe modelos operacionales; las dos excepciones que dejó, chatbots y organizaciones, las retiró #298 (2026-10-28): el corpus va por un router `edge` y lo que el cloud necesita saber del cliente lo pide al puerto `DatosDelCliente` |
| I3 · servicios edge leyendo modelos de config | ✅ | ningún módulo hace ya `session.get(HubChatbot)` ni `session.get(HubOrganizacion)` |
| I4 · la sync API edge es un stub 501 | ▶ | sigue siendo un stub, **a propósito**: es Fase 3. Lo que cambió es que ya no es superficie anónima (APER.2) |
| I5 · perfiles con UUID nulos | ✅ | resuelto el 2026-08-11; las dos factorías lanzan `NotImplementedError` |
| I6 · `modules/automation` es código muerto | ▶ | el consumidor que citaba (`_legacy_nicegui`) **ya no existe**, retirado en NIC. Hoy son cinco ficheros y la automatización con superficie aterrizó en `modules/redaccion/` |
| I7 · el widget esquiva el contrato | ✅ | no queda ningún `fetch(` a mano en `frontend/src/widget/` |
| I8 · capa API paralela de anonimización | ✅ | `useAnonymizationApi.ts` ya no existe |
| M1 · stubs post-MVP sin llamantes | ⏳ | no re-verificado en APER.7 |
| M2 · `ThemeEditor.tsx` muerto | ✅ | retirado en #171 (2026-09-27): editaba el tema equivocado |
| M3 · guardarraíl i18n sólo caza `hub.*` | ⏳ | no re-verificado en APER.7 |
| M4 · DSN con reserva a credenciales de desarrollo | ✅ | AIS.8: en producción **falla** en vez de conectar con la credencial publicada (`database/db.py:46`) |
| M5 · acciones decididas por estado en el frontend | ⏳ | no re-verificado en APER.7 |
| M6 · residuos versionados | ✅ | `server/my_errores.txt` ya no existe |
| M7 · tres servicios sin llamantes de producción | ⏳ | siguen sin llamante fuera de su propia definición |
| M8 · `create_all` en cada arranque | ✅ | **BD.2**: el esquema lo define Alembic y sólo Alembic (invariante I14) |

**Lo que queda abierto no es de seguridad**, con una excepción menor: el límite de peticiones en
feedback y temas. El resto son clasificación (I2), alcance pendiente (I4, I6) y limpieza (M1,
M3, M5, M7). Tres de ellos no se re-verificaron en APER.7 y lo dicen.

---

## 1. Seguridad

### CRÍTICO

✅ **CR-1 · SuperAdmin con credencial pública sembrada en producción — ✅ ARREGLADO**
`server/app/database/seeds.py` + `server/app/main.py:161`.
`seed_all()` corría en el `lifespan` en cualquier `ENVIRONMENT` y `seed_multitenancy_defaults()`
sembraba `fabra@uji.es` / `admin1234` (hash bcrypt válido; credencial en el repo). En el primer
arranque en producción se creaba un SuperAdmin comodín (acceso a todos los tenants) con
credencial conocida.
**Arreglo aplicado:** `seed_multitenancy_defaults()` retorna sin sembrar cuando
`ENVIRONMENT != "development"`. La provisión de producción la hace
`python -m server.app.scripts.bootstrap` (invocado por `setup.sh`), que toma la credencial de
`SUPERADMIN_EMAIL`/`SUPERADMIN_PASSWORD` y no hardcodea ninguna. Tests:
`server/tests/unit/test_seed_environment_gate.py`.

✅ **CR-2 · IDOR horizontal sistémico en los routers "edge" (sin capa de tenancy) — cerrado por SEC.8.1, y lo mantiene cerrado el inventario de SEC.9.5**
Solo 6 ficheros importan `assert_org_access`/`scope_query_to_orgs`. Los routers añadidos tras
SEC.2 se conformaron con `_require_admin`/`get_current_user` y **nunca resuelven
`chatbot_id`/`site_id`/`organizacion_id` a su organización dueña**. Verificado por lectura:

- `hub_organizaciones_router.py:103-193` — `list_organizaciones` devuelve todas las
  organizaciones a cualquier admin; `update`/`delete_organizacion` operan por `organizacion_id`
  sin comprobar pertenencia → un admin de A **borra** (CASCADE sobre chatbots) o renombra la
  organización de B.
- `hub_test_scenarios_router.py:211-258` — `run_scenario` ejecuta el `CoreGraph` completo contra
  el `chatbot_id` de la ruta con solo `_require_admin` → un admin de A **extrae el corpus
  completo de B**, consume su presupuesto LLM y recibe la respuesta.
- `hub_sites_router.py` (curation) — CRUD cross-org completo (`create_site` toma
  `organizacion_id` de query sin `assert_org_access`; `list_sites` sin `scope_query_to_orgs`).
- `hub_content_quality_router.py:268-293` — `analyze_content_gaps` por `chatbot_id` de query lee
  **las conversaciones de ciudadanos** de ese chatbot.
- `hub_prompt_templates_router.py` — `list`/`create`/`update`/`delete` por `template_id` sin
  resolver la org del chatbot dueño → se altera/borra el prompt de sistema de un chatbot ajeno.

**Patrón de arreglo (ya existe en el repo):** resolver el recurso y `assert_org_access(user,
recurso.organizacion_id)` (o `scope_query_to_orgs` en listados). Extender el guardarraíl de test
que ya prohíbe `session.get(HubChatbot,...)` directo en `hub_chatbots_router` a estos routers.

### ALTO

- ✅ **AL-1 · `api/v1/hub_tasks.py:49-63` `export_task`** — barrera "dueño **o** admin" sin resolver
  `chatbot_id→org`: cualquier admin descarga en Markdown/PDF la conversación (dato personal) de
  otra organización con solo el `run_id`.
- ✅ **AL-2 · `api/v1/hub_feedback.py:53-65` `submit_feedback` (POST)** — sin comprobación de org; el
  servicio hace `UPDATE HubInteraction WHERE id == interaction_id` a ciegas. Cualquier usuario
  autenticado sobrescribe el feedback de cualquier interacción. Sin rate limit.
- ✅ **AL-3 · `routers/redaccion/`** — `manifests_router.py:31-64` devuelve el `payload_json` de
  cualquier UUID sin comprobar owner; `hub_redaccion_router.py:276-344` tiene el parámetro
  `_user` **sin usar** (lee/muta bloques de cualquier workspace); `get_template_version:472-486`
  devuelve la `spec` de plantillas privadas ajenas.
- ✅ **AL-4 · `core/sandbox_client.py:488` `SANDBOX_MODE=local`** — sin gate de producción: ejecuta
  scripts de usuario en el host heredando `os.environ` (JWT, DATABASE_URL, GOOGLE_API_KEY).
  Recomendación: que `get_settings()` rechace `local` en producción.
  **Cerrado.** `get_settings()` lo rechaza desde SEC.8.3, y desde SEC.9.6 rechaza también
  `TESTING=1`, que llegaba al mismo ejecutor local por otra puerta. APER.1 añadió un cuarto gate
  con la misma forma. Lo fija `tests/core/test_sandbox_prod_gate.py`.
- ✅ **AL-5 · `script_auditor.py`** — la auditoría AST es evadible (`__builtins__['eval'](...)`,
  traversal de dunders, `getattr`). Contenida por Docker en prod; encadenada con AL-4 es RCE.
  **Cerrado por SEC.8.3**, con las evasiones de manual escritas en rojo primero. Y el eslabón del
  encadenamiento —AL-4— también está cerrado, así que la cadena ya no existe.
- ✅ **AL-6 · El widget embebe un Bearer privilegiado real** — `frontend/src/widget/main.tsx:22` +
  `hooks/useChat.ts:50` envían un JWT/PAT completo visible en el HTML embebido, con rol/orgs del
  dueño. El mecanismo `widget_api_key` (`chatbot_access.py:34,68-72`) está diseñado pero **no
  cableado**. (Coincide con el hallazgo funcional I7.)
- ✅ **AL-7 · Path traversal en subida de inputs de workspace** —
  `workspaces_router.py:336-339` interpola `file.filename` del cliente sin sanitizar y **sin
  `validate_upload`** (ni límite de tamaño ni tipo). Usar `basename`/clave `uuid4`.

### MEDIO

- ✅ **ME-1 · `core/rate_limit.py:89-92`** — `X-Forwarded-For` se toma por la izquierda (valor
  controlable por el cliente), lo que **anula el límite de fuerza bruta de login** falsificando
  la cabecera. ✅ **Arreglado**: se cuenta desde la derecha, tantos saltos como declare
  `TRUSTED_PROXY_HOPS`, y con 0 —expuesto directamente— la cabecera se ignora entera. En la VM
  el salto de confianza es el proxy inverso que termina TLS, así que ese número es
  **configuración del despliegue** (D.4-VM) y no algo que ponga la plataforma por ti.
- ✅ **ME-2 · SAML** (`core/auth/saml/settings.py:85,51-57`) — `validate_cert=False` en el fetch de
  metadata (MITM) y `wantAssertionsSigned: False`. La firma sí se valida vía `OneLogin_Saml2_Auth`.
- ✅ **ME-3 · `api/v1/ingestion.py` `user_upload`** — sin `assert_chatbot_access`: inyecta documentos
  y consume embeddings contra el chatbot de cualquier org.
- ✅ **ME-4 · `routers/redaccion/anonymization_router.py:73-86`** — el bypass admin cruza tenants.
- ✅ **ME-5 · Subidas de test-data sin `validate_upload`** (`scripts_router.py:267-305`) — DoS por
  memoria en `file.read()` sin límite.
- ✅ **ME-6 · `JWT_SECRET_KEY`** — exige que exista (bien) pero no rechaza el placeholder
  `change-me-in-production` ni una longitud mínima en producción.
  **Cerrado por SEC.8.4**: en producción se rechazan los secretos de ejemplo y los de menos de 32
  caracteres. El valor del `.env.example` está en esa lista negra, precisamente porque está
  publicado en el repositorio.
- ✅ **ME-7 · Contenedor sandbox sin `pids_limit`** (`docker-compose.prod.yml:112-117`).

### BAJO / INFO

- Feedback y `/hub/themes/for-chatbot/{id}` sin rate limit.
- `hub_themes_router.py:230-257` distingue 404/403 (oráculo de existencia; UUID difícil de
  enumerar, sin fuga de metadatos de org).
- `api/v1/edge_sync.py` — hoy 501 (stubs); resolver autenticación edge↔cloud y aislamiento por
  org **antes** de implementarlos.
- `hub_llm_configs_router.py` — providers/LLM configs globales; `_require_admin` deja que un
  admin (no solo superadmin) toque config que afecta a todas las orgs.
- bcrypt trunca a 72 bytes (`core/security.py`).

### Verificado correcto (evidencia de auditoría)

JWT sin default en código y sin `alg=none` (`jwt_handler.py:37-78`, `config.py:59-61`); PAT con
hash SHA-256 y `hmac.compare_digest` (`pat/service.py:115`); login con hash señuelo
anti-enumeración y mensaje uniforme (`auth_router.py`); identidad delegada solo con PAT + scope
+ `aud` + ventana de 5 min (`delegated_actor.py:104-139`); tenancy con asimetría vacío→todas
(superadmin) / ninguna (resto) (`tenancy.py`); `assert_chatbot_access` deny-by-default
(`chatbot_access.py`); **sin SQL crudo con interpolación en todo `server/app`** — retriever con
`websearch_to_tsquery` y `cosine_distance` como bind params; cuotas con UPSERT atómico
(`quotas.py`); subidas correctas en `hub_ingestion_router.py:329-350` y `api/v1/ingestion.py`;
CORS sin `*` en producción y `allow_credentials=False`; cabeceras nosniff/X-Frame-Options
DENY/CSP `frame-ancestors 'none'`/HSTS/docs off en producción **en las respuestas de la API**
(el HTML del panel y del sitio se servía sin ellas hasta el 2026-10-22: lo sirven nginx y el
bucket, no la aplicación); dependencias sin CVEs críticos
conocidos (pyjwt 2.10.1, python-multipart 0.0.21, cryptography 46.0.3; no se usa python-jose).

---

## 2. Integridad funcional

### BLOQUEANTE PARA DEPLOY

- ✅ **B1 · Temas en disco local relativo** — `hub_themes_router.py:127` (`THEMES_DIR =
  Path("data/themes")`, con `# en producción usar BD` escrito por el propio código). Los temas
  vivían en el sistema de ficheros del contenedor: se perdían al recrearlo —o sea en cada
  redespliegue— y no se compartían. **Tumbaba el arreglo del hallazgo #3 de MAN.2** (el widget
  con tema): `apply_theme_to_chatbot` guardaba en BD solo el puntero `{theme_id}` y resolvía
  leyendo el JSON local. ✅ **Arreglado por PLAT.7**: el tema en JSON se retiró y `THEMES_DIR`
  ya no existe en `server/app`; lo vigila
  `server/tests/infra/test_plat7_retirada_del_tema_en_json.py`.
- ✅ **B2 · La curación no puede rastrear en el despliegue estándar** — `main.py:94-99` construye el
  job con `_NullCrawler()` y `detectors=[]`, y no existe mecanismo real de inyección
  (`SpiderFactory`/`SiteCrawler` sin ningún llamante de producción). `POST /hub/sites/{id}/crawl`
  siempre acaba en `"no spider configured"`. O se cablea, o se asume que la curación web queda
  fuera del v1 (decisión de alcance).
- ✅ **B3 · 14 tests rotos/sin colectar en la raíz `tests/`** — 12 fallan porque importan rutas que
  CUR.1 movió a `modules/curation` sin actualizar los tests (**los spiders quedaron sin ningún
  test en la suite canónica**), y 2 errores de colección importan
  `partner_billing_service`/`partner_scripts_service` ya inexistentes. CI no lo ve (corre solo
  sobre `server/tests`); cualquier `pytest tests` desde la raíz sale en rojo. Viola el checklist
  propio ("grep -r a cero al retirar legacy").

### IMPORTANTE

- ✅ **I2 · `hub_ingestion_router` clasificado `cloud` siendo edge** — cerrado en #273 (`:3`, `main.py:234`): importa
  modelos operacionales solo-edge y el `IngestionWatcher`. En `DEPLOY_MODE=cloud` se serviría
  contra tablas inexistentes.
- ✅ **I3 · Servicios/grafos edge leen modelos de config directamente** — `config_resolver.py:110-118`
  (`session.get(HubChatbot)`/`HubOrganizacion`), `long_context_strategy.py:13`, `reranker.py:33`,
  `embedding_resolver.py:28`, `corpus/load.py:57`, `corpus/sync.py:70`. La regla es leer config vía
  `ConfigProvider`.
- ▶ **I4 · La sync API edge es un stub 501** (`api/v1/edge_sync.py:60-69`); solo hay
  `LocalConfigProvider`. `edge` y `cloud` separados hoy no son desplegables (el primer deploy será
  `DEPLOY_MODE=all`). Los DTOs conservan nombres pre-ROL (`partner_id`, `client_id`).
- ✅ ~~**I5 · `PUBLIC_PORTAL_AGGREGATOR` con UUIDs nulos** (`graph_factory.py:156-171,204`): si un
  chatbot selecciona este perfil, la recuperación consulta un `chatbot_id` nulo y devuelve vacío
  en silencio.~~ **Resuelto el 2026-08-11.** El alcance real era mayor: `PUBLIC_PORTAL_ROUTER`
  tenía el mismo defecto con `child_chatbot_ids=[]`, y el test de contrato de perfiles
  *certificaba* que ambos compilaban. Ahora las dos factorías lanzan `NotImplementedError`
  diciendo qué falta y qué usar en su lugar, ninguno de los dos se ofrece ya en los selectores
  del panel, y el contrato se aplica solo a los perfiles de `PERFILES_SIN_CONFIGURAR` hacia
  fuera. Implementarlos sigue siendo una funcionalidad pendiente con su propio alcance.
- ▶ **I6 · `modules/automation` es código muerto sin superficie** — sin router ni
  `frontend/src/automation/`; único consumidor `_legacy_nicegui`. Arrastra `token_service`/
  `api_key_service`. La "Fase 1 con automation" no tiene hoy ni API ni UI.
- ✅ **I7 · El widget esquiva el contrato** (`widget/main.tsx:31`, `useChat.ts:51`, `ChatWidget.tsx:57`
  usan `fetch` a mano). `GET /hub/themes/for-chatbot/{chatbot_id}` no está en los `openapi.json`
  presentes; **nada en CI verifica los endpoints que el widget consume por fetch**. (Los
  `openapi.json`/`generated/` están en `.gitignore` a propósito; CI regenera + valida con tsc.)
- ✅ **I8 · `useAnonymizationApi.ts:7-28`** — capa API paralela a mano (fetch + interfaces propias)
  que esquiva Orval y pierde el interceptor de auth de CAL.2.

### MENOR

- ⏳ **M1** · stubs post-MVP documentados sin llamantes (`anonymization/service.py:231-237`
  `save_state`/`load_state`; `library_router.py:201` `key_id: "default"`).
- ✅ **M2** · `ThemeEditor.tsx` es componente muerto (0 consumidores) y sus 16 claves `themeEditor.*`
  no existen en ningún locale (default inline en castellano). Era el "editor aparcado": se retiró en #171.
- ⏳ **M3** · el guardarraíl anti-"clave solo como default" del namespace admin solo caza `hub.*`
  (`adminI18nCoverage.test.ts:148`); `curation` sí tiene el guardarraíl completo. Paridad es/ca/en
  medida completa en los 7 namespaces.
- ✅ **M4** · DSN con fallback hardcodeado a credenciales dev (`database/db.py:15`,
  `agents_hub/database/connection.py:19`). En prod es mejor fallar que conectar en silencio.
- ⏳ **M5** · acciones decididas por estado en el frontend de curación (`FindingsPage.tsx:142-148`);
  presentacional (el backend valida), pero es el patrón que la regla HATEOAS proscribe.
- ✅ **M6** · residuos versionados (`server/my_errores.txt`, scripts sueltos en `tests/`).
- ⏳ **M7** · `agent_service.py`, `knowledge_orchestrator_service.py`, `scheduler_service.py` sin
  llamantes de producción (solo `test_imports.py`).
- ✅ **M8** · `create_all` en cada arranque (`main.py:50-61`) conviviendo con Alembic → puede
  enmascarar drift modelos↔migraciones.

### Verificado correcto

`StorageService` existe (`core/storage.py`, fsspec) y se usa en las subidas de negocio; sin
`relationship()` cross-base; frontera de aplicación limpia (ningún `modules/` importa `routers/`
ni billing; los 30 routers llevan etiqueta `Deploy:` y están registrados); Alembic con un solo
head (`s6b7c8d9e0f1`, 49 revisiones); contract-first donde importa (38 ficheros consumen
`shared/api/generated`; SDUI de redacción real); CI sólido (suite `-n0` + gate multi-tenant +
gate de retrieval + job de contrato + a11y); i18n con paridad es/ca/en en los 7 namespaces.

---

## 3. Corpus normativo — estado y plan de ingesta

**Calidad estructural alta y mejor que la instantánea del contrato:** 262 documentos, 0 anclas
duplicadas, las 8 unidades sin cuerpo resueltas, los 3 documentos con pérdida real (ALT-065,
ALT-034, REG-030) recuperados o consolidados, 52/52 tablas con texto, consolidación aplicada
(487 clases + 86 notas de vigencia dentro del chunk), front-matter en el 100%, vocabulario
(`vocabulari/*.csv`) cargable tal cual.

**Bloqueante de ingesta — ✅ ARREGLADO.** El generador emitía `us_assistents: 'True'/'False'`; el
pipeline exige `Literal["si","restringit","no"]` (`manifest.py:98`) y `LocalDirectorySource`
aborta el paquete entero a la primera entrada inválida (`source.py:119-126`) → 0/262. Corregido
en `genera_frontmatter.py` (normalización + `motiu_exclusio` derivado del estado de vigencia para
los 3 `no`) y regenerado `md_contracte/` (solo cambió el front-matter; cuerpos intactos).
**Verificado: 262/262 pasan la validación real del pipeline.**

**Revisiones del pipeline — estricto vs silencioso:**

- *Estricto (aborta):* `Literal` de `us_assistents`/`nivell_acces`/`content_class`;
  `relative_path` absoluta o con `..`; `content_class: regulation` sin `revisat_per`+`revisat_el`
  (`manifest.py:134`); `us_assistents: no` sin `motiu_exclusio` (`:139`); rutas repetidas;
  códigos de vocabulario no vigentes (`assert_vocabulary`, reporta todos con su fichero).
- *Silencioso (entra igual):* la guarda "una sola canónica por norma" (VIS.3) **solo corre con
  manifiesto** (`manifest.py:172`); en modo carpeta **no se ejecuta** → las parejas bilingües
  entran duplicadas. `versio_idiomatica_de` solo se enlaza si viene en el front-matter
  (`reconciler.py:308-326`). `content_class` ausente → default `generic` → la puerta de revisión
  humana nunca salta. `assert_vocabulary` solo valida lo presente (ámbitos/submaterias vacíos →
  pasa trivialmente). 34 documentos sin `url_oficial` (cita degradada, no rompe).

**Cambios de documento pendientes (proyecto del corpus), por impacto en el RAG:**

1. Emitir `canonica`/`versio_idiomatica_de` en las 29 parejas bilingües (elimina duplicados en el
   top-k). Hoy se usa `relacionada_amb`, que el pipeline guarda como metadato pero no enlaza.
2. Decidir `content_class` (si `regulation`, exige `revisat_per`+`revisat_el`).
3. `termes_bilingues` (puente léxico RAG.4): hoy 0 documentos.
4. `ambit_principal`/`submateries`: cuando SG valide el vocabulario (Hito B); es regenerar y
   recargar **sin re-embeber**.

**Decisiones del lado del pipeline (repo):** `desplacat` fuera de `ESTADOS_CONSOLIDACION`
(`chunker.py:46`) parece **deliberado** (es *lex superior*, no una consolidación hecha *a* la
norma; `classes` conserva `.desplacat` y la nota viaja en el chunk) — decisión, no fix. La guarda
VIS.3 solo en modo manifiesto: para la prueba en carpeta, generar un manifiesto mínimo o aceptar
duplicados hasta emitir `canonica`.

**Publicación HTML:** tiene pendientes propios (correcciones de SG, dashboards, paquetes) que
**no bloquean el RAG**.

---

## 4. Arquitectura LLM/retrieval y el modelo local

**Chatbots de fase 1 (sin datos sensibles): API (Gemini/Vertex).** Un 7B local aquí no aporta y
rompe el retrieval: el presupuesto de contexto por defecto es 128.000 tokens y `MD_LONG_CONTEXT`
inyecta documentos enteros (~25k tokens); con ventana de 8k el código **inyecta aunque no quepa**
(`long_context_strategy.py:64-70`). `MD_AGENT_SELECTOR`/router usan function-calling, débil en 7B.

**Redacción de informes (datos personales): el modelo local sí aporta, y llega en el momento
justo.** El motor LLM de redacción **todavía no está enchufado** — `llm_drafts_router`,
`scripts_router`, `copilot_router` son stubs 503 y `WorkspaceRunService` se instancia sin servicio
LLM (`workspaces_router.py:397`). Se cablea de todas formas → se cablea ya apuntando a un endpoint
local. Encaja porque la cadena de redacción es **texto y JSON-en-texto, sin function calling**
(perfil de baja exigencia de tooling). Cautelas: contexto por bloque hasta ~7,5k tokens
(`ai_assist_draft.py:16` `_MARKDOWN_LIMIT=30_000`) casi llena 8k; `LLMSpecService` es el único
consumidor JSON sin bucle de refinamiento (`llm_spec_service.py:90`).

**Implicación de retrieval:** ninguna directa. Embeddings (BGE-M3) y reranker
(`bge-reranker-v2-m3`) ya son locales tras protocolo, **independientes del LLM de generación**. El
único ajuste es el presupuesto de contexto, configurable por chatbot con un UPDATE.

**Implicación de deployment (transversal):** la guarda `assert_embedding_space_matches` compara la
procedencia del embedding en cada consulta y devuelve 409 si no coincide (`embedding_space.py`,
`hub_chat.py:260`). **Decidir el proveedor de embeddings ANTES de ingerir**: si se ingiere con
BGE-M3 local y se despliega con Vertex, hay que **re-embeber** el corpus (GPU + horas). El LLM de
generación sí puede diferir entre entornos (API en cloud, local en edge) sin re-ingerir.

**Cambios mínimos para enchufar un modelo local OpenAI-compatible:** el `model_factory` ya habla
`google_genai`, `openai_compatible` (con `base_url`) y `ollama`; el modelo de datos
(`HubProvider.base_url` + `HubLLMConfig`) admite un proveedor local por INSERT/UI; presupuesto de
contexto configurable por chatbot. Falta: (1) cablear el LLM de redacción al factory (sustituir
los stubs 503); (2) declarar `langchain-community`/`langchain-ollama` como dependencia directa (hoy
transitiva de ragas) o usar el endpoint `/v1` por la rama `openai_compatible`; (3) permitir key
dummy en `openai_compatible` para endpoints sin auth; (4) `UPDATE` de `context_token_budget`/
`max_tokens` y decidir `MD_LONG_CONTEXT` para 8k; (5) filtrar `purpose='chat'` en
`get_llm_config_for_tier` (`config_provider.py:54-64`); (6) robustecer `LLMSpecService` sobre 7B.

**Hardware:** `docker-compose.prod.yml:74-89` tiene servicio `ollama` sin límite ni reserva de
GPU. Un edge con 7B q4 + BGE-M3 + reranker pide ~12-16 GB de RAM/GPU; el deploy estándar "con
recursos reducidos" es coherente con embeddings+LLM de Vertex (sin 7B), reservando el modelo local
para el modo edge/redacción con datos sensibles.

---

## 5. Plan de remediación pre-deploy (SEC.8) y prueba local

**Ya hecho hoy:** CR-1 (gate del superadmin) y el bloqueante de ingesta del corpus.

**SEC.8 — antes de exponer la plataforma** (orden por severidad):
1. CR-2 y familia IDOR: `assert_org_access`/`scope_query_to_orgs` en test-scenarios, curation
   (sites + content-quality), prompt-templates y organizaciones; + AL-1/AL-2/AL-3 (hub_tasks,
   feedback POST, redaccion manifests/workspace).
2. AL-4 + AL-5: prohibir `SANDBOX_MODE=local` en producción y endurecer el auditor AST.
3. AL-6: credencial de sitio para el widget en vez de Bearer privilegiado.
4. AL-7 / ME-5: sanitizar nombres de fichero y enrutar todas las subidas por `validate_upload`.
5. ME-1, ME-2, ME-6: `X-Forwarded-For`, hardening SAML, rechazo de `JWT_SECRET_KEY` placeholder.
6. Bloqueantes funcionales: B1 (temas a BD/StorageService), B2 (decisión sobre el crawler),
   B3 (limpiar los tests rotos de la raíz `tests/`).

**Prueba local (antes de decidir el deployment):**
1. Decidir el proveedor de embeddings (ver §4: la guarda de procedencia obliga a fijarlo antes de
   ingerir).
2. Cargar el vocabulario (2 CSV) y `corpus.load --dir md_contracte --chatbot-id <uuid> --dry-run`,
   luego sin `--dry-run`.
3. Probar el chat con API (Gemini) sobre el corpus — camino de fase 1.
4. Cablear el LLM de redacción a un endpoint local (Ollama/vLLM con un 7B q4) y probar la
   generación de un informe end-to-end.
5. Con eso, decidir el deployment (estándar Vertex vs edge con local para redacción).
