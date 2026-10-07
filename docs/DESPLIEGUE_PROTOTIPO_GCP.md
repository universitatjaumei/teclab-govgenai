# Despliegue del prototipo en GCP — sitio de normativa + asistente público

> **Escrito el 2026-08-16.** Alcance: un **prototipo** para que un grupo de personas lo
> pruebe. No sustituye al bloque Deploy de `planificacion/Plan_TDD_Fase1.md`
> (D.0–D.6), que es el despliegue en condiciones; esto es lo mínimo para que se pueda usar.
>
> **Ya tiene dominio propio (2026-09-02).** Decía «sin dominio propio» y desde el bloque DOM
> `normativa.uji.es` sirve la portada, el cercador, las fichas, la API y el panel. El reparto
> completo de nombres y rutas está en **3.sexies**, que es la sección a leer antes de tocar el
> proxy.
>
> **De qué repositorio se despliega (2026-08-21).** De este, el principal. La gobernanza del
> proyecto prevé que cada organización despliegue desde su propio fork (ver `CONTRIBUTING.md`),
> pero el fork de la universidad no existe todavía y crearlo para una demostración sería poner el
> carro delante: primero se valora si la cosa tiene interés institucional, y entonces se hace el
> fork y se planifica el despliegue desde ahí. Esta nota deja de aplicarse en ese momento.

---

## Los marcadores: qué valor va en cada uno y de dónde sale

Este documento usa marcadores en vez de los valores de la instalación que lo originó. **No es por
secreto** —ninguno es una credencial; lo que autoriza es IAM y la federación de identidad— sino
porque un procedimiento con los valores de otra casa dentro obliga a adivinar qué sustituir, y
porque un ejemplo que parece real se acaba copiando tal cual.

| Marcador | Qué es | De dónde sale |
|---|---|---|
| `<PROYECTO_GCP>` | Id del proyecto de GCP | Lo eliges al crear el proyecto. `gcloud config get-value project` |
| `<NUMERO_DE_PROYECTO>` | Número del proyecto, distinto del id | `gcloud projects describe <PROYECTO_GCP> --format='value(projectNumber)'` |
| `<REGION>` | Región de Cloud SQL, la VM y Artifact Registry | Tu elección. Aquí se usó Madrid (`europe-southwest1`) porque el texto no sale de España |
| `<INSTANCIA_SQL>` | Nombre de la instancia de Cloud SQL | Lo eliges al crearla (§3.bis) |
| `<VM>` | Nombre de la máquina | Lo eliges al crearla (D.4-VM) |
| `<BUCKET_CORPUS>` | *Bucket* del sitio estático del corpus | Lo eliges. Va en la variable `CORPUS_BUCKET` |
| `<BUCKET_DOCS>` | *Bucket* de documentos de la aplicación | Lo eliges. Va en `STORAGE_BUCKET` |
| `<HOST>` | Nombre por el que responde el servicio | Tu dominio, o el provisional derivado de la IP mientras no lo haya |
| `<ORG>/<REPOSITORIO>` | El repositorio de GitHub desde el que se despliega | El tuyo. Aparece en **los dos** anclajes de la identidad federada |

**Ninguno de estos valores va en el código.** Van en variables del repositorio de GitHub
(`gh variable set`), de donde el *workflow* escribe el fichero de entorno de la máquina en cada
despliegue. Ésa es la razón por la que el mismo código sirve a cualquier organización.

---

## Son dos cosas, y conviene no mezclarlas

| | Qué es | Dónde va | Qué necesita |
|---|---|---|---|
| **El sitio** | 271 páginas de norma + buscador + portada + PDF. Estático puro | Bucket de GCS con acceso público | Nada: ni servidor, ni base de datos |
| **El asistente** | API, grafo, corpus vectorial | VM con `docker-compose.prod.yml` | Cloud SQL, GCS, credenciales de Vertex |

El sitio funciona **sin** el asistente: es la publicación de la normativa y vale por sí sola.
El asistente sin el sitio también funciona, pero cita PDF en vez de artículos. Se despliegan
por separado y se conectan con tres variables.

