# Extensión del navegador: agentes de unidad

Un panel lateral de Chrome con los agentes de unidad que la organización ofrece a quien lo usa
(§5.14 de [`docs/ESPECIFICACIONES.md`](../docs/ESPECIFICACIONES.md)). Se elige un agente, se escribe
la pregunta y la extensión **pide el prompt vigente a la plataforma** —que es lo que queda
registrado— y lo copia para pegarlo en el asistente general.

**En Gemini inserta el prompt y lee la respuesta** (#215), con las funciones de `asistente.js`. No
envía: lo envía la persona. Sólo actúa en `gemini.google.com`, con un permiso opcional que pide la
primera vez. **No es un control de acceso**: el asistente se usa igual sin ella.

## Cuando Gemini cambia su página

Los selectores no están en la extensión: los sirve la plataforma (el *adaptador*), y la extensión
avisa de cuál dejó de casar. Para corregirlo:

1. En **Agentes → Integración con Gemini** se ve qué selector falla. Se busca el bueno en la página
   de Gemini y se guarda: es una versión nueva, y todas las extensiones la toman sin actualizarse.
2. En el repositorio, se captura la página nueva en `instantaneas/` (mismo formato que la que hay) y
   se actualiza `adaptadores/gemini.json`. Las pruebas comprueban el adaptador contra **todas** las
   instantáneas, así que una corrección que rompa lo que ya funcionaba no pasa.

Es JavaScript sin empaquetar, sin dependencias ni compilación: Chrome carga esta carpeta tal cual.
Las pruebas viven en `frontend/src/__tests__/extensionPanel.test.ts`, que la carga con un `chrome`
de mentira.

## Instalarla para probar

1. `chrome://extensions` → activar **Modo de desarrollador** → **Cargar descomprimida** → esta
   carpeta.
2. Copiar el **ID** que Chrome le asigna y ponerlo en `AGENTES_EXTENSION_IDS` del servidor
   (separados por comas si hay varios). Reiniciar el servidor. Sin esto, la plataforma no le
   entrega el token: si lo diera a cualquier destino, una página ajena podría pedirlo.
3. Abrir el panel con el icono de la extensión, escribir la dirección del panel de la plataforma
   (p. ej. `http://localhost:5173` o `https://normativa.uji.es/panel`) y **Conectar**.

El ID de una extensión cargada sin empaquetar depende de la carpeta: en otro equipo, o moviéndola,
cambia.

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
