#!/usr/bin/env bash
#
# Volcado de los datos operativos que pasan al piloto (D.7).
#
# **Por qué existe.** Hasta ahora la pregunta «¿qué pasa al piloto?» sólo tenía dos respuestas
# posibles y las dos eran malas: un volcado completo —que arrastra los informes de prueba y toda
# la basura de test— o empezar de cero, tirando el corpus curado y los hallazgos ya revisados.
#
# **Lo que este guion NO hace, y es la mitad del asunto**: no lleva el catálogo del producto. Las
# plantillas demo se exportan a ficheros versionados en el repositorio y las siembra
# `bootstrap.py --con-demo`, así que la demo es reproducible, se revisa en un diff y es la misma
# en todos los despliegues. Es la misma regla que ya rige el vocabulario del corpus: lo que
# define el producto es dato versionado, no una fila que alguien tenía en su portátil.
#
# Uso:
#   scripts/volcado_piloto.sh --organizacion <UUID> --salida <FICHERO.sql> [--dry-run]
#
# La conexión se lee de `DATABASE_URL_SYNC` (o de `--dsn`), nunca cableada.

set -euo pipefail

ORGANIZACION=""
SALIDA=""
DSN="${DATABASE_URL_SYNC:-}"
DRY_RUN=0
#: Tablas que se saltan a peticion, para volcados en dos fases (los fragmentos pesan 1 GB y
#: no hace falta regenerarlos si ya estan subidos).
EXCLUIDAS=""

uso() {
  echo "Uso: $0 --organizacion <UUID> --salida <FICHERO.sql> [--dsn <DSN>] [--dry-run]" >&2
}

while [ $# -gt 0 ]; do
  case "$1" in
    --organizacion)   ORGANIZACION="${2:-}"; shift 2 ;;
    --organizacion=*) ORGANIZACION="${1#*=}"; shift ;;
    --salida)         SALIDA="${2:-}"; shift 2 ;;
    --salida=*)       SALIDA="${1#*=}"; shift ;;
    --dsn)            DSN="${2:-}"; shift 2 ;;
    --dsn=*)          DSN="${1#*=}"; shift ;;
    --excluir)        EXCLUIDAS="$EXCLUIDAS ${2:-}"; shift 2 ;;
    --excluir=*)      EXCLUIDAS="$EXCLUIDAS ${1#*=}"; shift ;;
    --dry-run)        DRY_RUN=1; shift ;;
    -h|--help)        uso; exit 0 ;;
    *) echo "ERROR: opción desconocida: $1" >&2; uso; exit 2 ;;
  esac
done

[ -n "$ORGANIZACION" ] || { echo "ERROR: falta --organizacion." >&2; uso; exit 2; }
[ -n "$SALIDA" ]       || { echo "ERROR: falta --salida." >&2; uso; exit 2; }
# #270 — se interpola en `sed` y en SQL, así que sólo se admite lo que es: un UUID.
[[ "$ORGANIZACION" =~ ^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$ ]] \
  || { echo "ERROR: --organizacion tiene que ser un UUID: «$ORGANIZACION»." >&2; uso; exit 2; }

# ---------------------------------------------------------------------------
# LO QUE VIAJA — lista explícita, y el porqué de cada tabla.
#
# Explícita y no «todo menos X»: una lista de exclusiones se queda corta el día que alguien
# añade una tabla, y entonces los datos de más viajan sin que nadie lo decida. Con una lista de
# inclusión, una tabla nueva se queda fuera por omisión, que es el lado seguro del error.
# ---------------------------------------------------------------------------
# Formato: tabla|filtro SQL (con :ORG)|razón
#
# **Cada tabla lleva su filtro escrito.** La primera versión de este guion usaba
# `pg_dump --table=…`, y `pg_dump` **no filtra filas**: volcaba la tabla entera. Lo peor es que
# imprimía antes un recuento por organización, así que *parecía* filtrado — 3,2 GB con datos de
# tres organizaciones ajenas, y sólo la comprobación sobre el fichero lo destapó. De ahí que
# aquí no haya un `pg_dump` sino un `\copy` por tabla con su `WHERE`.
#
# Los caminos no son uniformes y por eso se escriben uno a uno: unas tablas cuelgan de la
# organización, otras del chatbot, otras del sitio de curación. Una tabla nueva sin filtro no
# se puede volcar, que es el lado seguro del error.
_CHATBOTS_DE_LA_ORG="SELECT id FROM hub_chatbots WHERE organizacion_id = ':ORG'"
_SITIOS_DE_LA_ORG="SELECT id FROM hub_web_sites WHERE organizacion_id = ':ORG'"