---

## 1. El sitio

Se genera en el proyecto del corpus, no aquí:

```
cd Descarregar_pdf/normativa_propia/publicacio_transparencia_2026-07
python passa_el_pipeline.py --aplica
```

Antes de generar, las variables del asistente. Sin `ASSISTENT_CHATBOT` el sitio sale **sin
widget**, que es lo correcto si todavía no hay API desplegada:

```
ASSISTENT_API=https://<host-de-la-api>/api/v1
ASSISTENT_CHATBOT=<uuid del chatbot público>
ASSISTENT_CLAU=<credencial de sitio emitida para ESTE sitio>
```

Y hay que copiar el bundle del widget a la raíz del sitio:

```
cd frontend && npm run build:widget
cp dist/widget/widget.iife.js <sitio>/widget.iife.js
```

Lo que se sube al bucket: `index.html`, `cercador.html`, `html/`, `pdf/`, `img/` y
`widget.iife.js`. **No** se sube nada de `generat/`, que es material de ingesta.

⚠️ **Emite una credencial de sitio nueva para el bucket.** La que uses en local acaba dentro
del HTML generado; si subes esas páginas tal cual, subes la credencial de pruebas. Emítela
en el panel del chatbot, genera el sitio con ella, y revoca la de local.

---

## 2. El asistente

Lo que dice el bloque Deploy (D.4-VM), más lo que ha aparecido en el piloto:

