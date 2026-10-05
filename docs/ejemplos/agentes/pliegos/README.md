# La carpeta de un agente de pliegos, desde los datos abiertos de PLACSP

[`descarga_placsp.py`](descarga_placsp.py) llena la carpeta de Drive de un **agente de pliegos**
con pliegos reales de otras entidades. Esa carpeta la resume el guion del índice (#174) y la manda
como índice a la plataforma. Lee los datos abiertos de la Plataforma de Contratación del Sector
Público (PLACSP): ficheros ZIP con feeds Atom en formato CODICE. No usa ninguna API de pago.

Lo propio de cada organización es la **selección**: qué órganos, qué CPV y qué procedimientos. La
de la Universitat Jaume I, `SELECCION_UJI`, es el ejemplo. El resto del código no conoce a la UJI.

## El corpus por capas

El agente no trabaja solo con estos pliegos. La carpeta junta cuatro capas, y el nombre de cada
fichero empieza por la suya entre corchetes, para que el prompt del agente pueda decir cuánto pesa
cada documento:

| Capa | Qué | De dónde |
|---|---|---|
| 1. Lo propio | Los formularios e instrucciones de la propia organización | A mano. En la UJI, la propuesta de contratación y sus instrucciones |
| 2. Lo que dice qué está bien | Pliegos tipo de las juntas consultivas, guías, resoluciones de tribunales de recursos | A mano. Por ejemplo, los [pliegos tipo de la GVA](https://hisenda.gva.es/es/web/subsecretaria/contratacion/plecs-tipus) |
| 3. Universidades | PPT, memoria justificativa y justificación de los negociados de otras universidades públicas | **Este script** |
| 4. Otras entidades | El CSIC y otras entidades que compran lo mismo | **Este script** |

## Las familias: lo que contratan los grupos

La selección de la UJI se centra en los contratos que hacen los **grupos de investigación**, que
son los que más ayuda necesitan. Las obras y la TI las llevan los servicios, que tienen la
experiencia. Las familias salen de medirlo en 2024. De 4.057 expedientes de universidades (sin
obras, contratos menores ni derivados de acuerdo marco), 901 llevan **señal de grupo**: fondos
europeos, o «investigación», «laboratorio», «proyecto» o el código de una convocatoria en el
objeto.

| Familia | CPV | % de grupo en 2024 | Documentos |
|---|---|---|---|
| Equipamiento científico | 38 | 75 % | PPT, memoria |
| Equipos técnicos | 31, 32, 42, con señal | 55 % | PPT, memoria |
| Servicios de I+D | 73 | 84 % | PPT, memoria, insuficiencia de medios |
| Mantenimiento de equipos | 50, con señal | 19 % | PPT, memoria, insuficiencia de medios |
| Auditoría de proyectos | 792, 794, con señal | 39 % | PPT, memoria, insuficiencia de medios |
| Exclusividad | las anteriores, negociado sin publicidad, con señal | — | justificación, memoria |

Los negociados sin publicidad van aparte y **solo con su justificación**. Su PPT es escueto, pero
justificar una exclusividad (art. 168.a.2 LCSP) es justo donde más se atasca un grupo. Esa
justificación no tiene código en PLACSP: llega como «otros documentos», y se reconoce por el nombre.

El tope es de **dos expedientes por universidad y familia** (los más recientes) y cinco del CSIC,
así que la carpeta no crece con los años. Con 2024 salen 224 expedientes de 39 entidades y unos 330
documentos. **Los PDF pesan 0,42 MB de media** (medido sobre 30), así que la carpeta entera ocupa
unos cientos de megas.

Las capas 1 y 2 son pocas y estables. Van marcadas como **fichas prioritarias** en la hoja del
índice (#223): entran antes que los ejemplos si encajan con la consulta.

## Dos pasos: extraer una vez y elegir muchas

1. **Extraer** es lo pesado. Lee todo el feed de un periodo y guarda, en una tabla de unos megas,
   los expedientes de los órganos de las capas, **con cualquier CPV**. Cada periodo se extrae una
   sola vez: si la extracción ya está en la caché, se lee de ahí, y el ZIP se borra al terminar.
2. **Elegir** es barato. Filtra la extracción por CPV, tipo de contrato, procedimiento y estado,
   con un tope de expedientes por entidad. Se pueden probar otras familias de CPV sin volver a
   descargar nada.

Después se descargan los documentos de lo elegido.

### Cuánto pesa

Medido en octubre de 2026:

| Periodo | ZIP | XML sin comprimir |
|---|---|---|
| Un mes (`AAAAMM`) | ~190 MB | ~1,9 GB |
| Un año cerrado (`AAAA`) | ~1,8 GB | ~19 GB |
| Plataformas agregadas, un mes | ~11 MB | ~220 MB |

El XML no se descomprime a disco: se lee en flujo dentro del ZIP. **Un año de datos ocupa menos de
2 GB de disco mientras se procesa**, y después unos megas.

### Dónde ejecutarlo

- **La carga inicial** (varios años), **en local**, con **Google Drive para escritorio** y la
  carpeta del agente sincronizada. Es descargar unos 9 GB y leerlos una vez: un año tardó 18
  minutos en extraerse.
- **La actualización mensual, en Colab**. Solo baja el mes nuevo (unos 190 MB) y relee las
  extracciones anteriores de la caché. Por eso **la caché va en Drive** (unos megas por año) y
  **los ZIP en el disco de la sesión** (`--zips /content/zips`), que se borra al cerrarla. En la
  primera ejecución en Colab se copia la caché de la carga inicial.
- **No en Apps Script**: no descarga ficheros de cientos de megas y corta a los seis minutos.

No hace falta actualizar a diario. Para redactar un pliego, un ejemplo del mes pasado sirve igual
que uno de ayer.

Con el tope por familia, cada mes **entran los expedientes más recientes**. Los que dejan de estar
entre los dos últimos de su universidad no se borran de la carpeta: siguen siendo ejemplos válidos.

**La primera vez, el guion tarda en resumirlo todo.** Resume lo que cabe en una ejecución de
cuatro minutos y medio y lo programa una vez al día. Para la carga inicial conviene lanzar
`actualizarIndice` a mano varias veces, o programarlo cada hora durante unos días.

## Uso

```bash
python descarga_placsp.py \
  --carpeta "G:/Mi unidad/Agente de pliegos" \
  --tabla   "G:/Mi unidad/Agente de pliegos - expedientes.csv" \
  --cache   placsp_cache
```

`--periodos 2026 202610` sustituye los periodos de la selección. La tabla **no puede ir dentro de
la carpeta**: el guion la contaría como un documento sin ficha.

En Colab, monta Drive y pasa las rutas bajo `/content/drive/MyDrive/`, con `--zips /content/zips`.
Para la actualización mensual, en `--periodos` van **todos** los periodos: los ya extraídos se leen
de la caché, y solo el mes nuevo se descarga.

## Por qué los PDF van a Drive y no se enlazan a PLACSP

Las URL de PLACSP son públicas, así que el índice podría apuntar a ellas y ahorrarse la descarga.
No compensa:

- **El ahorro es pequeño**: unos cientos de megas y unos minutos de descarga.
- **El resumen necesita el PDF.** El guion lo lee en Drive, y sin él solo habría el título.
- **El índice lo manda el guion, y es el estado completo de la carpeta.** Una ficha con URL de
  PLACSP que no esté en la carpeta se retiraría en la siguiente actualización.
- **Gemini lee Drive con la cuenta de quien pregunta**, y es lo que se comprobó antes de seguir
  adelante con los agentes (#215). Que abra un servlet de PLACSP no está comprobado, y en la muestra
  uno de cada treinta documentos devolvió un error 500.
- Con todo en Drive, **este agente funciona como los demás**.

## Por qué así

- **Una carpeta plana y sólo PDF de hasta 15 MB.** Es lo que el guion sabe leer y resumir. Lo que
  no se guarda (un ZIP, un DOCX, un PDF demasiado grande) queda anotado en el resultado.
- **El nombre del fichero es el título de la ficha**:
  `[Universidad] Universidad de Burgos – UBU-2025-0024 – Suministro de … – PPT.pdf`.
- **Un expediente, en su último estado.** El feed repite el expediente cada vez que cambia, también
  entre años, y gana la entrada más reciente. Una lápida (`deleted-entry`) lo retira.
- **Las universidades, por la jerarquía y por el nombre.** En PLACSP cuelgan del nodo
  «UNIVERSIDADES». En las plataformas agregadas, las catalanas cuelgan de «Universitats» y otras de
  ningún nodo, así que también casan por el nombre: «Universidad», «Universitat», «Universidade»,
  siempre al principio y como palabra entera, para que no entre una «Consejería de … y
  Universidades».
- **Fuera los menores y los derivados de acuerdo marco**: sus pliegos son escuetos o son los del
  acuerdo, y no enseñan a redactar. **Los negociados sin publicidad sólo entran en la familia
  «Exclusividad», y sólo con su justificación y su memoria**, no con el PPT: lo que enseñan es a
  justificar la exclusividad.
- **Las fechas se comparan como instantes, no como texto**, porque en el cambio de hora el feed
  mezcla `+01:00` y `+02:00`. **Y las lápidas se guardan con su extracción**
  (`<extracción>_lapidas.json`): la baja de un expediente de 2024 puede llegar en 2025, y al juntar
  los periodos tiene que retirarlo.
- **Relanzar no vuelve a pedir lo que ya está**, así que se puede retomar tras un corte.

## Cómo se prueba

`server/tests/modules/agentes/test_agu16_ejemplo_pliegos_placsp.py`, con un feed **sintético** de
la forma del real y sin salir a la red: la descarga recibe la función que trae los bytes.