# **El orden es el de las claves ajenas, y se comprobó contra el esquema, no de memoria.** La
# primera versión ponía `hub_documents` antes de `hub_crawled_pages` y a los chatbots sin su
# `hub_llm_configs`, y no fallaba porque la cabecera desactivaba los disparadores con
# `session_replication_role = replica`. **Cloud SQL no permite eso** —exige superusuario, que un
# servicio gestionado no concede—, y al quitarlo aparecieron los tres problemas que tapaba:
# falta la tabla de configuración de LLM, las páginas van antes que los documentos, y 138
# documentos se referencian entre sí. Desactivar una comprobación es una forma de no enterarse.
TABLAS=(
  "hub_organizaciones|id = ':ORG'|la organización del piloto, y sólo ella"
  "hub_providers|true|los proveedores de modelo; la configuración de embeddings apunta a uno y sin él no resuelve"
  "hub_llm_configs|id IN (SELECT DISTINCT llm_config_id FROM hub_chatbots WHERE organizacion_id = ':ORG' AND llm_config_id IS NOT NULL) OR organizacion_id IS NULL OR organizacion_id = ':ORG'|la configuración de modelo. TAMBIEN las de plataforma (organización nula): el modelo de embeddings se resuelve por purpose=embedding e is_default, y esa fila NO la referencia ningún chatbot; llevar sólo las referenciadas dejaba el corpus inservible"
  "hub_chatbots|organizacion_id = ':ORG'|los asistentes con su configuración medida (umbrales, top_k, modo)"
  "hub_web_sites|organizacion_id = ':ORG'|el sitio de curación. **Antes** de los documentos: 3 de ellos citan una página"
  "hub_crawled_pages|site_id IN ($_SITIOS_DE_LA_ORG)|sus páginas rastreadas, con las señales de frescura"
  "hub_documents|chatbot_id IN ($_CHATBOTS_DE_LA_ORG)|el corpus curado, con su vigencia y su validación"
  "hub_document_chunks|chatbot_id IN ($_CHATBOTS_DE_LA_ORG)|los fragmentos y sus vectores: reembeberlos cuesta GPU y horas"
  "hub_vocabulary_terms|organizacion_id = ':ORG' OR organizacion_id IS NULL|ámbitos y submaterias; sin esto la ingesta aborta. Los nulos son de plataforma y se heredan"
  "hub_lexicon_pairs|organizacion_id = ':ORG'|el puente léxico catalán/castellano de la búsqueda de texto"
  "hub_content_findings|site_id IN ($_SITIOS_DE_LA_ORG)|los hallazgos ya revisados por una persona: es trabajo humano"
  "hub_corpus_selections|chatbot_id IN ($_CHATBOTS_DE_LA_ORG)|qué páginas alimentan a qué asistente"
  "hub_prompt_templates|chatbot_id IN ($_CHATBOTS_DE_LA_ORG)|los prompts del sistema, afinados por medición"
  "hub_themes|organizacion_id = ':ORG' OR chatbot_id IN ($_CHATBOTS_DE_LA_ORG)|la identidad visual de la organización"
  "hub_widget_keys|chatbot_id IN ($_CHATBOTS_DE_LA_ORG)|las credenciales de sitio ya emitidas"
  "hub_module_grants|organizacion_id = ':ORG'|qué módulos tiene concedidos la organización"
)

