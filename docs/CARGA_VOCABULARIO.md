# Carga del vocabulario controlado del corpus

Cómo cargar el vocabulario (ámbitos y submaterias) en una instalación, antes de ingerir el
corpus normativo. El vocabulario es **dato versionado por organización**, no código
(regla del proyecto): estos CSV se cargan en la tabla `hub_vocabulary_terms` y se pueden
recargar sin re-embeber nada.

> **Recordatorio de la estrategia del corpus.** La taxonomía **nunca** entra en el texto que
> se embebe. Cargar o cambiar el vocabulario es un `UPDATE`/recarga, no una reingesta. El
> vocabulario está **pendiente de validación por Secretaría General** (Hito B): va a cambiar,
> y por eso vive como dato.

## Qué se carga

Dos ejes, con los CSV que produce la curación del corpus (`normativa_propia/vocabulari/`):

| Eje | CSV | Columnas usadas por el loader |
|-----|-----|-------------------------------|
| `ambit` | `ambits.csv` | `codi`, `nom_val`, `nom_es`, `descripcio_router` |
| `submateria` | `submateries.csv` | `codi`, `nom_val`, `nom_es`, `ambit` (padre), `abast` |

El resto de columnas (`assistent`, `propietari_proposat`, recuentos, `normes_exemple`) es
documentación del informe de materias y el loader las ignora sin romper.

## Prerrequisitos

1. **Base de datos arrancada** (`docker compose up -d db` o el stack completo). El loader lee
   `DATABASE_URL` del entorno.
2. **La organización destino ya existe.** En una instalación recién sembrada la crea
   `server.app.scripts.bootstrap` («Organización de ejemplo»). Necesitas su UUID.

### Obtener el UUID de la organización

```powershell
docker compose exec db psql -U govgenai -d govgenai -c "SELECT id, name FROM hub_organizaciones;"
```

(o el mismo `SELECT` desde tu cliente SQL habitual). Copia el `id` de la organización que va a
usar el chatbot del corpus.

## Comandos de carga

Desde la **raíz del repo** (`C:/Users/fabra/Documents/AI_agents_hub`). **El orden importa**:
primero `ambit`, luego `submateria` — cada submateria referencia un `ambit` como padre y, si el
ámbito no está cargado todavía, el CSV se **rechaza entero** (no carga a medias, a propósito).

Empieza con `--dry-run` para ver el plan sin escribir, y repite sin él para aplicar.

```powershell
$env:VOCAB = "C:/Users/fabra/Documents/Descarregar_pdf/normativa_propia/vocabulari"
$env:ORG  = "<UUID-de-la-organizacion>"
$PY = "server/.venv/Scripts/python.exe"

# 1) Ámbitos (primero) — dry-run y luego real
& $PY -m server.app.modules.agents_hub.vocabulary.load --axis ambit --csv "$env:VOCAB/ambits.csv" --organizacion-id $env:ORG --dry-run
& $PY -m server.app.modules.agents_hub.vocabulary.load --axis ambit --csv "$env:VOCAB/ambits.csv" --organizacion-id $env:ORG

# 2) Submaterias (después) — dry-run y luego real
& $PY -m server.app.modules.agents_hub.vocabulary.load --axis submateria --csv "$env:VOCAB/submateries.csv" --organizacion-id $env:ORG --dry-run
& $PY -m server.app.modules.agents_hub.vocabulary.load --axis submateria --csv "$env:VOCAB/submateries.csv" --organizacion-id $env:ORG
```

Salida esperada de cada pasada: `NN términos leídos` y `creados=… actualizados=… sin_cambios=…`.

## Notas

- **Idempotente** por la clave natural `(organizacion_id, axis, codi)`: repetir una carga no
  duplica y reporta `sin_cambios`. Cambiar `nom`/`abast`/orden en el CSV y recargar hace `UPDATE`.
- **Renombrar o fusionar** un término no se hace editando el CSV a mano en producción, sino con
  el modo `--substituir` del mismo módulo, que preserva el histórico (`vigent=False` +
  `substituit_per_codi`) **y reclasifica los documentos que usaban el código viejo**:

  ```powershell
  & $PY -m server.app.modules.agents_hub.vocabulary.load --axis submateria `
      --substituir rrhh-ptgas --per rrhh-ptgas-condicions --organizacion-id $env:ORG --dry-run
  ```

  Con `--dry-run` dice cuántos documentos se reclasificarían sin escribir nada. **Las dos mitades
  van juntas a propósito** (issue #153): este documento decía «usa `supersede_term`» y esa
  función no era alcanzable desde ningún sitio, así que renombrar era imposible sin abrir un
  intérprete — y quien lo hiciera se dejaría la segunda mitad, que no da ningún error: el término
  queda retirado y los documentos siguen clasificados con el código viejo.

  Los ejes `rang` y `colectiu` viven en `doc_metadata` y no gobiernan la recuperación: se
  sustituyen igual y el barrido reporta 0.
- **El `ordre`** de presentación del router sale del orden de las filas del CSV.
- Un `parent_codi` (columna `ambit`) inexistente aborta el CSV de submaterias entero, nombrando
  los códigos colgantes. Es la señal de que falta cargar (o corregir) algún ámbito.

## Después de cargar

La validación de la ingesta (`assert_vocabulary`) comprueba que los códigos
`ambit_principal`/`submateries` del front-matter de los documentos existan y estén vigentes en
este vocabulario.

> **Corregido el 2026-08-15 (PIL.4).** Esto decía que los documentos «aún no emiten esos
> campos» y que por tanto «la validación pasa trivialmente». **Ya los emiten**: los 298 del
> paquete `normatiu` y los 124 del de `gerencia` traen `ambit_principal` y `submateries` en
> campos reales. La consecuencia es la contraria de la que prometía este documento: **sin el
> vocabulario cargado, la ingesta aborta entera** —y lo hace antes de escribir nada,
> enumerando todos los códigos desconocidos, no el primero—. Cargar el vocabulario dejó de
> ser un paso preparatorio y es un prerrequisito.

Verificado el 2026-08-15 sobre los dos paquetes del piloto, con el vocabulario ya cargado
(5 ámbitos + 58 submaterias): 298 y 124 entradas válidas, vocabulario OK en ambas.

Ver `docs/AUDITORIA_PRE_DEPLOY.md` §3 y el bloque ING.0 del plan.
