# Extensión del navegador: agentes de unidad

Un panel lateral de Chrome con los agentes de unidad que la organización ofrece a quien lo usa
(§5.14 de [`docs/ESPECIFICACIONES.md`](../docs/ESPECIFICACIONES.md)). Se elige un agente, se escribe
la pregunta y la extensión **pide el prompt vigente a la plataforma** —que es lo que queda
registrado—. Lo que el panel pinta sale de lo que declara el agente, no de la extensión:

- **Los datos de la consulta** (#219): las indicaciones y los campos que pide el agente —una lista
  de opciones o un texto—, con los obligatorios marcados; sin ellos no se puede consultar.
- **El adjunto** (#218): en un agente con el adjunto opcional, una casilla para decir si se va a
  adjuntar un documento, y entonces el panel pide describirlo en la pregunta. En uno de revisión,
  el adjunto es obligatorio y se avisa.
- **La lengua de la respuesta** no se elige aquí: la declara el agente y la plataforma añade la
  instrucción al componer el prompt.

**En Gemini, «Insertar en Gemini» pone el prompt en la conversación y lee la respuesta** (#215),
con las funciones de `asistente.js`. **No envía**: lo envía la persona, que en un agente de revisión
adjunta antes su documento. Si no hay pestaña de Gemini o insertar falla, lo copia para pegarlo a
mano. Sólo actúa en `gemini.google.com`, con un permiso opcional que pide la primera vez. **No es
un control de acceso**: el asistente se usa igual sin ella.

**«Buscar más documentos»** (#225): tras una consulta, se escribe qué falta —y se pueden cambiar
los datos— y la plataforma busca con ese texto enlaces **nuevos, sin repetir** los ya ofrecidos en
la conversación. Se insertan en **la misma conversación** de Gemini, sin volver a pegar el prompt
del agente. Cada ampliación es una consulta más, ligada a la primera.

**Y registra la conversación** (#216). En un agente **en validación** —el modo de partida— manda a
la plataforma la respuesta que leyó, o por qué no pudo leerla, y lo avisa en el panel. En cualquier
modo ofrece 👍/👎; un 👎 pide un motivo de los que sirve la plataforma y es un informe, que en un
agente en **sólo incidencias** es lo único que se guarda.

## Cuando Gemini cambia su página

Los selectores no están en la extensión: los sirve la plataforma (el *adaptador*), y la extensión
avisa de cuál dejó de casar. Para corregirlo:

1. En **Agentes → Integración con Gemini** se ve qué selector falla. Se busca el bueno en la página
   de Gemini y se guarda: es una versión nueva, y todas las extensiones la toman sin actualizarse.
2. En el repositorio, se captura la página nueva en `instantaneas/` (mismo formato que la que hay) y
   se actualiza `adaptadores/gemini.json`. Las pruebas comprueban el adaptador contra **todas** las
   instantáneas, así que una corrección que rompa lo que ya funcionaba no pasa.

Para no enterarse por el primer usuario al que le falla, un **canario diario** lo prueba antes:
abre una conversación temporal de Gemini con el adaptador vigente, inserta, envía y lee, y si algo
no casa avisa a la plataforma y guarda la página nueva para el paso 2. Procedimiento y requisitos
en [`canario/CANARIO.md`](canario/CANARIO.md). Las funciones que ejecuta en la página están en
`canario/canario.js`, y **no van en el ZIP de la extensión**: son del canario, no del panel.

Es JavaScript sin empaquetar, sin dependencias ni compilación: Chrome carga esta carpeta tal cual.
Las pruebas viven en `frontend/src/__tests__/extensionPanel.test.ts`, que la carga con un `chrome`
de mentira.

## El ID es fijo

El manifiesto lleva la clave pública de la extensión (`key`), así que **su ID es siempre
`pgcofokabefjfmadgmeiddhfkbkebnhk`**, en cualquier carpeta y en cualquier equipo. Es el que va en `AGENTES_EXTENSION_IDS`
del servidor (y en la variable del repositorio para producción). La clave privada no está en el
repositorio: sólo hace falta para empaquetar la extensión, y la guarda quien la mantiene. **No
cambies `key`**: cambiaría el ID y ninguna extensión instalada podría conectarse.

## Instalarla y actualizarla (beta)

1. Descarga el ZIP de la versión vigente (por ejemplo, de la carpeta compartida de las pruebas) y
   descomprímelo en una carpeta propia.
2. `chrome://extensions` → activar **Modo de desarrollador** → **Cargar descomprimida** → esa
   carpeta.
3. Abre el panel con el icono de la extensión, escribe la dirección del panel de la plataforma
   (p. ej. `https://normativa.uji.es/panel`, o `http://localhost:5173` en desarrollo) y
   **Conectar**.

**Para actualizar**: descarga el ZIP nuevo, sustituye los ficheros de la carpeta y pulsa la
flecha de recargar en la tarjeta de la extensión. El número de versión de la tarjeta dice cuál
tiene cada uno; se sube en cada entrega.

## Desplegarla en una organización

La dirección del panel la puede fijar la organización por política de Chrome
(`ExtensionSettings` / almacenamiento gestionado), con el esquema de `esquema.json`:

```json
{ "panel_url": "https://normativa.uji.es/panel" }
```

`api_url` es opcional: si no se da, es el origen de `panel_url`. Lo que fija la política gana a lo
que escriba la persona.

## Conexión

«Conectar» abre `/extension/conectar` del panel con `chrome.identity.launchWebAuthFlow`. La
persona, con su sesión, confirma con un botón, y la plataforma emite un token **sólo
`agentes:consulta`**, que **caduca a los 30 días** y vuelve a la extensión en el fragmento de la
dirección. Las conexiones se ven y se revocan en **Agentes → Consultar**; «Desconectar» en la
extensión sólo olvida el token en ese navegador.