| Variable | Valor | Por qué |
|---|---|---|
| `GOOGLE_CLOUD_PROJECT` | `<PROYECTO_GCP>` | Vertex. Ya verificado |
| `GOOGLE_CLOUD_LOCATION` | `europe-southwest1` | Madrid: el texto no sale de España |
| `CORPUS_SITE_BASE_URL` | `https://normativa.uji.es` | Sin esto las citas van al PDF. **Desde DOM.3 es el dominio y no la URL del bucket**: el bucket lo sigue sirviendo, pero por detrás del proxy |
| `CORS_ALLOWED_ORIGINS` | el origen del bucket **y** el del dominio, separados por coma | **Sin esto el widget no puede hablar con la API**: en producción la política es cerrada y un origen que falta se traduce en un preflight rechazado, no en un error visible. Los dos, y es aditivo a propósito: mientras la URL del bucket siga siendo pública, las páginas servidas desde ahí son de otro origen |
| `CORPUS_BUCKET` | `<BUCKET_CORPUS>` | El bucket al que el proxy manda todo lo que no es API ni panel (DOM.1). Lo lee **Caddy**, no la aplicación. Vacío compone `https://.storage.googleapis.com` y rompe portada, cercadores y fichas a la vez, así que el compose lo exige con `:?` |
| `ENVIRONMENT` | `production` | Cierra el sembrado de desarrollo (SEC.8.0) y la documentación de la API (SEC.7) |
| `AGENTES_EXTENSION_IDS` | `pgcofokabefjfmadgmeiddhfkbkebnhk` | Los ID de la extensión de los agentes de unidad, separados por comas, a los que se entrega el token de consulta (#176). **Vacía, no se conecta ninguna**. El ID es fijo porque el manifiesto lleva la clave pública (`extension/README.md`) |
| `INDICE_SIN_ACTUALIZAR_DIAS` | `3` por omisión; vacía o ilegible, también | Días sin que el guion mande el índice de un agente antes de marcarlo como «índice sin actualizar» (#174). Avisa, no oculta |
| `SAML_ORGANIZACION_ID` | el id de la organización de la institución | **La organización en la que queda quien entra con la cuenta institucional**, por Google o por SAML: el alta automática es la misma, y el nombre dice SAML por historia. Se vuelve a poner en cada entrada, así que asignarla a mano no sirve. **Vacía, la persona entra sin organización** y no ve nada acotado por organización —el catálogo de agentes le dice que no hay ninguno—. Con `GOOGLE_OAUTH_ALLOWED_DOMAIN=uji.es`, todo el que entra es de la UJI y queda en ella. Variable del repositorio, no secreto |

Credenciales de Vertex en la VM: cuenta de servicio con el rol de usuario de Vertex AI, no
una clave de API. En local se resolvió con ADC; en la VM lo aporta la propia máquina.

**El corpus se carga allí con la misma orden que aquí**, contra la BD de Cloud SQL:

```
uv run python -m server.app.modules.agents_hub.ingestion.corpus.load \
    --dir <corpus>/generat/ingesta/normatiu --chatbot-id <uuid> --dry-run
```

Son ~23.300 fragmentos y ~95 peticiones a Vertex para el asistente público. El vocabulario
va antes, o la carga aborta.

---

## 3. Orden

1. Cloud SQL con pgvector, y `alembic upgrade head`.
2. Vocabulario (ámbitos y después submaterias).
3. Chatbot público creado, con su configuración y **su cuota por IP** —ahora se puede fijar
   desde el panel, ya no hace falta SQL—.
4. Corpus cargado y comprobado con una consulta real.
5. Credencial de sitio emitida.
6. Sitio generado con esa credencial y subido al bucket.
7. `CORPUS_SITE_BASE_URL` al dominio, `CORS_ALLOWED_ORIGINS` con los dos orígenes y
   `CORPUS_BUCKET` con el nombre del bucket, y reinicio. **No son ficheros del repositorio**:
   son variables del repositorio de GitHub (`gh variable set`), de donde `deploy.yml` escribe
   `/opt/govgenai/.env.despliegue` en cada despliegue.
8. Comprobación de extremo a extremo: una pregunta cuya respuesta cite un artículo, y que el
   enlace de la cita abra la página en ese artículo.

---

---

## 3.bis Aprovisionado el 2026-08-31 (D.0, D.2 y D.3)

Lo que ya está hecho en `<PROYECTO_GCP>`, para no repetirlo ni adivinarlo:

| Qué | Cómo quedó |
|---|---|
| Servicios de GCP | **14 habilitados y comprobados** con `scripts/gcp_enable_services.sh` (D.0). Idempotente: se relanza sin miedo |
| Cloud SQL | Instancia **`<INSTANCIA_SQL>`**: POSTGRES_16, `db-g1-small`, edición **ENTERPRISE**, `europe-southwest1`, disco con crecimiento automático, copias a las 03:00 y **PITR activado**. Nombre de conexión `<PROYECTO_GCP>:<REGION>:<INSTANCIA_SQL>` |
| Base y usuario | BD **`govgenai`** y usuario **`govgenai`**, con la contraseña en Secret Manager (nunca en un fichero) |
| `pgvector` | **No hace falta paso manual**: la primera migración ejecuta `CREATE EXTENSION IF NOT EXISTS vector` (`a1b2c3d4e5f6_hub_schema.py:22`) y el usuario creado por la API de Cloud SQL tiene permiso |
| Secretos | Seis, inventariados en `scripts/lib/secretos.tsv` y creados con `scripts/gcp_create_secrets.sh`. Cinco con valor; **falta `govgenai-google-api-key`**, que lo aporta una persona |

**La edición importa**: el proyecto crea por defecto en `ENTERPRISE_PLUS`, que **rechaza** los
tiers de núcleo compartido (`db-g1-small`). Hay que pasar `--edition=ENTERPRISE` o el comando
falla con «Invalid Tier ... for (ENTERPRISE_PLUS) Edition».

**Cómo llegan los secretos al contenedor.** En el despliegue gestionado los inyectaba la
plataforma; en una VM lo hace `scripts/vm_fetch_secrets.sh`, que escribe
`/opt/govgenai/.env.runtime` con permisos 600 leyendo Secret Manager, y se niega a escribir un
fichero a medias si algún secreto falta. Rotar una credencial es cambiar el secreto y
reiniciar: no se entra en la máquina a editar nada.

> **Cuidado con el retorno de carro, que costó dos diagnósticos.** Ejecutando estos guiones
> **desde Windows**, `openssl` y algunas salidas de `gcloud` terminan en CRLF y `$(...)` sólo se
> come el `\n`: el `\r` se queda dentro del valor. Un `\r` en una contraseña hace que
> `gcloud sql users create` falle con «batch file arguments are invalid», y en un fichero de
> entorno se lleva la línea entera. Los dos guiones lo limpian ahora en un solo sitio. Y para
> comprobar un secreto, **`od -c` sobre un fichero**, no una comparación en el intérprete: la
> propia captura puede añadir el CR que estás buscando.

---

## 3.ter El nombre de la API, que sin dominio sigue haciendo falta

El sitio no necesita dominio —el bucket sirve por HTTPS con el de Google—, pero **la API sí
necesita un nombre**, y esto no es una preferencia:

- Las páginas del bucket se sirven por **HTTPS**, y ahí `ASSISTENT_API` tiene que ser `https://`.
  Una llamada a `http://IP` la bloquea el navegador por contenido mixto, sin error visible.
- Y `https://IP` **no puede tener certificado válido**: Let's Encrypt no emite para direcciones
  IP desnudas.

**Decisión del usuario (2026-08-31): `sslip.io` para el prototipo**, pidiendo en paralelo el
subdominio institucional. `<ip-con-guiones>.sslip.io` resuelve solo a esa IP y Let's Encrypt
emite con normalidad, sin trámite. El nombre sólo aparece en `ASSISTENT_API` y en el
certificado; nadie lo lee.

Cambiar después al subdominio cuesta: registro A, certificado nuevo, y **regenerar y volver a
subir el sitio** con el `ASSISTENT_API` nuevo (una orden, porque la URL se inyecta al generar y
no está escrita a mano en las 313 páginas). Los dos nombres pueden convivir mientras se cambia,
así que no hay ventana de caída. Lo que **no** cambia es la URL de cada norma, que es la que
cita el asistente y la que la gente guarda.

---

## 3.quater El despliegue continuo, y el origen del bucket (D.5-VM)

Aprovisionado el 2026-08-31 con `scripts/gcp_provision_cicd.sh`:

| Qué | Cómo quedó |
|---|---|
| Imágenes | Artifact Registry `govgenai` en `<REGION>`. **Cuatro** imágenes (`app`, `frontend`, `sandbox` y `mcp`, ésta desde REG.4) **etiquetadas con el SHA del commit**, nunca `latest` |
| Identidad | **Workload Identity Federation**, sin ninguna clave en el repositorio. **El nombre del repositorio está anclado en DOS sitios** — ver abajo |
| Cuenta de despliegue | `govgenai-deploy@…` con cuatro roles mínimos: publicar imagen, túnel de IAP, OS Login con sudo y leer instancias |
| Variables del repositorio | **Doce**, puestas con `gh variable set`. **Ninguna es un secreto**: son identificadores, y lo que autoriza es la federación |

#### Los dos anclajes de la identidad federada

Quien siga este documento y ponga sólo el primero se queda a medias, y el síntoma —la
autenticación falla— no señala a lo que falta. Son **dos**, y los dos llevan el nombre del
repositorio:

| Dónde | Qué dice |
|---|---|
| Condición del proveedor OIDC | `assertion.repository=='<ORG>/<REPOSITORIO>'` |
| Enlace de la cuenta de servicio | `principalSet://iam.googleapis.com/projects/<NUMERO_DE_PROYECTO>/locations/global/workloadIdentityPools/github/attribute.repository/<ORG>/<REPOSITORIO>` |

Corolario para cuando el repositorio cambie de dueño o de nombre: **hay que tocar los dos**, y se
hace de forma **aditiva** —ampliar la condición con `||` al nombre nuevo y añadir el segundo
`principalSet`, verificar un despliegue real, y sólo entonces retirar el viejo—. Así no hay
ventana en la que no se pueda desplegar. El código no se toca: el *workflow* lee el proveedor de
una variable y el nombre del recurso no cambia.

**Por qué la condición de atributo importa tanto**: sin ella el proveedor acepta tokens de
**cualquier** repositorio de GitHub, y cualquiera podría crear uno y suplantar a la cuenta de
despliegue. Es el error clásico de esta configuración, y el guion se niega a funcionar sin
`--repo` justamente para no dejarlo al descuido.

### El origen del bucket, que no es un detalle

Las páginas se pueden servir de dos formas, y **no dan el mismo origen**:

| URL | Origen para el navegador |
|---|---|
| `https://storage.googleapis.com/<BUCKET_CORPUS>/…` | `https://storage.googleapis.com` — **el de todos los buckets del mundo** |
| `https://<BUCKET_CORPUS>.storage.googleapis.com/…` | `https://<BUCKET_CORPUS>.storage.googleapis.com` — sólo este bucket |

Se usa la **segunda**. Con la primera, `CORS_ALLOWED_ORIGINS` tendría que abrirse a
`https://storage.googleapis.com` y entonces cualquier página alojada en cualquier bucket de
Google podría llamar a la API. Sigue habiendo dos frenos —la credencial de sitio sólo abre
chatbots `public_anon` y las cuotas por IP—, pero abrir el origen a medio internet cuando
existe una forma acotada es regalar superficie.

De ahí que `CORPUS_SITE_BASE_URL` y `CORS_ALLOWED_ORIGINS` valgan los dos
`https://<BUCKET_CORPUS>.storage.googleapis.com`.

---

## 3.quinquies Copias y vigilancia (D.6-VM)

| Qué | Cómo quedó |
|---|---|
| Copias de la base | Automáticas diarias + **PITR**, activados al crear la instancia (D.3) |
| Restauración | **Probada de verdad el 2026-08-31**: **7 min 43 s** (medidos) hasta ser utilizable |
| Buckets | Versionado activado en `<BUCKET_DOCS>` y `<BUCKET_CORPUS>` |
| Salud | Comprobación cada 5 min sobre `https://<host>/health`, **con validación de certificado** |
| Alertas | Caída de la comprobación, memoria > 85 % y disco > 85 %, al correo del responsable |
| Logs | Rotación local (`max-size 10m`, `max-file 3`) **y** copia en Cloud Logging vía el agente |
| La VM | **No se respalda a propósito**: no guarda nada que no reconstruya el aprovisionamiento |

Todo eso lo pone `scripts/gcp_provision_vigilancia.sh`, idempotente y con `--dry-run`.

**Por qué el agente de operaciones no es opcional**: sin él, Cloud Monitoring sólo ve la máquina
desde fuera —CPU y red—, así que las alertas de memoria y disco **no se pueden ni escribir**. Lo
instala el guion de arranque. Y la rotación local no la sustituye el envío remoto: si la red
falla, el fichero sigue creciendo hasta llenar el disco, que es la avería más aburrida y más
común de una VM.

**Por qué la comprobación valida el certificado**: con un TLS mal renovado el servicio responde
igual, y una comprobación sin `validateSsl` pasaría mientras los navegadores rechazan la página.
Es el fallo que nadie ve venir.

### La restauración, medida

Una copia que nadie ha restaurado nunca es una hipótesis, así que se restauró:

| Paso | Dato |
|---|---|
| Método | Clonado por **punto en el tiempo** (PITR) a una instancia nueva, `govgenai-restore-test` |
| Tiempo | **463 s — 7 min 43 s**, cronometrados alrededor del comando |
| Qué se comprobó | Estado `RUNNABLE` **y** que el clon trae la base `govgenai` y el usuario `govgenai`. Una instancia vacía también estaría `RUNNABLE`: eso es lo que hace falta distinguir |
| Después | El clon se **borró**: una instancia de prueba olvidada factura igual que una de verdad |

Se clonó por punto en el tiempo y no se restauró una copia sobre la instancia de producción a
propósito: probar la copia no puede poner en riesgo lo que la copia protege. Y el clonado ejercita
la cadena entera —copia base más WAL—, que es la garantía que de verdad se quiere.

Tres cosas que conviene saber antes de necesitarlo con prisa:

- La operación de clonado **sigue abierta** un rato después de que la instancia ya sirva: arranca
  su propia copia inicial.
- **Mientras haya una operación en curso no se puede borrar** la instancia; el borrado devuelve
  `409` hasta que termina.
- **`gcloud sql instances clone` salió con código 1 habiendo funcionado.** Creó la instancia
  —lo dice su propia salida— y después reventó con un `404: The Cloud SQL instance does not
  exist` al volver a leerla, que es una carrera del propio cliente. Si se automatiza esto
  algún día, el criterio no puede ser el código de salida: hay que comprobar el estado de la
  instancia y que trae su base.

> **Una alerta que nadie ha visto disparar es una hipótesis.** Queda pendiente de una persona
> apagar el servicio y comprobar que el correo llega — está en el cierre de D.6-VM y no lo puede
> firmar un agente.

---

## 3.sexies El dominio institucional, y el reparto de rutas (DOM, 2026-09-02)

El registro A de `normativa.uji.es` a la IP de `<VM>` apareció el 2026-09-02, y con él el
subdominio institucional pasó de estar pedido a estar en marcha. El certificado ya estaba
cargado en Secret Manager desde D.8, así que **funcionó por SNI sin tocar nada**: cadena de
HARICA/GÉANT, `CN=normativa.uji.es`, válida del 1 de septiembre de 2026 al **19 de marzo de
2027**.

Lo primero que sirvió el dominio fue **el login del panel**, porque el fragmento de rutas de
Caddy mandaba al frontend todo lo que no fuera API ni salud. El reparto de ahora:

| Dirección | Qué sirve | Quién |
|---|---|---|
| `normativa.uji.es/` | la portada pública: presentación e índice | el bucket, `index.html` |
| `normativa.uji.es/cercador` | el cercador de normativa | redirección 301 a `/cercador.html` |
| `normativa.uji.es/gerencia` | el cercador económico-administrativo | redirección 301 a `/cercador_gerencia.html` |
| `normativa.uji.es/html/<norma>.html#art-63` | la ficha de una norma, en su artículo | el bucket, **sin cambiar de forma** |
| `normativa.uji.es/pdf/…`, `/img/…`, `/widget.iife.js` | PDF, imágenes y el widget | el bucket |
| `normativa.uji.es/api/*` | la API | `app:8000` |
| `normativa.uji.es/health` | la salud | `app:8000` |
| `normativa.uji.es/panel/` | **el panel de gestión, y el login** | `frontend:8080` |

**El nombre provisional sirve exactamente lo mismo**, panel incluido, y con el mismo prefijo. No
es economía de configuración: `base` es de tiempo de compilación, así que la imagen del frontend
referencia `/panel/assets/…` sea quien sea el que la sirva. Servir el panel en la raíz de un
nombre y bajo prefijo en el otro pediría dos imágenes del frontend.

Tres cosas que conviene saber antes de tocar esto:

- **La raíz del bucket no es su `index.html`.** Devuelve 200 con `ListBucketResult`, el
  inventario de todos sus objetos: el mapeo de `/` a `index.html` es la configuración de *sitio
  web* de GCS, y eso exige el balanceador HTTPS que este despliegue evitó a propósito (18-25
  €/mes). De ahí el `rewrite / /index.html` del Caddyfile. Quitarlo publica el inventario.
- **El proxy al bucket reescribe la cabecera `Host`.** Con la forma virtual-hosted y el `Host`
  del cliente, GCS no sabe a qué bucket se refiere y responde 404 a todo el sitio, fichas
  incluidas.
- **El prefijo del panel se dice una vez por capa**: `ARG VITE_BASE_PATH` en
  `frontend/Dockerfile`, `location /panel/` en `frontend/nginx.conf` y el matcher del
  `deploy/vm/Caddyfile`. Son tres ficheros y una sola verdad; cuando divergen no hay error en
  ningún log, hay una pantalla en blanco con 404 en la consola. Lo fija
  `server/tests/infra/test_dom2_el_panel_bajo_su_prefijo.py`.

**Qué sigue apuntando al nombre provisional**, y por eso no se retira todavía: el paso de
comprobación de `deploy.yml` (`https://$GOVGENAI_HOST/health` y las dos rutas de `/docs`), la
comprobación de tiempo de actividad de D.6 con su alerta, y cualquier enlace ya enviado por
correo. Retirarlo el mismo día que se estrena el dominio no gana nada.

**Lo que no se ha cerrado**: el bucket sigue siendo público, así que su URL sirve las mismas
páginas y `CORS_ALLOWED_ORIGINS` conserva ese origen. Cerrarlo obligaría a que Caddy se
autenticara contra GCS —el `reverse_proxy` a secas no lo hace— y es un cambio propio.

---

## 3.septies El MCP remoto, y el token que no está en la máquina (REG.4, 2026-09-03)

Desde REG.4 la pila lleva un servicio más, `mcp`, y el proxy le manda `/mcp`. Es un servidor
**MCP** con transporte *streamable HTTP*: un cliente compatible —Claude Code, entre otros— se
conecta a `https://normativa.uji.es/mcp` y obtiene las herramientas que hablan con la API de la
plataforma, en cuatro juegos:

| Juego | Herramientas |
|---|---|
| Registro de actividad (REG.4) | `registrar_actividad`, `detectar_pii`, `anonimizar_texto` |
| Verificaciones (VAS) | `verificar_citas`, `consultar_vigencia`, `auditar_codigo`, `reglas_de_auditoria` |
| Agentes de unidad (#226) | `catalogo_de_agentes`, `consultar_agente`, `ampliar_consulta`, `cargar_indice_de_agente` |
| Catálogo de funciones (#236) | `registrar_cuaderno`, `catalogo_de_funciones` |

**La lista se comprueba sola.** `test_issue89_las_herramientas_del_mcp_no_se_cuentan_a_mano.py`
cruza esta tabla con lo que `http_server` registra de verdad, y se pone rojo si alguna falta. La
versión anterior de este documento daba una cantidad fija, congelada en REG.4, cuando VAS ya
había añadido otro juego.

**Lo que hay que entender antes de tocarlo: este servicio no tiene credencial propia.** El
servidor MCP que ya existía es de línea de comandos, mono-usuario, y lee su token de una variable
de entorno; ahí es lo correcto, porque un proceso equivale a una persona. El remoto atiende a
varios clientes a la vez, así que **el token es el que presenta cada petición** en su cabecera
`Authorization: Bearer`. Poner un PAT en el entorno del contenedor lo dejaría funcionando —de ahí
que la tentación exista— pero todos los clientes actuarían con la misma identidad, y el registro
de actividad, que existe justamente para saber quién usó qué, diría que todo lo hizo un solo
token. Lo impide `server/tests/infra/test_reg4_el_mcp_remoto_esta_declarado.py`.

Los hosts admitidos se derivan de `GOVGENAI_HOST` y `GOVGENAI_HOST_INSTITUCIONAL`, las mismas
variables que usa Caddy, y no de una variable propia. La protección contra *DNS rebinding* del
SDK valida la cabecera `Host` y Caddy reenvía la original: un nombre que faltara en esa lista
recibiría **421 en todo `/mcp`**, y ese error no se parece en nada a su causa.

### Cómo se conecta alguien

Hace falta un PAT con los scopes de lo que vaya a usar: `actividad:write` para registrar y
`anonimizacion:use` para las dos de PII. Se emiten desde el panel, y los puede emitir tanto un
superadministrador como un administrador de organización.

```bash
claude mcp add --transport http govgenai https://normativa.uji.es/mcp     --header "Authorization: Bearer pat_..."
```

Si el token no viaja, las herramientas fallan con un mensaje que lo dice —«Falta el PAT»— y **sin
llamar a la API**: un 401 del servidor haría buscar el problema en el token en vez de en su
ausencia.

### Comprobación después de desplegar

```bash
curl -si https://normativa.uji.es/mcp -X POST     -H 'Accept: application/json, text/event-stream'     -H 'Content-Type: application/json'     -H 'Authorization: Bearer pat_...'     -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | head -1
```

Un `200` cuyo cuerpo traiga **las herramientas de la tabla de arriba** es la señal buena. Un
**421** es la cabecera `Host` fuera de la lista de admitidos; un **502**, el contenedor sin
arrancar.

Se remite a la tabla y no se repite una cantidad **a propósito**: aquí se daba una cantidad
fija, y eso no era un dato desactualizado sino **un criterio de aceptación equivocado** — quien
comprobara un despliegue veía otra cosa y no sabía si estaba bien.

---

## 3.octies Si el superadministrador pierde su contraseña (issue #96)

**No hay recuperación por producto, y es a propósito.** `bootstrap` no rehashea —para que
reejecutar la instalación no revierta un cambio posterior—, el endpoint de cambiar contraseña es
sólo superadministrador y por tanto no puede ayudarle a él mismo, y la plataforma **no envía
correo**, así que no hay autoservicio posible. Tampoco lo arregla el login con Google: el login
local se conserva **como reserva**, justo para entrar cuando Google o su configuración fallen.

La vía es un guion que se ejecuta **en la máquina**, dentro del contenedor:

```
gcloud compute ssh <VM> --zone <ZONA> --tunnel-through-iap
sudo docker compose --env-file /opt/govgenai/.env.despliegue \
  -f /opt/govgenai/docker-compose.vm.yml --profile migrate run --rm \
  --entrypoint python migrate -m server.app.scripts.restablecer_superadmin \
  --email <CORREO>
```

Pide la contraseña **dos veces por entrada estándar** y no la muestra. Tres cosas que conviene
saber antes de usarlo:

- **Su autorización no es un rol: es tener acceso a la máquina.** SSH por IAP, `sudo` y `docker`.
  Añadirle un rol no añadiría seguridad, porque quien puede ejecutar `docker exec` ahí ya puede
  escribir en la base. Por eso es un guion y no una pantalla.
- **Se niega a crear.** Si el correo no existe, falla. Es lo contrario que `bootstrap`, y
  deliberado: crear una cuenta a partir de una errata sería el agujero que este guion no puede
  tener.
- **No acepta la contraseña como argumento.** Quedaría en el historial del *shell* y sería
  visible en `ps` mientras corre.

Deja traza en el registro de la aplicación diciendo a quién y cuándo, **nunca la contraseña ni su
hash**. Hoy esa traza va al registro que recoge el *ops-agent*; no hay tabla de auditoría en el
esquema, y crearla excede lo que esta issue resolvía.

**La alternativa sin código sigue sobre la mesa**: un segundo superadministrador elimina el punto
único de fallo, porque dos pueden restablecerse mutuamente con el endpoint que ya existe. El coste
es multiplicar la cuenta más poderosa. Es decisión de gobierno, no técnica.

---

## 4. Lo que este prototipo deja fuera a propósito

- ~~**Dominio propio.**~~ **Ya no**: `normativa.uji.es` sirve el sitio y la API desde el
  2026-09-02 (ver 3.sexies). Lo que sigue fuera es **un dominio y un sitio de corpus por
  organización**: `CORPUS_SITE_BASE_URL` es una variable global y `HubOrganizacion` no tiene
  columna para su dominio ni para su sitio. Sería una columna anulable con la cascada que ya
  existe, así que hacerlo hoy o en seis meses cuesta lo mismo.
- ~~**El asistente de Gerencia.**~~ **Es público**, y el usuario confirmó el 2026-09-02 que
  puede seguir siéndolo: no hay nada comprometido en su corpus. Tiene su propio cercador
  publicado (`/gerencia`) y su tarjeta en la portada.
- **Copias de seguridad y vigilancia**, que son D.6.

## 5. Riesgos que conviene mirar antes de abrirlo a gente

| Riesgo | Estado |
|---|---|
| Chatbot público sin límite por IP | **Resuelto**: las cuotas de SEC.4 ya tienen superficie en el panel. Ponle un valor |
| Presupuesto total de tokens agotable | `total_token_budget` a 0 es «sin techo». Para un prototipo abierto, conviene poner uno |
| Respuestas que citan mal | El aviso de vigencia desplazada ya viaja (PIL.3), pero **219 defectos del corpus siguen pendientes de Secretaría General** y 43 documentos no tienen la vigencia validada |
| La página de documentos del panel se bloquea con 297 documentos | Sin arreglar. Es del panel de administración, no del sitio público |
