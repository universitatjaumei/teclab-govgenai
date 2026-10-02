# El presupuesto propio, como dos funciones del catálogo

El cuaderno «Pressupost UJI», que hacía en Colab el dataset del cuadro de mando y el Word del
presupuesto, convertido en dos funciones de tarea (AUT.10, issue #120). **Se encadenan**: la salida
de la primera es la entrada de la segunda.

| | Función | Recibe | Produce |
|---|---|---|---|
| 1 | [`anonimizar_presupuesto.py`](anonimizar_presupuesto.py) | el CSV del presupuesto y la lista de nombres del PDI | `presupuesto_anonimizado.csv` |
| 2 | [`documento_presupuesto.py`](documento_presupuesto.py) | el CSV **anonimizado**, la clasificación económica y, si se quiere, la prosa en Markdown | `pressupost_net.csv` y `pressupost_uji.docx` |

Los contratos —slots, parámetros, declaración responsable y artefactos— están en
[`contratos.json`](contratos.json).

## Por qué dos funciones y no una

La anonimización del cuaderno es **propia del dominio**: busca códigos de convocatoria seguidos de
un nombre (`PID2023-…`, `CIDEGENT/2024/…`) y los nombres del personal investigador que estén en la
lista del PDI. El servicio general de anonimización de la plataforma no conoce ninguna de las dos
cosas, así que sustituirlo cambiaría qué se tacha. Registrarla aparte permite usarla sola y que el
registro diga que el documento se hizo sobre datos ya anonimizados.

## La prosa del documento

En el cuaderno vivía en un Google Doc que se leía con la cuenta de la persona. Ahora es un Markdown
que se sube, con los mismos marcadores:

```markdown
## Resum executiu

El pressupost de despeses puja a {{VAL:total_despeses}} euros.

{{TAULA:00_Resum:INICI}}
{{TAULA:00_Resum:FI}}
```

El texto de una sección es lo que hay entre su título y su `{{TAULA:<id>:INICI}}`. Las claves de
`{{VAL:…}}` que se calculan son `total_despeses`, `total_ingressos`, `var_despeses_pct`,
`var_despeses_eur`, `despeses_sense_afectacio` y `despeses_amb_afectacio`; una que no exista se
queda a la vista como `‹?clave›`, para que se note.

## Qué cambia respecto al cuaderno

Además de lo que exige la plataforma —leer con pandas porque el auditor deniega `open`, nada de
`pip install`, escribir en `output_dir`—, la anonimización tiene **cinco diferencias**, y las cinco
protegen más. Dos son de diseño y tres son defectos del cuaderno que destaparon los tests:

- **Sustituye en su sitio.** El cuaderno conservaba las columnas originales junto a las
  anonimizadas, así que su CSV «limpio» llevaba los nombres al lado.
- **Vacía el NIF del tercero en los gastos**, donde el tercero puede ser una persona.
- **La lista de palabras que descartan un nombre (`STOP`) no funcionaba**: se comparaba en
  minúsculas contra una lista en mayúsculas, y se tachaban títulos de proyecto.
- **De dos personas en una descripción, sólo se tachaba la primera.**
- **Se comía la partícula** que une con la persona siguiente.

## Cómo se prueba

Con datos **sintéticos**, nunca con el CSV real, que lleva nombres y NIF de terceros:
[`datos_sinteticos.py`](datos_sinteticos.py) genera un presupuesto con los casos difíciles puestos
a propósito. Lo usan dos pruebas gemelas, porque el sandbox y el modo local de la plataforma no
tienen la misma versión de pandas:

- `server/tests/modules/redaccion/test_aut10_el_presupuesto_propio.py` — por la API, en modo local.
- `services/script_sandbox/tests/test_aut10_el_presupuesto_propio.py` — por el sandbox de verdad.
