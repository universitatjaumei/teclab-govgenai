# Modelo de seguridad del Sandbox de scripts

El sistema permite a usuarios autenticados proponer scripts Python para extraer datos de documentos y generar gráficos. Este documento describe el modelo de amenazas y las capas de defensa implementadas.

---

## 1. Modelo de amenazas

### Adversario

Usuario autenticado de la plataforma (rol *proposer*) que intenta:

- Exfiltrar datos del cliente (base de datos, almacenamiento).
- Escalar privilegios dentro del contenedor o del host.
- Leer ficheros del sistema de archivos del contenedor.
- Provocar denegación de servicio (bucles infinitos, consumo de CPU/memoria).
- Pivotar hacia otros tenants o servicios internos.

### Activos protegidos

| Activo | Descripción |
|--------|-------------|
| `postgres` | Base de datos del cliente con expedientes y datos personales |
| `minio` / GCS | Almacenamiento de documentos subidos por el cliente |
| Red interna del cliente | Servicios en la misma red que el API (`default` bridge) |
| Otros tenants | Workspaces de otros usuarios en la misma instancia |

### Suposiciones del modelo

- El atacante puede escribir **código Python arbitrario**.
- La auditoría AST puede ser **bypassable** por ofuscación avanzada o errores en el parser.
- El script se ejecuta en un **subproceso hijo** del contenedor sandbox; el sandbox no tiene acceso a la BD ni al almacenamiento.

---

## 2. Capas de defensa

El sistema implementa defensa en profundidad con 8 capas independientes. Comprometer el sistema requiere superar **todas** las capas simultáneamente.

### Capa 1 — Auditoría AST en la API (pre-aceptación)

`ScriptSecurityAuditor` en `server/app/modules/redaccion/services/script_auditor.py` analiza el AST del script **antes de aceptar la propuesta**. Bloquea:

- Importaciones fuera de la whitelist (`os`, `subprocess`, `socket`, `requests`, etc.).
- Llamadas a `eval()`, `exec()`, `__import__()`.
- Acceso a dunder attributes (`__class__`, `__globals__`, etc.).

### Capa 2 — Workflow HITL (aprobación humana)

Antes de que un script llegue a ejecución en producción, debe pasar por el flujo de revisión humana de `9R.5.6`:

1. El proposer crea y prueba el script con datos anonimizados.
2. El proposer valida el resultado (`validate-test-result`).
3. El admin re-ejecuta (`admin-retest`) y verifica el hash.
4. El admin aprueba (`approve`) con una ventana de 10 minutos tras el retest.

Ningún script llega a plantillas globales sin un humano en el loop.

### Capa 3 — Red `sandbox-net` aislada

El servicio `script-sandbox` vive **exclusivamente** en la red `sandbox-net`. En producción (`internal: true`):

- No hay resolución DNS hacia `postgres`, `minio` ni otros servicios.
- No hay egress hacia internet.
- El único servicio conectado a ambas redes (`default` y `sandbox-net`) es `app`.

En desarrollo (`internal: false`) se permite tráfico de salida para el build/pull inicial, pero el sandbox no tiene credenciales para acceder a la BD.

### Capa 4 — Contenedor sin privilegios

```yaml
cap_drop: ["ALL"]
security_opt:
  - no-new-privileges:true
user: "65534:65534"   # nobody — sin shell, sin home
read_only: true       # filesystem de solo lectura
tmpfs:
  - /tmp/sandbox:size=128M,mode=0700,uid=65534,gid=65534
```

El contenedor no puede:
- Adquirir nuevas capacidades (`no-new-privileges`).
- Escribir en ningún path excepto `/tmp/sandbox` (tmpfs efímero).
- Escalar a root (usuario 65534 sin privilegios).

### Capa 5 — Re-auditoría AST dentro del sandbox

`services/script_sandbox/sandbox/auditor.py` es una **copia defensiva** del auditor de la API. Se ejecuta dentro del microservicio sandbox como segunda línea de defensa, independiente del código de la API. Un bypass de la capa 1 no garantiza pasar la capa 5.

### Capa 6 — Subproceso efímero por petición

Cada petición al sandbox lanza un **nuevo subproceso Python** (`subprocess.Popen`) que:

- Ejecuta solo el script del usuario.
- Arranca en **su propia sesión**, y al terminar —bien, mal o por tiempo— se mata **su grupo de
  procesos entero** (`runner._matar_el_grupo`): lo que el guion haya lanzado no sobrevive.
