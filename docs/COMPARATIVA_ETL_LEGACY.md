# ETL: qué se portó del legacy y qué se dejó

> Escrito en **PRO.4** (2026-08-17) y ampliado en **PRO.9** el mismo día. El legacy es
> `C:\Users\fabra\Documents\AutomatIA`, la aplicación NiceGUI de la que sale este módulo. Esto
> existe para que nadie tenga que volver a leer 1.143 líneas de allí para averiguar lo mismo.
>
> **Respuesta corta a «¿queda algo por migrar del legacy?»: no.** Su catálogo de modelos
> (`client_app/app/models/transform_operations.py`) son exactamente las once operaciones que
> PRO.4 portó, y `etl_page.py` y `data_contract_service.py` no añaden ninguna transformación más.
> Lo que faltaba —y motivó **PRO.9**— es un hueco que allí tampoco estaba cubierto.

Lo leído: `client_app/app/services/deterministic_etl_service.py` (350 l.),
`client_app/app/services/etl_service.py` (424 l.) y `client_app/app/modules/factory/etl_factory.py`
(369 l.). **`client_app/` se retiró el 2026-09-04**: estas rutas se leen en el historial
(`git log --diff-filter=D -- client_app/`) o en la carpeta `AutomatIA` que cita `AGENTS.md`.

## Lo que descubrió la comparación

**Los dos catálogos de operaciones casi no se solapaban.** El de 9R.5.8 se orientó a **análisis**
y lo decía en su propio docstring: «este catálogo se orienta a análisis (filter / aggregate /
join / pivot / normalize / groupby) **en lugar de limpieza**». El del legacy es de **limpieza**.

Y limpiar es lo que hace falta primero: un Excel real llega con columnas que no se usan, fechas
en tres formatos, filas duplicadas y celdas vacías. Sin esas operaciones, «transformar» en un
informe se quedaba en agrupar lo que ya estuviera limpio — que casi nunca lo está.

## Portado

| Operación del legacy | Aquí | Nota |
|---|---|---|
| `DropColumns` | `drop_columns` | |
| `RenameColumns` | `rename_columns` | |
| `MergeColumns` | `merge_columns` | **Conserva la posición** de la primera columna fusionada, como el legacy: una referencia que aparece al final de la tabla obliga a reordenar después |
| `ReorderColumns` | `reorder_columns` | Lo que no se nombra queda al final, en su orden original |
| `FormatDates` | `format_dates` | Con `ISO8601` como atajo, igual que allí |
| `ReplaceValues` | `replace_values` | |
| `NormalizeText` | `normalize_text` | Los cinco modos: `upper`, `lower`, `title`, `strip`, `snake_case` |
| `FillNulls` | `fill_nulls` | |
| `RemoveDuplicates` | `remove_duplicates` | |
| `RemoveNullRows` | `drop_null_rows` | Renombrada: «quitar filas nulas» describe mejor lo que hace |
| `FilterRows` | ya existía como `filter` | El nuestro tiene además `in`, `isnull` y `notnull` |

## Lo que ni el legacy ni nosotros teníamos (PRO.9)

El legacy sabía **limpiar** una tabla. Ni él ni nosotros sabíamos convertirla en **los datos que
un informe necesita**. Cuatro operaciones, y hasta PRO.9 cada una costaba un script generado por
un modelo, auditado y ejecutado en el sandbox.

| Operación | Para qué | Por qué no podía esperar |
|---|---|---|
| `to_number` | `"1.234,56 €"` → `1234.56` | **La más importante y la que menos se ve.** Cualquier aplicación de gestión de aquí exporta los importes así, y sobre texto `sum()` **concatena**: medido en la verificación de PRO.9, sumar la columna de obligaciones daba la cadena `'128.340,55 €45.120,00 €12.890,75 €(1.500,00)'`. Sin error, sin aviso, y un informe con la cifra mal |
| `compute_column` | `pct = obligaciones / credito * 100` | Es *la* transformación de un informe presupuestario |
| `sort_rows` | Ordenar la tabla | Una tabla de informe se lee ordenada, y ordenarla no es programar |
| `unpivot` | Cabeceras `ene feb mar` → columna `mes` | Las hojas institucionales son anchas y un informe necesita largo. `pivot` ya estaba; el inverso, no |

Tres decisiones dentro de esas cuatro:

**`compute_column` no admite fórmulas, y no es un descuido.** No hay campo `formula`, ni
`expression`, ni nada que se evalúe: el auditor de PRO.1 prohíbe `eval` y `exec` en un script, y
admitir una expresión aquí sería la misma capacidad por otra puerta, esta vez sin auditor
delante. La forma es declarativa —operando, operador de un conjunto cerrado, operando, factor— y
lo compuesto se **encadena**: `t = a + b`, `pct = t / c`, `drop t`. Más verboso, auditable, y se
puede pintar en una pantalla. Un operando de texto es **siempre** una columna: si no existe,
falla, porque tomarlo por una constante de texto daría una columna de basura sin avisar.

**Dividir por cero deja un hueco, no un infinito.** Un `inf` en una tabla publicada es basura; un
hueco se ve y se pregunta.

**`to_number` falla en dos casos, y los dos son de configuración, no de datos.** Si no se
convierte **ni un valor** de la columna, y si los separadores están declarados al revés —lo
delata que el de millares aparezca *después* del decimal—. El segundo se descubrió escribiendo el
test: se esperaba que `"1,234.56"` en configuración española no se convirtiera, y sí se convierte,
**a 1,23456**. Una cifra distinta es peor que una columna vacía, porque la columna vacía se ve.
Una celda suelta ilegible sí es un dato ausente y queda en blanco, igual que en `format_dates`.

## Un derroche que se arregló de paso (PRO.9)

El prompt le pide al modelo que devuelva `operations: []` cuando la petición no cabe en el
catálogo. Esa respuesta **deliberada** se trataba como un plan inválido y se reintentaba dos veces
más: tres llamadas para volver a oír lo mismo, y sólo entonces el script. Ahora se distingue lo
que el modelo puede corregir —un JSON roto, un campo mal— de lo que ha decidido. Mismo arreglo en
`ChartFactory`.

## Divergencias deliberadas

**1. Una columna que no existe falla, no se ignora.** En el legacy, cada operación empieza con
`if op.column not in df.columns: return df`. En una interfaz donde ves el resultado al momento
eso es cómodo. En un informe que se genera en segundo plano es un renombrado que se pierde y una
tabla que sale sin tocar **sin decirlo**. Aquí es `ColumnaInexistenteError` con el nombre que
falta y la lista de las que hay; el nodo lo convierte en un bloque `failed` con su motivo, que
se ve.

**2. Las fechas ambiguas se leen con el día primero.** `01/03/2026` es el 1 de marzo, y pandas
por defecto lo lee como 3 de enero (convención de EE. UU.). Equivocarse ahí no da error: da un
informe con las fechas cambiadas. Con `source_format` explícito manda el formato.

**3. Lo que no se entiende como fecha queda vacío.** El legacy dejaba la columna entera intacta
y escribía un `print`, así que una fecha sin convertir pasaba desapercibida. Un hueco en la
tabla del informe se ve.

**4. El catálogo del prompt se genera del contrato.** El prompt del planificador enumeraba las
seis operaciones a mano. Con dieciséis, una lista a mano se queda corta en el primer cambio y el
síntoma es un modelo que no usa la mitad del catálogo. `catalogo_de_operaciones()` lo genera de
los propios modelos Pydantic — el mismo arreglo que VER.3 hizo con el borrador de plantillas.

## Lo que se dejó fuera, y por qué

- **`generate_script()` del servicio determinista** (genera el código Python equivalente a las
  operaciones). Aquí las operaciones se ejecutan con pandas en proceso y el script sólo aparece
  como *fallback* del modo IA, ya auditado y ejecutado en el sandbox. Un generador de scripts
  para operaciones que ya sabemos ejecutar sería una segunda vía sin auditoría.
- **El orquestador `etl_factory.py` del legacy** (leer fichero → generar → auditar → sandbox).
  Ese papel lo hacen aquí el grafo (`FileNormalizationNode` materializa, el nodo de extracción
  lee) y `ETLService`. Portarlo sería duplicar la orquestación.
- **La UI de ETL paso a paso.** El bloque `DATA_TRANSFORM` de una plantilla es la superficie
  equivalente y no necesita asistente propio.

## Cómo corre hoy

- **Modo `deterministic`**: aplica `operations` sobre la tabla del bloque de origen. No necesita
  modelo, y **tiene que seguir sin necesitarlo**: un informe que sólo limpia y agrupa no depende
  de que haya un LLM configurado.
- **Modo `ai`**: el modelo de la actividad `transformacion_etl` (**nivel 2**, porque traducir a
  operaciones es programar) devuelve el plan declarativo. Si tras tres intentos no valida, pide
  un script `transform(df)` que pasa por **el mismo auditor** que el script de extracción
  (PRO.1) y se ejecuta en el sandbox. Un camino con auditoría y otro sin ella es no tener
  auditoría.
- El prompt y el nivel de esa actividad se editan en **Prompts de actividad**
  (`/hub/activity-prompts`), como cualquier otra (PRO.2.1).
