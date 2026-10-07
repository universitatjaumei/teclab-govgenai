# Valoración del proyecto — Gov Gen AI Platform

> Auditoría previa al despliegue del piloto: estado del desarrollo, seguridad, separación por
> organizaciones (multitenencia) y aislamiento del núcleo respecto de la configuración para el
> modelo de desarrollo colaborativo (fork/upstream) que declaran `README.md` y `CONTRIBUTING.md`.
> Fecha: 2026-08-24. Cursor del proyecto: **Deploy/D.0** (fase 1 del Bloque MT cerrada, `b705bfa`).
> Sustituye a la valoración del 2026-07-11.
>
> Método: cuatro auditorías de solo lectura sobre el árbol en `main` @ `b705bfa` (working tree
> limpio), verificación directa de los hallazgos críticos, y ejecución de las dos suites de
> tests. Cuando un hallazgo lo señalan dos auditorías independientes se indica, porque eleva la
> confianza. Las cifras de tests son **medidas en esta sesión**, no heredadas del historial.
>
> ---
>
> ## ⚠️ Estado de este informe (actualizado el 2026-08-24, mismo día)
>
> **El Bloque SEC.9 ya se ejecutó**, así que la sección 3 y los puntos 1–5 y 11 del plan de acción
> describen fallos **ya corregidos**. Se conservan tal cual —un informe de auditoría que se reescribe
> a medida que se arregla deja de poder auditarse a sí mismo—, pero al leerlos hay que saber que:
>
> - `library_router` exige identidad y la deriva del token; `/push` y `/sign_manifest` son de
>   superadministrador (SEC.9.1).
> - `HubProviderOut` ya no lleva `api_key` y `hub_llm_configs` pasa por la capa de tenencia (SEC.9.2).
> - El escritor de prompts de actividad respeta la organización (SEC.9.3).
> - La credencial literal desapareció **con su columna**: la base guarda un puntero (SEC.9.4).
> - **El gate de aislamiento recorre el árbol de routers** en vez de una lista fija, y pasó de 4
>   ficheros a 9 y de ~40 a 133 tests que bloquean el despliegue (SEC.9.5).
> - Los cinco controles «declarados y no aplicados» se aplican (SEC.9.6).
> - **MT.16 se adelantó**: dos organizaciones reales, sobre BD real, sin verse (SEC.9.7).
>
> Suite tras el bloque: **backend 3056 passed / 1 skipped / 0 fallos** (24:34, `-n0`) y **frontend
> 645 passed / 0 fallos sobre 246 ficheros**. La cifra del frontend se tomó con el reporter JSON
> propio de vitest y no con la salida filtrada por el proxy de shell, que en esta sesión dio tres
> recuentos distintos (598, 626, 645) para el mismo estado del árbol; el «598» del §2.4 viene de
> esa salida filtrada, así que **la medición fiable es 645**.
> **El Bloque AIS (§5 y puntos 6–10, 12–14) sigue pendiente**, y con él el único hallazgo que
> bloquea de facto el modelo open source: la paleta del panel.
>
> ---
>
> ## ⚠️ Segunda nota de estado (REPO.3, 2026-09-07): §2.3 ya no describe el presente
>
> Este informe **se conserva como instantánea fechada** y no se reescribe, por la misma razón que
> dice la nota de arriba. Pero han pasado dos semanas y su §2.3 —«deuda de calidad que sigue
> pendiente»— enumera siete cosas de las que **seis están cerradas**, así que leerlo sin este
> aviso manda a arreglar lo ya arreglado:
>
> - `subprocess.run` en `to_pdf` → **cerrado**, es `await asyncio.to_thread(_convertir)`.
> - `create_all` en el *lifespan* → **cerrado** por **BD.2**: el esquema lo define Alembic y sólo
>   Alembic, con `alembic check` en CI.
> - Fallback de `DATABASE_URL` con credenciales → **cerrado**: `_dsn()` falla duro en producción.
> - Sin *code-splitting* en el frontend → **cerrado**: el panel carga 45 fragmentos en diferido.
> - `client_app/` como peso muerto → **cerrado** por **NIC.3**, que retiró 574 ficheros.
> - Persistencia del mapa de anonimización → **cerrado por decisión** en **AIS.5** (2026-08-24):
>   el piloto no trata datos de ciudadanos, así que no hay bóveda antes del piloto y la
>   persistencia es F2.A.4. Los dos *no-op* se borraron en vez de dejarlos marcados.
>
> **Sobrevive una, y ha empeorado**: la higiene de arranque. Los `print()` de `server/app/` eran
> 157 y son **186**. Está trasladada a `planificacion/PROJECT_STATE.md`, que es donde vive el
> trabajo pendiente; aquí sólo queda dicho para que §2.3 no engañe.
>
> Y el hallazgo que la nota de arriba llamaba bloqueante —la paleta del panel— **está cerrado**:
> el bloque AIS se ejecutó, y hoy lo vigilan `paletaDelPanelNoEsDeNadie.test.ts` y
> `marcaNoViajaEnElRepo.test.ts`.

---

## 1. Resumen ejecutivo

Han pasado seis semanas y muchos bloques desde la valoración de julio, y el cambio de fondo es
que **aquella auditoría cumplió su función**: los dos fallos críticos que bloqueaban el
despliegue (login sin contraseña y ausencia de aislamiento multi-tenant) están corregidos, y no
de boquilla —hay commits con borrados masivos, migraciones, y sobre todo **tests de guardarraíl
sobre el árbol** que impiden la recaída—. El proyecto llega a la puerta del piloto en un estado
sólido y con una disciplina de ingeniería poco habitual para un desarrollo prácticamente en
solitario.

