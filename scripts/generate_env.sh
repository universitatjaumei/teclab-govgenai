#!/usr/bin/env bash
# Generador de configuración inicial (Fase 11.1 — Autoinstalación).
#
# Crea .env (raíz, leído por docker-compose), server/.env (copia, leído por
# server/app/core/config.py al ejecutar el backend fuera de Docker) y
# frontend/.env (VITE_API_URL, leído por Vite). Los secretos se generan
# aleatoriamente en cada ejecución; nunca sobrescribe ficheros existentes
# salvo que se pase --force.
#
# Uso:
#   scripts/generate_env.sh [--mode local|cloud] [--force] [--output-dir DIR]
#
# Modo local (por defecto): 100% sin servicios de pago — Ollama para el LLM
# (configurable luego en /hub/llm-configs) y MinIO para almacenamiento.
# Modo cloud: deja comentadas las opciones de Google Vertex AI / GCS-S3 listas
# para descomentar y rellenar.

set -euo pipefail

MODE="local"
FORCE=0
OUTPUT_DIR=""

while [ $# -gt 0 ]; do
  case "$1" in
    --mode)
      MODE="${2:-}"
      shift 2
      ;;
    --force)
      FORCE=1
      shift
      ;;
    --output-dir)
      OUTPUT_DIR="${2:-}"
      shift 2
      ;;
    *)
      echo "Argumento desconocido: $1" >&2
      exit 1
      ;;
  esac
done

if [ "$MODE" != "local" ] && [ "$MODE" != "cloud" ]; then
  echo "Error: --mode debe ser 'local' o 'cloud' (recibido: '$MODE')" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ -z "$OUTPUT_DIR" ]; then
  OUTPUT_DIR="$SCRIPT_DIR"
fi

mkdir -p "$OUTPUT_DIR/server" "$OUTPUT_DIR/frontend"

# --- Secretos generados en cada ejecución ---------------------------------
JWT_SECRET_KEY="$(openssl rand -hex 32)"
# SEC.2.1: secreto de la cabecera X-GovGenAI-Actor. Se genera siempre aunque hoy solo lo use
# el Pipe de Open WebUI: un secreto sin usar no cuesta nada, y pedirlo a mano el dia del
# despliegue es como se acaba compartiendo el de otro entorno.
DELEGATED_ACTOR_SECRET="$(openssl rand -hex 32)"
LANGFUSE_NEXTAUTH_SECRET="$(openssl rand -hex 32)"
LANGFUSE_SALT="$(openssl rand -hex 32)"
LANGFUSE_ENCRYPTION_KEY="$(openssl rand -hex 32)"
POSTGRES_PASSWORD="$(openssl rand -hex 16)"
MINIO_ROOT_PASSWORD="$(openssl rand -hex 16)"
LANGFUSE_PUBLIC_KEY="lf-pk-govgenai-$(openssl rand -hex 8)"
LANGFUSE_SECRET_KEY="lf-sk-govgenai-$(openssl rand -hex 8)"
LANGFUSE_ADMIN_PASSWORD="$(openssl rand -hex 12)"
[ "$MODE" = "local" ] && APP_ENVIRONMENT="development" || APP_ENVIRONMENT="production"
# SEC.3: en local se deja vacío (comodín en desarrollo). El generador no puede adivinar el
# dominio del panel en producción, así que lo deja vacío y visible: mejor un CORS que falla
# con nombre propio en la consola del navegador que un comodín puesto por un script.
CORS_ALLOWED_ORIGINS="${CORS_ALLOWED_ORIGINS:-}"

# Clave RSA para la firma de manifiestos (AUTOMATIA_SIGNING_KEY). PKCS1 PEM;
# server/app/services/manifest_signature_service.py normaliza '\n' literal a
# saltos de línea reales al cargarla.
RSA_PEM="$(openssl genrsa 2048 2>/dev/null)"
AUTOMATIA_SIGNING_KEY="$(printf '%s\n' "$RSA_PEM" | awk 'BEGIN{ORS="\\n"} {print}')"

if [ "$MODE" = "local" ]; then
  STORAGE_BACKEND="file"
  STORAGE_BUCKET="/tmp/govgenai_uploads"
  STORAGE_COMMENT="# Modo local: almacenamiento en el sistema de archivos del contenedor/host."
else
  STORAGE_BACKEND="s3"
  STORAGE_BUCKET="govgenai"
  STORAGE_COMMENT="# Modo cloud: descomenta STORAGE_BACKEND=gcs y rellena tus credenciales GCS/S3 mas abajo."
fi

