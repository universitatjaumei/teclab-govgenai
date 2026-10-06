# El canario diario de la integración con Gemini (#215)

Gemini cambia su página sin avisar, y la extensión inserta el prompt y lee la respuesta por
selectores. Tres capas hacen que un cambio se sepa enseguida: las **instantáneas** en las pruebas,
el **aviso de campo** de la extensión cuando a alguien le falla, y este **canario**, que lo prueba
cada día antes de que le falle a nadie.

Ninguna impide que Gemini cambie. Lo que hacen es que se corrija con un cambio de datos —el
adaptador, en **Agentes → Integración con Gemini**— y no con una versión nueva de la extensión.

## Dónde corre, y por qué ahí

En **un equipo personal**, como tarea programada de Claude con el navegador ya abierto y la sesión
de Google iniciada (decisión del 2026-10-03). Gemini sólo se puede probar desde un navegador con
una cuenta, y no hay manera de hacerlo desde un servidor sin guardar allí una credencial personal.

Requisitos del equipo:

- Chrome con **Claude in Chrome**, y la cuenta institucional con sesión en `gemini.google.com`.
- Una copia de este repositorio (de aquí salen `canario.js` y `../asistente.js`).
- Un **token con sólo `agentes:consulta`** en `_local/canario/token` (fuera del repositorio). Es
  el alcance de la extensión: desde #214 sólo sirve para consultar agentes, leer el adaptador y
  avisar de fallos. Se emite en **Plataforma → Tokens de acceso**.

## Lo que hace cada día

Variables: `API=https://normativa.uji.es`, `PAT=$(cat _local/canario/token)`.

1. **El adaptador vigente.**
   `curl -s -H "Authorization: Bearer $PAT" $API/api/v1/agentes/asistentes/gemini/adaptador`
   → `{asistente, version, origen, selectores}`. Si no responde 200, se informa y se para: el
   problema es la plataforma o el token, no Gemini.
2. **Gemini en una conversación temporal.** Una pestaña nueva en `https://gemini.google.com/app`,
   y se activa **«Conversación temporal»** antes de escribir nada: no deja historial. La pestaña
   tiene que quedar **visible** durante toda la prueba, porque con la pestaña oculta Gemini no
   termina de pintar la respuesta.
3. **Los selectores, antes de enviar.** Se inyectan `extension/canario/canario.js` y
   `extension/asistente.js` en la página y se ejecuta `comprobarSelectores(selectores, false)`.
4. **Insertar.** `const previas = contarRespuestas(selectores)` y
   `insertarEnElAsistente(selectores, "Responde sólo con la palabra: canario.")`. Tiene que
   devolver `{ok: true}`.
5. **Enviar.** Con la tecla Intro en el cuadro, como lo haría una persona: ni la extensión ni el
   canario pulsan «enviar» por código. **Se comprueba que se ha enviado**: el cuadro queda vacío y
   la pregunta aparece en la conversación (`user-query`). Si a los 10 s no ha pasado, se hace clic
   en el cuadro y se vuelve a pulsar Intro.
6. **Leer, sin bloquear.** La herramienta del navegador corta una ejecución a los 45 s, y Gemini en
   modo «Thinking» tarda más. Así que la espera se lanza en la página y se consulta aparte:
   `window.__resultado = null; esperarRespuesta(selectores, previas, 120000).then(r => { window.__resultado = r; })`,
   y cada 10 s se mira `window.__resultado` hasta que deje de ser `null`. Tiene que ser `ok: true`
   con un texto no vacío; `porEstabilidad: true` es normal —Gemini tarda en bajar `aria-busy`—.
   Que diga «canario» no se exige: lo que se prueba es leer, no lo que contesta.
7. **Los selectores, con la respuesta dada.** `comprobarSelectores(selectores, true)`.

Si todo sale bien, el resultado es una línea: fecha, versión del adaptador y «correcto». No se
escribe nada en la plataforma.

## Si algo falla

- **Avisar a la plataforma**, una vez por cada selector que falla:
  `curl -s -X POST -H "Authorization: Bearer $PAT" -H "Content-Type: application/json" -d '{"version": <versión>, "selector": "<nombre>"}' $API/api/v1/agentes/asistentes/gemini/fallos`.
  La integración sale como rota en **Agentes → Integración con Gemini**, contando sólo los avisos de
  la versión vigente.
- **Guardar la página nueva**: `instantaneaDeLaPagina("<AAAA-MM-DD>")` en
  `extension/instantaneas/gemini-<AAAA-MM-DD>.html`. Con ella delante se corrige el adaptador, y al
  añadirla a las pruebas la corrección no puede romper lo que ya funcionaba.
- **Notificar** a quien mantiene la integración, con qué selectores fallaron y en qué paso.
- **No se corrige el adaptador desde el canario.** Cambiar los selectores es decisión de una
  persona, con la página nueva delante.

Un fallo en el paso 6 con `motivo: "sin_respuesta"` o `"sin_terminar"` puede ser Gemini lento y no
un selector roto: se repite una vez antes de avisar.

## Probado en vivo el 2026-10-06

Pasos 2 a 7 contra Gemini con la cuenta institucional, en una conversación temporal y con el
adaptador del repositorio: selectores correctos antes y después, inserción correcta, respuesta
leída («canario», por estabilidad) e instantánea de 9 KB con lo que buscan los selectores. De la
prueba salieron los dos detalles de los pasos 5 y 6 —comprobar el envío y no esperar dentro de una
sola ejecución— y que la raíz de la instantánea conservaba clases de Angular. Una advertencia: en
la página de Gemini `DOMParser` está bloqueado (Trusted Types), así que la instantánea se guarda
como texto y se comprueba fuera.

## Programarlo

Como tarea programada de Claude en el equipo, una vez al día y a una hora en la que el equipo esté
encendido y Chrome abierto. El prompt de la tarea es este documento: «Ejecuta el canario de
`extension/canario/CANARIO.md` y dime el resultado».