Dicho eso, esta auditoría **no da luz verde incondicional al despliegue**. Las tres conclusiones:

1. **La seguridad estructural está resuelta; la regresión está en los bordes nuevos.** Los diez
   hallazgos de julio (A1–A5, widget, temas, uploads, docs, JWT) están resueltos o
   sustancialmente mitigados. Pero los bloques recientes (MT, PLAT, REV) han abierto agujeros
   nuevos que **tres de las cuatro auditorías encontraron por separado**: un router de biblioteca
   (`library_router`) **completamente sin autenticar** que incluye un oráculo de firma RSA, la
   clave de proveedor LLM **devuelta en claro** por la API, y dos routers de configuración sin
   filtro por organización. Ninguno estaba en julio: son deuda introducida después. Son
   bloqueantes de despliegue con datos reales, pero baratos de cerrar (un bloque SEC.9 corto).

2. **La separación por organizaciones es robusta en su núcleo y frágil en su superficie.** Las
   dos capas que hacen cumplir la frontera (`tenancy.py` y `ambito.py`) son de calidad muy alta,
   fail-closed en los casos difíciles, y el widget/chat público —la superficie más expuesta— está
   bien cerrado. Pero el esquema de MT.1–MT.7 metió la *dimensión* de organización en las tablas
   sin que todos los routers la *usen* todavía, y el inventario de `docs/MULTITENENCIA.md`
   presenta como funcionalidad viva algunas columnas que aún no consume nadie. Es coherente con la
   decisión declarada («meter el esquema antes del piloto, la vista y los permisos después»), pero
   hay que separar con precisión lo que es hueco documentado (fase 2) de lo que es fuga real.

3. **El aislamiento núcleo/configuración es genuino, con una grieta concreta que sí importa para
   el modelo open source.** El mecanismo de fork/upstream está encarnado en código real
   (vocabulario como dato, prompts con default-en-código y override-en-BD, branding en BD con un
   test que prohíbe que la marca viaje al repo). Pero la paleta de color del panel de
   administración está hardcodeada como «UJI brand» en `index.css` y la cascada de temas no la
   alcanza: otro ayuntamiento que despliegue el principal tendría el panel con los colores de la
   UJI y sin pantalla para cambiarlos. Es el único hallazgo que **bloquea de facto** el uso del
   principal tal cual. Falta, además, implementar el §13 de la AGPL (enlace al fuente en la
   interfaz y en el widget) y varias piezas de infraestructura de contribución.

**Recomendación:** insertar un **Bloque SEC.9** (endurecimiento de la 3ª auditoría, 4–6 prompts)
entre el cursor actual y D.0, más un puñado de arreglos de aislamiento OSS de coste bajo. El
resto es deuda conocida y acotada que puede acompañar al piloto documentada.

---

## 2. Estado del desarrollo

### 2.1 Dónde está el proyecto

El cursor está en **Deploy/D.0**. Antes del piloto quedan, por decisión del usuario, los bloques
PLAT (administración de plataforma), IDE (identidad y permisos) y MT (multitenencia), **los tres
ya completos**, más el propio despliegue. La fase 1 del Bloque MT (MT.1–MT.7) cerró el 2026-08-24
y era lo único que el usuario puso explícitamente delante del piloto; la fase 2 de MT (vista y
permisos, MT.8–MT.21) queda para después, porque depende de cómo resulte el piloto.

Los tres módulos de usuario del MVP están construidos y verificados de punta a punta en navegador
en sesiones anteriores: **Chatbots** (RAG en tres niveles, widget embebible, chat identificado),
**Informes** (extracción determinista + valoración de IA aprobada por humano) y **Curación**
(rastreo de portal, detección de contenido caducado, selección de corpus). Los dos módulos
previstos y aún no existentes —Automatización de procesos y Gestor de expedientes— están
correctamente marcados como no construidos en el README.

### 2.2 Los problemas de calidad de julio: qué se resolvió

Los tres problemas estructurales grandes del §3 de la valoración anterior están **genuinamente
resueltos**, con la diferencia clave de que hay tests que impiden la recaída:

