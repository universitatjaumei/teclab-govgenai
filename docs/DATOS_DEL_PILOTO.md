# Qué datos llegan al piloto, y por qué

> **Entregable de D.7 (2026-08-31).** Escrito porque la próxima vez que alguien migre no va a
> leer el prompt: aquí está la lista, el criterio y las cifras medidas.

## La distinción que gobierna todo lo demás

Se estaban confundiendo dos cosas que **viajan de forma distinta**:

| | Qué es | Cómo viaja |
|---|---|---|
| **El catálogo del producto** | Las plantillas demo | Ficheros versionados en `server/app/data/plantillas_demo/`, sembrados por `bootstrap.py --con-demo` |
| **Los datos operativos** | Corpus, curación, chatbots, vigencia | `scripts/volcado_piloto.sh`: lista explícita de tablas y filtro por organización |

El catálogo **no se copia de la base de datos de nadie**. Así la demo es reproducible, se revisa
en un diff y es la misma en todos los despliegues. Es la regla que ya rige el vocabulario del
corpus: lo que define el producto es dato versionado, no una fila que alguien tenía en su
portátil.

Sin esa separación, la pregunta «¿qué pasa al piloto?» sólo tenía dos respuestas y las dos eran
malas: un volcado completo —que arrastra 29 informes de prueba y toda la basura de
verificación— o empezar de cero, tirando el corpus curado y 292 hallazgos ya revisados por una
persona.

## Lo que viaja

Medido el 2026-08-31 sobre la organización `Universitat Jaume I`
(`735a5f55-7020-4c88-a374-c2b641c5b00b`):

| Tabla | Filas | Por qué |
|---|---:|---|
| `hub_organizaciones` | 1 | La del piloto, y sólo ella |
| `hub_chatbots` | 4 | Con su configuración medida: umbrales, `top_k`, modo de recuperación |
| `hub_documents` | 751 | El corpus curado, con su vigencia y su validación |
| `hub_document_chunks` | 163.950 | Los vectores. **Reembeberlos cuesta GPU y horas**; copiarlos cuesta disco |
| `hub_vocabulary_terms` | 69 | Ámbitos y submaterias. Sin esto la ingesta aborta |
| `hub_web_sites` | 1 | El sitio de curación |
| `hub_crawled_pages` | 351 | Sus páginas, con las señales de frescura |
| `hub_content_findings` | 292 | **Trabajo humano**: hallazgos ya revisados uno a uno |
| `hub_themes` | 1 | La identidad visual |
| `hub_widget_keys` | 3 | Credenciales de sitio ya emitidas |
| **Total** | **165.423** | 3,4 GB en texto, **1,0 GB comprimido** |

Vacías hoy y por eso ausentes del fichero: `hub_lexicon_pairs`, `hub_corpus_selections`,
`hub_prompt_templates`, `hub_module_grants`.

## Lo que NO viaja, y se comprueba que no está

No basta con no listarlas. El guion **verifica sobre el fichero generado** que no aparecen:

- `hub_workspaces`, `hub_workspace_blocks`, `hub_workspace_audit_events`, `hub_run_manifests` —
  los 29 informes de prueba con sus bloques y su auditoría.
- `hub_users`, `hub_personal_access_tokens` — **ninguna persona**. Los usuarios se recrean por
  SSO al primer acceso; los tokens de máquina se emiten donde se usan.
- `hub_interactions` — las conversaciones son de quien preguntó, no del despliegue.
- `hub_test_runs`, `hub_test_scenarios`, `hub_script_proposals` — material de verificación.
- `hub_report_templates`, `hub_report_template_versions` — el catálogo viaja como fichero.

## Dos cosas que costaron un intento y conviene no repetir

**`pg_dump --table=…` no filtra filas.** La primera versión del guion lo usaba y volcaba cada
tabla **entera**: 3,2 GB con datos de tres organizaciones ajenas. Lo peor es que imprimía antes
un recuento por organización, así que *parecía* filtrado. Sólo la comprobación **sobre el
fichero** lo destapó — que es exactamente por lo que el prompt insistía en comprobar ahí y no
sobre la consulta. Ahora es un `\copy` por tabla con su `WHERE`.

**El sitio de curación tenía `organizacion_id` a NULO.** `Escola de Doctorat (RAS.5)` se dio de
alta sin organización, así que el filtro lo dejaba fuera y con él se quedaban sus 351 páginas y
sus 292 hallazgos. Es un descuido del alta y no una decisión, así que se asignó a la UJI **antes**
del volcado. Si vuelve a aparecer un sitio con la organización a nulo, el volcado lo dejará fuera
en silencio: revisa el recuento de `hub_web_sites` antes de dar el fichero por bueno.

## Cuatro trampas más, todas descubiertas restaurando de verdad

