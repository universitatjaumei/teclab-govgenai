# Registro de actividad IA

La plataforma sabe todo de las conversaciones que pasan por ella y nada de las que no. Una
organización que además use asistentes de escritorio, agentes de código o integraciones propias no
puede responder «qué IA se usó aquí, para qué y sobre qué datos» sin ir a preguntar a cada
herramienta, una por una, y confiar en que cada una guarde algo.

Este registro es el sitio donde esas herramientas lo declaran. Sirve a la **conservación de
registros del AI Act** (arts. 12 y 26) y al **registro de actividades de tratamiento del RGPD**
(art. 30).

**No es trazado técnico.** El detalle token a token de lo que pasa *dentro* de la plataforma ya lo
cubre la observabilidad interna, y no se reconstruye aquí. Lo que se guarda son metadatos de
gobernanza.

> Bloque REG del `planificacion/Plan_TDD_Fase1.md`. Origen: la reunión con desarrollo del
> 2026-08-31, donde se planteó que la plataforma no podía dar cuenta de la IA que ocurre fuera de
> ella.

---

## 1. La regla que conviene entender antes de pedir un campo nuevo

**Metadatos sí, payloads no.** El contrato del evento **no tiene ningún campo de contenido**, y
rechaza los que no declara (`extra="forbid"`). Mandar el prompt, la respuesta o el documento no lo
registra: **falla con un 422**.

No es una omisión que se pueda corregir por petición. Un registro de cumplimiento que guardara el
contenido sería un segundo sitio donde viven los datos personales de la organización: uno más que
inventariar, uno más que proteger, uno más que borrar cuando alguien ejerza su derecho de
supresión — y creado precisamente por la herramienta que existe para llevar la cuenta de los
riesgos.

`extra="forbid"` rechaza **cualquier** campo no declarado, así que la regla no depende de acertar
una lista de nombres. Lo que sí hay es una lista de los que se mandan de buena fe —`payload`,
`content`, `prompt`, `mensaje`, `texto`, `respuesta`, `input`, `output`…—: ésos reciben un 422 que
explica la regla y señala `payload_hash` en vez del «Extra inputs are not permitted» de rigor,
porque quien lee eso concluye razonablemente que al esquema le falta un campo y pide que se añada.

**Si un caso exige evidencia del contenido**, va su **SHA-256** en `payload_hash`. Un hash permite
demostrar después que un texto concreto es el que se procesó, sin guardar el texto. Se valida en
forma —64 dígitos hexadecimales en minúscula— porque un hash mal formado no sirve para cotejar
nada y es mejor saberlo al registrar que en la auditoría.

---

## 2. El contrato del evento, campo a campo

`POST /api/v1/actividad`, cuerpo `ActividadIAEvent`:

| Campo | Tipo | Obligatorio | Qué es |
|---|---|---|---|
| `ocurrido_en` | `datetime` **con zona horaria** | sí | Cuándo ocurrió el uso, según quien lo declara. Una marca sin zona se rechaza: un instante sin zona no es un instante, y en un registro que se cruza entre organizaciones eso son horas de diferencia sin avisar |
| `actor` | `str` (≤255) | sí | Quién lo usó, en la forma que la herramienta pueda dar. Un identificador interno estable es preferible a un correo: identifica igual y no propaga un dato personal |
| `herramienta` | `str` (≤100) | sí | El producto: `claude-cowork`, `copilot`, `gemini-cli`… |
| `agente` | `str` (≤255) | no | El agente concreto dentro de esa herramienta, si lo hay: `revisor-de-contratos` |
| `finalidad` | `str` (≤500) | sí | Para qué. Es el campo que hace útil el registro en una auditoría: sin él, sólo consta que hubo uso |
| `modelo_usado` | `str` (≤100) | no | El modelo, si se conoce |
| `categorias_datos` | `list[str]` | no (vacía) | Categorías de datos personales tocadas. **Vocabulario abierto**, no un `Enum`: quien registra sabe qué trató, y una lista cerrada en nuestro código haría que un caso legítimo se registrara mal o no se registrara. Pide los códigos a `GET /api/v1/actividad/categorias` — ver §2.bis |
| `payload_hash` | `str` | no | SHA-256 en minúscula, si hace falta evidencia del **contenido** procesado |
| `funcion_sha256` | `str` | no | SHA-256 en minúscula del **programa** que se ejecutó, cuando está registrado en el catálogo como función de origen externo (AUT.3). Es lo que cruza «qué cuadernos existen» con «cuándo corrieron». Campo propio y no `payload_hash`: aquél significa el contenido, y un campo con dos significados deja una auditoría sin poder leerse |

