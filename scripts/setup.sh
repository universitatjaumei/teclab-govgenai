#!/usr/bin/env bash
#
# setup.sh — instalación de primera vez de Gov Gen AI Platform (11.3).
#
# Automatiza: verificación de requisitos, arranque del stack, migraciones,
# creación del SuperAdmin y sembrado del chatbot de ejemplo, y resumen final.
#
# Es idempotente de extremo a extremo: la parte que toca datos vive en
# server/app/scripts/bootstrap.py, que busca cada entidad por su clave natural
# antes de crearla. Ejecutarlo dos veces no duplica nada.
#
# Compatible con bash 3.2 (el que trae macOS): sin arrays asociativos, sin
# lectura de ficheros en array y sin las expansiones de caja de bash 4.
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

COMPOSE_FILE="docker-compose.prod.yml"
# Sin 5432 (#269): el compose de producción no publica Postgres, así que exigirlo libre
# rechazaba máquinas que sí podían instalar.
PUERTOS_REQUERIDOS="80 443"

DRY_RUN=0
SKIP_CHECKS=0
SKIP_STACK=0
NON_INTERACTIVE=0

SUPERADMIN_EMAIL="${SUPERADMIN_EMAIL:-}"
SUPERADMIN_PASSWORD="${SUPERADMIN_PASSWORD:-}"
SUPERADMIN_NAME="${SUPERADMIN_NAME:-Superadministrador}"

# ---------------------------------------------------------------------------
# Utilidades (solo builtins: el script debe poder informar aunque el PATH esté
# incompleto, que es justo el síntoma de "Docker no instalado")
# ---------------------------------------------------------------------------

log()   { printf '%s\n' "$*"; }
paso()  { printf '\n==> %s\n' "$*"; }
error() { printf 'ERROR: %s\n' "$*" >&2; }

# En --dry-run se anuncia la acción en lugar de ejecutarla.
ejecutar() {
    if [ "${DRY_RUN}" -eq 1 ]; then
        printf '   [DRY-RUN] %s\n' "$*"
        return 0
    fi
    "$@"
}

uso() {
    printf '%s\n' \
"Uso: scripts/setup.sh [opciones]" \
"" \
"Instalación de primera vez: comprueba requisitos, levanta el stack, aplica las" \
"migraciones, crea el SuperAdmin y siembra un chatbot de ejemplo." \
"" \
"Opciones:" \
"  --non-interactive   No pregunta nada. Toma las credenciales del SuperAdmin de" \
"                      las variables SUPERADMIN_EMAIL, SUPERADMIN_PASSWORD y" \
"                      SUPERADMIN_NAME (opcional)." \
"  --dry-run           Muestra el plan sin ejecutar ninguna acción que modifique" \
"                      el sistema. Las comprobaciones de requisitos sí se hacen." \
"  --skip-checks       Omite la verificación de requisitos (Docker y puertos)." \
"  --skip-stack        No levanta docker compose; asume que los servicios ya" \
"                      están arriba. Útil para reejecutar solo el sembrado." \
"  --compose-file <f>  Fichero de Compose a usar (por defecto ${COMPOSE_FILE})." \
"  -h, --help          Muestra esta ayuda." \
"" \
"Es idempotente: ejecutarlo dos veces no duplica datos."
}

# ---------------------------------------------------------------------------
# Argumentos
# ---------------------------------------------------------------------------

while [ $# -gt 0 ]; do
    case "$1" in
        --non-interactive) NON_INTERACTIVE=1 ;;
        --dry-run)         DRY_RUN=1 ;;
        --skip-checks)     SKIP_CHECKS=1 ;;
        --skip-stack)      SKIP_STACK=1 ;;
        --compose-file)
            if [ $# -lt 2 ]; then error "--compose-file necesita un valor"; exit 2; fi
            COMPOSE_FILE="$2"; shift ;;
        -h|--help)         uso; exit 0 ;;
        *)
            error "opción desconocida: $1"
            printf '\n'
            uso
            exit 2 ;;
    esac
    shift