La restauración necesitó cinco intentos y **ninguno falló por el mismo motivo**. Los cuatro
primeros los tapaba una sola línea que yo había puesto en la cabecera del volcado.

### 1. `session_replication_role` no está en Cloud SQL — y fue una suerte

El volcado empezaba desactivando los disparadores para saltarse las claves ajenas. Cloud SQL lo
prohíbe (exige superusuario de verdad), y al quitarlo aparecieron **tres errores de la propia
lista de tablas** que llevaba tapando:

- Faltaba `hub_llm_configs`, y los cuatro chatbots la referencian.
- `hub_crawled_pages` iba **después** de `hub_documents`, y 3 documentos citan una página.
- 138 documentos se referencian entre sí (`versio_idiomatica_de`).

**Desactivar una comprobación es una forma de no enterarse.** El orden de las tablas sale ahora
del esquema y no de la memoria de quien lo escribió.

### 2. Las columnas generadas no admiten valores en `COPY FROM`

`hub_document_chunks.tsv` es `GENERATED ALWAYS` y se recalcula de `content` y `bilingual_terms`.
Llevarla hacía fallar la carga con **«extra data after last expected column»**, que suena a
fichero corrupto y era una columna de más. Se excluyen.

### 3. Dos bases en la misma revisión pueden tener distinto orden físico de columnas

Esto es lo que más caro sale si no se sabe:

```
desarrollo:  id, chatbot_id, document_id, content, source_url, ...
producción:  id, chatbot_id, content, source_url, content_hash, ..., document_id
```

Misma revisión de Alembic, mismas 19 columnas, **orden distinto**: la tabla de desarrollo
evolucionó con migraciones y `create_all`, la de producción nació de cero. Un `COPY` sin lista de
columnas usa el orden físico del destino, así que los campos entran desplazados y el síntoma es
un hash aterrizando en la columna del vector.

**Corolario: en un volcado entre bases, la lista de columnas no es opcional.**

### 4. La dimensión del vector estaba mal en toda instalación nueva

Y esto no era del volcado, sino **un defecto de producción**. La primera migración deja
`hub_document_chunks.embedding` en `vector(1536)` y ninguna posterior lo corrige, mientras el
modelo declara `Vector(1024)`. Una base creada con `alembic upgrade head` tenía una columna en la
que la aplicación **no puede escribir**: la primera ingesta falla.

Llevaba meses invisible porque la base de desarrollo está en 1024 —no nació de la cadena de
migraciones— y porque `test_migrations_fresh_install.py` comprueba que las columnas **existan**
pero no su tipo. Apareció aquí porque producción es la primera base de este proyecto creada de
verdad sólo con migraciones.

Corregido con la migración **`e2b3c4d5f6a7`**, condicional para no borrar vectores buenos, y
verificado en una instalación limpia (`alembic upgrade head` acaba en `vector(1024)`). El
guardarraíl que faltaba está en `tests/infra/test_dimension_de_los_vectores.py`.

## Desviaciones respecto a lo que D.7 esperaba

El prompt se escribió el 2026-08-23 y las cifras han cambiado por trabajo posterior:

| | D.7 esperaba | Realidad del 31-08 | Por qué |
|---|---:|---:|---|
| Chatbots | 3 | **4** | HIB.T creó un tercer asistente de Gerencia como banco de inyección |
| Documentos | 548 | **751** | El bloque ACT reingirió el corpus en los cuatro asistentes |
| Hallazgos | 288 | **292** | Curación posterior |
| Páginas | 351 | 351 | — |
| Informes / personas | 0 | 0 | — |

**Los dos asistentes «(proves)» viajan pero siguen `is_active=False`**: son bancos de medición,
invisibles para quien use el piloto, y sus fragmentos costarían embeddings si hubiera que
rehacerlos. D.7 pedía renombrar el agéntico para quitarle el «(proves)»; **no se ha hecho**,
porque ese renombrado se pensó cuando era uno de tres asistentes del piloto y HIB.U lo dejó
inactivo como banco: hoy «(proves)» describe lo que es.

## Cómo se restaura

```bash
# 1. Base limpia y migrada
createdb piloto
DATABASE_URL_SYNC=... uv run alembic upgrade head

# 2. El catálogo del producto (la contraseña la pide por teclado; nunca como argumento)
uv run python -m server.app.scripts.bootstrap --superadmin-email <correo> --con-demo

# 3. Los datos operativos
psql "$DSN" -f piloto.sql
```

El fichero desactiva los disparadores durante la carga (`session_replication_role = replica`)
porque `hub_chatbots` y `hub_documents` tienen claves ajenas circulares. El orden de las tablas
en el fichero es el orden de dependencias: **no reordenar**.

Después, comprobar los recuentos de la tabla de arriba. Si no cuadran, no restaures encima:
regenera el volcado.