| Problema de julio | Estado | Evidencia |
|---|---|---|
| `api/v1/automation.py` (1.189 LOC, 19 endpoints, DI violada, sin registrar) | **Resuelto** | Borrado en `6e78b35` (ROL.1), −1189 LOC. El fichero no existe. |
| `server/app/ui/` (21 ficheros NiceGUI en árbol activo) | **Resuelto** | Retirado a `_legacy_nicegui/` (CAL.1). 3 tests de cuarentena lo vigilan. |
| `AIBrainService` monolítico (~1.082 LOC) | **Resuelto** (la clase no existe) | Ver deuda nueva D1: el módulo sustituto quedó sin cablear. |
| Shims `init_db`/alias en `seeds.py` | **Resuelto** | Guardarraíl `test_no_legacy_shims.py`. |
| Capa API manual del frontend (fetch crudo, tipos a mano) | **Resuelto** (estructural) | Migrado a Orval con guardarraíl `contractFirstApi.test.ts`. Ver D2: queda una isla que es un bug. |
| Scopes calculados en cliente (`AccessTokensPage`) | **Resuelto** (#230) | Primero se resolvió con `scopesForRole()`, una función pura testeable, pero la lista seguía siendo del cliente y se quedó en cinco alcances mientras el servidor llegaba a quince. Desde #230 los alcances y las organizaciones los da `GET /auth/pats/opciones`. |
| `ca/admin.json` al ~25 % | **Resuelto** | Paridad **exacta**: 854 claves × 3 locales, 0 huecos, con guardarraíl de cobertura. |
| `DocumentsPage.tsx` (1.019 LOC) | **Resuelto** | Descompuesta a 287 LOC + 12 módulos con tests. |

La brecha más grave de todas —que CI ejecutaba solo el 42 % de los tests, invalidando todas las
cifras— también está cerrada: `ci.yml` ejecuta ahora `pytest tests` entero con `-n0`, más dos
gates separados que bloquean el despliegue (aislamiento entre organizaciones y regresión de
retrieval).

### 2.3 Deuda de calidad que sigue pendiente

Ninguna es bloqueante por sí sola para un piloto, pero conviene tenerlas a la vista:

- **Higiene de arranque y observabilidad.** 157 llamadas a `print()` en `server/app/` y **sin
  configuración de logging de la aplicación** (el único `basicConfig` está dentro de un script).
  En el piloto la observabilidad será stdout sin niveles ni timestamps. Además, el `except
  Exception` del arranque del scheduler de calidad (`main.py:156`) se traga cualquier fallo con un
  `print` y devuelve `None`.
- **`subprocess.run` síncrono en `async def to_pdf`** (`curation/report_exporter.py:108`): bloquea
  el event loop durante la conversión de LibreOffice. Envolver en `asyncio.to_thread`.
- **`create_all` en el lifespan** (`main.py:260-261`) conviviendo con 72 migraciones Alembic.
  Mitigado en producción por un servicio `migrate` en `docker-compose.prod.yml`, pero el `CMD` del
  `Dockerfile` no ejecuta `alembic upgrade head`: un despliegue que arranque la imagen sin ese
  compose (Kubernetes, `docker run`) se apoyará silenciosamente en `create_all` y divergirá.
- **Fallback de `DATABASE_URL` con credenciales en claro** (`db.py:13-16` y
  `connection.py:18-19`): si la variable falta, el servidor arranca contra una BD conocida en
  silencio en vez de fallar. `JWT_SECRET_KEY` sí falla duro; `DATABASE_URL` debería también.
- **Sin code-splitting en el frontend**: 0 `React.lazy` en ~31.500 líneas de `.tsx`; todo va a un
  bundle único junto con ~500 KB de clientes Orval. Coste de primera carga relevante para equipos
  y redes modestas de una administración local. Barato de arreglar con lazy routes.
- **`client_app/`**: 469 ficheros `.py` (era 489; −4 %). Es peso muerto en el repo, **no en el
  artefacto** (el `Dockerfile` no lo copia). Su retirada está asignada al Bloque NIC, después del
  despliegue. No bloquea.
- **Persistencia del mapa de anonimización**: `save_state`/`load_state` siguen siendo no-op
  (`anonymization/service.py:231-237`). El mapa se produce en memoria pero no sobrevive al
  proceso, así que **re-identificar un informe generado ayer es imposible** y no queda rastro de
  auditoría del mapeo. Si el piloto maneja datos reales de ciudadanos por el flujo de Informes,
  esto merece una decisión explícita **antes** de arrancar, no un descubrimiento a posteriori.

### 2.4 Cifras de tests (medidas en esta sesión)

- **Frontend**: 598 tests, 0 fallos (vitest en serie, `--no-file-parallelism`).
- **Backend**: 2978 tests passed, 1 skipped, 0 fallos (pytest completo desde Git Bash, `-n0`, con
  Docker levantado; 24 min 05 s). La suite entera está verde con las regresiones de seguridad y
  multitenencia de este informe presentes: **ningún test las cubre**, que es precisamente el
  problema de método del §3.3.
- 315 ficheros de test en `server/tests/`, 95 en el frontend. 72 migraciones Alembic.
- Solo 14 marcas TODO/FIXME en todo el backend (2 de ellas los no-op de anonimización) y **cero**
  en el código de producción del frontend. Cifra inusualmente baja para ~50 K + ~31 K LOC.

---

## 3. Seguridad

> Verificación de los diez hallazgos de julio contra el código actual, más los hallazgos nuevos
> introducidos por los bloques posteriores. La base sigue siendo mejor que la media (bcrypt, PAT
> correcto, ORM parametrizado, JWT sin secreto por defecto, sandbox de scripts, cabeceras de
> seguridad, CORS por entorno). El problema ya no es la base: es que la superficie creció más
> rápido que el gate que la vigila.

### 3.1 Hallazgos de julio — estado

| # | Hallazgo | Estado | Nota |
|---|---|---|---|
| A1 | Login de partner/admin sin contraseña | **Resuelto** | bcrypt + hash señuelo anti-timing + rate limit por IP antes de tocar la BD (`auth_router.py:60-144`). Ningún login local sin credencial. |
| A2 | Sin aislamiento multi-tenant | **Parcial** | Claim `orgs` en JWT (fail-closed), capa única `tenancy.py`, gate de CI propio. Pero cuatro routers nuevos quedan fuera — ver 3.2. |
| A3 | Secretos en `.env` | **Resuelto** estructural | `.env` en `.gitignore`, `generate_env.sh` con `openssl rand`, nunca commiteado. Residuos: fallback de `DATABASE_URL` (§2.3) y la rotación de credenciales no es verificable desde el código. |
| A4 | CORS `allow_origins=["*"]` | **Resuelto** | Por entorno; en producción el `*` se descarta aunque venga en la variable (`core/cors.py`). |
| A5 | Sin rate limiting ni cuotas | **Parcial** | Implementado y probado (`rate_limit.py`, `quotas.py`, `hub_usage_counters`). Pero la cuota por IP del anónimo del widget nunca se aplica — ver NUEVO-6. |
| — | Widget: bearer privilegiado en `data-token` | **Resuelto** | `HubWidgetKey` con SHA-256, revocable, scope `public_anon`, atada al chatbot de la ruta. |
| — | Temas sin auth + path traversal con `unlink` | **Resuelto** | Temas en BD; desapareció el almacén de ficheros y todo `unlink`. `theme_id` validado como UUID. |
| — | Uploads sin magic bytes ni límite | **Parcial** | `core/uploads.py` con magic bytes, corte en streaming, anti-traversal. Falta un endpoint — ver NUEVO-5. |
| — | Docs FastAPI + cabeceras de seguridad | **Resuelto** | Docs off en producción; HSTS/CSP/X-Frame-Options/nosniff, también en errores. |
| — | JWT + placeholder SAML | **Resuelto** | Sin default inseguro (rechaza valores de ejemplo y <32 car.); SAML con `wantAssertionsSigned` + `validate_cert`. |
| — | Sandbox de scripts (gate prod + auditor AST) | **Parcial** | Ambos existen. El gate se salta con `TESTING=1` — ver NUEVO-7. |
| — | Sembrado de desarrollo (`admin1234`) | **Resuelto** | Solo se siembra si `ENVIRONMENT=development`; bootstrap de producción aparte. |

### 3.2 Hallazgos nuevos (introducidos después de julio)

Ordenados por severidad. Los tres primeros son **bloqueantes de despliegue con datos reales**.

- **CRÍTICO — `library_router` completamente sin autenticación** (verificado directamente;
  coincidencia de 3 auditorías). `server/app/routers/library_router.py`, montado en
  `/api/v1/library/*`. Ninguno de sus 4 endpoints tiene `get_current_user`, `require_role` ni
  `require_module`:
  - `GET /manifest` y `GET /download/{item_id}` deciden la visibilidad por las cabeceras
    `X-Client-Id`, `X-Partner-Id`, `X-Client-Groups` — **que pone el propio cliente**. La
    identidad de tenant es autodeclarada; devuelve el código ejecutable de la automatización de
    cualquier cliente.
  - `POST /push` (`:113`) publica una automatización arbitraria **y el servidor la firma** con la
    clave privada de la plataforma. Inyección firmada en la cadena de suministro.
  - `POST /sign_manifest` (`:171`) es un **oráculo de firma abierto**: se le pasa un JSON y un
    `partner_id` (ambos del cuerpo) y devuelve la firma RSA-SHA256 hecha con
    `AUTOMATIA_SIGNING_KEY`.
  - Agravante: el test `test_plat5_frontera_de_modulos.py` declara este router como `plataforma`
    pero solo comprueba que la cadena aparezca en el **docstring**, no que haya un `Depends`. El
    check pasa en verde sobre un router abierto.
  - Arreglo: `dependencies=[Depends(require_module("plataforma")), Depends(require_admin)]` en el
    `APIRouter`, derivar la tenencia del token, y restringir `/push` y `/sign_manifest` a
    superadmin.

- **ALTO — La clave del proveedor LLM se devuelve en claro por la API** (verificado
  directamente). `HubProviderOut.api_key` (`hub_llm_configs_router.py:44`) y `GET /providers`
  devuelven la fila ORM tal cual. `HubProvider.api_key` es ámbito `plataforma`, así que cualquier
  `admin` de cualquier organización lee la clave del proveedor de la plataforma en claro (y
  `PATCH` se la puede cambiar). Arreglo: quitar `api_key` de `HubProviderOut`.

- **ALTO — `hub_activity_prompts_router` sin filtro de organización** (coincidencia de 2
  auditorías). MT.6 dio a la tabla la dimensión de organización (`(activity, organizacion_id)`
  con `NULLS NOT DISTINCT`) y el *lector* la respeta, pero el *escritor* no: `_fila()`
  (`:126-130`) consulta solo por `activity`. Consecuencia: un `admin` de cualquier organización
  puede leer, **sobrescribir o borrar** el prompt de plataforma que heredan todas las
  organizaciones (cross-tenant write + inyección de prompt al LLM). El router no tiene
  `require_module` y ningún test de aislamiento lo cubre.

- **ALTO — `hub_llm_configs_router` (MT.2) sin tenancy.** `list_llm_configs` sin
  `scope_query_to_orgs` (un admin ve las configuraciones de todas las organizaciones);
  `create_llm_config` acepta `organizacion_id` del cuerpo sin validarlo contra el token (un admin
  crea un modelo en otra organización, o de plataforma que heredan todas); `update`/`delete` por
  id sin `assert_org_access`. Es exactamente lo contrario del criterio «el cuerpo propone, el
  token dispone» que `hub_themes_router` ya aplica bien. Mitigante: el router exige
  `require_module("plataforma")`.

- **MEDIO-ALTO — `hub_provider_credentials` (MT.2): la clave literal se guarda sin cifrar.**
  `api_key` en `String(255)` en texto plano cuando `metodo='clave'`. No hay cifrado en reposo en
  ningún punto (0 coincidencias de Fernet/encrypt/KMS). **No se expone por HTTP** (no hay router
  para esa tabla), así que el riesgo es un volcado de BD o la sincronización cloud→edge. Hoy es
  teórico (no hay filas); sube a real el día que el piloto cree la primera credencial. Decisión:
  cifrar en reposo, o restringir el `CHECK` a los métodos que no guardan el secreto en la base
  (nombre de variable de entorno / ADC), que es lo que el propio módulo recomienda.

- **MEDIO** — un grupo de hallazgos de severidad media, todos con arreglo acotado:
  - **NUEVO-5**: subida sin límite de tamaño en `POST /redaccion/llm-drafts/sample`
    (`llm_drafts_router.py:163`, `file.read()` sin `read_within_limit`). El único endpoint de
    `UploadFile` que quedó fuera de SEC.6/SEC.8.2.
  - **NUEVO-6**: los controles de SEC.4 para el anónimo del widget están declarados y no
    aplicados: `anon_ip_daily_token_quota` es código muerto (nunca se pasa `ip=`), y todos los
    visitantes anónimos de un chatbot comparten un único cubo de rate limit, así que un visitante
    puede dejar el widget sin servicio para el resto.
  - **NUEVO-7**: el gate de producción del sandbox se salta con `TESTING=1`, y `subprocess.Popen`
    no pasa `env=`, heredando `JWT_SECRET_KEY`/`DATABASE_URL`/`AUTOMATIA_SIGNING_KEY`.
  - **NUEVO-8**: endpoints post-SEC.8 con el usuario declarado y sin usar (`hub_agents_router`
    ignora `workspace_id` y exporta una interacción cualquiera; tres endpoints de
    `hub_redaccion_router` con `_user` sin usar; `workspaces_router` sin `require_module`;
    `hub_organizaciones_router` acepta `partner_id` del cuerpo sin validar).
  - **NUEVO-9**: `docker-compose.prod.yml` con contraseñas por defecto (`:-govgenai_dev`,
    `:-minioadmin_dev`) en el servicio `app`. El fichero de producción no debería llevar ni un
    `:-` en un secreto.

- **BAJO** — `HubWidgetKey` y los PAT sin caducidad obligatoria (solo revocación); documentación
  que miente sobre el estado de seguridad (`seeds.py:12` dice que el login no verifica contraseña;
  `hub_prompts_catalog_router.py:11` dice que `activity` es «único global», ya falso desde MT.6).

### 3.3 La lección de método

Los cuatro agujeros vivos de aislamiento (`library`, `llm-configs`, `activity-prompts`,
`llm-drafts`) están precisamente **donde el gate de CI no mira**. El paso «Access control gate»
de `ci.yml` cubre una lista fija de routers que no incluye ninguno de los añadidos en REV ni MT, y
el guardarraíl estático de `test_tenant_isolation.py` es también una lista de nombres que se salta
en silencio los ficheros que no encuentra. El patrón bueno ya existe en el propio proyecto
(`tablas_sin_ambito()` recorre el registro de modelos en vez de una lista): **aplicar ese mismo
patrón al inventario de routers** —recorrer `app/routers` + `app/api/v1` con una lista de
exenciones explícita— habría cazado estos cuatro hallazgos sin necesidad de una auditoría.

---

## 4. Separación por organizaciones (multitenencia)

> El diseño existe para que una Diputación pueda desplegar una instancia para varios municipios,
> cada uno con su administrador, sin que ninguno vea los datos de otro. La pregunta es si esa
> promesa se sostiene hoy.

### 4.1 El núcleo: robusto y bien probado

Las dos capas que hacen cumplir la frontera son de calidad **muy alta**, y están correctamente
separadas (una decide *quién ve qué*, la otra *qué fila gana*):

- **`core/auth/tenancy.py`** es fail-closed en los tres casos difíciles: un principal sin
  organizaciones da un `IN ()` vacío (no ve nada) en vez del listado entero —que era el hallazgo
  A2—; `assert_org_access(None)` deniega; un UUID de claim inválido degrada a «no ve nada», no a
  «no filtra». La asimetría «vacío = todas» solo para el superadministrador está fijada por los
  dos lados en los tests.
- **`core/ambito.py`** resuelve la cascada plataforma→organización **campo a campo** (no fila
  entera) y distingue `None` («heredar») de `""` («vaciar»), sin lo cual no se podría vaciar un
  valor heredado desde la pantalla. Usa `or_(... , is_(None))` en vez de `IN (X, None)` porque
  `NULL IN (...)` no traería la fila de plataforma.
- **El guardarraíl MT.1** obliga a las 14 tablas de `HubConfigBase` a declarar su `__ambito__`
  recorriendo el registro de modelos (no una lista), comprueba que la declaración **no se hereda**
  de la clase padre, y exige coherencia entre la etiqueta y el esquema (heredable ⇒ columna
  nullable). MT.7 añade un test que mantiene honesto el inventario de `docs/MULTITENENCIA.md`. Es
  la parte más sólida del bloque.
- **El widget y el chat público** —la superficie más expuesta— están **muy bien cerrados**: la
  credencial de sitio se ata al chatbot de la ruta, el actor anónimo no lleva organizaciones (no
  puede escalar por identidad), y la organización se deriva siempre del chatbot, nunca del cliente.

El núcleo operativo (chatbots, corpus, ingesta, curación, temas, vocabulario, interacciones,
feedback, escenarios, chat y cuotas) está acotado y hay una docena de routers que pasan por la
capa de tenencia, vigilados por `test_tenant_isolation.py`. **Eso es lo que filtraría contenido
entre municipios, y lo hace.**

### 4.2 La superficie: dimensión metida, filtro a medias

El Bloque MT metió el *esquema* (la columna `organizacion_id`) en las tablas antes del piloto —una
decisión correcta: añadir una columna a una tabla casi vacía es gratis, con meses de datos es una
migración con riesgo— pero eso deja una ventana en la que la dimensión existe y no todos los
routers la usan. Hay que separar tres categorías:

**Huecos documentados como fase 2 (correctos, no son fugas hoy):**
- El superadministrador ve todo sin filtrar (MT.8): correcto como *permiso*; falta la *vista*.
- El listado de personas sin filtrar por organización (MT.9): el router de usuarios es hoy solo
  para superadministrador, así que un admin recibe 403 en todo. Falta funcionalidad, no hay fuga.
- Las pantallas de modelos/plantillas/prompts/concesiones/cuotas (MT.10–MT.15).

**Bien cerrado (verificado):**
- MT.3 (`get_model_for_tier` recibe la organización, obligatoria, en los 7 llamadores).
- MT.4 en plantillas de informe (`hub_report_templates` filtra por organización + nivel plataforma).
- MT.5 en la lógica de los PAT (acotan y nunca amplían; las organizaciones del dueño se resuelven
  en cada validación, no se congelan). Con un hueco que salió en la revisión de la PR #237: el
  token acotado de un superadmin conservaba el rol, y lo que mira `is_superadmin` antes que las
  organizaciones lo dejaba pasar a todas. Cerrado en #238: actúa como administrador de esa
  organización.

**Huecos NO documentados (el inventario los presenta como funcionalidad viva):**
- Los routers de `hub_activity_prompts` y `hub_llm_configs` (ya en §3.2 como hallazgos de
  seguridad: son al mismo tiempo el fallo de multitenencia).
- **`hub_workspaces.organizacion_id` no se escribe ni se lee**: `docs/MULTITENENCIA.md` lo declara
  acotado por organización, pero nadie rellena la columna y el acceso real es por propiedad
  (`es_propietario`), que hoy es *más* estrecho —así que no es fuga—, pero el inventario miente y
  ningún test lo caza (MT.7 solo vigila `HubConfigBase`, no las tablas operacionales).
- **MT.5 está inerte en las concesiones**: la columna `organizacion_id` de `HubModuleGrant` existe
  pero `ConcesionCreate` no la expone y el camino de enforcement (`require_module`) no la usa. Es
  coherente con «MT.5 no cambia comportamiento», pero el inventario no lo dice. (La mitad de los
  PAT ya no lo está: `PatCreateRequest` la acepta desde #230.)
- La cola de revisión de scripts de Informes (`scripts_router`) se protege por rol y no por
  pertenencia: un admin de A puede listar, reejecutar, aprobar y rechazar las propuestas de script
  de B, incluido el código y los datos de prueba del otro municipio.

### 4.3 Valoración de robustez por capa

| Capa | Robustez |
|---|---|
| `tenancy.py` / `ambito.py` / guardarraíl MT.1 | **Muy alta** |
| Servicios de resolución (MT.2/MT.3/MT.6, `credenciales_llm`, `config_provider`) | **Alta** |
| Routers de Chatbots / Curación / Temas | **Alta** (SEC.2 + SEC.8.1 con tests HTTP) |
| Routers de Informes (`redaccion/`) | **Media** (propiedad sí, organización no; `hub_workspaces.organizacion_id` muerto) |
| Routers de Plataforma (`llm_configs`, `activity_prompts`) | **Baja** (fuga real, §3.2) |
| Widget / chat público | **Muy alta** |
| `library_router` | **Nula** (sin autenticación, §3.2) |
| Red de tests | **Alta en la capa, media en la superficie** (el guardarraíl de routers es una lista fija que no incluye ningún router REV/MT) |

---

## 5. Aislamiento núcleo/configuración para el desarrollo colaborativo

> `README.md` y `CONTRIBUTING.md` declaran un modelo de un principal (upstream) multiorganización
> y un fork por institución, donde **lo específico de una institución no entra en el principal**.
> La pregunta: ¿está el núcleo suficientemente aislado de la configuración para que eso sea
> viable?

### 5.1 El mecanismo es real y de calidad alta

El proyecto no solo tiene la separación: la tiene escrita, razonada y **testada**. Varias piezas
son el modelo fork/upstream correctamente encarnado en código:

- **Vocabulario del corpus como dato en tabla** (`hub_vocabulary_terms`), con los *ejes* en Enum
  (pocos, estables, añadir uno exige código) y los *términos* como dato (cambian sin tocar
  código). Carga por CSV con `--organizacion-id` obligatorio, idempotente, con `supersede_term`
  para renombrar sin perder historia. Es exactamente lo que necesita el modelo: el corpus y su
  vocabulario se quedan en el fork como dato.
- **Prompts con default-en-código y override-en-BD**, con la cascada resolviendo `template_text`
  y `override_tier` por separado (un municipio puede querer el texto de la plataforma con un
  modelo más caro). El texto por defecto **no se copia** a la BD, así que las mejoras del
  principal llegan al fork; un texto en blanco vuelve al código, así que se puede deshacer desde
  la pantalla sin SQL.
- **Branding en BD** (`hub_themes` en `HubConfigBase`), con un test —`marcaNoViajaEnElRepo.test.ts`—
  que **prohíbe cualquier imagen en `src/assets/` y cualquier import de imagen desde el código**.
  Ese test nació de una regresión real ya corregida (había una excepción en `.gitignore` que hacía
  viajar la marca al repo). Es el guardarraíl exacto que se necesita para el problema de §5.2.
- **Criterios de curación como dato por sitio** (`stale_days`, umbral de contenido pobre, política
  de series), con un test que documenta la misma auditoría que este informe, ya hecha para ese
  módulo.
- **Doble base ORM con inventario exhaustivo** (`test_edge_boundary.py` afirma la igualdad exacta
  del conjunto de tablas de cada base), **`ConfigProvider` usado de verdad** (devuelve DTOs, no
  modelos ORM, para no filtrar el símbolo de config a los módulos), y **SAML/SSO enteramente
  configurable** (cero metadata institucional en el repo, JIT y mapeo de grupos→roles por
  entorno).

### 5.2 Lo que bloquea de facto, y lo que es material de fork

**BLOQUEANTE — la paleta de marca UJI está hardcodeada en el panel y la cascada de temas no la
alcanza.** `frontend/src/index.css` define, con el comentario literal «UJI brand», los tokens
`--primary`, `--sidebar`, `--accent`, `--chart-*` que consumen todas las utilidades del panel. Hay
**dos sistemas de theming disjuntos**: la cascada de temas (`hub_themes`) escribe `--color-*` y
alcanza el widget y el logotipo, pero el cromo del panel resuelve contra los `--*` de `index.css`,
que siguen siendo el turquesa/azul marino de la UJI, sin pantalla que los cambie. Un ayuntamiento
que despliegue el principal tiene un panel con los colores corporativos de la UJI y tendría que
editar `index.css` —la divergencia en código que la gobernanza quiere evitar—. Es más llamativo
porque **el proyecto ya libró y ganó esta batalla para el logotipo**: lo sacó del bundle; los
colores del panel se quedaron. Arreglo: llevar la paleta a la cascada (o a una neutra) y añadir un
test hermano de `marcaNoViajaEnElRepo` que prohíba marca institucional en los tokens de
`index.css`.

**Material de fork que se coló en el principal (severo, no bloqueante):**
- Credencial de desarrollo con el correo personal del autor (`DEV_ADMIN_EMAIL = "fabra@uji.es"` en
  `seeds.py:35`); solo se siembra en `development`, pero todo fork que arranque en local crea un
  superadmin con el correo del mantenedor del upstream. Arreglo: leerlo de entorno con default
  neutro.
- `"uji"` en el `frozenset` de tipos de fuente de spiders (`spider_factory.py:9`), donde además
  sus selectores son un duplicado exacto de `boe`; y un spider de un portal concreto
  (`procedimientos_spider.py`, «procedimientos.uji.es»), que es literalmente «integración con un
  sistema interno que solo esa institución tiene». Los selectores deberían ser dato
  (`hub_web_sites`), no un dict de módulo.
- Prompt de sistema con presunción institucional no sobreescribible («Eres un redactor de informes
  institucionales de una universidad pública», `redactor_de_bloques.py:19`): los otros prompts sí
  son overrideables vía `hub_activity_prompts`; estos dos no están en el catálogo. Un ayuntamiento
  que genere informes recibe texto que le dice al modelo que es una universidad. Arreglo: dos
  entradas más en `ActividadLLM` (el mecanismo ya existe).
- Menor: nombres de clase con `Uji` en un punto de extensión genérico
  (`UjiDualSourceRetrievalStrategy`), textos de ayuda i18n que usan `www.uji.es` como ejemplo
  (visibles al usuario en los tres idiomas), stopwords del anonimizador con sesgo de contexto
  investigador. Todo cosmético o de nomenclatura.

Lo verificado **limpio**: `migrations/`, `scripts/`, `.env.example` y `mcp_server/` (código) tienen
cero ocurrencias institucionales; no hay metadata SAML de la UJI, ni allowlist de dominio de
correo, ni logotipo en el bundle; los seeds del hub son genéricos («Organización Demo»).

### 5.3 La grieta de arquitectura: `core/` importa de `modules/` y de `routers/`

`CONTRIBUTING.md` regula que un módulo no importe de otro módulo, pero **la dirección inversa no
está regulada ni testada**, y `core/` importa de `modules/` en 18 sitios. Dos de ellos son
`core/` importando de `routers/` (`modulos_service.py:32` y `saml/identity_service.py:131`), lo
que invierte la jerarquía por completo: la capa de autenticación depende de la capa HTTP de un
módulo. Para el modelo de gobernanza esto importa: `core/` es la capa que un fork más va a querer
no tocar, y hoy arrastra `modules.agents_hub.database.config_models` y `routers.redaccion`. Además
hay dos cruces entre módulos (`curation → agents_hub` y `curation → redaccion`) que la regla
prohíbe sin que nada lo detecte. **El hueco de tests de frontera más claro** es un test de
dirección de imports: `core/` no importa de `modules/` ni de `routers/`, y los módulos no se
importan entre sí (o se declara `agents_hub` como segunda capa base y se regula explícitamente).

### 5.4 Infraestructura de contribución

**Sólido y presente:** `LICENSE` (AGPL-3.0 íntegra), `DCO`, `.github/workflows/dco.yml`
(ejemplar: verifica PR y push, exige que la firma coincida con el autor), `ci.yml` (ejemplar),
`.env.example` (243 líneas, neutral), `generate_env.sh`, `setup.sh`, y la gobernanza documentada
con la distinción jurídicamente correcta entre lo que la licencia obliga y lo que el proyecto
pide.

**Ausente:**
- **`.github/PULL_REQUEST_TEMPLATE.md`** con la pregunta «¿por qué es generalizable y no material
  de fork?». Es el filtro central de la gobernanza y hoy depende de que el contribuyente haya
  leído el manual. La intervención de mayor rendimiento por menor coste de todo el informe.
- **`SECURITY.md`** — para software de administración pública bajo ENS, sin canal de divulgación
  responsable, es lo primero que echará en falta quien lo audite antes de un pliego.
- **`CODEOWNERS`** (hace exigible la revisión de mantenedor sobre `core/`, `migrations/` y la
  frontera), plantillas de issues, `CODE_OF_CONDUCT.md`, `dependabot.yml`.
- **El §13 de la AGPL no está implementado** (el propio README lo admite): no existe `SOURCE_URL`
  ni enlace al fuente en el pie del panel ni en el widget —«el caso que se olvida», según el
  propio README—. El patrón ya está en uso en el proyecto (`CORPUS_SITE_BASE_URL`: variable de
  entorno, vacío = desactivado); replicarlo.

---

## 6. Plan de acción recomendado (priorizado)

**Bloqueante de despliegue con datos reales — Bloque SEC.9 (nuevo, entre el cursor y D.0):**
1. `library_router`: añadir autenticación al `APIRouter`, derivar la tenencia del token, restringir
   `/push` y `/sign_manifest` a superadmin. Convertir el check de módulos de `test_plat5` de
   docstring a `dependencies` reales.
2. Quitar `api_key` de `HubProviderOut`.
3. `hub_activity_prompts_router` y `hub_llm_configs_router`: aplicar `scope_query_to_orgs` /
   `assert_org_access` y validar `organizacion_id` del cuerpo contra el token (el patrón de
   `hub_themes_router` ya existe).
4. Cifrar en reposo `hub_provider_credentials.api_key`, o restringir el `CHECK` a los métodos que
   no guardan el secreto en la base.
5. **Convertir el gate de aislamiento en un recorrido del árbol de routers** con lista de
   exenciones explícita (patrón `tablas_sin_ambito`), y añadir al gate de CI los routers hoy
   ausentes. Es lo que evita la próxima regresión de esta clase.

**Antes del piloto, coste bajo:**
6. Sacar la paleta UJI de `index.css` a la cascada de temas + test hermano de `marcaNoViajaEnElRepo`.
7. `DEV_ADMIN_EMAIL` por entorno; docstrings de seguridad falsos corregidos (`seeds.py:12`,
   `main.py:3-6`, `hub_prompts_catalog_router.py:11`).
8. `SECURITY.md` + `PULL_REQUEST_TEMPLATE.md` + `CODEOWNERS`.
9. Arreglar el bug del 401 en el panel de anonimización (D2): cambiar un import a la versión Orval
   ya generada.
10. **Decidir la persistencia del mapa de anonimización** si el piloto maneja datos reales de
    ciudadanos por Informes (§2.3). No es un arreglo: es una decisión con consecuencias legales.
11. NUEVO-5 a NUEVO-9 (uploads, cuota anónima, gate del sandbox con `TESTING`, `_user` sin usar,
    contraseñas por defecto del compose de producción).

**Deuda de calidad, intercalable o post-piloto:**
12. Implementar el §13 de la AGPL (`SOURCE_URL` en panel y widget).
13. Test de dirección de imports (`core/` no importa de `modules/`/`routers/`); decidir cablear o
    borrar `modules/automation/` (D1, 1.401 LOC sin consumidor).
14. Higiene: logging estructurado en vez de 157 `print()`, `subprocess` en `to_thread`, fallback
    de `DATABASE_URL` que falle en vez de conectar a ciegas, code-splitting del frontend,
    descomponer `ChatbotsPage.tsx` (1.059 LOC, el nuevo fichero monolítico).

---

## Anexo — Referencias de código citadas

Seguridad: `server/app/routers/library_router.py:21,33,113,171` (sin auth + oráculo de firma),
`server/app/routers/hub_llm_configs_router.py:44,64,229,285` (api_key expuesta + sin tenancy),
`server/app/routers/hub_activity_prompts_router.py:126` (prompt de plataforma escribible),
`server/app/modules/agents_hub/database/config_models.py:183-185` (credencial sin cifrar),
`server/app/routers/redaccion/llm_drafts_router.py:163` (upload sin límite),
`server/app/core/quotas.py:119-124` + `server/app/api/v1/hub_chat.py:310` (cuota anónima muerta),
`server/app/core/sandbox_client.py:518` (gate con `TESTING=1`), `docker-compose.prod.yml:27,31`.
Multitenencia: `server/app/core/auth/tenancy.py:39-99`, `server/app/core/ambito.py:97-189`,
`server/tests/core/test_mt1_ambito.py`, `server/tests/api/test_tenant_isolation.py`,
`docs/MULTITENENCIA.md` (inventario). Aislamiento OSS: `frontend/src/index.css:115,122` (paleta
UJI), `frontend/src/__tests__/marcaNoViajaEnElRepo.test.ts` (guardarraíl de marca),
`server/app/database/seeds.py:35`, `server/app/modules/redaccion/services/redactor_de_bloques.py:19`,
`server/app/core/auth/modulos_service.py:32` + `saml/identity_service.py:131` (core→routers).
Calidad: `server/app/modules/redaccion/services/anonymization/service.py:231-237` (mapa no-op),
`frontend/src/redaccion/hooks/useAnonymizationApi.ts:22` (401), `server/app/main.py:3-6,260-261`.
