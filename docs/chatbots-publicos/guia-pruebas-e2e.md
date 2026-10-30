# Guía de uso y pruebas — Chatbots Públicos

**Gov Gen AI Platform · Módulo 9B**

> Esta guía explica cómo configurar, utilizar y probar el sistema de chatbots
> de principio a fin. No es necesario conocer los detalles técnicos del sistema:
> cada sección explica qué es lo que se hace y por qué.

---

## Cómo está organizada esta guía

El sistema funciona en capas. Antes de poder crear un chatbot que responda
preguntas, hay tres configuraciones previas que deben existir:

```
Proveedor LLM  →  Configuración del modelo  →  Organización  →  Chatbot  →  Documentos  →  Widget
```

1. **Proveedor LLM** — qué servicio de inteligencia artificial se usa (Google Gemini, OpenRouter, Ollama…).
2. **Configuración del modelo** — qué modelo concreto, con qué parámetros y para qué nivel de uso.
3. **Organización** — la entidad propietaria de los chatbots (p. ej. "Universitat Jaume I").
4. **Chatbot** — el asistente virtual, con su comportamiento, idioma y modo de búsqueda configurados.
5. **Documentos** — el conocimiento del que dispone el chatbot (PDFs, páginas web).
6. **Widget** — la interfaz de chat embebida en una web pública.

En una instalación nueva, los pasos 1–3 se hacen una sola vez. Los pasos 4–5
se repiten por cada chatbot nuevo. El paso 6 se prueba cuando el chatbot tiene documentos.