La respuesta es `201` con `{id, registrado_en}`. Se devuelve `registrado_en` y no sólo el `id`
porque es lo que quien integra necesita para conciliar: su reloj y el nuestro no son el mismo, y la
marca que vale en una auditoría es la que pone la plataforma.

**La organización no viaja en el cuerpo.** Se deriva del dueño del token. Si se pudiera elegir, un
token de una organización podría escribir en el registro de otra y el registro dejaría de dar
cuenta de nada. Mandarla llega como **422** y no se ignora en silencio: ignorarla haría creer a
quien integra que la está eligiendo.

---

## 2.bis El catálogo de categorías: se anuncia, no se impone

`categorias_datos` acepta cualquier código, y eso resuelve un problema y crea otro.

**El que resuelve**: quien registra sabe qué datos trató, y una lista cerrada en nuestro código
haría que un caso legítimo se registrara mal o no se registrara.

**El que crea**: si cada herramienta inventa sus códigos —`datos_identificativos`,
`identificativos`, `PII`—, el registro **deja de poder agregarse**, que es exactamente para lo que
existe en una auditoría. Y ningún canal automático lo arregla: ni el esquema MCP ni OpenAPI pueden
transmitir un vocabulario que no existe.

De ahí el catálogo:

```bash
curl -sS https://normativa.uji.es/api/v1/actividad/categorias \
    -H "Authorization: Bearer pat_..."
```

```json
[{"codigo": "datos_identificativos", "nombre": "Datos identificativos",
  "nombre_secundario": null, "vigente": true, "sustituida_por": null}]
```

**El `POST` sigue aceptando cualquier código.** Rechazar uno que no esté en el catálogo
convertiría «esta categoría todavía no está dada de alta» en «este uso de IA no queda
registrado», y perder el registro es peor que tenerlo con una etiqueta imperfecta. Lo que sí se
hace es dejar los códigos sin catalogar **a la vista** en el panel, tal como llegaron: es la única
señal de que al catálogo le falta una entrada, y es así como se cura en vez de podrirse.

**Este endpoint no exige rol ni módulo**, a diferencia de la lectura del registro: saber cómo se
llaman las categorías de tu propia organización no es privilegiado, y exigir el módulo `registro`
dejaría fuera al consumidor principal —el token de máquina que sólo tiene `actividad:write`—. Un
superadministrador tiene que indicar `?organizacion_id=...`, porque en él la lista vacía significa
«todas» y no hay «la suya».

### De dónde salen los códigos, y quién los cambia

Viven en `hub_vocabulary_terms` con el eje `categoria_dades`: la misma tabla que el vocabulario
del corpus, y por la misma razón. Un catálogo de protección de datos necesita exactamente lo que
esa tabla da —`vigent` para retirar una categoría sin borrar el histórico,
`substituit_per_codi` para renombrar dejando la traza, y el par de nombres para las dos lenguas—.

**Las categorías sembradas están pendientes de validación** por quien lleve el registro de
actividades de tratamiento de la organización. Son un punto de partida convencional, con las
categorías del art. 30 del RGPD y `datos_de_categoria_especial` para lo del art. 9 cuando no haga
falta más detalle:

`datos_identificativos` · `datos_de_contacto` · `caracteristicas_personales` ·
`datos_academicos_y_profesionales` · `datos_economicos_y_financieros` ·
`datos_de_trafico_y_conexion` · `datos_de_categoria_especial` · `sin_datos_personales`

El último hace falta poder decirlo: sin él, una lista vacía es ambigua entre «no hubo datos
personales» y «no lo declaré», y en una auditoría son dos cosas distintas.

