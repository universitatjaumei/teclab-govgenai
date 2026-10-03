/**
 * Lo que la extensión hace **dentro de la página del asistente** (#215): insertar el prompt y leer
 * la respuesta. Nada más: no envía —lo envía la persona, que en un agente de revisión tiene que
 * adjuntar antes su documento— y no lee nada que no sea la última respuesta.
 *
 * **Cada función es autocontenida**: el panel las inyecta con `chrome.scripting.executeScript`,
 * que las serializa, así que no pueden usar nada de fuera. Los selectores no están aquí: son datos
 * que sirve la plataforma (el adaptador), y por eso una corrección no exige publicar la extensión.
 *
 * Cuando algo no casa, se dice **qué selector** falló: es lo que la plataforma recibe como aviso
 * de integración rota.
 */

/** Pone el texto en el cuadro del asistente, sustituyendo lo que hubiera. */
function insertarEnElAsistente(selectores, texto) {
  const cuadro = document.querySelector(selectores.cuadro);
  if (!cuadro) return { ok: false, selector: 'cuadro' };
  cuadro.focus();
  const rango = document.createRange();
  rango.selectNodeContents(cuadro);
  const seleccion = window.getSelection();
  seleccion.removeAllRanges();
  seleccion.addRange(rango);
  // `insertText` y no escribir en el DOM: el editor del asistente lo recibe como si se hubiera
  // tecleado, y su estado interno —habilitar el botón de enviar— se entera.
  const hecho = document.execCommand('insertText', false, texto);
  // El editor convierte cada línea en un párrafo, así que se coteja sólo el principio de la primera.
  const muestra = texto.trim().split('\n')[0].slice(0, 40);
  if (!hecho || !cuadro.textContent.includes(muestra)) return { ok: false, selector: 'insercion' };
  return { ok: true };
}

/** Cuántas respuestas hay ya: la que se espera es la siguiente. */
function contarRespuestas(selectores) {
  return document.querySelectorAll(selectores.respuesta).length;
}

/**
 * Espera a que aparezca una respuesta nueva y termine, y la devuelve.
 *
 * Termina cuando el panel del texto deja de estar ocupado —el atributo que el asistente pone para
 * los lectores de pantalla, que cambia mucho menos que su maquetación— y el texto deja de crecer.
 * Se lee `textContent` y no `innerText`: con la pestaña en segundo plano no hay maquetación, y
 * `innerText` sale vacío aunque el texto esté.
 *
 * **Y con la pestaña oculta Gemini no baja `aria-busy`**: lo quita al pintar, y una pestaña oculta
 * no pinta. Se vio en su página: el texto completo y el atributo en `true` hasta volver a mirarla.
 * Por eso un texto que no cambia durante `estableMs` se da por terminado igualmente, y se marca.
 */
function esperarRespuesta(selectores, previas, limiteMs, cadaMs, estableMs) {
  const intervalo = cadaMs || 500;
  const estable = estableMs || 15000;
  return new Promise(function (resolver) {
    const inicio = Date.now();
    let aparecida = null;
    let anterior = null;
    let iguales = 0;
    let desde = null;
    const reloj = setInterval(function () {
      const ahora = Date.now();
      const todas = document.querySelectorAll(selectores.respuesta);
      if (todas.length <= previas) {
        if (ahora - inicio > limiteMs) terminar({ ok: false, motivo: 'sin_respuesta' });
        return;
      }
      const ultima = todas[todas.length - 1];
      if (aparecida === null) aparecida = ahora;
      const panel = ultima.querySelector(selectores.texto);
      if (!panel) {
        // La respuesta está y su texto no se encuentra: eso sí es un selector roto.
        if (ahora - aparecida > 20000) terminar({ ok: false, selector: 'texto' });
        return;
      }
      const texto = panel.textContent.trim();
      const ocupado = panel.getAttribute(selectores.ocupado) === 'true';
      iguales = !ocupado && texto && texto === anterior ? iguales + 1 : 0;
      desde = texto && texto === anterior ? desde : ahora;
      anterior = texto;
      const quieto = ocupado && texto && ahora - desde >= estable;
      if (iguales >= 2 || quieto) {
        const fuentes = Array.prototype.map.call(ultima.querySelectorAll(selectores.fuentes), function (a) {
          return a.href;
        });
        const leida = { ok: true, texto: texto, fuentes: fuentes };
        if (quieto) leida.porEstabilidad = true;
        terminar(leida);
      } else if (ahora - inicio > limiteMs) {
        terminar({ ok: false, motivo: 'sin_terminar' });
      }
    }, intervalo);
    function terminar(resultado) {
      clearInterval(reloj);
      resolver(resultado);
    }
  });
}