done

# ---------------------------------------------------------------------------
# 1. Requisitos del sistema
# ---------------------------------------------------------------------------

puerto_ocupado() {
    # /dev/tcp es una redirección de bash: no depende de nc, lsof ni ss, que no
    # están garantizados ni en Linux mínimo ni en macOS.
    ( exec 3<>"/dev/tcp/127.0.0.1/$1" ) >/dev/null 2>&1
}

verificar_requisitos() {
    paso "1/5 Verificando requisitos del sistema"

    if ! command -v docker >/dev/null 2>&1; then
        error "docker no está instalado o no está en el PATH."
        error "Instálalo desde https://docs.docker.com/get-docker/ y vuelve a ejecutar."
        exit 1
    fi
    log "   docker: encontrado"

    if ! docker compose version >/dev/null 2>&1; then
        error "'docker compose' no disponible (se necesita Compose v2)."
        exit 1
    fi
    log "   docker compose: disponible"

    if ! docker info >/dev/null 2>&1; then
        error "el demonio de Docker no responde. Arranca Docker Desktop o el servicio."
        exit 1
    fi
    log "   demonio de Docker: respondiendo"

    # Se comprueban todos los puertos antes de abortar, para no obligar al
    # usuario a descubrirlos de uno en uno.
    ocupados=""
    for puerto in ${PUERTOS_REQUERIDOS}; do
        if puerto_ocupado "${puerto}"; then
            log "   puerto ${puerto}: OCUPADO"
            ocupados="${ocupados} ${puerto}"
        else
            log "   puerto ${puerto}: libre"
        fi
    done

    if [ -n "${ocupados}" ]; then
        error "puertos ocupados:${ocupados}"
        error "Libéralos (o para el servicio que los usa) y reintenta."
        error "Si ya son de esta instalación, usa --skip-checks --skip-stack."
        exit 1
    fi
}

if [ "${SKIP_CHECKS}" -eq 1 ]; then
    paso "1/5 Verificación de requisitos omitida (--skip-checks)"
    log "   puertos que se habrían comprobado: ${PUERTOS_REQUERIDOS}"
    log "   docker: no comprobado"
else
    verificar_requisitos
fi

# ---------------------------------------------------------------------------
# 2. Credenciales del SuperAdmin (antes de tocar nada, para no dejar el stack
#    levantado a medias si el usuario cancela)
# ---------------------------------------------------------------------------

paso "2/5 Credenciales del SuperAdmin"

leer_o_abortar() {
    # `read` devuelve != 0 al llegar a EOF. Sin esta guarda, invocar el script
    # sin terminal (CI, tubería) dejaba el bucle girando para siempre.
    if ! read -r "$@"; then
        printf '\n'
        error "no hay entrada interactiva disponible."
        error "Usa --non-interactive con SUPERADMIN_EMAIL y SUPERADMIN_PASSWORD."
        exit 2
    fi
}

if [ "${NON_INTERACTIVE}" -eq 1 ]; then
    faltan=""
    [ -z "${SUPERADMIN_EMAIL}" ] && faltan="${faltan} SUPERADMIN_EMAIL"
    [ -z "${SUPERADMIN_PASSWORD}" ] && faltan="${faltan} SUPERADMIN_PASSWORD"
    if [ -n "${faltan}" ]; then
        error "--non-interactive requiere estas variables de entorno:${faltan}"
        exit 2
    fi
elif [ "${DRY_RUN}" -eq 1 ]; then
    # En un dry-run no se crea nada, así que no tiene sentido pedir credenciales.
    [ -z "${SUPERADMIN_EMAIL}" ] && SUPERADMIN_EMAIL="<se pedirá interactivamente>"
