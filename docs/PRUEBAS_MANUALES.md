# Pruebas manuales de la plataforma completa

**Prompt MAN.1** (`planificacion/Plan_TDD_Fase1.md`). Sustituye al modelo anterior de un `.bat` por bloque:
esos guiones caducaban en silencio cada vez que un bloque posterior renombraba una ruta o
rehacía una pantalla, y nadie había recorrido la plataforma de una pieza.

**Regla que no cambia** (AGENTS.md §Verificación de UI): lo que el agente puede comprobar en
navegador **no entra** aquí. Esta matriz es sólo lo irreducible — credenciales e IdP reales,
sistemas externos no simulables, juicio subjetivo, lector de pantalla real y datos personales
de verdad.

---

## Hallazgos que requieren tu decisión (MAN.1 + MAN.2, para revisar juntos)

| # | Hallazgo | Estado | Alcance |
|---|---|---|---|
| 1 | `curation/SitesPage.tsx`: `useDeleteSite` no invalidaba la lista tras borrar (DELETE 204 en servidor, fila seguía en pantalla) | ✅ **Arreglado** (commit `6cba8fc`, test RED/GREEN) | 1 fichero |
| 2 | `GET /api/v1/hub/redaccion/templates` (y 5 sitios más del mismo router) devuelve **500** para cualquier sesión cuyo `user_id` no sea UUID — el SuperAdmin de desarrollo tiene `admin_id` entero y el Admin `partner_id` de texto libre, ninguno UUID | ✅ **Arreglado** — los 6 sitios de `hub_redaccion_router.py` usan ahora `_actor.user_to_uuid` (uuid5 determinista), el mismo patrón que ya aplicaban `llm_drafts_router.py` y `scripts_router.py` para este problema; se extrajo a un helper compartido para no triplicarlo. No era una decisión de diseño abierta: dar a SuperAdmin/Admin una identidad UUID real exigiría migrar `SuperAdminAccount.admin_id`/`AdminAccount.partner_id`, desproporcionado para este hallazgo. 5 tests nuevos en `tests/redaccion/test_hub_redaccion_router.py` | 3 ficheros de código + 1 test nuevo. De paso, arreglados dos rojos preexistentes destapados al tocar el módulo: `test_llm_drafts_router.py` no colectaba (`_PARTNER` con `role="partner"`, obsoleto desde el renombrado ROL.1→ROL.2) y una aserción esperaba `status == "draft"` donde el código, deliberadamente desde 9R.10.2, devuelve `"ingesting"` |
| 3 | El widget público (`frontend/src/widget/`) **no consume ningún tema** de organización/chatbot — `ThemeProvider` sólo está cableado en `frontend/src/App.tsx` (panel admin) | ✅ **Arreglado** — investigado primero: `HubChatbot.theme_config`/`HubOrganizacion.theme_config` eran columnas huérfanas (nadie las leía); el sistema real es `hub_themes_router.py` (temas en `data/themes/*.json`, cascada plataforma→organización→chatbot ya modelada), pero `apply_theme_to_chatbot` era un stub con `# TODO` que no persistía nada. Completado el stub (guarda `{"theme_id": ...}` en `theme_config`, reutilizada como puntero) y añadido `GET /hub/themes/for-chatbot/{chatbot_id}`: devuelve solo `config` (nunca `theme_id`/`organizacion_id`/`name`, para no reabrir el censo de organizaciones que SEC.5 cerró) y exige `assert_chatbot_access` (mismo criterio que `/hub/chat`). El widget (`main.tsx`) lo llama al montar y reutiliza `injectThemeCSS` de `ThemeProvider` (exportada para la ocasión), sin duplicar lógica de temas. Verificado en navegador de punta a punta: tema creado por API → aplicado a "Chatbot MAN Uno" → `--color-primary` inyectado en `:root` con el valor real (`#ff00aa`). 10 tests backend + 6 tests frontend nuevos, suite frontend completa **en serie: 281 passed, 0 failed** (`--no-file-parallelism`; en paralelo la suite da falsos rojos distintos en cada pasada — contención ya documentada en `planificacion/PROJECT_STATE.md`, no relacionada con este cambio), `tsc --noEmit` limpio. **Pendiente para un prompt propio** (fuera de MAN.2, a petición del usuario): completar el editor de temas del panel admin con cabecera/logo — es la definición de la plantilla, no la resolución que consume el widget |
| 4 | "Ejecutar" en `/hub/test-scenarios` fija `fallback_reason=None` a propósito (línea 256 de `hub_test_scenarios_router.py`) — **no es un bug**, pero significa que las ejecuciones de escenarios de prueba **nunca** alimentan la detección de huecos de RAG.14. Sólo lo hace una conversación real (widget o `POST /hub/chat/{id}`) | ℹ️ Documentado, sin acción — es la separación correcta entre "revisión manual" y "señal de uso real" | Ninguno; queda anotado para que nadie repita la confusión |

