# Secciones dinámicas: parametrizar un apartado que se mantiene solo

> Bloque **DIN** (2026-09-17). Qué hace falta para que un apartado del portal —jornadas, eventos,
> becas— alimente al asistente sin que nadie lo cure página a página, y qué se pierde si se hace
> mal. Está escrito para seguirlo sin preguntar.

## 1. Lo que hay que entender antes de tocar nada

**Curación una vez, automatización después.** La decisión del 2026-08-02
(`docs/DECISION_CURACION_SEPARADA.md`) sigue en pie: una página nueva es una señal para quien
cura, no un disparador. Lo que DIN añade es el matiz: **dentro del ámbito que una persona aprobó
una vez**, la automatización mantiene. No hay ingesta automática de nada que nadie haya aprobado
nunca; hay mantenimiento automático de lo que alguien aprobó.

Por eso una sección **nace en modo `manual`** y hay que pasarla a `automatic` a mano. No es una
precaución decorativa: en `manual`, una baja deja un aviso y no toca el corpus.

**El apartado es dato, no estructura.** Antes de DIN, un apartado se expresaba creando un sitio
entero con su filtro de URL: duplicaba raíz, sitemap, cortesía y criterios de juicio, y «añadir el
apartado de becas» era trabajo de quien administra sitios. Ahora es un formulario en la pestaña de
curación del sitio.

## 2. La receta, paso a paso

Todo se hace en **Curación → Sitios**, en la fila del sitio, botón **«Secciones del sitio»**.

1. **Rastrea el sitio una vez** («Rastrear ahora») si no lo has hecho. Hace falta para el paso 3:
   el patrón se prueba contra las páginas **ya rastreadas**.
2. **«Nueva sección»** y rellena:
   - **Nombre** — el que reconoce quien cura («Jornadas»). Es único por sitio, y con él se
     identifica la sección en el diario de pasadas.
   - **Patrón** y **clase**: `Prefijo de ruta` (`/jornadas`) o `Expresión regular`. El prefijo
     compara **la ruta**, no la URL entera; la expresión regular compara la URL completa, que es
     lo que permite acotar por idioma (`/va/`) cuando el portal lo duplica.
   - **Cadencia propia (horas)**: **déjala vacía para heredar la del sitio**. Vacío es heredar, y
     un número es «lo quiero así»; en la lista, cada sección dice cuál de las dos está usando.
   - **Responsable**: quién mantiene el apartado. Es la razón por la que RAS.5 partía por sitios,
     y aquí es un campo.
3. **«Probar patrón»** antes de guardar. Dice cuántas páginas ya rastreadas casarían y muestra
   diez. **Si dice cero, el patrón está mal**: un regex que compila y no casa nada no da ningún
   error, y sin esta prueba sólo se descubre cuando la pasada siguiente no ingiere nada — y como
   la ingesta automática es silenciosa, se descubre tarde.
4. **Guarda.** La sección queda en `manual`.
5. **Enlázala a un asistente**: en la selección de corpus del chatbot, apunta `section_id` a esta
   sección en vez de repetir su patrón. Con eso puesto, **el patrón lo manda la sección** y el
   `rule_value` se ignora: dos sitios de verdad de la misma regla divergirían en cuanto alguien
   editara uno.
6. **Primera pasada, revisada hallazgo a hallazgo** en **Curación → Hallazgos**. Aquí es donde se
   calibran los criterios del sitio (antigüedad, mínimo de contenido, selectores de contenido y
   de fecha) contra este apartado concreto. Es el paso que no se puede saltar: la automatización
   va a aplicar **estos** criterios.
7. **Pásala a `automatic`** en el desplegable «Modo» de su fila.

Desde ese momento, cada vez que venza su cadencia:

| Lo que pasa en el portal | Lo que hace la plataforma |
|---|---|
| Página **nueva** que casa el patrón | la ingiere sola, si no tiene hallazgos bloqueantes |
| Página **cambiada** que ya estaba en el corpus | la reingiere y deja el aviso `content_updated` |
| Página **desaparecida** | retira sus documentos del corpus y lo anota en el diario |
| Página nueva **ilegible** (vacía, necesita JavaScript, error de descarga, muy pobre) | **no** la ingiere: `auto_ingesta_detenida` con el motivo |
| **Muchas** bajas de golpe | **no retira nada**: `retirada_masiva_detenida` con las cifras |

## 3. Las dos salvaguardas, y cómo se ajustan

Las dos son **criterios de juicio**, así que se ponen en el sitio y se pueden sobrescribir por
sección (nulo hereda). Un apartado que alimenta al asistente puede ser más exigente que su portal.

