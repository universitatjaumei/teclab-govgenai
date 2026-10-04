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
| 3. Universidades | PPT y memoria justificativa de otras universidades públicas | **Este script** |
| 4. Otras entidades | El CSIC y otras entidades que compran lo mismo | **Este script** |

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

- **La carga inicial** (varios años): en un equipo con **Google Drive para escritorio**, con la
  carpeta del agente sincronizada. Es descargar unos 9 GB y leerlos una vez. También funciona en
  Colab: los ZIP van al disco de la sesión, no a Drive.
- **Las actualizaciones**: basta con el mes nuevo, unos 190 MB. Cabe en Colab o en local.
- **No en Apps Script**: no descarga ficheros de cientos de megas y corta a los seis minutos.

No hace falta actualizar a diario. Para redactar un pliego, un ejemplo del mes pasado sirve igual
que uno de ayer.

## Uso

```bash
python descarga_placsp.py \
  --carpeta "G:/Mi unidad/Agente de pliegos" \
  --tabla   "G:/Mi unidad/Agente de pliegos - expedientes.csv" \
  --cache   placsp_cache
```

`--periodos 2026 202610` sustituye los periodos de la selección. La tabla **no puede ir dentro de
la carpeta**: el guion la contaría como un documento sin ficha.

En Colab, monta Drive y llama a `ejecutar` con las mismas rutas bajo `/content/drive/MyDrive/`.

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
- **Fuera los negociados sin publicidad, los menores y los derivados de acuerdo marco.** Sus
  pliegos son escuetos o son los del acuerdo, y no enseñan a redactar.
- **Relanzar no vuelve a pedir lo que ya está**, así que se puede retomar tras un corte.

## Cómo se prueba

`server/tests/modules/agentes/test_agu16_ejemplo_pliegos_placsp.py`, con un feed **sintético** de
la forma del real y sin salir a la red: la descarga recibe la función que trae los bytes.
