#!/usr/bin/env bash
#
# Vigilancia del despliegue (D.6-VM): canal de avisos, comprobación de salud y alertas.
# Idempotente y versionado, como el resto.
#
# **Por qué esto existe.** Un servicio gestionado trae el reinicio, el registro y la salud
# gratis; una VM no. Ésta es la contrapartida honesta de haber elegido VM, y sin ella la
# primera noticia de una caída la da un usuario.
#
# **Por qué por API y no con `gcloud`.** Los canales de notificación viven en `gcloud beta`, y
# instalar un componente en el SDK de quien ejecuta esto es tocar su máquina para nada: la API
# REST hace lo mismo y no cambia nada en local.
#
# **Las alertas de memoria y disco necesitan el agente de operaciones** en la VM. Sin él,
# Cloud Monitoring sólo ve la máquina desde fuera —CPU y red— y estas dos alertas no se podrían
# ni escribir. Lo instala `deploy/vm/startup.sh`.
#
# Uso:
#   scripts/gcp_provision_vigilancia.sh --project <ID> --host <HOST> --email <CORREO>
#                                       [--vm govgenai-vm] [--dry-run]

set -euo pipefail

PROYECTO=""
HOST=""
CORREO=""
VM="govgenai-vm"
DRY_RUN=0

uso() {
  echo "Uso: $0 --project <ID> --host <HOST> --email <CORREO> [--vm <NOMBRE>] [--dry-run]" >&2
}

while [ $# -gt 0 ]; do
  case "$1" in
    --project)   PROYECTO="${2:-}"; shift 2 ;;
    --project=*) PROYECTO="${1#*=}"; shift ;;
    --host)      HOST="${2:-}"; shift 2 ;;
    --host=*)    HOST="${1#*=}"; shift ;;
    --email)     CORREO="${2:-}"; shift 2 ;;
    --email=*)   CORREO="${1#*=}"; shift ;;
    --vm)        VM="${2:-}"; shift 2 ;;
    --vm=*)      VM="${1#*=}"; shift ;;
    --dry-run)   DRY_RUN=1; shift ;;
    -h|--help)   uso; exit 0 ;;
    *) echo "ERROR: opción desconocida: $1" >&2; uso; exit 2 ;;
  esac
done

[ -n "$PROYECTO" ] || { echo "ERROR: falta --project." >&2; uso; exit 2; }
[ -n "$HOST" ] || { echo "ERROR: falta --host (el nombre por el que responde /health)." >&2; uso; exit 2; }
if [ -z "$CORREO" ]; then
  echo "ERROR: falta --email. Una alerta que no llega a una persona no es una alerta." >&2
  uso
  exit 2
fi

API="https://monitoring.googleapis.com/v3/projects/$PROYECTO"

echo "== Vigilancia =="
printf '  %-14s %s\n' "proyecto" "$PROYECTO"
printf '  %-14s %s\n' "host" "$HOST"
printf '  %-14s %s\n' "avisos a" "$CORREO"
printf '  %-14s %s\n' "máquina" "$VM"
echo
echo "  Se crean: 1 canal de correo, 1 comprobación de salud sobre https://$HOST/health,"
echo "  y 3 alertas — caída de la comprobación, memoria > 85 % y disco > 85 %."
echo

if [ "$DRY_RUN" -eq 1 ]; then
  echo "(--dry-run: no se llama a ninguna API y no se crea nada.)"
  exit 0
fi