#: Columnas que apuntan a la PROPIA tabla. Se cargan en dos pasos —primero a nulo, después un
#: `UPDATE`— porque en un `COPY` la comprobación es por fila: si el documento al que se apunta
#: viene después, falla. Ordenar las filas «bien» sería frágil (una cadena de dos saltos y vuelve
#: a romperse); dos pasos siempre funciona.
declare -A AUTORREFERENCIAS=(
  ["hub_documents"]="versio_idiomatica_de"
  ["hub_chatbots"]="parent_chatbot_id"
)

# ---------------------------------------------------------------------------
# LO QUE NO VIAJA — y se comprueba que no está en el fichero.
#
# No basta con no listarlas: se verifica sobre el volcado YA GENERADO. Un filtro mal escrito
# produce un `WHERE` que pasa los tests de la consulta y datos de más en el fichero, y esa
# diferencia es justo la que importa.
# ---------------------------------------------------------------------------
PROHIBIDAS=(
  "hub_workspaces|informes de prueba: 29 filas de basura de test"
  "hub_workspace_blocks|sus bloques"
  "hub_workspace_audit_events|sus eventos de auditoría"
  "hub_run_manifests|manifiestos de ejecución de informes"
  "hub_users|ninguna persona: se recrean por SSO al primer acceso"
  "hub_personal_access_tokens|credenciales de máquina, que se emiten donde se usan"
  "hub_interactions|conversaciones: son de quien preguntó, no del despliegue"
  "hub_test_runs|resultados de escenarios de prueba"
  "hub_test_scenarios|los escenarios"
  "hub_script_proposals|propuestas de script en revisión"
  "hub_report_templates|el catálogo del producto viaja como fichero, no como fila"
  "hub_report_template_versions|idem"
)

echo "== Volcado para el piloto =="
printf '  %-14s %s\n' "organización" "$ORGANIZACION"
printf '  %-14s %s\n' "salida" "$SALIDA"
echo
campo() { printf '%s' "$1" | cut -d'|' -f"$2"; }

# Una tabla excluida se salta, y se DICE que se salta: un volcado con una tabla menos y sin
# avisar es el que alguien restaura creyendo que está completo.
esta_excluida() {
  case " $EXCLUIDAS " in *" $1 "*) return 0 ;; *) return 1 ;; esac
}
if [ -n "${EXCLUIDAS// /}" ]; then
  echo "  EXCLUIDAS a petición:$EXCLUIDAS"
  echo "  (este volcado NO está completo; restaura también lo que falte)"
  echo
fi

echo "  Viajan ${#TABLAS[@]} tablas:"
for entrada in "${TABLAS[@]}"; do
  printf '    %-28s %s\n' "$(campo "$entrada" 1)" "$(campo "$entrada" 3)"
done
echo
echo "  NO viajan ${#PROHIBIDAS[@]} tablas:"
for entrada in "${PROHIBIDAS[@]}"; do
  printf '    %-28s %s\n' "${entrada%%|*}" "${entrada#*|}"
done
echo

if [ "$DRY_RUN" -eq 1 ]; then
  echo "(--dry-run: no se consulta la base y no se escribe nada.)"
  exit 0
fi

[ -n "$DSN" ] || { echo "ERROR: falta DATABASE_URL_SYNC o --dsn." >&2; exit 2; }
command -v psql >/dev/null 2>&1 || { echo "ERROR: psql no está en el PATH." >&2; exit 3; }


# `psql` y `pg_dump` quieren un DSN de libpq; SQLAlchemy añade el driver.
DSN_LIBPQ="$(printf '%s' "$DSN" | sed 's#^postgresql+psycopg2://#postgresql://#; s#^postgresql+asyncpg://#postgresql://#')"