render_env() {
  cat <<EOF
# =============================================================
# Gov Gen AI Platform — Configuracion generada por
# scripts/generate_env.sh (modo: ${MODE})
# =============================================================
# Este fichero contiene secretos. NO lo subas a git (ya esta en .gitignore).
# Para regenerar con secretos nuevos: scripts/generate_env.sh --force

# === BASE DE DATOS ===
# PostgreSQL + pgvector. En docker-compose estas variables ya se usan para
# levantar el contenedor "postgres"; DATABASE_URL debe apuntar al mismo host.
POSTGRES_DB=govgenai
POSTGRES_USER=govgenai
POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
DATABASE_URL=postgresql+asyncpg://govgenai:${POSTGRES_PASSWORD}@localhost:5432/govgenai
DATABASE_URL_SYNC=postgresql+psycopg2://govgenai:${POSTGRES_PASSWORD}@localhost:5432/govgenai

# === AUTENTICACION SSO (SAML 2.0) ===
# Desactivado por defecto: el login email+contrasena (superadmin/admin) sigue
# activo como fallback. Actívalo solo si tu institución tiene un IdP SAML.
SAML_ENABLED=false
SAML_SP_ENTITY_ID=https://tu-dominio.example/sp
SAML_SP_ACS_URL=https://tu-dominio.example/api/v1/auth/saml/acs
# SAML_SP_X509_CERT=
# SAML_SP_PRIVATE_KEY=
# Metadata del IdP institucional — usa una de las dos:
# SAML_IDP_METADATA_URL=https://idp.tu-institucion.example/idp/shibboleth
# SAML_IDP_METADATA_XML=
# Nombres de los atributos que emite tu IdP (ajusta si difieren):
SAML_ATTR_EMAIL=mail
SAML_ATTR_NAME=displayName
SAML_ATTR_ROLE=role
SAML_ATTR_GROUPS=groups
# Mapeo grupo del IdP -> rol del sistema (JSON). Precedencia: superadmin>admin>informer>user.
# SAML_GROUP_ROLE_MAP={"pas-informatica":"admin","govgenai-admins":"superadmin"}
SAML_DEFAULT_ROLE=user
# Login local de una PERSONA (USR.2), mientras el IdP no este configurado. Con `false`,
# POST /auth/user/login responde 404. El defecto es `true` AHORA; con el SSO en marcha, se apaga.
LOCAL_USER_LOGIN_ENABLED=true
# De DESARROLLO, donde el panel se sirve en la raiz. En un despliegue el panel vive bajo
# `/panel/` (DOM.2) y la vuelta del ACS lleva el prefijo: https://<dominio>/panel/auth/callback.
SAML_FRONTEND_RETURN_URL=http://localhost:5173/auth/callback

# === MODELOS DE LENGUAJE (elige uno o varios; se configuran por chatbot en /hub/llm-configs) ===
# Opción A: Google Vertex AI / Gemini — rellena tu clave:
GOOGLE_API_KEY=
# Opción B: OpenRouter (acceso a múltiples proveedores con una sola clave):
OPENROUTER_API_KEY=
# Opción B bis: OpenAI directo:
OPENAI_API_KEY=
# Opción C: Local (Ollama) — sin coste, sin clave. Instala Ollama y crea el
# proveedor "ollama" en /hub/llm-configs con base_url=http://localhost:11434/v1
# (o http://ollama:11434/v1 si Ollama corre como contenedor — ver Fase 11.2).

# === ALMACENAMIENTO DE ARCHIVOS ===
${STORAGE_COMMENT}
STORAGE_BACKEND=${STORAGE_BACKEND}
STORAGE_BUCKET=${STORAGE_BUCKET}
# Opción A: Google Cloud Storage (producción Cloud Run) — credenciales via
# Application Default Credentials o GOOGLE_APPLICATION_CREDENTIALS:
# STORAGE_BACKEND=gcs
# STORAGE_BUCKET=govgenai-prod
# Opción B: MinIO (contenedor local, sin coste) via S3:
# STORAGE_BACKEND=s3
# STORAGE_BUCKET=govgenai
# STORAGE_ENDPOINT=http://localhost:9000
# STORAGE_ACCESS_KEY=minioadmin
# STORAGE_SECRET_KEY=${MINIO_ROOT_PASSWORD}
MINIO_ROOT_USER=minioadmin
MINIO_ROOT_PASSWORD=${MINIO_ROOT_PASSWORD}

# === LÍMITES DE SUBIDA (SEC.6) ===
MAX_UPLOAD_MB=10
# 0 = sin límite de documentos por chatbot
MAX_DOCUMENTS_PER_CHATBOT=0

# === CONECTIVIDAD INSTITUCIONAL (servidor MCP — mcp_server/) ===
# El servidor MCP es un proceso aparte (cliente stdio para Claude Code / IDEs).
# Emite un Personal Access Token desde /plataforma/tokens tras el primer login
# y arráncalo con esas dos variables (no van en el .env de la app):
# GOVGENAI_API_BASE_URL=http://localhost:8000
# GOVGENAI_PAT=pat_...

# === Autenticación JWT (sesiones humanas) ===
JWT_SECRET_KEY=${JWT_SECRET_KEY}
JWT_ALGORITHM=HS256
JWT_EXPIRATION_MINUTES=60

# === Identidad delegada (SEC.2.1) ===
# Compartir con el cliente de confianza que firma X-GovGenAI-Actor. Sin el scope
# chat:onbehalf en su PAT, la cabecera se ignora aunque la firma sea correcta.
DELEGATED_ACTOR_SECRET=${DELEGATED_ACTOR_SECRET}

# === App ===
ENVIRONMENT=${APP_ENVIRONMENT}
DEPLOY_MODE=all
# SEC.3: origenes permitidos desde un navegador. En modo local se deja vacio (comodin en
# desarrollo); en produccion hay que enumerar el dominio del panel y los de los widgets, o
# ningun navegador podra llamar a la API. Se deja escrito y vacio, y no ausente, para que se
# vea que falta rellenarlo.
CORS_ALLOWED_ORIGINS=${CORS_ALLOWED_ORIGINS}
# SEC.4: limite de PETICIONES (el gasto en tokens son las cuotas, que van en la BD).
RATE_LIMIT_LOGIN=10/minute
RATE_LIMIT_CHAT=30/minute

# === Sandbox de scripts (microservicio aislado — Bloque SBX) ===
SANDBOX_BASE_URL=http://script-sandbox:5000
SANDBOX_TIMEOUT_SECONDS_DEFAULT=30

# === Calidad de contenido web (scheduler — Bloque 9Q) ===
CONTENT_QUALITY_ENABLED=true
CONTENT_QUALITY_INTERVAL_HOURS=24
CONTENT_QUALITY_SEMANTIC_ENABLED=true

# === Sincronizacion del corpus con el servicio de publicacion (Bloque SYNC) ===
# Se dejan vacias a proposito: son datos del cliente y no hay valor por defecto sensato.
# El token es un secreto; en produccion va por Secret Manager (D.2), no en este fichero.
PUBLICATION_MCP_URL=
PUBLICATION_DATASET_INDEX=
PUBLICATION_DATASET_CONTENT=
PUBLICATION_DATASET_TOKEN=

# === Firma de manifiestos (RSA, autogenerada) ===
AUTOMATIA_SIGNING_KEY="${AUTOMATIA_SIGNING_KEY}"

# === LangFuse (observabilidad — autogenerado, valores usados por docker-compose) ===
LANGFUSE_PUBLIC_KEY=${LANGFUSE_PUBLIC_KEY}
LANGFUSE_SECRET_KEY=${LANGFUSE_SECRET_KEY}
LANGFUSE_HOST=http://localhost:3000
LANGFUSE_NEXTAUTH_SECRET=${LANGFUSE_NEXTAUTH_SECRET}
LANGFUSE_SALT=${LANGFUSE_SALT}
LANGFUSE_ENCRYPTION_KEY=${LANGFUSE_ENCRYPTION_KEY}
LANGFUSE_ADMIN_EMAIL=admin@govgenai.local
LANGFUSE_ADMIN_PASSWORD=${LANGFUSE_ADMIN_PASSWORD}
EOF
}