Cambiarlas es un `UPDATE`, no un despliegue. Con `?incluir_retiradas=true` el catálogo devuelve
también las retiradas con su sustituta, que es lo que hace falta para reetiquetar lo ya registrado.

---

## 3. Mapeo a las convenciones semánticas OTel GenAI

El esquema es **propio y mínimo**, con nombres mapeables a
[OpenTelemetry GenAI](https://opentelemetry.io/docs/specs/semconv/gen-ai/). Adoptar el estándar
entero arrastraría campos de observabilidad —latencias, recuentos de tokens, identificadores de
span— que en un registro de gobernanza no aplican y que nadie rellenaría.

| Nuestro campo | Atributo OTel GenAI | Nota |
|---|---|---|
| `herramienta` | `gen_ai.provider.name` *(aprox.)* | No es exactamente lo mismo: OTel nombra el proveedor del modelo y nosotros el producto que lo usa. Para un registro de gobernanza importa más «Copilot» que «OpenAI» |
| `agente` | `gen_ai.agent.name` | Correspondencia directa |
| `modelo_usado` | `gen_ai.request.model` | Se declara el modelo pedido; `gen_ai.response.model` no se recoge |
| `ocurrido_en` | marca de tiempo del span | En OTel es propiedad del span, no un atributo |
| `actor` | `enduser.id` | Fuera del espacio `gen_ai.*`; es una convención general |
| `finalidad` | — | **Sin equivalente, y a propósito.** OTel describe *qué llamada se hizo*; el AI Act pregunta *para qué*. Es el campo que convierte una traza en un registro de cumplimiento |
| `categorias_datos` | — | Sin equivalente: la categoría de datos personales es del RGPD, no de la observabilidad |
| `payload_hash` | — | OTel tiene `gen_ai.input.messages` / `gen_ai.output.messages` para el contenido, **opt-in**. Aquí el contenido no se recoge nunca; el hash es la alternativa |
| — | `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`, `gen_ai.operation.name`, `gen_ai.conversation.id` | **No se recogen.** Son coste y depuración, no gobernanza |

Si alguna vez hace falta exportar a un sistema OTel, la tabla de arriba es la traducción. El
camino contrario —adoptar `gen_ai.*` como esquema— dejaría `finalidad` y `categorias_datos` como
atributos no estándar, que es exactamente lo que hoy son los dos campos que más valen.

---

## 4. Dar de alta un agente externo

### 4.1 El token

Desde el panel: **Plataforma → Tokens de acceso → Crear token**. Los scopes según lo que vaya a
hacer:

| Scope | Para qué |
|---|---|
| `actividad:write` | registrar usos en este registro |
| `anonimizacion:use` | detectar y sustituir datos personales en un texto |

Los dos los puede emitir tanto un superadministrador como un administrador de organización.
(`chatbots:write` es la excepción del catálogo, y por un motivo concreto: muta un chatbot en
producción in-place. Registrar actividad añade metadatos y no muta nada.)

El token se muestra **una sola vez** y es revocable desde la misma pantalla.

### 4.2 Registrar un uso, por HTTP

```bash
curl -sS -X POST https://normativa.uji.es/api/v1/actividad \
  -H "Authorization: Bearer pat_..." \
  -H "Content-Type: application/json" \
  -d '{
        "ocurrido_en": "2026-09-03T10:30:00Z",
        "actor": "u-7f3a1c",
        "herramienta": "claude-cowork",
        "agente": "revisor-de-contratos",
        "finalidad": "Revisión previa de un pliego de licitación",
        "modelo_usado": "claude-opus-5",
        "categorias_datos": ["datos_identificativos", "datos_de_contacto"]
      }'
```

**La escritura exige un PAT, no una sesión.** Una sesión de navegador con permiso de escritura
aquí permitiría fabricar entradas del registro desde el panel, que es justo lo que un registro de
gobernanza no puede admitir. Un intento con sesión recibe `403 PAT_REQUIRED`.

### 4.2.bis Desde un cuaderno, en tres líneas (AUT.5)

Un cuaderno que se ejecuta fuera de la plataforma —en el equipo de una persona, en un servicio de
cuadernos en la nube— puede registrar su ejecución al terminar **sin instalar nada**: `requests` y
`hashlib` ya están donde hay un cuaderno.

**La URL y el token van como parámetros del cuaderno**, no incrustados. Es la primera celda, y en
los servicios de cuadernos que tienen formulario de parámetros aparece como tal:

```python
GOVGENAI_URL = ""          # p. ej. https://normativa.uji.es
GOVGENAI_PAT = ""          # token con scope actividad:write
ACTOR = ""                 # identificador estable de quien lo ejecuta, opaco
NOMBRE_DEL_CUADERNO = ""   # la ruta de este mismo fichero .ipynb
```

El cuaderno tiene que **nombrarse a sí mismo** porque no hay forma fiable de que lo averigüe: un
cuaderno no conoce su propia ruta —`__file__` no existe ahí— y los servicios de cuadernos la
exponen cada uno a su manera, cuando la exponen.

Y ésta es la última celda, la que registra:

```python
import hashlib, json, requests
from datetime import datetime, timezone

# El hash del propio cuaderno: es lo que lo enlaza con su registro en el catálogo.
with open(NOMBRE_DEL_CUADERNO, "rb") as f:
    huella = hashlib.sha256(f.read()).hexdigest()

requests.post(
    f"{GOVGENAI_URL}/api/v1/actividad",
    headers={"Authorization": f"Bearer {GOVGENAI_PAT}"},
    json={
        "ocurrido_en": datetime.now(timezone.utc).isoformat(),
        "actor": ACTOR,
        "herramienta": "jupyter",
        "finalidad": "Extracción anual de subvenciones nominativas del presupuesto",
        "categorias_datos": ["sin_datos_personales"],
        "funcion_sha256": huella,
    },
    timeout=10,
).raise_for_status()
```

**`funcion_sha256` es lo que cierra el circuito.** El cuaderno calcula su propio hash sin saber
nada de la plataforma —ni identificadores, ni versiones— y ese hash es exactamente el
`code_sha256` que el catálogo guardó al registrarlo como función de origen externo (§AUT.3, ver
[`CATALOGO_FUNCIONES.md`](CATALOGO_FUNCIONES.md)). Con eso, el catálogo dice **qué cuadernos
existen** y el registro dice **cuándo corrieron**.

Si el cuaderno no está registrado, el hash no casa con nada y **no pasa nada**: el uso queda
registrado igual. Eso también es información — consta que se ejecutó algo que no está en el
catálogo, que es lo que las normas de desarrollo ciudadano llaman distribución informal.

**Tres advertencias que ahorran una tarde:**

- **El hash es del fichero guardado, no del que está en memoria.** Si se edita el cuaderno y no
  se guarda antes de ejecutar la última celda, la huella es la de la versión anterior. Guardar y
  volver a ejecutar esa celda basta.
- **`raise_for_status()` está a propósito.** Un registro que falla en silencio es peor que no
  registrar: nadie lo echa en falta hasta la auditoría. Si el token no tiene el scope o la
  categoría va mal escrita, conviene enterarse en la celda.
- **Nada del contenido puede viajar aquí.** El contrato rechaza `payload`, `texto`, `input` y
  compañía con un 422 que lo explica (§1). Si hace falta poder cotejar un contenido concreto, va
  su SHA-256 en `payload_hash`, que es otro campo y significa otra cosa.

Si además el cuaderno manda texto a un modelo externo y el contrato con ese proveedor lo exige,
la anonimización se pide igual, con el mismo token y un scope más (§4.4).

**No hay paquete que instalar, y es una decisión.** Publicar una biblioteca para tres líneas es
más mantenimiento —versionado, compatibilidad, una dependencia más en cada cuaderno— que valor.
Si algún día aparece un segundo consumidor con la misma necesidad, se reconsidera con ese caso
delante.

### 4.3 Registrar un uso, por MCP

Un cliente compatible se conecta al servidor MCP remoto y obtiene las tres herramientas —
`registrar_actividad`, `detectar_pii` y `anonimizar_texto` — sin escribir código HTTP:

```bash
claude mcp add --transport http govgenai https://normativa.uji.es/mcp \
    --header "Authorization: Bearer pat_..."
```

El token viaja en cada petición y no vive en el servidor: ver
[`MCP_SERVER.md`](MCP_SERVER.md) para los dos transportes y por qué no son intercambiables, y
[`DESPLIEGUE_PROTOTIPO_GCP.md`](DESPLIEGUE_PROTOTIPO_GCP.md) §3.septies para el despliegue.

### 4.4 La anonimización, si la herramienta la quiere usar

```bash
curl -sS -X POST https://normativa.uji.es/api/v1/anonimizacion/replace \
  -H "Authorization: Bearer pat_..." \
  -H "Content-Type: application/json" \
  -d '{"text": "Solicitud de Manuela Ferrer, DNI 12345678Z"}'
```

Devuelve `text_anonimizado` y `spans_aplicados`, que describe exactamente lo que se sustituyó en
ese texto. **Ni el texto de entrada ni el resultado se registran**, en ningún sitio: no en la base
y no en el log del servidor, ni a nivel DEBUG. Hay un test con un centinela que lo comprueba,
porque aquí llega por definición el material más sensible que pasa por la plataforma y un
`logger.debug(text)` de una depuración convertiría el log en el archivo de datos personales que el
servicio existe para evitar.

### 4.5 Qué te dice el sistema solo, y qué tienes que leer aquí

Conviene saber qué parte del contrato viaja por el canal y qué parte no, para no buscarla donde
no está.

| | Por MCP | Por HTTP |
|---|---|---|
| Nombres de campo, obligatorios y descripciones | sí, en el esquema de `tools/list` | `openapi.json`, **apagado en producción** por SEC.7 |
| La regla «metadatos sí, payloads no» | sí, en la descripción de la tool | en el mensaje del 422, cuando choques |
| Los códigos de `categorias_datos` | no: pídelos a `/actividad/categorias` | igual |
| Por qué el contrato es así, y el mapeo a OTel | no | no |

Las dos últimas filas son la razón de que este documento exista. Y de que el rechazo del contrato
no diga «Extra inputs are not permitted» sino qué regla se ha tocado y qué hacer en su lugar: sin
eso, la conclusión razonable de quien integra es que al esquema le falta un campo.

---

## 5. Consultar el registro

La lectura es para personas: **Registro IA** en el menú del panel, con rol admin o superadmin, y
acotada a las organizaciones del principal. Filtros por herramienta y rango de fechas —cerrado por
los dos extremos— y exportación a CSV con los mismos filtros.

**La lectura no la abre un PAT**, al contrario que la escritura: darle a una integración capacidad
de leer el registro sería regalarle una ventana a la actividad de toda la organización.

Se concede por el módulo **`registro`**, propio y no dentro de `plataforma`: el registro es dato
operacional de la organización y aquel módulo es configuración de la plataforma —modelos de LLM,
organizaciones, tokens—. Meterlo ahí obligaría a dar todo eso para poder dar el registro.

Las cabeceras del CSV son los **nombres del contrato** y no rótulos traducidos: un fichero que
alguien va a cruzar con otra fuente necesita nombres estables, y las etiquetas legibles son cosa
del panel, que sí sabe en qué idioma está su lector.

---

## 6. Dónde vive cada pieza

| Pieza | Fichero |
|---|---|
| Contrato del evento | `server/app/modules/agents_hub/contracts/actividad.py` |
| Semilla del catálogo de categorías | `server/app/core/actividad_categorias.py` (los términos, en `hub_vocabulary_terms`) |
| Tabla | `hub_actividad_ia` (`operational_models.py`) — **operacional**, vive en el edge |
| Endpoints | `server/app/routers/actividad_router.py` (`Deploy: edge`) |
| Anonimización como servicio | `server/app/routers/anonimizacion_router.py` (`Deploy: edge`) |
| Motor de anonimización | `server/app/modules/redaccion/services/anonymization/` |
| Tools MCP | `mcp_server/tools/actividad.py`, transporte en `mcp_server/http_server.py` |
| Pantalla | `frontend/src/admin/pages/RegistroActividadPage.tsx` |