---

## Ya verificado por el agente en navegador (2026-08-09) — no repetir

Con `docker compose up -d db`, backend en `:8000` y frontend en `:5173`, sesión real como
`fabra@uji.es`:

| Área | Qué se comprobó |
|---|---|
| Hub — Chatbots | Lista con datos reales (Chatbot Demo, Chatbot de Ejemplo) |
| Hub — Organizaciones | Lista con datos reales (2 organizaciones) |
| Hub — Documentos | Selector de chatbot, banner de retrieval, dropzone, tabla vacía |
| Hub — Informes | Estado vacío correcto (0 interacciones) |
| Hub — Modelos LLM | Proveedores (google/ollama/openrouter) y 4 configuraciones LLM |
| Hub — Prompts del sistema | Prompt base por chatbot + 3 plantillas es/ca/en de "Chatbot de Ejemplo" |
| Hub — Cerebro IA | Selector de modelo con el actual marcado (✓) |
| Hub — Escenarios de prueba | Selector de chatbot, estado vacío |
| Hub — Tokens de acceso | Estado vacío, formulario accesible |
| Curación — Sitios | Alta real de un sitio (POST 201), listado, disparo de rastreo (POST 202) |
| Curación — Auditoría | Informe se muestra al elegir sitio (GET 200), sin pasos intermedios |
| Curación — Hallazgos | Selector de sitio + panel de huecos de corpus (RAG.14) montado siempre |
| Curación — Publicación | Selector de sitio y chatbot, selecciones y candidatas vacías correctas |
| Automatización / Plataforma | Placeholders intencionados (Fase 1 no los cubre aún) |
| Widget | `widget.html` requiere `npm run build:widget`; tras construirlo, el input y "Enviar" renderizan |
| MCP | Suite propia `mcp_server/tests`: 54 passed |

**MAN.2 — recorrido de punta a punta (2026-08-09), datos reales creados en esta sesión:**

