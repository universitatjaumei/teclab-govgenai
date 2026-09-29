# **3.13, la misma que la imagen del servidor.** Estuvo en 3.12 sin que nadie lo decidiera.
# El manifiesto dice `>=3.12`, así que la 3.13 lo cumple y **no se aprieta la declaración**.
#
# Comprobado construyendo y arrancando: Python 3.13.15, `/health` a **200** igual que con la
# 3.12, y las bibliotecas pesadas en la misma versión (`pandas` 3.0.6, `numpy` 2.5.3,
# `matplotlib` 3.11.2). Entonces hizo falta comprobarlo a mano porque el job `imagen` de CI
# construía esta imagen sin arrancarla; **desde la issue #91 sí la arranca** y espera un
# `/health` a 200, así que esa comprobación manual ya no hace falta.
FROM python:3.13-slim

# Dependencias del sistema mínimas (libgomp1 lo necesita numpy/pandas en algunos entornos).
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Usuario no-root con UID 65534 (nobody). El `|| true` cubre el caso de que la
# distribución base ya tenga ese UID asignado a otro usuario.
RUN useradd --uid 65534 --no-create-home --shell /usr/sbin/nologin sandboxuser \
    || true

WORKDIR /srv/sandbox

COPY pyproject.toml ./
COPY uv.lock* ./
# `--locked` y no `--frozen`. **Los dos usan el lock sin volver a resolver**, que es lo que se
# quiere aquí —una imagen construida meses después no puede traer versiones que nadie probó—,
# pero sólo `--locked` comprueba además que el lock **cuadre con su manifiesto**.
#
# Medido, porque la diferencia no se ve leyendo los nombres: con `--frozen` y una dependencia
# añadida al `pyproject.toml` sin relockear, la construcción **pasa en verde y esa dependencia
# no llega a la imagen**. Comprobado añadiendo `tabulate>=0.9` al manifiesto del sandbox:
# `--frozen` construyó y `find_spec('tabulate')` daba `None`; `--locked` rompe con
# «error: The lockfile at `uv.lock` needs to be updated, but `--locked` was provided».
#
# Es además el flag que ya usaban CI y el despliegue, así que las imágenes comprobaban menos
# que quien las construye.
#
# **Aquí había además una reserva —`|| (pip install uv && uv sync --no-dev)`— y se retiró.** Si
# el primer `uv sync` fallaba, la segunda rama **volvía a resolver** y la imagen salía con
# versiones que nadie había fijado ni probado: justo lo que el lock existe para impedir, y con la
# construcción en verde. Comprobado con `--no-cache` y sin reserva que el primero se vale solo.
RUN pip install --no-cache-dir uv && uv sync --locked --no-dev

COPY sandbox/ ./sandbox/

# /tmp/sandbox lo monta el orquestador (SBX.4) como tmpfs; aquí solo lo
# creamos por si el contenedor se ejecuta sin el tmpfs en local.
RUN mkdir -p /tmp/sandbox && chown 65534:65534 /tmp/sandbox

# El venv ya quedó sincronizado por `uv sync` en el paso anterior (con red
# disponible en build-time). El CMD debe invocar uvicorn DIRECTAMENTE desde
# ese venv, nunca vía `uv run`: `uv run` re-resuelve/reconstruye el proyecto
# local en cada arranque (necesita red para el build backend), y este
# contenedor corre sin red (sandbox-net internal) y sin $HOME escribible
# (USER 65534, root fs read_only) — mismo patrón que el Dockerfile raíz.
ENV PATH="/srv/sandbox/.venv/bin:$PATH"

USER 65534:65534
EXPOSE 5000

# La sonda de salud (issue #91). El compose ya declaraba una para este servicio; ponerla también
# en el `Dockerfile` hace que valga para cualquiera que despliegue esto con otro orquestador,
# que es la misma razón por la que `app` y `frontend` la traen en el suyo.
#
# Aquí sí se espera un 200: `/health` del sandbox responde 200 y no tiene guardián de host, al
# contrario que el MCP. En Python porque esta imagen corre como 65534 con el sistema de ficheros
# en sólo lectura y sin red, y no conviene añadirle `curl` para esto.
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD python -c "import http.client,sys; c=http.client.HTTPConnection('127.0.0.1',5000,timeout=5); c.request('GET','/health'); sys.exit(0 if c.getresponse().status == 200 else 1)"

CMD ["uvicorn", "sandbox.main:app", "--host", "0.0.0.0", "--port", "5000"]
