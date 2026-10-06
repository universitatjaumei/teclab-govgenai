# Instalación

> **Clase: referencia viva.** Escrita el 2026-09-19. De clonar el repositorio a un sistema que
> responde. Dos caminos —instalar para usar, o montar el entorno para desarrollar—, la elección de
> **modelos locales o por API**, y las trampas que cuestan una tarde si nadie las dice.
>
> Lo que viene después de instalar —crear la organización, el primer asistente, un informe— está
> en [`GUIA_DE_USO.md`](GUIA_DE_USO.md). El despliegue en una VM de GCP, paso a paso, en
> [`DESPLIEGUE_PROTOTIPO_GCP.md`](DESPLIEGUE_PROTOTIPO_GCP.md).

---

## 1. Qué hace falta antes de empezar

| | Para qué |
|---|---|
| **Docker** con Compose v2 | La base de datos, el almacenamiento y el sandbox de scripts |
| **[uv](https://docs.astral.sh/uv/)** | Gestiona los paquetes de Python. **No uses `pip`** |
| **Node 20 o superior** | El frontend (CI y el despliegue usan 24) |
| **Git Bash**, si estás en Windows | La suite de tests y los guiones `.sh` lo necesitan |

**No hay proyecto Python en la raíz.** Los proyectos uv son cuatro —`server/`, `shared/`,
`mcp_server/` y `services/script_sandbox/`— y cada comando se lanza desde su directorio o con
`--project`. Ejecutar `uv sync` en la raíz no instala nada útil.

---

## 2. Camino A — instalar para usar

Es el camino de quien va a levantar la plataforma, no a desarrollarla. Levanta el conjunto
completo en contenedores.

```bash
git clone <repositorio> && cd teclab-govgenai
scripts/generate_env.sh          # genera .env, server/.env y frontend/.env con secretos nuevos
scripts/setup.sh                 # instalación de primera vez
```

**`generate_env.sh`** escribe los tres ficheros de configuración con secretos aleatorios y **nunca
pisa uno que ya exista** salvo con `--force`. Tiene dos modos: `--mode local` (por omisión) deja
todo funcionando sin servicios de pago —Ollama para el modelo y MinIO para el almacenamiento—, y
`--mode cloud` deja preparadas y comentadas las opciones de Vertex AI y GCS.

**`setup.sh`** hace cinco pasos: comprueba requisitos (Docker, y los puertos **80, 443 y 5432**
libres), pide las credenciales del superadministrador, levanta `docker-compose.prod.yml`, aplica
las migraciones y siembra. **Es idempotente de extremo a extremo**: ejecutarlo dos veces no
duplica nada ni rehashea la contraseña que ya pusiste.

Opciones que conviene conocer:

| Opción | Para qué |
|---|---|
| `--dry-run` | Enseña el plan sin tocar nada. Las comprobaciones de requisitos sí se hacen |
| `--non-interactive` | No pregunta: toma `SUPERADMIN_EMAIL`, `SUPERADMIN_PASSWORD` y `SUPERADMIN_NAME` del entorno |
| `--skip-stack` | No levanta Compose; sirve para repetir sólo el sembrado |
| `--skip-checks` | Omite la verificación de Docker y puertos |

Al terminar tienes una organización de ejemplo, un chatbot de ejemplo con sus prompts de
bienvenida en castellano, catalán e inglés, y tu cuenta de superadministrador. El ejemplo sirve
para comprobar que todo responde; **no sirve como punto de partida de nada real**.

---

## 3. Camino B — montar el entorno de desarrollo

Aquí los contenedores son sólo la infraestructura y la aplicación corre en tu máquina, que es lo
que permite recargar en caliente y depurar.

```bash
scripts/generate_env.sh
docker compose up -d postgres            # el servicio se llama `postgres`, no `db`
cd server
uv sync --extra shared                   # ver §4 antes de decidir si añades --extra local-models
uv run alembic upgrade head
cd ..                                    # el backend arranca DESDE LA RAÍZ
uv run --project server uvicorn server.app.main:app --port 8000
```

> **Por qué desde la raíz y con `server.app.main:app`.** La aplicación importa `server.*` en
> absoluto y necesita la raíz en el camino de importación. Ejecutado desde `server/` —como decía
> este documento hasta el 2026-09-23— falla con `ModuleNotFoundError: No module named 'server'`,
> que es un error sin pista de que la causa es el directorio.
>
> Es el mismo módulo y el mismo directorio que usa la imagen de producción, y eso se comprueba:
> `test_issue92_el_comando_de_arranque_documentado_funciona.py` cruza este comando con el `CMD`
> del `Dockerfile`, para que no puedan volver a separarse.

Y el frontend, en otra terminal:

```bash
cd frontend
npm install
npm run generate:api                     # OBLIGATORIO en un clon nuevo, ver abajo
npm run dev                              # http://localhost:5173
```

**`npm run generate:api` no es opcional la primera vez.** El cliente TypeScript de la API lo
genera Orval desde `openapi.json` y **no viaja en el repositorio** —está en `.gitignore` a
propósito: es código generado, no código que se edita—. Sin ese paso, `npm run dev` falla con
veinte «Cannot find module `@/shared/api/generated/...`», que no es un problema del frontend sino
la arquitectura *contract-first* diciendo que el contrato se genera. El primer despliegue en GCP
murió exactamente ahí.

Necesita el `openapi.json`, que lo exporta el backend:

```bash
cd server;   uv run python export_openapi.py
cd frontend; npm run generate:api
```

Hay que repetirlo **cada vez que cambie la API**. Un trabajo de CI se pone rojo si el cliente
generado no cuadra con el contrato.

En Windows, `arranque.bat` levanta el backend y el frontend, pero **no genera el cliente**: eso se
hace una vez, a mano.

`docker-compose.yml` levanta además `minio`, `clickhouse`, `redis`, `langfuse` y `script-sandbox`
si los necesitas; `postgres` es el único imprescindible para arrancar.

---

## 4. La decisión que hay que tomar: modelos locales o por API

La plataforma necesita **embeddings** para buscar en el corpus y, opcionalmente, un **reranker**
para reordenar lo recuperado. Puede hacer las dos cosas de dos maneras, y la elección tiene
consecuencias de tamaño, de coste y de protección de datos:

| | Modelos locales | Por API |
|---|---|---|
| Qué instala | `torch`, `torchvision`, `sentence-transformers` (BGE-M3) | Nada: adaptadores HTTP |
| Dónde se procesa el texto | En tu máquina | En el proveedor |
| Imagen del servidor | **3,11 GB** | **1,84 GB** |
| Arranque | Minutos la primera vez: carga los modelos | Inmediato |

**La diferencia medida es +1,27 GB**, y es el número con el que dimensionar la máquina. Los dos
caminos trabajan a **1024 dimensiones** a propósito, que es el único valor que sirve a la vez a
BGE-M3 en local y a Google en la nube: cambiar de proveedor no obliga a migrar la columna de
vectores ni a reconstruir el índice.

**Cuál elegir.** Si el requisito regulatorio es que el texto no salga de la institución, locales.
Si no, por API sale más barato de operar. El modo *edge* sigue necesitando los locales.

### 4.1 El interruptor (APER.18)

**Por omisión no se instalan.** La imagen hace `uv sync --frozen --no-dev --no-editable`, sin
extras, y hasta APER.18 tener modelos locales exigía **editar el `Dockerfile`**. Ahora es un
argumento de construcción:

```bash
# Construir la imagen del servidor con la pila local
docker build --build-arg EXTRAS_APP="--extra local-models" .

# Con el Compose de producción, sólo el servicio `app` lo lleva
docker compose -f docker-compose.prod.yml build \
  --build-arg EXTRAS_APP="--extra local-models" app
```

En el despliegue automatizado **no se toca el código**: sale de la variable de repositorio
`GOVGENAI_EXTRAS_APP` —vacía significa despliegue estándar; `local-models`, con la pila local—.
La elección es de cada institución, así que vive en su configuración.

**Y la variante va en la etiqueta de la imagen**, que no es cosmético: el despliegue no
reconstruye si la etiqueta ya está publicada, y la etiqueta es el SHA del commit. Sin el sufijo
`-local-models`, activar el interruptor y redesplegar el mismo commit se llevaría la imagen
anterior —la que no lleva modelos— **y sin decir nada**.

En **desarrollo**, el interruptor equivalente es el extra de uv:

```bash
cd server
uv sync --extra local-models --extra shared
```

Sin él, el primer uso de embeddings falla con un mensaje que dice exactamente eso. **Con él, el
primer arranque tarda varios minutos** cargando los modelos: hasta que el servidor no escriba
`Application startup complete`, no responde.

### 4.2 Elegir el proveedor sin reconstruir nada

Cuál se usa **no lo decide la imagen, lo decide la configuración**: una fila de `hub_llm_configs`
con propósito `embedding`. Sin ninguna fila, el local. Misma imagen, distinta fila.

**No hay reserva silenciosa**: si el proveedor configurado no se sabe hablar, el error es
explícito. Degradar a local sin avisar dejaría medio corpus en un espacio vectorial y medio en
otro, y el coseno entre ambos no da error: da respuestas malas. Por la misma razón, cambiar de
modelo de embedding con el corpus ya indexado obliga a reindexar **a propósito**, y un guardarraíl
lo impide mientras no se haga.

---

## 5. Las variables que importan

`.env.example` documenta cada una. Las que hay que mirar sí o sí:

| Variable | Qué decide |
|---|---|
| `DATABASE_URL` · `DATABASE_URL_SYNC` | La base de datos (async y para Alembic). **No hay host ni contraseña en el código** |
| `ENVIRONMENT` | `development` o `production`. En `development` se siembra la cuenta de desarrollo; en producción **no existe** |
| `JWT_SECRET_KEY` | Las sesiones. Cámbiala, y rotarla cierra todas las sesiones abiertas |
| `STORAGE_BACKEND` · `STORAGE_BUCKET` | Dónde van los ficheros: `file`, `s3`/MinIO o `gcs`. Nunca se escribe con `open()` |
| `DEPLOY_MODE` | `cloud`, `edge` o `all` (por omisión). Decide qué routers se registran |
| `LOCAL_USER_LOGIN_ENABLED` | Contraseña local mientras el SSO institucional no esté conectado |
| `SAML_*` | El SSO, cuando lo haya |
| `SOURCE_URL` | El enlace al código fuente que exige el §13 de la AGPL si has modificado el programa. **Apunta a tu versión** —tu fork, en el commit desplegado—, no al repositorio principal. Lo sirve `GET /api/v1/instancia`, público y sin credencial; vacío significa «sin enlace». Hoy **ninguna interfaz lo enseña todavía** |
| `DEV_ADMIN_EMAIL` · `DEV_ADMIN_PASSWORD` | La cuenta que siembra el arranque en `development`. Sin ponerlas hay valores por omisión que **sólo valen en local** |
| `TRUSTED_PROXY_HOPS` | Cuántos proxies de confianza hay delante. Suponerlo es como se falsifica una IP de origen |
| `AGENTES_EXTENSION_IDS` | Los identificadores de la extensión del navegador de los agentes de unidad a los que se entrega el token de consulta, separados por comas. **Vacía, no se conecta ninguna.** El de la extensión del repositorio es fijo: `extension/README.md` |
| `INDICE_SIN_ACTUALIZAR_DIAS` | Días que puede pasar el guion del índice de un agente sin mandarlo antes de marcarlo como «índice sin actualizar» (3 por omisión). Avisa y no oculta: el agente se sigue ofreciendo. Una hoja subida a mano no caduca |

---

## 6. El esquema lo aplica Alembic, y sólo Alembic

**La aplicación no crea tablas al arrancar.** Si la base no está migrada, la primera consulta
falla con claridad, que es mejor que una tabla aparecida en silencio.

```bash
cd server
uv run alembic upgrade head      # aplicar
uv run alembic current           # comprobar en qué revisión estás
uv run alembic check             # los modelos y la cadena de migraciones cuadran
```

En el Compose de producción lo hace el servicio `migrate` antes de que arranque `app`.

---

## 7. Comprobar que ha salido bien

```bash
curl http://localhost:8000/health        # {"status": "ok"}
```

Y en el navegador: entra en `http://localhost:5173` (desarrollo) o en el puerto 80 (producción),
inicia sesión con la cuenta que creaste, y comprueba que aterrizas en un módulo. Si ves
«sin acceso», el rol está bien pero **falta la concesión de módulo** —§1 de
[`GUIA_DE_USO.md`](GUIA_DE_USO.md)—.

---

## 8. Trampas conocidas

- **El primer arranque con modelos locales tarda minutos.** No está colgado: está cargando BGE-M3.
  Hasta `Application startup complete`, no responde.
- **El servicio de Postgres se llama `postgres`, no `db`.**
- **En Windows, la suite se ejecuta desde Git Bash.** Desde PowerShell, `test_setup_script.py`
  invoca `bash`, que resuelve al lanzador de WSL y da diez rojos de entorno.
- **`&&` no existe en PowerShell.** Encadena con `;`.
- **El servidor de desarrollo y la suite de tests se pelean por la misma base.** Los tests crean
  bases desechables, pero conviene no tener las dos cosas trabajando a la vez sobre `govgenai`.
- **Si cambias dependencias, el lock va en el mismo commit.** CI instala con `uv sync --locked`, y
  comprobar con `uv sync` a secas no sirve: relockea y siempre pasa. Lo que dice la verdad es
  `uv lock --check`.
- **El puerto 8000 puede quedar ocupado** por un uvicorn anterior que no murió del todo.
- **«Cannot find module `@/shared/api/generated/…`» no se arregla borrando `node_modules`**: falta
  generar el cliente de la API (§3). Es lo primero que hay que descartar ante veinte errores de
  importación en el frontend.

---

## 9. Dónde seguir

| Si quieres | Lee |
|---|---|
| Empezar a usarla | [`GUIA_DE_USO.md`](GUIA_DE_USO.md) |
| Desplegar en una VM de GCP | [`DESPLIEGUE_PROTOTIPO_GCP.md`](DESPLIEGUE_PROTOTIPO_GCP.md) |
| Entender cómo está construida | [`Arquitectura.md`](Arquitectura.md) |
| Saber qué garantiza | [`ESPECIFICACIONES.md`](ESPECIFICACIONES.md) |
| Contribuir | [`../CONTRIBUTING.md`](../CONTRIBUTING.md) |