**Puerta de calidad** — `tipos_bloqueantes`. Por defecto los de legibilidad: `empty`,
`needs_javascript`, `crawl_error`, `thin` y `navigation` (#345: las páginas cuyo texto son enlaces,
que antes salían como `thin`; una lista que bloquea `thin` bloquea también `navigation`). `stale` **no** bloquea: dice que la página es vieja, no
que no se pueda leer, y bloquear por eso dejaría fuera medio portal. Una lista puesta **sustituye**
al defecto, en los dos sentidos: se puede endurecer y se puede relajar.

La página bloqueada **sigue siendo candidata**. No se marca nada: resuelto el hallazgo, la pasada
siguiente la ingiere sola.

**Retirada masiva detenida** — `retirada_masiva_umbral`, por defecto `0.30`. Si las bajas de una
pasada superan esa proporción **del ámbito rastreado**, no se retira nada y queda el aviso con las
cifras. Protege de la clase de rastreo malo que el truncado no capta: el portal que responde 200
con una plantilla vacía, la redirección masiva. La proporción es del ámbito y no del sitio porque
cuatro bajas en un apartado de diez son el 40 % del apartado y el 4 % de un portal de cien.

## 4. Lo que hay que saber aunque no se pregunte

**Un sitio con secciones deja de rastrearse como sitio entero por cadencia.** Vencen las
secciones. Si venciera además el sitio, cada pasada del sitio volvería a pedir lo que la sección
acaba de mirar: el doble de peticiones contra el mismo servidor. **Lo que quede fuera de toda
sección se rastrea a mano** con «Rastrear ahora», y eso no automatiza nada.

**El censo se acota al ámbito.** Una pasada de `/jornadas` compara contra las páginas de
`/jornadas`, nunca contra las del sitio entero; fuera del ámbito no se declara nada, ni baja ni
cambio. Es la regla dura del bloque: sin ella, una pasada completa de una sección declararía baja
el resto del portal, y con la retirada automática detrás eso vacía corpus.

**Una pasada de sección no reanuda la cola del sitio.** La cola de reanudación (RAS.3) es de un
recorrido del sitio entero; si una sección la escribiera, la siguiente pasada de otra sección
arrancaría por la mitad del recorrido ajeno y creería haber visto su ámbito sin haberlo visto. Una
sección es pequeña por definición: si se trunca, empieza de nuevo.

**Borrar una sección con selecciones colgando no se puede**: responde 409 y hay que desactivarla.
Perder la selección no es perder una fila: es dejar de mantener lo que ya está en el corpus. El
**diario sí sobrevive** al borrado de la sección, con el nombre que tenía.

## 5. Dónde se mira lo que hizo

**Diario de pasadas**, debajo de las secciones del sitio. Una fila por pasada, con su ámbito
—el nombre de la sección, o «sitio»— y sus contadores: ingeridas, reingeridas, retiradas,
bloqueadas y bajas. El detalle despliega los errores, las páginas que no se pudieron descargar, y
el aviso de que el rastreo **no vio el ámbito entero** (que es la diferencia entre «cero bajas» y
«no se han comprobado las bajas»).

Se conservan las **50 últimas pasadas de cada ámbito**. Por ámbito y no por sitio: si fuera por
sitio, la sección de cada seis horas se llevaría todas las filas y borraría la historia de la que
se mira una vez a la semana.

Los avisos accionables van a **Curación → Hallazgos**, con su tipo: `page_gone`,
`auto_ingesta_detenida`, `retirada_masiva_detenida`, `content_updated`.

## 6. La decisión que queda pendiente: la caducidad editorial

Un evento que ya ocurrió **sigue publicado** en el portal, así que para la plataforma no ha
desaparecido y sigue en el corpus. El asistente lo citará como si viniera. Esto **no se ha
implementado a propósito**: no es una decisión técnica.

Las opciones, con su precio:

1. **No hacer nada** (lo de hoy). El asistente puede citar un evento pasado. Aceptable en un
   apartado de normativa; malo en uno de eventos.
2. **Que el portal lo diga.** Si la página publica su fecha de celebración en el marcado, se lee
   con los selectores de CUR.1 y se retira sola al vencer. Es la opción buena, y **depende de que
   quien publica marque la fecha**.
3. **Deducir la fecha del texto.** Barato de escribir y caro de sufrir: es exactamente la
   heurística que CUR.1 vino a retirar, porque marcaba tres de cada cuatro páginas.
4. **Caducidad por antigüedad del apartado** (por ejemplo, retirar del corpus lo que lleve seis
   meses sin cambiar en `/eventos`). Configurable por sección, y es una convención, no un dato:
   funciona si el responsable del apartado la acepta.

**A quién le toca**: al propietario del contenido, no a esta plataforma. La pregunta que hay que
llevarle es «¿cuándo deja de ser cierto lo que publicas?», y la respuesta decide entre la 2 y la
4. Mientras no haya respuesta, la 1 es lo que hay y conviene que quien cura lo sepa.
