# Multitenencia: qué está acotado, por qué camino, y qué es de plataforma a propósito

> Escrito en **MT.7** (2026-08-24) porque la auditoría que originó el Bloque MT consistió en
> reconstruir esto a mano leyendo 31 tablas y 32 routers. Lo mantiene honesto
> `server/tests/core/test_mt7_el_inventario_esta_escrito.py`: si una tabla de configuración falta
> aquí, o su ámbito no coincide con el que declara el código, el test se pone rojo. **No es
> documentación que se actualiza cuando alguien se acuerda.**

## Para qué existe todo esto

El objetivo del diseño es que **una Diputación pueda desplegar una instancia para varios
municipios**: un superadministrador da de alta las organizaciones, cada una tiene su
administrador, y las personas de una organización sólo alcanzan el contenido de la suya.

Lo que **no** es: esto no convierte la instalación en multiinstancia. Sigue siendo una base de
datos con organizaciones dentro. La separación **física** por municipio es el modo `edge` que
describe `AGENTS.md` — un despliegue por cliente, con la configuración sincronizada desde el
cloud.

## Los cuatro ámbitos

Toda tabla de `HubConfigBase` declara el suyo en `__ambito__`, y una que no lo declare pone rojo
el guardarraíl de MT.1. La declaración **no se hereda** de una clase padre: heredar de una base
común es normal, heredar la decisión de quién es el dueño de los datos no.

| Ámbito | Qué significa | Columna |
|---|---|---|
| `plataforma` | Una sola configuración para la instalación entera. No hay nivel de organización. | — |
| `organizacion` | Siempre de una organización. | `organizacion_id` NOT NULL |
| `heredable` | **Nulo = de la plataforma, y se hereda.** | `organizacion_id` nullable |
| `derivada` | La organización se alcanza por otra tabla. | la que diga `via` |

Son cuatro y no tres porque varias tablas llegan a la organización **por otra tabla**
(`hub_prompt_templates` por su chatbot), y meterlas en «de organización» diría que tienen una
columna que no tienen.

La cascada de `heredable` la resuelve `core/ambito.py`, escrita una vez: **campo a campo**, no
fila entera —con reemplazo de fila, una organización que quiera cambiar un color tendría que
repetir la configuración completa— y distinguiendo `None` («heredar») de `""` («lo quiero
vacío»), sin lo cual no se puede vaciar un valor heredado desde la pantalla.

## Tablas de configuración (`HubConfigBase`, se sincronizan cloud→edge)

