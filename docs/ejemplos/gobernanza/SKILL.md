---
name: gobernanza-govgenai
description: >-
  Usar al escribir, compartir o ejecutar código en una organización que despliega Gov Gen AI
  Platform. Fija el ciclo de la Instrucció 02/2026: consultar las reglas antes de escribir,
  auditar antes de compartir, anonimizar si el contrato con el proveedor lo exige, y registrar
  el uso al terminar. Necesita el servidor MCP `govgenai` conectado.
---

# Gobernanza del código que escribes

Esta organización tiene un registro de lo que la IA hace y un catálogo de lo que se comparte. Las
herramientas para cumplirlo están a un tool call de distancia; lo que falta casi siempre es que
alguien se acuerde. Eso es lo que fija esta skill.

**El cumplimiento por MCP es voluntario, y conviene decirlo primero.** Un agente puede no llamar a
ninguna de estas herramientas y nada se lo impide. El modelo de las normas de desarrollo ciudadano
asume exactamente eso: la responsabilidad es de quien escribe y la revisión es posterior. Lo que
la plataforma puede hacer —y hace— es que cumplir sea **el camino fácil**. La imposición sólo
existe donde la ejecución ocurre dentro, que es el catálogo de funciones.

## El ciclo

### 1. Antes de escribir código destinado a compartirse

Llama a **`reglas_de_auditoria`**. Devuelve la caja de herramientas real: qué módulos están en la
lista blanca, qué patrones son críticos y con qué versión del auditor. Escribir primero y
descubrir después que `csv` no está permitido cuesta una reescritura entera.

**Cada módulo viene con su ficha, y no es adorno**, en `modulos`:

- **`instala`** — con qué nombre se instala, que no siempre es el que se importa: `import fitz`
  sale de `pymupdf` y `import docx` de `python-docx`. Es `null` en la biblioteca estándar.
- **`para`** — para qué sirve. Léelo antes de elegir: para PDF hay **dos** lectores y **no son
  alternativas**. `pdfplumber` recupera mejor las tablas con líneas y `fitz` llega a la
  maquetación; leer con los dos y componer las dos lecturas es lo que más información deja.
- **`copyleft`** — si arrastra copyleft fuerte. Hoy sólo `fitz`, que es AGPL-3.0. A la
  plataforma no le afecta, **al código que escribes fuera sí**: si acaba en un producto que no
  es AGPL, la pregunta aparece allí. Si el documento se deja leer con `pdfplumber`, no se
  plantea. Dilo si eliges `fitz` teniendo alternativa, en vez de decidirlo por dentro.

No hace falta para código de usar y tirar que no va a salir de tu máquina.

### 2. Antes de compartirlo

Llama a **`auditar_codigo`** con el script entero y **adjunta el resultado** a lo que entregues: el
nivel de riesgo, cada hallazgo con su línea y el `code_sha256`.

- **CRITICAL** no se comparte. Se corrige y se vuelve a auditar.
- **WARNING** sí se comparte, con el hallazgo a la vista: quien revise decide.
- Un módulo fuera de la lista blanca suele ser un hueco de la lista y no un defecto del código;
  dilo así en vez de reescribir para esquivarlo.

La auditoría es **estática**: no ejecuta nada. Ejecutar es el sandbox, y eso vive dentro de la
plataforma.

### 3. Si el texto va a un modelo externo

**Sólo si el contrato con el proveedor del agente lo exige**, pasa el texto por
**`anonimizar_texto`** antes de enviarlo, y usa `detectar_pii` si sólo quieres saber qué hay.

Esto **no lo decide la skill**: depende de la sensibilidad del dato y de lo que la organización
haya firmado con el proveedor. Si no lo sabes, pregunta a quien administre la plataforma en vez de
suponer en cualquiera de las dos direcciones.

Ni el texto de entrada ni el resultado se guardan en ninguna parte, tampoco en el log.

### 4. Al terminar

Llama a **`registrar_actividad`** con qué hiciste, para qué y con qué categorías de datos.

- Los códigos de categoría **se piden** a `GET /api/v1/actividad/categorias`. El campo acepta
  cualquiera, pero si cada herramienta inventa los suyos el registro deja de poder agregarse, que
  es para lo que existe.
- **Nunca el contenido.** El contrato no tiene ningún campo de texto y rechaza los que no declara:
  mandar el prompt no lo registra, falla. Si hace falta prueba de un contenido, va su SHA-256 en
  `payload_hash`.
- Si el programa que ejecutaste está registrado en el catálogo como función de origen externo,
  manda su hash en `funcion_sha256`: es lo que cruza «qué cuadernos existen» con «cuándo
  corrieron».

## Lo que esta skill no hace

- **No ejecuta nada en la plataforma.** Auditar no es ejecutar.
- **No aprueba.** No hay aprobación previa en el nivel 2, a propósito: la revisión es posterior y
  la hace una persona distinta de quien escribió.
- **No decide si hay que anonimizar.** Eso sale del contrato con el proveedor, no de aquí.

## Instalación

1. Emite un PAT desde el panel: **Plataforma → Tokens de acceso → Crear token**, con los scopes
   `verificaciones:use`, `anonimizacion:use` y `actividad:write`. Se muestra una sola vez.
2. Copia `.mcp.json` de esta misma carpeta a la raíz de tu proyecto y exporta el token:

   ```bash
   export GOVGENAI_PAT=pat_xxxxxxxx_yyyyyyyyyyyy
   ```

3. Copia esta carpeta a `.claude/skills/gobernanza-govgenai/` del proyecto, o a
   `~/.claude/skills/` si la quieres en todos.

Comprueba con `claude mcp list` y pidiendo `reglas_de_auditoria`: si responde con la lista de
módulos, está conectado.

## Sesión de ejemplo

```
> Escribe un script que cruce el fichero de gastos con el de proveedores y lo suba al
  repositorio del servicio.

[reglas_de_auditoria]  → 17 módulos permitidos con su ficha, 6 reglas,
                         version_auditor 3f9c…

  `csv` no está en la lista blanca, así que lo hago con `pandas`, que sí está.

  … escribe el script …

[auditar_codigo]       → SAFE, 0 hallazgos, code_sha256 9130c489…

  Pasa la auditoría. Adjunto el resultado al mensaje del *commit*.

[registrar_actividad]  → id 7f3a…, registrado_en 2026-09-29T11:04:12Z
                         finalidad: «Cruce de gastos y proveedores para el cierre anual»
                         categorias_datos: ["dades_pressupostaries"]
```
