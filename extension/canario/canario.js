/**
 * El canario diario de la integración con Gemini (#215): lo que se ejecuta **dentro de su página**.
 *
 * Lo usa la tarea programada que describe `CANARIO.md`, inyectándolo junto a `../asistente.js`.
 * Como aquél, cada función es autocontenida: se serializa para ejecutarla en la página.
 *
 * Dos funciones:
 * - `comprobarSelectores` dice qué selectores del adaptador vigente casan y cuáles no, por su
 *   nombre, que es lo que `POST /api/v1/agentes/asistentes/gemini/fallos` espera;
 * - `instantaneaDeLaPagina` saca el esqueleto de la página en el formato de
 *   `../instantaneas/`, para corregir el adaptador con la página nueva delante y añadirla a las
 *   pruebas.
 */

/**
 * Antes de enviar sólo tiene que estar el cuadro; con la respuesta ya dada, también la respuesta,
 * su panel de texto y el atributo de ocupado en ese panel. Las fuentes no cuentan: una respuesta
 * sin fuentes no tiene ninguna, y eso no es un selector roto.
 */
function comprobarSelectores(selectores, conRespuesta) {
  const fallan = [];
  if (document.querySelectorAll(selectores.cuadro).length !== 1) fallan.push('cuadro');
  if (conRespuesta) {
    const respuestas = document.querySelectorAll(selectores.respuesta);
    const ultima = respuestas[respuestas.length - 1];
    if (!ultima) {
      fallan.push('respuesta');
    } else {
      const panel = ultima.querySelector(selectores.texto);
      if (!panel) fallan.push('texto');
      else if (!panel.hasAttribute(selectores.ocupado)) fallan.push('ocupado');
    }
  }
  return { ok: fallan.length === 0, fallan: fallan };
}

/**
 * El esqueleto de la página, como el de las instantáneas: las etiquetas, los roles, los `aria-*`,
 * `contenteditable`, los identificadores y las clases que no genera Angular; fuera estilos,
 * imágenes, scripts y el resto de atributos, y cada texto cortado a 60 caracteres.
 */
function instantaneaDeLaPagina(fecha) {
  const QUITAR = ['style', 'script', 'svg', 'img', 'picture', 'video', 'canvas', 'link', 'meta', 'noscript'];
  const raiz = (document.querySelector('chat-window') || document.body).cloneNode(true);

  function conservar(nombre) {
    return nombre === 'role' || nombre === 'id' || nombre === 'contenteditable' ||
      nombre === 'class' || nombre.indexOf('aria-') === 0 || nombre === 'data-test-id';
  }

  /** Deja en un elemento sólo los atributos que se conservan, y en `class` las que no genera Angular. */
  function depurar(el) {
    Array.prototype.slice.call(el.attributes).forEach(function (a) {
      if (!conservar(a.name)) el.removeAttribute(a.name);
    });
    const clases = (el.getAttribute('class') || '').split(/\s+/).filter(function (c) {
      return c && c.indexOf('ng-') !== 0 && c.indexOf('_ng') !== 0 && c.indexOf('cdk-') !== 0 && c.indexOf('mat-') !== 0;
    });
    if (clases.length) el.setAttribute('class', clases.join(' '));
    else el.removeAttribute('class');
  }

  function limpiar(nodo) {
    Array.prototype.slice.call(nodo.childNodes).forEach(function (hijo) {
      if (hijo.nodeType === 8) {
        nodo.removeChild(hijo);
      } else if (hijo.nodeType === 3) {
        const texto = hijo.textContent.replace(/\s+/g, ' ');
        if (!texto.trim()) nodo.removeChild(hijo);
        else hijo.textContent = texto.trim().slice(0, 60);
      } else if (hijo.nodeType === 1) {
        if (QUITAR.indexOf(hijo.tagName.toLowerCase()) >= 0) {
          nodo.removeChild(hijo);
          return;
        }
        depurar(hijo);
        limpiar(hijo);
      }
    });
  }

  // También la raíz: en la página real salía con las clases `ng-tns-…` (2026-10-06).
  if (raiz.nodeType === 1) depurar(raiz);
  limpiar(raiz);
  const cabecera = [
    '<!--',
    '  Esqueleto de gemini.google.com, capturado el ' + fecha + ' por el canario diario (#215), de una',
    '  conversación temporal. Mismo formato que las demás instantáneas: etiquetas, roles, aria-*,',
    '  contenteditable, identificadores y clases que no genera Angular; textos cortados a 60',
    '  caracteres. Las pruebas comprueban el adaptador vigente contra todas.',
    '-->',
  ].join('\n');
  return cabecera + '\n' + raiz.outerHTML + '\n';
}
