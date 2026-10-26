# Incrustar el widget en una página

> **Entregable de D.6-VM (2026-08-31)**, que recoge lo que D.1 dejó pendiente. La credencial de
> sitio la construyó SEC.8.5 (`HubWidgetKey`); esto documenta cómo se usa, cómo se revoca y
> qué es exactamente lo que viaja en el HTML.

## El fragmento

```html
<div
  id="govgenai-widget"
  data-chatbot-id="<UUID del chatbot>"
  data-widget-key="<credencial de SITIO>"
  data-api-url="https://<HOST>/api/v1"
  data-lang="es"
  data-title="Assistent normativa"
></div>
<script src="https://<HOST>/widget.iife.js" defer></script>
```

**Las dos URL van absolutas**, con el host de la instancia. El fragmento se pega en otra web, y
una ruta relativa apunta a esa web y no a la plataforma. El panel lo genera ya así (#279), con el
origen desde el que se sirve; la plataforma no tiene un ajuste de «URL pública», así que si el
panel se abre por una dirección interna, el fragmento la lleva y hay que corregirla a mano.

| Atributo | Obligatorio | Qué hace |
|---|---|---|
| `data-chatbot-id` | **Sí** | Sin él el widget no arranca (`readConfig` devuelve `null`) |
| `data-widget-key` | Sí en una página pública | La credencial de sitio. Viaja en la cabecera `X-Widget-Key` |
| `data-api-url` | Sí si la página no está en el mismo origen que la API | Por omisión `/api/v1`, que sólo vale si comparten origen |
| `data-lang` | No | `es` por omisión |
| `data-model` | No | Sólo para el aviso del pie: lo declara la página, no el servidor |
| `data-title` | **Sí si publicas más de un asistente** | Nombre en la cabecera del chat. Sin él, la traducción genérica («Asistente») |

## La política de seguridad de contenido (CSP) de la página anfitriona

Si la web que incrusta el widget envía una cabecera `Content-Security-Policy`, tiene que permitir
tres cosas, o el widget no arranca o arranca sin estilo, **sin ningún error visible en la página**:

| Directiva | Qué añadir | Por qué |
|---|---|---|
| `script-src` | `https://<HOST>` | Carga `widget.iife.js` desde la instancia |
| `connect-src` | `https://<HOST>` | Las llamadas a la API: tema, preguntas por SSE, valoraciones |
| `style-src` | `'unsafe-inline'` | El widget inyecta elementos `<style>` con las variables del tema y el CSS propio del chatbot |

```
Content-Security-Policy: script-src 'self' https://<HOST>; connect-src 'self' https://<HOST>; style-src 'self' 'unsafe-inline'
```

`'unsafe-inline'` en `style-src` es una concesión de la página anfitriona, y conviene saberlo
antes de integrar: el tema se aplica escribiendo CSS en tiempo de ejecución, así que no hay un
fichero de estilos que se pueda listar por hash. Una web sin CSP no tiene que hacer nada.

El widget, por su parte, sólo atiende mensajes `postMessage` del propio origen de la página: un
`iframe` de terceros no puede cambiarle el idioma (#278).

## Por qué `data-title` no es cosmético

Con dos asistentes publicados sobre el mismo corpus —el normativo y el
económico-administrativo del piloto de la UJI— una cabecera que dice sólo «Asistente» no
permite a quien prueba saber cuál está contestando, y sus valoraciones quedan atribuidas a
ciegas. Se descubrió enseñando el piloto: las dos páginas eran idénticas salvo el
`data-chatbot-id`, que no se ve.

**Lo declara la página y no el servidor**, igual que `data-model`, y por dos razones: el texto
que se quiere mostrar no suele ser el nombre interno del chatbot en el panel («Gerència —
assistent economicoadministratiu» frente a «Assistent econòmic-administratiu»), y el nombre
interno puede decir cosas que no van en una página pública.

## Lo que hay que entender de la credencial

**Es de SITIO y aparece en el HTML de quien publique la página.** Eso no es un descuido: es el
diseño. Por eso sólo abre chatbots `public_anon` y nada más — no da acceso al panel, ni a otros
chatbots, ni a datos de ninguna organización.

Dos consecuencias prácticas:

1. **Una credencial por sitio.** Si la misma clave está en dos sitios, revocar por abuso de uno
   apaga el otro.
2. **La que uses en local acaba dentro del HTML generado.** Emite una nueva para el bucket,
   genera el sitio con ella, y **revoca la de local**. Si no, publicas tu credencial de pruebas.

## Revocar y rotar

Las dos operaciones están en el panel del chatbot, y la diferencia importa:

- **Revocar** apaga la credencial ya. El widget de las páginas que la lleven deja de responder;
  las páginas siguen leyéndose, porque el asistente es un añadido y no el servicio principal.
- **Rotar** es emitir una nueva, regenerar y volver a subir el sitio con ella, y revocar la
  vieja **después** de comprobar que el sitio nuevo funciona. En ese orden: al revés hay un
  hueco en el que el widget está muerto en producción.

La clave se guarda **con hash**, así que no se puede volver a mostrar: si se pierde, se emite
otra. Es la misma razón por la que la rotación es «emitir, publicar, revocar» y no «recuperar».

## Si el widget no responde

En orden, porque el primero explica la mayoría de los casos:

1. **Origen no permitido.** La página y la API no comparten origen, así que el origen del sitio
   tiene que estar en `CORS_ALLOWED_ORIGINS`. En producción la política es cerrada, y un origen
   que falta se traduce en un *preflight* rechazado — **no** en un error visible en la página.
2. **Contenido mixto.** Si la página se sirve por HTTPS y `data-api-url` es `http://`, el
   navegador bloquea la llamada sin avisar en la interfaz. Mírala en la consola.
3. **Credencial revocada o de otro chatbot.** Responde 401/403, y el widget lo dice: «este
   asistente no está disponible desde esta página». No rompe la página.
4. **El chatbot no es `public_anon`.** La credencial de sitio no abre ningún otro tipo, a
   propósito.
5. **La CSP de la página.** Ver la sección de arriba: la consola del navegador dice qué
   directiva bloqueó qué.

**El widget nunca puede romper la lectura de la página.** Si el servidor no responde, se queda
sin abrir y la norma se sigue leyendo: es el requisito que D.6.1 pone por escrito, y la razón de
que el `<script>` vaya con `defer`.