# ---------------------------------------------------------------------------
# Recuento ANTES de escribir nada. Si las cifras no son las que se esperan, se para aquí y no
# después de haber generado un fichero que alguien podría restaurar.
# ---------------------------------------------------------------------------
echo "== Recuento en origen =="
declare -A RECUENTO
TOTAL=0
for entrada in "${TABLAS[@]}"; do
  tabla="$(campo "$entrada" 1)"
  esta_excluida "$tabla" && { printf "  [excluida] %s
" "$tabla"; continue; }
  filtro="$(campo "$entrada" 2 | sed "s/:ORG/$ORGANIZACION/g")"
  n="$(psql "$DSN_LIBPQ" -tAc "SELECT count(*) FROM $tabla WHERE $filtro" 2>&1 | tr -d '[:space:]')"
  case "$n" in
    ''|*[!0-9]*)
      echo "  [ERROR] $tabla: el filtro no se pudo evaluar" >&2
      echo "          $filtro" >&2
      exit 4
      ;;
  esac
  RECUENTO["$tabla"]="$n"
  TOTAL=$((TOTAL + n))
  printf '  %-28s %s\n' "$tabla" "$n"
done
echo
echo "  total de filas que viajan: $TOTAL"
echo "  Revisa estas cifras ANTES de continuar: son las que tienen que aparecer al restaurar."
echo

# ---------------------------------------------------------------------------
# Generación: un `\copy` por tabla con su filtro.
#
# Y **no** `pg_dump --table=…`: `pg_dump` no filtra filas, así que volcaría cada tabla entera.
# La primera versión de este guion hacía justo eso y produjo 3,2 GB con datos de tres
# organizaciones ajenas — sólo la comprobación sobre el fichero lo destapó.
# ---------------------------------------------------------------------------
echo "== Generando $SALIDA =="
: > "$SALIDA"
{
  echo "-- Volcado del piloto para la organización $ORGANIZACION"
  echo "-- Generado por scripts/volcado_piloto.sh. Restaurar con psql -f sobre una base ya migrada."
  echo "-- Orden de las tablas = orden de dependencias: NO reordenar."
  echo "--"
  echo "-- NO lleva 'session_replication_role': Cloud SQL lo prohíbe (exige superusuario), y"
  echo "-- desactivar las comprobaciones sólo servía para no enterarse de que el orden estaba mal."
  echo "-- Las columnas que apuntan a su propia tabla se cargan a nulo y se rellenan al final."
} >> "$SALIDA"

# Los UPDATE de las autorreferencias, que van al FINAL del fichero: para entonces todas las
# filas existen y ya no importa en qué orden se insertaron.
COLA="$(mktemp)"
trap 'rm -f "$COLA"' EXIT

