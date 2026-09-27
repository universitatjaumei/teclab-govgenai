# Estado del Proyecto — Gov Gen AI Platform

> Actualizado automáticamente al final de cada prompt de desarrollo.
> Fuente de verdad para saber en qué paso está cada plan activo.

---

## Lo que viene después de la Fase 1: el roadmap, no los planes de fase

**Los planes `Plan_TDD_Fase2.md` y `Plan_TDD_Fase3.md` se cerraron el 2026-09-23 y no se van a
ejecutar.** Lo que falta por construir vive ahora en **[`../ROADMAP.md`](../ROADMAP.md)** y en los
hitos de GitHub, con una *issue* por unidad de trabajo en vez de un prompt por paso:

| Tema del roadmap | Hitos | Qué sustituye |
|---|---|---|
| **Automatización gobernada** (tema 4) | 9–12, *issues* AUT.1–AUT.13 (#112–#124) | La Fase 2. 2.B quedó vacía con NIC, 2.C está hecha bajo otros nombres y **2.A se descarta** |
| **Trámites asistidos con IA** (tema 8) | 13–16, *issues* TRA.1–TRA.13 (#126–#138) | La Fase 3. **No se construye gestor de expedientes**: el institucional es la fuente de verdad y la plataforma no cambia nunca su estado |

**Cómo se ejecutan.** Igual que un prompt: RED → GREEN → REFACTOR, verificaciones de cierre, un
commit firmado por *issue* con su número en el asunto. Lo que cambia es dónde está escrito el
alcance —en la *issue*, no en `fase1/`— y que al cerrar se actualiza esta tabla y se cierra la
*issue*, en vez de mover un cursor.

Los prompts de la **Fase 1** siguen donde estaban y se ejecutan como siempre; su cursor es el de
la sección siguiente.

---

## Planes activos

### Plan_Contrato_OpenAPI.md — Alineación Backend/Frontend con OpenAPI + Orval

| Bloque | Último completado | Siguiente | Estado |
|--------|-------------------|-----------|--------|
| CF.1 — Exportación OpenAPI | CF.1.2 ✅ | — | ✅ Completo |
| CF.2 — Orval + generación | CF.2.3 ✅ | — | ✅ Completo |
| CF.3 — Compilación TypeScript | CF.3.3 ✅ | — | ✅ Completo |
| CF.4 — Formulario piloto Chatbot | CF.4.4 ✅ | — | ✅ Completo |
| CF.5 — CI | CF.5.2 ✅ | — | ✅ Completo |

**Plan completo (CF.1–CF.5). No tiene cursor propio.** El único cursor vivo del proyecto es el de `Plan_TDD_Fase1.md`, en la sección siguiente. *(Esta línea decía «Cursor actual: 9B.6» desde que se cerró este plan; 9B quedó completo en 9B.14 y el puntero llevaba meses obsoleto, engañando a quien leyera el fichero de arriba abajo. Limpiado el 2026-07-30.)*

---

### Plan_TDD_Fase1.md — Hub Informativo, Personalización y Redacción (MVP)

| Bloque | Último completado | Siguiente | Modelo sugerido siguiente | Estado |
|--------|-------------------|-----------|---------------------------|--------|
| Fase 0 — Infraestructura | — | — | — | ✅ Eliminada (heredada) |
| Subfase 1.A — Chatbots Públicos (9B) | 9B.14 ✅ | — | — | ✅ Completo |
| Redacción Contract-First (9R) | 9R.10.2 ✅ | — | — | ✅ Completo (vertical slice MVP GREEN) |
| Subfase 1.B — Identidad Visual | 10.11 ✅ | — | — | ✅ Completo — Fase 10 (temas/plantillas) |
| Subfase 1.C — Privacidad, Diseño y Exportación | 1C.4 ✅ | — | — | ✅ Completo — 1C.0–1C.4 |
| Fase 13 — NER reversible en redacción | 13.2 ✅ | — | — | ✅ Completo |
| Fase 20 reducida — WCAG transversal | 20.2 ✅ | — | — | ✅ Completo — 9/9 tests verdes, CI gate activo, A11Y_CHECKLIST.md creado |
| Bloque SBX — Sandbox aislado de scripts | SBX.4 ✅ | — | — | ✅ Completo — SBX.1+SBX.2+SBX.3+SBX.4 cerrados |
| Bloque 9Q — **Motor de auditoría de sitios web** (antes «Calidad de Contenido Web Ingestado») | 9Q.9 ✅ | — | — | ✅ Completo — 9Q.0–9Q.9 cerrados. **Alcance reescrito el 2026-08-02** (`docs/DECISION_CURACION_SEPARADA.md`): el código no cambia, cambia de qué es parte. Deja de ser «calidad del contenido ingerido al servicio del RAG» y pasa a ser **el motor de la herramienta de curación**, que es previa al asistente. La salida principal es el **informe de auditoría** —vale por sí solo, sin chatbot—; la higiene del retriever es el efecto secundario. **No hay ingesta automática de web a corpus**: una página nueva es señal para el curador, no disparador. Ya estaba latente en su propio modelo —`HubWebSite` cuelga de `organizacion_id` y no tiene `chatbot_id`—. El movimiento de código va en el Bloque CUR |
| Bloque AUTH — SSO SAML + PAT (adelanto 1.B.1) | AUTH.4 ✅ | — | — | ✅ Completo — AUTH.1-AUTH.4 (SP SAML + provisioning + PAT/auth dual + UI login SSO/gestión PAT). Backend 43 tests + frontend 8 tests verdes |
| Bloque MCP — Servidor MCP stdio (plantillas+chatbots+test_chat) | MCP.4 ✅ | — | — | ✅ Completo — MCP.1-MCP.4 (scaffolding + tools plantillas/chatbots/test_chat + docs/MCP_SERVER.md). 16 tools + 5 resources, 54 tests MCP verdes |
| Bloque ROL — Renombrado institucional (Partner→Admin, Client→Organización) | ROL.2 ✅ | — | — | ✅ Completo — ROL.1 (backend) + ROL.2 (frontend: Orval regen, rutas /organizaciones, i18n es/ca/en, roles superadmin/admin). tsc sin errores, Vitest verde |
| Fase 11 — Autoinstalación y Distribución | 11.3 ✅ | — | — | ✅ Completo — 11.1 (generate_env.sh + .env.example), 11.2 (docker-compose.prod.yml one-click) y 11.3 (setup.sh + bootstrap idempotente). Suite `tests/infra`: 58 passed, 0 skipped |
| Bloque SEC — Endurecimiento de seguridad (bloqueante de despliegue) | SEC.7 ✅ | — | — | ✅ **Completo (2026-08-03)** — los 9 prompts: SEC.1 (contraseña en el login de Admin), SEC.2 (aislamiento entre organizaciones), SEC.2.1 (modo de acceso por chatbot + identidad delegada), SEC.3 (CORS por entorno), SEC.4 (límite de peticiones, contabilidad de tokens y cuotas), SEC.4.1 (vigencia y presupuesto), SEC.5 (temas), SEC.6 (validación de subidas, adelantado) y SEC.7 (docs off + cabeceras). **Pendientes las pruebas manuales del bloque.** ~~SEC.1~~, ~~SEC.2~~, ~~SEC.2.1~~, ~~SEC.3~~, ~~SEC.4~~, ~~SEC.4.1~~, ~~SEC.5~~, ~~SEC.7~~, SEC.4, **SEC.4.1**, SEC.5, SEC.6, SEC.7 (login con password A1, aislamiento multi-tenant A2, **modo de acceso por chatbot + identidad delegada**, CORS, **contabilidad de tokens + cuotas multi-sujeto**, **vigencia y presupuesto por chatbot**, temas, uploads, docs/headers). Planificado 2026-07-11, ampliado 2026-07-27 |
| **FIX.1** — El modelo de un chatbot no se puede cambiar | FIX.1 ✅ | — | — | ✅ **Completo (2026-08-02)** — detalle en el historial. ~~Pendiente— **añadido el 2026-08-02** desde las pruebas manuales del Bloque RAG, que quedaron bloqueadas. Un síntoma («el botón de ejecutar no hace nada») tapaba cuatro fallos: `gemini-2.0-flash` retirado por Google (404), el 500 de la ejecución invisible porque la mutación no tiene `onError`, `llm_config_id` **hardcodeado en el formulario y ausente de `ChatbotUpdate`** —la API no permite cambiar el modelo—, y el 409 al marcar por defecto en vez de demotar la anterior. **Riesgo latente**: editar cualquier chatbot en la UI le reasigna el modelo en silencio |
| Bloque CUR — La curación como producto propio | CUR.2 ✅ | — | — | ✅ **Completo (2026-08-09)** — decisión en `docs/DECISION_CURACION_SEPARADA.md`. CUR.1 mueve `ingestion/quality/` + spiders a `modules/curation/` (el `gap_detector` **se queda** en `agents_hub/ingestion/`: es la señal que el asistente emite hacia la curación); CUR.2 le da superficie y navegación propias en el frontend (`frontend/src/curation/`: Sitios, Auditoría, Hallazgos, Publicación) y hace explícito el paso de publicación (`CorpusSelectionService` → `PublicationPage`, cada candidata con su propio botón). **No reescribe nada y no toca el esquema.** **Suite backend completa con Docker levantado: 1697 passed, 1 skipped, 0 failed** — el primer pase sin BD (1414 passed, 280 skipped) escondía una regresión real en `GapFinding` (faltaban `site_id`/`page_id`, que un test de 9Q sigue comprobando), corregida en `d9ed15f` al re-ejecutar contra Postgres real. Suite frontend completa en serie: **274 passed, 0 failed**, `tsc --noEmit` limpio |
| Bloque CAL — Deuda de calidad pre-repo público | CAL.4.1 ✅ | — | — | ✅ **Completo (2026-08-09)** — CAL.1 (retirar NiceGUI del árbol activo + Caso B en client_app), CAL.2 (capa API del frontend desde el contrato, **cierra CF.4**), CAL.3 (descomponer `DocumentsPage`), CAL.4 (i18n `ca` a paridad + etiquetas accesibles), CAL.5 (carga por ruta + retirada de shims, más el borrado de los 3 scripts huérfanos) y **CAL.4.1** (las 41 claves de la pantalla de documentos que vivían sólo como *default*, subidas a `es/ca/en admin.json`; nuevo guardarraíl `should_not_keep_admin_keys_only_as_inline_default` que el test de paridad no podía cazar por construcción). **Suite frontend completa en serie: 264 passed, 0 failed. tsc --noEmit sin errores.** Planificado 2026-07-11 |
| Bloque MAN — Validación manual de la plataforma completa | MAN.1 ✅ | MAN.2 (falta ejecución humana) | Sonnet | ▶ **MAN.1 completo (2026-08-09)**: inventario de los 11 `.bat` de la raíz — 3 borrados por caducados, 2 corregidos por ruta muerta, 6 vigentes. `docs/PRUEBAS_MANUALES.md` con la matriz por módulo. Recorrido real en navegador (Hub + Curación completos, MCP 54 tests, widget construido) **destapó y corrigió un bug real** (`6cba8fc`, `SitesPage`/`useDeleteSite` sin invalidar la lista). **MAN.2 con el `.bat` maestro escrito y probado en seco** (`pruebas_manuales_plataforma.bat`, commit `aaf3b86`) y **recorrido en vivo de los caminos 1 y 2** con datos reales (organización, 2 chatbots, PDF ingerido, consultas reales a Gemini, `GapFinding` de CUR.1 ejercitado con 0 huecos esperados). **Hallazgo #2 arreglado (2026-08-10)**: el 500 de `GET /hub/redaccion/templates` (y 5 sitios más) para SuperAdmin/Admin con `user_id` no-UUID — los 6 sitios de `hub_redaccion_router.py` usan ahora el `_actor.user_to_uuid` compartido (uuid5 determinista) que `llm_drafts_router.py`/`scripts_router.py` ya aplicaban; no era una decisión de diseño abierta, era el mismo patrón sin aplicar de forma consistente. De paso, arreglados dos rojos preexistentes que este mismo módulo tenía escondidos (`test_llm_drafts_router.py` no colectaba por un fixture con rol obsoleto de antes de ROL.1/ROL.2; una aserción esperaba `"draft"` donde el código deliberadamente da `"ingesting"` desde 9R.10.2). 5 tests nuevos, `tests/redaccion` completo: 129 passed. Detalle en `docs/PRUEBAS_MANUALES.md` §Hallazgos. **Hallazgo #3 arreglado (2026-08-10)**: el widget público no consumía ningún tema. La investigación destapó que `HubChatbot`/`HubOrganizacion.theme_config` eran columnas huérfanas y que el sistema real de temas (`hub_themes_router.py`, cascada plataforma→organización→chatbot ya modelada) tenía `apply_theme_to_chatbot` como stub sin persistir (`# TODO`) — completado (guarda `{"theme_id":...}` en `theme_config`) más `GET /hub/themes/for-chatbot/{chatbot_id}` nuevo, que solo devuelve `config` (SEC.5 había cerrado la lectura pública de temas por censo de organizaciones; este endpoint no la reabre) y exige `assert_chatbot_access` como `/hub/chat`. El widget reutiliza `injectThemeCSS` de `ThemeProvider` (exportada para la ocasión) al montar. Verificado en navegador de punta a punta con un tema real aplicado. 10 tests backend + 6 frontend nuevos. **Descubierta de paso una contención preexistente de vitest en paralelo** (falsos rojos distintos en cada pasada, ya la documentaba la nota de abajo de este mismo fichero para A11y.test.tsx): confirmado que en serie (`--no-file-parallelism`) da 281/281, igual que las cifras "en serie" de cierres anteriores (CUR.2, CAL.4.1) — no es una regresión de este cambio. **Alcance explícitamente aparcado a petición del usuario**: completar el editor de temas del panel admin con cabecera/logo va en un prompt propio — es la definición de la plantilla, no la resolución que consume el widget. **Falta el criterio de cierre de MAN.2**: que el usuario ejecute el `.bat` de principio a fin. Pendientes: MAN.3 (lector de pantalla real + identidad visual) y MAN.4 post-deploy |
| Bloque SEC.8 — Endurecimiento pre-deploy (2ª auditoría) | SEC.8.5 ✅ | — | — | ✅ **Completo (2026-08-10)** — los 8 prompts. SEC.8.0 gate del sembrado de desarrollo (`56d5ef4`), SEC.8.1 IDOR horizontal en los routers post-SEC.2 (`1784519` + `391b23a`), SEC.8.2 subidas (`77c2a24`), SEC.8.3 sandbox y auditor AST (`97baafc`), SEC.8.4 proxy/secreto/SAML (`754127f`), SEC.8.6 temas en BD (`c604086`), SEC.8.7 tests de la raíz (`bd36e81`), SEC.8.8 crawler cableado (`4239ad9`) y SEC.8.5 credencial de sitio del widget (`8d10e79`). **Suite backend completa: 1782 passed, 1 skipped, 0 failed. Frontend en serie: 276 passed, 0 failed. `tsc --noEmit` limpio.** Dos migraciones aplicadas (`t7c8d9e0f1g2` temas, `u8d9e0f1g2h3` credenciales de widget). **Lección de método**: cerrar SEC.8.1 verificando solo `tests/api` dejó 30 rojos que la suite completa destapó — los directorios que toca un prompt incluyen los tests unitarios de los routers, no solo los de su superficie | ▶ **BLOQUEANTE DE DESPLIEGUE, va antes de D.0**. Nace de `docs/AUDITORIA_PRE_DEPLOY.md` (2026-08-10). **SEC.8.0 hecho** (`56d5ef4`): gate del sembrado de desarrollo (CR-1, el superadmin `fabra@uji.es`/`admin1234` ya no se siembra fuera de `development`). Pendientes SEC.8.1–SEC.8.8: aislamiento multi-tenant en los routers post-SEC.2 (CR-2 + IDOR horizontal, **Opus**), subidas (path traversal + validate_upload), sandbox (gate prod + auditor AST), cabeceras/SAML/JWT placeholder, widget sin Bearer privilegiado, temas persistentes en BD (B1), limpieza de los 14 tests rotos de la raíz `tests/` (B3), y decisión sobre el crawler de curación (B2). Prompts en `Plan_TDD_Fase1.md` §Bloque SEC.8 |
| **Bloque EXT** — Frontera de la extracción (corpus vs contexto) | EXT.3 ✅ | — | — | ✅ **Completo (2026-08-11)** — EXT.1 (`b9c2a94`) al corpus solo `.md` del contrato, EXT.2 (`66acd4a`) contexto con pdfplumber y guarda de escaneado, EXT.3 retirada de Docling y medición. **Suite backend: 1796 passed, 3 skipped, 0 failed** (con Docling y RapidOCR ya ausentes del entorno). Frontend 281 passed, `tsc` limpio. **Medición para D.4**: app en reposo 627 MB, pico 968 MB con un PDF de 40 páginas; el que manda ya no es Docling sino `torch`+`transformers`+`sentence-transformers`, que están por los modelos locales y no por la extracción — hacerlos extra opcional queda anotado como candidato en D.4 | **Cuando se planificó: va ANTES de Deploy**. Decisión en `docs/DECISION_EXTRACCION_Y_DESPLIEGUE.md` (2026-08-10). Separa dos cosas que se llamaban igual: al **corpus** solo entra `.md` conforme al contrato —lo convierte el pipeline de curación, que vive fuera y previsiblemente pasará a plantilla + pandoc—, y el **contexto temporal** (PDF que alguien aporta para preguntar, o fuente de un informe) se extrae con **pdfplumber**, que ya es dependencia directa. EXT.1 cierra la puerta del corpus, EXT.2 sustituye Docling por pdfplumber en las dos vías de contexto **con guarda de documento escaneado —que debe fallar en alto, no ingerir un documento vacío—**, EXT.3 retira Docling del árbol y **mide la huella**, que es lo que dimensiona la VM en D.4. El OCR no se pierde: ya vive en la curación, con `origen_del_text` para declararlo |
| **Bloque REV** — Primer vistazo del usuario a Plataforma | REV.10 ✅ | — | — | ✅ **Completo (2026-08-23)** — los 10 prompts, del repaso del usuario al módulo Plataforma. REV.1 guardarraíl del DSN del entorno + borrado de las 97 filas `ada-*`; REV.2 valores por defecto editables; REV.3 la opción activa del menú con negrita y barra; REV.4 el selector del logotipo accionable y sin exigir tema previo; REV.5 el enlace de vigencia, que llevaba a Informes por dos fallos encadenados; REV.6 validar la vigencia desde la cola (endpoint nuevo + migración `p6i7j8k9l0m1`); REV.7 buscar y filtrar las actividades por módulo; REV.8 borrar a quien nunca entró, ver al superadministrador y no quedarse sin ninguno; REV.9 la cascada de color llega al panel; REV.10 la organización se elige una vez, en la cabecera. **Suites completas: backend 2887 passed, 1 skipped, 0 failed (26:08, `-n0`); frontend 630 passed, 0 failed; `tsc --noEmit` limpio.** Una migración aplicada. Contrato regenerado (146 rutas). **Los diez prompts de UI verificados en navegador** contra el servidor real, con los artefactos de verificación retirados. **Cuatro defectos los destapó el navegador y no los tests**: la firma de la vigencia iba a `revisat_per` —un campo del frontmatter del corpus—, `require_role` es coincidencia exacta y devolvía 403 a un superadministrador, el botón de validar fallaba en silencio, y guardar un color no refrescaba el panel. **El nombre del bloque colisionaba** con un «Bloque REV» pendiente desde el 2026-08-11 (revisión humana de respuestas): como ése no tenía código y éste ya estaba en commits, tests y una migración, se renombró el pendiente a **RHR**. **Pendiente del mismo repaso, planteado por el usuario el 2026-08-23 y no abordado aquí**: Organizaciones vive bajo Chatbots y su router ya exige `plataforma`; el tema de una organización no lo ve un superadministrador porque `/themes/resolved` sólo funde el nivel de organización cuando la persona pertenece a una sola; y los prompts están en dos pantallas con dos modelos distintos |
| **Bloque REV (continuación)** — REV.11 a REV.13 | REV.13 ✅ | — | — | ✅ **Completo (2026-08-23)** — los tres prompts del segundo repaso del usuario. REV.11 mueve Organizaciones a `/plataforma/organizaciones`: su router **ya** exigía el módulo `plataforma`, así que quien tenía ese módulo y no `chatbots` no llegaba a la pantalla que su propio módulo protege. REV.12 hace que `/hub/themes/resolved` acepte la organización elegida en la cabecera, con `assert_org_access` —hasta ahora la cascada fundía el nivel de organización sólo para quien pertenece a una sola, y un superadministrador no pertenece a ninguna: configuraba el logotipo de la UJI y no lo veía—. REV.13 añade `/hub/prompts-catalog`, de sólo lectura, que agrega los prompts con su `ambito` a la vista sin unificar dos modelos que no lo son; la edición sigue en el router de cada uno. **Hallazgo de REV.13**: lo que de verdad se ve hoy en Chatbots no son plantillas —hay cero filas en `hub_prompt_templates`— sino el **prompt base** de cada asistente, que es una columna de `hub_chatbots`; entra como tercer ámbito. Los tres verificados en navegador contra el servidor real, con los datos de desarrollo restaurados después
| **Bloque MT** — Multitenencia real: qué está aislado y qué no | MT.7 ✅ (fase 1 completa) | **MT.8** (fase 2, tras el piloto) | Opus | ▶ **FASE 1 COMPLETA (2026-08-24), que es lo que el usuario puso delante del piloto. La fase 2 espera al piloto.** Los siete prompts; el bloque creció el 2026-08-24** con el diseño de la reutilización de configuración entre organizaciones (MT.4 ampliado con la doble elevación, MT.4.2 nuevo para la procedencia, y MT.17–MT.21 en la fase 2). **MT.1**: `core/ambito.py` con la cascada escrita una vez y el guardarraíl que obliga a las 13 tablas de `HubConfigBase` a declarar su ámbito (`__ambito__`). Cuatro valores y no tres, porque varias llegan a la organización **por otra tabla** y meterlas en «de organización» diría que tienen una columna que no tienen. La declaración **no se hereda**: un modelo que extendiera a otro pasaría el guardarraíl con el ámbito del padre sin que nadie decidiera nada. Sin cambio de comportamiento y sin migración: se declara lo que hay hoy, incluido lo global que MT.2 y MT.6 van a cambiar. **MT.2**: `hub_llm_configs` gana `organizacion_id` nullable y la credencial se va a `hub_provider_credentials`, heredable, con los tres métodos que ya estaban en uso —clave literal, **nombre** de variable de entorno (el que sirve a Secret Manager sin meter secretos en la base) y ADC—. **`hub_providers` sigue siendo de plataforma a propósito**: al mirar sus cuatro filas resulta ser un catálogo de tipos sin ninguna `api_key`, así que el plan («`organizacion_id` en las dos tablas») habría exigido cambiarle la clave primaria con una clave ajena por medio para nada. Migración `q7j8k9l0m1n2` aplicada, `downgrade` comprobado. **Dos fallos preexistentes encontrados y arreglados**: `_relevar_default` degradaba por nivel ignorando el propósito —promover un chat nivel 1 dejaba la plataforma sin modelo de embeddings— y cualquier administrador podía renombrar o **archivar** la plantilla de informe de plataforma o la personal de otra persona, porque sólo se comprobaba el rol y nunca de quién es la plantilla. **Planificado y detallado el 2026-08-23.** El usuario decidió que la FASE 1 va ANTES del piloto** (7 prompts: MT.1 la regla del ámbito y su guardarraíl, MT.2 proveedores y modelos por organización, MT.3 la organización hasta el modelo, MT.4 Informes gana la dimensión, MT.5 concesiones y tokens, MT.6 prompts de actividad heredables, MT.7 el inventario); la fase 2 —vista y permisos, 9 prompts— queda para después del piloto y sin detallar, porque depende de cómo quede. Sale de la pregunta del usuario: «cambio de organización y sigo viendo los mismos proveedores y modelos, las mismas personas, los mismos chatbots». **Auditoría hecha, con cifras**. Lo que **sí** está bien: el núcleo operativo está acotado —chatbots, corpus, ingesta, vigencia, curación, temas, vocabulario, interacciones, feedback, escenarios, chat y cuotas—, unas veces por `organizacion_id` y otras por el camino `chatbot_id`/`site_id`; 12 routers pasan por la capa de tenencia y `test_tenant_isolation.py` lo vigila. Eso es lo que filtraría contenido entre municipios, y no lo hace. Lo que **no**: (1) `hub_providers` —con `api_key` dentro— y `hub_llm_configs` son **globales**, sin organización ni camino hacia una, y `get_model_for_tier` no la recibe (8 llamadores); (2) el módulo **Informes no tiene dimensión de organización en absoluto** —`owner_kind` es `user`/`platform`/`superadmin`—, 51 endpoints y 7 modelos; (3) en Personas el dato está y el filtro no, y el listado es sólo de superadministrador, así que un administrador no gestiona a su propia gente; (4) concesiones y tokens van por sujeto, sin organización; (5) los prompts de actividad son globales por diseño; (6) el superadministrador lo ve todo —correcto como permiso— y el selector de REV.10 **no filtra nada todavía**. **El corte propuesto es por migración**: lo que después costaría migrar datos vivos va ANTES del piloto (fase 1, 6-8 prompts, sin cambio de comportamiento: `organizacion_id` nulo = plataforma y se hereda) y la vista y los permisos van DESPUÉS (fase 2, 8-10 prompts). No convierte la instalación en multiinstancia: sigue siendo una base con organizaciones dentro, y la separación física por municipio es el modo `edge` | **MT.3**: `get_model_for_tier` y `get_llm_config_for_tier` reciben la organización, **obligatoria y sin valor por omisión** —un opcional se olvida y resolver plataforma en vez de la organización no rompe nada visible, así que no lo caza ningún test—; los siete llamadores dicen de dónde la sacan (el rastreo del sitio, la ingesta y los de Informes de quien pide, con `organizacion_unica_de`), y un test recorre el **árbol sintáctico** para que ninguno se quede atrás. **MT.4**: `owner_kind` gana `organizacion`, que completa la escalera usuario → organización → plataforma pedida el 2026-08-24; `organizacion_id` en plantillas e informes con CHECK de coherencia; **`is_global` deja de ser columna** y pasa a `hybrid_property` derivada de `owner_kind`, porque eran el mismo hecho en dos sitios; y `POST /templates/{id}/fork`, sin el cual «heredado» significaba «mírala y no la toques» tras el arreglo del 2026-08-24. **La procedencia (MT.4.2) se adelantó a MT.4** porque la bifurcación es su primera consumidora, y meter las columnas antes habría sido dejarlas sin nadie que las lea. Migración `r8k9l0m1n2o3` aplicada, `downgrade` comprobado con los datos intactos (20+2+1 plantillas, 29 informes). **MT.5**: la concesión y el token dicen **dónde** valen, con nulo = «en todas» para no reinterpretar en silencio los permisos de nadie; la unicidad de la concesión pasa a cuatro columnas con `NULLS NOT DISTINCT`, y el token **acota y nunca amplía** —el alcance del dueño se sigue resolviendo en cada validación, como decidió SEC.2—. **MT.6**: `activity` deja de ser único global y los dos campos del override se heredan **por separado**, porque obligar a copiar el texto para cambiar el nivel lo congelaría igual que copiarlo del código; la cadena entera es organización → plataforma → código. **MT.7**: `docs/MULTITENENCIA.md` con el inventario tabla por tabla, enlazado desde `AGENTS.md` y **con un test que lo mantiene honesto** —si una tabla falta o su ámbito no coincide con el que declara el código, rojo—. Cuatro migraciones aplicadas (`q7j8k9l0m1n2`, `r8k9l0m1n2o3`, `s9l0m1n2o3p4`, `t0m1n2o3p4q5`), todas con `downgrade` comprobado. **Tres fallos preexistentes encontrados por el camino y arreglados**: `_relevar_default` ignoraba el propósito, cualquier administrador podía archivar la plantilla de plataforma de todos, y `hub_workspaces.organizacion_id` estaba en la migración pero no en el modelo.
| **Bloque SEC.9** — Endurecimiento pre-deploy, tercera auditoría | SEC.9.7 ✅ | — | — | ✅ **Completo (2026-08-24)** — los 7 prompts. **Suite backend completa: 3056 passed, 1 skipped, 0 fallos** (24:34, `-n0` desde Git Bash); **frontend: 626 passed, 0 fallos**; `tsc --noEmit` limpio; contrato regenerado (148 rutas); una migración aplicada (`u1n2o3p4q5r6`) con `downgrade` comprobado. El gate «Access control gate» de `ci.yml` pasa de 4 ficheros a 9 y de ~40 a **133 tests que bloquean el despliegue**. **SEC.9.7 hecho** (MT.16 adelantado de la fase 2 de MT): dos organizaciones reales sobre BD real, cada una con su modelo, su asistente, su sitio y su override de prompt, y un recorrido por HTTP comprobando que el administrador de una recibe 403 o listado vacío en todo lo de la otra, que el superadministrador ve las dos —permiso correcto, y se fija para que nadie lo «arregle» convirtiéndolo en 403— y que la credencial del widget de una no alcanza a la otra. Se adelanta porque **el piloto arranca con una sola organización**, así que sin este test el aislamiento no se ejercita en producción; y es el único del bloque que puede fallar por una razón que los demás no ven, porque comprueba los endpoints **juntos, sobre las mismas filas, con credenciales distintas**. **Tres cosas que enseñó montarlo**: `db_session` vive bajo `tests/modules/agents_hub/`, no en `tests/api/`; `TestClient` es síncrono y su portal de anyio choca con el bucle de la sesión async —`got Future attached to a different loop`, que no se parece a su causa—, así que va con `httpx.ASGITransport`; y el catálogo de proveedores **se comparte a propósito** entre las dos (MT.2: Google es Google en todos los municipios; lo que se separa es la credencial), así que compartirlo no es una fuga. **Y la suite completa destapó un choque real que los tests por fichero no veían**: la restricción de `create_organizacion` a superadministrador que había puesto SEC.9.6 contradecía una decisión deliberada de PLAT.5 —el módulo `plataforma` habilita gestionar organizaciones—. Al investigarlo apareció algo mejor que cualquiera de las dos posturas: **`partner_id` sí tiene efecto de autorización** (`_orgs_del_admin` resuelve el claim con `WHERE partner_id == <su partner>`, así que aceptarlo del cuerpo dejaba plantar una organización en el ámbito de otro administrador, y le aparecería como suya en el siguiente inicio de sesión) **y no hace falta inventar ningún claim para arreglarlo**: el partner de un administrador *es* su `user_id`, tal y como lo emite `login_admin`. Así que se deriva del token, el administrador conserva la capacidad que PLAT.5 le dio, y el agujero se cierra. **SEC.9.6 hecho**: los cinco medios, y lo que tienen en común merece nombrarse — **no eran controles ausentes, eran controles presentes que no llegaban a ejecutarse**, que es peor, porque el código lee como si estuviera cubierto. La subida de `llm-drafts/sample` pasa por `read_within_limit` (era el único `UploadFile` fuera de SEC.6/SEC.8.2: que no se persista no impide agotar la memoria mientras se resume). `anon_ip_daily_token_quota` deja de ser código muerto —su único llamador nunca pasaba `ip=`— y, sobre todo, **el widget deja de compartir un cubo de peticiones entre todos sus visitantes anónimos**: el actor es `widget:{chatbot_id}`, el mismo para todos, así que uno solo dejaba el asistente público sin servicio para el resto; pasando `actor_id=None` el limitador cae a la IP, que es su comportamiento para el tráfico sin identidad. El gate de producción del sandbox **también mira `TESTING`**, porque `sandbox_client` elige el ejecutor local con `TESTING=1` sea cual sea `SANDBOX_MODE`: el escenario que el gate dice evitar se alcanzaba por otra puerta. Y el subproceso del sandbox local recibe un entorno **por lista blanca**, no heredado —una lista negra hay que ampliarla cada vez que aparece un secreto nuevo y nadie se acuerda—, con un «hogar» temporal que además aísla mejor que heredar `USERPROFILE`. `hub_agents_router` **usa el `workspace_id` de la ruta**: hacía `where(user_id == ...).limit(1)`, o sea exportaba una interacción cualquiera presentada como el workspace pedido —el DOCX no era el documento que se pidió y nada lo delataba—, y ahora además pasa por `assert_chatbot_org_access`. `workspaces_router` gana el `require_module("informes")` que era el único de `redaccion/` sin él. Crear una organización pasa a superadministrador: `partner_id` viene del cuerpo y **no se puede derivar del actor** porque ROL.1 retiró esa dimensión del principal, así que la respuesta no es inventarle un claim sino que el alta sea un acto de la plataforma (el criterio de MT.13). Y el compose de producción se queda **sin un solo `:-` en un secreto**: usa `:?` y se detiene. **Un hallazgo del propio arreglo**: el entorno mínimo rompió los gráficos —matplotlib no se importa sin sitio donde escribir su configuración—, lo que confirma que heredar `os.environ` estaba tapando una dependencia que nadie había declarado. **Cierre: 1222 passed, 1 skipped, 0 fallos** (`tests/api` + `tests/core` + `tests/modules/redaccion` + higiene + `tests/unit`). **SEC.9.5 hecho, y es el prompt que impide la próxima regresión de esta clase**: el inventario de routers **se recorre** (`rglob` sobre `app/routers` + `app/api/v1`) en vez de enumerarse, siguiendo el patrón de `tablas_sin_ambito()` de MT.1. La diferencia de fondo: olvidarse de añadir a una lista de **exenciones** falla del lado seguro; olvidarse de añadir a una lista de **vigilados**, no. Cuatro comprobaciones nuevas: ningún router sin registrar en `main.py` (superficie muerta), ningún router sin señal de acotado salvo exención **con su razón escrita**, ninguna exención que ya no corresponda a un fichero, y —el meta-fix— **un docstring que declara módulo tiene que exigirlo con `require_module`**, que es exactamente lo que dejó a `library_router` pasando el check de PLAT.5 en verde estando abierto. **Tres hallazgos del propio test**: `hub_prompts_catalog_router` (REV.13) declaraba `plataforma` sin exigirlo —arreglado, su pantalla ya pide el módulo desde SEC.9.3—; `hub_test_scenarios_router` comprueba rol y pertenencia pero no módulo; y **el guardarraíl de SEC.2 vigilaba un fichero que no existe** (`hub_feedback_router.py`, que vive en `api/v1/hub_feedback.py`): el `continue` lo saltaba en silencio, así que llevaba desde SEC.2 pareciendo cubierto. Los desajustes heredados quedan en un **trinquete** de 7 entradas que sólo puede encoger, visible en el código y no implícito, porque añadirles la guarda puede dejar fuera a un administrador sin la concesión y eso es decisión de despliegue (PLAT/MT fase 2), no de este bloque. El paso «Access control gate» de `ci.yml` pasa de 4 ficheros a 8: **123 tests bloquean el despliegue**. **SEC.9.4 hecho** (decisión del usuario del 2026-08-24: **restringir el método, no cifrar**): el método `clave` —la clave literal en texto plano— se retira **con su columna**, así que no queda dónde guardar un secreto. Volcados, copias, réplicas y el payload de la sincronización cloud→edge dejan de ser sensibles **por construcción**, en vez de por acordarse de cifrarlos. Cifrar queda descartado por escrito y con su razón: mueve el secreto al entorno del mismo proceso que lo descifra —o sea donde ya estaba con los otros dos métodos— y añade gestión de clave para siempre (rotar obliga a recifrar, perderla es perder todas las credenciales, la copia sólo se restaura con ella, el edge la necesita, y aparece un fallo nuevo que se ve como una caída). El autoservicio del panel que esto cuesta **se recupera en MT.10** con un `SecretProvider` que guarda el nombre del recurso. La migración `u1n2o3p4q5r6` **no borra a ciegas**: cuenta las filas con `metodo='clave'` y se detiene con instrucciones si hay alguna, porque esta migración no guarda copia del valor en ningún sitio —y guardarla «por si acaso» sería dejar el secreto en la base con otro nombre—. Aplicada, `downgrade` comprobado. El fallo de configuración ahora dice **qué** variable falta y **de quién** es la credencial: con una variable por organización, «no está definida» a secas no se puede arreglar sin ir a mirar la tabla. 4 tests nuevos; 45 en verde en los ficheros afectados y 150 con `tests/core` incluido (el inventario de MT.7 sigue honesto). `docs/MULTITENENCIA.md` actualizado. **Queda anotado y NO se toca aquí**: `hub_providers.api_key`, la otra columna de secreto en claro, que **sí tiene datos** y cuya retirada cambia la cadena de `model_factory` y el formulario del proveedor. **SEC.9.3 hecho**: MT.6 dejó el lector de prompts de actividad bien y el escritor mal —`_fila()` buscaba `WHERE activity == ...` y se quedaba con la primera—, así que cualquier administrador podía leer, sobrescribir o borrar el prompt de plataforma que heredan todas; y como ese texto va al LLM, no era configuración ajena sino **inyección de prompt en las llamadas de las demás**. Ahora hay dos búsquedas y la diferencia es el prompt entero: `_fila` hereda (para leer) y `_fila_propia` no (para escribir), porque **escribir no se hereda**. La organización se nombra como en REV.12: viaja del selector de la cabecera y se comprueba con `assert_org_access`; sin nombrarla, la del actor si gestiona una sola, y 400 si varias. `require_module("plataforma")` al router, que el docstring declaraba sin que nada lo hiciera cumplir. **Y MT.6 pasa a ser alcanzable**: antes no había forma por API de crear un override *de organización*, porque el escritor nunca ponía la columna. **Un test contra BD real destapó un defecto de estilo con consecuencias**: `= Query(default=None)` deja el objeto `Query` como valor por omisión en Python, así que llamar al endpoint como función —lo que hacen esos tests— se lo pasaba a asyncpg y reventaba con «'Query' object has no attribute 'bytes'»; con `Annotated` el default es `None` de verdad. 10 tests nuevos, 45 en verde en los ficheros afectados, contrato regenerado, `tsc` limpio, 6 tests de la pantalla. **Lección de método**: la pasada amplia de cierre se lanzó en segundo plano *mientras* se editaba el prompt siguiente y dio 7 rojos que no existían —leyó los ficheros a medio cambiar—. No se solapa una suite larga con ediciones. **SEC.9.2 hecho**: la clave del proveedor sale del contrato (`HubProviderOut` la declaraba, y siendo `hub_providers` de plataforma cualquier administrador de cualquier organización la leía en claro con un `GET`); las escrituras de proveedor suben a superadministrador, porque crear, cambiar o borrar uno afecta a todas; y MT.2 gana la tenencia que le faltaba en los cinco endpoints de configuración. **Dos decisiones que el patrón obligaba**: el listado usa `or_(IN mis orgs, IS NULL)` y no `scope_query_to_orgs`, porque la tabla es **heredable** y acotar a secas escondería el nivel de plataforma —el único que existe hoy— dejando la pantalla vacía; y un administrador que no nombra organización **escribe en la suya**, con 400 si gestiona varias, en vez de caer a plataforma, que convertiría un despiste en un cambio para todo el mundo. En el frontend, el formulario del proveedor ya no precarga la clave y **omitir el campo significa «no la cambies»**: sin eso, editar el nombre de un proveedor le borraba la credencial y el fallo aparecía en la siguiente llamada al modelo, no al guardar. Contrato regenerado (148 rutas), `tsc` limpio, 4 tests de la pantalla en verde. 12 tests nuevos; **cierre: 1084 passed, 0 fallos** (`tests/api` + `tests/modules/agents_hub/unit` + `tests/infra` + export del contrato). Los 5 tests del router que operaban sobre plataforma con un admin sin organizaciones pasan a superadministrador, que es de quien es ese nivel. **SEC.9.1 hecho**: `library_router` exige identidad y la saca del token. La guarda va en el `APIRouter` (`require_module("plataforma")`) y no en el docstring —el inventario de PLAT.5 se validaba leyendo docstrings, y este fichero declaraba su módulo estando abierto de par en par—; `/push` y `/sign_manifest` suben a superadministrador, porque firmar con la clave de la plataforma es un acto de la plataforma. **Desviación documentada**: `sign_manifest` conserva `partner_id` en el cuerpo (es el destinatario, no quien firma; derivarlo del actor exigiría una dimensión de *partner* que ROL.1 retiró del principal). **Y la compartición por partner + `access_groups` desaparece**, no se arregla: sus dos entradas venían de las cabeceras `X-Partner-Id`/`X-Client-Groups`, o sea que «pertenezco al grupo Premium» lo decidía quien pedía el fichero. Es un estrechamiento a propósito —nadie ve menos de lo suyo— y compartir configuración entre organizaciones es lo que diseñan MT.17–MT.21. De paso, un manifiesto sin `id` pasa de 500 a 400 y el `str(e)` interno deja de viajar al cliente. 10 tests nuevos; `tests/api` + `tests/unit` + higiene + PLAT.5 en verde (415 passed tras arreglar los 3 de `test_prompt2_db_api.py` que usaban la firma antigua del servicio) ⏳ Planificado el 2026-08-24. **BLOQUEANTE DE DESPLIEGUE, va ANTES de D.0.** Nace de `docs/VALORACION_PROYECTO.md` (auditoría del 2026-08-24). Los diez hallazgos de julio están resueltos; estos son regresiones de los bloques REV y MT, y **tres de las cuatro auditorías los encontraron por separado**. 7 prompts: SEC.9.1 (`library_router` sin auth + oráculo de firma RSA, **CRÍTICO**, Opus), SEC.9.2 (`api_key` del proveedor en claro + `hub_llm_configs` sin tenencia, Opus), SEC.9.3 (`hub_activity_prompts` sin filtro de organización, MT.6 a medias, Opus), SEC.9.4 (credencial literal sin cifrar en reposo, Sonnet — **decisión tomada el 2026-08-24: restringir el método**, la BD guarda un puntero y nunca un secreto; cifrar se descarta porque mueve el secreto al entorno del mismo proceso y añade gestión de clave permanente sin ahorrar la abstracción posterior; el autoservicio del panel se recupera con el `SecretProvider` de MT.10), SEC.9.5 (**el gate de aislamiento recorre el árbol de routers en vez de una lista fija** —el meta-fix que evita la próxima regresión—, Opus), SEC.9.6 (los NUEVO-5..9: upload sin límite, cuota anónima muerta, gate del sandbox con `TESTING`, endpoints con guarda incompleta, contraseñas por defecto en el compose de producción, Sonnet), SEC.9.7 (**MT.16 adelantado**: aislamiento de punta a punta con dos organizaciones, Opus). Detalle en `Plan_TDD_Fase1.md` §Bloque SEC.9 |
| **Bloque AIS** — Aislamiento del núcleo y saneamiento previo al piloto | AIS.8 ✅ | — | — | ✅ **Completo (2026-08-25)** — los 8 prompts. **Suite backend completa: 3107 passed, 1 skipped, 0 fallos** (25:03, `-n0`); **frontend: 653 passed** sobre 250 ficheros; `tsc` limpio; contrato regenerado (149 rutas); una migración aplicada (`v2o3p4q5r6s7`) con `downgrade` comprobado. **AIS.8 hecho**: el arranque configura el logging —no había ninguno, el único `basicConfig` vivía dentro de un script de reingesta y el servidor hablaba por `print`—, `to_pdf` deja de bloquear el bucle de eventos hasta 30 s con LibreOffice, el DSN de reserva **falla en producción** (en local se conserva, porque sin él no se arranca ni corre la suite) y deja de estar escrito en dos sitios, y entra el guardarraíl del extra `local-models` que salió de la falsa alarma del `uv.lock`. **La suite encontró un fallo de mi propio arreglo**: `basicConfig(force=True)` **elimina** los manejadores existentes, incluido el que pytest instala para capturar registros, y puso en rojo dos tests —uno de ellos el que afirma que un arranque fallido deja su causa en el log, justo lo que el prompt venía a mejorar—. Un mecanismo de observabilidad que apaga a otro no es observabilidad: ahora se fija el nivel y el formato **sin destruir** lo que haya. **AIS.7 hecho**: plantilla de PR cuya primera pregunta es «¿por qué esto es generalizable?» —la pregunta de la gobernanza, que hasta ahora dependía de que el contribuyente hubiera leído el manual—, `SECURITY.md` con plazos de **respuesta** y no de resolución, `CODEOWNERS` sobre el núcleo, la frontera, las migraciones y los guardarraíles, y plantillas de issue que preguntan por el fork y el modo de despliegue. **AIS.6 hecho**: el §13 de la AGPL, con sus tres condiciones — va en la interfaz, sale de `SOURCE_URL` (un test prohíbe URLs escritas a mano, porque una fija al principal haría incumplir a todo fork) y **se ve también en el widget público**, que es el caso que el README llama «el que se olvida». **AIS.5 hecho** (decisión del usuario): la anonimización es política de la **organización** y el informe sólo la endurece; sin bóveda cifrada, que sigue siendo F2.A.4. Dos cosas que la auditoría daba por pendientes ya estaban: el modo ya era política (cuatro valores desde Fase 13) y la evidencia del tratamiento también (el `RunManifest` guarda conteos sin valores). **Y un error de diseño mío que cazó un test existente**: `MODO_POR_DEFECTO` como suelo habría hecho la anonimización obligatoria con otro nombre —nadie podría elegir `off` en una instalación nueva—, así que suelo lo es sólo la política fijada a propósito. **AIS.4 hecho**: el panel de auditoría NER **no ha funcionado nunca desde el navegador**. `useAnonymizationApi.ts` era un módulo escrito a mano cuyo `fetch` no mandaba credencial, y sus tres endpoints exigen sesión y módulo: 401 los tres. Lo que importa es **por qué siguió invisible**: el cliente correcto ya estaba generado y el panel importaba el manual; el test del panel mockeaba ese módulo, así que la capa de red no se ejercitaba; y el guardarraíl de CAL.2 lista módulos manuales **por nombre** —éste no estaba, porque se escribió después— y comprueba la credencial buscando ficheros que *mencionen* la cabecera, así que éste pasaba **precisamente por no construirla**. Arreglado el panel (hooks generados, invalidación con la clave que construye el propio cliente) y **reforzado el guardarraíl**: ahora **descubre** recorriendo el árbol en vez de enumerar, con las exenciones declaradas (widget por SSE, login por ser previo a la credencial). Es el mismo movimiento que SEC.9.5 hizo con los routers. Frontend completo: **653 passed, 0 fallos** sobre 250 ficheros; `tsc` limpio. **AIS.3 hecho**: `core/` deja de importar de `routers/` —eran dos, `normalizar_correo` y `user_to_uuid`, o sea la autenticación dependiendo de la capa HTTP de un módulo—, y las dos se van a `core/identidad.py`, que es su sitio porque son **decisiones de identidad**: si las dos formas de normalizar se separan, dos filas que son la misma persona dejan de serlo. El único cruce módulo→módulo sin justificación (`curation` tirando de una función **privada** de Informes) se resuelve moviendo la utilidad a `core/llm_json.py`: no era que curación necesitara algo de Informes, era que la utilidad estaba en el sitio equivocado. Test de dirección con **tres severidades distintas a propósito**: `core→routers` prohibido sin excepciones (y en cero), `core→modules` congelado en una lista que **sólo puede encoger** —lo que queda son modelos ORM, que viven en el módulo que los posee—, y módulo→módulo según lista declarada, donde **`agents_hub` se declara como la capa base que de facto es** en vez de fingir que la regla se cumple con 24 imports diciendo lo contrario. El propio test podó una entrada que sobraba al estrenarse. **`modules/automation` no se borra, se deja probado**: 1.401 líneas sin un solo importador vivo (los `.pyc` que aparecían eran de ficheros que ROL.1 borró), y su retirada va al Bloque NIC, cuyo primer prompt **no borra nada sino que cruza qué está cubierto** — borrar 1.400 líneas a ojo a mitad de un bloque de aislamiento es como se pierde una funcionalidad sin enterarse. Cierre AIS.3: **1391 passed, 1 skipped, 0 fallos**. **AIS.2 hecho, y el barrido dio mucho menos de lo que decía la auditoría**: en **código** de producción sólo había **tres** sitios que nombraran una institución (`DEV_ADMIN_EMAIL`, el conjunto de tipos de fuente y una entrada de selectores). Todo lo demás de la lista eran **comentarios y docstrings de procedencia** —de qué portal salió un selector, qué acrónimos manda un IdP—, que son documentación verificable y no viajan como comportamiento; el test lo distingue explícitamente para no obligar a borrar la explicación de un dato real. Lo arreglado: `DEV_ADMIN_EMAIL` por entorno con valor neutro —todo fork que arrancara en local creaba un superadministrador **con el correo del mantenedor del principal**—; el prompt de sistema de Informes deja de presumir «una universidad pública» y dice «una administración pública», que cubre a las dos y es lo que pide el destinatario declarado (entidades locales); y la entrada de tipo de fuente con nombre de institución sale, porque sus tres selectores eran un **duplicado exacto** de los de `boe` —no añadía un marcado, añadía un alias—. **Y los dos prompts de redacción de SEG.2 entran en el catálogo de actividades**, que era la mitad sustantiva: eran los únicos del módulo que no se podían afinar sin desplegar, y `RedactorDeBloques` los resolvía con un `dict` del módulo, así que el mecanismo de MT.6 existía y a ellos no llegaba. Ahora se resuelven en `workspaces_router` —el único punto del camino con sesión y organización a la vez— y se entregan ya hechos, para que `generate()` siga sin tocar la base de datos: corre dentro de un nodo del grafo. Dos docstrings que mentían, corregidos: `seeds.py` decía que el login de administrador no verifica contraseña (SEC.1 lo arregló hace bloques) y `main.py` anunciaba como «pendientes de registrar» dos routers **borrados** en ROL.1 — es lo primero que lee quien abre el punto de entrada. **Pendiente anotado, más grande que este prompt**: los selectores de spider deberían ser **dato del sitio** (`hub_web_sites`), como ya lo son los criterios de curación desde CUR.2.1; mientras vivan en código, un portal con otro marcado obliga a tocar el principal. Cierre: **1293 passed, 1 skipped** en `tests/infra` + `redaccion` + `curation` + `unit` (el único rojo era `VARIABLES_POR_ACTIVIDAD` sin las dos entradas nuevas, y su test es justamente el que exige que toda actividad declare sus variables). Contrato regenerado, `tsc` limpio. **AIS.1 hecho, y con una desviación grande respecto a lo planificado: la mitad del prompt ya estaba hecha.** La auditoría decía que la cascada de temas no alcanza el cromo del panel —`injectThemeCSS` escribe `--color-*` y las utilidades resuelven contra `--*`—, y eso era cierto **hasta REV.9**, un día antes: `aplicarColoresDelPanel` escribe los `--*` de la capa shadcn como **estilo en línea** sobre `:root`, que gana a cualquier hoja de estilos incluido `.dark`. **Verificado en el navegador**: el atributo `style` de `<html>` traía `--primary: #0b5394; --sidebar-accent: #0b5394` puestos por la cascada. Los dos sistemas ya estaban puenteados y `index.css` es a propósito el valor de reserva. **Lo que sí quedaba, y es peor de lo que decía la auditoría**: el bloque `.dark` estaba rotulado literalmente `UJI brand` con el turquesa (hue 211) y el azul marino (hue 244) de esa institución, mientras UX.5 había pasado el bloque claro al azul del proyecto (`#0b5394`, hue ~255) — así que **cambiar a modo oscuro no oscurecía la identidad, la sustituía por otra**. Eso no es una etiqueta de más, es un defecto. Ahora la marca se declara una vez (`--marca`) y el modo oscuro **deriva de ella** con `color-mix`, así que los dos modos son la misma marca por construcción y no porque alguien mantenga dos listas. **Restricción que decidió el diseño**: REV.9 ata los literales de `:root` al contrato del servidor con `test_rev9_la_paleta_es_una.py`, que los compara **como texto**, así que poner `var(--marca)` en el bloque claro dejaría ese test comparando una función CSS contra un hexadecimal; el claro se queda literal y un test nuevo vigila que los dos no se separen. Guardarraíl `paletaDelPanelNoEsDeNadie.test.ts`, hermano de `marcaNoViajaEnElRepo`: prohíbe nombrar una institución en la hoja de estilos —**comentarios incluidos**, al contrario que su hermano, porque este fichero se compila en el bundle de todos los despliegues—, exige que el oscuro derive de la marca y que ningún token esté declarado en un solo modo. **Verificado en navegador con medición y no a ojo**: `color-mix` resuelve, y los contrastes leídos por píxel pasan AA en los dos modos (claro 7.84 / 6.88 / 6.81 / 5.15; oscuro 6.71 / 12.84 / 9.95 / 10.89), consola limpia en las dos pantallas. Los 38 tests de temas del servidor y `tsc` intactos. **Hallazgo nuevo que NO se arregla aquí**: la cascada es **ciega al modo** —escribe un solo valor para `--primary` y se aplica igual en claro que en oscuro, así que el azul de una organización pensado para fondo claro se pinta sobre fondo oscuro—. Arreglarlo bien exige que el claro también derive de la semilla, y eso pasa por enseñar al test de REV.9 a resolver un salto de `var()`: es prompt propio ⏳ Planificado el 2026-08-24. **Va DESPUÉS de SEC.9 y ANTES de D.0.** Calidad y aislamiento núcleo/configuración de `docs/VALORACION_PROYECTO.md` §2 y §5. No bloquea por seguridad, pero AIS.1 **bloquea de facto** el modelo de gobernanza (otra administración no puede usar el principal tal cual). 8 prompts: AIS.1 (la paleta del panel a la cascada de temas, **bloqueante OSS**, Opus), AIS.2 (material de fork fuera del principal: `DEV_ADMIN_EMAIL` por entorno, prompts institucionales al catálogo, selectores de spider a dato, Sonnet), AIS.3 (el núcleo no importa de módulos ni routers + decisión sobre `modules/automation`, Opus), AIS.4 (bug del 401 en el panel de anonimización, Sonnet), AIS.5 (anonimización: **decisión del usuario del 2026-08-24** — el piloto no trata datos de ciudadanos y la anonimización es **configurable, no obligatoria**, así que **no hay bóveda cifrada antes del piloto**; y al planificar resultó que el modo **ya es política** (`AnonymizationMode` con cuatro valores, columna por informe), de modo que el prompt pasa a ser: modo **heredable desde la organización** —el contrato con el proveedor LLM es de la organización, no del informe, y el informe solo restringe, nunca amplía—, acotar la promesa de `REPLACE` a la reversión **dentro** de la ejecución, y **evidencia del tratamiento sin guardar el mapa** (tipo y conteo, nunca valores). La persistencia cifrada sigue siendo F2.A.4, post-piloto. Opus), AIS.6 (§13 AGPL: `SOURCE_URL` en panel y widget, Sonnet), AIS.7 (infraestructura de contribución: `SECURITY.md`, `PULL_REQUEST_TEMPLATE.md`, `CODEOWNERS`, Sonnet), AIS.8 (higiene: logging estructurado, `to_thread`, `DATABASE_URL` que falle, Sonnet). **Post-piloto anotado en el bloque**: code-splitting, descomponer `ChatbotsPage.tsx`, retirada de `client_app/` (NIC), MT fase 2. Detalle en `Plan_TDD_Fase1.md` §Bloque AIS |
| Deploy GCP | **D.0.doc**, **D.0**, **D.2**, **D.3**, **D.4-VM**, **D.5-VM**, **D.6.1**, **D.7** ✅, **D.6-VM** ✅ (alerta probada) (2026-08-31) | **pruebas manuales + receptor Docker del ops-agent + RAG.6b** | Sonnet | ✅ **BLOQUE DEPLOY COMPLETO el 2026-08-31, y sirviendo**. **Alerta probada por CLI**: 13 min de parada, 38 puntos `false` desde seis regiones y recuperación a las 18:09:44 — y al probarla se descubrió que **la comprobación de salud nunca se había creado** (el POST fallaba y el guion imprimía «[creada]» descartando la respuesta), así que la alerta de caída llevaba dos horas inerte. Arreglado en tres capas. **D.6.1 a medias a propósito**: las 313 páginas, los PDF y las imágenes están subidas a `gs://govgenai-normativa-uji` con `Cache-Control` y subida idempotente, pero **el bucket sigue privado** porque abrirlo es hacia fuera y hay 219 defectos del corpus pendientes de Secretaría General. Incrustar el widget necesita chatbot y credencial en producción: es D.7. `https://34-175-38-129.sslip.io/health` responde 200 con certificado válido, la etiqueta desplegada coincide con el commit, las migraciones se aplicaron contra Cloud SQL, el reinicio de la máquina devuelve el servicio solo en 50 s (relojes verificados) y la vuelta atrás está probada. **D.6-VM queda en ▶ por una sola cosa**: nadie ha visto disparar una alerta — hay que apagar el servicio y comprobar que el correo llega, y eso no lo puede firmar un agente. Del cierre de D.4-VM falta también «un rastreo termina y deja páginas»: la base de producción está vacía a propósito y eso es **D.7**. **Nueve fallos reales en ocho intentos, ninguno del código de la aplicación** (ver historial): dos eran míos —una guarda que no comprobaba y una comprobación que medía el frontend creyendo medir la API—, y uno no daba síntoma: editar `startup.sh` no cambia la máquina, así que el agente de operaciones y la rotación de logs **nunca se instalaron y las alertas eran inertes**. Lo que queda del bloque —D.2, D.3, D.4-VM, D.5-VM, D.6-VM, D.6.1, D.7— **no tiene ni un prompt ejecutable sin la nube**: D.1 lo cerró SEC.8.5 y **D.4.0 ya se ejecutó el 2026-08-11** (`c92dc47`, 627→345 MB de RSS, `e2-small` holgado). **D.0 cerrado y EJECUTADO contra `uji-teclab`**: `scripts/gcp_enable_services.sh` con 10 tests verdes, los **14 servicios habilitados y comprobados** uno a uno por el propio script, y la idempotencia verificada contra la nube de verdad (segunda ejecución, exit 0). Hizo falta un `gcloud auth login` interactivo en medio, que es la única parte del prompt que no puede hacer un agente. La lista se cruzó contra el código: `run.googleapis.com` fuera, `compute`/`oslogin`/`iap` dentro, y `iamcredentials`+`sts` que la lista del plan no tenía y Workload Identity de D.5-VM necesita. D.0.doc cerrado: las nueve menciones de Cloud Run clasificadas —cuatro razonaban sobre el destino actual— y la **capa 8 del sandbox resuelta en un sentido**: gVisor se queda, pero como configuración de la VM (`runtime: runsc`, plataforma `systrap`) con el comando que la comprueba, y la tarea de instalarlo pasa a D.4-VM. Dos guardarraíles nuevos en `tests/infra`. Nota histórica: **ya no es lo siguiente**: el 2026-08-22 el usuario lo movió DETRÁS de PLAT e IDE —«no tiene sentido hacer el deploy de una aplicación con una estructura y unos mecanismos de identificación que no son los que se van a utilizar»—. **Tarea nueva heredada de IDE.1**: el inventario de variables de entorno tiene que incluir el ajuste de la autoridad del rol. **D.4.0 añadido el 2026-08-11**: `torch`, `transformers` y `sentence-transformers` pasan a un extra de instalación `[local-models]`, con importación perezosa y un error que diga cómo instalarlo. Están solo por `LocalEmbeddingService` y `LocalReranker`, así que con embeddings de Vertex no se usan pero se pagan enteros (216+172 MB y casi todo el arranque, medido en EXT.3). **Va antes de D.4-VM**: cambia el tamaño de la máquina de ~2 GB a ~150-250 MB esperados, y ese es el número que D.4 fija. No retira capacidad: el modo edge instala el extra. **BLOQUE REESCRITO EL 2026-08-10: el destino es una VM, no Cloud Run** (`docs/DECISION_EXTRACCION_Y_DESPLIEGUE.md` §2). El planificador de calidad es un APScheduler del `lifespan` y el rastreo va por `BackgroundTasks`: con escalado a cero el primero no dispara y el segundo muere a media ejecución, y el descuento que justificaba Cloud Run no era cobrable porque el scheduler exige CPU continua igual. VM + `docker-compose.prod.yml`, con **Cloud SQL y GCS** conservados —el estado sigue gestionado—. **D.1 ya está hecho**: lo resolvió SEC.8.5 con `HubWidgetKey`, que es superconjunto de la API key que D.1 describía (hash, revocable, solo abre `public_anon`). **D.4 y D.5 reescritos** (una máquina en vez de tres servicios Cloud Run: `embedding-service` y `docling-service` desaparecen por MOD.2 y EXT.3) y **D.6 nuevo** (copias con restauración probada, vigilancia, y la guía de incrustación del widget que D.1 dejó suelta). **Desaparece como problema** el ejecutor de trabajos que SEC.8.8 aplazó: en una VM el proceso vive |
| **RAG.6b** — Adaptador de Vertex para el reranker + medición del valenciano | RAG.6b ✅ (2026-08-24) | — | — | ✅ **Completo (2026-08-24)**, adelantado a petición del usuario y medido contra el servicio real con el proyecto `uji-teclab`. **El hallazgo que justificaba el prompt entero**: los scores del Ranking API **ya vienen en [0,1], no son logits** —medidos 0,7944 / 0,0504 / 0,01 sobre tres candidatos en valenciano—, así que pasarlos por la sigmoide de `normalize_score`, que es la correcta para el cross-encoder local, los habría aplastado hacia 0,5 y destruido la separación que hace útil al reranker: un 0,01 se convertiría en 0,502 y el packer de RAG.5 y el quality gate decidirían sobre números sin rango. El contrato escrito **no** coincidía con el real, que era el riesgo que el prompt nombraba. Fijado en `tests/modules/agents_hub/integration/test_reranker_vertex.py`, donde cada test dice qué comportamiento observado protege. **Decisión tomada con el dato**: el reranker queda **apagado en el asistente normativo**, porque en ese corpus restaba; HIB.J corrigió además el efecto de segundo orden que sólo se vio al mirarlo —sin reranker la nota del gate era una constante, así que el umbral no medía nada—. **Esta fila decía «⏳ Pendiente» hasta el 2026-09-26** mientras otra línea de este mismo fichero decía «✅ HECHO el 2026-08-24»: de ahí salió la issue #10, abierta un mes sobre trabajo entregado. Contexto original de la decisión de orden (2026-08-01): El Ranking API vive en Discovery Engine y lo habilita **D.0**, así que este prompt no puede cerrarse antes. Comprueba que el contrato escrito coincide con el real —un adaptador probado solo contra un doble está verificado en su lógica, no en su integración— y decide con el gate de RAG.1 sobre el dorado en valenciano si el flag se enciende en algún sitio. **No depende del corpus v1**: el dorado ya está en valenciano y el corpus de fixture son 25 normas breves. Modelo cerrado: `semantic-ranker-default-004` (1.024 tokens; las variantes de 512 truncarían la mitad de cada chunk). Riesgo abierto: Google declara 25 idiomas y no publica cuáles; el catalán no aparece |
| **Bloque FAQ** — Preguntas frecuentes como contenido citable | FAQ.2 ✅ | — | — | ✅ **Completo (2026-08-11)** — FAQ.1 (`1dd4910`) formato y validación, FAQ.2 autoridad de la cita. **Suite backend: 1819 passed, 3 skipped, 0 failed.** Dos hallazgos del RED: el troceador **ya** hacía lo correcto con encabezados y anclas (no hubo que tocarlo), y el "regalo gratis" de sembrar el dorado desde la FAQ **no era gratis** — la entrada resultaría circular, porque el documento que contiene la frase la recupera siempre; queda descartado y explicado en el plan. `content_class` viaja ahora del documento al fragmento y de ahí a la evidencia, con el aviso **dentro** del texto que ve el modelo  **Cuando se planificó: añadido el 2026-08-11**. Se ingieren como documentos con `content_class: faq` —valor que el contrato ya admite—, no como ejemplos en el prompt (no escala, e invita a parafrasear una respuesta redactada con cuidado) ni como dataset dorado (eso mide recuperación, es artefacto de prueba). La razón de fondo: **el texto de la pregunta es un objetivo de embedding casi perfecto**, porque se parece a lo que el ciudadano escribe mucho más que el artículo que la fundamenta. FAQ.1 fija el formato —**un encabezado por pregunta**, con ancla `{#faq-N}`, para que pregunta y respuesta caigan en el mismo fragmento; con negritas o listas, un corte deja media pregunta con la respuesta de otra y eso se cita mal sin que se note—. FAQ.2 cierra el riesgo real: **una respuesta sugerida no es una norma**, y tiene que citarse como orientativa con enlace a la norma que la sostiene. De regalo, el mismo fichero siembra el dorado y alimenta el detector de huecos |
| **Bloque RHR** — Revisión humana de las respuestas del asistente interno | RHR.1 ✅ (entregado por REV.1 el 2026-08-23; **verificado en navegador el 2026-09-18**) | RHR.2 (CONDICIONAL, no ejecutar) | Opus (sólo si se dispara RHR.2) | ✅ **Completo en lo ejecutable (2026-09-18)** — **desviación documentada: RHR.1 no lo escribió este bloque, lo entregó REV.1** y HIB.H lo amplió; la fila se quedó sin actualizar cinco semanas. Al arrancar el bloque se comprobó pieza por pieza contra el prompt y estaba todo: modelo con los mismos valores que `HubTestRun`, `PATCH .../interactions/{id}/review` con nota obligatoria en «mal», guarda de tenencia SEC.8.1, `GET` con `review_status` en `pending` por defecto, pantalla en `/hub/revision` con contador y CSV, i18n en tres idiomas y **los siete tests con sus nombres literales**. La verificación en navegador destapó un defecto de usabilidad y se arregló con TDD: «Inadecuada» sin nota era un `return` silencioso —no mandaba nada, correcto, y **no lo decía**—; ahora el botón está deshabilitado con el motivo a la vista y en el `title`. **RHR.2 sigue condicional**: hilos persistentes, sólo si el piloto muestra que los funcionarios piden retomar una conversación; su pregunta decisiva es para Gerencia, y si la respuesta es «espacio de trabajo conversacional» hay que reconsiderar OWUI. Contexto original: Gerencia quiere un asistente para funcionarios **con identificación** y poder **revisar las respuestas** para valorar si son adecuadas o si conviene reformular las FAQ. Se evaluó OWUI para esto y se descartó: es una interfaz de chat y **no aporta la revisión**, que es lo que se pide. **Casi todo existe ya**: el asistente restringido es configuración (`access_mode: restricted` + `allowed_saml_groups` de SEC.2.1 sobre el SSO de AUTH), cada turno queda en `HubInteraction`, la pantalla de revisión con CSV es `ReportsPage` sobre `/hub/feedback/{id}/review`, y el bucle al contenido lo hace el detector de huecos de RAG.14. **RHR.1** añade lo que falta: el veredicto de quien revisa sobre conversaciones **reales** (hoy `feedback_score` es del usuario final), replicando el patrón `verdict`/`verdict_note`/`verdict_by` que RAG.13 ya usa en escenarios de prueba, con cola de pendientes y nota obligatoria cuando el veredicto es «mal». **REV.2 es CONDICIONAL** —hilos de conversación persistentes, lo único que OWUI habría dado hecho— y solo se ejecuta si el piloto muestra que los funcionarios lo piden |
| Bloque OWUI — Carcasa de chat desechable (adaptador compatible-OpenAI + Pipe) | — | ❌ | — | ❌ **DESCARTADO el 2026-08-11** (decisión del usuario). **Reconsiderado el mismo día** con el caso de Gerencia (asistente interno revisable) y **confirmado el descarte**: OWUI no aporta la revisión, duplicaría el registro de conversaciones y debilitaría la cadena de identidad. Lo que sí daba hecho —hilos persistentes— queda como REV.2 condicional. Se reabriría solo si Gerencia quiere un espacio de trabajo conversacional (hilos largos, adjuntos, prompts guardados, compartir) y no un asistente de preguntas con fuente. Cuatro razones: se pierde la identidad institucional —que SEC.8.6 y el hallazgo #3 de MAN.2 acaban de construir—, actualizar OWUI cuesta, consume recursos de la VM única, y el público al que servía (personal interno, con historial y UX rica) ya está servido o es más barato de añadir al frontend propio. **El adaptador compatible-OpenAI también se aparca**: tiene valor independiente, pero solo si aparece un consumidor concreto; sin él es código especulativo. El andamiaje (scope `chat:completions`, PAT, identidad delegada) ya está desde SEC.2.1 si algún día se reabre. Lo que se pierde, dicho sin adornos: historial de conversaciones y UX de chat rica. Registro original abajo. ~~Pendiente — OWUI.1-OWUI.3 (post-deploy). Añadido 2026-07-24 desde `docs/DECISION_OPENWEBUI_CARCASA_CHAT.md`.~~ Adaptador `/v1/chat/completions`+`/v1/models` sobre el grafo, contrato de citas P6 + anonimización P7, Pipe delgado. Reglas: OWUI llama al backend, la gobernanza no vive en OWUI. **Ampliado 2026-07-27**: `/v1/models` filtrado por `assert_chatbot_access`, cabecera `X-GovGenAI-Actor` firmada emitida por el Pipe (decisión (a)), traducción de 429/403 a errores OpenAI, y sección obligatoria "Lo que NO se usa de OWUI" (ni Groups para autorizar, ni LiteLLM, ni plugins de token-tracking) |
| Bloque ING.0 — Fundamentos del corpus normativo | ING.0.5 ✅ | — | — | ✅ Completo — **replanificado 2026-07-28**: de 2 prompts a **5** (ING.0.1 vocabulario como dato, ING.0.2 modelo de datos del documento, ING.0.3 front-matter + manifiesto, ING.0.4 chunker 5 niveles + anclas, **ING.0.5 Opus** reconciliador + CLI). Los antiguos ING.0.1/ING.0.2 (nunca ejecutados) quedan sustituidos; su contenido se conserva ampliado en ING.0.3 e ING.0.5. Motivo en el historial 2026-07-28 |
| Bloque VIS — Vistas del fundamento único (recuperación por metadatos) | VIS.5 ✅ (implementados el 2026-08-25, **en `main` desde entonces**; verificados el 2026-09-18) | — | — | ✅ **Completo (2026-09-18)** — **desviación documentada: VIS.4 y VIS.5 ya estaban implementados y desplegados**, con sus tests (`test_vis4_primero_vigente_despues_lengua.py`, `test_vis5_el_aviso_dice_lo_que_es.py`, 18 passed), y la fila se quedó tres semanas en «reabierto». Lo que faltaba de verdad era la **especificación**: §5.2 describía `prefer` como «prefiere esa versión» sin decir que la lengua opera **dentro** de la vigencia, y no mencionaba el aviso de lengua — o sea que quien la leyera concluiría lo contrario de lo que el código hace. Verificado: el orden con dos versiones sembradas a mano (llega `val` sin validar con score 0,91, gana `es` validada con 0,72, y entre dos igual de vigentes gana la lengua de la pregunta) y el aviso contra el corpus real en las tres lenguas. Reabierto el 2026-08-24 con VIS.4 (primero vigente, después lengua) y VIS.5 (el aviso de traducción avisa del idioma de la pregunta, no del de la fuente), los dos entre AIS y Deploy. Lo anterior, completo — VIS.1 (filtro de metadatos en SQL, fail-closed) + VIS.2 (Niveles 0/1/2: índice de submaterias, selección escalonada, inyección de subconjunto con recorte) + VIS.3 (canónica única, derogados fuera de la recuperación, advertencia de vigencia garantizada por el grafo). Detalle en el historial 2026-07-31 |
| **Bloque ACT** — Actualizar el corpus sin pagar dos veces; idioma, emparejamiento y vigencia como el corpus los declara | ACT.7 ✅, ACT.0 ✅, ACT.1 ✅, ACT.2 ✅, ACT.3 ✅, ACT.4 ✅, ACT.5 ✅, ACT.6 ✅, ACT.8 ✅, ACT.9 ✅, ACT.10 ✅, ACT.11 ✅ | — | — | ✅ **Completo el 2026-08-29** (12 prompts). **El corpus del 27-08 está ingerido en los cuatro asistentes** y la segunda pasada da `ingeridos=0 copiados=0 metadatos=0`: idempotencia probada sobre el corpus real. Normativa 295 documentos (las 22 externas fuera, decisión escrita ya en `assistents.json`), Gerencia 130 con las 22. Lo que el bloque cambió de comportamiento: se recupera **una sola versión por norma, la de la lengua de la pregunta** (`canonica` retirado, migración `d1a2b3c4e5f6`); `ca` y `val` son la misma lengua en todo el sistema; sólo lo que **afirma** que ya no rige queda fuera del índice, con la causa en vocabulario; y la validación de vigencia es de la NORMA, así que se comparte entre las dos versiones. Y **ACT.8**: quien busca por fragmentos los tiene — el banco agéntico ingería sin trocear y su índice se habría ido vaciando norma a norma. Decisiones para Secretaría General en `docs/CONFIGURACION_APERTURA_PILOTO.html` §12 |
| **Bloque HIB** — Madurar los cuatro asistentes para el piloto con informadores | HIB.J ✅, HIB.G ▶, HIB.H ✅, HIB.I ✅, HIB.B ✅, HIB.C ✅, HIB.Q ✅, HIB.D ✅, HIB.L ✅, HIB.O ✅ | **HIB.M** (ablación en Gerencia; espera lote) | **Opus** para HIB.J — decidir qué significa la puerta en la escala RRF es diseño | ▶ **En curso (2026-08-26).** HIB.0 y HIB.A cerrados; el bloque se reescribió dos veces el mismo día: la primera por dos premisas falsas y la literatura, la segunda (Fable 5, sólo redacción) porque HIB.A apagó el reranker y con él el pool de candidatos, y porque el piloto de Gerencia se abre igualmente. 16 prompts en dos ramas: común (B, C, F, G–K) y Gerencia (D, E, L–P). Orden en la tabla del bloque; decisiones fijadas: HIB.C 800 ms / 400 tokens, HIB.P 15 % de silencio máximo. Informe de literatura en `docs/LITERATURA_ASISTENTES_NORMATIVA.html`. |
| **Bloque RES** — Que el asistente responda | RES.5 ✅ | — | — | ✅ **Completo (2026-08-25), añadido y ejecutado el mismo día, delante de Deploy.** Sale de que el usuario rechazara el resultado de RAG.15 —«no resulta aceptable un sistema que no contesta a casi la mitad»— y afirmara que todas sus preguntas tienen respuesta en el corpus: comprobado por SQL, la tenían. **Resultado: Normativa de 18 a 22 de 25, Gerencia de 2 a 6 de 7.** RES.1 la puerta con el mejor fragmento (y `quality_threshold` cambia de significado, escrito en tres sitios) · RES.2 segunda búsqueda al fallar, con **dos fallos silenciosos encontrados verificándola** (tope de salida de 100 tokens sobre un modelo que razona, y plazo de 2 s contra una llamada de 2,4-2,6 s: los dos con el síntoma idéntico a no tener reformulación) · RES.3 expansión léxica sobre `bilingual_terms`, **movida al lado operacional** porque el guardarraíl de la frontera cazó que `termino_de_usuario` es texto de una persona · RES.4 `retrieval_top_k = 3` en los dos, elegido con cifras, y la decisión pendiente del umbral 0,35 **resuelta sola** · RES.5 medido y **cerrado sin implementar**: 0 descartes por citas en 85 respuestas, con la advertencia de que eso es compatible con hasta un 4,4% real. **Migraciones `x4q5r6s7t8u9` y `y5r6s7t8u9v0`** aplicadas con `downgrade` comprobado. Medir RAG.15 dejó al asistente contestando **18 de 25** en Normativa y **2 de 7** en Gerencia, y el usuario lo rechazó: «no resulta aceptable un sistema que no contesta a casi la mitad de las preguntas». Diagnóstico cerrado en `docs/DIAGNOSTICO_POR_QUE_NO_CONTESTA.html`: **dos defectos y ninguno es la anchura**. (1) La puerta promedia todas las puntuaciones, así que la cola vota; puntuarla sobre **el mejor fragmento** da 20/25 y 4/7 **con cualquier anchura** — la columna es plana en 2, 3, 5 y 8. `top_k=2` contesta lo mismo pero con 6/25 y 5/7 de fuente única, y un suelo relativo al mejor se probó y da peor. (2) **No hay normalización en la primera pregunta**: `query_rewriting_enabled` está en `t` en los tres chatbots pero `necesita_reescritura` exige dos turnos previos, así que `rewritten_query` fue `None` en las 14 ejecuciones medidas; reformulada al vocabulario de la norma, una consulta pasa de 0,126 a 0,640. **RES.1** la puerta con el mejor fragmento (y `quality_threshold` cambia de significado, hay que escribirlo donde se lea) · **RES.2** segunda búsqueda con la consulta reformulada, **sólo al fallar** (28% de las consultas en Normativa, 71% en Gerencia), con guarda contra bucles y prompt nuevo —el de `query_rewriter` resuelve pronombres, que no es esto— · **RES.3** expansión léxica sobre `bilingual_terms`, que **ya está cableado al `tsvector` como columna generada**, con los candidatos que produce RES.2 y una persona que sólo aprueba o rechaza · **RES.4** medir la anchura y los umbrales cuando ya no dependan de dos mandos, y regenerar la batería de Gerencia. **Decisión pendiente del usuario**: el umbral 0,35 del `economicoadministratiu` |
| **Bloque DET** — Desempate determinista del retriever | DET.1 ✅ | — | — | ✅ Completo — **añadido y ejecutado el 2026-08-02** al cuadrar la deuda del cierre de RAG. El orden de dos fragmentos empatados lo decidía el plan de la consulta, o sea que decidía **qué norma se cita**. Desempate por `content_hash` (no por `id`, que es uuid4 y cambia en cada reingesta): **en SQL en la rama léxica**, **en Python tras el LIMIT en la vectorial**, porque un `ORDER BY embedding <=> $1, id` **inutiliza el índice HNSW** de RAG.3 (medido: pasa a `Seq Scan + Sort`). 5 tests nuevos, baseline regenerada y ya estable |
| Bloque SYNC — Sostenibilidad de la vigencia del corpus | SYNC.2 ✅ | — | — | ✅ **Completo (2026-08-02)** — SYNC.1 (fuente MCP sobre el reconciliador de ING.0.5, con `content_hash` de transporte para que el coste sea proporcional a los cambios) + SYNC.2 (caducidad activa: `data_revisio_prevista` vencida ⇒ finding `revisio_vencuda`, con default de 1 año al ingerir). Suite completa **1500 passed, 1 skipped, 0 failed**. Detalle en el historial. ~~planificado 2026-07-28~~ |
| Bloque TST — Fiabilidad de la suite de tests | TST.4 ✅ | — | — | ✅ Completo — **TST.4 añadido el 2026-08-01** (coste de la verificación: sin cobertura por defecto, `-n auto`, BD por `TEMPLATE`; política escalonada en CLAUDE.md). TST.1 (mocks sobre la clase, no el event_loop) + TST.2 (BD desechable en e2e/auth/pipeline, residuos limpiados) + TST.3 (cero rojos preexistentes). 4 guardarraíles en `tests/infra/test_suite_hygiene.py`. Detalle en historial 2026-07-30 |
| Bloque MOD — Modelos de embedding y reranker: local en edge, API en cloud | MOD.2 ✅ | — | — | ✅ Completo — **añadido el 2026-08-01** a petición del usuario, antes de RAG.6 y **antes de cargar el corpus v1**. Decisión en `docs/DECISION_MODELOS_EMBEDDING_RERANKER.md`. 2 prompts: ~~MOD.1 propósito en la configuración + procedencia en el vector~~ ✅, MOD.2 selección del servicio por la cascada (`get_embedding_service` deja de devolver el local a pelo; `HttpEmbeddingService` para el microservicio) |
| Bloque RAG — Refuerzo del retrieval y calidad RAG | RAG.14 ✅ | — | — | ✅ **Completo (2026-08-02)** — planificado 2026-07-15 desde `docs/COMPARATIVA_RAG_LAMB.md`. 14 prompts (RAG.1-RAG.14), 13 ejecutados aquí + RAG.6b fuera del bloque: ~~dataset dorado+CI~~ ✅, ~~consolidación de grafos~~ ✅, ~~HNSW~~ ✅, ~~tsvector~~ ✅, ~~umbral+presupuesto~~ ✅, **reranker RAG.6 → partido en 6a/6b el 2026-08-01**, ~~contextual retrieval~~ ✅, ~~parent-child~~ ✅, ~~metadato embeddings~~ ✅, ~~query rewriting~~ ✅, ~~bypass~~ ✅, ~~progreso jobs~~ ✅, ~~test scenarios~~ ✅, ~~feedback→huecos~~ ✅. **RAG.6b salió de este bloque y va detrás de Deploy** —ver su fila propia—. RAG.9 llegó muy solapado con MOD.1 y se redujo a hacer obligatoria la procedencia, poner la guarda en la consulta y escribir la CLI |

| **Bloque PIL** — Los dos asistentes del piloto: Vertex, corpus real y pruebas en local | PIL.7 ✅ | — | — | ✅ **Completo (2026-08-15)** — los 7 prompts. Adaptador de Vertex con lote y propósito del embedding, borrado de chatbot con su corpus, aviso de vigencia desplazada, vocabulario y validación, los dos asistentes creados, **37.504 fragmentos ingeridos** y calibración medida. **Suite backend completa: 1921 passed, 3 skipped, 0 failed.** Migración `a1p2i3l4m5n6` aplicada. **Tres hallazgos abiertos que no se arreglan aquí**: la rama léxica devuelve 0 resultados para preguntas naturales (`websearch_to_tsquery` exige TODOS los términos), las cuotas de SEC.4 no tienen superficie, y la página de documentos bloquea el navegador con 297 documentos | **Cuando se planificó: planificado el 2026-08-15.** Análisis en `docs/PLAN_CHATBOTS_E_INGESTA_LOCAL.md` (reescrito el mismo día: la versión del 08-11 daba por pendiente lo que ya está hecho y por resuelto lo único que no). 7 prompts. **Cuatro decisiones del usuario**: embeddings por **Vertex con adaptador propio** (es el proveedor del despliegue y el corpus se embebe una vez), Gerencia como `authenticated` en local y `restricted`+SAML al desplegar, el borrado de chatbot **se arregla en código**, y el aviso de vigencia desplazada **entra antes** de las pruebas. **Cuatro hallazgos verificados contra el código**: el corpus ya viene desdoblado en dos paquetes listos (`generat/ingesta/normatiu` 298 `.md` / `gerencia` 124) con `ambit_principal`+`submateries` en campos reales, así que `assert_vocabulary` **ya no pasa trivialmente y aborta la ingesta** sin vocabulario cargado; **no existe adaptador de Vertex** (`GoogleEmbeddingService` es la API de AI Studio y el resolver solo conoce `google_genai`/`local`); **ningún adaptador por API expone `embed_batch`**, así que el watcher haría ~21.400 llamadas de una en una; y **`hub_documents.chatbot_id` no tiene FK**, así que borrar un chatbot deja su corpus huérfano. Más un defecto del corpus que se resuelve de nuestro lado: de 86 unidades desplazadas por los Estatutos de 2025, **83 tienen fragmentos sin la nota de vigencia**, y se hidrata al montar la evidencia |
| **Bloque PRO** — Las puertas al LLM del módulo de Informes, con el legacy delante | PRO.9 ✅ | — | — | ✅ **Completo (2026-08-17)** — nueve prompts + PRO.2.1. **Reabierto el mismo día con dos prompts más, antes de las pruebas manuales**, a petición del usuario: **PRO.8** (gráficos deterministas) y **PRO.9** (lo que el ETL necesita para una hoja de cálculo). El criterio del usuario es el mismo en los dos casos y es correcto: «los más usuales se elegían de forma determinista sin tener que programarlos». Al medirlo, mi razón para dejarlos fuera en PRO.5 estaba incompleta —juzgué «tipos que nadie ha pedido» sin comprobar cuál es la alternativa cuando faltan, y la alternativa es **generar código**: `translate_nl_to_config("chart_config")` no devuelve configuración, llama a `generate_script()`, y una plantilla **no puede ni pedir un título**—. En ETL la comprobación dio lo contrario de lo esperado: **lo determinista del legacy está portado al 100%** en PRO.4, así que ahí no hay migración pendiente; lo que falta es cobertura de cuatro operaciones que **ni el legacy ni nosotros** teníamos y que una hoja real necesita —columna calculada, números en formato español leídos como texto (esta es la peor: `sum()` sobre texto **concatena, sin error**), ordenar y unpivot—. Los 7 prompts anteriores + **PRO.2.1 añadido a mitad de bloque** a petición del usuario (biblioteca de prompts con el tier sobreescribible). **Suite backend completa: 2197 passed, 3 skipped, 0 fallos** (11 m 42 s desde Git Bash); frontend sin fallos; `tsc` limpio; dos migraciones aplicadas (`c3v4y5z6a7b8` veredicto del auditor, `d4w5z6a7b8c9` prompts de actividad). **El resumen del bloque, en una línea: las puertas al LLM estaban cerradas y detrás de ellas el camino estaba cortado en once sitios.** Lo cerrado: auditoría de tres niveles con rutas absolutas y dos listas (PRO.1); nivel 2 escribe y nivel 3 audita, con el veredicto del modelo encima de la determinista (PRO.2); el prompt y el nivel de cada actividad editables desde el panel (PRO.2.1); el script aprobado extrayendo dentro de un informe (PRO.3); ETL con modelo y las diez operaciones de limpieza del legacy (PRO.4); gráficos en el informe y el informe **descargable** (PRO.5); el copiloto alcanzable y respondiendo con citas (PRO.6). Lo que se descubrió y nadie sabía: **el fichero de prueba no llegaba nunca al sandbox**, **los datos extraídos no se veían en ningún informe** —ni por script, ni por Excel, ni por PDF—, **el bloque CHART no dibujaba nada**, **el informe no se podía exportar** y **`blocks/handlers.py` sólo lo importaban los tests**. Comparativas escritas en `docs/COMPARATIVA_LEGACY_INFORMES.md` y `docs/COMPARATIVA_ETL_LEGACY.md`; niveles de modelo en `docs/NIVELES_DE_MODELO.md`. Planificado el mismo día: ⏳ 7 prompts. Planificado y **reescrito el mismo día** al avisar el usuario de que todo esto ya estaba programado, probado y funcionando en NiceGUI (`C:\Users\fabra\Documents\AutomatIA`). Lo que iba a ser «cablear dos dependencias» pasa a ser **portar decisiones ya tomadas**, y varias son mejores que las del código nuevo: el legacy tiene auditoría determinista de **tres niveles** (`SAFE`/`WARNING`/`CRITICAL`) con número de línea y **regex de rutas absolutas** que la nueva perdió —un script que abra `C:\Users\...` pasa su auditoría—, mientras la nueva es binaria (`approved = not findings`) y un `import csv` tumba la propuesta igual que un `eval()`. Además: **el nodo ETL del grafo se construye sin modelo** (VER.1 no le pasó `etl_llm`) y **no hay endpoint de ETL**, siendo ETL y gráficos lo que el usuario señala como más usado; el copiloto y el modo foco **estaban montados en el legacy**, así que no hay que decidir dónde van. Decisiones: auditoría graduada, **Tier 2 para escribir y Tier 3 para auditar** (hoy todas las configuraciones son de nivel 1), auditoría con modelo **encima** de la determinista y no en su lugar, y comparar con el legacy antes de escribir en ETL y extracción de PDF. **Los scripts libres se aparcan para automatizaciones**, razonado en el bloque |
| **Bloque RAS** — Rastreo de un portal institucional real | RAS.5 ✅ | — | — | ✅ **Completo (2026-08-18)** — los 5 prompts. **RAS.1** cortesía (pausa por host, `robots.txt` una vez por host con su `Crawl-delay`, User-Agent con contacto, presupuesto de tiempo, concurrencia acotada) y, de paso, **un rastreo truncado ya no declara bajas**: las bajas se calculaban como «activas que no aparecen», lo que con `max_pages` declaraba desaparecido lo no visitado. **RAS.2** `needs_javascript` en vez de acusar de vacía, con heurísticas **calibradas contra el portal** —una página estática de `www.uji.es` lleva `<noscript>` y diez `<script>`, así que ni eso es evidencia— y, por el camino, de una página se guarda **su texto y no 51 KB de marcado** (con el HTML dentro, `token_count` medía plantillas, el umbral de `thin` era inalcanzable, el detector semántico comparaba menús idénticos y al corpus llegaban `<div>`). **RAS.3** reanudación por cola guardada, reintentos con espera creciente, 404 ≠ timeout en severidad, y **no pedir dos veces la misma página** (el recorrido descargaba y tiraba; el guardado volvía a pedir: 25 páginas, 50 peticiones). **RAS.4** decisión escrita **sin navegador**, con la medición delante: 0 de 25 páginas lo necesitan. **RAS.5** el apartado de la Escuela de Doctorado de punta a punta, y aquí salieron **siete defectos más**, tres que impedían rastrear y cuatro que hacían mentir al informe: un enlace roto tumbaba el rastreo completo (primer intento real: **cero páginas** por un 404), un PDF enlazado se guardaba como texto y el byte `0x00` lo tumbaba otra vez, `config_json` no se podía fijar ni al crear ni al editar un sitio —así que `url_regex_filter`, la decisión operativa del bloque, era inalcanzable desde la interfaz—, la mitad de las páginas eran la misma en `http` y en `https` (191 supersesiones falsas), el portal tiene una **trampa de rastreador** en su conmutador de idioma (526 URLs pendientes que no acababan y 107 supersesiones falsas más), los 404 salían además como `empty` crítico, y una página ilegible se declaraba «la versión vigente». Y en el camino al asistente: **el botón de ingerir respondía 202 y no ingería nada** (servicio sin watcher, fallo en background), **`changed_page_ids` no lo consumía nadie** (el portal cambiaba y el asistente seguía citando el texto viejo) y **el job del arranque se construía con `watcher=None`**, así que nada de eso podía ocurrir en la aplicación real. Decisión del usuario: una página del corpus que cambia **se actualiza sola y queda avisada** (`content_updated`). Caso escrito en `docs/CASO_CURACION_ESCOLA_DOCTORAT.md`; decisión de renderizado en `docs/DECISION_RENDERIZADO_RASTREO.md`. Planificado el mismo día: **Cuando se planificó: planificado el 2026-08-18.** Caso guía: **el apartado de la Escuela de Doctorado de `www.uji.es`**, elegido porque está acotado, su contenido envejece de verdad y **es la misma unidad que el caso del Bloque SEG** —la misma gente, dos herramientas—. **La finalidad ya está construida y no se toca**: los detectores emiten `empty`, `thin`, `stale`, `orphan_page`, `crawl_error` y **`superseded`** (agrupa versiones del mismo recurso quitando los segmentos de año de la URL, que es literalmente «la nueva se publicó y la vieja sigue ahí»), más duplicado y contradicción por semántica; y `CorpusSelectionService` ya lleva de la página rastreada al corpus del asistente con decisión humana. **Lo que falta es poder apuntarlo a un portal de verdad**, y son cuatro cosas. (1) **Cortesía**: el bucle es secuencial, con `timeout` de 10 s y **sin pausa entre peticiones ni lectura de `robots.txt`** — miles de peticiones seguidas contra el portal de la propia casa figuran en sus registros como lo que parecen; es requisito, no mejora. (2) **El contenido dinámico**, que el usuario señaló: los enlaces se extraen con una regex sobre `href=`, así que una página pintada con JavaScript vuelve sin texto y el detector emite hoy **`empty` con severidad crítica** — un falso positivo que afirma lo contrario de la verdad y que arruinaría la credibilidad del informe en la primera pasada. Se resuelve con **sondeo previo sin navegador** (la señal más fuerte sale gratis: el hueco entre las URLs del sitemap y las que alcanza el recorrido por enlaces) y con un tipo nuevo **`needs_javascript`**, que dice lo único que el sistema sabe de verdad: «no se ha podido leer sin renderizar». (3) **Reanudación**: la cola BFS vive en memoria y arranca siempre de `root_url`; un corte en la página 8.000 obliga a empezar de cero. Y un `timeout` se convierte hoy en `crawl_error` crítico sin reintentos, o sea decenas de falsos positivos por causas de red. (4) **Renderizado con navegador, sólo si el sondeo dice que hace falta**, y como extra de instalación desactivado por defecto: es la misma decisión que se tomó con `torch` y la app está en ~345 MB precisamente por eso. **Fraccionar, no rastrear el portal entero**: el spider ya lee `url_regex_filter`, así que se da de alta un sitio por apartado — y no es sólo técnico, cada apartado tiene un responsable distinto y un informe del portal completo no lo lee nadie |
| **Bloque SEG** — El asistente de informes de seguimiento: valoración anclada a su tabla | SEG.5 ✅ | — | — | ✅ **Completo (2026-08-18)** — los 5 prompts. **Suite backend completa desde Git Bash: 2360 passed, 3 skipped, 0 fallos** (8 m 38 s); **frontend: 358 passed, 0 fallos**; `tsc` limpio; el contrato OpenAPI no cambia. Verificado de punta a punta con el informe real del Programa de Doctorado en Ciencias (70.181 bytes, 42 tablas): cada apartado trae **una** tabla y es la suya, ninguna valoración usa cifras que no estén en el origen, las tres tablas con «No hay valor» lo dicen, y el DOCX sale con las tablas como tablas de Word. Caso escrito en `docs/CASO_INFORME_SEGUIMIENTO.md`. **Montarlo de verdad destapó cuatro cosas más, todas del mismo tipo —la capacidad existía y la puerta estaba cerrada—**: (1) **los bloques `TABLE` no los pintaba nadie**, estaban en el contrato, el validador les exigía `data_block_ref` y el prompt los ofrecía, pero ningún nodo los rellenaba, así que el informe salía con las nueve tablas vacías sin error ni aviso —es el mismo agujero que PRO.5 tapó para los gráficos, y lo cubre ahora `TableRenderNode`—; (2) **un bloque que no está en ninguna sección desaparece del informe**, porque la vista previa y el ensamblado recorren `sections[].block_ids`, y el informe salía corto con aspecto de estar bien —ahora se rechaza al publicar la plantilla y al validar el borrador, con la regla también en el prompt—; (3) **las tablas del cuerpo se pintaban sin estilo**, porque sólo estaba vestido el anexo de auditoría (hasta ahora ningún bloque del cuerpo había producido una tabla); (4) **la valoración llegaba con markdown crudo** —`**Producción vegetal:**` impreso literalmente— y con longitud de ensayo. Planificado el mismo día: **Cuando se planificó: planificado el 2026-08-18.** Es el **supuesto de uso que el usuario necesita y que no estaba escrito en ningún plan**: «el informe lee la información, presenta las tablas y gráficos en la estructura que define la plantilla de forma determinista y, a continuación, la literatura con la valoración de tendencias o el resumen de resultados la propone la IA, sujeto a aprobación o edición por el humano». Caso guía real: el **informe anual de seguimiento de un programa de doctorado**, con dos documentos sobre la mesa —el resumen de datos de un programa (30 tablas) y el prompt de la gema de Gemini que se usó antes—. **Por qué el intento anterior no bastó**: la gema *inventaba datos al pintar las tablas* y *resumía omitiendo información relevante*; su prompt pelea contra eso en mayúsculas, y perder esa batalla a base de instrucciones es lo esperable. Aquí las tablas **no las escribe el modelo**. **El hueco que decide si el módulo sirve para esto**: `_build_context` mete **todos** los bloques extraídos en un solo contexto y lo entrega igual a cada apartado de IA, y `AIAssistedTextBlock` sólo tiene `ai_prompt_template_id` y `review_policy_id` —**no puede decir «reflexiona sobre la Tabla 1.2»**—, así que con 30 tablas cada valoración recibiría las 30: el fallo de la gema reproducido por arquitectura. Sin SEG.1 el resto no vale. 5 prompts: SEG.1 anclaje (`data_block_refs`, contexto sólo con esos bloques, y un apartado sin anclaje **consta en el manifiesto**), SEG.2 la instrucción de valorar tendencias con sus reglas duras portadas del prompt real (no recalcula, «No hay valor» se respeta, sugerencias en tono no imperativo), SEG.3 pipeline de tablas Markdown (el origen de hoy; JSON o API mañana, aditivo), SEG.4 **cablear la edición**, que el backend ya sabe hacer —`editBlock` guarda el original en auditoría y **su hook generado no lo llama ninguna pantalla**—, SEG.5 la plantilla del informe de doctorado de punta a punta con datos reales. **Decisión tomada al planificar**: los datos que no están en el documento se piden **por formulario y no por conversación** —cada respuesta queda registrada y asociada al informe—, con campos opcionales y selector sí/no, **sin condicionalidad**, que exigiría ampliar el contrato de entrada sin aportar nada que un campo vacío no resuelva |
| **Bloque CUR** — La curación vista por quien cura | CUR.9 ✅ | — | — | ✅ **Completo (2026-08-19)** — los 7 prompts + CUR.2.1 + **CUR.8** (cuatro arreglos de las pruebas manuales: las dos URLs de un duplicado, la razón de cada hallazgo, la confirmación de la ingesta y el botón de PDF sólo cuando hay PDF) + **CUR.9** (la reconciliación: un hallazgo que ya no se detecta se retira, y la cola arranca en «Pendientes»). CUR.1 ✅ la fecha real que publica el portal (`.clockBarDate` → `24/09/2025` \| `Escola de Doctorat`) con selector **por sitio**: 28 de 31 páginas del apartado traen ya fecha real, y salen páginas de 2015 y 2017 con su unidad responsable. CUR.2 ✅ una serie anual es **un** hallazgo informativo con sus URLs y fechas, y ninguna página aparece en dos apartados; más el duplicado exacto por `content_hash` con las dos URLs y sus dos fechas, que pidió el usuario. **CUR.2.1 ✅ añadido a mitad de bloque** por una pregunta suya sobre el despliegue multiorganización, y tenía razón: el aislamiento de datos sí era por organización, pero **los criterios de juicio eran globales** —`stale_days` y el umbral de contenido pobre los ponía el constructor del detector y **nadie los pasaba**, y CUR.2 acababa de fijar global que una serie por años no supersede, que es cierto en la UJI y falso en un portal que versiona convocatorias—. Ahora `stale_days`, `thin_min_tokens` y `version_series_policy` (`series`\|`superseded`\|`off`) son configuración del sitio, con los defectos de hoy; frontera escrita en `docs/CURACION_MULTIORGANIZACION.md`: **el criterio es dato, la honestidad es código** —la cortesía, no acusar de lo que no se pudo leer, 404 ≠ timeout y la identidad de una URL no se pueden desactivar—. **CUR.3 ✅** al corpus sólo el contenido, y la medición corrigió dos veces al plan: el portal **no usa `<nav>` ni `<header>`** —su menú son `div` con clases— pero **sí `<main>`**, que es la señal inversa y quita el 39 % de una página y el 67 % de la de normativa; y la regla de seguridad planificada («si se lleva más de la mitad, conserva el original») **habría revertido justo esa página**, así que se cambió por lo único inequívoco: quedarse sin nada. Con selector de contenido, selectores de plantilla declarados y una pasada de **repetición medida** —una línea que sale en el 60 % de las páginas es menú—, el rastreo completo dio **349 páginas, 21 bloques de plantilla, 176.303 caracteres quitados, 0 revertidos y 0 páginas vacías**: de 4.106 caracteres por página a 1.585. **CUR.4 ✅** poder mirar lo que el informe dice: las URLs de los hallazgos son enlaces que abren en otra pestaña, un hallazgo de grupo **se despliega** con sus versiones y sus fechas en vez del «+4 más» muerto, el «+N más» del informe de auditoría también, y —lo que más falta hacía y no estaba pedido así— se puede **leer el texto guardado** de una página, que es lo que iría al asistente y lo único que permite juzgar si un hallazgo es cierto y si el recorte de CUR.3 se comió algo. Y verificarlo en el navegador destapó que **la pantalla no tenía con qué**: el contrato de la cola de hallazgos no servía `page_id` ni la señal, así que los dos botones nuevos no aparecían nunca fuera de los tests —275 hallazgos reales en pantalla, cero botones—. Arreglado en el contrato (`_FindingOut` con `page_id` y `signal`), con el doble del test convertido en clase real: un `MagicMock` inventaba un `.signal` que la fila de la base de datos no tiene y habría dado el test por bueno leyendo un atributo inexistente. Verificado en vivo tras el arreglo: «Ver las 9 versiones» con sus fechas, 274 botones de ver texto, y el visor de una página mostrando `Acords Comité de Direcció … · Escola de Doctorat · 18/11/2021 · 263 tokens` con 1.052 caracteres de contenido limpio. **CUR.5 ✅** la descarga y la selección. La descarga era un `<a href download>` contra la API, o sea **una navegación sin cabecera de autorización**: 401, y el navegador enseñando su propio error —«el fitxer no es troba disponible»—, que no menciona el 401 y parece que el informe no exista. Ahora se pide con el cliente autenticado (`shared/api/download.ts`) y se entrega desde memoria, con el fallo visible en la pantalla si lo hay. **El mismo defecto estaba en Informes** —el `<a href>` a `/redaccion/workspaces/{id}/export`, con `Depends(get_current_user)` detrás—, así que PRO.5 dejó el informe «descargable» sin que la descarga pudiera funcionar: arreglado también, con su test. Y en publicación se puede **elegir**: casilla por página, «marcar todo», e ingerir sólo lo marcado —sigue sin haber «ingerir todo el sitio»: cada página entra porque alguien la marcó; lo que desaparece es pulsar 349 veces—. Además **se ve lo que ya está en el corpus**, que exigió una decisión de contrato: una página ingerida ya no se descarta de la lista, se devuelve con `is_ingested` —esconder la fila no distingue «ya está en el corpus» de «nunca fue candidata», y al pulsar «Ingerir» la fila desaparecía sin confirmar nada—. Verificado en vivo: DOCX descargado de verdad (39.746 bytes en Descargas, los mismos que sirve el endpoint), «Descargar PDF» guarda un `.docx` porque **el servidor declara el fallback sin LibreOffice** y el nombre del servidor manda (la honestidad de VER.7 llega hasta el fichero guardado), tres páginas marcadas e ingeridas de una tacada (3 documentos en la base) y el resumen pasando a «346 por publicar · 3 ya en el corpus» con sus tres casillas bloqueadas; la exportación de Informes, un DOCX de 36.648 bytes. **CUR.6 ✅** reconocimiento antes de rastrear: un sondeo que **no guarda nada** —ni el sitio hace falta que exista— y devuelve las URLs agrupadas por subapartado, el total, el CSV descargable y **cuánto tardaría el rastreo**, que es lo que responde «de golpe o por subapartados». La estimación sale de lo medido y de la cortesía real: `segundos_por_pagina` se mide en el sondeo y se le suma la pausa que el rastreo va a usar, porque estimar con la latencia del sondeo rápido daría minutos donde el rastreo tarda horas. Verificado contra el portal, y la primera pasada estaba mal: el sondeo usaba la **profundidad del formulario** (1) y devolvía 11 URLs de un apartado que tiene 349 —contestaba a otra pregunta—; el plan decía «profundidad y tope propios» y ahora baja 3 niveles. Con eso: **219 URLs desde 60 páginas pedidas**, aviso de truncado por `max_pages`, y «unos 11 min, a 3,1 s por página». Y un hallazgo del portal que nadie buscaba: el apartado más grande sale como **`estudis` con 188 URLs**, porque la misma sección es alcanzable bajo `/estudis/centres/escola-doctorat/` además de `/centres/escola-doctorat/` — dos prefijos para el mismo contenido, que es parte de la duplicación que el usuario veía. **CUR.7 ✅** el detector semántico corre de verdad: existía desde 9Q.4 con sus tests y el job se construía con un solo detector, así que `audit_semantic_scope='full'` no significaba nada. Cablearlo destapó **cuatro defectos más**: el job **no persiste** los hallazgos (los cuenta y calcula `quality_score`, pero guardarlos lo hace cada detector, y el semántico decía que era del job), el flag `run_semantic` **nunca se aplicaba** (se mira con `getattr(detector, "_is_semantic", False)` y ningún detector declaraba el atributo), casi se cablea el adaptador equivocado —`RedactorDeBloques` cumple el mismo protocolo pero entiende su primer argumento como el **id** de una plantilla, así que el juez habría recibido «esa plantilla no está en el catálogo» y contestado `unrelated` a todo—, y el detector **funcionaba exactamente una vez por sitio**: la segunda pasada falla con `float32 is not JSON serializable` porque los vectores de pgvector vuelven como numpy y la similitud va a un JSONB. **Ejecutado cuatro veces contra el apartado real** (349 páginas embebidas, tope de 25 pares), y cada pasada corrigió la anterior: 10 hallazgos y **los 10 el falso positivo que el usuario ya corrigió en CUR.2**, con otra sintaxis —el archivo de formación transversal publica una página por curso académico (`/23-24/`, `/24-25/`) y la identidad de serie sólo reconocía años de cuatro cifras, así que **el determinista tampoco los agrupaba**—; arreglado en la identidad, sirve a los dos detectores, y el semántico deja de pagar llamadas por pares de la misma serie. Quedaban 11, de los que 9 seguían siendo ediciones del mismo curso con la ruta reorganizada (`recerca/programacio-r` → `tecniques/programacio-r`), que ninguna regla de URL puede cazar: se resolvió **diciéndoselo al juez** —el dato del dominio de CUR.2, generalizado—. Resultado final: **13 hallazgos, 0 contradicciones, 13 duplicados**, y los cuatro primeros son lo que el usuario sospechaba: la misma página bajo dos rutas del portal (`/base/escola/normativa/acordacded/` vs `/escola-doctorat/normativa/acordacded/`, `/base/info-academica/…` vs `/info-academica/…`, `internalitzacio` vs `base/internacionalitzacio` —con la errata incluida—) y **`/base/calendari` contra `/base/calendari/`**, que no es duplicación del portal sino nuestra: la misma página rastreada dos veces por la barra final. Arreglado con una clave de identidad que **no cambia la URL que se pide** (hay servidores donde `/x/doc` existe y `/x/doc/` da 404). El alcance semántico se puede cambiar desde la fila del sitio, con `off` incluido |
| ~~**Bloque CUR** (planificado)~~ | — | CUR.1 | Sonnet (CUR.2 y CUR.3, Opus) | ⏳ **Pendiente, planificado el 2026-08-19** a partir de las **pruebas humanas del Bloque RAS**. Ocho observaciones del usuario sobre el informe del apartado de la Escuela de Doctorado, y ninguna es de estilo: cuatro son hallazgos falsos o duplicados, tres son cosas que **no se pueden hacer desde la interfaz** —ver el contenido de una página, abrir una URL, elegir qué se ingiere— y una es un botón que responde 401. **El hilo común: el módulo produce un informe y no da forma de comprobarlo.** Dos entradas que no se deducen del código: (1) el dato del dominio que tumba un detector —el portal publica acuerdos y actas **por año y todos siguen vigentes**, así que declarar «superada» la de 2017 afirma algo falso, y encima la misma página sale en dos apartados—; y (2) el regalo que estábamos ignorando: **cada página publica su fecha y su unidad responsable en el HTML** (`<div class="clockBarDate">` → `24/09/2025` \| `Escola de Doctorat`), con lo que «desactualizada» pasa de conjetura a dato. 7 prompts: CUR.1 la fecha real del portal (selector por sitio, no hardcodeado), CUR.2 una serie anual es **un** hallazgo informativo y nunca la misma página en dos apartados, CUR.3 fuera el menú y la plantilla para que al corpus vaya solo el contenido —lo que habilita el chatbot de prueba—, CUR.4 poder mirar lo que el informe dice (URLs clickables, «+4 más» desplegable, y **ver el texto guardado** de una página), CUR.5 la descarga con autorización y la selección de candidatas, CUR.6 reconocimiento previo del sitio con recuento por subapartado y CSV, CUR.7 cablear el **detector semántico**, que existe, está probado y no lo ejecuta nadie —el sitio está en `full` y no cambia nada—. **CUR.1 y CUR.3 cambian lo que se guarda**, así que exigen volver a rastrear el apartado (12 min) para ver el efecto |
| **Bloque LEG** — Retirada del legacy de prompts de AutomatIA | LEG.5 ✅ | — | — | ✅ **Completo (2026-08-19)** — los 5 prompts. **Suite backend completa: 2488 passed, 3 skipped, 0 fallos** (8 m 14 s) **y sin el flake** de `tests/test_prompts.py` que llevaba semanas inventariado. Migración `h8a9d0e1f2g3` aplicada. **LEG.1** los ocho prompts leídos antes de borrarlos (`docs/COMPARATIVA_PROMPTS_LEGACY.md`): el vivo gana en generación de scripts —genera las listas prohibidas del auditor en vez de escribirlas a mano, prohíbe rutas absolutas y declara el contrato de `result`—, y una regla del legacy **se descarta a propósito** («maneja excepciones con try/except» convierte un fallo visible en una tabla vacía que nadie revisa, y el auditor vivo dice lo contrario); **lo único que aporta** es la nomenclatura semántica, portada al prompt del ETL con su test, porque el modelo crea columnas y su nombre acaba impreso en la tabla de un informe; y lo que no tiene equivalente —clarificación previa, orquestación de flujos con prioridad LOCAL/ORGANIZATION/PARTNER/GLOBAL, disparadores independientes con suscripción, pasos `PLACEHOLDER`— queda **citado** para el bloque de automatizaciones en vez de conservarse como código muerto. **LEG.2** el arranque deja de sembrar en `extraction_service_config` y `system_prompt`: era la causa común de los dos síntomas —arranques fallidos en desarrollo y el flake—, porque el servidor escribía mientras la suite reinicializaba. **LEG.3** fuera el orquestador huérfano (0 % de cobertura, 220 líneas nunca ejecutadas) y guardarraíl que prohíbe **abrir sesión** sobre `server_engine`, no importarlo: hay un test-smoke legítimo que sólo comprueba que el motor existe, y un guardarraíl con falsos positivos se acaba desactivando. **LEG.4** dos clases de diecinueve fuera de `models.py` —el fichero se queda— y migración que borra las tablas; al escribirla salieron dos cosas: se llaman `extractionserviceconfig` y `systemprompt` **sin guiones bajos** (es el nombre que SQLModel deriva de la clase, y por escribirlos «bonitos» falló el primer intento) y va con `IF EXISTS` porque en esta base no estaban, al haberse creado el esquema con `create_all` y no con Alembic. **LEG.5** el `main.py` de la raíz (705 líneas de NiceGUI) a `_legacy_nicegui/`, `arranque.bat` sin la opción que lo lanzaba y comprobado que su comando levanta el servidor; el `grep -r` a cero destapó **dos consumidores más** que el plan no conocía —`client_app/main.py`, otro lanzador NiceGUI, y `client_app/tests/unit/test_watcher_migration.py`, que prueba las rutas del fichero movido—, y los dos van a cuarentena con su ruta relativa. Planificado el mismo día: **Cuando se planificó: planificado el 2026-08-18** — sale de una pregunta del usuario sobre unos logs de arranque, y **no es limpieza estética**: esta vía **escribe en la base de datos en cada arranque del servidor**, que es lo que colisiona con la suite cuando ambos corren a la vez. Dos síntomas ya observados con una sola causa: los arranques fallidos del log del 2026-08-17 y el flake de `tests/test_prompts.py`, que pasa aislado y falla en la suite paralela porque usa `server_engine` —la BD real del desarrollador— y siembra prompts. **Qué es**: ocho prompts de la época de AutomatIA (generador de scripts, clarificación por tipo de tarea, procesado con LLM, naming semántico, orquestador de flujos, metaprogramación) sembrados en `ExtractionServiceConfig` y `SystemPrompt`. **Por qué se puede retirar**: su único consumidor es `knowledge_orchestrator_service.py`, que **no lo importa nadie** —cero referencias en `server/`, **0 % de cobertura**, 68 líneas sin ejecutar—; los prompts vivos son `HubPromptTemplate` (por asistente) y `HubActivityPrompt` (por actividad), que no se tocan. 5 prompts: LEG.1 **comparar antes de borrar** (es la lección de PRO.1 y PRO.4: el legacy tenía decisiones mejores y se vieron al leerlo), LEG.2 cortar la siembra del arranque, LEG.3 el orquestador huérfano y el test, con guardarraíl contra tests que escriban en la BD del desarrollador, LEG.4 migración que borra las dos tablas, LEG.5 el `main.py` de la raíz a cuarentena. **Tres fronteras localizadas al planificar**: `AutomationLibrary` **se queda** (la usa `library_router`, vivo); `models.py` pierde **dos clases de diecinueve**, no el fichero; y **`arranque.bat` todavía ejecuta `uv run main.py`**, así que mover el lanzador sin tocar el script deja un arranque roto |
| **Bloque VER** — Verificación de Informes y Curación antes del despliegue | VER.9 ✅ | — | — | ✅ **Completo (2026-08-17)** — los 9 prompts. **19 hallazgos, todos arreglados con TDD**, y el resumen es que **el módulo de Informes no funcionaba de punta a punta**: el grafo no se ejecutaba, no había pantalla donde abrir un workspace, la subida de ficheros no se persistía, la extracción los buscaba en el disco en vez de por `StorageService`, las cuatro transiciones de bloque daban 500 y `resume` no reanudaba. En Curación, **el rastreo fallaba siempre** (`site.url` vs `root_url`) y el «PDF» del informe era un DOCX disfrazado. Verificado en vivo: informe generado desde un Excel real con el texto de IA citando las cifras extraídas, y los seis caminos recorridos. Planificado el mismo día: ⏳ **Planificado (2026-08-17)** — 9 prompts. Los dos módulos llegan al despliegue sin haberse recorrido nunca de una pieza, y al planificarlo apareció que **Informes no genera nada**: `POST /workspaces/{id}/run` transiciona el estado y devuelve un `run_id` sintético sin ejecutar el `DraftingCoreGraph`, que está construido entero (14 nodos) y solo necesita sus dependencias inyectadas; `llm-drafts/propose`, `scripts/propose` y `copilot/ask` son stubs 503. Curación sí está cableada (crawler, detectores y planificador se registran en el arranque). **Decisión del usuario**: cablear la generación (VER.1) y `llm-drafts` (VER.2) y luego recorrer los seis caminos en navegador (VER.3–VER.8); copiloto y propuesta de scripts por LLM quedan fuera, documentados. Cierre con la matriz de lo irreducible y el `.bat` humano (VER.9). El crawl de curación apunta al sitio local del corpus en `:4174`, no a `www.uji.es` |
| **Bloque INF** — El módulo de informes, utilizable de punta a punta | INF.10 ✅ | — | — | ✅ **Completo (2026-08-20)** — los 10 prompts, nacido de las pruebas humanas del usuario sobre los dos caminos del módulo, que no llegaban al final. **Cuando se planificó: planificado el 2026-08-20** desde las pruebas humanas del usuario sobre los dos caminos del módulo. **Ninguno de los dos llegó al final.** Trece observaciones, y las dos que importan no son de estilo: **(A)** `WorkspacePage.tsx` tiene dos disparadores de la generación y **uno se salta la subida de datos** (el botón azul destacado, líneas 137-147, frente al submit del contrato, líneas 85-100) — en el log no hay una sola petición de subida, y de ahí sale toda la cascada `Required input slot missing: 'datos'` → tablas sin datos → bloques de IA en error; la plantilla, comprobada en BD, **no tiene ningún defecto**. **(B)** `preview_builder.py:37-49` considera pendiente todo bloque de IA fuera de `{approved, locked}` y `AIBlockReviewPanel.tsx` solo el que está en `needs_review`: un bloque que **falló** cae en el hueco, así que el panel anunciaba «Todos los apartados aprobados» mientras la vista previa y la exportación devolvían 409 por esos mismos bloques, **sin ninguna acción que pulsar**. Es la regla maestra nº2 incumplida: el frontend calcula el estado en vez de recibirlo. Además, **una regresión respecto al legacy señalada por el usuario**: `propose` recibe solo `prompt_nl` y el legacy mandaba `columns`, `dtypes`, `row_count` y `df.head(3)` **anonimizados** (`etl_factory.py:146-200`); y **el prompt induce el error que el validador castiga** (`llm_spec_service.py:85` llama «table» a lo que debe ser un `DETERMINISTIC_DATA`). **Decisión de alcance del usuario (2026-08-20): el control de acceso se resuelve por módulos concedidos, no con un rol nuevo** — hoy no hay ninguno (`App.tsx:92` solo comprueba que hay sesión, cero `role ===` en la navegación, routers de `redaccion` con `get_current_user` a secas), así que cualquier trabajador con cuenta puede editar los chatbots institucionales; el rol `informer` no sirve, su contrato es supervisar respuestas de la IA. 10 prompts en `Plan_TDD_Fase1.md` §Bloque INF; INF.1-INF.3 son los que convierten «no puedo terminar» en «puedo terminar» |
| **Bloque NIC** — Retirada del legacy NiceGUI, con inventario antes de borrar | NIC.4 ✅ | — | — | ✅ **Completo (2026-09-04)** — NIC.1–NIC.4; **NIC.5 absorbido en NIC.3** por decisión del usuario: `client_app/` y `_legacy_nicegui/` se retiraron completos (574 ficheros, 2105 → 1531) porque el agente que se iba a conservar no compilaba. El entorno de la raíz (`pyproject.toml` con `nicegui==3.4.1`, su lock de 1,6 MB, `tests/`, `translations.json`) se fue en NIC.4, con 16 ficheros de tests vivos migrados a `server/tests/` y 25 rojos reparados con regla escrita. Detalle en `HISTORIAL.md` (2026-09-04) y `docs/INVENTARIO_RETIRADA_LEGACY.md` §4–§7. Planificado el 2026-08-21 al revisar el repositorio para abrirlo. Medido: `client_app/` tiene **505 ficheros versionados y 96 importan NiceGUI** (87 en `app/ui`), cuando la regla de `CLAUDE.md` dice que ahí sólo debe vivir el agente de ejecución local (`rpa_executor.py`, `modules/rpa/`, `modules/watchers/`). **Nada en producción lo importa** —las 10 menciones en `server/` son comentarios de procedencia— y sólo hay **un import real**, en `shared/tests/test_security_unification.py:44`. No está en `docker-compose`, ni en el `Dockerfile`, ni en CI. Y la UI NiceGUI existe en **cuatro sitios**: `Documents\AutomatIA`, el bundle de GenGov, `client_app/app/ui` y `_legacy_nicegui/`. **NIC.1 no borra nada: cruza** qué está cubierto en `server/app/modules/automation/` + `frontend/src/`, porque borrar 87 ficheros a ojo es como se pierde una funcionalidad sin enterarse. NIC.5 lo ejecuta el usuario y cierra la Fase 1 |
| **Bloque PLAT** — La administración de la plataforma, separada de la de Chatbots | — | PLAT.1 | Sonnet (PLAT.1, .2, .5, .7) · Opus (PLAT.3, .4, .6) | ✅ **Completo (2026-08-23)** — los 7 prompts. Planificado el 2026-08-22 a propuesta del usuario. 7 prompts, **partidos en la ejecución**: PLAT.1 y PLAT.2 van ANTES del Bloque IDE —las pantallas de IDE.4 e IDE.5 cuelgan de `/plataforma`, la sección que crea PLAT.2— y PLAT.3…PLAT.7 después. Todo antes de Deploy. **No es solo reordenar el menú: el backend y el frontend ya se contradicen.** `hub_llm_configs_router` exige `require_module("plataforma")` y `App.tsx` monta esa pantalla bajo `<RutaDeModulo modulo="chatbots">`, así que hoy **quien tiene `chatbots` y no `plataforma` ve el tab «Modelos LLM» y recibe un 403**, y quien tiene `plataforma` no puede llegar a la única pantalla que ese módulo protege: el módulo existe en `MODULOS_INICIALES`, se puede conceder y **no abre nada** (se retiró del menú porque era un `PlaceholderPage`). Ocho hallazgos medidos, entre ellos: `tier` lo consumen Informes, Curación y Chatbots y `HubLLMConfig` no tiene `organizacion_id` —es global—; `OrganizacionRead` mezcla identidad, tema y **una docena de `default_*` de RAG**, que es por lo que la pantalla acabó bajo Chatbots; el `<textarea>` «Configuración de tema (JSON)» escribe `HubOrganizacion.theme_config` y **nadie lo lee** (la cascada resuelve desde `hub_themes`); `AIBrainPage` importa plantillas de prompt **y** configs LLM sin recurso propio; y no hay interfaz para conceder módulos —**esto último salió a un bloque propio (IDE)**: `HubModuleGrant` dice que «no hay una tabla de usuarios única» y su `subject_id` es un `uuid5` del claim del token, así que no se puede enumerar a quién concederlas—. **El criterio no se inventa**: `Deploy: cloud` es configuración de plataforma, `Deploy: edge` es operación de un módulo. **PLAT.1 no se puede saltar**: sin la migración de concesiones, PLAT.5 deja fuera a todo admin no-superadmin. **PLAT.1+PLAT.2 se pueden adelantar** —dos prompts, ningún contrato tocado— y arreglan por sí solos el 403; merece la pena si el piloto va a tener administradores que no sean superadmin. **Posición en la secuencia sin decidir**: propuesta, después de NIC y antes de REPO |
| **Bloque IDE** — Identidad y permisos: alta manual hoy, grupos del IdP mañana | — | IDE.1 | Opus (IDE.1, .2, .3, .5) · Sonnet (IDE.4) | ✅ **Completo (2026-08-22)** — los 5 prompts. Fue ANTES de Deploy (decisión del usuario, 2026-08-22), después de PLAT.1 y PLAT.2. Planificado el 2026-08-22 al preguntar el usuario dónde estaba prevista la gestión de usuarios. La respuesta era **en ningún sitio**: `grep` sobre `planificacion/` no encuentra nada en Fase 1, 2 ni 3. 5 prompts. **Lo que quiere el usuario**: dar usuarios con roles a mano y que el SSO solo identifique, y **en el futuro** que los permisos vengan del ERP por un atributo del IdP. **Medio mecanismo ya está construido**: `resolve_role` resuelve el rol desde la aserción con tres niveles (`SAML_ATTR_ROLE` → `SAML_GROUP_ROLE_MAP` → `SAML_DEFAULT_ROLE`), los grupos viajan en el claim `groups` del JWT, y **ya tienen consumidor en producción** —el modo `restricted` de un chatbot cruza `allowed_saml_groups`—. **Dos huecos exactos**: (1) `_provision_sso_user` hace `sso.role = role` **sin condición**, así que un rol puesto a mano lo pisa el siguiente inicio de sesión —no falta la pantalla, es que no serviría—; (2) `HubModuleGrant.subject_id` es siempre una persona. **La decisión que unifica ahora y futuro** (usuario, 2026-08-22): declarar **quién es la autoridad** del rol (aplicación o IdP) y que el sujeto de una concesión pueda ser **persona o grupo**, con la semántica de `assert_chatbot_access` —rol o grupo, y el vacío es «nadie», no «todos»—. **El grupo entra desde el principio, también en la interfaz** (decisión del usuario): dejarlo para después convierte el paso al ERP en una migración en vez de un cambio de pantalla. Dos cosas que el bloque **no** hace, a propósito: unificar las cuatro tablas de identidad (`user_to_uuid` está en la propiedad de los workspaces, en los PAT y en las concesiones, y `es_propietario` ya acepta las dos formas desde SEC.8.1 — merece bloque propio con inventario antes de tocar), y repartir un IdP entre varias organizaciones (`SAML_ORGANIZACION_ID` asocia el IdP a **una**). **Prerrequisito del usuario para IDE.5**: qué grupos declara hoy el IdP institucional y cuáles sirven para repartir módulos |
| **Bloque REPO** — Sustituir el repositorio de GitHub por uno sin objetos huérfanos | — | REPO.1 | — (lo ejecuta el usuario) | ⏳ **Pendiente, y va DESPUÉS de NIC.5 por decisión del usuario (2026-08-21)**: no tiene sentido montar el repositorio definitivo y acto seguido meterle la retirada de 500 ficheros de legacy. El historial se reescribió el 2026-08-21 para sacar `logs/` (45 volcados con datos de usuarios reales) y se forzó el push, así que los commits viejos quedaron **inalcanzables pero no borrados**: GitHub los sirve por URL de SHA hasta que recoge basura. Hay que hacerlo **antes de que exista el primer fork**. Inventariado lo que se pierde: 0 issues, 0 PRs, 0 releases, 0 tags, 0 webhooks, ningún secreto de Actions, sin protección de rama — sólo la fecha de creación y el historial de runs. Incluye REPO.2: retirar dos repositorios previos ajenos al proyecto (detalle fuera del repositorio, en `_local/`). Pasos completos en `Plan_TDD_Fase1.md` §Bloque REPO |
| **Bloque REG** — La plataforma como registro de actividad IA y servicios hacia fuera | REG.1-REG.9 ✅ | — | — | ✅ **Completo (2026-09-03)**. **REG.1 ✅** contrato `ActividadIAEvent` y tabla `hub_actividad_ia`, con la regla «metadatos sí, payloads no» fijada por test y dos desviaciones documentadas (sin `__ambito__` y sin FK: es el patrón de los modelos operacionales, no lo que pedía el prompt); migración `28d7fafbf4af`. **REG.2 ✅** `POST /api/v1/actividad`, con la organización derivada del token y `require_pat_scopes` —`require_scopes` deja pasar sesiones JWT a propósito, y aquí eso permitiría fabricar entradas desde el panel—; scopes `actividad:write` y `anonimizacion:use`. **REG.3 ✅** `/anonimizacion/spans` y `/replace` sobre el motor de `redaccion`, stateless y con la regla «el texto no se registra» fijada por un test con centinela a nivel DEBUG; la política por defecto sale del motor y no de una copia en el router. **REG.4 ✅** MCP remoto con transporte streamable HTTP y tres tools; el token es el de cada petición y no hay ninguno en el entorno del servicio, con test de dos clientes concurrentes; imagen, servicio `mcp` en el compose de la VM y ruta `/mcp` en Caddy declarados, **sin desplegar**. **REG.5 ✅** lectura paginada y exportación CSV por sesión JWT, acotadas por organización y con desempate por `id` para que paginar no repita ni pierda filas. **REG.6 ✅** pantalla del registro en el panel con módulo propio `registro` (migración `3a9c1e77b402`) y `docs/REGISTRO_ACTIVIDAD_IA.md` con el mapeo a OTel GenAI. **REG.7-REG.9 ✅** (añadidos el 2026-09-04, tras preguntar el usuario si hace falta documentar el contrato o MCP ya lo intercambia): la firma de la tool declara los ocho campos con descripción y un guardarraíl impide que se separe del contrato; catálogo de categorías en `hub_vocabulary_terms` con el eje `categoria_dades`, que **se anuncia y no se impone**; y el rechazo del contrato explica la regla y señala `payload_hash` en vez de decir «campo no permitido». Migración `4b1d8e29c7f3`. **Bloque completo y sin desplegar.** Planificado, planificado el 2026-08-31 y va DESPUÉS del Bloque Deploy (D)**: REG.4 (MCP remoto streamable HTTP) solo existe con el servidor accesible desde fuera. Origen: reunión con desarrollo del 2026-08-31, valoración en `docs/EVOLUCIO_I_ASPECTES_PENDENTS.md`. 6 prompts: contrato+tabla `hub_actividad_ia`, `POST /api/v1/actividad` con scopes PAT nuevos, anonimización como servicio (`/spans`, `/replace`), MCP remoto con token por petición, lectura+export CSV, vista admin+`docs/REGISTRO_ACTIVIDAD_IA.md`. Reglas duras: metadatos sí payloads no (`extra="forbid"`), el texto a anonimizar no toca logs ni BD, todo `Deploy: edge`. La otra propuesta de la reunión (BD vectoriales embebidas) quedó **desaconsejada** en la misma valoración. Prompts en `Plan_TDD_Fase1.md` §Bloque REG |
| **Bloque VAS** — Verificaciones como servicio: citas, vigencia y auditoría estática por API | VAS.1-VAS.4 ✅ | — | — | ✅ **Completo (2026-09-04)**. **VAS.1 ✅** scope `verificaciones:use` y `POST /verificaciones/citas`; el cuerpo del contrato se movió a `aplicar_contrato` y `enforce_citation_contract` delega, así que no hay segunda implementación y el test de paridad lo fija. **VAS.2 ✅** vigencia acotada por tenencia con el aviso byte a byte del grafo; **destapó que `PatService._orgs_del_dueno` resolvía las organizaciones sólo por `partner_id`, así que un PAT de administrador se quedaba sin organización y `POST /actividad` de REG.2 respondía 403 a todo integrador real** — arreglado con cuatro tests que no sobreescriben el principal. **VAS.3 ✅** auditoría estática con evento de registro y la caja de herramientas leída de los `frozenset`. **VAS.4 ✅** las cuatro tools MCP con firma tipada y el guardarraíl anti-deriva ampliado; **destapó que el MCP remoto servía una sola llamada por proceso** porque cerraba su pool en el ciclo de FastMCP, que con `stateless_http` corre por petición. **Bloque completo y sin desplegar.** Planificado, planificado el 2026-09-02; va DESPUÉS del Bloque REG** (consume sus scopes, su evento y su MCP remoto); independiente de FUN, PLG, DIN y PRC. Origen: `docs/GOVERNANCA_PER_API.md` §4, los **tres candidatos de coste bajo** que ya existen como función interna y solo necesitan superficie, para que «la UADTI desarrolla fuera con registro por API dentro» sea literal. **4 prompts**: VAS.1 scope `verificaciones:use` + `POST /verificaciones/citas` (envuelve `enforce_citation_contract`, test de paridad con el motor); VAS.2 `GET /verificaciones/vigencia` por `document_id` o URL, acotado por tenencia y `MetadataFilter()` cerrado (404, no «no validado»), aviso byte a byte el del CoreGraph; VAS.3 `POST /verificaciones/codigo` (el `AuditResult` del `ScriptSecurityAuditor` tal cual, **evento REG con `code_sha256` y nivel de riesgo**: es la revisión posterior del nivel 2 de la Instrucció 02/2026 para código que corre fuera) + `GET /verificaciones/codigo/reglas` con la caja de herramientas **leída de los frozenset del auditor** y `version_auditor`; VAS.4 tools MCP y documentación (las tres filas de GOVERNANCA_PER_API pasan de candidato a hecho). Reglas: sin segunda implementación; el texto y el código no se guardan (solo hash); solo la auditoría registra evento. Los otros tres candidatos del documento siguen sin planificar. Prompts en `Plan_TDD_Fase1.md` §Bloque VAS |
| **Bloque DIN** — Secciones parametrizables y ciclo de vida de la ingesta automática | DIN.7 ✅ (2026-09-17) | — | — | ✅ **Completo (2026-09-17)**, los 7 prompts, con el ciclo verificado de verdad contra un portal controlado. **Planificado el 2026-08-31; independiente del Deploy** (todo es edge) y **no depende de decidir ningún apartado**: los crea quien cura. Origen: reunión con desarrollo («jornadas/eventos deberían alimentar el chatbot sin curación manual») + corrección del usuario: **los apartados se parametrizan como secciones dentro del proceso de curación, no se fijan**. La revisión enseñó que la premisa era **falsa en dos tercios**: rastreo con cadencia (RAS.5), auto-ingesta de nuevas con `auto_ingest_new=True` (9Q.7, default `True`) y reingesta de cambiadas (RAS.5 paso 3.bis) ya existen y corren en el APScheduler. **7 prompts**: `HubWebSection` con herencia sitio→sección (nulo hereda), rastreo por sección con **censo acotado**, API+UI de parametrización con prueba del patrón, auto-retirada con salvaguarda del 30% del ámbito, puerta de hallazgos bloqueantes, diario por pasada, y ciclo completo verificado + `docs/SECCIONES_DINAMICAS.md`. **La trampa que el bloque evita**: `site_crawler.py:232` compara contra las páginas de TODO el sitio, así que una pasada de sección completa declararía baja el resto del portal — y con auto-retirada, vaciaría corpus (es la lección de `is_census()` del corpus normativo). Principio conservado: *curación una vez, automatización después*; `mode` nace en `manual` a propósito. Valoración 3 en `docs/EVOLUCIO_I_ASPECTES_PENDENTS.md`. **Lo que el bloque destapó y no estaba en el plan**: (1) el job de calidad **nunca confirmaba su sesión** —sólo `flush`—, así que la retirada de DIN.4 contaba 1 y el documento seguía en el corpus, y el `quality_score` y las supersesiones de **9Q.5 se perdían desde entonces**; (2) el arranque le pasaba un repositorio de selecciones **nulo** y `watcher=None` con dos puertas cerradas, así que **la auto-ingesta de páginas nuevas de 9Q.7 no había corrido nunca en producción**; (3) el alta de sitio no mandaba `organizacion_id`, de modo que un administrador de organización **no podía crear un sitio desde la interfaz**; (4) una sección homónima devolvía 500 en vez de 409. Los cuatro con test. **Suite completa al cerrar: 4648 passed, 1 skipped, 0 fallos** (11 m 15 s desde Git Bash); frontend **761 passed** con `--no-file-parallelism`; `tsc -p tsconfig.app.json` limpio; `ruff check app/` limpio; dos migraciones aplicadas (`4ac6ff057736` secciones, `53bbc4c5d4c5` `section_id`, `aff38fa79582` diario) y `alembic check` sin diferencias. Sin desplegar. Documentado en `docs/SECCIONES_DINAMICAS.md` y en `docs/ESPECIFICACIONES.md` §5.11 (`construido`) |
| **Bloque DOM** — El dominio institucional sirve lo público | DOM.5 ✅ | — | — | ✅ **Completo (2026-09-02)**, el día que apareció el registro A, el día que apareció el registro A. Planificado el 2026-09-01 y **rehecho el 2026-09-02**: eran 4 prompts y son **5**. Origen: pregunta del usuario de si el bucket estaba en la misma IP —no: lo sirve la infraestructura de Google, siete IPs rotando— y si el subdominio podía servir también el buscador. De las tres formas (proxy en Caddy, segundo subdominio con segundo certificado, o balanceador HTTPS a 18-25 €/mes) se eligió la primera. **Por qué se rehizo**: la primera versión decidió a propósito **no mover el panel** (dominio sólo para lo público, panel en el nombre provisional) para no tocar el frontend; al resolver el DNS, lo primero que servía `normativa.uji.es` era **el login**, y el usuario pidió lo contrario — portada en la raíz, login bajo ruta propia. Medido antes de replanificar, mover el panel sale barato: **una sola** navegación absoluta en todo el frontend (`LoginPage.tsx:96`, y va a la API), la vuelta del SSO ya es configuración (`SAML_FRONTEND_RETURN_URL`) y el widget se compila aparte, así que un `base` no le afecta. Y aparece una **simplificación**: con el panel bajo prefijo, **los dos nombres sirven lo mismo con un solo fragmento** de rutas — el plan anterior necesitaba dos sólo porque el panel ocupaba la raíz. **El reparto, decidido por el usuario el 2026-09-02**: `/` la portada pública del corpus (la del bucket, ampliada por el pipeline de curación), `/cercador` y `/gerencia` las dos direcciones cortas, `/html/<norma>.html#art-63` **sin cambiar de forma**, `/api/*` y `/health` la aplicación, y **`/panel/` el panel y su login** — `/panel` y no `/plataforma` porque el panel ya tiene una sección interna con ese nombre (PLAT.2) y quedaría `/plataforma/plataforma/modelos`. **Un hallazgo que obliga a una línea**: la raíz del bucket devuelve 200 con el **listado XML de todos sus objetos**, porque el mapeo de `/` a `index.html` es configuración de sitio web de GCS y eso pide el balanceador que el bloque evitó; sin `rewrite / /index.html` el dominio publicaría el inventario. **Dos cosas medidas que corrigieron el plan original y siguen valiendo**: la credencial de sitio **sigue siendo necesaria** (sin `X-Widget-Key` el chat da 401 aunque el chatbot sea `public_anon`) y **CORS no se cierra** mientras la URL del bucket siga pública. **5 prompts**: DOM.1 el reparto en Caddy (✅), DOM.2 el panel bajo `/panel/` sin literales en el código (Opus: toca compilación, router y nginx a la vez), DOM.3 las citas y los orígenes al dominio (variables del repositorio, no ficheros), DOM.4 la portada ampliada y la republicación de las 313 páginas, DOM.5 despliegue, verificación en navegador y decisión sobre el nombre provisional. **Queda fuera**: dominio y sitio de corpus por organización —hoy es un despliegue, un dominio, un sitio, porque `CORPUS_SITE_BASE_URL` es global y `HubOrganizacion` no tiene campo— y no es urgente: sería una columna anulable con la cascada existente |
| **Bloque USR** — Contraseña local para las personas, hasta que llegue el SSO | USR.11 ✅ | — | — | ✅ **Completo (2026-09-03)**: los 7 prompts planificados **más los 3 arreglos** que el usuario pidió antes de seguir **y USR.11**, que pidió al preguntar si esto afectaba a producción. **USR.11 ✅** el contrato de citas normaliza el contenido en la entrada: era el último sitio del camino de la respuesta que lo leía como si siempre fuera cadena, y con `sources` vacías devolvía la lista incumpliendo su firma. **USR.10 ✅** «no tienes ningún módulo» dejó de salirle a quien sí los tiene: sin ninguno se sigue redirigiendo, y con módulos y sin éste la dirección no cambia y se dice lo que es. **USR.9 ✅** la pantalla de Personas sale del módulo `plataforma` a un módulo propio y su listado se abre a quien administra una organización, acotado por tenencia, con el reparto de acciones dicho por el servidor —crear, cambiar roles y borrar siguen siendo de plataforma—; migración `c8f1b5d92e47`. **USR.8 ✅**: el asistente agéntico perdía **todas** sus conversaciones —0 interacciones registradas frente a 33, 9 y 1 de los de RAG— porque `"".join(collected_tokens)` reventaba con el `content` en bloques de Gemini, y como el tramo de después del bucle estaba **fuera de todo `try`**, el cliente no recibía ni `error`: se quedaba esperando para siempre. Tercera mordida del mismo problema, así que `texto_de` pasa a desenvolver el mensaje entero (los ocho sitios de llamada ya no tienen ocasión de equivocarse) y un guardarraíl prohíbe la forma que falla. Lo demás del bloque, los 7 prompts: Planificado el 2026-09-01; no depende de Deploy ni de REG/DIN.** Lo pide el piloto: los probadores de Gerencia y de la plataforma tienen que entrar antes de que el IdP de la UJI esté configurado, y eso no tiene fecha. Origen: pregunta del usuario («hasta que no tengamos configurado el SSO puedo habilitar usuarios con contraseñas?»); la respuesta medida contra el código fue **no**, porque `hub_users` no tiene columna de contraseña y sus identidades solo pueden venir del ACS de SAML. **Y NO se arregla dando rol de administrador**, que fue la primera idea: `AdminAccount.partner_id` es la clave primaria y las organizaciones se enlazan por `HubOrganizacion.partner_id`, así que solo la fila con `partner_id='uji'` ve los asistentes de la UJI y cinco probadores serían cinco filas de las que cuatro no verían nada — se degrada a **una credencial compartida**, sin atribución por persona (que es lo que necesita el Bloque RHR) y con poderes de panel completos. **El bloque es pequeño porque IDE.3 ya hizo el alta manual**: `POST/PATCH/DELETE /hub/users` y `UsuariosPage.tsx` existen, y `assert_chatbot_access` ya abre un chatbot `authenticated` a cualquier actor de su organización (no hay ningún `restricted` en producción, así que no hace falta ningún grupo de SAML). **5 prompts**: columna + `PATCH /hub/users/{id}/password` (admin sobre su organización, no solo superadmin), `POST /auth/user/login` con las tres defensas de SEC.1/SEC.4 copiadas a conciencia, panel (tercer intento en `LoginPage` + acción en `UsuariosPage`), verificación en navegador **de los límites** (que un probador no vea plataforma ni otra organización), y la unicidad de `AdminAccount.email`, defecto latente encontrado el 2026-09-01 y barato hoy porque la tabla está vacía. **`LOCAL_USER_LOGIN_ENABLED` (defecto `true`) para poder apagarlo** cuando llegue el SSO: sin interruptor, «hasta que llegue el SSO» se convierte en «para siempre». **Ampliado el 2026-09-01 a 7 prompts, a petición del usuario**: **USR.6** (Opus) el alta manual de cuentas de administración —hoy no hay **ningún** endpoint que cree un `AdminAccount`, solo `seeds.py` y `bootstrap.py`— y sobre todo la decisión de fondo de que **varias personas puedan administrar la misma organización**, que hoy no es representable; se recomienda que `HubUser` con `role='admin'` pase a ser la identidad de administración y que `AdminAccount` se quede con el partner y la facturación, que es la dirección que el propio docstring de `HubUser` señala, en vez de una tabla puente que consolidaría las cuatro tablas de identidad. **USR.7** (Sonnet) cambiar la propia contraseña, que **no existe en ningún rol** de gestión |
| **Bloque LANG** — Política de lengua configurable: monolingüe y respuesta fija | LANG.2 ✅ | — | — | ✅ **Completo (2026-09-03)**, los 2 prompts. `cfg.language_mode` decide ya la política que compone la factoría (`none` reutiliza `NeutralLanguagePolicy`, `fixed:<código>` es nueva y hereda de `prefer` cambiando solo `detect`), el valor se valida con 422 desde `core/language_mode.py`, y el panel ofrece los modos y los idiomas desde `GET /hub/opciones/lengua` —con el código del corpus, `val` y no `ca`—. De paso se retiraron dos opciones que el panel ofrecía y no funcionaban: `strict`, que la factoría nunca compuso, y `neutral`, que no es ningún valor. Planificado, planificado el 2026-09-01; independiente de Deploy, 2 prompts.** Origen: pregunta del usuario («¿grafo sin selector de idioma para ayuntamientos no multilingües?»). Medido contra el código: la política de lengua es una estrategia del CoreGraph y sobre corpus monolingüe degrada sola a passthrough — pero **`language_mode` viaja por toda la cascada (plataforma→organización→chatbot→config efectiva) y nadie lo consume**: la factoría monta siempre `DefaultLanguagePolicy` (`graph_factory.py`), el `"none"` documentado en `metadata_filter.py` no tiene ningún `if` que lo lea, y el modo «responde siempre en X, pregunten como pregunten» no existe. LANG.1 cablea `none` y `fixed:<lang>` como políticas del protocolo existente + validación del valor (hoy `String(20)` libre: un typo cae a `prefer` sin avisar); LANG.2 el desplegable en el panel con el catálogo de modos venido del contrato. Conviene antes del primer despliegue monolingüe. Prompts en `Plan_TDD_Fase1.md` §Bloque LANG |
| **Bloque BD** — Una sola fuente para el esquema de la base de datos | BD.2 ✅ | — | — | ✅ **Completo (2026-09-04)**, los dos prompts. **BD.2 ✅** retiró la creación del esquema en el arranque, puso `alembic check` en CI, endureció las tres columnas y —en la primera ejecución del guardarraíl— destapó y corrigió **siete diferencias más entre la cadena y los modelos que producción tenía y desarrollo no**, una de las cuales borraba interacciones en silencio al borrar un chatbot. Sin desplegar. Nacido de una pregunta del usuario al cerrar NIC: si la retirada del NiceGUI dejaba tablas colgando. **BD.1 ✅** censó `govgenai` —88 tablas, 51 declaradas, **36 sin dueño y vacías**, residuo del «Brain» de AutomatIA—, comprobó producción en solo lectura (51, cero huérfanas) y las retiró con `5c2e9f4a1b76`; la única diferencia que queda con producción es `hub_actividad_ia`, de REG, sin desplegar. **BD.2** cierra la causa: el esquema lo gobernaban **dos mecanismos** —Alembic en el despliegue y la creación desde el metadato en cada arranque—, y la segunda no aporta nada (la cadena sola produce las 51) pero nunca borra. Se quita, `alembic check` entra en CI, y se endurecen las **tres columnas** que ya divergían (`created_at`/`updated_at` nullable en migración, NOT NULL en modelo; cero nulos en dev y en prod), anotadas y aplazadas por REG.1 y USR.1. Prompts en `fase1/73_BLOQUE_BD.md` |
| **Bloque DEP** — Las dependencias vulnerables, medidas y no supuestas | DEP.7 ✅ (2026-09-15) | — | — | ✅ **Completo, los 7 prompts (2026-09-15)**, con su ejecución real en `desarrollo`. Nace el 2026-09-08 de la **primera ejecución del job `supply-chain`** —32 avisos en `server`, 4 en `mcp_server`, 21 en el frontend con 13 altos—, no de una sospecha. **DEP.1 ✅** saca `browser-use`, `ragas` y `datasets` a extras y el árbol del servidor pasa de **408 a 189**; lo que de verdad destapó fueron **cuatro paquetes usados y no declarados** que llegaban de rebote como transitivas suyas (`python-multipart`, `langchain`, `beautifulsoup4` y `langchain-community`), y por eso entra `test_dep1_no_hay_dependencias_de_rebote.py`. **DEP.2 ✅** sube 14 paquetes uno a uno, con `cryptography` cruzando cuatro mayores. **DEP.4 ✅ (2026-09-10)** sube `camelot-py` a 2.0 y con ello **`pypdf` desaparece del árbol entero** —acumulaba 30 avisos, más que ningún otro paquete, y parsea PDF que vienen de fuera, que es la superficie que un atacante elige—; base del servidor **199 → 197**. La comprobación que valía no era la suite: sobre **20 PDF reales** del corpus, 18 idénticos y **2 distintos, y en los dos la versión vieja era la equivocada** (una cabecera de dos niveles que la 1.0.9 colapsaba, y una portada de 28×2 que no era tabla). Sobre 60 PDF: 24 documentos con tabla, 25 tablas, cero errores. Deja anotado un defecto **no** arreglado ahí, que es de código y no de dependencias: el filtro del pipeline descarta tablas de menos de 2 columnas y esa portada pasaba con exactamente 2, una vacía del todo. **DEP.5 ✅** deja `mcp` en 1.30 con techo `<2` **en el manifiesto**. **DEP.6 ✅** descubre cuatro herramientas de construcción en `dependencies`: reclasificarlas, sin subir nada, quita 16 de los 21 avisos, y el árbol de producción del frontend queda en **cero**. **DEP.3 ✅ (2026-09-15)** sube `starlette` 0.50.0 → 1.6.0 —`fastapi` 0.136.0 pide `>=0.46.0` **sin techo**, así que sube solo y el diff del lock son 3 líneas— y **sus 5 avisos desaparecen** (PYSEC-2026-161, -248, -249, -2280, -2281; 1.6.0 sale «No known vulnerabilities found»). **Su premisa era falsa y eso es lo que hay que recordar**: `app.routes` sigue plano y los 14 tests que enumeran rutas pasan, así que no se reescribió ninguno. Lo que la subida sí destapó, y se arregló aquí, son **dos constantes deprecadas usadas 15 veces en 7 ficheros** (`HTTP_422_UNPROCESSABLE_ENTITY` → `..._CONTENT`, `HTTP_413_REQUEST_ENTITY_TOO_LARGE` → `HTTP_413_CONTENT_TOO_LARGE`): mismos valores numéricos, contrato idéntico, y sin ellas el próximo mayor de starlette rompe la app. **DEP.7 ✅ (2026-09-15)** enciende la puerta, y su criterio **no es el que el prompt proponía**: «bloquear en `high` y `critical`» no se puede, porque **`pip-audit` no informa de severidad**. Bloquea lo que **tiene corrección publicada y no está aceptado** en `avisos_aceptados.toml` —dato que la herramienta sí da, y que además es la pregunta que decide si quien lee el rojo puede hacer algo—; `npm audit`, que sí trae severidad, bloquea en `high` sobre producción, medida en cero antes de encenderlo. **Antes de encender se midió y se limpió**: había **10 avisos en 5 paquetes, todos con corrección**, aparecidos después de DEP.2; se subieron cuatro (`langsmith` 0.6.4→0.12.4, `langchain-classic` 1.0.4→1.0.8, `pydantic-settings` 2.14.0→2.15.0, `soupsieve` 2.8.1→2.9.2) y el quinto, `setuptools`, **no se puede subir**: `torch` 2.11.0 declara `setuptools<82` y la corrección está en 83.0.0 — es la única entrada del fichero de aceptados, con motivo, responsable y caducidad al 15-12-2026. **10 tests nuevos**, dos casos negativos y **8 mutaciones del job comprobadas**. Prompts en `fase1/74_BLOQUE_DEP.md` |
| **Bloque IMG** — Que CI construya la imagen y la arranque | IMG.1 ✅ (2026-09-17) | — | — | ✅ **Completo (2026-09-17)**, un prompt, **verde en CI** (run `35214706322`) **y con el caso real reproducido en rojo**. Nace el 2026-09-15, el mismo día en que el hueco tumbó producción 35 minutos: **el conjunto de dependencias que se despliega —base, sin extras— era el único que no probaba nadie**. El job `imagen` construye las cuatro imágenes con los `Dockerfile` del despliegue, migra con la recién construida y **la arranca** hasta `/health` 200, con `ENVIRONMENT=production`; el cliente de la API lo hereda del job `contract` en vez de reinstalar uv y node. Guardarraíl: `test_img1_ci_construye_y_arranca_la_imagen.py`, que **lee de `deploy.yml`** qué imágenes y qué `Dockerfile` usa el despliegue en vez de copiarlos. **Cinco mutaciones comprobadas una a una, y la cuarta se quedó VERDE en la primera versión**: preguntaba si había un `docker run` y el paso de migraciones ya ejecuta uno, así que quitar el arranque de la aplicación no se notaba — ahora pregunta por `docker run -d` de una etiqueta construida aquí. **2 min 45 s en CI** (construir las cuatro 111 s, migrar 4 s, arrancar y servir 12 s) y **no es camino crítico**: `contract` 3,33 + `imagen` 2,75 = 6,1 frente a los 7,87 de `Lint & Test`, así que sale gratis en reloj de pared — **la medida local decía 5,6 min y sobreestimaba por casi el doble**. **El caso real reproducido**: sin `uvicorn` en el manifiesto (sólo llega por el extra `agente-navegador`), la imagen **construye** y `docker run -d` da **rc=127** con `executable file not found in $PATH`, el mensaje del incidente palabra por palabra. Detalle en `fase1/75_BLOQUE_IMG.md` |
| **Bloque PLG** — Perfiles, estrategias y pipelines de recuperación descubiertos por *entry points* | PLG.3 ✅ (2026-09-16) | — | Opus (PLG.1 y PLG.2) · Sonnet (PLG.3) | ⏳ **Pendiente, planificado el 2026-09-02 y ampliado el mismo día con las estrategias; independiente de Deploy, REG, DIN y FUN; conviene DESPUÉS de LANG** (toca la misma factoría de perfil). Origen: el correo de desarrollo del 2026-09-02 pidiendo plugins previstos de inicio; respuesta: **sí al descubrimiento, no a congelar los protocolos** (declarados 0.x hasta el primer tercero real). **3 prompts**: PLG.1 grupos `govgenai.graph_profiles` y `govgenai.retrieval_pipelines`, cargador que falla en alto ante duplicados o factorías que no cumplen el contrato, retirada del enum `PublicGraphProfile` (los nombres son cadenas validadas contra el registro), `retrieval_pipeline_factory` de cadena de `if` a registro, validación de perfil y modo en los routers de chatbots y organizaciones, fixture de paquete demo y la **decisión de empaquetado medida** (el servidor no está instalado como paquete en el venv, así que sus propios entry points no serían visibles: si hacerlo instalable cuesta sólo `[build-system]`+relock, el núcleo se declara por entry points; si no, registra por código a través del mismo cargador y se documenta). **PLG.2 (nuevo, Opus) estrategias por eje**: `StrEnum` de cuatro ejes (retrieval, merge, template, language; el bucle agéntico no es eje, candidato), protocolos `@runtime_checkable`, `StrategyRegistry` con el núcleo registrando por el mismo camino, grupo `govgenai.strategies` (`<eje>.<nombre>`) verificado al arrancar contra el protocolo del eje, el perfil operativo compone **por nombre** (test de regresión: mismas cuatro clases), columnas `HubOrganizacion.default_estrategias` y `HubChatbot.estrategias` JSONB **heredables clave a clave** con migración, sobreescritura aplicada en `GraphFactory.build` (misma capa que rewrite_llm y agentic_loop), nombre no registrado falla en alto, validación 422 en routers, y la traza ya lo registra por valor. PLG.3 endpoint de opciones de grafo (perfiles con composición, modos, estrategias por eje) y el panel sin literales, con un select por eje y «heredar» por defecto (regla maestra 1). Prompts en `Plan_TDD_Fase1.md` §Bloque PLG |
| **Bloque FUN** ✅ **Completo** — Catálogo de funciones deterministas versionadas y compartidas, con doble origen: el canal del nivel 2 de la Instrucció 02/2026 | FUN.7 ✅ (2026-09-18) | — (bloque completo) | Opus (FUN.2, FUN.3, FUN.4 y FUN.5) · Sonnet (resto) | ✅ **Completo (2026-09-18)**, los 7 prompts, cada uno con su fichero de tests (`test_fun1_catalogo` … `test_fun7_el_catalogo_documentado`) y FUN.7 dejando `docs/CATALOGO_FUNCIONES.md` con la sección «Empaquetar una función». **Esta celda decía «▶ En curso» hasta el 2026-09-26 mientras la cabecera de su propia fila decía «✅ Completo»**: de ahí salió la issue #7, abierta ocho días sobre trabajo entregado. Una fila que se contradice a sí misma es peor que una desactualizada, porque quien la lee escoge. Planificado el 2026-09-01 y revisado dos veces el 2026-09-02 (doble origen; alineación con la Instrucció 02/2026 de desarrollo ciudadano governat). FUN.1–FUN.5 independientes de Deploy; FUN.6 DESPUÉS del Bloque REG** (consume su registro de actividad y su patrón de scopes). **Segunda revisión**: el catálogo no está pensado para desarrolladores profesionales sino para **gobernar el desarrollo ciudadano**; el nivel 1 (uso personal) vive fuera de la plataforma y **la plataforma entra en el nivel 2**: registrar una función ES declararla y compartirla. Por eso registrar = declaración responsable + AST sin CRITICAL + sandbox, **automáticos y con uso inmediato**; **sin aprobación humana previa** (la Instrucció la prohíbe como condición para compartir); **revisión posterior** con muestreo, correcciones, reclasificación y **suspensión** (de quien revisa; retirar es del autor); aprobación previa **solo** para el paso a nivel 3 (promoción con valoración del superadmin); el registro **acepta código escrito fuera** (autoría ia|persona); el auditor AST es **la caja de herramientas** de la Instrucció y sus reglas se contrastan con las Guías Operativas Técnicas de la UADTI. Estados de versión: draft/registrada/suspendida/retirada/no_instalada. FUN.4 pasa a Opus (máquina de estados por rol). Origen: la observación de desarrollo («generador, no framework») releída sobre los scripts deterministas, donde **acierta**: el código aprobado **se incrusta copiado** en el bloque de cada plantilla (`scripts_router.py:555-560`) — dos plantillas con la misma extracción son dos copias y dos aprobaciones, y un bug se arregla N veces; `HubScriptProposal` es cola, no catálogo. La segunda observación («ese código tiene que estar en manos de quien lo define, versionado y testeado en su repositorio») acierta para el autor desarrollador y no para el informador sin repositorio: de ahí el **doble origen** — *autoservicio* (código en el catálogo, IA+AST+sandbox+aprobación, anclaje exacto por construcción) y *empaquetado* (código en el repositorio del equipo, *entry point* `govgenai.funciones`, semver con anclaje por mayor, in-process con la confianza en quien instala). Lo que centraliza la plataforma en ambos es revisión, `RunManifest`, trazabilidad y contrato, no el código. **7 prompts**: `HubFuncion`+versiones con `origen` (`__ambito__="heredable"`, versión aprobada inmutable, `code_sha256`), contrato E/S declarado y validado ANTES del sandbox con un solo validador para ambos orígenes (los parámetros con la forma de `UIFieldDescriptor`: el SDUI pinta el formulario gratis), **referencia `funcion_id@versión` en vez de copia** con migración de las plantillas existentes y anclaje (publicar v2 NO cambia ninguna plantilla anclada — el test más importante del bloque), promoción a plataforma con aprobación del superadmin + catálogo en el panel (acciones desde el DTO), **FUN.5 origen paquete** (sincronización al arrancar que falla en alto con contrato incoherente, `no_instalada` al desinstalar, fixture de paquete demo), `POST /api/v1/funciones/{id}/run` con scope `funciones:execute` y evento REG, y verificación e2e + `docs/CATALOGO_FUNCIONES.md` con la sección «Empaquetar una función» para el primer equipo externo. **Diseñado como pieza compartida**: en Fase 3 las fases de expediente referencian `plantilla@versión` y `función@versión` — restricción escrita el mismo día en `Plan_TDD_Fase3.md` (retirado `ejecuciones_accion.codigo_ejecutado`, que duplicaba sandbox+auditoría+aprobación). Se comparte código y contrato, nunca datos; la cadena AST+sandbox+HITL no se relaja. Prompts en `Plan_TDD_Fase1.md` §Bloque FUN |
| **Bloque PRC** — El catálogo de procedimientos entra al asistente de normativa (**replanificado el 2026-09-04**: sólo lo que afecta a ingesta y recuperación entra en la plataforma; `id_ficha` retirado, `tipus_document` como vocabulario con la clase de autoridad como estructura, y los literales institucionales fuera del código. **PRC.0 y PRC.1 se ejecutan en el repositorio `normativa-uji`**, donde ya vive `cataleg_procediments/`; aquí sólo su línea de historial) | — | PRC.0 | Opus (PRC.2 y PRC.5) · Sonnet (resto) | ⏳ **Pendiente, planificado el 2026-09-02. BLOQUEADO por dos prerrequisitos externos: las fichas del catálogo validadas por los servicios** (revisión en curso: 363 fichas, 206 con banderas, 28 citando normas derogadas — `Descarregar_pdf/normativa_propia/cataleg_procediments/`) **y la consulta de descarga del dataset que debe habilitar el equipo del catálogo** (contrato decidido el 2026-09-02: **estado completo, no deltas por horas** — un filtro por fecha no expresa bajas, exige contabilidad de la última pasada exitosa y depende de fechas que mienten; HTTPS con token, solo validadas, `generated_at`+`total` con completitud verificada, ID estable, bajas explícitas si puede ser; el incremento lo da el hash en destino; petición textual en la Qüestió 6 del informe). Origen: valoración de diseño del 2026-09-02 (Qüestió 6 de `docs/EVOLUCIO_I_ASPECTES_PENDENTS.md`): el piloto no contesta procedimiento (servicio, plazos, silencio, canal) porque eso no está en la normativa sino en el catálogo. **Decisión tomada: un solo asistente, no dos chatbots con router** — los usuarios preguntan mezclado y no distinguen; el router clasificaría donde el usuario es ambiguo y los perfiles router/aggregator siguen sin implementar (I5); la pregunta mixta necesita ficha y artículos en el mismo contexto. **6 prompts (PRC.0–PRC.5)**: cliente del dataset con validación del contrato (censo incompleto abortado sin tocar el export anterior), rendido determinista ficha→`.md` del contrato (vive con el proyecto del catálogo, solo fichas VALIDADAS, bilingüe emparejado por `id_ficha`), eje `tipus_document` (`norma`|`procediment`) en filtro e índice agéntico (las fichas NO entran en la vigencia normativa: su frescura es `data_actualitzacio`), marcador de autoridad en la respuesta («segons la fitxa del catàleg, Servei X, actualitzada el …» con `url_fitxa` citable), sincronización reutilizando reconciliador+poda+salvaguarda (pasadas supervisadas primero, scheduler diario después), y recalibración medida con el lote dorado antes/después + escenarios mixtos nuevos. **Ejecutable por tandas** conforme los servicios validan. Decisiones 14-16 del informe pendientes: qué significa «validada», tandas o todo al final, y caducidad de fichas |

## 👉 EMPEZAR AQUÍ EL PRÓXIMO DÍA (actualizado 2026-09-15, tras desplegar LANG+DEP y el incidente)

> 🔥 **INCIDENTE DEL 2026-09-15: producción caída 35 minutos al desplegar. Resuelto, con la causa
> cerrada y el agravante también.**
>
> **Lo que pasó**: el contenedor `app` no arrancó — `exec: "uvicorn": executable file not found in
> $PATH`. `uvicorn` **nunca estuvo declarado** en `pyproject.toml`: llegaba de rebote por
> `browser-use → mcp → uvicorn`, y DEP.1 mandó `browser-use` a un extra. La imagen instala
> `uv sync --frozen --no-dev`, **sin extras**.
>
> **Por qué no lo vio nadie, que es lo que hay que recordar**: CI instala con `--all-extras`, así
> que **el conjunto que se despliega no lo prueba nadie**; el guardarraíl de DEP.1 busca *imports*
> y `uvicorn` no se importa, se invoca; y comprobar que la app *importa* con el conjunto base
> **pasa en verde** — importar funciona, lo que faltaba era el proceso que la arranca. Un
> guardarraíl sólo ve la pregunta que le hicieron.
>
> **Arreglado**: `uvicorn` declarado, y `test_dep8_los_ejecutables_del_dockerfile_estan_declarados.py`
> pregunta lo que faltaba — ¿lo que el `CMD` ejecuta está en las dependencias base?
>
> ⚠️ **Y el agravante, que es la parte cara: duró 35 minutos en vez de 2 porque el paso «Comprobar
> que sirve, y volver atrás si no» no llevaba `if: always()`** y se saltó al fallar «Desplegar» —su
> único momento útil—, dejando el servicio caído **con la reversión preparada y sin ejecutar**. Ya
> pasó el 2026-09-01 y quedó anotado aquí como «merece mirarse». **No se miró.** Dos incidentes, la
> misma línea. Ahora lo lleva y lo fija un test.
>
> **Lo que queda apuntado y no se hizo**: CI sigue sin construir las imágenes, así que el conjunto
> base sólo está cubierto en los ejecutables del `CMD`, no en el arranque completo.


**Hay UN cursor y está aquí.** Hasta el 2026-09-14 este fichero tenía **dos párrafos de cursor que
se contradecían** —uno en esta cabecera diciendo «Bloque REPO, prompt REPO.1» y otro sesenta
líneas más abajo diciendo «Bloque DEP, 4 de 7»—, porque el segundo se añadió al final en vez de
sustituir al primero. Y **ninguno estaba al día**: DEP.4 se cerró en el commit `95ef392` del
2026-09-10 y no constaba ni aquí ni en `HISTORIAL.md`. Si vuelve a hacer falta anotar un cursor
nuevo, **se reescribe este párrafo**; lo viejo baja a «Lo anterior».

**Cursor: Bloque APER — apertura del repositorio. ▶ EN CURSO, 26 prompts cerrados (APER.1–APER.26)**; los trece primeros **desplegados el 2026-09-19** en la PR #27, y de APER.14 a APER.21 están **en `desarrollo`, esperando en la PR #50**. Los cinco últimos salen de la revisión de esa PR.

El bloque empezó con siete prompts y va por veintiséis, y **eso no es desviación: es lo que pasa cuando encender un medidor destapa lo que no medía**. Los diecinueve añadidos, por lo que los trajo:

* **La revisión de Copilot en la PR #27** dio tres hallazgos, los tres ciertos: APER.14, APER.15 y APER.16.
* **Activar Dependabot** destapó en trece minutos que `supply-chain` auditaba **dos locks de cuatro** (APER.9), que sus trece PR eran inmezclables y que sus grupos **rebajaban** versiones (APER.13), y que ninguna podía pasar el DCO porque los commits de robot no van firmados.
* **La puerta de avisos, ya con los cuatro locks, bloqueó la PR del propio despliegue** (APER.11) — y tenía razón.
* **La suite completa del cierre** destapó un *flake* de 1 entre 1024 (APER.10) que el paralelismo escondía, y **la suite rota de `shared` resultó ser el 81% de un paquete muerto de AutomatIA** (APER.12).
* **APER.17** nació de que `pip-audit` **instala** lo que audita y con `torch` no termina: se sustituyó por consultas a OSV por lotes, segundos en vez de cuartos de hora.
* **APER.18** lo pidió el usuario: los modelos locales no se suben en el despliegue por tamaño, pero otras administraciones los querrán, así que el extra se **elige al desplegar** (`EXTRAS_APP`). Su defecto lo encontró el usuario leyendo el diff —la imagen construía una etiqueta y anunciaba otra— y se cerró en APER.18b.
* **APER.19, APER.20 y APER.21** son el tramo de dependencias, y entre los tres llevaron los avisos del lock de **34 a 4**: retirar el agente de navegador quitó 22 **sin actualizar nada**, subir `torch` cerró cinco más —la aceptación de `setuptools` llevaba escrita su condición de salida y se cumplió— y `pytest` y `datasets` cerraron los tres últimos que tenían corrección. Los 4 que quedan **no la tienen publicada**.
* **La revisión de Copilot en la PR #50** dio **diez** hallazgos y ninguno era ruido. Los cinco prompts que salieron de ahí: **APER.22**, que el interruptor de modelos locales de APER.18 **no funcionaba** —`docker build` recibía el valor partido por un espacio— y los seis guardarraíles que lo vigilaban lo daban por bueno porque **ninguno ejecutaba nada**; **APER.23**, tres sitios donde el auditor de avisos confundía «no me han contestado» con «no hay corrección»; **APER.24**, el README publicado de `automatia-shared` describiendo módulos que APER.12 borró; **APER.25**, tres operaciones de disco síncronas en la ruta asíncrona de una petición; y **APER.26**, la exención del DCO escrita como comodín sobre el correo del autor, que lo elige quien commitea. **La lección que se repite en cuatro de los cinco**: un guardarraíl que comprueba que una cadena *esté* en un fichero no comprueba nada. Los cinco nuevos **ejecutan** lo que vigilan.
* **APER.8** se añadió al preguntar el usuario si los `permissions` de los workflows se podían tocar desde el CLI: estaban en el tramo «el día de abrir» por suponer que era trabajo de consola, y resultó ser un cambio en el repositorio, o sea que va con su guardarraíl como todo lo demás.

**Dónde está la seguridad de la cadena de suministro ahora mismo, medido el 2026-09-19**: los cuatro conjuntos que se despliegan (289 paquetes) están a **cero avisos**, y la puerta pasa en verde **sin ninguna aceptación** en `avisos_aceptados.toml`. En el lock quedan 4 avisos, todos fuera del despliegue y **ninguno con corrección publicada** (`diskcache` y `ragas`, dos cada uno). O sea que **no queda ningún aviso corregible sin decidir**, que es el listón que se puede sostener; «cero avisos» no lo es mientras dependamos de paquetes que no publican arreglo.

**Verificación, con las cifras medidas**: la suite completa del servidor pasa —**5.050 tests, 1 saltado, 0 fallos**, 12 min 59 s— ya con `torch` 2.14 y `pytest` 9.1.1. Y CI dio los cinco trabajos en verde sobre el mismo commit, incluido `Lint & Test` con `-n0` y el que construye y arranca la imagen.

**Y una nota sobre cómo se midió, porque costó dos intentos.** El primer lanzamiento de la suite lo mató el sistema por falta de memoria antes de que escribiera una sola línea. La causa no era la suite: son 22 CPUs, el paralelismo por omisión levanta 22 procesos y desde APER.20 **cada uno carga `torch`**. Con seis trabajadores cabe de sobra y nunca bajó de 10 GB libres. Si alguien vuelve a ver ese corte, la respuesta es `-n 6`, no menos tests.

El bloque **no sale de `planificacion/fase1/`**: sale de la auditoría de seguridad y calidad
previa a hacer público el repositorio (2026-09-18), cuyo informe vive en `_local/` porque
describe dónde es débil el sistema. De sus hallazgos, el usuario eligió ejecutar el tramo
«antes de abrir»: **M1** (SSRF del rastreador, APER.1 ✅), **M2** (los dos stubs 501 de
`edge_sync` como superficie sin guardia, APER.2 ✅), **M4** (`ENVIRONMENT` seguro por omisión, APER.3 ✅), el
`npm audit fix` (APER.4 ✅), el bump de `setuptools` en el lock (APER.5 ✅, decidido: se queda en 81 y está razonado), un `dependabot.yml` (APER.6 ✅) y corregir
`docs/AUDITORIA_PRE_DEPLOY.md` (APER.7 ✅), que sigue dando por abiertos hallazgos que los bloques SEC
cerraron. **Ningún hallazgo era ALTO** y no hay nada que impida abrir; esto es el tramo que
conviene cerrar antes de que el código sea público.

**Lo anterior: Bloque IMG ✅ COMPLETO el 2026-09-17**, su único prompt, con ejecución real en CI
**y el caso del incidente reproducido en rojo** (sin `uvicorn` en el manifiesto: la imagen
construye, `docker run -d` da rc=127 y `executable file not found in $PATH`). El job `imagen` construye las cuatro imágenes con los `Dockerfile` del despliegue,
migra con la recién construida y la arranca hasta `/health` 200; su guardarraíl
(`test_img1_ci_construye_y_arranca_la_imagen.py`) lee de `deploy.yml` qué construir, y sus cinco
mutaciones están comprobadas una a una —**la cuarta se quedó verde en la primera versión**, ver
el bloque—. **Ejecutado en CI el mismo día y verde a la primera** (run `35214706322`): **2 min
45 s**, de los que 111 s son construir las cuatro imágenes, 4 s migrar y 12 s arrancar y servir.
**La medida local sobreestimaba por casi el doble** (5,6 min) y con ella se escribió que el job
sería el camino crítico: **no lo es** —`contract` 3,33 + `imagen` 2,75 = 6,1 min frente a los
7,87 de `Lint & Test`—, así que **sale gratis en reloj de pared** y corre en cada push. Lo que
queda es verlo **rojo** con el defecto dentro. Detalle en
[`fase1/75_BLOQUE_IMG.md`](fase1/75_BLOQUE_IMG.md).

**Y desde el 2026-09-17 lo pendiente vive como issues**, no como filas de esta tabla: 24 issues
en cuatro hitos —*Antes de abrir el repositorio*, *Backlog funcional - fase 1*, *Defectos y
deuda*, *Verificación humana*—, a petición del usuario y porque es lo que ve quien llega de
fuera. Los ficheros de `fase1/` siguen siendo el detalle de ejecución y cada issue enlaza al
suyo. `main` tiene además *ruleset* desde ese día: sin borrado, sin *force-push*, PR con
aprobación y tres comprobaciones requeridas, con bypass sólo para el rol `admin`.

## Lo anterior — Bloque DEP

**Bloque DEP ✅ COMPLETO el 2026-09-15**, los 7 prompts, **con su ejecución real en
`desarrollo` hecha** (run `34974628381`).

**Y esa ejecución justificó el criterio que la pedía: encontró tres cosas que ninguna
comprobación local encontró.** (1) La puerta **bloqueó y por la razón correcta** —
`langchain-openai` PYSEC-2026-76, que en local cayó en el trozo declarado como no medido—.
(2) **Un defecto del propio prompt**: al ponerse roja, la puerta saltaba `npm audit`, el SBOM y
**el escaneo de secretos del árbol**; encender una puerta apagaba las otras dos. Arreglado **por
regla** —`if: always()` desde el primer paso bloqueante— y fijado con un guardarraíl que
comprueba por posición. (3) **Un flake preexistente** por estado global de Faker filtrado entre
tests, que sólo aparece en serie: para eso corre CI con `-n0`.

**Lo que DEP.7 dejó montado**, con su criterio decidido el 2026-09-15 contra la propuesta escrita:

- **La propuesta del prompt («bloquear en `high` y `critical`») no era implementable**:
  `pip-audit` **no informa de severidad** —sus entradas traen `id`, `aliases`, `description` y
  `fix_versions`, y nada más—. Un umbral por CVSS habría dejado un hueco silencioso, porque los
  avisos sin severidad no bloquearían nunca.
- **El criterio que se aplica**: bloquea lo que **tiene corrección publicada y no está aceptado**;
  lo que no se puede arreglar informa. Es la misma razón por la que el job nació informando —«un
  guardarraíl rojo por algo que quien lo lee no puede arreglar acaba desactivado»— respetada en
  vez de contradicha.
- **En JavaScript sí hay severidad**, así que `npm audit` bloquea en `high` sobre el árbol de
  producción, que estaba **medido en cero** antes de encenderlo.
- **`avisos_aceptados.toml`** con cinco campos obligatorios, **`scripts/puerta_de_avisos.py`** que
  aplica el criterio, y **10 tests nuevos** —incluidos dos casos negativos y **8 mutaciones del
  job comprobadas una a una**—.

**Y lo que DEP.3 enseñó, que es lo que hay que recordar de él: la premisa era falsa.** El prompt
decía —y este fichero lo repetía— que `starlette` 1.6 «deja de aplanar las rutas en `app.routes` y
mete un `_IncludedRouter` sin API pública», rompiendo 10 tests en 8 ficheros. **No se reproduce.**
Con `fastapi` 0.136.0, `app.routes` sigue plano (198 rutas, todas `APIRoute`/`Route`, todas con
`path`) y **los 14 tests que enumeran rutas pasan**. No se reescribió ninguno: reescribir catorce
tests verdes contra un defecto que no existe es churn. La hipótesis de dónde salía la premisa —el
intento revertido se hizo antes de que DEP.2 subiera `fastapi`— **no está comprobada** y se deja
anotada como tal. Corrobora el diagnóstico que **`mcp_server` ya corría starlette 1.6.0 desde
DEP.5**, sin que nadie notara nada.

**Bloque REPO: REPO.4 ✅ el 2026-09-16 — `CODEOWNERS` pasa de una persona a un equipo.** Catorce
entradas apuntaban a **una sola persona**, incluidas `/server/migrations/`, `/server/app/core/` y
`/.github/workflows/`: un único punto de fallo humano sobre lo que rompe todos los despliegues a
la vez. Ahora es **`@universitatjaumei/gov-gen-ai-platform-maintainers`**, creado con los cuatro
que ya tenían admin sobre el repositorio.

**Y el inventario del prompt se quedó corto**: decía seis sitios y eran **siete** —aparecieron
`frontend/package.json` y `pruebas_manuales_bloqueAIS.bat`, escritos después del 07-09—. En
cambio `docs/DESPLIEGUE_PROTOTIPO_GCP.md` ya estaba resuelto: REPO.5 lo dejó con marcadores
`<ORG>/<REPOSITORIO>` y documentando **los dos** anclajes de WIF.

**Lo vigila `test_repo4_no_se_nombra_al_dueno_anterior.py`**, que prohíbe además volver a poner un
`@usuario` individual — sin eso, «retirar el nombre viejo» se podría hacer cambiando una persona
por otra y el problema seguiría igual. Comprobado contra el estado anterior: se pone rojo con las
14 entradas.

**REPO.6 ✅ el 2026-09-16 — la revisión del contenido antes de abrirlo.** La purga cerró **de
dónde viene** el repositorio; esto miró **qué contiene**, que es lo otro que se publica al cambiar
la visibilidad. Cinco hallazgos sobre los 1525 ficheros versionados, y **el que importa no es un
fichero sino un guardarraíl**: el de REPO.5 buscaba la IP como `34-175-38-129`, con guiones, y el
documento la escribe con puntos — **nueve días en verde con la IP de producción dentro de
`DESPLIEGUE_PROTOTIPO_GCP.md`**, y lo encontró un barrido a mano, no el test. Los otros cuatro:
este mismo fichero llevaba una lista de correos institucionales junto al detalle de qué podían
hacer esas cuentas, que es un dato personal y un mapa a la vez (las identidades se fueron a
`_local/`, y lo que describían quedó sin objeto el mismo día: ver el aviso ✅ de más abajo);
`server/my_errores.txt` y `frontend/tsc_baseline.txt`, dos salidas guardadas que **no lee nadie**
—la segunda no la menciona ni un fichero del repositorio—; siete scripts de `scripts/` que abrían
todos el mismo `translations.json` de la app NiceGUI retirada; y faltaba `CODE_OF_CONDUCT.md`, lo
único del juego estándar que no estaba.

**Lo vigila `test_repo6_el_contenido_que_se_publica.py`** con cuatro guardarraíles. El de correos
barre la **superficie viva** —lo versionado menos `HISTORIAL.md`, `planificacion/fase1/` y los
tests— y su lista de permitidas obliga a escribir **por qué** una cadena no nombra a nadie: quien
no pueda escribirlo está callando a alguien. **Y uno de los cuatro nació con el defecto que este
proyecto persigue**: buscaba las palabras `volcado`, `my_errores`… y acusó a
`scripts/volcado_piloto.sh`, que es la **herramienta que hace** un volcado. Ahora mira la forma
—extensión de salida fuera de los tests— y no el nombre.

**Queda sólo REPO.2** (los otros dos repositorios), que no bloquea abrir éste.

**Bloque REPO ▶: desbloqueado (rol `admin` desde el 2026-09-14) y REPLANIFICADO a la variante C
el 2026-09-15.** La variante B —«el limpio nace en la organización y no se transfiere nada»— **ya
no es posible: la transferencia se hizo el 2026-09-10**, y con ella entró en la organización justo
lo que B existía para evitar. Medido contra la API: los **dos** commits huérfanos
(`dc4904e0c763` y `152c3d2f3f2e`) son alcanzables y sirven **92 ficheros**; el historial
alcanzable, en cambio, está limpio.

**Y lo que hay dentro ya no es una suposición**: son volcados `llm_anonymized_input_*.txt` cuyo
nombre **miente**. Sobre una muestra, y sin leer contenido personal: de 28 correos, **13 son de
dominios institucionales reales** (`uji.es`, `mondragon.edu`, `doctor.upv.es`). La anonimización
no lo cogió todo. Los DNI y teléfonos **no discriminan** —Faker sustituye un DNI por otro DNI—,
así que lo que decide son los dominios.

**Por eso `filter-repo` no basta**: los volcados no están en la historia, así que reescribirla no
los toca. Y **la variante C —repositorio nuevo— está bloqueada por permisos**: el usuario es
`member` de la organización, que tiene `members_can_create_repositories=false`; puede **borrar**
el repositorio (es `admin` sobre él) pero no crear uno.

**Vigente: la variante D — pedir a GitHub Support la recogida de basura, y verificar.** Y el
argumento con el que se descartó Support al escribir la C **estaba mal**: se dijo que no era
comprobable desde fuera, y sí lo es — con la misma llamada que encontró el problema. Lo que
además dice que aquí funciona limpiamente es que **nada ancla los huérfanos**: **0 *forks*, 0
*pull requests*, 0 refs de *pull***. Con eso, una recogida de basura se los lleva.

**Pasos 1-4 EJECUTADOS el 2026-09-15**: respaldo, filtrado de las 7 rutas y *force-push* al mismo
repositorio. `main` **50bb0c5**, `desarrollo` **b0d8523**, CI verde entero sobre la historia
reescrita. Las 7 rutas pasan de 12 commits a 0, el recuento se queda en 736 —sin desplome— y el
diff de árboles son exactamente los 4 ficheros. Los cuatro se copiaron antes a
`_local/docs_operacion/` (paso 3.bis, que estaba pendiente).

## ✅ LA PURGA ESTÁ HECHA Y VERIFICADA (2026-09-16)

**GitHub Support la ejecutó el mismo día**, y está comprobado a los tres niveles:

| Comprobación | Resultado |
|---|---|
| Los **4 huérfanos** por API | **422 «No commit found for SHA»** |
| `contents/logs` de los dos con datos | **404 «No commit found for the ref»** |
| **`git fetch origin <sha>`** ← la definitiva | **no se pueden descargar** |
| `main` / `desarrollo` | vivas, y el historial completo (741 commits) se descarga entero |

**Con esto cae la puerta que impedía abrir el repositorio.** Lo que queda antes de hacerlo
público es **REPO.4** (el repositorio se nombra a sí mismo en seis ficheros con el dueño anterior;
es de agente) y **REPO.2** (los otros dos repositorios).

> ⚠️ **Y la lección de la verificación, que es de método y ya tiene nombre en esta casa: el
> medidor miente antes que el sistema.** Las **dos primeras** comprobaciones dieron falso:
>
> * `gh api … --jq '.sha'` sobre un error imprime la cadena `"null"`, que **no está vacía**, así
>   que un `if [ -n "$r" ]` daba «sigue vivo» **siempre**. Dijo «TODAVÍA ALCANZABLE» en los cuatro.
> * `--jq 'length'` sobre `contents` contaba la longitud del **JSON de error** como si fueran
>   ficheros.
>
> Quedarse en la primera lectura habría sido acusar a Support de no haber hecho su trabajo. Lo que
> zanjó la duda fue **bajar al nivel correcto**: `git fetch origin <sha>` no pasa por la API ni
> por cachés — o el objeto está en el almacén, o no está.
>
> **Matiz sobre la respuesta de Support**: dice *«I have cleared the cached views»*, que
> literalmente es menos que «he recogido la basura» y podía significar sólo la interfaz web. **No
> fue el caso.** Y su aviso de rotar credenciales **no aplica**: lo que había eran volcados con
> correos institucionales, no secretos. Nada que rotar.

Texto del ticket y comprobaciones, en `_local/TICKET_GITHUB_SUPPORT_purga.md`.

> ⚠️ **Al rellenarlo apareció una trampa que conviene no volver a pisar**: la categoría
> «Eliminaciones» lleva a un formulario que **borra el repositorio entero** y es irreversible,
> porque ahí «purgar» significa destruir del todo un repositorio **ya eliminado**. El nuestro está
> vivo y lo que se purgan son objetos **dentro**. El camino bueno es **Repositorios → Funciones
> del repositorio → Datos**, y el cuerpo del mensaje empieza diciendo explícitamente que **no** se
> pide borrar el repositorio. (Y «Problemas», en ese menú, es la traducción de *Issues*.)

**La puerta CAYÓ el 2026-09-16** con la purga verificada (arriba). Ya no hay nada que impida
abrir el repositorio salvo REPO.4 y REPO.2.

**Y el punto de no retorno ya se cruzó**: era la purga, no el *push*. Mientras los huérfanos
existían, todo lo anterior al filtrado se recuperaba desde el propio GitHub; ahora **la única
copia de la historia previa al filtrado es el *bundle*** `respaldo-gov-gen-ai-platform-2026-09-15.bundle`
—ya fuera del portátil— y este clon local. No borrar ninguno de los dos a la ligera.

**La exposición que hubo, para el registro**: privado, 7 colaboradores directos, 30 miembros en la
organización, del 2026-08-21 al 2026-09-16. Acotada y conocida en todo momento; nunca pública.

**Lo que ya está hecho y no hay que repetir**: las 12 variables, los dos anclajes de GCP
—demostrados por **dos despliegues reales** el 2026-09-15—, y el paso **0.bis** (los tres ficheros
que sólo protegía `.git/info/exclude`, que no viaja, movidos a `_local/docs_operacion/`;
comprobado además que ninguno entró nunca al historial).

**El orden de lo que queda: DEP → PLG → DIN → FUN**, con **PRC en paralelo y a tandas** cuando
lleguen las fichas validadas, y **REPO intercalado** en cuanto el usuario ejecute REPO.1.

**DESPLEGADO el 2026-09-15**: `main` = `8e518e0`, con **LANG y DEP enteros** más REPO.3/REPO.5 y
los documentos. Los seis contenedores arriba, `/` y `/health` en 200, `/docs` en 404 (SEC.7). La
madurez de lo que estos bloques cambian pasa de `construido` a `producción`.

**Lo que pasó el 2026-09-07, y por qué el bloque cambió de forma.** Al valorar la propuesta de
UADTI de llevar los repositorios a la organización de la UJI se midió el estado real, y salieron
tres cosas:

1. **La exposición sigue viva.** Caminando la cadena de huérfanos en GitHub, el commit
   `dc4904e0c763` (2026-08-21 06:20) todavía sirve `logs/` con **46 ficheros** de datos reales.
   GitHub no ha recogido basura en 17 días y no promete cuándo. Y **el SHA que REPO.1 mandaba
   comprobar no demostraba nada**: el árbol de `82f475b` no tiene `logs/`.
2. **Se elige la variante B**: el repositorio limpio **nace en la organización** y no se
   transfiere nada. Una transferencia se lleva el almacén de objetos completo, así que con la
   variante A los 46 volcados entrarían en la organización de la universidad. Con B no entran
   nunca. Requisito: permiso para crear repositorios allí.
3. **Aparece REPO.4**, que con la variante A no hacía falta: al cambiar el dueño, el repositorio
   se nombra a sí mismo en seis sitios (`CODEOWNERS`, dos `pyproject.toml`, `CONTRIBUTING.md`,
   `DESPLIEGUE_PROTOTIPO_GCP.md` §177 y `PLAN_DESARROLLO.md`). `deploy.yml` **no** lleva el
   nombre.

**El modelo de gobernanza acordado, que es lo que decide todo lo anterior**: un solo repositorio
—no un *fork* institucional— gestionado con la disciplina de que otra administración pueda
descargarlo, con lo específico de la UJI en variables, Secret Manager y filas de la base de datos.
El *fork* se creará el día que la UJI escriba código que no se pueda generalizar; hoy estaría
vacío. La propuesta para UADTI, con el estado real del reparto medido, está publicada como página
aparte. Y **la AGPL ya garantiza el uso**: sus derechos son irrevocables (§2), así que ninguna
decisión de gestión puede impedir el uso investigador ni por entidades locales; lo que la licencia
no protege es la **dirección**, y eso lo protege la arquitectura.

**Antes de REPO había: sin bloque en curso.** El **Bloque LANG ✅ quedó completo el 2026-09-03** (2
prompts), en `desarrollo` y **sin desplegar**: `language_mode` dejó de estar desconectado —los
tres modos los compone la factoría y el valor se valida con 422—, y el panel los ofrece desde el
contrato, con el código del corpus. Antes, el **Bloque USR ✅ también quedó completo el
2026-09-03** y **ése sí está desplegado** (`main` = `cf43832`, migraciones aplicadas hasta
`c8f1b5d92e47`): los 7
prompts planificados **más los tres arreglos** que el usuario pidió antes de seguir con LANG —los
hallazgos que el informe de cierre reportaba sin arreglar—: USR.8 el chat agéntico que no
terminaba nunca ni avisaba, USR.9 la pantalla de Personas fuera del módulo de plataforma y con su
listado abierto a quien administra una organización, y USR.10 el «no tienes ningún módulo» que se
le enseñaba a quien sí los tiene. Y **USR.11**, pedido al preguntar si los arreglos llegaban a
producción: el contrato de citas era el último sitio del camino de la respuesta que leía el
contenido del modelo como si siempre fuera cadena. Lo que el bloque dejó hecho: una persona de `hub_users` puede tener contraseña local, entrar con su rol real, que se
la fijen desde el panel y **cambiarla ella misma**, con el interruptor `LOCAL_USER_LOGIN_ENABLED`
para apagar la vía cuando llegue el SSO. La decisión de fondo está en
`docs/DECISION_IDENTIDAD_DE_ADMINISTRACION.md`: la identidad de administración es **`HubUser` con
`role='admin'`**, y `AdminAccount` se queda con el partner y la facturación — con lo que **varias
personas pueden administrar la misma organización**, que era el motivo real por el que el alta del
piloto tuvo que dar el rodeo que dio.

**Cuando haya que dar acceso a alguien**: `pruebas_manuales/pruebas_manuales_bloqueUSR.bat` — alta
como Persona con su rol y **una credencial propia**, y concederle sus módulos. Desde USR.9, a quien
administre una organización hay que concederle además el módulo **`personas`**; a quien ya tenía
`plataforma` se lo dio la migración. **El rodeo del piloto ya no existe**: sus cuentas se retiraron
el 2026-09-16 (aviso ✅ más abajo).

**DEP nació el 2026-09-08** de la primera medición del job de cadena de suministro, y su prompt
DEP.1 se pudo adelantar solo porque arreglaba un defecto latente en la subida de ficheros. **LANG
✅ quedó completo el 2026-09-03** y está en `desarrollo`. El estado vivo de los dos está en el
cursor, arriba. Lo anterior:

### El orden de los bloques que quedan, acordado el 2026-09-02

Lo decidió el usuario sobre una propuesta razonada. **59 prompts en once bloques** —eran 49; REPO
pasó de 2 a 5 el 2026-09-07, al elegir la variante B y aparecer REPO.4 y REPO.5, y **DEP nació el
2026-09-08** con la primera medición del job de cadena de suministro.

| # | Bloque | Prompts | Por qué aquí |
|---|---|---|---|
| ~~1~~ ✅ | ~~**USR**~~ (+4 arreglos) | 7+4 | **Cierra una exposición viva**: en producción hay siete superadministradores, seis de ellos probadores del piloto, con **la misma contraseña** y sin poder cambiarla ellos mismos. Y el piloto ya está abierto mientras el IdP no tiene fecha |
| ~~1~~ ✅ | ~~**LANG**~~ | 2 | Dos prompts, y el mando ya existe sin consumidor (`language_mode` viaja por toda la cascada y nadie lo lee). Hacerlo después de que haya datos puestos añade una migración |
| ~~3~~ ✅ | ~~**REG**~~ | 6 (9 ✅) | Lo pidió la reunión de desarrollo del 31-08 y **esperaba el despliegue** (REG.4, el MCP remoto, sólo existe con el servidor accesible desde fuera — ya lo está). Desbloquea VAS y FUN.6 |
| ~~4~~ ✅ | ~~**VAS**~~ | 4 | El mejor ratio del plan: los tres candidatos ya existen como función interna y sólo necesitan superficie |
| ~~5~~ ✅ | ~~**NIC**~~ | 5 (4 ✅ + NIC.5 del usuario) | Cierra la Fase 1. Se puede esperar sin coste porque nada de lo planificado toca `client_app/`. **NIC.5 lo ejecuta el usuario** |
| 6 ▶ | **REPO** | 5 (4 ✅) | **Sólo queda REPO.2.** REPO.3 y REPO.5 ✅ el 2026-09-07; **REPO.1 ✅ el 2026-09-15** (historial filtrado y empujado, variante D) con su **purga de GitHub verificada el 2026-09-16** —los cuatro huérfanos dan 422 y `git fetch` no los descarga—; **REPO.4 ✅ el 2026-09-16**. **La puerta para abrir el repositorio ya cayó**: lo único que queda antes de `Settings → Danger Zone → Change visibility` es REPO.2, que son los OTROS dos repositorios y no bloquea a éste. |
| ~~7~~ ✅ | ~~**DEP**~~ | 7 | **COMPLETO en código el 2026-09-15**, los siete. Falta sólo el push que demuestre la puerta en una ejecución real, que es decisión del usuario. El árbol del servidor pasa de **408 a 197 dependencias** y el de producción del frontend de **21 avisos (13 altos) a cero**. **DEP.4 se cerró midiendo, no confiando**: `camelot-py` 2.0 saca `pypdf` del árbol entero, y de los **2 PDF de 20** cuya extracción cambia, mirados celda a celda, **en los dos la versión vieja era la equivocada** —una cabecera de dos niveles colapsada y una portada de 28×2 que no era tabla, sino un falso positivo que la 2.0 rechaza bien—. **DEP.3 se cerró midiendo y su premisa resultó FALSA**: `starlette` sube a 1.6.0 sin tocar `fastapi` y sus 5 avisos desaparecen, pero `app.routes` **sigue plano** y los 14 tests que enumeran rutas **pasan**, así que no se reescribió ninguno — el `_IncludedRouter` que el prompt daba por hecho no aparece con `fastapi` 0.136.0. **Queda sólo DEP.7**, ya desbloqueado. **Lo que DEP.1 destapó y no estaba previsto**: al sacar `browser-use` y `ragas` aparecieron **tres paquetes usados y no declarados** —`python-multipart`, `langchain`, `beautifulsoup4`— más `langchain-community`, que sostiene Ollama. Entra un guardarraíl que los caza todos de golpe |
| ~~—~~ ✅ | ~~**IMG**~~ | 1 | **No tenía fila y sí prompt** (issue #5). El job `imagen` construye las cuatro imágenes con los `Dockerfile` del despliegue, migra con la recién construida y la arranca hasta `/health` 200. Cerrado el 2026-09-17 |
| ~~8~~ ✅ | ~~**PLG**~~ | 3 | Responde al correo de desarrollo pidiendo plugins. Después de LANG, que tocan la misma factoría |
| ~~9~~ ✅ | ~~**DIN**~~ | 7 | Bueno y no urgente: su premisa resultó falsa en dos tercios —el rastreo con cadencia y la auto-ingesta ya existen— |
| ~~10~~ ✅ | ~~**FUN**~~ | 7 (9 ✅) | El más grande y el de más diseño; FUN.6 necesita REG, que a estas alturas ya está |
| — | **PRC** | 6 | **No se puede programar**: espera las fichas validadas por los servicios y que el equipo del catálogo habilite la consulta de descarga. **En paralelo y a tandas**, conforme lleguen |

### Dónde se trabaja: la rama `desarrollo` (decisión del usuario, 2026-09-02)

**El trabajo se empuja a `desarrollo`, no a `main`.** `deploy.yml` sólo dispara con
`push: branches: [main]`, así que empujar a la rama **no despliega**: el despliegue se hace a
propósito, por bloque o conjunto de bloques, llevando `desarrollo` a `main`.

- **CI y DCO sí corren en `desarrollo`** (añadida a sus dos `on: push`). Sin eso, empujar a la
  rama no ejecutaría nada y se perdería la comprobación que hoy hay en cada push, que no es lo
  que se quería evitar.
- **`deploy.yml` no la lleva, y es el punto entero.** Si alguna vez se añade ahí, desaparece la
  separación.
- Lo que motivó la decisión: un commit que sólo tocaba `scripts/publica_sitio_corpus.sh`
  desplegó producción entera —`scripts/` no está en `paths-ignore` porque de ahí salen ficheros
  que sí viajan a la máquina—, con sus 60-90 s de reinicio y su aviso de vigilancia.

Lo anterior:
**Bloque ACT ✅ completo el 2026-08-28** (8 prompts, corpus ingerido y verificado). El corpus del 27-08 **ya está ingerido y verificado** (ACT.6). Decisiones pendientes de Secretaría General en `docs/CONFIGURACION_APERTURA_PILOTO.html` §12. **Modelo sugerido para el próximo prompt: Sonnet** (D.0 tiene alcance cerrado; espera datos del usuario). Lo anterior: **Bloque HIB ✅ completo el 2026-08-28** (15 prompts; HIB.K aplazado por necesitar dos informadores, HIB.S implementado y **apagado** porque rechaza 10 de las 30 respuestas correctas y el criterio escrito antes era «más de 2 y no se despliega»). Configuración de apertura del piloto en `docs/CONFIGURACION_APERTURA_PILOTO.html`: Normativa 0,65 y Gerencia 0,69, reranker apagado en los dos, `parent_child` en los dos, `top_k=3`. Lo que el bloque deja medido y no se puede cerrar sin el piloto: la varianza del contrato de citas es de ±3 sobre 18, mayor que varias de las diferencias medidas. **HIB.G ✅ completo el 2026-08-27**: los dos lotes existen, validan y se miden solos (`medir_lote.py`), con la fuente esperada anotada por el equipo (`equipo_provisional`) porque los informadores están de vacaciones. Desbloquea HIB.M y HIB.P. **HIB.K se aplaza**: la kappa entre informadores necesita dos informadores y es bloqueante para publicar, no para abrir el piloto. La anotación de informador sigue pendiente y con ella la publicabilidad de cualquier cifra del lote (actualizado el 2026-08-26; el bloque HIB se antepuso a Deploy/D.0 el 2026-08-26 y hasta hoy sólo constaba en `HISTORIAL.md`). **Modelo sugerido para el próximo prompt: Sonnet** (HIB.M, mismo instrumental que HIB.A). Antes de HIB, el orden hasta el
despliegue es **~~SEC.9~~ ✅ → ~~AIS~~ ✅ → ~~RAG.15~~ ✅ → ~~VIS.4~~ ✅ → ~~VIS.5~~ ✅ →
~~RES.1~~ ✅ → ~~RES.2~~ ✅ → ~~RES.3~~ ✅ → ~~RES.4~~ ✅ → ~~RES.5~~ ✅ → **Deploy/D.0**.
**El bloque RES está completo y ya no queda nada delante del despliegue.**

> 🔥 **INCIDENTE DEL 2026-09-01: el disco de la VM se llenó y el servicio se cayó. Arreglado, y
> con la causa cerrada.**
>
> **Lo que pasó**: diez despliegues habían dejado **30 imágenes de Docker y 25,2 GB** en un disco
> de 30 GB —la de `app` pesa 2,26 GB y cada despliegue publica tres—, y **el despliegue nunca
> limpiaba**. El `docker compose up` murió con `no space left on device` al crear el socket del
> proxy de Cloud SQL.
>
> **Por qué costó verlo**: el síntoma no señalaba al disco por ningún lado. La unidad decía
> «dependency failed to start: container govgenai_sql_proxy is unhealthy», que apunta al proxy y
> a la base de datos. El disco sólo aparece leyendo el log del propio proxy.
>
> **Y lo que lo agravó**: el paso «Comprobar que sirve, y volver atrás si no» **se salta cuando
> falla el paso de desplegar**, así que no hubo reversión — el servicio se quedó caído en vez de
> volver a la imagen anterior. Merece mirarse si ese paso debería correr con `if: always()`.
>
> **Arreglado**: 22,25 GB liberados, servicio restaurado y verificado de punta a punta, y **paso
> de `docker image prune -af` añadido al despliegue**, con dos tests que lo fijan. Va **antes de
> que la máquina baje las imágenes nuevas**, y la posición es el diseño: en ese punto los
> contenedores siguen apuntando a la generación actual y `prune -a` conserva exactamente lo que
> algún contenedor referencia, así que se conserva la actual, se libera todo lo anterior y la
> descarga que viene tiene sitio garantizado; tras el reinicio la anterior se queda en local sin
> contenedor, así que una vuelta atrás no tiene que volver a bajar 2,26 GB. Estado estacionario:
> dos generaciones, unos 10 GB de 30. Verificado en el despliegue `0f4b178`.
>
> **Limpiar sólo tras un despliegue exitoso no habría servido**, que fue la primera idea: el disco
> ya estaba lleno al empezar, así que una limpieza condicionada al éxito no se ejecuta nunca
> cuando hace falta.
>
> ⚠️ **Y LA LECCIÓN NO ES TÉCNICA. La alerta de disco existe, funcionó y avisó cuatro horas
> antes.** Una versión anterior de esta nota decía que no había alerta de espacio en disco: era
> falso, y no la había mirado antes de escribirlo. El registro de violaciones tiene el evento a
> las **05:11:56Z** (07:11 hora local) de «Gov Gen AI - disco por encima del 85%», y la métrica
> confirma **376 minutos por encima del 85%** con un pico del 95,9%. El aviso llegó; nadie actuó.
>
> **Por qué se perdió, y esto sí era accionable**: la alerta de salud dispara en **cada
> despliegue**, porque el reinicio deja el servicio 60-90 s sin responder y la comprobación lo
> coge desde varias regiones. El 2026-09-01 disparó cuatro veces, todas por reinicios.
>
> ✅ **Y la causa raíz era otra, más barata y peor de lo que parecía: el despliegue se disparaba
> con CUALQUIER push, incluidos los de sólo documentación.** El usuario avisó de que seguía
> recibiendo alertas «sin que se haya hecho ningún despliegue»; los había — el commit `16b5f61`
> tocaba únicamente `PROJECT_STATE.md` y reinició la pila. Medido en el momento: 101 de 1.293
> comprobaciones fallidas en tres horas, y el log de Caddy con 10 de 43 peticiones a `/health`
> en 502, todas en las ventanas de reinicio. **Arreglado con `paths-ignore`** (`**.md`, `docs/**`,
> `planificacion/**`, `pruebas_manuales/**`, `LICENSE`, `DCO`) y un test que lo fija, incluida la
> lista de lo que NO puede ignorarse. CI se deja disparando con todo a propósito: no reinicia
> producción y sí ejecuta tests que comprueban la documentación.
>
> **Lo que queda como opción, no como pendiente**: si tras esto siguiera molestando el aviso de
> los despliegues reales, la solución limpia es que el despliegue silencie su propia ventana con
> un *snooze* de diez minutos, lo que exige un rol propio con `monitoring.snoozes.create`. Subir
> el umbral se descartó: depende de cuántas regiones tenga la comprobación y envejece mal.

> 📅 **FECHA QUE HAY QUE RECORDAR: el certificado de `normativa.uji.es` caduca el 19 de marzo de
> 2027 y NO se renueva solo.**
>
> Desarrollo entregó el 2026-09-01 el certificado del dominio institucional (HARICA vía GÉANT,
> RSA 4096, un solo SAN) con su clave. Está en Secret Manager como `govgenai-tls-cert` y
> `govgenai-tls-key`, con acceso concedido a la cuenta de la VM y comprobado desde ella.
>
> **Lo que lo separa del anterior**: el del nombre provisional de `sslip.io` lo obtiene y renueva
> Caddy por ACME sin que nadie intervenga. Este hay que pedirlo, subir la versión nueva de los dos
> secretos y `systemctl restart govgenai`. Una renovación olvidada deja el dominio con un
> certificado caducado, que en un navegador es indistinguible de un servicio caído.
>
> **Y sigue faltando lo que de verdad bloquea: el registro DNS.** El 2026-09-01
> `normativa.uji.es` **no existía** — el propio servidor de la UJI (`ntp.uji.es`) responde
> «Non-existent domain». Hace falta un registro A a `34.175.38.129`. Emitir el certificado y crear
> el registro son dos peticiones distintas y la segunda está pendiente.
>
> **Cuando el DNS exista**, el orden importa y es corto: (1) comprobar que resuelve a la IP,
> (2) `systemctl restart govgenai` en la VM —el sitio se instala solo, porque el certificado ya
> está—, (3) comprobar `https://normativa.uji.es/health`, (4) regenerar las páginas del corpus con
> `ASSISTENT_API=https://normativa.uji.es/api/v1` y republicarlas, (5) **sólo entonces** valorar
> retirar el nombre provisional. El paso 4 es el que no se puede saltar: las 313 páginas
> publicadas llevan el nombre viejo dentro.

> ⏳ **PENDIENTE (anotado el 2026-09-01, a petición del usuario): añadir el receptor de Docker a la
> configuración del ops-agent de la VM.** Hueco de D.6-VM, que se dio por cerrado sin cubrirlo.
>
> **Lo que pasa hoy**: los contenedores escriben con el driver `json-file` —o sea, sólo en el disco
> local de la VM— y el ops-agent **no tiene configuración propia** (`/etc/google-cloud-ops-agent/config.yaml`
> no menciona Docker), así que a Cloud Logging sólo llegan `syslog`, `ops-agent-*` y las métricas.
> Comprobado: `gcloud logging logs list` no tiene ningún flujo de la aplicación.
>
> **La consecuencia, que ya costó una investigación**: **cada despliegue borra el registro de
> accesos**, porque reinicia los contenedores. El 2026-09-01, al investigar por qué el usuario no
> entraba al panel, los 401 de sus intentos habían desaparecido y no se pudieron fechar contra el
> momento del cambio de contraseña. El diagnóstico se cerró por otra vía, pero a ciegas en ese punto.
>
> **Al hacerlo**: receptor de Docker en el ops-agent (o driver de logs `journald` en Compose, que es
> más barato pero pierde la estructura), test de infraestructura que compruebe que la configuración
> lo declara, y verificación de que un `POST /api/v1/auth/superadmin/login` aparece en Cloud Logging
> **después** de un redespliegue. Cuidado con lo que se manda: el log de acceso lleva IP y correo.

> ✅ **CERRADO EL 2026-09-16: producción tiene un solo superadministrador.**
>
> Las cuentas de superadministración que se habían abierto para el piloto del 2026-09-01 están
> retiradas. **Ninguna llegó a usarse**, así que la retirada no dejó a nadie sin trabajo a medias;
> el acceso de cada persona se dará de alta como Persona —con su rol y su credencial propia—
> cuando haga falta, que es la vía que abrió el Bloque USR.
>
> **Por qué ese rodeo existió**, que es lo que conviene no repetir: `AdminAccount.partner_id` es
> la clave primaria y las organizaciones se enlazan por `HubOrganizacion.partner_id`, así que
> varias cuentas de administración para una misma organización serían varios `partner_id`
> distintos y todas menos una abrirían el panel con la lista vacía. Esa es la razón de fondo por
> la que se recurrió a la superadministración, y la que resolvió
> `docs/DECISION_IDENTIDAD_DE_ADMINISTRACION.md`: la identidad de administración es **`HubUser`
> con `role='admin'`**, y `AdminAccount` se queda con el partner y la facturación. Con eso, varias
> personas pueden administrar la misma organización y el rodeo deja de hacer falta.
>
> **Lo único que queda abierto de aquí: no existe cambio de contraseña por el propio usuario** en
> ninguno de los dos roles de gestión —lo dice el docstring de `set_admin_password`—, así que hoy
> una credencial de gestión sólo la cambia quien administra. **Es USR.7.**
>
> El detalle de la operación está en `HISTORIAL.md`.

> 📌 **Decisión del 2026-09-01: el widget vive SOLO en los buscadores, no en las 313 fichas.**
>
> Cada sitio publicado lleva su asistente —`cercador.html` e `index.html` el de Normativa
> (`d18ffad7`), `cercador_gerencia.html` e `index_gerencia.html` el de Gerencia (`722aaa10`)—
> pero **las fichas de norma son compartidas por los dos sitios**, así que la que se abría desde
> el buscador de Gerencia enseñaba el asistente de Normativa.
>
> **No se arregla con un juego de fichas por sitio**, que fue la primera idea, y la razón está en
> `citations.py:89`: la URL de la cita se construye como `{CORPUS_SITE_BASE_URL}/html/{slug}.html`,
> con la base **global del despliegue** y `/html/` fijo. No hay base por chatbot, así que el clic
> en una cita —que es como la gente llega de verdad a una ficha— seguiría cayendo en el mismo
> juego. Un juego por sitio exigiría además hacer la base de citas configurable por chatbot:
> columna en `HubChatbot`, migración y `citations.py`. Queda anotado como candidato, **no hecho**.
>
> **Y el motivo de fondo pesa más que la confusión visual**: una pregunta hecha desde una ficha se
> registraba contra el chatbot de Normativa aunque el probador viniera de Gerencia, así que con
> seis personas puntuando respuestas los datos de la evaluación se contaminaban sin dar ninguna
> señal. Quitar el widget de las fichas lo elimina de raíz y cuesta una variable de entorno
> (`estil_uji.assistent()` devuelve cadena vacía sin `ASSISTENT_CHATBOT`).
>
> **El precio aceptado**: se pierde preguntar mientras se lee una norma, que es justo donde
> aterrizan las citas. Si el piloto pide recuperarlo, el camino es la base de citas por chatbot.

> ✅ **RES.5 ejecutado y cerrado SIN implementar (2026-08-25), que es un resultado legítimo del
> prompt y no un abandono.** 96 ejecuciones (3 tandas × 32 consultas), 85 pasaron la puerta y
> **`citation` no aparece ni una vez**; los 11 rechazos son todos de la puerta. La regla acordada
> pedía al menos un descarte que mencionara un título literal para justificar el enlazado
> determinista: hay cero.
>
> **No dice «no pasa nunca»**: cero en 85 es compatible con una tasa real de hasta el 4,4%, y el
> caso se observó una vez con `top_k=5`. Queda como línea base para repetirlo con tráfico del
> piloto sobre `hub_interactions.fallback_reason`.
>
> **Hipótesis** de por qué ya no aparece: `top_k=3` deja menos URLs compitiendo y citar una bien es
> más fácil. REAL-07 responde ahora en las tres tandas con 0,626 estable.
>
> **Se verificó el instrumento antes de fiarse del cero**: una respuesta que cita con corchetes y
> sin URL da `fallback_used=True` y `motivo='citation'`, así que el cero sale de la contabilidad
> del producto. La sonda dejó 3 registros de 96 sin reconciliar con el estado final —no afectan a
> la cifra, que se lee de `fallback_reason`— pero **su clasificación de motivos no es de fiar** y
> habría que depurarla antes de decidir nada con ella.

> ✅ **RES.4 hecho (2026-08-25). Valor elegido con las cifras delante: `retrieval_top_k = 3` en los
> dos chatbots.** Con la puerta desacoplada, la anchura ya sólo decide contexto, y se midió con el
> grafo completo:
>
> | | responden | se rinden | docs citados | fuente única |
> |---|---|---|---|---|
> | Normativa `top_k=5` | 20/25 | 5 (4 puerta, 1 cita) | 3,60 | 0 |
> | Normativa `top_k=3` | **22/25** | 3 (todas puerta) | 2,59 | 2 |
> | Gerencia `top_k=3` | **6/7** | 1 | — | 0 |
>
> Los rechazos están **anidados**: todo lo que falla con 3 falla con 5. La calidad es
> **indistinguible** —4-2 con **12 de 25 veredictos dados la vuelta** al invertir el orden, más
> ruido que en la tanda anterior—, así que decide la cobertura. **El coste está mirado una por una**:
> en las dos respuestas de fuente única con 3, la versión con 5 cita un segundo documento pertinente
> (en ORI-10, una *Instrucció* de diciembre de 2025 del Vicerectorat). Se acepta: una respuesta con
> una norma correcta vale más que ninguna, y `respuesta_incompleta` es 4 de 25 en el catálogo de los
> informadores frente a los 15 de `curso_caducado`, que es el modo que estrechar **reduce**.
>
> ✅ **Y la decisión pendiente del umbral 0,35 de Gerencia se ha resuelto sola: no hay que
> tocarlo.** Con la puerta sobre el mejor fragmento responde 6 de 7 con ese mismo valor, y la que
> falla lo hace con 0,152 — no la recupera ningún umbral razonable. RES.1 hizo innecesario bajarlo.
>
> ✅ **Umbral de Normativa bajado a 0,40 (decisión del usuario, 2026-08-26).** Las tres que
> callaban tenían nota 0,405 / 0,458 / 0,30 contra 0,50. Lo decisivo fue el veredicto del
> informador sobre **ORI-04**: «INCORRECTA por falso desconocimiento — contestó *no disposem
> d'informació* cuando la información SÍ está en el corpus» (art. 3.4 del Reglament sobre
> reconeixement). O sea que **negarse a responderla era exactamente el defecto que el lote existe
> para cazar**, reproducido con otro mecanismo.
>
> Y un dato que quita peso al miedo habitual: **el umbral no filtra las preguntas fuera del
> corpus**. De las tres marcadas así en el lote, dos contestan con 0,795 y 0,547 — la nota no
> detecta «esto no está en el corpus», así que bajarla no desmantela una protección que
> funcionara. Lo que sí protege es SGE-04 (0,30, `colectivo_equivocado` + `citas_irrelevantes`),
> y 0,40 lo deja fuera con 0,10 de margen. Es además el hueco más ancho de la distribución
> (`0,30 · 0,405 · 0,458 | 0,526 · 0,547 …`).
>
> **Dos límites dichos al decidir**: ORI-04 pasa por 0,005, y **las notas no son estables entre
> tandas** (ORI-13 dio 0,76 y 0,533 con la misma consulta), así que entrará unas veces sí y otras
> no. Y el lote son 25 preguntas legítimas: **no permite estimar cuántas respuestas equivocadas
> admite un listón más bajo**. Gerencia se queda en 0,35: la que falla allí lo hace con 0,152.
>
> **Corrección de RES.3 que salió de la suite completa** (`aeedf5c`): `hub_lexicon_pairs` nació en
> `HubConfigBase` y el guardarraíl de la frontera lo rechazó **con razón**. `termino_de_usuario` es
> literalmente lo que escribió una persona, y la configuración se sincroniza cloud→edge: ponerla ahí
> obligaba a que el texto de las preguntas del cliente existiera en el cloud. Lo que decide el lado
> no es «es vocabulario» —`hub_vocabulary_terms` es configuración y está bien— sino si lleva dentro
> texto de alguien. Movida a `HubOperationalBase`, sin las dos FK y sin `__ambito__`.

> ✅ **RES.1, RES.2 y RES.3 hechos (2026-08-25).** Medido en la batería de Gerencia con el grafo
> completo: **de 2 respuestas de 7 a 6 que pasan la puerta**. RES.1 (puerta con el mejor fragmento)
> llevó de 2 a 4; RES.2 (segunda búsqueda al fallar) de 4 a 6. La séptima —REAL-03, portátil de
> alta gama— sigue por debajo del umbral incluso reformulada (0,201 contra 0,35).
>
> **Dos fallos silenciosos encontrados verificando RES.2, y los dos del mismo tipo**: síntoma
> idéntico a no tener reformulación, que es justo lo que el prompt venía a corregir. (1)
> `get_rewrite_model` traía `max_tokens=100`, escrito para un modelo que no razona;
> `gemini-2.5-flash` sí razona y esos tokens salen del mismo presupuesto, así que las
> reformulaciones llegaban como «Cont» y «Contrato menor de» — y no lo cazaba nada, porque media
> palabra no está vacía ni pasa de 300 caracteres. (2) Al subirlo a 512 el modelo devuelve la
> reformulación correcta pero tarda 2,4-2,6 s, y el plazo era 2,0: se mataban **todas**. Ahora la
> reformulación tiene su propio plazo de 8 s, porque su compromiso es otro —sólo corre cuando la
> puerta ya rechazó, o sea que la alternativa a esperar es no responder— y hay una guarda por
> `finish_reason` para que un truncamiento no pueda volver a pasar inadvertido. Esa guarda vale
> también para la reescritura de RAG.10, que llevaba el mismo tope y el mismo defecto.
>
> **Hallazgo que se convirtió en RES.5**: REAL-07 se rinde con nota 0,626 —muy por encima del
> umbral, o sea que la puerta la dejó pasar— por el **contrato de citas**. Espiando
> `enforce_citation_contract` se ve la causa: el modelo escribe «...a les quals es refereix
> **l'article 8 del mateix reglament**...», o sea **nombra la norma en prosa en vez de emitir un
> enlace**, mientras las tres URLs permitidas estaban ahí y eran las correctas. No citó mal: no
> citó en el formato que el contrato sabe leer, y el contrato no puede distinguir eso de una
> respuesta inventada porque sólo mira enlaces `[texto](url)`.
>
> La degradación del ancla al documento (2026-08-24) **sigue puesta y funciona**; lo que queda
> intacto son las dos guardas que su docstring declara —citar un documento no recuperado, y no
> citar nada—, y esto es la segunda. **Es intermitente**: la misma consulta repetida sí citó.
>
> **RES.5 empieza por medir la frecuencia y puede terminar en «no se hace»**: tres tandas de cada
> lote, separando los dos motivos, y una puerta de decisión en el 2% de las respuestas que pasan el
> gate. Si se implementa, el orden es enlazado determinista del título literal —que **crea** un
> puntero verificable en vez de aceptar uno vago, coste cero— y sólo si no basta, un reintento con
> la instrucción reforzada, que se paga sólo al fallar. **Descartado a propósito**: adjuntar las
> fuentes y conservar la respuesta, porque fabrica la apariencia de respaldo bajo afirmaciones que
> no están atadas a ninguna fuente concreta.
>
> **Desviación de método documentada**: RES.1 y RES.2 fueron en **un commit** (`a99e16f`) y no en
> dos. Los dos cambian `merge_node` y `quality_gate` en el mismo fichero y se implementaron
> seguidos; separar los *hunks* habría dejado un commit cuyo código no cubren sus tests. Queda
> dicho porque la regla de un commit por prompt existe para poder volver a un punto exacto.

**RES se mete delante de Deploy a propósito.** Medir RAG.15 dejó al asistente contestando 18 de 25
en Normativa y 2 de 7 en Gerencia, y el usuario lo rechazó con el criterio correcto: «no resulta
aceptable un sistema que no contesta a casi la mitad de las preguntas». Desplegar un piloto que
calla en la mitad de las consultas es desplegar la primera impresión equivocada, y esa no se
repite. El diagnóstico está cerrado y medido —el problema no es la anchura— así que lo que queda es
ejecutarlo, no investigarlo.

**Modelo sugerido para el próximo prompt**: **Sonnet** para RES.1. Después **Opus** para RES.2 y
RES.3, y **Sonnet** para RES.4.

> **VIS.4 y VIS.5 hechos (2026-08-25).** VIS.4: la preferencia de lengua opera **dentro de la misma
> vigencia**, no por encima de ella — antes «usa la otra lengua» y «usa una versión anterior» eran
> la misma acción, y para quien pregunta son cosas muy distintas: citar lo que ya no rige en su
> lengua es un error de fondo, y citar lo vigente en otra lengua es una incomodidad que además se
> avisa. `prefer` **ordena** en vez de filtrar, con la señal de vigencia que VIS.3 ya pone en cada
> evidencia, y conservando la relevancia dentro de cada grupo. Con el corpus de hoy **no cambia
> ningún resultado** (cada norma tiene una sola versión), y ése es el motivo de escribirlo antes:
> cuando el emparejamiento bilingüe se complete, nadie estará mirando esta parte. VIS.5: el aviso
> **sale de la lengua de la fuente**, se emite en las dos direcciones —antes se callaba cuando la
> pregunta era en castellano, que es el caso más frecuente del corpus, y el grafo sí había decidido
> avisar— y se redacta en la lengua de quien pregunta, con acentos. **Matiz que aclaró la
> implementación**: el `translation_warning: False` de los dos ejecutores es el estado *inicial*
> del grafo y se sobrescribe; lo que de verdad faltaba es que el **resultado** guardara el aviso,
> y sin eso el texto que ve el ciudadano no aparecía en ninguna herramienta de revisión. Migración
> `w3p4q5r6s7t8` aplicada.

> ✅ **La medición que RAG.15 dejó abierta está hecha (2026-08-25).** Informe en
> `docs/MEDICION_RETRIEVAL_TOP_K.html`. Se midió **sólo la recuperación**, con un barrido nuevo
> (`_local/golden/barrido_topk.py`) que aplica cada valor con `dataclasses.replace` sobre la
> configuración efectiva: así no hacen falta las 25 llamadas al modelo por configuración que
> frenaban esto, ni se escribe `HubTestRun` en la base del usuario. **Recomendado: 5.** Es el valor
> más bajo que deja en **cero** las respuestas de fuente única (con 3 quedan 3 de 25), y el que
> menos respuestas pierde por el filtro.
>
> **Lo que la medición destapó, y no estaba previsto**: el `quality_gate` compara
> `quality_threshold` contra la **media** de las puntuaciones (`core_graph.merge_node`), así que
> ensanchar la búsqueda **baja mecánicamente la nota que decide si se responde**. Con el `8` de hoy
> **10 de las 25 consultas caen a la respuesta de cortesía**; con 5 caen 7 y con 3, 6. La nota que
> este bloque escribió —«los dos números se mueven juntos»— resulta ser más literal de lo que
> parecía: no es que haga falta recalibrar, es que **un mando mueve al otro por construcción**. La
> salida razonable es puntuar sobre el mejor fragmento o la media de los tres primeros, de modo que
> la cola informe el contexto sin votar sobre si hay respuesta. **No está hecho**: merece su propio
> prompt y no se coló en una medición.
>
> **Aplicado el 2026-08-25 por decisión del usuario**: `retrieval_top_k = 5` en `Normativa UJI` y
> en `assistent economicoadministratiu`.
>
> ✅ **Y medida también la calidad de la RESPUESTA** (`docs/CALIDAD_RESPUESTA_TOP_K.html`), que era
> lo que el barrido de recuperación no podía ver. 50 llamadas al modelo más 50 del juez, comparación
> ciega por pares con `gemini-2.5-pro` —distinto del `gemini-2.5-flash` que redacta— y **doble
> vuelta con el orden intercambiado**. Respuesta: **el modelo NO redacta mejor con menos
> documentos**. Cuando las dos configuraciones contestan, 4-3 con 6 veredictos que se dan la vuelta
> al invertir el orden: ruido. Toda la ventaja del 5 es que **responde 18 de 25 frente a 15**, y
> **no hay ni un caso en que el 8 responda y el 5 se calle** —los rechazos están anidados—.
>
> Lo que sí tiene señal es el **motivo** de cada victoria, y es asimétrico: el 8 gana cuando sus
> documentos extra completan (distinguir grado/máster/enseñanzas propias) y pierde cuando
> contaminan con normas de otro curso. Cuatro contra tres empata, **el coste no**: el propio lote
> cataloga `curso_caducado` en 15 de 25 escenarios y lo llama «el defecto más repetido del ensayo»,
> frente a 4 de `respuesta_incompleta`. Se elige 5 por riesgo, no por calidad media.
>
> **Dos validaciones de método**: el barrido barato predijo 18 y 15 respuestas y el grafo completo
> dio exactamente 18 y 15 —reescritura de consulta incluida—, así que **para decidir sobre el filtro
> el barrido de recuperación sustituye a las llamadas al modelo**; y juzgar dos veces era
> imprescindible, porque con una sola vuelta habría reportado un ganador inexistente en 6 de 25.

> ⚠️ **RAG.15 dejó mudo al `assistent economicoadministratiu`, y no se vio.** Informe en
> `docs/GERENCIA_TOP_K_Y_UMBRAL.html`. Sus seis preguntas reales son del 15-16 de agosto, o sea
> **anteriores al arreglo**: entonces la anchura efectiva era 1, el filtro promediaba un solo
> fragmento y le salía la nota del mejor (0,427 sobre un umbral de 0,35), así que contestó las seis.
> Con la anchura arreglada entran 4-5 fragmentos, la media baja a 0,282 y el umbral la rechaza:
> medido con el grafo completo, **se rinde en 5 de 7 preguntas, con anchura 5 y con 8 igual**.
>
> Es la misma raíz que el acoplamiento de arriba, y aquí se ve como una **regresión que introdujo
> una corrección**: arreglar un mando movió otro que nadie estaba mirando. La lección operativa es
> que un chatbot cuyo corpus puntúa bajo no puede compartir la calibración de uno que puntúa alto,
> mientras el umbral se compare contra una media.
>
> **`top_k = 5` aplicado igualmente** (no rescata ninguna pregunta, pero evita el relleno: en la
> única que ambas contestan, el 8 dobla el texto —2.034 → 4.458 caracteres— y baja su propia nota
> de 0,69 a 0,50). **El umbral NO se ha tocado**: bajarlo a 0,30 lleva de 2 a 4 respuestas de 7
> —las dos que puntuaban 0,311 y 0,327—, pero cambia qué evidencia se considera suficiente para
> afirmar algo, y eso es decisión del usuario. Las otras tres puntúan 0,11-0,12 y parecen huecos
> del corpus.
>
> **Dato para leer la comparación con el agéntico**: responde 7 de 7 porque
> `md_agent_selector_pipeline` asigna `score = 1.0` fijo, así que **su filtro no puede rechazar
> nada con ningún umbral** y el reranker no actúa. No es que recupere mejor: es uno con filtro
> contra otro sin filtro.
>
> 🔴 **Y el diagnóstico que sale de rechazar ese resultado (2026-08-25).** El usuario no aceptó
> «18 de 25» —«no es aceptable un sistema que no contesta a casi la mitad»— y afirmó que **todas
> sus preguntas tienen respuesta en el corpus**. Comprobado por SQL: los documentos están.
> Informe autónomo en `docs/DIAGNOSTICO_POR_QUE_NO_CONTESTA.html`. **Dos defectos, y `top_k` no es
> ninguno**:
>
> 1. **La puerta promedia.** Puntuarla sobre **el mejor fragmento** da **20/25 y 4/7 con cualquier
>    anchura** (la columna es plana en 2, 3, 5 y 8) frente a 18 y 2 hoy. `top_k=2` contesta lo
>    mismo pero con 6/25 y 5/7 de **fuente única**: cambia un defecto por el que se acababa de
>    corregir. Un *suelo relativo* al mejor se probó y **da peor** (19, y reintroduce fuente única).
> 2. **No hay normalización en la primera pregunta.** `query_rewriting_enabled` está en `t` en los
>    tres chatbots, pero `necesita_reescritura` exige **dos turnos previos**: `rewritten_query` fue
>    `None` en las 14 ejecuciones medidas. Reformulada a mano al vocabulario de la norma, REAL-04
>    pasa de 0,126 a **0,640**; 4 de las 5 mudas de Gerencia pasarían. **Aviso**: esas
>    reformulaciones se escribieron conociendo el corpus, así que son un techo.
>
> **Tres piezas que ya existen y abaratan el arreglo**: `LanguagePolicy` **declara
> `needs_secondary_search(...)`, tiene tests y `core_graph` no lo llama nunca** —el escalón
> «si falla, reformula y reintenta» es completar lo previsto—; `get_rewrite_model` ya está con tope
> de 100 tokens; y **`hub_document_chunks.bilingual_terms`** es el hueco de la expansión léxica ya
> cableado al `tsv` (columna generada), así que ampliarla es un `UPDATE` sin re-embeber.
>
> **Orden propuesto**: puerta → escalón de reformulación (se paga sólo al fallar: 28% en Normativa,
> 71% en Gerencia) → expansión léxica alimentada por `feedback_score`/`review_verdict`, que ya son
> columnas de `hub_interactions` → **y entonces** medir la anchura, que hoy sería medir sobre una
> base que se va a mover. **Nada de esto está implementado**: falta escribir los prompts.
>
> **Batería de validación entregada a Gerencia**: `docs/VALIDACION_GERENCIA.html`, publicada como
> artifact con la capacidad `artifact` (la página guarda versiones de sí misma, así que los
> veredictos vuelven) y `downloads` como respaldo si quien valida entra en sólo lectura. Siete
> preguntas × cuatro configuraciones, **a ciegas y con el orden permutado por pregunta**. Aquí no
> hay juez porque **en Gerencia no existe una lista de respuestas validadas**: las preguntas sirven,
> las respuestas de hoy no tienen por qué ser las adecuadas, y de lo que Gerencia marque saldrán
> los tests.

> **RAG.15 va primero de los tres**: `retrieval_top_k` **no lo lee ningún pipeline** —la
> estrategia se construye con `top_k=cfg.min_retrieval_results`—, así que el asistente responde
> con **un solo fragmento** sobre un corpus de 23.306. Medido: 25 de 25 respuestas con una sola
> fuente. Va delante de VIS.4/VIS.5 porque cambia la anchura del contexto, y con ella los scores
> y la calibración del umbral: medir lo otro antes sería medir sobre una base que va a moverse.
> Y `retrieval_top_k` es editable desde el panel, así que hoy un admin puede ajustar un número
> que no hace nada.
>
> **VIS.4 y VIS.5 se intercalan entre AIS y Deploy** (decisión del usuario, 2026-08-24). Salen de
> medir el asistente normativo contra el lote ujirag y **van antes del despliegue a propósito**:
> las dos tocan lo que ve quien pregunta —qué versión se le cita y de qué se le avisa— y el piloto
> es justo cuando eso deja de ser una hipótesis. Reabren un bloque cerrado el 2026-07-31, que es
> lo correcto: son la continuación natural de la canónica bilingüe de VIS.3.
>
> - **VIS.4** — primero vigente, después lengua. Hoy `PreferLanguagePolicy` no distingue «la única
>   versión está en otra lengua» de «la única versión es de otro curso», y en el corpus real las
>   directrices de 2026/2027 sólo están en castellano y las de 2025/2026 sólo en valencià.
> - **VIS.5** — el aviso de traducción avisa del idioma de la **pregunta** en vez de del de la
>   **fuente**, y se calla cuando se pregunta en castellano, que es el caso más frecuente: 195 de
>   290 normas sólo existen en valencià.
>
> **Y dentro de Deploy, D.6.1** (nuevo, antes de D.7): publicar el buscador y los HTML de las
> normas en la misma VM con los enlaces al bucket, e incrustar el widget ahí. Sin eso,
> `CORPUS_SITE_BASE_URL` sigue en `127.0.0.1` y las citas del asistente sólo funcionan en el
> portátil de quien lo desarrolla — medido: 16 de 25 respuestas llevaban enlaces a localhost.

**Modelo sugerido para el próximo prompt**: **Sonnet** para AIS.2 — retirada mecánica de material
de fork (`DEV_ADMIN_EMAIL` por entorno, prompts institucionales al catálogo de actividades,
selectores de spider a dato) con verificación por `grep`; el alcance está cerrado.

**Pendiente nuevo que dejó AIS.1, y no estaba en la auditoría**: la cascada de temas es **ciega al
modo**. Escribe un solo valor para `--primary` y se aplica igual con fondo claro que oscuro, así que
el color de una organización pensado para el panel claro se pinta sobre el oscuro. Arreglarlo exige
que el bloque claro derive también de la semilla `--marca`, y eso pasa por enseñar a
`test_rev9_la_paleta_es_una.py` a resolver un salto de `var()`. Es prompt propio (candidato a
AIS.1.1 o a MT.11, que es donde la paleta gana interfaz). La auditoría de
`docs/VALORACION_PROYECTO.md` (2026-08-24) confirmó que los diez hallazgos de julio están resueltos,
pero los bloques REV y MT abrieron regresiones nuevas —`library_router` sin auth, `api_key` en claro,
dos routers de configuración sin tenencia— que son **bloqueantes de despliegue con datos reales**; SEC.9
las cierra y adelanta MT.16 (el único test que valida el aislamiento, que un piloto monoorganización no
ejercita). AIS cierra la deuda de calidad y de aislamiento del núcleo que conviene resolver antes del
piloto, con la paleta del panel (AIS.1) como bloqueante de facto del modelo open source. Lo genuinamente
post-piloto queda anotado en el §"Lo que este bloque NO hace" del Bloque AIS.

**Modelo sugerido para el próximo prompt**: **Opus** para SEC.9.1 — es el hallazgo crítico del bloque
(`library_router` sin autenticación con oráculo de firma RSA) y decide el modelo de identidad del endpoint.

**Nota histórica (contexto previo, ya no es el cursor):** la fase 1 del Bloque MT quedó completa el 2026-08-24 (MT.1 a MT.7), y era lo único que el usuario puso delante del piloto; la fase 2 del bloque va después del piloto. Antes, REV cerró el 2026-08-23 con REV.13 (y de ahí PLAT e IDE). El **Bloque INF quedó completo** el 2026-08-20 (los 10
prompts) y el 2026-08-21 se preparó el repositorio para abrirse: limpieza de la raíz, licencia,
gobernanza y DCO. Ese trabajo no es un bloque del plan y no mueve el cursor, pero deja dos bloques
nuevos (NIC y REPO) y un orden que no se puede invertir. El 2026-08-22 se planificaron otros dos —**PLAT** e
**IDE**— y el usuario los puso **delante del despliegue**.)_

**IDE y PLAT van ANTES de Deploy** (decisión del usuario, 2026-08-22): «no tiene sentido hacer el deploy de una
aplicación con una estructura y unos mecanismos de identificación que no son los que se van a utilizar». Se sostiene
solo: entre los dos bloques hay **dos migraciones de esquema** (IDE.2 renombra `hub_sso_users`, IDE.5 cambia
`hub_module_grants`), **dos cambios de autorización** (IDE.1 la autoridad del rol, PLAT.5 los `require_module`) y
**el cambio de todas las URL del panel** (PLAT.2). Las tres clases de cambio son baratas antes de que haya personas
reales dentro y caras después: una migración sobre una base vacía no tiene riesgo, y cambiar la autorización cuando
nadie depende de ella no echa a nadie fuera.

**Con una salvedad de orden, que es una dependencia y no una preferencia**: PLAT.1 y PLAT.2 se ejecutan **antes** de
IDE, porque las pantallas de IDE.4 e IDE.5 cuelgan de `/plataforma` —la sección que crea PLAT.2— y porque mover
«Modelos LLM» a una sección en la que un admin no puede entrar le quita un acceso que hoy tiene, que es lo que
reparte PLAT.1. Los dos ya estaban marcados como adelantables por otro motivo: arreglan solos el 403.

**Y deja una tarea para el bloque Deploy**: IDE.1 introduce un ajuste nuevo —la autoridad del rol— que el inventario
de variables de entorno del despliegue tiene que incluir. Omitirlo significa desplegar con el valor por defecto sin
que nadie lo haya decidido.

**Coste asumido**: 12 prompts entre el cursor y D.0, y el piloto se retrasa lo que tarden. Es decisión del usuario.

**Deploy iba ANTES de NIC**, y la razón principal caducó el 2026-09-04. Era que `AGENTS.md` manda
borrar la cuarentena «una vez verificado que todo lo migrado funciona en producción», y NIC.5 **era**
ese borrado; a eso se añadía que NIC.1 decide qué cuenta como «cubierto» y producción es el único
sitio donde esa respuesta se comprueba.

**NIC.3 hizo el borrado antes de esa verificación, por decisión explícita del usuario**, y conviene
que quede escrito qué se aceptó al hacerlo. La regla protegía algo real: la cuarentena era la
referencia mientras el código nuevo se estabilizaba contra escenarios reales, y el despliegue no ha
recorrido en producción todo lo migrado. Lo que la volvió inaplicable es lo que midió NIC.2: la
cuarentena contenía código que **no compila** —`client_app/` tenía 28 imports activos hacia diez
ficheros movidos allí sin reapuntar a sus importadores— y no se podía vaciar fichero a fichero,
porque 48 de los 67 candidatos tenían quien los importara y el bloqueo era transitivo. Una
referencia que no arranca no protege de nada.

**Y la referencia no se perdió, cambió de sitio**: el historial de git de este repositorio, la
carpeta `AutomatIA` y el *bundle* de GenGov, con `INVENTARIO_RETIRADA_LEGACY.md` como mapa. El
historial es mejor que la cuarentena en lo que importaba —viaja con el repositorio y no se puede
perder— y peor en una cosa: hay que saber que está ahí. Por eso el inventario sobrevive y lo dice.

De las razones originales sobreviven dos, y siguen siendo ciertas: NIC **no le ahorra nada al
despliegue** (comprobado: el `Dockerfile` sólo copia `shared/`, `server/app/`, `server/migrations/`
y el `.venv` — `client_app/` nunca entró en la imagen), y **NIC.4 toca el `pyproject.toml` de la
raíz**, que es lo último que conviene mover justo antes de desplegar por primera vez. Secuencia vigente:
**PLAT.1 → PLAT.2 → IDE.1…IDE.5 → PLAT.3…PLAT.7 → Deploy (D.0–D.6) → pruebas humanas y RAG.6b → REV → NIC → REPO.**

**Ya alineado antes de D.0**: el `Dockerfile` construía en Python 3.11 y la suite corre en 3.13.
Corregido y verificado construyendo la imagen (Python 3.13.15 dentro, `xmlsec` y `onelogin.saml2`
importan, `server.app.main` con 163 rutas), con tres guardarraíles para que no vuelva a derivar.
**Pendiente aparte**: `requires-python` sigue en `>=3.11` en los cinco pyproject; estrecharlo obliga
a re-resolver cinco locks y no debe viajar con el despliegue.

### El orden, y por qué

**PLAT.1 → PLAT.2 → IDE → PLAT.3…PLAT.7 → Deploy → pruebas humanas y RAG.6b → REV → NIC → REPO.** (NIC.5 era «el usuario borra `_legacy_nicegui/`»; NIC.3 lo hizo el 2026-09-04.)

Dos decisiones distintas lo fijan. La primera es del usuario (2026-08-21): **REPO no se ejecuta hasta
que la migración esté hecha**, porque no tiene sentido montar el repositorio definitivo y acto seguido
meterle la retirada de 500 ficheros de legacy. La segunda salía de `AGENTS.md`: `_legacy_nicegui/`
se borraba «una vez verificado que todo lo migrado funciona en producción», así que NIC.5 no podía
preceder al despliegue. **Esa segunda decisión ya no aplica**: NIC.3 retiró la cuarentena el
2026-09-04 por decisión del usuario, con el razonamiento y lo que se aceptó al hacerlo escritos más
arriba. La primera —REPO después de la migración— sigue en pie y es la que fija el orden.

**REPO no depende técnicamente de NIC.** Si abrir el repositorio pasara a tener fecha, se desengancha:
la dependencia dura es sólo la de los objetos huérfanos, que va de borrar el repositorio viejo y no
tiene nada que ver con el código legacy.

### Lo que espera a una persona, no a un agente

1. **Las pruebas manuales del Bloque INF**: `pruebas_manuales/pruebas_manuales_bloqueINF.bat`, cinco
   pasos. Lo irreducible: si el texto que la IA escribió sobre las tablas reales dice algo cierto, si
   el DOCX se lee, y los permisos por módulo, que necesitan dos cuentas.
2. **REPO.2** — retirar los otros dos repositorios antiguos. **REPO.1 ya está hecho** (issue
   #5: esta entrada decía lo contrario): historial filtrado y empujado el 2026-09-15, con la
   purga de GitHub **verificada** el 2026-09-16 —los cuatro huérfanos dan 422 y `git fetch` no
   los descarga—. Los pasos de REPO.2 están en `planificacion/fase1/61_BLOQUE_REPO.md`,
   versionados a propósito: el guion detallado vivía en `_local/`, que es ignorada y de usar y
   tirar. Y **el respaldo sigue en el portátil**, que es justo donde no debe estar; eso no ha
   cambiado.
3. **El Camino 3 de redacción, sin verificar del todo** — *trasladado aquí por REPO.3 al retirar
   `docs/PRUEBAS_PENDIENTES.md`, 2026-09-07*. Falta un borrador real con bloques
   `AI_ASSISTED_TEXT` (vía `/redaccion/llm-drafts/approve-as-workspace`), la anonimización con
   datos sintéticos, y abrir el export en Word y Adobe reales. Es el único punto del documento
   retirado que seguía abierto: los otros —el 500 de `templates`, el 403 del propio workspace, el
   `data-token` del widget— están arreglados y comprobados.

### Deuda de calidad que sigue abierta

*Trasladado por REPO.3 (2026-09-07) desde `docs/VALORACION_PROYECTO.md` §2.3, que se conserva
como instantánea fechada. De las siete deudas que aquel informe listaba el 2026-08-24, **seis se
cerraron** —`asyncio.to_thread` en `to_pdf`, el `create_all` del arranque (BD.2), el fallback de
`DATABASE_URL` (ahora `_dsn()` falla duro en producción), los fragmentos en diferido del frontend,
`client_app/` (NIC.3) y el mapa de anonimización (AIS.5 lo retiró por decisión, aplazado a
F2.A.4)—. Sobrevive una, y ha empeorado:*

- **Higiene de arranque y observabilidad.** El informe contó **157** llamadas a `print()` en
  `server/app/`; medidas el 2026-09-07 son **186**. Ya hay tres `basicConfig`/`dictConfig` en
  `app/`, así que la parte de «sin configuración de logging» está a medias, pero los `print()`
  crecen. En producción la observabilidad sigue siendo stdout sin niveles ni marcas de tiempo.
  Sin bloque asignado.

### Lo que se hizo el 2026-08-21 y conviene no repetir

- **La raíz pasó de 89 entradas a 15 ficheros y 16 directorios.** La documentación a `docs/`, los
  planes y el cursor a `planificacion/`, los 15 `.bat` a `pruebas_manuales/` (cada uno con
  `cd /d "%~dp0.."` para seguir ejecutándose desde la raíz), y los datos de trabajo a `_local/`,
  que está ignorada. Borrado el código muerto: `desarrollo/`, siete scripts de un solo uso, `MAP.md`,
  `utils/`, `styles/`, `tmp/`, `copia/`, `data_test/`, `.benchmarks/`.
- **`HISTORIAL.md` es nuevo y es donde va el historial.** Se separó de este fichero porque era el 85%
  de sus 626 KB y este se lee entero al arrancar cada sesión; ahora son 104 KB. **Al cerrar un prompt
  la fila nueva va arriba de la tabla de `planificacion/HISTORIAL.md`**, no aquí.
- **AGPL-3.0-or-later**, con titularidad de la UJI, procedencia INNOVAP (Derecho Público e
  Innovación) y autoría de Modesto Fabra. Gobernanza en genérico —un principal y el fork de cada
  organización que despliega, sin fork privilegiado— y **DCO obligatorio, también en el principal**,
  comprobado por `.github/workflows/dco.yml`. Todos los commits van firmados (`git commit -s`).
- **Pendiente que la AGPL impone a este despliegue**: el §13 exige que una aplicación web ofrezca a
  sus usuarios el fuente de **la versión desplegada**. Tiene que ser configuración (`SOURCE_URL`), no
  una URL fija al principal, y verse también en el **widget público embebido**. Sin implementar.
- **Las acciones de CI a su major actual** (checkout/setup-python/setup-node/upload-artifact v7,
  download-artifact v8, setup-uv v10.0.1 fijada porque no publica mayor flotante). Y arreglado un
  rojo de CI que llevaba desde INF.4: el mock de `redaccion-llm-draft-preview.a11y.test.tsx` no tenía
  `useDescribeSampleFile`. **`npm test` no incluye la suite de accesibilidad**: al cerrar un bloque
  que toque frontend hay que correr también
  `npx vitest run --config vitest.a11y.config.ts --no-file-parallelism`.

## 👉 (2026-08-20, al planificar el Bloque INF)

**Cursor actual: INF.3.** INF.1 e INF.2 completos el 2026-08-20, y con ellos **el flujo del
módulo llega al final**: verificado en navegador de punta a punta sobre el informe real del
usuario, desde dos bloques de IA fallidos hasta `preview = 200` y `export = 200`.
**Modelo sugerido para el próximo prompt: Sonnet** — INF.3 tiene alcance cerrado: el 409 ya
trae `pending_block_ids`, y lo que falta es contarlo donde se ve y poder volver de la vista
previa.

**Los dos caminos del módulo de informes no llegan al final hoy.** Las dos causas de fondo, con su
sitio en el código, están en la fila del bloque en la tabla de arriba y desarrolladas en
`Plan_TDD_Fase1.md` §Bloque INF. En una línea cada una: hay **dos disparadores de la generación y uno
se salta la subida de datos**, y **el servidor y la pantalla no usan la misma definición de
«pendiente»**, así que un bloque de IA que falla bloquea el informe sin ofrecer ninguna acción.
**INF.1–INF.3 son los tres que desbloquean el flujo**; el resto no se puede probar de punta a punta
sin ellos.

**Decisión ya tomada por el usuario (2026-08-20)**: el control de acceso al módulo se resuelve **por
módulos concedidos, no con un rol nuevo**. Es INF.7, y es independiente del resto: puede adelantarse
si la apertura del módulo a toda la organización corre prisa.

**Un hallazgo del análisis sin confirmar**, y el único que puede ser un falso positivo: el usuario vio
el estado de cada bloque dos veces. Puede ser solo el `<span className="sr-only">` de
`WorkspaceEditor.tsx:74-76` saliendo al copiar el texto. Se comprueba en navegador en INF.8, antes de
tocar nada.

**El Bloque LEG está completo (LEG.1–LEG.5)** y con él **desaparece el último rojo conocido de la
suite**: 2488 passed, 3 skipped, 0 fallos, sin el flake de `tests/test_prompts.py`. El servidor ya no
escribe en la base de datos al arrancar, que era la causa común de ese flake y de los arranques
fallidos en desarrollo. **Medido de nuevo el 2026-08-20 con el venv reconstruido: 2618 passed, 1
skipped, 0 failed** (11:36 con `-n auto`).

**Siguen pendientes las tres tandas de pruebas
humanas**, todas escritas y en la raíz del proyecto:

1. `pruebas_manuales_bloqueVER.bat` — ocho pruebas, cubre VER + PRO + la PRUEBA H rehecha en GUI.
2. `pruebas_manuales_bloqueSEG.bat` — una sola pregunta: ¿sirve la valoración que propone la IA?
3. `pruebas_manuales_bloqueRAS.bat` — ¿son ciertos los hallazgos?, ¿molestó el rastreo al servidor?,
   ¿qué páginas merecen entrar en el asistente?

**Dos cosas que sólo puede hacer la persona**: preguntar a quien gestiona el portal por el rastreo
—el User-Agent es `GovGenAI-Curacion/1.0 (+contacto)`— y por la línea del `robots.txt` que excluye a
ClaudeBot de `www.uji.es`.

**Y una decisión pendiente sobre el árbol de trabajo**: los dos ficheros de entrada del informe de
doctorado siguen en la raíz sin añadir a git (`Informe Resumen Programa de Doctorado en Ciencias
(90162).md` y `Prompt_informe.txt`). Conviene moverlos fuera o ignorarlos.

Debajo, el registro del cierre de RAS.

## 👉 (2026-08-18, al cerrar el Bloque RAS)

**El Bloque RAS está completo (RAS.1–RAS.5)** y el rastreo del apartado de la Escuela de Doctorado
funciona de punta a punta: 351 páginas en 12 minutos, rastreo completo, **20 hallazgos y los 20
ciertos** (venían 500). Detalle y coste en `docs/CASO_CURACION_ESCOLA_DOCTORAT.md`.

**Lo siguiente son las dos pruebas humanas pendientes**, que ya están escritas:
`pruebas_manuales_bloqueRAS.bat` (¿son ciertos los hallazgos? ¿el rastreo molestó al servidor? ¿qué
páginas merecen entrar en el asistente?) y `pruebas_manuales_bloqueSEG.bat` (¿sirve la valoración que
propone la IA?). Y sigue pendiente `pruebas_manuales_bloqueVER.bat`.

**Dos cosas que la persona tiene que hacer y el agente no puede**: preguntar a quien gestiona el
portal si el rastreo aparece en sus registros —el User-Agent es `GovGenAI-Curacion/1.0 (+contacto)`—
y decidir qué hacer con la línea del `robots.txt` que excluye a ClaudeBot de todo `www.uji.es`.

**Bloque LEG** sigue planificado y sin ejecutar (retirada del legacy de prompts, que es lo que
colisiona con la suite).

**Un límite conocido del rastreo**: cada página del portal repite su menú completo, y eso viaja al
corpus con el contenido. Quitar el *boilerplate* no está hecho.

Debajo, el registro del cierre de SEG.

## 👉 (2026-08-18, al cerrar el Bloque SEG)

**El Bloque SEG está completo (SEG.1–SEG.5)** y con él el módulo de Informes hace lo que el
usuario describió: las tablas se pintan del dato, la valoración la propone la IA sobre **su** tabla
y el técnico la aprueba o la edita. Verificado con el informe real de un programa de doctorado.

**Lo siguiente es la persona, y es una sola pregunta**: `pruebas_manuales_bloqueSEG.bat` —¿la
valoración que propone la IA le sirve a quien firma el informe? Todo lo mecánico está comprobado en
navegador y no se repite.

**Sigue pendiente el `.bat` anterior**: `pruebas_manuales_bloqueVER.bat` (ocho pruebas, cubre VER +
PRO + la PRUEBA H rehecha en GUI).

**Dos bloques planificados y no ejecutados**: **LEG** (retirada del legacy de prompts, que es lo que
colisiona con la suite) y **RAS** (rastreo de un portal real, con la Escuela de Doctorado como caso
guía — la misma unidad que el caso de SEG).

**Un aviso sobre el árbol de trabajo**: en la raíz del repo hay dos ficheros sin seguimiento que
son datos de entrada del usuario (`Informe Resumen Programa de Doctorado en Ciencias (90162).md` y
`Prompt_informe.txt`). **No se han añadido a git a propósito** —informes fuente fuera del repo— y
conviene decidir si se mueven fuera o se ignoran, para que un `git add -A` no los suba.

Debajo, el registro del cierre de GUI.

## 👉 (2026-08-18, al cerrar el Bloque GUI)

**El Bloque GUI está completo (GUI.1–GUI.6)** y salió de una sola frase del usuario al ir a
probar: las plantillas no se podían borrar ni editar. Detrás había cinco huecos del mismo tipo, y
el peor era que **la PRUEBA H no se podía hacer**: el borrador no podía proponer un bloque de
transformación, así que el ETL de PRO.4 y PRO.9 era inalcanzable desde la interfaz. Ya se puede,
y está verificado con el modelo real sobre una hoja con importes en texto.

**Lo siguiente sigue siendo la persona**: `pruebas_manuales_bloqueVER.bat` (ocho pruebas, cubre
VER + PRO) **con la guía de pantallas** que se entregó como artefacto. La PRUEBA H está rehecha
para el camino que ahora existe.

**Un hueco conocido y no cerrado**: no hay pantalla para editar los bloques de un informe ni para
aplicar lo que el copiloto propone. Los bloques se crean describiendo el informe. Documentado en
la guía y en el propio panel.

Debajo, el registro del cierre de PRO.

## 👉 (2026-08-17, al cerrar PRO.8 y PRO.9)

**PRO.8 y PRO.9 están cerrados, y ahora sí toca la persona.** Los dos salieron del mismo criterio
del usuario —lo usual se elige sin programarlo— y en los dos la comprobación dio algo que no se
esperaba: en gráficos, que pedir «barras horizontales» costaba **generar un script** y que una
plantilla **no podía ni poner un título**; en ETL, que **lo determinista del legacy ya estaba
portado entero**, así que lo que faltaban eran cuatro operaciones que allí tampoco existían.

**Lo siguiente: `pruebas_manuales_bloqueVER.bat`** en la raíz (cubre VER **y** PRO). **Ocho
pruebas**, y las tres que importan de PRO son **F** (calidad del script sobre un fichero real de
la UJI), **G** (si el copiloto es útil o sólo correcto) y **H, nueva** (una hoja de cálculo tuya
de verdad: que el plan ponga `to_number` antes de sumar, y que una hoja en formato inglés falle
diciéndolo en vez de dar otra cifra).

Debajo, el registro de cierre de los siete primeros prompts.

**El Bloque PRO está completo**, con PRO.2.1 añadido a mitad de camino. El módulo de Informes
ya hace de punta a punta lo que prometía: pedir un script en lenguaje natural, auditarlo con dos
modelos de dos niveles, ejecutarlo en el sandbox contra un fichero real, aprobarlo, extraer con
él dentro de un informe, transformar los datos, dibujar un gráfico, **ver todo eso en la vista
previa** y **descargar el DOCX**. Y el copiloto responde con citas a la documentación real.

**Lo siguiente, y ahora sí depende de una persona: `pruebas_manuales_bloqueVER.bat`** en la raíz
(cubre ya VER **y** PRO). Siete pruebas —ocho al cerrar PRO.9—, y dos son las que importan de la
primera mitad de este bloque:
**F — la calidad del script del modelo sobre un fichero real de la UJI** (el agente prueba con
un Excel sintético cuyas columnas inventó él, así que no puede saber si la tabla es la que se
pedía) y **G — si la respuesta del copiloto es útil o sólo correcta**. Las otras cinco siguen
siendo las de VER: calidad editorial, exportación abierta en Word y Adobe, anonimización con
datos reales, rastreo de una web con enlaces en HTML y el asistente de Gerencia contra su
gemelo agéntico.

Después, el **despliegue del prototipo en GCP** (`docs/DESPLIEGUE_PROTOTIPO_GCP.md`), que sigue
pendiente de dos cosas del usuario: las cuentas locales para los probadores de Gerencia y la
credencial del sitio publicado en el bucket.

**Dos cosas anotadas y no hechas, cada una candidata a prompt propio**: (1) retirar el legacy de
prompts **de este repositorio** —`ExtractionServiceConfig`, `seeds_prompts.py` y el `main.py` de
la raíz, con `tests/test_prompts.py` sembrando la base de datos del desarrollador y siendo
inestable con `-n auto`—. ~~(2) los diez tipos de gráfico del legacy~~ **→ pasó a ser PRO.8**.

**Una cosa del entorno que quedó así, a propósito**: el sandbox del stack de producción no
publica su puerto, así que para probarlo desde un backend en el host se levantó una instancia
aparte en el 5099.

> ⚠️ **Corregido el 2026-08-20: el «huérfano del 8000» no era inmatable.** Esta nota decía que
> el backend de desarrollo corría en el **8001** porque el 8000 lo retenía «un proceso huérfano
> que no responde a `taskkill`», y de ahí la deriva a 8001 y luego al 8002 de
> `frontend/.env.local`. **Ninguna de las dos mudanzas hacía falta.**
>
> El mecanismo real: cuando uvicorn `--reload` falla en el arranque (típicamente por la BD
> apagada), **el árbol de procesos no muere**. El padre se queda con el socket en estado
> **`Bound`**, no `Listening`, así que `netstat | findstr LISTENING` no lo ve —el puerto parece
> libre— pero `bind()` falla con `WinError 10048`. Lo que no funcionaba era matar **un** PID:
> el resto del árbol mantiene el socket. Matando los tres a la vez el puerto se libera.
>
> ```powershell
> Get-NetTCPConnection -LocalPort 8000 | Select LocalAddress,State,OwningProcess
> Get-CimInstance Win32_Process -Filter "ProcessId=<PID>" | Select ParentProcessId,CommandLine
> Stop-Process -Id <los PID del árbol entero> -Force
> ```
>
> `frontend/.env.local` vuelve a apuntar al **8000**, que es lo que levanta `arranque.bat`.
> Mientras apuntaba al 8002 y el backend arrancaba en el 8000, toda llamada a la API desde el
> frontend en dev daba 502. Si el 8000 vuelve a dar 10048, se limpia el árbol; no se cambia de
> puerto.

**Fuera del alcance de VER, documentado**: `POST /redaccion/scripts/propose` y
`POST /redaccion/copilot/ask` siguen siendo stubs 503 por decisión del usuario.

El Bloque PIL quedó completo el 2026-08-15; el registro anterior se conserva debajo.

---

**Lo siguiente era el Bloque PIL**, que es lo que convierte la plataforma en algo que se puede
enseñar: los dos asistentes del piloto con el corpus normativo real (298 y 124 documentos),
embeddings por Vertex y pruebas en local antes de desplegar. Empieza por **PIL.1** (el
adaptador de Vertex y el embebido por lotes), que bloquea toda la ingesta. Prerrequisitos que
aporta el usuario: Docker arrancado, y proyecto/región de GCP con la Vertex AI API habilitada
y credenciales ADC en la máquina.

D.0 (Deploy) sigue esperando los mismos datos de GCP, y MAN.2 sigue esperando ejecución
humana. El registro anterior se conserva debajo.

**Cerrados desde la última revisión del cursor**: SEC.8 (los 8 prompts), EXT (los 3) y FAQ
(los 2). Suite backend **1819 passed, 3 skipped, 0 failed**; frontend 281; `tsc` limpio.

**El usuario está extrayendo los XML consolidados del BOE**, que es el prerrequisito de la
base documental de Gerencia. Mientras tanto, lo que se puede avanzar en la aplicación **sin
depender del corpus**, por orden de valor:

1. ~~**D.4.0**~~ ✅ **hecho el 2026-08-11** (`c92dc47`). La app pasa de 627 MB a **345 MB** y
   arranca en **9,4 s** sin el extra. `e2-small` basta para la VM.
2. ~~**Arreglo de los perfiles de grafo sin configurar**~~ ✅ **hecho el 2026-08-11**
   (hallazgo I5). Eran **dos**, no uno, y el test de contrato certificaba que compilaban.
3. ~~**REV.1**~~ ✅ **hecho el 2026-08-11**. El veredicto del revisor, con su cola de
   pendientes, sus filtros y sus columnas en el CSV. Migración `v9e0f1g2h3i4` aplicada.

4. ~~**FIX.4**~~ ✅ **hecho el 2026-08-11**. La carga del corpus embebe con el modelo
   configurado, comprueba el espacio vectorial **antes de escribir**, y **vuelve a
   arrancar**: estaba rota con SIGSEGV en Windows desde D.4.0.

5. ~~**DER.1**~~ ✅ **hecho el 2026-08-11**. `--chatbot-id` repetible: el mismo corpus en
   varios asistentes en una pasada, leído y validado una sola vez.

6. ~~**DER.2**~~ ✅ **hecho el 2026-08-11**. Hallazgo `copia_divergent`, aviso antes de borrar
   con borrado en cascada opcional, y aviso de deriva al terminar cada carga.

7. ~~**DER.3a**~~ ✅ **hecho el 2026-08-11**. `docs/REQUISITOS_PUBLICACION_PLATAFORMA.md`,
   para llevar a la reunión con la unidad de desarrollo.

**El bloque DER queda cerrado en todo lo que no depende de terceros.** DER.3 sigue bloqueado
a la espera de que la unidad de desarrollo conteste al entregable. La carga del corpus está
lista para los dos asistentes del piloto.

**Lo siguiente, si no hay otra prioridad**: el Deploy GCP (D.0), que espera datos tuyos
—proyecto, región, credenciales—, y MAN.2, que espera ejecución humana.

**El bloque COR quedó planificado y descartado el mismo día (2026-08-11)**: compartir el
documento entre chatbots no compensa. La deduplicación de fragmentos solo se dispararía si
coincidieran modelo de embedding y estrategia de troceado, y el piloto **varía la estrategia
a propósito**; el problema de mantenimiento se resuelve con un solo `.md` en disco y dos
cargas incrementales; y las filas separadas conservan que cada asistente elija su modelo de
embedding. Razonamiento completo —incluidos **dos argumentos míos que eran incorrectos**— en
la cabecera del bloque en `Plan_TDD_Fase1.md`. Queda un candidato sin planificar: un hallazgo
de curación que detecte **deriva** entre copias de la misma norma.

**Pendiente de acción del usuario, no de código**: MAN.2 (ejecutar
`pruebas_manuales_plataforma.bat` de principio a fin; el paso de subir un PDF al corpus ya se
actualizó a `.md` tras EXT.1). Y **D.0/D.2/D.3** esperan datos de GCP (proyecto, región,
credenciales), no al corpus.

**Modelo sugerido: Sonnet** para D.4.0 y REV.1.

---

**Cursor: Bloque PIL (PIL.1), y detrás el Deploy GCP empezando por D.0. MAN.2 espera ejecución humana** — **BLOQUE CAL COMPLETO el 2026-08-09** (CAL.1 `944bb48`, CAL.2 `bec3300`, CAL.3 `393ce03`, CAL.4 `57d538a`, CAL.5 `d13353f`, cierre `5c7774d`, CAL.4.1 `7e4f435`) y **BLOQUE CUR COMPLETO el 2026-08-09** (CUR.1 `d1b9453` + fix `fd39ee9` + fix `d9ed15f`, CUR.2 `ca53cd5`). **BLOQUE SEC COMPLETO**: SEC.1 (`3a7b5a4`), SEC.2 (`2ad9125`), SEC.2.1 (`3c4fa24`), SEC.3 (`35cfdcb`), SEC.4 (`7127e36`), SEC.4.1 (`2ddc121`), SEC.5 (`d59c842`), SEC.7 (`d0712b6`), FIX.2 (`18f8969`) y FIX.3 (`1f58f53`).

> 🧹 **Tres scripts huérfanos borrados (Caso B, decisión del usuario el 2026-08-03).**
> `scripts/verify_fix.py`, `scripts/diagnose_startup.py` y `scripts/init_rpa_prompts.py` eran
> los únicos llamantes del shim `init_db` que retiró CAL.5. Importaban rutas anteriores al
> monorepo (`app.database.*`, `app.services.*`, `app.core.*`) que ya no existen, así que **no
> podían ejecutarse**; ni siquiera entre ellos —`diagnose_startup` llamaba a un
> `init_rpa_prompts` de `app.database.seeds` que `main.py:91` ya documentaba como inexistente—.
> Nadie los invocaba desde fuera. El historial de git es la fuente de verdad de lo que hacían.

> ⚠️ **La suite backend en paralelo también da un falso rojo en esta máquina.**
> `tests/infra/test_setup_script.py::test_should_check_docker_and_required_ports` invoca
> `bash setup.sh --dry-run` con un timeout de 60 s; con `-n auto` y 16 workers compitiendo, el
> script no acaba a tiempo y el test cae por **TimeoutExpired, no por aserción**. En serie el
> fichero da **12 passed en 10 s**. Es el gemelo backend de la nota de vitest de más arriba: si
> ves ese rojo, reprodúcelo con `-n0` antes de investigarlo. (CLAUDE.md ya avisa de este
> fichero por un motivo emparentado —resolución de `bash`—, pero la causa aquí es la
> contención, no PowerShell: la sesión corría desde Git Bash.)

> ⚠️ **Por qué existe CAL.4.1 (deuda medida que dejó CAL.4).**
> La paridad que CAL.4 dejó verde es de claves **del diccionario**, y la pantalla de documentos
> casi no tiene: **41 claves viven sólo como *default* dentro del `t('clave', 'texto')` del
> código** y no existen en `es/ca/en admin.json`. El efecto se ve a simple vista poniendo
> `i18nextLng=ca` en `localStorage`: la navegación sale en catalán y **el cuerpo de la pantalla
> se queda en castellano**, que es justo lo que CAL.4 pretendía arreglar. Reparto medido:
> `DocumentsTable` 12, `IngestionJobsPanel` 7, `RechunkControls` 7, `DocumentsPage` 5,
> `RetrievalBanner` 4, `UploadDropzone` 4, `DocumentBadges` 2.
>
> **El test de paridad no lo caza por construcción**: lo que no está en el diccionario no se
> compara con nada. Por eso CAL.4.1 tiene que añadir un guardarraíl distinto —que ninguna clave
> del namespace `admin` viva sólo como default— y no basta con ampliar el de paridad.
>
> No se absorbió en CAL.4 porque el prompt acotaba `DocumentsPage` a *sus constantes*, y
> ampliarlo sobre la marcha habría vuelto a inflar un prompt que ya se había desbordado en
> CAL.2. Queda como prompt propio, que es lo que era.
**El uvicorn zombi ya no bloquea las pruebas manuales**: el PID 7576 del 2026-08-02 (arrancado sin `--reload`, quedándose `127.0.0.1:8000` por delante del reiniciado en `0.0.0.0:8000`) se paró el 2026-08-03 al verificar CAL.2 en navegador. Si vuelve a aparecer un 8000 duplicado, la comprobación es `Get-NetTCPConnection -State Listen -LocalPort 8000`. Lo único que no se puede probar en local sigue siendo el **SSO SAML real contra el IdP**.

> ⚠️ **La suite de vitest en paralelo da falsos rojos en esta máquina.** Con `-n auto` (el
> defecto) caen entre 1 y 15 tests por pasada, siempre distintos y casi todos con
> `STACK_TRACE_ERROR` —que es como vitest marca un *timeout*—, más el clásico «Axe is already
> running» de `A11y.test.tsx`. Los mismos ficheros pasan sueltos y **la suite entera da
> 255/255 con `--no-file-parallelism`**. Antes de investigar un rojo de vitest, reprodúcelo en
> serie; si en serie pasa, es contención, no regresión. Es el mismo motivo por el que CI del
> backend corre con `-n0` (ver TST.1).

---

## ✅ CAL.2 cerrado — la capa API del frontend sale del contrato (2026-08-03)

*(El traspaso «CAL.2 analizado y sin empezar» que ocupaba este sitio queda resuelto: ejecutado
entero, verificado en navegador y commiteado. Lo que sigue es lo que hay que saber para CAL.3.)*

### Lo que resultó ser el trabajo de verdad: el contrato no tenía los tipos

El prompt pedía «usar los tipos de `generated/model` (IngestionJob, HubDocument…)». **Esos tipos
no existían**, y no por un despiste de Orval: **los endpoints no declaraban `response_model`**, así
que FastAPI los documentaba como objeto vacío y Orval los generaba como `Promise<unknown>`. Migrar
a los hooks sin arreglar eso habría *movido* la interfaz escrita a mano de `shared/api/*.ts` a la
página, no eliminado. Por eso CAL.2 empieza en el backend:

- **`hub_ingestion_router.py`** — 10 modelos nuevos: `IngestionJob`, `IngestionJobsOut`,
  `HubDocumentOut`, `HubDocumentDetailOut`, `HubDocumentsOut`, `UploadDocumentOut`,
  `DeleteIngestionJobOut`, `ClearCollectionOut`, `AnalyzeHtmlOut`, `MessageOut`. Los 8 endpoints
  del panel declaran ya `response_model`.
- **`hub_feedback.py`** — `InteractionReviewOut` sustituye a `list[dict]`.
- **`hub_llm_configs_router.py`** — `AvailableModelsOut` y `LLMConnectionTestOut`, los dos huecos
  que quedaban en un router que ya tenía tipado el resto.

**Decisión que no se rediscute: `IngestionJob.status` es `str`, no `Literal`.** Es un campo de
presentación, la tabla ya tiene rama por defecto, y un valor inesperado en una fila debe pintarse
«en cola», no tumbar el listado entero con un 500 de validación de respuesta.

### La trampa de los `response_model` sobre objetos ORM (costó 3 rojos)

`chunks_processed`, `progress_current`, `progress_message`, `processing_stats` y `created_at` son
**NOT NULL con `default=` de SQLAlchemy**, o sea que el valor lo pone el *flush*, no el constructor.
Una fila leída de la BD siempre los trae; un `HubIngestionJob(...)` recién construido los tiene a
`None`. Tres tests montaban la sesión con `AsyncMock`, así que su job nunca pasaba por el flush y
el `response_model` nuevo lo rechazaba con razón. **Arreglado en los dobles, no en el modelo**:
`test_ingestion_storage.py` tiene ahora un `refresh` que rellena los defaults como haría el real, y
`test_job_progress.py` construye el job completo. Si añades un `response_model` sobre un objeto ORM,
mira primero qué columnas dependen del flush.

**Y no recortes campos al tipar**: la primera versión de `IngestionJob` se dejó fuera
`processing_stats`, que el endpoint sí devolvía —el `response_model` filtra en silencio— y tumbó el
test de progreso de RAG.12. El modelo describe lo que ya se sirve; no es la ocasión de podar.

### Retirada del panel de fuentes: hecha

Se ejecutó la opción B ya decidida. `DocumentsPage` pasa de **1.019 a ~610 líneas** y de 3 pestañas
a ninguna (con una sola vista, la barra sobra). Fuera: `AdminIngestionAssistant.tsx` y su test, y
los 5 módulos manuales de `shared/api/`. El analizador de HTML (`/hub/ingestion/analyze-html`,
endpoint vivo) cae con el asistente porque su botón de guardar iba al 404 de `createSource`;
recuperarlo es repuntarlo a `/hub/sites/{id}/analyze`, y eso es producto, no limpieza.

### Dos extensiones sobre el alcance literal del prompt

1. **`copilotApi.ts` también se retira.** El prompt nombra 5 módulos, pero su criterio de cierre
   (`grep localhost:8000` = 0) lo alcanza, y su propio `// TODO CF.4` decía «cuando openapi.json se
   regenere con `/redaccion/copilot/*`» — ya está regenerado. Único consumidor: `CopilotPanel`.
2. **`LoginPage` deja de construir su `API_BASE`.** Ahora importa `apiBaseUrl` de `client.ts`, que
   es el único sitio del frontend donde vive el host. Su `fetch` **se queda**: el bucle de dos rutas
   con manejo explícito del 401 (SEC.1) no se traduce a axios sin cambiar comportamiento, y ahí no
   hay cabecera de autenticación que centralizar.

### `client.ts` ahora traduce `detail` a `error.message`

Al pasar de `fetch` a axios, las pantallas que pintan `err.message` habrían empezado a mostrar
«Request failed with status code 409» en vez del motivo. El interceptor de respuesta copia el
`detail` de FastAPI (string o lista de errores de Pydantic) a `message`. **Sin esto, migrar a Orval
degrada todos los mensajes de error del panel** — y no lo habría cazado ningún test de tipos.

### El guardarraíl que impide la recaída

`frontend/src/shared/api/__tests__/contractFirstApi.test.ts` lee el árbol de fuentes y falla si
alguien reintroduce un módulo API a mano, un `fetch` en `DocumentsPage`, un `localhost:8000` fuera
de configuración, o una cabecera `Authorization` construida fuera de `client.ts`. **Único exento:
`widget/hooks/useChat.ts`** (SSE; Orval no lo cubre y axios no expone el cuerpo incremental).
Exigió añadir `"node"` a `types` en `tsconfig.app.json`.

### ⚠️ Tras `git pull` de este commit hay que regenerar el contrato

`server/openapi.json`, `frontend/openapi.json` y `frontend/src/shared/api/generated/` están en
`.gitignore` (líneas 103-107), así que **el commit no los lleva**. Como CAL.2 introduce tipos
nuevos que el frontend importa, sin regenerar **el `tsc` falla**:

```
cd server;   uv run python export_openapi.py
cd frontend; npm run generate:api
```

### Desviaciones documentadas

- **Nombres**: el prompt sugería `HubDocument`; se usa **`HubDocumentOut`** porque `HubDocument` ya
  es la clase ORM en `operational_models.py` y colisionaría en el router. `IngestionJob` sí es literal.
- **Dos rojos preexistentes de `tsc` arreglados** para poder cumplir el criterio de cierre
  («tsc --noEmit en verde»), ambos ajenos a CAL.2: una prop `expandido` muerta en
  `TestScenariosPage` (el `<details>` gestiona su propio estado) y un cast que necesitaba
  `as unknown as` en `rol2_rename.test.tsx`.
- **Los tests que stubbeaban `fetch` global ahora doblan los hooks generados** (Organizaciones,
  AIBrain, LLMConfigs, Prompts, CopilotPanel). No es cosmético: axios **no pasa por `fetch`**, así
  que esos stubs habían dejado de interceptar y los tests medían pantallas vacías.

---

## ✅ SEC.2 y SEC.2.1 cerrados — el modelo de autorización, en una página

*(El traspaso «SEC.2 a medias» que ocupaba este sitio queda resuelto: los 6 rojos arreglados, el gate probando endpoints y todo commiteado. Detalle en las filas de SEC.2 y SEC.2.1 del historial.)*

### El modelo de tenencia, en cuatro líneas

- `UserInfo.organizacion_ids` + claim `orgs` en el JWT. Un token anterior a SEC.2 se lee **sin acceso**, no con acceso total.
- `server/app/core/auth/tenancy.py`: `puede_acceder`, `assert_org_access`, `scope_query_to_orgs`, `orgs_del_principal`. **Vacío significa lo contrario según el rol**: en un superadmin es «todas», en cualquier otro «ninguna».
- Frontera aplicada en `hub_chatbots_router` (listado acotado en SQL + `_get_chatbot_or_404` como único punto de lectura), `hub_chat`, `hub_feedback`, `hub_themes_router` y `hub_ingestion_router`.
- Claim poblado en el login de admin (organizaciones por `partner_id`) y en PAT (**heredado del dueño y resuelto en cada validación**: guardarlo en la fila lo congelaría y una revocación dejaría de revocar).

### Lo que añadió SEC.2.1

- **`assert_chatbot_access`** (`core/auth/chatbot_access.py`) es el único sitio donde se decide si alguien puede conversar con un chatbot: organización **y** modo de acceso, juntos. `hub_chat` ya no llama a `assert_org_access` por su cuenta, y hay un test que falla si el adaptador OpenAI (OWUI.1) o el endpoint del widget (D.1) nacen sin pasar por él.
- **`EffectiveActor` + `resolve_effective_actor`** (`core/auth/delegated_actor.py`): quién pregunta de verdad cuando la petición llega por un cliente de confianza. Lo consumirá la cuota de SEC.4 — se escribe **sobre el actor**, no sobre el principal, o la contabilidad por usuario nace mal.
- **`SAML_ORGANIZACION_ID`**: la organización del IdP. Un usuario SSO ya no entra sin acceso a nada.

### Lo que queda apuntado para más adelante

1. **La cabecera delegada no tiene consumidor todavía.** Está probada a nivel unitario; quien la usa de verdad es el Pipe de OWUI (OWUI.3), y el `via='widget_api_key'` de `assert_chatbot_access` espera a D.1. Ninguno de los dos bloquea nada ahora.
2. **RS256 para la cabecera** cuando haya más de un cliente delegante: cada uno querrá su clave y su rotación. Hoy hay uno, y HS256 con secreto compartido es lo proporcionado.
3. **El SSO real contra el IdP sigue en pruebas manuales pendientes** — la organización del IdP se ha probado contra la BD, no contra el IdP institucional.

### Tres decisiones que no se rediscuten

1. **`organizacion_ids` y `saml_groups` son tuplas, no listas** (el plan decía lista en los dos casos). `UserInfo` es `frozen` para que nadie amplíe permisos a mitad de petición, y una lista dejaba `.append(...)` disponible. Vale igual para los grupos, que ahora deciden el acceso en modo `restricted`.
2. **Un tema sin `organizacion_id` es de plataforma y exige superadmin**, y la organización del cuerpo se **valida** contra el token en vez de derivarse de él. Verificado que ninguna pantalla del frontend consume `/api/v1/hub/themes`, así que nadie empieza a recibir 403 por esto.
3. **`restricted` con las listas vacías no deja pasar a nadie salvo al superadmin.** La lectura contraria —«no hay restricción declarada, luego no restrinjo»— convierte un descuido de configuración en un chatbot abierto. Igual con un `access_mode` que el código no reconozca: no se interpreta, se cierra.

---

**Nota del cierre de SYNC (ya resuelta por SEC.1)**: se detectó que `/api/v1/auth/admin/login` no verificaba la contraseña. Cerrado en `3a7b5a4`.
**DEUDA DEL BLOQUE RAG: CERRADA el 2026-08-02.** La baseline del gate está regenerada en **MRR 0,940 · recall@5 0,960 · recall@10 0,960** (antes 0,8613 de RAG.1), así que la mejora de RAG.7 ya está protegida. Y los 0,02 están cuadrados **por medición, no por hipótesis**: son **una sola consulta** —«qui tutoritza les pràctiques externes?»— que pasa de rango 2 a rango 1, lo que vale exactamente 0,5/25 = 0,02. **La hipótesis de HNSW queda refutada**: con 52 chunks el planificador nunca toca el índice vectorial (`EXPLAIN` da `Sort` + top-N heapsort sobre un Index Scan por `chatbot_id`). Lo que hay debajo es un **empate exacto de coseno** (0,316227773316) entre dos fragmentos de documentos distintos, y el `ORDER BY` de las dos ramas del retriever **no tiene desempate**: cuál de los dos queda primero lo decide el plan de la consulta, no la recuperación. Detalle y controles en el historial.
**Recordatorio del orden vigente**: tras RAG.7→RAG.14 van SYNC, resto de SEC y CAL; después **Deploy empezando por D.0** (habilita los nueve servicios de GCP de una vez) y, solo entonces, **RAG.6b** (adaptador de Vertex + medición del valenciano), que depende de que D.0 haya habilitado Discovery Engine.

> **Por qué TST fue delante de RAG.2 (cerrado el 2026-07-30).** Quedan 39 prompts y todos se cierran comparando la suite. Esa comparación arrastraba 10 fallos que aparecían y desaparecían según la selección de tests, así que «sin regresiones» era una afirmación con asterisco. Ya no: `unit`+`integration` juntos dan 0 fallos y los guardarraíles de `tests/infra/test_suite_hygiene.py` impiden la recaída. **TST.3 (2026-07-30) cerró la deuda residual**: cero fallos y cero errores en toda la suite. **Ya no hay nada que filtrar al comparar la suite** — si aparece un rojo, es real.

> **La carga del corpus v1 queda pendiente y ya no bloquea nada.** RAG.1 resultó no necesitarla: construye su propio corpus de fixture (25 normas breves, embedding determinista) para el gate de CI. La carga real conviene hacerla cuando el front-matter esté completo — ya existe el script que lo emite y `md_frontmatter/` tiene los 226 con `url_oficial`, `title`, `language` e `id_publicacio`; faltan la revisión de consolidación en el panel y las columnas de catálogo del Hito A. Cuando toque: `bootstrap` → `ingestion.corpus.load --census --dry-run`.
>
> **Herramientas del corpus entregadas fuera del repo** (en `Descarregar_pdf/normativa_propia/publicacio_transparencia_2026-07/`): `genera_frontmatter.py` (front-matter derivado del catálogo + bloque `consolidacio` + clases de estado en los encabezados), `build_dashboard_consolidacio.py` (panel de revisión → `decisions_consolidacio.json`) y el parche de `build_pagines.py` para que el HTML emita `id` por artículo, que es lo que permite el enlace profundo desde el panel. El chunker del hub soporta `{#ancora .classe}` desde el fix del 2026-07-29.

> ✅ **BD de desarrollo reparada (2026-07-28).** Estaba sellada en `y6h7i8j9k0l1` con **cero tablas `hub_*`**: el esquema de `agents_hub` se perdió al recrear la BD durante el renombrado `AI_agents_hub`→`govgenai`. Reparada con la opción aprobada por el usuario: `create_all` desde el metadata del ORM **sin tocar las 56 tablas existentes ni mover `alembic_version` a mano**, dejando fuera `hub_vocabulary_terms` para que la creara su propia migración y el sello avanzara por la vía normal. Estado final: **79 tablas (23 `hub_*`), `alembic_version = z7i8j9k0l1m2`**. Después se alinearon **81 `server_default`** que `create_all` no pone (el ORM los declara del lado Python) tomando la referencia de una BD construida con `alembic upgrade head`: **0 diferencias** en las columnas comunes de las 23 tablas. La BD sigue **sin sembrar** (`bootstrap.py` pendiente, lo ejecuta el usuario porque fija la contraseña del SuperAdmin); ING.0.2 no lo necesita, ING.0.5 sí.
>
> 🐞 **Hallazgo de la comparación — fallo de despliegue en instalación limpia.** El ORM declara `HubIngestionJob.canonical_url` y `.original_filename` (`operational_models.py:237-238`) pero **ninguna migración las crea**: `e5f6a7b8c9d0` las trata como opcionales (`if _column_exists(...)`) porque las creó código fuera de la cadena. En una instalación limpia no existen, y `POST /hub/ingestion/upload` las escribe (`hub_ingestion_router.py:228`, más `watcher.py:266,277`) ⇒ **la subida de documentos revienta en un despliegue nuevo**. Es la misma familia que el fallo de `hub_ingestion_sources` que arregló 11.2. Se corrige en **ING.0.2**, que ya es el prompt de migración del modelo de datos de ingesta. Tercera diferencia, inocua: `hub_interactions.metadata` existe en instalación limpia y el ORM no la declara (columna muerta). **Fase 11 completa (11.1→11.3)** y **SEC.6 completo** (adelantado). Siguiente en el orden: ING.0 (ING.0.1→ING.0.5) → carga del corpus v1 + pruebas manuales → RAG.1 (baseline) → RAG.2 (consolidación) → **Bloque VIS (VIS.1→VIS.3)** → resto del Bloque RAG (RAG.3→RAG.14) → **Bloque SYNC (SYNC.1→SYNC.2)** → resto de SEC → CAL → Deploy GCP.

> **ORDEN VIGENTE (reescrito el 2026-08-03; manda sobre cualquier lista anterior de este fichero).**
> Hecho desde la última revisión: **RAG completo** (RAG.6a→RAG.14) · **Bloque DET ✅** ·
> **Bloque SYNC ✅** · **Bloque SEC ✅** (+FIX.1/FIX.2/FIX.3) · **Bloque CAL ✅** (CAL.1→CAL.5).
>
> **Quedan 17 prompts para cerrar la Fase 1**, en este orden:
> 1. **CAL.4.1** (1) — las 41 claves de la pantalla de documentos. **Decisión del usuario: la próxima sesión empieza aquí.**
> 2. **Bloque CUR** (2) — CUR.1→CUR.2. Va **antes** del Deploy y no después: los artefactos de D.4/D.5 codifican la estructura de módulos y la clasificación de routers, así que decidirla luego obliga a rehacer el pipeline y a repetir la verificación en producción. Un refactor pre-deploy sólo arriesga en local.
> 3. **Bloque MAN, parte local** (3) — MAN.1→MAN.3. Van **después de CUR** a propósito: CUR mueve módulos, y escribir los guiones antes sería documentar una estructura que está a punto de cambiar. Y van **antes del Deploy** porque un fallo encontrado en local cuesta un prompt; encontrado en producción cuesta un despliegue.
> 4. **Deploy GCP** (6) — D.0 primero, que habilita los nueve servicios de una vez —decisión del usuario del 2026-08-01— y sin el cual D.1-D.5 asumen APIs encendidas que nadie encendió.
> 5. **MAN.4** (1) — campaña contra el entorno desplegado. SSO SAML real, sistemas externos, Cloud Run/Cloud SQL/GCS y edge vs cloud. **No se puede empezar antes de D.5.**
> 6. ~~**RAG.6b** (1)~~ ✅ **HECHO el 2026-08-24, adelantado a petición del usuario.** No hubo que
>    esperar a D.0: `discoveryengine.googleapis.com` ya estaba habilitado en `uji-teclab`. Se
>    adelantó porque hacía falta para medir el asistente normativo en local contra el lote
>    dorado de 25 consultas reales. **Los dos riesgos abiertos, cerrados con datos**: el
>    valenciano funciona (documento correcto 0,7944 frente a señuelo 0,0504) y los scores del
>    Ranking API **ya vienen en [0,1]**, así que `normalize_score` NO se les aplica.
> 7. **Bloque OWUI** (3) — OWUI.1→OWUI.3, post-deploy.
>
> **La carga del corpus v1 no bloquea a ninguno de estos** y no es un prompt, pero sí desbloquea dos mediciones que están anotadas y sin hacer: BGE-M3 contra Google a 1024 en valenciano (que **no** necesita el deploy, porque los embeddings van por API key de Gemini) y la traza del asistente con corpus real.
>
> **Las pruebas manuales del Bloque SEC quedan absorbidas por MAN.2**: reejecutarlas sueltas ahora sería la tercera pasada sobre un guion que CAL.2/CAL.3/CAL.4 han dejado a medio caducar.

> **Nota para ING.0.5**: la validación de subidas ya existe y es reutilizable — `server/app/core/uploads.py`, `validate_upload(file, kind=UploadKind.TEXT)` acepta `.md`/`.markdown`/`.txt` y rechaza binario disfrazado. No reimplementarla.

> **Dos reglas duras que atraviesan ING.0, VIS y RAG** (replanificación 2026-07-28): (1) el vocabulario de ámbitos/submaterias es **dato versionado en tabla**, nunca `Enum` ni `CheckConstraint` — está pendiente de validar por SG y debe seguir siendo revisable; (2) **la taxonomía no entra jamás en el texto embebido**, o cada revisión del vocabulario costaría un re-embedding del corpus completo. Los pares bilingües van al `tsvector` de RAG.4, no al embedding.

> Bloque 9R Redacción Contract-First cerrado: 9R.0→9R.10.2. Siguiente: Fase 10 (Plantillas y Temas).

**Orden de ejecución acordado (2026-05-13, actualizado 2026-07-15):**
`9R.7.1→9R.10` → `Fase 10` → `1C.0→1C.1` → `Fase 13 (NER redacción)` → `1C.2→1C.4` → `Fase 20 reducida` → `Bloque SBX (SBX.1→SBX.4)` → `Bloque 9Q (9Q.0→9Q.9)` → **`Bloque AUTH (AUTH.1→AUTH.4)`** → **`Bloque MCP (MCP.1→MCP.4)`** → **`Bloque ROL (ROL.1→ROL.2)`** → `Fase 11 (11.1→11.3)` → **`SEC.6`** (adelantado) → **`Bloque ING.0 (ING.0.1→ING.0.5)`** → *(carga del corpus v1 + pruebas manuales end-to-end)* → **`RAG.1`** (baseline) → **`Bloque TST (TST.1→TST.2)`** → **`RAG.2`** (consolidación de grafos) → **`Bloque VIS (VIS.1→VIS.3)`** → **`RAG.3→RAG.14`** → **`Bloque SYNC (SYNC.1→SYNC.2)`** → **`Bloque SEC (SEC.1, SEC.2, SEC.2.1, SEC.3, SEC.4, SEC.4.1, SEC.5, SEC.7)`** → **`Bloque CAL (CAL.1→CAL.5)`** → `Deploy GCP` (con corpus definitivo revisado) → **`Bloque OWUI (OWUI.1→OWUI.3)`** (post-deploy, spike/comparación para el piloto)

> **Actualización del orden 2026-07-28:** el Bloque RAG se **parte** para intercalar el Bloque VIS. `RAG.1` y `RAG.2` van delante (baseline sobre el corpus v1 y consolidación de grafos); `VIS.1→VIS.3` después, porque VIS.2 reescribe `md_agent_selector_pipeline` y hacerlo antes sería escribir contra `agent/graph.py`, que RAG.2 elimina. El resto del Bloque RAG (RAG.3→RAG.14) sigue sin cambios de alcance, con cuatro enmiendas in situ (RAG.2, RAG.4, RAG.5, RAG.7). El Deploy GCP pierde la fecha fija de septiembre: el usuario prioriza los fundamentos sobre el calendario (2026-07-28).

> **Actualización del orden 2026-07-11:** insertados **ROL** (antes de Fase 11), **SEC** (bloqueante, antes de Deploy) y **CAL** (antes de abrir el repo AGPLv3), a partir de `docs/VALORACION_PROYECTO.md`. **ING.0** (carga de corpus curado) es la vía de ingesta principal pero depende de que el usuario entregue la carpeta canónica + manifiesto; se ejecuta cuando esté listo, en paralelo. Total nuevos prompts Fase 1: +16 (ROL×2, SEC×7, CAL×5, ING.0×2).

> **Actualización del orden 2026-07-15:** nuevo **Bloque RAG** (RAG.1→RAG.14) en `Plan_TDD_Fase1.md`, derivado de la comparativa arquitectónica con LAMB (`docs/COMPARATIVA_RAG_LAMB.md`). Insertado **tras las pruebas manuales con corpus de prueba y antes del resto de SEC**: el corpus cargado en ING.0 es insumo del dataset dorado (RAG.1) y las mejoras de retrieval llegan al deploy de septiembre. Planificación en dos fases: relación de prompts aprobada y **2ª pasada de detalle verbatim completada el mismo día** (tests enumerados, ficheros, migraciones, criterio de done por prompt). Total nuevos prompts Fase 1: +14.

> **Bloque OWUI añadido (2026-07-24):** nuevo **Bloque OWUI** (OWUI.1→OWUI.3) al final de `Plan_TDD_Fase1.md`, **post-deploy**, desde `docs/DECISION_OPENWEBUI_CARCASA_CHAT.md`. Es lo único que las decisiones (carcasa OWUI + dependencias RAG) exigían **añadir**: el bloque RAG ya estaba alineado y no se reescribe; la chat-UI React no se descoped (decisión del usuario). Contenido: **OWUI.1** adaptador `/v1/chat/completions`+`/v1/models` sobre el grafo (scope nuevo `chat:completions`, reusa CoreGraph, no reimplementa RAG); **OWUI.2** citas P6 + anonimización P7 con test de equivalencia vs `hub_chat`; **OWUI.3** Pipe delgado + despliegue edge (P8) + validación e2e. Regla dura: la gobernanza se hereda del grafo, nunca vive en el adaptador ni en el Pipe.

> **Lente de mantenibilidad del RAG (2026-07-24):** creado `docs/RAG_SUSTITUCION_DEPENDENCIAS.md` — vista transversal "código propio → dependencia madura" del Bloque RAG + Bloque ING, derivada de `docs/DECISION_OPENWEBUI_CARCASA_CHAT.md` §6 (RAG/ingesta se queda en el perímetro; el mantenimiento se alivia apoyando las **primitivas** en librerías, no moviéndolas a OWUI). **No añade prompts**: reencuadra los ya aprobados. Clasificación: ✅ ya apoyado (chunker/embeddings/PDF), ♻️ reinventado→sustituir (ILIKE→FTS = RAG.4), ➕ hueco→añadir (HNSW=RAG.3, reranker=RAG.6, parent-child=RAG.8, multi-formato Docling=ING), 🔒 diferencial→no sustituir (`superseded`/citas/`hasher`/`quality`). 80 % del valor = **RAG.4 + RAG.6**. Anti-patrón: no adoptar LlamaIndex/Haystack como orquestador.

> **Actualización del orden 2026-07-13:** el usuario confirma que el **deploy no ocurrirá hasta septiembre** (a la espera de la revisión definitiva del corpus UJI) y quiere hacer **pruebas manuales + ingesta con un corpus de prueba en local** antes de esa fecha. Se **adelanta el Bloque ING.0** (antes backlog/"cuando el corpus esté listo") a justo después de cerrar Fase 11, usando un corpus de prueba no-regulatorio (sin bloqueo por revisión). Se adelanta también **SEC.6** (validación de subidas) delante de ING.0.2, que quiere reutilizarla, para no duplicar trabajo. El resto del Bloque SEC (SEC.1-5, SEC.7), CAL y Deploy GCP se mantienen en el orden previo, con margen hasta septiembre.

> **Adelanto AUTH+MCP (2026-06-11):** SSO SAML real (Subfase 1.B.1, antes diferida) + PAT para clientes máquina, insertados **antes de Fase 11** para habilitar el Bloque MCP (servidor stdio de autoría de plantillas y configuración de chatbots, `docs/mcp.md`). SAML autentica humanos; el PAT es lo que consume el servidor MCP headless. Total Fase 1: 55 → 63 prompts (+8: AUTH.1-4, MCP.1-4).

> **Bloque ING (Ingesta multi-formato) — planificado 2026-06-23:** detalle de las 4 fases y decisiones de diseño en el historial (2026-06-23). **Adelantado al orden de ejecución el 2026-07-13** (ver nota arriba) — ya no es backlog sin programar; se ejecuta con corpus de prueba tras cerrar Fase 11, antes de la carga definitiva de septiembre.

> Nota: el bloque **9R** se incorporó el 2026-05-11 a partir de `Rediseño_informes.md`.
> Sustituye los antiguos prompts 9.11a–9.11d. **Fase 13** en Fase 1 cubre únicamente el hook NER pre/post-LLM en DraftingCoreGraph; la integración con expedientes es Fase 3. **Fase 20** se ejecuta sin la consola conversacional admin (diferida a Fase 2). **Fase 11** precede a Deploy GCP como prerrequisito de distribución como software libre.

---

### Plan_TDD_Fase2.md y Plan_TDD_Fase3.md

| Plan | Estado |
|------|--------|
| Fase 2 — Migración NiceGUI + Agente local | ⏳ No iniciada — **replanteada 2026-07-11**: la migración en bloque NO se recomienda (gran parte del valor ya está en `redaccion`/`agents_hub` o superada por agentes IA). Se reduce de facto a **Subfase 2.A (Thin Client, infra para Fase 3)** + limpieza; el resto se migra por goteo bajo demanda del piloto. Ver §"Recomendaciones y replanteamiento" en Plan_TDD_Fase2.md |
| Fase 3 — Gestor de Expedientes | ⏳ No iniciada — **recomendaciones añadidas 2026-07-11** (prerrequisitos reconciliados, checkpointing oficial, auditoría inmutable con rol BD, RGPD en Fairness, reutilización de lo ya migrado, spike temprano ENI/ENS). Ver §"Recomendaciones de la Fase 3" en Plan_TDD_Fase3.md |

**Subfase 2.B — Estado del plan para el extractor PDF (9.12b / 9.13)**

Plan enriquecido el 2026-05-11 con el análisis de `Migración_extracción_pdf.txt`:

| Prompt | Descripción | Estado |
|--------|-------------|--------|
| 9.12b.0 | Auditoría funcional legacy (`legacy_extraction_spec.md`) | ⏳ Pendiente |
| 9.12b | Refactor backend PDF extractor a Docling | ⏳ Pendiente |
| 9.13 | UI React del extractor PDF (Focus Mode + wizard) | ⏳ Pendiente — bloqueado por 9.12b |

Secuencia de implementación: 12 pasos atómicos documentados en **Guía 9C.1** del plan.
Prompts verbatim para el agente: `Migración_extracción_pdf.txt` §5.

> **Prerequisito de Fase 2**: Subfase 1.A completada ✅ (9B.14 verde, 2026-05-11).

---

## Historial

Las entradas cerradas viven en **`HISTORIAL.md`**, en este mismo directorio. Se separaron el
2026-08-21: eran 535 de los 626 KB de este fichero, que se lee entero al arrancar cada sesión.

Al cerrar un prompt, **la fila nueva va arriba** de la tabla de `HISTORIAL.md`, con la fecha, el
identificador y una descripción de una línea. Este fichero conserva el cursor, los planes activos y
los bloques cerrados recientes.