| Paso | Qué se hizo | Resultado |
|---|---|---|
| Organización nueva | `POST /hub/organizaciones` → "Organización MAN.2" | 201, aparece en la lista con 0 chatbots |
| Dos chatbots bajo la misma organización | "Chatbot MAN Uno" y "Chatbot MAN Dos" | 201 × 2, ambos Vectorial RAG / Activo |
| Ingesta de un PDF real | `ARQUITECTURA GEN-GOV.pdf` (240 KB) subido a "Chatbot MAN Uno" vía dropzone | Job pasa de "Procesando" a documento en el corpus, 4,8 k tokens, Docling + RapidOCR en los logs. **Obsoleto desde EXT.1 (2026-08-11)**: al corpus solo entra `.md` conforme al contrato; un PDF da 415. La conversión vive en el pipeline de curación, y con ella el OCR |
| Consulta real contra el LLM (Gemini, clave real configurada) | 3 preguntas sobre la arquitectura de despliegue vía Escenarios de prueba | El chatbot respondió (sin alucinar) "no tengo información suficiente… con citas verificables" las 3 veces — el PDF elegido es sobre todo diagramas, poco texto extraíble; ver hallazgo #4 sobre por qué esto NO alimentó la detección de huecos |
| `POST /hub/quality/gaps/analyze` contra el `GapFinding` corregido en CUR.1 | Ejecutado desde Curación → Hallazgos | 200 OK, 0 huecos (esperado, ver hallazgo #4) — confirma que el fix de CUR.1 no rompió el camino feliz con datos reales |
| Organización + 2 chatbots + 1 documento **se dejan sembrados** en la BD de desarrollo, por si quieres continuar la verificación de RAG.14 tú mismo repitiendo el paso de consulta desde el widget en vez de Escenarios de prueba | — | — |

**Nuevo `.bat` maestro**: `pruebas_manuales_plataforma.bat`, con menú (o parámetro `0`-`4`) para
los cuatro caminos cruzados de MAN.2. Probado en seco (`0`, `1`, `2`, `3`, `4`): arranca, hace
los `curl` reales y no se cuelga. Corregido en el proceso un bug propio del guion (faltaba el
salto para el parámetro `0`, y unos `^` de escape sobrantes en las cadenas de `curl` que hacían
salir un `^>` literal en vez de `->`).

---

## Ya verificado por el agente en navegador (2026-08-17, Bloque VER) — no repetir

Backend en `:8001`, frontend de desarrollo en `:5174`, sitio del corpus en `:4174` y una
instancia aparte del sandbox en `:5099`. Sesión real como `fabra@uji.es`.

| Camino | Qué se comprobó, con evidencia |
|---|---|
| Informes — plantilla con IA | Descripción en lenguaje natural → propuesta con 4 secciones y bloques `DETERMINISTIC_DATA` + `TABLE` + `AI_ASSISTED_TEXT` + `REVIEW_GATE` → validación `ok=true` → aprobación **200** → contrato de UI **200** con una zona de arrastre y dos campos derivados |
| Informes — informe completo | Workspace desde plantilla → formulario construido **desde el contrato** → Excel sintético de ejecución presupuestaria subido → generación → bloque determinista `extracted` con la tabla real → el bloque de IA redacta **citando las cifras extraídas** (120.000, 96.000, 80 %) → aprobar → reanudar → `assembled` → vista previa **200** |
| Informes — scripts | Propuesta → `test` en el sandbox real → validación → `pending_review` → re-test con `hash_matches=True` → **aprobado**, confirmado en la base |
| Curación — sitios | Alta desde la pantalla → rastreo **202** → sitio `active` con `last_crawled_at` → 2 páginas guardadas → las mismas como candidatas |
| Curación — hallazgos | Análisis **202**, informe de calidad **200**, y las tres transiciones: confirmar **200**, `confirmed → new` **422** con el motivo, resolver **200** |
| Curación — publicación | Selección `path_prefix` creada, candidatas marcadas con su regla, y la selección **sólo** en el chatbot destino |
| Curación — huecos y caducidad | `gaps/analyze` **200** y `stale/analyze` **200**. No contradicen a la pantalla de Vigencia: aquélla cuenta lo que **nadie ha validado** (50), ésta lo que **ya venció** (0, porque las fechas del corpus están en 2027) |

**Lo que este recorrido dejó por el camino**: la generación de informes **no existía** —el
endpoint devolvía un `run_id` sintético sin ejecutar el grafo—, no había pantalla donde abrir
un workspace, la subida de ficheros no se persistía, el rastreo de sitios fallaba siempre y el
«PDF» del informe de calidad era un DOCX. Diecinueve hallazgos, todos arreglados con TDD.
Detalle en `planificacion/PROJECT_STATE.md`, entradas VER.1–VER.8.

---

## Ya verificado por el agente en navegador y por API (2026-08-17, Bloque PRO) — no repetir

Backend en `:8001`, frontend de desarrollo en `:5173`, sandbox en `:5099`, sesión real como
`fabra@uji.es`. Modelos reales: `gemini-2.5-flash` en el nivel 2 y `gemini-2.5-pro` en el 3.

| Camino | Qué se comprobó, con evidencia |
|---|---|
| Modelos por nivel desde la pantalla | Las dos configuraciones creadas **desde `/hub/llm-configs`** (nivel 2 → `gemini-2.5-flash`, nivel 3 → `gemini-2.5-pro`), con su marca de «por defecto» y el relevo de FIX.1 |
| Script escrito por el modelo | «Describir → generar» produce un script que la auditoría determinista deja en **SAFE**, y el **nivel 3 lo devuelve como `duda`** con dos objeciones que un AST no puede ver: asume los nombres de columna y asume la primera hoja |
| Script ejecutado en el sandbox | Excel real subido desde el asistente → sandbox Docker → tabla con `capítulo`/`credito_inicial`/`obligaciones_reconocidas` y métrica `porcentaje_ejecucion: 68,52 %` (166.500/243.000, comprobado a mano) → validación **200** |
| Script aprobado dentro de un informe | Propuesta `platform` → anonimización → sandbox → cola → re-test con `hash_matches` → **aprobado** en una plantilla global nueva → workspace → Excel subido → **`assembled`** con el bloque `extracted` y su tabla en la vista previa |
| Transformación de datos | Bloque `DATA_TRANSFORM` determinista: renombra `capitulo`→`seccion` y quita una columna, y **las dos tablas** salen en la vista previa. En modo IA, `gemini-2.5-flash` traduce «renombra capitulo a seccion y quita obligaciones_reconocidas» a las dos operaciones (`model_used` registrado en el bloque) |
| Gráfico en el informe | Bloque `CHART` determinista → PNG de matplotlib guardado en el almacén y servido en la vista previa como data URI (35 KB) |
| Los once tipos de gráfico y su presentación (PRO.8) | Los once renderizan un PNG de verdad sin pasar por ningún modelo. Y el gráfico se **miró**, no sólo se contó: `barh` con título, etiquetas de eje legibles, cifras encima de las barras y orden descendente, publicable tal cual. Ahí apareció lo que ningún test veía: las cifras salían en formato inglés (`128,340.55`) en un informe de una institución española |
| Una petición de gráfico no genera código (PRO.8) | «Barras horizontales del gasto por capítulo, de mayor a menor, con las cifras» devuelve **configuración declarativa** en una sola llamada. Antes eso llamaba a `generate_script()`: modelo + auditoría + sandbox para lo que es un campo |
| Importes en texto y columna calculada (PRO.9) | Hoja con `"128.340,55 €"`: `sum()` sobre la columna devolvía la **cadena concatenada** `'128.340,55 €45.120,00 €12.890,75 €(1.500,00)'` —sin error—; tras `to_number`, **184.851,30**. Cadena completa `to_number` → `normalize_text` → `compute_column` (`pct_ejecucion`) → `sort_rows` verificada sobre esa hoja, con el paréntesis contable leído como negativo |
| Exportación del informe | `GET /redaccion/workspaces/{id}/export` → DOCX de 56 KB con **2 tablas reales, 1 imagen y 0 párrafos con HTML** |
| Biblioteca de prompts de actividad | `/hub/activity-prompts` muestra las actividades con su nivel y su origen; puesto el nivel 3 a «generar script», **la propuesta siguiente la escribe `gemini-2.5-pro`**; borrado el override, vuelve a `flash` |
| Copiloto | Se abre desde el botón de la pantalla del informe, en su pestaña. Primera pregunta **56 s** (construye el índice sobre los `docs/` reales), segunda **3,3 s**; respuestas correctas citando `docs\DECISION_EXTRACCION_Y_DESPLIEGUE.md` y `docs\CONTRATO_MD_CORPUS.md` |

**Lo que este recorrido dejó por el camino**: la auditoría era binaria y no veía rutas
absolutas; el fichero de prueba **no llegaba nunca al sandbox** (se mandaba una ruta del host);
el asistente de scripts era un esqueleto de la fase 3 en adelante; un script aprobado dejaba la
plantilla **ilegible**; los datos extraídos **no se veían** en ningún informe (ni por script, ni
por Excel, ni por PDF); el ETL no tenía modelo y no encontraba su tabla de origen; el bloque
CHART **no dibujaba nada**; el informe **no se podía exportar**; y el copiloto contestaba «no
tengo esa información» a preguntas cuya respuesta está en `docs/`; una plantilla **no podía pedir
ni un título** para su gráfico y pedir uno «usual» costaba generar código; y los importes en
formato de aquí llegaban como texto, así que **sumarlos concatenaba sin dar error**. Todo
arreglado con TDD; detalle en `planificacion/PROJECT_STATE.md`, entradas PRO.1–PRO.9.

---

## Matriz de lo irreducible

### `agents_hub` (RAG, ingesta de conversación, LangGraph)

| Qué se prueba | Por qué NO lo hace el agente en navegador | Quién |
|---|---|---|
| Respuesta real de un chatbot con corpus cargado y LLM en producción (Gemini/OpenRouter) | El coste y la clave de API son del usuario; el agente no debe gastar cuota ajena sin permiso | Alguien con las claves de API configuradas |
| Calidad subjetiva de una respuesta en valenciano/catalán frente a castellano | Juicio lingüístico — un test automático mide recall de citas, no naturalidad | Persona con criterio institucional en las tres lenguas |
| SSO SAML contra el IdP real de la UJI | Sin IdP de pruebas disponible; el flujo completo (redirect + assertion) no es simulable | Alguien con acceso al IdP institucional |

### `modules/automation` (flows, ETL, sandbox de scripts)

| Qué se prueba | Por qué NO lo hace el agente en navegador | Quién |
|---|---|---|
| Aislamiento de red real del `script-sandbox` Docker (sin DNS a `postgres`, sin salida a internet) | Exige inspeccionar `docker inspect` y ejecutar comandos dentro del contenedor prod; cubierto por `pruebas_manuales_promptSBX_4.bat`, vigente | Alguien con Docker Desktop y el stack `docker-compose.prod.yml` levantado |
| Ejecución de un script real contra un sistema externo (SharePoint, correo, ERP institucional) | Credenciales y sistemas reales de la UJI, no reproducibles en local | Alguien con acceso a esos sistemas |

### `modules/redaccion` (plantillas, borrador LLM, anonimización, exportación)

> ✅ **Desbloqueado el 2026-08-10** (hallazgo #2 de la tabla de arriba): el 500 de
> `GET /hub/redaccion/templates` para sesiones con `user_id` no-UUID está arreglado, así que
> las filas de esta tabla ya se pueden recorrer.

| Qué se prueba | Por qué NO lo hace el agente en navegador | Quién |
|---|---|---|
| Calidad de la anonimización sobre un documento con datos personales reales | El agente no debe procesar PII real; los tests usan datos sintéticos | Alguien con un documento de prueba ya anonimizado por otra vía, o con autorización expresa para usar uno real |
| Fidelidad del borrador LLM generado frente a lo que un redactor humano esperaría | Juicio de calidad editorial, no verificable por regla. **Ahora sí hay algo que juzgar**: desde VER.1/VER.4 el informe se genera de verdad y el texto sale de los datos extraídos | Persona con criterio de redacción institucional |
| **Calidad del script que escribe el modelo sobre un documento real de la UJI** (PRO) | El agente comprueba que el script pasa la auditoría, se ejecuta y devuelve una tabla; **no si esa tabla es la que se pedía**. Con un Excel sintético las columnas son las que el propio agente inventó: la prueba de verdad es un fichero institucional real, con sus cabeceras en dos filas, sus totales intercalados y sus celdas combinadas | Quien conoce el dato: alguien de gestión económica o de la unidad que produce ese fichero |
| **Una hoja de cálculo real de la unidad, transformada** (PRO.9) | El agente comprobó que los importes en formato de aquí se convierten y se suman, que la columna calculada sale bien y que una hoja ancha se pone en largo — con hojas que se inventó él. Lo que no puede saber es si **tus** hojas tienen alguna forma que el catálogo no cubre, ni si las cifras del informe cuadran con las tuyas. Dos cosas concretas a mirar: que el plan ponga `to_number` **antes** de sumar (si no, la cifra sale mal sin error), y que una hoja en formato inglés **falle diciéndolo** en vez de dar otra cifra | Quien produce o usa esa hoja: gestión económica o la unidad correspondiente |
| **Si la respuesta del copiloto es útil o sólo correcta** (PRO.6) | El agente puede comprobar que cita un fichero real de `docs/` y que la cita sostiene la frase. Que la respuesta **resuelva la duda de quien la hizo** —en vez de recitar el documento— es juicio de quien pregunta | Cualquiera que trabaje con la plataforma y tenga una duda de verdad |
| Exportación final (DOCX/PDF) abierta en Word/Adobe reales, con la maquetación institucional | Desde PRO.5 el informe **se descarga de verdad** (`GET /redaccion/workspaces/{id}/export`, DOCX con tablas e imágenes), y el agente comprueba estructura y tamaño; que "se vea bien" en Word y que la maquetación sea la institucional, no | Cualquiera con Office/Adobe instalado |
| PDF **real** del informe de calidad de curación | En esta máquina no hay LibreOffice, así que la exportación cae a DOCX —y desde VER.7 lo dice en el tipo y la extensión en vez de mentir—. Verificar el PDF exige un entorno con LibreOffice instalado | Alguien con LibreOffice, o el despliegue donde vaya a correr |
| Rastreo de un sitio con enlaces servidos en HTML (p. ej. `www.uji.es`) | El sitio local del corpus pinta sus fichas con JavaScript, así que un rastreador estático sólo alcanza el índice y el buscador. La profundidad real no se puede medir contra él | Cualquiera, apuntando un sitio nuevo a una web institucional real |

### `frontend/src/widget` (chatbot público embebible)

| Qué se prueba | Por qué NO lo hace el agente en navegador | Quién |
|---|---|---|
| El widget embebido en una página real de la UJI (no `widget.html` de laboratorio) | Requiere publicar el script en un dominio real de la universidad | Alguien con acceso a publicar en un sitio de la UJI |
| Citas como pills (lo que probaba el difunto `prompt9CBis11.bat`) contra un chatbot con corpus real | `widget.html` sigue apuntando a un `chatbot_id` de fixture (`E2E Bot`) inexistente **y** autentica con el `data-token` que SEC.8.5 dejó de leer. Hace falta un chatbot `public_anon` con credencial de sitio y corpus cargado: los pasos están en `pruebas_manuales_plataforma.bat` CAMINO 1(c)-(d) | Alguien que configure ese chatbot de prueba con datos reales |

### `themes` (identidad visual)

> ✅ **El widget ya aplica el tema del chatbot** desde el 2026-08-10 (hallazgo #3 de la tabla de
> arriba), y SEC.8.6 movió los temas del disco a la BD. Las dos filas de abajo pasan por tanto a
> ser irreducibles de verdad: la pieza que faltaba existe. Lo que **sigue** sin existir es la
> pantalla de temas del panel admin —queda para un prompt propio—, así que crear y aplicar un
> tema va por API; el CAMINO 1(c) de `pruebas_manuales_plataforma.bat` lleva los `curl` exactos.

| Qué se prueba | Por qué NO lo hace el agente en navegador | Quién |
|---|---|---|
| Tipografía, color y tono del texto frente a la identidad visual institucional de la UJI | Juicio subjetivo de diseño; el agente puede comprobar que el tema carga, no si "es la UJI" | Diseño / comunicación institucional |
| El tema de una organización aplicado al widget en una página real | Depende del punto anterior (widget en dominio real) | Igual que el punto anterior |

### Servidor MCP (`mcp_server/`)

| Qué se prueba | Por qué NO lo hace el agente en navegador | Quién |
|---|---|---|
| Conexión real desde un cliente MCP (Claude Desktop, Cursor…) por stdio | No tiene superficie HTTP ni de navegador; es un proceso stdio que un cliente MCP lanza | Alguien con un cliente MCP instalado y `docs/MCP_SERVER.md` a mano |
| Autoría de una plantilla de redacción de principio a fin usando las tools MCP desde un cliente real | Igual que el punto anterior — el agente puede (y ha) probado las 54 tests automáticas, no la experiencia de uso real | Igual que el punto anterior |

### El agente de ejecución local ya no se prueba: no existe

Aquí había dos filas —el agente local con su vigilante de carpeta en la máquina de un usuario
final, y el canal WebSocket edge↔cloud con el grafo orquestando y el edge ejecutando—. **Las dos
se retiraron el 2026-09-04 con `client_app/`**, y no porque se den por buenas: **no hay código que
probar**. Pedirle a una persona que instale un agente inexistente es la peor clase de prueba
pendiente, porque parece trabajo y no se puede ni empezar.

**Y no vuelven**: el 2026-09-23 se decidió no construir el agente local. Es un límite deliberado,
no una tarea aplazada. Ver `docs/ESPECIFICACIONES.md` §10.

### Despliegue `DEPLOY_MODE=cloud|edge`

| Qué se prueba | Por qué NO lo hace el agente en navegador | Quién |
|---|---|---|
| Que arrancando con `DEPLOY_MODE=edge` los routers cloud (auth admin, organizaciones, temas) de verdad no responden | Exige levantar el servidor dos veces con variables de entorno distintas; no es una prueba de un único navegador con sesión ya iniciada | Alguien con dos arranques del backend, o esperar a D.0-D.5 y probarlo contra el despliegue real (MAN.4) |

---

## Lo que YA no necesita entrar aquí (cubierto por otra vía)

- Cualquier pantalla del Hub o de Curación con datos ya sembrados: cubierto en la tabla de
  arriba y en los tests de componente (Vitest) de cada pantalla.
- Accesibilidad automática (contraste, roles ARIA, `<label>` asociado): la cubre el gate de
  `axe` en CI desde la Fase 20. Lo que **no** cubre axe —orden del foco, que el lector de
  pantalla anuncie el nombre correcto— va en MAN.3, no aquí.
- Paridad de traducción es/ca/en: la cubren los guardarraíles `adminI18nCoverage.test.ts` y
  `curationI18nCoverage.test.ts`.
- Seguridad de cabeceras, límite de peticiones, aislamiento multi-tenant: cubierto por los
  tests automáticos del Bloque SEC; lo irreducible de SEC ya vive en
  `pruebas_manuales_bloqueSEC.bat` (vigente, con la única corrección de ruta de esta sesión).

---

## `.bat` de la raíz: inventario (MAN.1)

| Fichero | Estado | Motivo |
|---|---|---|
| `pruebas_manuales_bloqueFASE11.bat` | Vigente | Instalación one-click; `bootstrap.py` sigue creando "Chatbot de Ejemplo" con 3 prompts tal como describe |
| `pruebas_manuales_bloqueRAG.bat` | Vigente (corregido) | La sección de huecos de corpus apuntaba a `/hub/content-quality`, retirado por CUR.2; corregido a `/curation/findings` |
| `pruebas_manuales_bloqueSEC.bat` | Vigente (corregido) | El paso 5 apuntaba a `/admin/chatbots`, una ruta que nunca existió (siempre fue `/hub/chatbots`); corregido. Migración `s6b7c8d9e0f1` sigue siendo head |
| `pruebas_manuales_prompt9CBis11.bat` | **Borrado (2026-08-12)** | Inejecutable desde SEC.8.5. Su banco de pruebas, `frontend/widget.html`, autentica con `data-token` (un JWT de rol `admin` incrustado y caducado), y el widget **ya no lee ese atributo**: SEC.8.5 retiró el Bearer privilegiado y ahora manda `X-Widget-Key` desde `data-widget-key`. Sumado al `chatbot_id` de fixture que MAN.1 ya había señalado (`9d6eed7d…`, «E2E Bot», ausente de todo sembrado), el paso 2 del guion da 401 haga lo que haga quien lo ejecute. La comprobación de las pills sobrevive en `pruebas_manuales_plataforma.bat` CAMINO 1(d), que sí emite credencial de sitio |
| `pruebas_manuales_prompt9CBis8.bat` | **Borrado** | Describía subir un PDF desde una pestaña "Documentos" dentro de la edición del chatbot; esa UI la sustituyó por completo la página `/hub/documents` independiente (CAL.1-CAL.4) |
| `pruebas_manuales_prompt9CBis9.bat` | **Borrado** | Describe la tab "Fuentes web" dentro de Documentos, retirada por CAL.2, y el layout de la tabla que CAL.3/CAL.4 rehicieron |
| `pruebas_manuales_prompt9Q_9.bat` | **Borrado** | Rutas `/hub/sites` y `/hub/content-quality` movidas por CUR.2 a `/curation/*`; el "panel de mapeo" anidado bajo una fila de sitio ya no existe, ahora es la página `Publicación` independiente. Su contenido queda cubierto por la tabla de "ya verificado" de arriba |
| `pruebas_manuales_promptAUTH_4.bat` | Vigente | Login, tokens de acceso y SSO opcional sin cambios desde AUTH.4 |
| `pruebas_manuales_promptFIX1.bat` | Vigente | Selector de modelo y escenarios de prueba sin cambios desde FIX.1 |
| `pruebas_manuales_promptROL_2.bat` | Vigente | Renombrado Partner→Admin, Client→Organización sin cambios desde ROL.2 |
| `pruebas_manuales_promptSBX_4.bat` | Vigente | Aislamiento Docker del sandbox, infraestructura no tocada por ningún bloque posterior |
| `pruebas_manuales_plataforma.bat` | **Nuevo (MAN.2)** | `.bat` maestro con menú/parámetro para los 4 caminos que cruzan módulos; ver la sección MAN.2 más arriba |