- No tiene acceso al entorno del proceso padre del sandbox.

**Y las peticiones se ejecutan de una en una** (`main._UNA_A_LA_VEZ`). Hasta el 2026-10-22 esta
capa decía «sin estado compartido entre peticiones», y no era cierto: los endpoints son `def`
síncronos que FastAPI corre en paralelo, todas las ejecuciones comparten uid y `/tmp/sandbox`, y
un guion que saltara la auditoría leía los ficheros de entrada de otra organización mientras se
ejecutaba. Con una a la vez, mientras corre un guion no existen los ficheros de ningún otro —se
borran al acabar cada ejecución— y nada del anterior sigue vivo. Es la garantía real frente a la
lectura entre organizaciones; la auditoría sólo la hace difícil. Cuesta rendimiento: las
ejecuciones esperan en cola, y `timeout_seconds` tiene un techo de 300 para que ninguna bloquee
la cola indefinidamente. Lo prueba `services/script_sandbox/tests/test_una_ejecucion_no_ve_otra.py`.

### Capa 7 — Límites de recursos Docker

```yaml
deploy:
  resources:
    limits:
      cpus: '1.0'
      memory: 512M
tmpfs:
  - /tmp/sandbox:size=128M
```

Evita que un script malicioso agote la CPU, la memoria o el disco del host.

> **El préstamo se saldó el 2026-09-25 y el despliegue de referencia vuelve a 512M.** La VM
> subió a `e2-medium`, así que ya no hace falta quitarle memoria a esta capa. Lo que sigue
> queda escrito porque explica cómo se pide prestado sin cambiar el modelo de seguridad, y
> cómo se devuelve.
>
> **El despliegue de referencia llevó 192M en vez de 512M entre el 24 y el 25 de septiembre.** Los dos
> *compose* autoinstalables —`docker-compose.yml` y `docker-compose.prod.yml`— mantienen los 512M
> que esta capa describe; quien instale la plataforma los tiene. La desviación es sólo de la VM de
> la UJI (`deploy/vm/docker-compose.vm.yml`): el 2026-09-24 el contenedor de la aplicación se
> quedó sin memoria atendiendo consultas del chat, y en una `e2-small` de 2 GB no había de dónde
> sacarla salvo de aquí.
>
> **Es un préstamo con condición de salida escrita**, no un cambio del modelo de seguridad: se
> pudo hacer porque hoy nadie ejecuta scripts en esa instalación, y el día que se abra a usuarios
> que los suban, la VM sube de tipo y este techo vuelve a 512M. Está en la línea de al lado del
> propio techo, en el compose, y en la issue #149 con la factura hecha.
>
> Lo que sí cambia mientras dure: **un guion que necesite más de 192M morirá por OOM** en esa
> instalación. Las otras siete capas no se tocan.

### Capa 8 — gVisor en la VM (la pone el aprovisionamiento)

**Esta capa la daba la plataforma y ahora la ponemos nosotros.** Hasta el 2026-08-10 el destino era un servicio gestionado que ejecuta los contenedores sobre gVisor sin que nadie lo pida; el destino pasó a ser una **VM con Docker Compose** (`DECISION_EXTRACCION_Y_DESPLIEGUE.md` §2), y ahí **no está salvo que se configure**. Se configura: es la única capa que mitiga una fuga del kernel del host, y las suposiciones del modelo dicen que la auditoría AST es *bypassable*.

**gVisor** (runtime `runsc`) intercepta las llamadas al sistema del contenedor y las emula en espacio de usuario, así que un exploit de kernel se estrella contra un kernel que no es el del host.

Cómo se pone, en el aprovisionamiento de la VM (D.4-VM):

1. Instalar `runsc` y registrarlo como runtime de Docker en `/etc/docker/daemon.json`.
2. Ejecutar bajo ese runtime **sólo el sandbox**, que es el único que corre código ajeno:

```yaml
script-sandbox:
  runtime: runsc
```

Con plataforma `systrap`, no `kvm`: `kvm` necesita `/dev/kvm` y por tanto virtualización anidada, que en GCE no está en todos los tipos de máquina. `systrap` funciona en cualquier VM y su coste de rendimiento es irrelevante para scripts que duran segundos.

Cómo se comprueba — **una capa que no se comprueba no se cuenta**, y ésta ya se contó una vez sin estar:

```bash
docker compose exec script-sandbox dmesg | grep -i gvisor
# Starting gVisor...     <- si no sale nada, la capa 8 NO está y quedan 7
```

---

## 3. Lo que este diseño NO mitiga

| Amenaza | Estado |
|---------|--------|
| Exploits del kernel del host | Mitigado parcialmente por gVisor (capa 8), **si el aprovisionamiento lo configuró**: lo dice la comprobación de esa capa, no la suposición |
| Side-channel attacks entre tenants | Fuera de alcance MVP |
| Un guion que salte la auditoría puede **señalizar al servidor del sandbox** (mismo uid) y tumbarlo hasta que Docker lo reinicie, o **pedir a la API** desde `sandbox-net` lo que pediría un anónimo | Abierto. Separarlo exige otro uid por ejecución o una regla de salida de red, y ninguno de los dos cabe en un contenedor sin capacidades. El límite de intentos del login sí está cubierto: desde esa red no se cree `X-Forwarded-For` |
| Inyección de prompts maliciosos al LLM que generan bypass | Mitigado por capas 1, 2 y 5 |
| Ataques de timing para inferir datos de otros tenants | Fuera de alcance MVP |

---

## 4. Cómo auditar el aislamiento

### Comandos de verificación manual

Tras `docker compose -f docker-compose.prod.yml up -d`:

```bash
# 1. El sandbox NO debe poder resolver postgres
docker compose -f docker-compose.prod.yml exec script-sandbox \
  python -c "import socket; print(socket.gethostbyname('postgres'))"
# Resultado esperado: socket.gaierror (Name or service not known)

# 2. El sandbox NO debe poder salir a internet
docker compose -f docker-compose.prod.yml exec script-sandbox \
  python -c "import urllib.request; urllib.request.urlopen('https://www.google.com', timeout=3).read()"
# Resultado esperado: urllib.error.URLError / OSError (Network unreachable)

# 3. El API SÍ debe poder hablar con el sandbox
docker compose -f docker-compose.prod.yml exec app \
  curl -s http://script-sandbox:5000/health
# Resultado esperado: {"status":"healthy"}

# 4. El sandbox NO debe poder hablar con el API
docker compose -f docker-compose.prod.yml exec script-sandbox \
  python -c "import urllib.request; urllib.request.urlopen('http://app:8000/health', timeout=3).read()"
# Resultado esperado: OSError / urllib.error.URLError (Network unreachable)
```

### Inspección de capacidades del contenedor

```bash
docker inspect govgenai_script_sandbox --format '{{json .HostConfig.CapDrop}}'
# Resultado esperado: ["ALL"]

docker inspect govgenai_script_sandbox --format '{{json .HostConfig.SecurityOpt}}'
# Resultado esperado: ["no-new-privileges:true"]

docker inspect govgenai_script_sandbox --format '{{.HostConfig.ReadonlyRootfs}}'
# Resultado esperado: true
```

---

## 5. Migración futura a gVisor explícito (on-premise)

Para despliegues on-premise donde el cliente gestiona su propio Kubernetes/containerd con gVisor instalado:

```yaml
# En el Deployment de Kubernetes (o en docker-compose con el plugin gVisor):
runtime: runsc   # requiere gVisor instalado en el nodo
```

Pasos:
1. Instalar gVisor (`runsc`) en los nodos del cluster: [gVisor installation](https://gvisor.dev/docs/user_guide/install/).
2. Crear un `RuntimeClass` en Kubernetes con `handler: runsc`.
3. Añadir `runtimeClassName: gvisor` al `PodSpec` del `script-sandbox`.
4. Verificar con `docker run --runtime=runsc hello-world` que el runtime funciona.

Este paso queda fuera del MVP; se documenta aquí por si el departamento de seguridad del cliente lo requiere.

---

## 6. Diferencias dev vs. prod

| Aspecto | Desarrollo (`docker-compose.yml`) | Producción (`docker-compose.prod.yml`) |
|---------|-----------------------------------|----------------------------------------|
| `sandbox-net.internal` | `false` (permite build/pull) | `true` (sin egress a internet) |
| Puerto expuesto al host | `127.0.0.1:5001:5000` (para `uv run` local) | Ninguno |
| `app` conectado a `sandbox-net` | No (el API corre en host con `SANDBOX_BASE_URL=http://localhost:5001`) | Sí (`default` + `sandbox-net`) |
| `SANDBOX_MODE` recomendado | `local` para tests sin Docker; `http` con Docker Compose | `http` (siempre) |