> **Sistema preconfigurado:** Al arrancar por primera vez, el sistema crea automáticamente
> un proveedor Google Gemini, una configuración del modelo `gemini-2.5-flash`,
> un cliente "Cliente Demo" y un chatbot "Chatbot Demo".
> Si solo quieres probar el sistema, puedes saltar directamente a la [Parte 3](#parte-3--ingestión-de-documentos).

---

## Glosario

Antes de empezar, estos son los términos que aparecen a lo largo de la guía:

| Término | Qué es |
|---|---|
| **Proveedor LLM** | Empresa o servicio que ofrece el modelo de inteligencia artificial (Google, OpenRouter, una instancia local de Ollama). |
| **Configuración LLM** | La combinación concreta de proveedor + modelo + parámetros (temperatura, tamaño de respuesta…) que un chatbot utilizará. |
| **Tier** | Nivel de uso de una configuración LLM. Tier 1 = chat con usuarios. Tier 2/3 = tareas internas de análisis. |
| **Organización** | La entidad dueña de los chatbots. Agrupa chatbots y establece valores por defecto para todos ellos. |
| **Chatbot** | El asistente virtual. Tiene su propia base de conocimiento (documentos), modo de búsqueda y prompt de sistema. |
| **Corpus** | El conjunto de documentos que el chatbot conoce. Cuanto mayor, más puede responder. |
| **Chunk** | Fragmento en que se divide un documento para almacenarlo y buscarlo eficientemente. |
| **Retrieval** | La búsqueda de fragmentos relevantes que el chatbot realiza antes de generar una respuesta. |
| **RAG** | Retrieval-Augmented Generation: el chatbot busca fragmentos relevantes y los usa como contexto para responder. |
| **Widget** | El componente visual de chat que se incrusta en una página web pública. |
| **Spider** | Programa que recorre automáticamente páginas web para extraer su contenido como documentos del chatbot. |
| **Ingestión** | El proceso de convertir un documento (PDF o web) en chunks almacenados y listos para la búsqueda. |
| **Token** | Credencial de acceso temporal que demuestra que el usuario ha iniciado sesión. Se usa en llamadas a la API. |

---

## Parte 0 — Antes de empezar

### 0.1 Puesta en marcha del entorno

1. **Abre Docker Desktop** y espera a que el icono de la barra de tareas esté verde.

2. **Arranca los servicios.** Abre una terminal, navega hasta la carpeta raíz del proyecto
   y ejecuta:
   ```
   docker compose up -d
   ```
   La primera vez tarda 2–3 minutos mientras se descargan las imágenes.

3. **Aplica las migraciones de base de datos** (solo la primera vez, o tras actualizar el código):
   ```
   cd server
   uv run alembic upgrade head
   ```

4. **Comprueba que el servidor responde:**
   ```
   curl http://localhost:8000/health
   ```
   Debes ver `{"status": "ok"}`. Si ves un error de conexión, espera 10 segundos y repite.

5. **Abre el panel de administración** en el navegador:
   ```
   http://localhost:5173
   ```

---

### 0.2 Iniciar sesión

El panel de administración requiere autenticación. **Las credenciales no están escritas aquí, y
no es descuido**: este documento se publica, y una contraseña en un fichero versionado es una
contraseña quemada el día que alguien no la cambia.

De dónde salen, según cómo hayas instalado:

| Instalación | Quién crea la cuenta | Dónde está la credencial |
|---|---|---|
| Desarrollo (`ENVIRONMENT=development`) | El sembrado automático del arranque | `DEV_ADMIN_EMAIL` y `DEV_ADMIN_PASSWORD` de tu `.env`. Sin ponerlas, `admin@example.local` y una contraseña por omisión que **sólo vale en local** |
| Cualquier otra | `scripts/setup.sh`, que la pide al instalar | La que tú diste (`SUPERADMIN_EMAIL` / `SUPERADMIN_PASSWORD` en modo no interactivo) |

El sembrado de desarrollo **sólo corre con `ENVIRONMENT=development`**: una instalación de
producción no tiene esa cuenta.

Inicia sesión en `http://localhost:5173/login` (o la ruta de acceso que muestre el panel).

> **Para pruebas con curl:** algunas pruebas de esta guía usan llamadas directas a la API.
> Sustituye `$EMAIL` y `$PASSWORD` por los tuyos y ejecuta en una terminal:
>
> ```bash
> curl -s -X POST http://localhost:8000/api/v1/auth/token/admin \
>   -H "Content-Type: application/json" \
>   -d "{\"email\": \"$EMAIL\", \"password\": \"$PASSWORD\"}"
> ```
>
> La respuesta tendrá el formato `{"access_token": "eyJ...", "token_type": "bearer"}`.
> Copia el valor de `access_token` y guárdalo en la variable `TOKEN` para reutilizarlo:
>
> ```bash
> TOKEN="eyJ..."
> ```
>
> También puedes recuperarlo desde el navegador: abre las herramientas de desarrollo
> (F12), ve a la pestaña **Console** y ejecuta `localStorage.getItem('access_token')`.

---

## Parte 1 — Configuración inicial

Esta parte solo es necesaria la primera vez que se instala el sistema, o cuando
se quiere añadir un nuevo proveedor o modelo de IA.

> Si usas la instalación de desarrollo, el sistema ya tiene creados:
> - Proveedor: **Google AI (Gemini)**
> - Modelo: **Gemini 2.0 Flash** (tier 1, por defecto)
> - Organización: **Cliente Demo**
>
> Puedes saltar directamente a la [Parte 2](#parte-2--gestión-de-chatbots).

---

### 1.1 Proveedores LLM

Un **proveedor** es el servicio externo de inteligencia artificial que procesa las
preguntas. Los tres proveedores preinstalados son:

| ID | Nombre | Cuándo usarlo |
|---|---|---|
| `google` | Google AI (Gemini) | Modelos Gemini de Google. Requiere clave de API de Google AI Studio. |
| `openrouter` | OpenRouter | Acceso a múltiples modelos (GPT-4, Claude, Llama…) desde un único punto. |
| `ollama` | Ollama (Local) | Modelos ejecutados localmente en tu máquina. No requiere clave de API. |

#### Ver los proveedores instalados

```bash
curl -s http://localhost:8000/api/v1/hub/llm-configs/providers \
  -H "Authorization: Bearer $TOKEN"
```

**Qué debes ver:** Una lista con al menos los tres proveedores predefinidos.

#### Añadir una clave de API a un proveedor existente

Para que Google Gemini funcione, el proveedor `google` necesita la clave de API.
La clave se especifica mediante el nombre de la variable de entorno donde está guardada
(no se envía la clave en texto plano):

```bash
curl -s -X PATCH http://localhost:8000/api/v1/hub/llm-configs/providers/google \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"api_key": "GOOGLE_API_KEY"}'
```

Esto indica al sistema que busque la clave en la variable de entorno `GOOGLE_API_KEY`.
Esa variable debe estar definida en el archivo `.env` del proyecto.

#### Añadir un proveedor personalizado

Por ejemplo, para añadir una instancia propia de un servidor OpenAI-compatible:

```bash
curl -s -X POST http://localhost:8000/api/v1/hub/llm-configs/providers \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "id": "mi-servidor-local",
    "name": "Servidor IA interno",
    "provider_type": "openai_compatible",
    "base_url": "http://192.168.1.50:11434/v1",
    "api_key": "MI_API_KEY_INTERNA"
  }'
```

**Qué debes ver:** HTTP 201 con el proveedor creado.

**Casos límite:**
- [ ] Crear un proveedor con un ID que ya existe → HTTP 409 con mensaje "Ya existe un proveedor con este ID".
- [ ] Eliminar un proveedor que tiene modelos configurados → HTTP 409 con mensaje "hay configuraciones usando este proveedor".

---

### 1.2 Configuraciones de modelo LLM

Una **configuración LLM** combina un proveedor con un modelo concreto y sus
parámetros de generación. Un chatbot siempre usa una configuración LLM.

Los parámetros más importantes son:

| Parámetro | Qué controla | Valores típicos |
|---|---|---|
| `model_name` | El modelo concreto a usar | `gemini-2.0-flash`, `gpt-4o`, `llama3.2` |
| `temperature` | Creatividad de las respuestas. 0.0 = muy determinista, 1.0 = muy creativo | 0.1 para chatbots; 0.0 para extracción |
| `top_p` | Controla la diversidad del vocabulario elegido | 1.0 (dejar por defecto) |
| `max_tokens` | Longitud máxima de cada respuesta | 2048–12000 |
| `tier` | Para qué se usa esta configuración: 1 = chat con usuarios, 2/3 = tareas internas | 1 para chatbots |
| `is_default` | Si es la configuración que se usa cuando no se especifica otra | Solo puede haber una por tier |
| `label` | Nombre descriptivo visible en el panel | "Gemini Flash — Chatbot" |

#### Ver las configuraciones existentes

```bash
curl -s http://localhost:8000/api/v1/hub/llm-configs \
  -H "Authorization: Bearer $TOKEN"
```

**Qué debes ver:** La configuración de desarrollo `Gemini 2.5 Flash` aparece como `is_default: true` en tier 1, salvo que ya hubiera otro modelo por defecto: sólo puede haber uno por nivel (#343).

#### Ver los modelos disponibles de un proveedor

Antes de crear una configuración, puedes consultar qué modelos ofrece el proveedor:

```bash
curl -s http://localhost:8000/api/v1/hub/llm-configs/available-models/google \
  -H "Authorization: Bearer $TOKEN"
```

**Qué debes ver:** Lista de modelos Gemini disponibles (p. ej. `gemini-2.5-flash`, `gemini-1.5-pro`).

#### Crear una configuración de modelo

```bash
curl -s -X POST http://localhost:8000/api/v1/hub/llm-configs \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "provider": "google",
    "model_name": "gemini-2.5-flash",
    "temperature": 0.1,
    "max_tokens": 4096,
    "tier": 1,
    "label": "Gemini 2.5 Flash — Chatbot",
    "is_default": false
  }'
```

Anota el `id` devuelto — lo necesitarás al crear o editar un chatbot.

**Qué debes ver:** HTTP 201 con la configuración creada.

#### Probar la conectividad de una configuración

Antes de asignar una configuración a un chatbot, comprueba que el servicio externo responde:

```bash
curl -s -X POST http://localhost:8000/api/v1/hub/llm-configs/{CONFIG_ID}/test \
  -H "Authorization: Bearer $TOKEN"
```

Sustituye `{CONFIG_ID}` por el UUID de la configuración.

**Qué debes ver:**
- `{"ok": true, "latency_ms": 843}` — la IA responde. La latencia está en milisegundos.
- HTTP 502 con mensaje de error si la clave de API es incorrecta o el servicio no está disponible.

**Casos límite:**
- [ ] Crear dos configuraciones con `is_default: true` en el mismo tier → HTTP 409.
- [ ] Intentar eliminar una configuración asignada a un chatbot → HTTP 409 con "hay chatbots usando esta configuración".

---

### 1.3 Organizaciones

Una **organización** es la entidad que utilizará el sistema (p. ej. una universidad,
un ayuntamiento, una empresa). Agrupa varios chatbots bajo una misma entidad
y define los valores por defecto que heredarán esos chatbots.

Los valores por defecto de la organización evitan tener que configurar los mismos
parámetros manualmente en cada chatbot nuevo.

#### Ver las organizaciones existentes

Ve a `http://localhost:5173/admin/clients` o usa la API:

```bash
curl -s http://localhost:8000/api/v1/hub/clients \
  -H "Authorization: Bearer $TOKEN"
```

**Qué debes ver:** La organización "Cliente Demo" preinstalada aparece en la lista con `chatbot_count: 1`.

#### Crear una organización nueva

```bash
curl -s -X POST http://localhost:8000/api/v1/hub/clients \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Universitat Jaume I",
    "partner_id": "partner_dev",
    "default_retrieval_mode": "RAG",
    "default_language_mode": "prefer",
    "default_quality_threshold": 0.6,
    "default_min_retrieval_results": 2,
    "default_reranker_enabled": true
  }'
```

Anota el `id` devuelto — lo necesitarás al crear un chatbot.

Los parámetros `default_*` se explican en detalle en la [Parte 2](#parte-2--gestión-de-chatbots).

**Qué debes ver:** HTTP 201 con la organización creada, `is_active: true` y `chatbot_count: 0`.

#### Editar una organización

```bash
curl -s -X PATCH http://localhost:8000/api/v1/hub/clients/{CLIENT_ID} \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "UJI — Sede electrónica"}'
```

**Qué debes ver:** HTTP 200 con la organización actualizada.

#### Eliminar una organización

Solo se puede eliminar si no tiene chatbots asociados.

```bash
curl -s -X DELETE http://localhost:8000/api/v1/hub/clients/{CLIENT_ID} \
  -H "Authorization: Bearer $TOKEN"
```

**Qué debes ver:** HTTP 204 sin contenido.

**Casos límite:**
- [ ] Eliminar una organización con chatbots → el servidor debería rechazarlo (o eliminar en cascada, según configuración).

---

## Parte 2 — Gestión de chatbots

Un **chatbot** es el asistente virtual. Tiene un nombre, una personalidad
(definida por el prompt de sistema), una base de conocimiento (los documentos
que ha ingestado) y un modo de búsqueda.

### 2.1 Crear un chatbot

1. Ve a `http://localhost:5173/admin/chatbots`.
2. Haz clic en **Nuevo chatbot**.
3. Rellena los campos principales:

| Campo | Qué es | Ejemplo |
|---|---|---|
| **Nombre** | Identificador descriptivo visible en el panel | `Asistente de Normativa UJI` |
| **Organización** | A qué organización pertenece | `Universitat Jaume I` |
| **Configuración LLM** | Qué modelo de IA usará | `Gemini 2.0 Flash` |
| **Prompt de sistema** | Las instrucciones que definen la personalidad y límites del chatbot | Ver ejemplo abajo |
| **Modo de retrieval** | Cómo busca los documentos | `RAG` para la mayoría de casos |

**Ejemplo de prompt de sistema:**
```
Eres el asistente virtual de la Universitat Jaume I. Responde en español
o catalán según el idioma de la pregunta. Basa todas tus respuestas
exclusivamente en los documentos proporcionados. Si no encuentras la
información, di que no dispones de esa información y sugiere contactar
con la administración.
```

4. Guarda.

**Qué debes ver:**
- El chatbot aparece en la lista.
- No hay errores en la consola del navegador.

---

### 2.2 Parámetros de configuración avanzada

Estos parámetros controlan la calidad y el comportamiento de las respuestas.
Se pueden cambiar en cualquier momento desde la pantalla de edición del chatbot.

#### Parámetros de búsqueda (retrieval)

| Parámetro | Qué controla | Por defecto | Cuándo ajustarlo |
|---|---|---|---|
| `retrieval_top_k` | Cuántos fragmentos recupera antes de responder | 8 | Reducir si las respuestas mezclan temas; aumentar si faltan detalles. |
| `min_retrieval_score` | Puntuación mínima de similitud (0–1) para incluir un fragmento | 0.25 | Subir si hay ruido en las respuestas; bajar si hay pocas fuentes. |
| `quality_threshold` | Calidad mínima global de la búsqueda para responder con confianza | 0.6 | Ajustar según la calidad de los documentos. |
| `min_retrieval_results` | Mínimo de fragmentos encontrados antes de declarar que "no hay información" | 2 | Poner a 1 en corpus pequeños. |
| `reranker_enabled` | Activa un segundo paso de clasificación para mejorar la relevancia | `true` | Desactivar solo si la respuesta es lenta y la calidad ya es buena. |

#### Modo de retrieval

| Modo | Cuándo usarlo |
|---|---|
| `RAG` | Corpus grandes con muchos documentos. Respuestas rápidas y citadas. |
| `MD_LONG_CONTEXT` | Corpus pequeños o cuando la respuesta necesita integrar información de muchos documentos a la vez. Más lento. |
| `MD_AGENT_SELECTOR` | El chatbot elige automáticamente la mejor estrategia. Adecuado cuando el corpus mezcla tipos de contenido muy distintos. |

> **Nota:** Solo se puede usar **Regenerar chunks** (sección 3.2) cuando el modo es `RAG`.
> Para los otros modos, usa **Recalcular corpus** (sección 3.3).

#### Idioma

| Parámetro | Valores | Qué hace |
|---|---|---|
| `language_mode` | `prefer` | Intenta responder en el idioma de la pregunta. |
| `language_mode` | `force` | Siempre responde en el idioma del corpus, independientemente del idioma de la pregunta. |

#### Prueba: cambiar la sensibilidad de búsqueda

1. Edita el chatbot `Chatbot Demo`.
2. Cambia `quality_threshold` a `0.4` y `min_retrieval_results` a `1`.
3. Guarda.
4. Abre el widget y haz una pregunta relacionada con los documentos.

**Qué debes ver:** El chatbot responde incluso con fragmentos de menor calidad.
Restaura los valores originales (`0.6` / `2`) cuando termines la prueba.

---

### 2.3 Ver estadísticas del corpus

Las estadísticas muestran cuánto conocimiento tiene el chatbot y si el modo
de retrieval elegido es el más adecuado.

1. Ve a `http://localhost:5173/admin/chatbots`.
2. Haz clic en el icono de estadísticas del chatbot (o botón **Corpus**).

**Qué debes ver:**

| Campo | Qué indica |
|---|---|
| Total de documentos | Número de PDFs/páginas web ingestadas. |
| Total de tokens | Tamaño total del corpus en tokens (unidades de texto que el LLM procesa). |
| Por idioma | Distribución de documentos por idioma. |
| Modo recomendado | El sistema sugiere RAG o MD_LONG_CONTEXT según el tamaño del corpus. |
| Razón | Explicación en lenguaje natural de la recomendación. |

> **Regla práctica:** si el corpus supera los 100.000 tokens, RAG es más eficiente;
> por debajo de ese umbral, MD_LONG_CONTEXT puede dar respuestas más completas.

---

### 2.4 Chatbot router (delegación entre chatbots)

Un **chatbot router** no responde directamente, sino que decide a cuál de
sus chatbots hijos derivar cada pregunta. Es útil cuando hay chatbots
especializados (normativa, trámites, RRHH…) y se quiere un único punto de entrada.

1. Crea un chatbot nuevo con tipo `router` (o cambia el campo `kind` a `router`).
2. En la lista de chatbots, abre el chatbot router y accede a la sección **Hijos**.
3. Haz clic en **Añadir hijo** y selecciona el chatbot `Chatbot Demo`.
4. Para ver los hijos asignados:
   ```bash
   curl -s http://localhost:8000/api/v1/hub/chatbots/{CHATBOT_ROUTER_ID}/children \
     -H "Authorization: Bearer $TOKEN"
   ```
5. Para eliminar un hijo:
   ```bash
   curl -s -X DELETE \
     http://localhost:8000/api/v1/hub/chatbots/{CHATBOT_ROUTER_ID}/children/{CHILD_ID} \
     -H "Authorization: Bearer $TOKEN"
   ```

**Qué debes ver:**
- El chatbot router muestra su lista de hijos correctamente.
- Añadir y quitar hijos funciona sin recargar la página.

---

### 2.5 Eliminar un chatbot

1. Ve a la lista de chatbots.
2. Haz clic en **Eliminar** en el chatbot que quieres borrar.
3. Confirma el diálogo de confirmación.

**Qué debes ver:** El chatbot desaparece de la lista. Los documentos ingestados
previamente permanecen en la base de datos hasta que se borren explícitamente
(ver sección 3.5).

---

## Parte 3 — Ingestión de documentos

La **ingestión** es el proceso de convertir un documento en fragmentos de texto
(chunks) que el chatbot puede buscar. Un chatbot sin documentos solo puede
responder con su conocimiento general, no con información específica de tu organización.

---

### 3.1 Subir un PDF

1. Ve a `http://localhost:5173/admin/documents`.
2. Selecciona el chatbot de destino.
3. Haz clic en **Subir documento** y elige un PDF (máximo 10 MB).
4. Opcionalmente indica el idioma del documento y una URL canónica de referencia.

**Qué debes ver:**
- Aparece un indicador de progreso.
- Tras unos segundos, el documento aparece en la lista con estado `processed`.
- Las estadísticas del corpus muestran más chunks y tokens.

**Casos límite:**
- [ ] Subir un archivo que no sea PDF → debe rechazarse con un mensaje de error.
- [ ] Subir un PDF de más de 10 MB → debe rechazarse con error de tamaño.

---

### 3.2 Regenerar chunks (solo modo RAG)

Cuando se cambian los parámetros de fragmentación (chunk size, solapamiento…),
los documentos existentes deben procesarse de nuevo.

> Este botón solo está disponible si el chatbot está en modo `RAG`.

1. Ve a la pantalla del chatbot.
2. Haz clic en **Regenerar chunks**.

**Qué debes ver:** Mensaje de confirmación con el número de documentos procesados
y chunks creados. El número puede variar si se cambiaron parámetros.

---

### 3.3 Recalcular corpus

A diferencia de "Regenerar chunks", esta opción funciona con todos los modos
de retrieval y recalcula el corpus completo.

```bash
curl -s -X POST \
  http://localhost:8000/api/v1/hub/chatbots/{CHATBOT_ID}/recalculate-corpus \
  -H "Authorization: Bearer $TOKEN"
```

**Qué debes ver:** Respuesta con `documents_queued` y `chunks_deleted` indicando
cuántos documentos se han puesto en cola para reprocesarse.

---

### 3.4 Fuentes web monitorizadas (spiders)

Un **spider** es un programa que recorre páginas web automáticamente y extrae
su contenido como documentos del chatbot. Es la forma de mantener el corpus
actualizado con información de webs institucionales sin tener que subir PDFs manualmente.

#### Tipos de spider disponibles

| Tipo (`spider_type`) | Para qué sirve |
|---|---|
| `generic` | Cualquier web pública. Recorre páginas en amplitud hasta la profundidad indicada. |
| `uji` | Normativa publicada en la web de la UJI. Extrae título, fecha y texto oficial. |
| `boe` | Normativa del Boletín Oficial del Estado. Misma estructura que `uji`. |
| `dogv` | Normativa del Diari Oficial de la Generalitat Valenciana. |
| `procedimientos` | Fichas de procedimientos administrativos de procedimientos.uji.es. Extrae código, unidad responsable, plazo y documentación requerida. |

> **Para los siguientes ejemplos necesitas:** el UUID del chatbot (`{CHATBOT_ID}`)
> y el token de acceso (`$TOKEN`). Ver [sección 0.2](#02-iniciar-sesión).

#### Crear una fuente web genérica

El spider `generic` sigue los enlaces de la URL raíz hasta la profundidad configurada.

```bash
curl -s -X POST http://localhost:8000/api/v1/hub/ingestion/{CHATBOT_ID}/sources \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://www.uji.es/serveis/",
    "label": "Servicios UJI",
    "spider_type": "generic",
    "check_interval_hours": 24,
    "language": "es",
    "config_json": {
      "crawl_depth": 2,
      "max_pages": 20,
      "url_regex_filter": "/serveis/"
    }
  }'
```

| Parámetro en `config_json` | Qué hace | Por defecto |
|---|---|---|
| `crawl_depth` | Niveles de profundidad desde la URL inicial. 1 = solo la página inicial y sus enlaces directos. | 1 |
| `max_pages` | Límite de páginas a visitar. El spider se detiene al alcanzarlo. | 50 |
| `url_regex_filter` | Expresión regular: solo sigue los enlaces que cumplan este patrón. | Sin filtro |

#### Crear una fuente de normativa

```bash
curl -s -X POST http://localhost:8000/api/v1/hub/ingestion/{CHATBOT_ID}/sources \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://www.uji.es/normativa/",
    "label": "Normativa UJI",
    "spider_type": "uji",
    "check_interval_hours": 168,
    "language": "es",
    "config_json": {}
  }'
```

Los documentos ingestados incluirán metadatos de `fecha_publicacion` y `numero_norma`
(si el título tiene el formato `N/AAAA`).

#### Crear una fuente de procedimientos

```bash
curl -s -X POST http://localhost:8000/api/v1/hub/ingestion/{CHATBOT_ID}/sources \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://procedimientos.uji.es/",
    "label": "Procedimientos UJI",
    "spider_type": "procedimientos",
    "check_interval_hours": 168,
    "language": "es",
    "config_json": {}
  }'
```

Los documentos incluirán código, unidad responsable, plazo y documentación requerida.

#### Listar las fuentes registradas

```bash
curl -s http://localhost:8000/api/v1/hub/ingestion/{CHATBOT_ID}/sources \
  -H "Authorization: Bearer $TOKEN"
```

Anota el `id` de la fuente que quieres comprobar (`{SOURCE_ID}`).

#### Lanzar una comprobación inmediata

Por defecto, el spider se ejecuta automáticamente según el intervalo configurado
(`check_interval_hours`). Para forzar una ejecución ahora mismo:

```bash
curl -s -X POST \
  http://localhost:8000/api/v1/hub/ingestion/{CHATBOT_ID}/sources/{SOURCE_ID}/check \
  -H "Authorization: Bearer $TOKEN"
```

**Qué debes ver:** HTTP 202 con `{"message": "Comprobación iniciada."}`.
La ejecución ocurre en segundo plano. En los logs del servidor
(`docker compose logs -f server`) verás las URLs visitadas.

#### Verificar los documentos ingestados

Espera 10–30 segundos y consulta los documentos del chatbot:

```bash
curl -s \
  "http://localhost:8000/api/v1/hub/ingestion/{CHATBOT_ID}/documents" \
  -H "Authorization: Bearer $TOKEN"
```

**Qué debes ver:**
- Documentos con `source_kind: "web"`.
- El campo `canonical_url` apunta a la URL rastreada.
- `token_count > 0`.

Para ver el contenido extraído de un documento:

```bash
curl -s \
  "http://localhost:8000/api/v1/hub/ingestion/{CHATBOT_ID}/documents/{DOC_ID}" \
  -H "Authorization: Bearer $TOKEN"
```

El campo `markdown_content` muestra el texto extraído (no HTML crudo).

#### Pausar y reactivar una fuente

Una fuente pausada no se ejecuta en el ciclo automático ni acepta comprobaciones manuales.

```bash
# Pausar
curl -s -X PATCH \
  http://localhost:8000/api/v1/hub/ingestion/{CHATBOT_ID}/sources/{SOURCE_ID} \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"status": "paused"}'

# Reactivar
curl -s -X PATCH \
  http://localhost:8000/api/v1/hub/ingestion/{CHATBOT_ID}/sources/{SOURCE_ID} \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"status": "active"}'
```

#### Casos límite de spiders

- [ ] **URL no accesible** — configurar una URL inexistente. El job queda en `failed`, el servidor no se bloquea.
- [ ] **`max_pages` alcanzado** — con `max_pages: 2` en una web grande, el resultado indica `pages_skipped > 0`.
- [ ] **Filtro regex sin coincidencias** — si `url_regex_filter` no coincide con ningún enlace, solo se ingesta la página raíz.
- [ ] **Fuente pausada** — intentar `/check` sobre una fuente pausada → HTTP 409 "La fuente está pausada."
- [ ] **URL duplicada** — registrar la misma URL dos veces → HTTP 409 "Esta URL ya está registrada para este chatbot."

---

### 3.5 Eliminar documentos y limpiar la colección

#### Eliminar un documento individual

Borra el documento y todos sus chunks. Los jobs de ingestión asociados no se eliminan.

```bash
curl -s -X DELETE \
  "http://localhost:8000/api/v1/hub/ingestion/{CHATBOT_ID}/documents/{DOC_ID}" \
  -H "Authorization: Bearer $TOKEN"
```

**Qué debes ver:** HTTP 200 con `{"message": "Documento eliminado."}`.
Las estadísticas del corpus se actualizan al recargar.

#### Eliminar un job de ingestión

Solo se pueden eliminar jobs en estado `done` o `failed` (no los que están en curso).

```bash
curl -s -X DELETE \
  "http://localhost:8000/api/v1/hub/ingestion/{CHATBOT_ID}/jobs/{JOB_ID}" \
  -H "Authorization: Bearer $TOKEN"
```

**Qué debes ver:** HTTP 200. Si el job tenía un PDF adjunto en el almacenamiento, también se elimina el archivo.

**Casos límite:**
- [ ] Intentar eliminar un job en estado `pending` o `running` → HTTP 409 "No se puede eliminar un job en curso."

#### Vaciar toda la colección del chatbot

Esta operación elimina **todos** los documentos, chunks y jobs del chatbot.
Es irreversible. Úsala para empezar desde cero.

```bash
curl -s -X DELETE \
  "http://localhost:8000/api/v1/hub/ingestion/{CHATBOT_ID}/chunks" \
  -H "Authorization: Bearer $TOKEN"
```

**Qué debes ver:** HTTP 200 con `documents_deleted` y `jobs_deleted`.

---

## Parte 4 — Widget de chat

> Para estas pruebas, necesitas incrustar el widget en una página de prueba.
> Usa la plantilla del apéndice al final de esta guía o abre directamente
> la página de previsualización del chatbot en el panel admin.

---

### 4.1 Apertura y cierre

1. Carga la página con el widget.
2. El widget debe abrirse automáticamente (estado inicial `open=true`).
3. Haz clic en el botón ✕ (cerrar).

**Qué debes ver:**
- El widget se colapsa a la burbuja flotante 💬.
- Al hacer clic en 💬, el widget se reabre con el historial de conversación conservado.

---

### 4.2 Consulta básica

1. Escribe una pregunta relacionada con el contenido de los documentos ingestados.
2. Pulsa **Enter** o el botón de envío.

**Qué debes ver:**
- El mensaje del usuario aparece en la conversación.
- Aparece un indicador de actividad ("Detectando idioma…", "Buscando en la base de conocimiento…", "Generando respuesta…").
- La respuesta del asistente se va mostrando en tiempo real, palabra a palabra (streaming).
- Al completarse, el indicador desaparece.
- Debajo de la respuesta aparecen **píldoras de fuentes** con el título del documento y enlace.
- Aparecen las **estrellas de valoración** (1–5) debajo de la respuesta.

---

### 4.3 Fuentes citadas

1. Haz clic en una píldora de fuente que aparece bajo la respuesta.

**Qué debes ver:** El documento de origen se abre en una nueva pestaña
(o muestra 404 si la URL es de prueba).

---

### 4.4 Pregunta sin respuesta (fallback)

1. Haz una pregunta completamente ajena al contenido ingestado
   (p. ej. "¿Cuál es la capital de Australia?").

**Qué debes ver:**
- El asistente responde con un mensaje de fallback (no inventa información del corpus).
- No aparecen fuentes citadas, o las que aparecen tienen puntuación muy baja.
- No aparece aviso de traducción.

---

### 4.5 Múltiples turnos

1. Haz 3 preguntas consecutivas esperando la respuesta completa de cada una.

**Qué debes ver:**
- El historial de la conversación es visible en el widget.
- Cada respuesta tiene sus propias estrellas de valoración.

---

### 4.6 Envío durante streaming (botón bloqueado)

1. Envía una pregunta.
2. Mientras el asistente está respondiendo, intenta enviar otra pregunta.

**Qué debes ver:**
- El campo de texto y el botón de envío están **deshabilitados** durante el streaming.
- No se generan mensajes duplicados.

---

### 4.7 Enter y botón de envío

1. Escribe una pregunta y pulsa **Enter**.
2. Escribe otra y haz clic en el botón de envío.

**Qué debes ver:** Ambas formas de envío funcionan de forma idéntica.

---

## Parte 5 — Idioma y traducción

### 5.1 Consulta en el idioma del corpus

1. Si los documentos están en español, haz una pregunta en español.

**Qué debes ver:** Respuesta en español sin ningún aviso de traducción.

---

### 5.2 Consulta en idioma diferente al corpus

1. Si el corpus está en español, haz la pregunta en catalán o inglés.

**Qué debes ver:**
- Aparece un aviso en amarillo indicando que la pregunta se detectó en un idioma
  diferente al del corpus.
- La respuesta se genera en el idioma configurado en `language_mode`
  (`prefer` = responde en el idioma de la pregunta; `force` = responde en el idioma del corpus).

---

### 5.3 Cambio de idioma dinámico

El widget acepta instrucciones de la página que lo contiene vía `postMessage`.
Prueba el cambio de idioma desde la consola del navegador (F12 → Console):

```javascript
window.postMessage({ type: 'govgenai:setLang', lang: 'ca' }, '*')
```

**Qué debes ver:** Los textos del interfaz del widget cambian al catalán
(placeholder del campo de texto, botones, mensajes de estado).

---

## Parte 6 — Feedback

### 6.1 Valoración con estrellas

1. Tras recibir una respuesta, haz clic en la estrella 4.

**Qué debes ver:**
- Las estrellas 1–4 aparecen rellenas (★), la 5 vacía (☆).

2. En el panel admin (`http://localhost:5173/admin` → sección de interacciones),
   busca la conversación.

**Qué debes ver:** La interacción tiene `feedback_score = 4`.

---

### 6.2 Cambiar la valoración

1. Con la misma respuesta, haz clic ahora en la estrella 2.

**Qué debes ver:**
- La UI refleja inmediatamente la nueva valoración (2 estrellas rellenas).
- En la base de datos se registra el último valor enviado.

---

## Parte 7 — Modos de retrieval en profundidad

Para cada prueba, edita el chatbot y cambia el modo antes de consultar.

### 7.1 RAG (Retrieval-Augmented Generation)

- **Cuándo usarlo:** corpus grandes, respuestas rápidas, cuando se necesitan fuentes citadas.
- **Configuración:** `retrieval_mode = RAG`, `retrieval_top_k = 5`.

1. Haz una consulta específica sobre un fragmento del corpus.

**Qué debes ver:** Respuesta precisa con 1–5 fuentes citadas del documento relevante.

---

### 7.2 Contexto largo (MD_LONG_CONTEXT)

- **Cuándo usarlo:** corpus pequeños o preguntas que requieren integrar información de muchos documentos a la vez.
- **Advertencia:** más lento y consume más tokens.

1. Cambia a `retrieval_mode = MD_LONG_CONTEXT`.
2. Haz la misma consulta que en 7.1.

**Qué debes ver:**
- Respuesta potencialmente más completa (el chatbot ve más contexto).
- El streaming puede tardar más tiempo.
- Las fuentes citadas corresponden a documentos completos, no fragmentos.

---

### 7.3 Selector de agentes (MD_AGENT_SELECTOR)

- **Cuándo usarlo:** cuando el corpus mezcla tipos de contenido muy distintos
  (normativa, procedimientos, noticias…) y el chatbot debe elegir la estrategia óptima.

1. Cambia a `retrieval_mode = MD_AGENT_SELECTOR`.
2. Haz dos preguntas de naturaleza distinta (una factual concreta, una de síntesis amplia).

**Qué debes ver:** El chatbot adapta su estrategia de búsqueda según el tipo de pregunta.

---

### 7.4 Comparativa entre modos

Usa la misma pregunta en los tres modos y compara:

- [ ] ¿Cuál es más precisa?
- [ ] ¿Cuál es más rápida?
- [ ] ¿Las fuentes citadas son relevantes en cada caso?
- [ ] ¿Cuál consume más tokens (visible en los logs del servidor)?

---

## Parte 8 — Casos límite y errores

### 8.1 Mensaje vacío

1. Haz clic en el botón de envío con el campo de texto vacío.

**Qué debes ver:** El botón está deshabilitado. No se envía ningún mensaje.

---

### 8.2 Chatbot sin documentos

1. Crea un chatbot nuevo sin ingestar ningún documento.
2. Abre el widget y haz una pregunta.

**Qué debes ver:**
- Respuesta de fallback (no hay información disponible).
- Sin fuentes citadas.
- Sin errores en la consola del navegador ni en los logs del servidor.

---

### 8.3 Error de red simulado

1. Para el servidor con `docker compose stop server`.
2. Intenta enviar un mensaje desde el widget.

**Qué debes ver:**
- El widget muestra un mensaje de error o el streaming se detiene.
- No se queda en estado "cargando" indefinidamente.
- El campo de texto vuelve a ser editable cuando el error es visible.

3. Reinicia el servidor con `docker compose start server`.

---

### 8.4 Pregunta muy larga

1. Pega un texto de más de 2.000 caracteres en el campo de texto.

**Qué debes ver:**
- El mensaje se envía (el límite del servidor es 10.000 caracteres).
- O el campo rechaza el texto si el frontend tiene validación de longitud máxima.
- En ningún caso el servidor devuelve un error 500.

---

## Parte 9 — Panel admin: revisión de interacciones

Tras completar las pruebas de las partes 4–6:

1. Ve a `http://localhost:5173/admin` → sección de **Interacciones** o **Feedback**.
2. Verifica que aparecen las conversaciones realizadas durante las pruebas.
3. Comprueba que las valoraciones de estrellas se muestran correctamente.
4. Filtra por chatbot para ver solo las interacciones del chatbot de prueba.

**Qué debes ver:**
- Cada pregunta y respuesta registrada.
- El `feedback_score` de las interacciones valoradas.
- Los metadatos de idioma detectado.

---

## Checklist de cierre

Antes de dar por válidas las pruebas, verifica cada punto:

**Configuración inicial**
- [ ] Al menos un proveedor LLM configurado
- [ ] Al menos una configuración LLM con test de conectividad exitoso (`ok: true`)
- [ ] Al menos una organización creada

**Chatbots**
- [ ] CRUD de chatbots funciona sin errores
- [ ] Los parámetros editados persisten al reabrir el chatbot

**Ingestión**
- [ ] Al menos un PDF ingestado con estado `processed`
- [ ] Al menos una fuente web (spider genérico) activa
- [ ] La comprobación manual de spider devuelve 202 y genera documentos con `source_kind = web`
- [ ] La eliminación individual de un documento actualiza las estadísticas

**Widget**
- [ ] El widget se abre, cierra y reabre conservando el historial
- [ ] El streaming funciona (tokens visibles en tiempo real)
- [ ] Las fuentes citadas aparecen y son clicables
- [ ] La valoración de estrellas se registra correctamente en la base de datos
- [ ] El fallback se activa cuando no hay evidencias suficientes
- [ ] El aviso de traducción aparece solo cuando el idioma de la pregunta difiere del corpus
- [ ] El botón de envío se deshabilita durante el streaming

**Robustez**
- [ ] El chatbot sin documentos responde con fallback, sin errores 500
- [ ] La fuente pausada rechaza `/check` con 409
- [ ] El servidor no tiene errores 500 en los logs durante todas las pruebas

---

## Apéndice — Página HTML mínima para probar el widget

Guarda el siguiente código como `test-widget.html`, ábrelo con un navegador
y sustituye `REEMPLAZA-CON-UUID-DEL-CHATBOT` por el UUID del chatbot a probar.

```html
<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <title>Prueba del widget</title>
  <style>
    #govgenai-widget {
      position: fixed;
      bottom: 1.5rem;
      right: 1.5rem;
      width: 380px;
      height: 540px;
      border: 1px solid #e2e8f0;
      border-radius: 12px;
      background: #fff;
      box-shadow: 0 8px 32px rgba(0,0,0,0.12);
      overflow: hidden;
    }
  </style>
</head>
<body>
  <h1>Página de prueba</h1>
  <p>El widget aparece en la esquina inferior derecha.</p>

  <div
    id="govgenai-widget"
    data-chatbot-id="REEMPLAZA-CON-UUID-DEL-CHATBOT"
    data-api-url="http://localhost:8000/api/v1"
    data-lang="es"
  ></div>

  <script type="module" src="http://localhost:5173/src/widget/main.tsx"></script>
</body>
</html>
```

> En producción, sustituye el `<script>` por el bundle compilado (`widget.js`)
> y `data-api-url` por la URL real del servidor.
