# Stage 1: Builder — instala dependencias con uv
FROM python:3.14-slim AS builder

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# El paquete compartido debe copiarse antes de instalar server/
COPY shared/ ./shared/

# Copiar sólo los manifiestos para aprovechar caché Docker en cambios de código.
#
# `README.md` va aquí aunque no sea un manifiesto, y **quitarlo rompe la construcción entera**:
# desde PLG.1 `server/pyproject.toml` tiene `[build-system]` —sin él no hay entry points que
# descubrir— así que `uv sync` construye el wheel del proyecto, y hatchling lee `readme =
# "README.md"` y aborta con `OSError: Readme file does not exist` si no está en el contexto.
# Antes de PLG no había backend de construcción y el fichero no hacía falta.
COPY server/pyproject.toml server/uv.lock server/README.md ./server/

WORKDIR /app/server

# APER.18 — la pila de modelos locales se elige **al construir**, no editando este fichero.
#
# `local-models` (`torch`, `torchvision`, `sentence-transformers`) es lo que hace funcionar los
# embeddings BGE-M3 y el reranker **en la propia máquina**, sin que los datos salgan a una API.
# Se conserva porque es lo que permite que otra administración despliegue con modelos locales, y
# **no se instala por omisión** porque son cientos de megas y una VM mayor: el `pyproject`
# documenta 216 MB de `sentence-transformers` y 172 de `torch`, y que entre los tres se llevaban
# casi todo el tiempo de arranque.
#
# Vacío por omisión, o el despliegue estándar engordaría por un interruptor que nadie tocó. Para
# activarlo:
#
#     docker build --build-arg EXTRAS_APP="--extra local-models" .
#
# En el despliegue lo pone `deploy.yml` desde una variable del repositorio, así que la elección
# es de cada institución y no del código. **Y la variante va en la etiqueta de la imagen**: sin
# eso, activar el interruptor y redespliegar el mismo commit se llevaría la imagen anterior, sin
# modelos, y en silencio.
ARG EXTRAS_APP=""

# --no-editable convierte automatia-shared en paquete regular (no hace falta shared/ en runtime)
# **`--frozen` aquí, y `--locked` en las imágenes del MCP y del sandbox.** No es incoherencia:
# es que en esta imagen `--locked` **no puede funcionar**, y conviene que esté escrito para que
# nadie lo «arregle» por simetría.
#
# Los dos flags usan el lock sin volver a resolver, que es lo que se quiere —una imagen
# construida meses después no puede traer versiones que nadie probó—, y `--locked` comprueba
# además que el lock cuadre con su manifiesto. Pero para comprobarlo necesita **los metadatos de
# todos los miembros del workspace**, y uno de ellos es un paquete de pruebas
# (`tests/fixtures/paquete_perfil_demo`) que esta imagen **no copia a propósito**. Medido: con
# `--locked` la construcción muere en `error: Failed to generate package metadata for
# `govgenai-demo-perfil==0.1.0 @ editable+tests/fixtures/paquete_perfil_demo``.
#
# Lo que `--frozen` no da —avisar de que el lock no cuadra con el manifiesto— lo dan aquí CI y
# el despliegue, que instalan con `uv sync --locked`, y el job de cadena de suministro, que hace
# `uv export --locked` de los cuatro proyectos.
RUN uv sync --frozen --no-dev --no-editable ${EXTRAS_APP}


# Stage 2: Runtime — imagen mínima sin herramientas de build
FROM python:3.14-slim AS runtime

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --shell /bin/bash appuser

COPY --from=builder /app/server/.venv /app/server/.venv

# Código fuente del servidor
COPY server/app/ ./server/app/
COPY server/migrations/ ./server/migrations/
COPY server/alembic.ini ./server/alembic.ini

ENV PATH="/app/server/.venv/bin:$PATH"
ENV PYTHONPATH="/app"
ENV PYTHONUNBUFFERED=1

# APER.3 — el entorno se ancla aquí, y no se deja al valor por omisión del código.
#
# `core/config.py` y `database/seeds.py` leen los dos `os.getenv("ENVIRONMENT", "development")`,
# o sea que **un ENVIRONMENT ausente significa «sin protecciones»**: no corre ninguno de los
# cuatro gates de producción y se siembra `admin@example.local` con una contraseña escrita en el
# propio repositorio. Los dos composes y el job `imagen` de CI lo fijan, así que el despliegue de
# la UJI nunca estuvo afectado; el riesgo es de quien despliegue desde el repositorio público con
# un `docker run` y sólo `JWT_SECRET_KEY`.
#
# Se ancla en la imagen y no dándole la vuelta al defecto del código porque en el host —la
# suite, el desarrollo— `TESTING=1` y `SANDBOX_MODE=local` son correctos, y los gates los
# rechazan: invertirlo rompería todo eso para arreglar un caso que sólo ocurre aquí. Quien
# necesite la imagen en modo desarrollo lo sobrescribe al arrancarla, que es un acto explícito.
ENV ENVIRONMENT=production

# La versión del despliegue, estampada al construir. `deploy.yml` la pasa con `--build-arg`
# leyéndola del fichero `VERSION` de la raíz, que es la fuente única.
#
# El ARG tiene que volcarse a ENV: un ARG sólo vive durante la construcción, así que declararlo
# sin esta línea dejaría la imagen sin saber qué versión es, y el endpoint diría «desconocida».
# El defecto no es una versión plausible a propósito — si aparece en un informe de fallo, lo que
# hay que arreglar es el empaquetado y no el número.
ARG GOVGENAI_VERSION="0.0.0+desconocida"
ENV GOVGENAI_VERSION=${GOVGENAI_VERSION}

# hub_themes_router crea data/themes (ruta relativa a WORKDIR) al importarse;
# /app es de root hasta aquí, así que appuser necesita este directorio ya
# creado y con permisos antes de arrancar (si no, PermissionError en el import).
RUN mkdir -p /app/data && chown -R appuser:appuser /app/data

USER appuser

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

EXPOSE 8000

CMD ["uvicorn", "server.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
