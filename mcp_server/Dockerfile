# Imagen del MCP remoto (REG.4).
#
# Proceso pequeño y sin estado: habla HTTP con la API y nada más. No lleva el venv del servidor
# ni cliente de base de datos, porque el paquete no importa `server.app` —hay un test que lo
# comprueba— y eso es lo que le permite ser esta imagen y no la del servidor entera.
#
# El transporte y el modelo de autenticación están en `http_server.py`: streamable HTTP, sin
# sesión, y el PAT lo presenta cada cliente en su petición. Aquí no se configura ningún token.
# **3.13, la misma que la imagen del servidor.** Estuvo en 3.12 sin que nadie lo decidiera:
# la aplicación se movió a la 3.13 y esta se quedó. El manifiesto dice `>=3.11`, así que la
# 3.13 lo cumple y **no se aprieta la declaración** — apretar la del servidor a
# `>=3.13,<3.14` fue una decisión medida, por cómo Dependabot resuelve sus *splits*, y el
# trabajo de este proyecto pasa hoy.
#
# Comprobado construyendo y arrancando: Python 3.13.15, y `/mcp` responde **421** igual que
# con la 3.12 —el guardián de host, o sea la aplicación en pie—. No es un cambio a ciegas
# porque el job `imagen` de CI **construye esta imagen y no la arranca**.
FROM python:3.14-slim

WORKDIR /srv/mcp

COPY pyproject.toml uv.lock ./
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
RUN pip install --no-cache-dir uv && uv sync --locked --no-dev

COPY config.py api_client.py errors.py resources.py server.py http_server.py ./
COPY tools/ ./tools/

# El venv ya está sincronizado, así que uvicorn se invoca directamente desde él y nunca por
# `uv run`: `uv run` vuelve a resolver el proyecto en cada arranque, lo que necesita red y un
# $HOME escribible — mismo motivo que en el Dockerfile de la raíz y en el del sandbox.
ENV PATH="/srv/mcp/.venv/bin:$PATH"

# Sin usuario propio ni ficheros que escribir: nada aquí necesita root.
USER 65534:65534
EXPOSE 8080

# `--factory` porque `app` es una función: la aplicación se construye al arrancar, cuando las
# variables de entorno ya están, y no al importar el módulo.
# La sonda de salud (issue #91). Sin ella el contenedor salía `Up` sin estado de salud, que es
# indistinguible de sano: si se quedara sirviendo errores, nadie se enteraría hasta intentar
# usarlo.
#
# **La respuesta sana del MCP no es un 200**, y por eso el conjunto se escribe entero: un
# `GET /mcp` sin la cabecera del transporte devuelve **406**, y desde un host que no esté en
# `GOVGENAI_MCP_ALLOWED_HOSTS` —como `127.0.0.1` aquí dentro— devuelve **421**. Una sonda que
# esperase 200 se pondría roja con el servicio en pie.
#
# **Y se acota a esos tres.** La primera versión aceptaba cualquier código —`0 if status else 1`,
# y todo entero no nulo es verdadero—, así que un MCP que arrancara y respondiera 500 por un
# fallo de la aplicación seguía `healthy` y no disparaba la reversión que esto venía a cubrir.
# El razonamiento «cualquier respuesta significa que el proceso está en pie» es cierto del
# proceso y falso del servicio, y lo que importa es si sirve. Lo señaló la revisión de la PR #110.
#
# Si una versión futura del transporte contesta otro código a esta petición, esto se pondrá rojo:
# es lo que se quiere: que el conjunto se revise a conciencia y no que se ensanche solo.
#
# En Python y no con `curl` porque esta imagen no lo lleva. `request()` levanta
# `ConnectionRefusedError` si no hay nadie escuchando, que sigue siendo «muerto».
#
# `--factory` importa aquí: la aplicación se construye **al arrancar**, no al importar, así que
# un fallo de construcción sólo se ve con el proceso en marcha. Por eso la sonda vale y una
# comprobación de la imagen construida no.
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import http.client,sys; c=http.client.HTTPConnection('127.0.0.1',8080,timeout=5); c.request('GET','/mcp'); sys.exit(0 if c.getresponse().status in (200,406,421) else 1)"

CMD ["uvicorn", "http_server:app", "--factory", "--host", "0.0.0.0", "--port", "8080"]
