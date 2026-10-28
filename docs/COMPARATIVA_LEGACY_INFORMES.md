# Informes frente al legacy de AutomatIA: qué se portó y qué se dejó

> Escrito al cerrar el **Bloque PRO** (2026-08-17). El legacy es la aplicación NiceGUI que vive
> completa en `C:\Users\fabra\Documents\AutomatIA`. Esto existe para que nadie tenga que volver
> a leer 163 KB de `extraction_service.py` para averiguar lo mismo.
>
> El detalle del ETL está aparte, en `docs/COMPARATIVA_ETL_LEGACY.md`.

## Lo que el legacy hacía mejor, y ya está portado

| Pieza del legacy | Qué resolvía | Cómo quedó aquí |
|---|---|---|
| `automatia_shared/core/security.py:audit_code()` | Auditoría determinista con **tres niveles** (`SAFE`/`WARNING`/`CRITICAL`), motivos, y **regex de rutas absolutas antes del AST** | Portado en **PRO.1**. `ScriptSecurityAuditor` era binario (`approved = not findings`) y **no comprobaba rutas**: un script que abriera `C:\Users\…` pasaba. Ahora tres niveles, `puede_revisarse`, **número de línea** en cada hallazgo y rutas absolutas cazadas |
| `FORBIDDEN_IMPORTS` frente a la lista blanca | Dos listas, no una: denegación **explícita** (`os`, `socket`, `requests`, `pickle`…) frente a «no está en la lista blanca» | Portado en **PRO.1**, y es lo que hace segura la graduación: `csv` es un hueco en una lista y lo puede aceptar una persona; `os` es una capacidad y no |
| `ExternalScriptAuditService` | Cuatro severidades, número de línea y `can_proceed_with_review` | Portada **la mitad valiosa** (`puede_revisarse`, la línea). La auditoría de cuatro niveles para scripts **traídos de fuera** se planifica con el bloque de automatizaciones, donde su modelo de confianza tiene sentido |
| `deterministic_etl_service.py` | Diez operaciones de **limpieza** que aquí no existían | Portadas en **PRO.4**, con tres divergencias razonadas. Detalle en `COMPARATIVA_ETL_LEGACY.md` |
| `focus_manager.py` + `drawer_hub.py` | El copiloto en un **cajón lateral** con pestañas, abierto mientras se trabaja | Replicado en **PRO.6**: botón en la pantalla del informe, cajón con las pestañas y el copiloto, y **arranca cerrado** |
| Biblioteca de prompts (`SystemPrompt`, `admin_prompts.py`) | `name`/`version`/`content`/**`tier`**, con el defecto por tarea **en código** y sólo el override en base de datos, y un editor con radio de cuatro opciones y variables detectadas | Replicada en **PRO.2.1** para las actividades de plataforma (`/hub/activity-prompts`). Lo de chatbot ya existía (`/hub/prompts`, `/hub/brain`) |
| Dos niveles de modelo | Tareas distintas, modelos distintos | **PRO.2**: nivel 2 escribe el script, nivel 3 lo audita. El mapa actividad→nivel es catálogo en código, sobreescribible desde la pantalla |
| `chart_configuration.py` (198 l.) | Configuración de gráfico mucho más rica: título y etiquetas de eje, valores encima, orden, leyenda, tamaño, `bins`, `donut_ratio`, y **quince tipos** frente a cinco | Portado en **PRO.8**, y **PRO.5 se equivocó al dejarlo fuera**. Su razón —«diez tipos que nadie ha pedido es código especulativo»— juzgaba los tipos sin comprobar cuál es la alternativa cuando faltan, y la alternativa es **generar código**: `translate_nl_to_config("chart_config")` no devolvía ninguna configuración, llamaba a `generate_script()`. Además el hueco mayor no eran los tipos: **una plantilla no podía pedir ni un título**, y `show_values` estaba declarado en el contrato y el renderizador lo ignoraba. Detalle abajo |

## Lo que se dejó fuera, y por qué

| Pieza del legacy | Por qué no se porta |
|---|---|
| `script_ingestion_service` + `script_adaptation_service` | Subir un script de fuera y adaptarlo al contrato. En un informe el contrato es estrecho y comprobable por máquina, y cualquier código que lo cumpla **ya entra** por la cola de aprobación; un formulario de subida añadiría una puerta, no una capacidad. Su valor aparece cuando lo que llega es cualquier cosa —RPA, carpetas vigiladas, ERP—: eso es **automatizaciones** |
| `generate_script()` del servicio determinista de ETL | Genera el Python equivalente a las operaciones. Aquí las operaciones se ejecutan con pandas en proceso; un generador de scripts para lo que ya sabemos ejecutar sería una segunda vía **sin auditoría** |
| El orquestador `etl_factory.py` (leer → generar → auditar → sandbox) | Ese papel lo hacen el grafo (`FileNormalizationNode` materializa, el nodo de extracción lee) y `ETLService`. Portarlo sería duplicar la orquestación |
| `violin` y `pairplot` de `chart_configuration.py` | Son gráficos de **exploración estadística**, no de informe, y `pairplot` devuelve un grid de ejes que no cabe en el `fig, ax` de este servicio. El resto de ese fichero **sí se portó en PRO.8**: ver la fila de arriba |
| `extraction_service.py` (163 KB) | El usuario lo señala como el módulo más probado del legacy, y aquí `pdf_text_pipeline` + `pdf_table_pipeline` ya extrajeron bien un Excel real en VER.4 y un Excel por script en PRO.2. No se toca sin un caso que falle: reemplazar lo que funciona por 163 KB de otro sitio no es portar, es apostar |
| La UI de ETL paso a paso | El bloque `DATA_TRANSFORM` de una plantilla es la superficie equivalente y no necesita asistente propio |

## Gráficos: qué quedó tras PRO.8

Once tipos, y **seis de ellos eran un parámetro de lo que ya se hacía**, que es lo que hacía
absurdo pagar un script por ellos: `barh` son los ejes cruzados, `bar_grouped` y `line_multi` ya
existían como `color_by`, `bar_stacked` es un pivot y una llamada, `donut` es un `wedgeprops`, y
`bubble` es `scatter` con `size=`. Los dos verdaderamente nuevos son `boxplot` y `heatmap` —y el
heatmap es la forma más institucional que hay: capítulo × año—.

Con la presentación completa expresable desde la plantilla (título, etiquetas, cifras encima,
orden, leyenda, rejilla, tamaño, `bins`) y `translate_nl_to_config` devolviendo **configuración**
en vez de código cuando la petición cabe en el catálogo.

Un defecto que no cazó ningún test y apareció **mirando el PNG**: las cifras salían en formato
inglés —`128,340.55`— en un informe de una institución española. Los tests comprobaban que la
cifra estaba, y estaba. Ahora `number_format` por defecto es `es` y también separa los millares
del eje.

## Lo que había aquí y el legacy no tenía

No es una migración en un solo sentido. Lo que este módulo aporta y allí no existía:

- **Sandbox de verdad** (`services/script_sandbox`, contenedor sin red) con su propio auditor
  como segunda barrera, y un guardarraíl que impide que se quede **más laxo** que el de la API.
- **Cola de aprobación con re-test y hash** (9R.5.6): el administrador vuelve a ejecutar el
  script contra los mismos datos y compara el resultado antes de aprobar.
- **Anonimización de los datos de prueba** antes de que un script destinado a una plantilla
  global se pruebe (Fase 13 + 9R.5.5).
- **Contrato de UI dirigido por el servidor**: el formulario de un informe sale del
  `ui_contract` de la plantilla, no de campos fijos en React.
- **Manifiesto de ejecución** con el modelo y la versión de prompt de cada bloque.

## Una nota sobre el legacy de este repositorio

Al escribir esto, `ExtractionServiceConfig` y `seeds_prompts.py` —la biblioteca de prompts **del
legacy heredado en este mismo repositorio**— seguían en el árbol activo junto a un `main.py` en la
raíz, con su interfaz en la cuarentena NiceGUI y un test que **sembraba la base de datos real del
desarrollador**. Todo ello se retiró con el cliente NiceGUI el 2026-09-04 (bloque NIC); el
detalle, en `docs/INVENTARIO_RETIRADA_LEGACY.md`.