command -v gcloud >/dev/null 2>&1 || { echo "ERROR: gcloud no está en el PATH." >&2; exit 3; }
command -v curl >/dev/null 2>&1 || { echo "ERROR: curl no está en el PATH." >&2; exit 3; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

limpiar() { tr -d '\r\n'; }
# #270 — el token va en un fichero que sólo lee quien ejecuta, y `curl` lo lee con `-H @…`.
# Como argumento se veía con `ps` mientras duraba cada llamada. `printf` es un builtin, así que
# tampoco aparece en la línea de órdenes de ningún proceso.
CABECERA="$TMP/cabecera"
(umask 077; printf 'Authorization: Bearer %s\n' "$(gcloud auth print-access-token | limpiar)" > "$CABECERA")

# Escribe el cuerpo en la salida y deja el código HTTP en "$TMP/codigo".
llamar() { # método ruta [fichero_json]
  local metodo="$1" ruta="$2" cuerpo="${3:-}"
  local opciones=(-sS -X "$metodo" "$ruta" -H "@$CABECERA" -o "$TMP/cuerpo" -w '%{http_code}')
  if [ -n "$cuerpo" ]; then
    opciones+=(-H "Content-Type: application/json" --data-binary "@$cuerpo")
  fi
  curl "${opciones[@]}" > "$TMP/codigo"
  cat "$TMP/cuerpo"
}

# Para meter el correo en la URL del filtro: `+` y `@` tienen significado ahí.
codificar() {
  local LC_ALL=C texto="$1" i c salida=""
  for ((i = 0; i < ${#texto}; i++)); do
    c="${texto:i:1}"
    case "$c" in
      [a-zA-Z0-9.~_-]) salida+="$c" ;;
      *) printf -v c '%%%02X' "'$c"; salida+="$c" ;;
    esac
  done
  printf '%s' "$salida"
}

# Como `llamar`, pero **mira la respuesta**. La primera versión de este guion canalizaba los
# POST a /dev/null e imprimía «[creada]» a continuación, pasara lo que pasara: la comprobación
# de salud falló con «selected_regions must include at least three locations», el error se
# perdió, el guion dijo que la había creado y la alerta de caída quedó **inerte** —no puede
# dispararse sin la comprobación que la alimenta— sin que nada lo delatara. Es el mismo defecto
# que un `tail` comiéndose un código de salida: no basta con actuar, hay que leer el resultado.
#
# #270 — se mira el **código HTTP**, no si el cuerpo contiene `"error"`: un cuerpo bueno puede
# contener la palabra —una alerta que se llame así— y uno malo puede no traerla.
crear() { # ruta fichero_json etiqueta
  local ruta="$1" cuerpo="$2" etiqueta="$3" respuesta codigo
  respuesta="$(llamar POST "$ruta" "$cuerpo")"
  codigo="$(cat "$TMP/codigo")"
  if [ "${codigo:0:1}" != "2" ]; then
    echo "  [ERROR]     $etiqueta (HTTP $codigo):" >&2
    printf '%s' "$respuesta" | tr ',' '\n' | grep -E '"message"|"status"' | head -2 >&2
    return 1
  fi
  printf '  [creada]    %s\n' "$etiqueta"
}

# ---------------------------------------------------------------------------
# 1. Canal de avisos
# ---------------------------------------------------------------------------
echo "== 1. Canal de avisos =="

# Se filtra en la API y se extrae con `grep`, sin `python3`: este guion se ejecuta desde la
# máquina de quien despliega, y en Git Bash de Windows no hay `python3` — la primera versión
# lo usaba para leer el JSON y se rompió con un «curl: Failed writing body» que no señalaba
# a la causa.
FILTRO="filter=labels.email_address%3D%22$(codificar "$CORREO")%22"
canal_existente() {
  llamar GET "$API/notificationChannels?$FILTRO" \
    | tr -d ' \n' | grep -o '"name":"[^"]*"' | head -1 | cut -d'"' -f4
}

CANAL_ID="$(canal_existente || true)"
if [ -n "$CANAL_ID" ]; then
  echo "  [ya estaba] un canal con $CORREO"
else
  cat > "$TMP/canal.json" <<JSON
{
  "type": "email",
  "displayName": "Gov Gen AI - avisos",
  "labels": { "email_address": "$CORREO" }
}
JSON
  crear "$API/notificationChannels" "$TMP/canal.json" "canal de correo a $CORREO"
  CANAL_ID="$(canal_existente || true)"
fi

[ -n "$CANAL_ID" ] || { echo "ERROR: no se pudo resolver el canal de avisos." >&2; exit 4; }
echo "  canal: $CANAL_ID"
echo

# ---------------------------------------------------------------------------
# 2. Comprobación de salud
# ---------------------------------------------------------------------------
echo "== 2. Comprobación de salud =="
API_UPTIME="https://monitoring.googleapis.com/v3/projects/$PROYECTO/uptimeCheckConfigs"
YA="$(llamar GET "$API_UPTIME" | grep -c "\"host\": \"$HOST\"" || true)"
if [ "${YA:-0}" -gt 0 ]; then
  echo "  [ya estaba] comprobación sobre $HOST"
else
  cat > "$TMP/uptime.json" <<JSON
{
  "displayName": "Gov Gen AI - salud",
  "monitoredResource": {
    "type": "uptime_url",
    "labels": { "host": "$HOST", "project_id": "$PROYECTO" }
  },
  "httpCheck": {
    "path": "/health",
    "port": 443,
    "useSsl": true,
    "validateSsl": true,
    "requestMethod": "GET"
  },
  "period": "300s",
  "timeout": "10s"
}
JSON
  # Sin `selectedRegions`: la API exige **al menos tres** («selected_regions must include at
  # least three locations») y omitirlo significa comprobar desde todas, que para un extremo
  # público es la respuesta honesta — si sólo responde en Europa, eso es información.
  crear "$API_UPTIME" "$TMP/uptime.json" "comprobación cada 5 min sobre https://$HOST/health"
fi
echo

# ---------------------------------------------------------------------------
# 3. Alertas
#
# `validateSsl` en la comprobación no es un detalle: con TLS mal renovado el servicio
# responde y la comprobación pasaría, que es justo el fallo que nadie ve venir.
# ---------------------------------------------------------------------------
echo "== 3. Alertas =="
API_ALERT="https://monitoring.googleapis.com/v3/projects/$PROYECTO/alertPolicies"
EXISTENTES="$(llamar GET "$API_ALERT" || true)"

crear_alerta() { # nombre fichero
  local nombre="$1" fichero="$2"
  if printf '%s' "$EXISTENTES" | grep -q "\"displayName\": \"$nombre\""; then
    echo "  [ya estaba] $nombre"
    return
  fi
  crear "$API_ALERT" "$fichero" "$nombre"
}

# **Se agrupa entre series y se exige más de una región.** Sin `crossSeriesReducer`, cada
# región de comprobación es su propia serie y abre su propio incidente: la primera versión
# mandó **seis correos por una sola caída** —Bélgica, Singapur, Brasil y tres de EE. UU.—, y
# seis avisos de lo mismo enseñan a ignorar los avisos. Agrupando por host sale uno.
#
# Y el umbral es «más de una región fallando», no «alguna»: un parpadeo de red entre un
# comprobador y la máquina no es una caída del servicio, y despertar a alguien por eso gasta
# la credibilidad de la alerta que sí importa.
cat > "$TMP/alerta_salud.json" <<JSON
{
  "displayName": "Gov Gen AI - la salud no responde",
  "combiner": "OR",
  "conditions": [{
    "displayName": "la comprobacion falla en mas de una region",
    "conditionThreshold": {
      "filter": "metric.type=\"monitoring.googleapis.com/uptime_check/check_passed\" AND resource.type=\"uptime_url\"",
      "aggregations": [{
        "alignmentPeriod": "600s",
        "perSeriesAligner": "ALIGN_NEXT_OLDER",
        "crossSeriesReducer": "REDUCE_COUNT_FALSE",
        "groupByFields": ["resource.label.host"]
      }],
      "comparison": "COMPARISON_GT",
      "thresholdValue": 1,
      "duration": "60s",
      "trigger": { "count": 1 }
    }
  }],
  "notificationChannels": ["$CANAL_ID"]
}
JSON
crear_alerta "Gov Gen AI - la salud no responde" "$TMP/alerta_salud.json"

cat > "$TMP/alerta_memoria.json" <<JSON
{
  "displayName": "Gov Gen AI - memoria por encima del 85%",
  "combiner": "OR",
  "conditions": [{
    "displayName": "memoria usada > 85%",
    "conditionThreshold": {
      "filter": "metric.type=\"agent.googleapis.com/memory/percent_used\" AND resource.type=\"gce_instance\" AND metric.labels.state=\"used\"",
      "aggregations": [{ "alignmentPeriod": "300s", "perSeriesAligner": "ALIGN_MEAN" }],
      "comparison": "COMPARISON_GT",
      "thresholdValue": 85,
      "duration": "600s",
      "trigger": { "count": 1 }
    }
  }],
  "notificationChannels": ["$CANAL_ID"]
}
JSON
crear_alerta "Gov Gen AI - memoria por encima del 85%" "$TMP/alerta_memoria.json"

cat > "$TMP/alerta_disco.json" <<JSON
{
  "displayName": "Gov Gen AI - disco por encima del 85%",
  "combiner": "OR",
  "conditions": [{
    "displayName": "disco usado > 85%",
    "conditionThreshold": {
      "filter": "metric.type=\"agent.googleapis.com/disk/percent_used\" AND resource.type=\"gce_instance\" AND metric.labels.state=\"used\"",
      "aggregations": [{ "alignmentPeriod": "300s", "perSeriesAligner": "ALIGN_MEAN" }],
      "comparison": "COMPARISON_GT",
      "thresholdValue": 85,
      "duration": "600s",
      "trigger": { "count": 1 }
    }
  }],
  "notificationChannels": ["$CANAL_ID"]
}
JSON
crear_alerta "Gov Gen AI - disco por encima del 85%" "$TMP/alerta_disco.json"
echo

echo "== Comprobación =="
FALTA=0

# La comprobación de salud se verifica **aparte y primero**. La versión anterior sólo revisaba
# las alertas, y por eso una comprobación que nunca se creó pasó desapercibida: la alerta de
# caída existía y parecía correcta, pero sin la comprobación que la alimenta **no puede
# dispararse**. Una alerta huérfana es peor que ninguna, porque da la impresión de cobertura.
if printf '%s' "$(llamar GET "$API_UPTIME" || true)" | grep -q "\"host\": \"$HOST\""; then
  printf '  [ok]    comprobación de salud sobre %s\n' "$HOST"
else
  printf '  [FALTA] comprobación de salud sobre %s — la alerta de caída no podría dispararse\n' "$HOST"
  FALTA=$((FALTA + 1))
fi

FINAL="$(llamar GET "$API_ALERT" || true)"
for nombre in "la salud no responde" "memoria por encima" "disco por encima"; do
  if printf '%s' "$FINAL" | grep -q "$nombre"; then
    printf '  [ok]    %s\n' "$nombre"
  else
    printf '  [FALTA] %s\n' "$nombre"
    FALTA=$((FALTA + 1))
  fi
done
echo

if [ "$FALTA" -gt 0 ]; then
  echo "ERROR: faltan $FALTA piezas de la vigilancia. No se puede dar por vigilado." >&2
  exit 1
fi
echo "AVISO: una alerta que nadie ha visto disparar es una hipótesis. Pruébala apagando el"
echo "       servicio (D.6-VM lo pide en su cierre) y comprueba que el correo llega."