| Tabla | Ámbito | Camino a la organización | Nota |
|---|---|---|---|
| `hub_organizaciones` | `plataforma` | — | Es el eje sobre el que se acota todo lo demás, no algo acotable. |
| `hub_platform_modules` | `plataforma` | — | Catálogo de módulos de la instalación. |
| `hub_providers` | `plataforma` | — | **A propósito**: es un catálogo de *tipos* (Google, Vertex, Ollama, OpenRouter). Google es Google en todos los municipios. Lo que se separa es la credencial. |
| `hub_provider_credentials` | `heredable` | `organizacion_id` | MT.2. Con qué credencial habla cada organización. **Dos métodos desde SEC.9.4**: **nombre** de variable de entorno y ADC. El tercero —la clave literal en la base— se retiró con su columna: lo que se guarda es *dónde* está el secreto, no el secreto, así que un volcado o la sincronización cloud→edge dejan de ser sensibles por construcción. El autoservicio del panel que eso cuesta se recupera en MT.10 con un `SecretProvider`. |
| `hub_llm_configs` | `heredable` | `organizacion_id` | MT.2. `is_default` es único por (nivel, propósito, organización). |
| `hub_chatbots` | `organizacion` | `organizacion_id` | Un asistente es siempre de una organización. **PLG.2** le añade `estrategias` (`JSONB`, `{eje: nombre}`), que es **heredable clave a clave** contra `hub_organizaciones.default_estrategias`: fijar `merge` en la organización no pisa el `template` del chatbot. Es la única herencia por clave de todo el inventario, y por eso no pasa por `_apply_layer` —que sustituye el valor entero— sino por `_resolver_estrategias`. |
| `hub_vocabulary_terms` | `organizacion` | `organizacion_id` | Cada organización tiene su vocabulario; no hay nivel de plataforma que heredar. |
| `hub_lexicon_pairs` | operacional (no es de `HubConfigBase`) | `organizacion_id` | RES.3 — pares «como lo dice una persona / como lo dice la norma». **Nació en configuración y el guardarraíl de la frontera lo rechazó con razón**: `termino_de_usuario` es literalmente lo que escribió alguien, y la configuración se sincroniza cloud→edge. Mismo lado y mismo motivo que `hub_test_scenarios`. Lo que decide el lado no es «es vocabulario» —`hub_vocabulary_terms` es configuración y está bien— sino si lleva dentro texto de una persona. Sin FK a `hub_organizaciones` ni a `hub_documents`, como el resto de los operacionales; el acotado lo garantizan el código y su test. |
| `hub_prompt_templates` | `derivada` | `chatbot_id` | Cuelga de un chatbot, por idioma y versionada. Lo acota `/hub/prompts-catalog` (REV.13). |
| `hub_widget_keys` | `derivada` | `chatbot_id` | La credencial pública de un asistente concreto (SEC.8.5). |
| `hub_activity_prompts` | `heredable` | `organizacion_id` | MT.6. Cadena organización → plataforma → **código**; el texto del código nunca se copia a una fila. |
| `hub_themes` | `heredable` | `organizacion_id` | La cascada visual, de la que salió el patrón. |
| `hub_users` | `heredable` | `organizacion_id` | Nulo = cuenta que no pertenece a ninguna. El filtro del listado lo puso MT.9 (issue #186), **diciendo cuántas deja fuera y ofreciendo verlas**: en herencia, filtrar y callarse es esconder. |
| `hub_module_grants` | `heredable` | `organizacion_id` | MT.5. **Nulo = en todas**, que es lo que valen las concesiones de siempre. Eje perpendicular al de `subject_type`. |
| `hub_personal_access_tokens` | `heredable` | `organizacion_id` | MT.5. Nulo = donde valga su dueño. Cuando lo declara **acota, nunca amplía**. |

## Tablas operacionales (`HubOperationalBase`, viven sólo en el edge)

Casi ninguna declara `__ambito__`: son datos del cliente final, y su acotación es la del camino
por el que se llega a ellas. La columna dice **por dónde** las acota un router.

**Las dos excepciones son las de FUN.1**, y la excepción está razonada: `hub_funciones` tiene una
cascada de verdad —nulo = de plataforma, y se hereda, que es lo que hace que una función
promocionada la referencie cualquier organización—, así que declarar su ámbito documenta esa
cascada aunque el guardarraíl de MT.1 sólo recorra `HubConfigBase`. Están en el lado operacional,
y no en configuración, porque `hub_funcion_versiones.code` y su declaración responsable son texto
escrito por una persona de la organización: el mismo criterio que mandó aquí a `hub_lexicon_pairs`.
Lo comprueba `test_fun1_catalogo.py`, que es el guardarraíl que a estas dos les faltaba.

| Tabla | Camino a la organización |
|---|---|
| `hub_web_sites` | `organizacion_id` |
| `hub_web_sections` | `site_id` → sitio (DIN.1) |
| `hub_crawled_pages` | `site_id` → sitio |
| `hub_content_findings` | `site_id` / `chatbot_id` |
| `hub_corpus_selections` | `site_id` / `chatbot_id` |
| `hub_documents` | `chatbot_id` |
| `hub_document_chunks` | `chatbot_id` |
| `hub_ingestion_jobs` | `chatbot_id` |
| `hub_interactions` | `chatbot_id` |
| `hub_test_scenarios` | `chatbot_id` |
| `hub_test_runs` | por su escenario |
| `hub_funciones` | `organizacion_id` — **nulo = de plataforma, y se hereda** (FUN.1) |
| `hub_funcion_versiones` | `funcion_id` → función |
| `hub_report_templates` | `organizacion_id` (MT.4) |
| `hub_report_template_versions` | `template_id` → plantilla |
| `hub_workspaces` | `organizacion_id` (MT.4) |
| `hub_workspace_blocks` | `workspace_id` → informe |
| `hub_workspace_audit_events` | `workspace_id` → informe |
| `hub_run_manifests` | `workspace_id` → informe |
| `hub_script_proposals` | por su informe |
| `hub_usage_counters` | `subject_type='organizacion'` desde SEC.4 |
| `hub_actividad_ia` | `organizacion_id`, la del dueño del token que registra (REG.1) |

## Las dos capas que hacen cumplir la frontera

No son lo mismo y es fácil confundirlas:

- **`core/auth/tenancy.py` — quién puede ver qué.** `assert_org_access` (403 sobre una entidad ya
  leída) y `scope_query_to_orgs` (acota un listado). Recibe un principal. **El superadministrador
  no se acota, y es correcto como permiso**: lo que falta es la *vista*, y eso es MT.8.
- **`core/ambito.py` — qué fila gana** cuando la misma configuración está puesta en dos niveles.
  No recibe principal.

`scope_query_to_orgs` con un principal **sin** organizaciones devuelve un `IN ()` vacío, que no
devuelve nada. Es intencionado, y es la diferencia entre «no ve nada» y «no se filtra»: devolver
el listado entero cuando el claim viene vacío era el hallazgo A2 de SEC.2.

## Qué pantalla acota qué listado

Lo de arriba dice **quién puede ver qué**. Esto es la capa de encima: desde REV.10 la organización
se elige **una vez** en la cabecera, y aquí queda escrito a qué listados llega esa elección — y,
lo que más se pierde, **a cuáles no debe llegar**.

Medido el 2026-09-28 al cerrar MT.8. Sin esta sección, quien lea la issue verá cinco listados sin
filtrar y añadirá el filtro, rompiendo la herencia.

| Listado | ¿Acota por la organización elegida? | Por qué |
|---|---|---|
| Chatbots | **Sí** | `organizacion`: un asistente es siempre de una. Lo pide `useChatbotsDeLaOrganizacion` y lo aplica el servidor. **Nueve pantallas dependen de él**: casi ninguna lista «lo suyo», listan chatbots para elegir uno y pedir después sus documentos, sus escenarios o sus interacciones. |
| Sitios de curación | **Sí** | `organizacion`. Fue el primero, en SEC.8.1, y de ahí sale el patrón. |
| Prompts de chatbot | **Sí, por herencia** | `derivada` de `chatbot_id`: al acotar los chatbots queda acotado solo. No lleva filtro propio. |
| Organizaciones | **No, y no debe** | Es el eje sobre el que se acota todo lo demás, no algo acotable. |
| Temas (identidad visual) | **No, y no debe** | `heredable`. La pantalla trabaja con los **tres niveles a la vez** —plataforma, organización, chatbot— porque eso es la cascada. Filtrar por organización ocultaría la fila de plataforma que se hereda, o sea que rompería lo que la pantalla existe para enseñar. |
| Configuraciones de modelo | **No, y no debe** | `heredable`, mismo motivo: nulo significa «de plataforma, y se hereda». |
| Concesiones de módulo | **No, y no debe** | `heredable` con una vuelta más: **nulo = en todas**. Un filtro por organización escondería justamente las concesiones que valen para todo el mundo. |
| Personas | **Sí, con salida** | `heredable`, y por eso es el caso distinto (**MT.9**, issue #186). El listado ya estaba acotado por tenencia; esto es estrecharlo a la elegida. Lo que en herencia no se puede hacer es filtrar y callarse: nulo significa «de plataforma», así que la pantalla **dice cuántas cuentas deja fuera** —el servidor manda el recuento— y ofrece verlas. Sin esa salida, con organizaciones dadas de alta siempre hay una elegida y la cuenta de arranque dejaría de ser alcanzable. |

**La regla que resume la tabla**: se filtra lo que es `organizacion`; **no** se filtra lo
`heredable`, porque en herencia «nulo» no es «de nadie», es «de todos». Confundir las dos cosas
convierte un acotado en una ocultación.

Lo vigila `test_issue11_el_listado_de_chatbots_no_se_desacota.py`, que además impide que una
pantalla nueva vuelva a pedir la lista de chatbots sin acotar — con salida declarada
(`lista-sin-acotar:`) para el consumidor que de verdad necesite todas.

## Qué sigue abierto (fase 2, después del piloto)

La fase 1 metió el **esquema** antes del piloto porque añadir una columna a una tabla casi vacía
es gratis y añadirla con meses de informes firmados es una migración con riesgo. La **vista** y
los **permisos** van después, porque dependen de cómo quede el piloto:

- **MT.8** — el selector de la cabecera **filtra** los listados de un superadministrador. Filtro,
  no permiso: seguir pudiendo verlo todo es correcto; verlo todo **a la vez** es lo que estorba.
- **MT.9** — un administrador gestiona a las personas de su organización.
- **MT.10** a **MT.15** — pantallas de modelos, plantillas, prompts, alta de organización con su
  administrador, concesiones y cuotas.
- **MT.16** — prueba de aislamiento de punta a punta con dos organizaciones.
- **MT.17** a **MT.21** — reutilizar configuración entre organizaciones: `capacidades`/`requiere`,
  plantilla de asistente, catálogo, exportar/importar y el mismo mecanismo en automatizaciones y
  expedientes. El detalle está en `planificacion/Plan_TDD_Fase1.md` §Bloque MT.