write_if_absent() {
  local target="$1"
  if [ -f "$target" ] && [ "$FORCE" -ne 1 ]; then
    echo "Ya existe, se conserva (usa --force para regenerar): $target"
    return 0
  fi
  # #270 — lleva la contraseña de Postgres, el secreto JWT y la clave privada RSA: sólo su
  # dueño lo lee. `umask` cubre el fichero nuevo; `chmod`, el que ya existía y se regenera con
  # `--force`, porque redirigir a un fichero existente conserva sus permisos.
  (umask 077; render_env > "$target")
  chmod 600 "$target"
  echo "Generado: $target"
}

write_if_absent "$OUTPUT_DIR/.env"
write_if_absent "$OUTPUT_DIR/server/.env"

FRONTEND_ENV="$OUTPUT_DIR/frontend/.env"
if [ -f "$FRONTEND_ENV" ] && [ "$FORCE" -ne 1 ]; then
  echo "Ya existe, se conserva (usa --force para regenerar): $FRONTEND_ENV"
else
  cat > "$FRONTEND_ENV" <<EOF
# URL base de la API (backend FastAPI). Cambia el host/puerto si despliegas
# el backend en otra máquina o detrás de un proxy.
VITE_API_URL=http://localhost:8000
EOF
  echo "Generado: $FRONTEND_ENV"
fi

echo ""
echo "Configuración generada en modo '${MODE}'."
echo "Pendiente de rellenar manualmente: claves de LLM (GOOGLE_API_KEY / OPENROUTER_API_KEY / OPENAI_API_KEY según elijas), y SSO SAML si aplica."