for entrada in "${TABLAS[@]}"; do
  tabla="$(campo "$entrada" 1)"
  esta_excluida "$tabla" && { printf "  [excluida] %s
" "$tabla"; continue; }
  filtro="$(campo "$entrada" 2 | sed "s/:ORG/$ORGANIZACION/g")"
  [ "${RECUENTO[$tabla]}" != "0" ] || { printf '  [vacía] %s\n' "$tabla"; continue; }

  # Las columnas GENERADAS se excluyen: `COPY FROM` **no acepta** valores para ellas y falla con
  # «extra data after last expected column», un mensaje que suena a fichero corrupto y es una
  # columna de más. `hub_document_chunks.tsv` es la única hoy, y se recalcula sola de `content` y
  # `bilingual_terms`, así que llevarla no sólo estorba: sobra.
  auto="${AUTORREFERENCIAS[$tabla]:-}"
  columnas="$(psql "$DSN_LIBPQ" -tAc \
    "SELECT string_agg(column_name, ', ' ORDER BY ordinal_position) FROM information_schema.columns WHERE table_name = '$tabla' AND is_generated <> 'ALWAYS'" \
    | tr -d '\r')"

  if [ -n "$auto" ]; then
    # La columna que se autorreferencia sale como NULL en el COPY…
    seleccion="$(printf '%s' "$columnas" | sed "s/\b$auto\b/NULL AS $auto/")"
    # …y su valor real viaja como UPDATE al final.
    n_auto="$(psql "$DSN_LIBPQ" -tAc \
      "SELECT count(*) FROM $tabla WHERE ($filtro) AND $auto IS NOT NULL" | tr -d '[:space:]')"
    if [ "$n_auto" != "0" ]; then
      {
        echo ""
        echo "-- $tabla.$auto: $n_auto fila(s) que apuntan a su propia tabla."
      } >> "$COLA"
      psql "$DSN_LIBPQ" -tAc \
        "SELECT format('UPDATE $tabla SET $auto = %L WHERE id = %L;', $auto, id) FROM $tabla WHERE ($filtro) AND $auto IS NOT NULL" \
        >> "$COLA"
      printf '  [ok]    %-28s %s filas (+%s autorreferencias al final)\n' \
        "$tabla" "${RECUENTO[$tabla]}" "$n_auto"
    else
      printf '  [ok]    %-28s %s filas\n' "$tabla" "${RECUENTO[$tabla]}"
    fi
  else
    seleccion="$columnas"
    printf '  [ok]    %-28s %s filas\n' "$tabla" "${RECUENTO[$tabla]}"
  fi

  {
    echo ""
    echo "COPY $tabla ($columnas) FROM stdin;"
  } >> "$SALIDA"
  psql "$DSN_LIBPQ" -tAc "\\copy (SELECT $seleccion FROM $tabla WHERE $filtro) TO STDOUT" >> "$SALIDA"
  echo "\\." >> "$SALIDA"
done

cat "$COLA" >> "$SALIDA"
echo "  escrito: $(wc -c < "$SALIDA") bytes"
echo

# ---------------------------------------------------------------------------
# Verificación SOBRE EL FICHERO
# ---------------------------------------------------------------------------
echo "== Comprobando el fichero =="
PROBLEMAS=0
for entrada in "${PROHIBIDAS[@]}"; do
  tabla="${entrada%%|*}"
  if grep -qE "COPY (public\.)?$tabla " "$SALIDA"; then
    printf '  [FUGA]  %s aparece en el volcado (%s)\n' "$tabla" "${entrada#*|}"
    PROBLEMAS=$((PROBLEMAS + 1))
  fi
done
[ "$PROBLEMAS" -eq 0 ] && echo "  [ok]    ninguna tabla prohibida aparece en el fichero"

# Y que no viaje ninguna fila de otra organización. Se busca el UUID de la organización en las
# líneas de datos: si hay filas de otra, aparecerá algún UUID distinto en esa columna.
OTRAS="$(psql "$DSN_LIBPQ" -tAc \
  "SELECT string_agg(id::text, '|') FROM hub_organizaciones WHERE id <> '$ORGANIZACION'" \
  2>/dev/null || true)"
if [ -n "$OTRAS" ]; then
  while IFS= read -r otra; do
    [ -n "$otra" ] || continue
    if grep -qF "$otra" "$SALIDA"; then
      printf '  [FUGA]  aparece la organización %s\n' "$otra"
      PROBLEMAS=$((PROBLEMAS + 1))
    fi
  done < <(printf '%s' "$OTRAS" | tr '|' '\n')
  [ "$PROBLEMAS" -eq 0 ] && echo "  [ok]    ninguna otra organización aparece en el fichero"
else
  echo "  [i]     no hay otras organizaciones con las que confundirse"
fi
echo

if [ "$PROBLEMAS" -gt 0 ]; then
  rm -f "$SALIDA"
  echo "ERROR: $PROBLEMAS problema(s). **El fichero se ha borrado**: un volcado con datos de más" >&2
  echo "       que se queda en el disco es el que alguien restaura por error." >&2
  exit 1
fi

echo "Volcado listo. Restaurar en una base limpia y comprobar los recuentos de arriba."