else
    while [ -z "${SUPERADMIN_EMAIL}" ]; do
        printf 'Correo del SuperAdmin: '
        leer_o_abortar SUPERADMIN_EMAIL
    done

    printf 'Nombre [%s]: ' "${SUPERADMIN_NAME}"
    leer_o_abortar nombre_leido
    [ -n "${nombre_leido}" ] && SUPERADMIN_NAME="${nombre_leido}"

    while [ -z "${SUPERADMIN_PASSWORD}" ]; do
        printf 'Contraseña: '
        leer_o_abortar -s SUPERADMIN_PASSWORD
        printf '\n'
        printf 'Repite la contraseña: '
        leer_o_abortar -s confirmacion
        printf '\n'
        if [ "${SUPERADMIN_PASSWORD}" != "${confirmacion}" ]; then
            error "las contraseñas no coinciden"
            SUPERADMIN_PASSWORD=""
        fi
    done
fi

# La contraseña no se imprime nunca, ni siquiera enmascarada.
log "   correo: ${SUPERADMIN_EMAIL}"
log "   nombre: ${SUPERADMIN_NAME}"

# ---------------------------------------------------------------------------
# 3. Stack
# ---------------------------------------------------------------------------

if [ "${SKIP_STACK}" -eq 1 ]; then
    paso "3/5 Arranque del stack omitido (--skip-stack)"
else
    paso "3/5 Levantando el stack (${COMPOSE_FILE})"
    ejecutar docker compose -f "${ROOT_DIR}/${COMPOSE_FILE}" up -d
fi

# ---------------------------------------------------------------------------
# 4. Migraciones (alembic) y sembrado idempotente (bootstrap)
# ---------------------------------------------------------------------------

paso "4/5 Migraciones de base de datos (alembic) y sembrado"

# La contraseña viaja por el entorno del proceso hijo, nunca por la línea de
# comandos: `ps` la dejaría visible para cualquier usuario de la máquina.
export SUPERADMIN_PASSWORD

if [ "${SKIP_STACK}" -eq 1 ]; then
    # Sin stack, se asume un entorno Python ya preparado contra la BD del .env.
    # alembic.ini resuelve `script_location` relativo al directorio de trabajo,
    # así que hay que invocarlo desde server/ y no desde la raíz.
    if [ "${DRY_RUN}" -eq 1 ]; then
        log "   [DRY-RUN] (cd server && python -m alembic upgrade head)"
    else
        ( cd "${ROOT_DIR}/server" && python -m alembic upgrade head )
    fi
    ejecutar python -m server.app.scripts.bootstrap \
        --superadmin-email "${SUPERADMIN_EMAIL}" \
        --superadmin-name "${SUPERADMIN_NAME}"
else
    # El servicio `migrate` del compose ya ejecuta `alembic upgrade head`; el
    # `up -d` anterior espera a que complete (service_completed_successfully).
    log "   alembic: aplicado por el servicio 'migrate' del compose"
    # `exec` no hereda el entorno del host: sin -e, la contraseña no llegaría
    # nunca al contenedor y el sembrado abortaría por argumento obligatorio.
    ejecutar docker compose -f "${ROOT_DIR}/${COMPOSE_FILE}" exec -T \
        -e SUPERADMIN_PASSWORD \
        app \
        python -m server.app.scripts.bootstrap \
        --superadmin-email "${SUPERADMIN_EMAIL}" \
        --superadmin-name "${SUPERADMIN_NAME}"
fi

# ---------------------------------------------------------------------------
# 5. Resumen
# ---------------------------------------------------------------------------

paso "5/5 Instalación completada"
printf '%s\n' \
"" \
"  Frontend .................. http://localhost/" \
"  Panel de administración ... http://localhost/hub" \
"  API (OpenAPI) ............. http://localhost:8000/docs" \
"" \
"  Accede con el correo del SuperAdmin: ${SUPERADMIN_EMAIL}" \
"" \
"  Se ha creado un 'Chatbot de Ejemplo' con prompts de bienvenida en" \
"  castellano, catalán e inglés. Puedes editarlo o borrarlo desde el panel." \
""

if [ "${DRY_RUN}" -eq 1 ]; then
    log "DRY-RUN: no se ha ejecutado ninguna acción. Repite sin --dry-run para instalar."
fi
