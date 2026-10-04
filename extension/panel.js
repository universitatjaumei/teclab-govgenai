/**
 * Panel lateral de la extensión de agentes de unidad — Gov Gen AI Platform (#176).
 *
 * La biblioteca: los agentes que la plataforma ofrece al colectivo de quien mira. Se elige uno, se
 * escribe la pregunta, y la extensión **pide el prompt vigente a la API** —que es lo que queda
 * registrado— y lo copia para pegarlo en el asistente general. Por eso existe la extensión: con
 * copiar y pegar a mano, quien reutiliza un prompt viejo no vuelve a pasar por la plataforma, y el
 * registro subcuenta y el prompt se queda desfasado.
 *
 * **En Gemini, inserta el prompt y lee la respuesta** (#215): las funciones que actúan en su página
 * están en `asistente.js`, y los selectores los sirve la plataforma —el adaptador—, de modo que un
 * cambio de Gemini se corrige sin publicar la extensión. Si insertar falla, se copia, como antes,
 * y la plataforma recibe el aviso de qué selector dejó de casar. **No envía**: lo envía la persona,
 * que en un agente de revisión tiene que adjuntar antes su documento. **No es un control de
 * acceso**: cualquiera puede usar el asistente sin la extensión.
 *
 * **#216 — la conversación**: en un agente en validación, la respuesta leída va a la plataforma —o
 * por qué no se pudo leer—; en cualquier modo, quien consulta la valora, y un 👎 con motivo es un
 * informe. Los motivos los sirve la plataforma con su etiqueta: aquí no se conocen.
 *
 * Se identifica con la cuenta de la persona: «Conectar» abre la página de la plataforma, que pide
 * iniciar sesión si hace falta y, con el consentimiento de la persona, entrega a la extensión un
 * token que sólo sirve para consultar.
 */

const LENGUAS = ['es', 'ca', 'en'];

function lengua() {
  const ui = (chrome.i18n.getUILanguage() || 'es').toLowerCase();
  if (ui.startsWith('ca') || ui.startsWith('va')) return 'ca';
  return LENGUAS.indexOf(ui.slice(0, 2)) >= 0 ? ui.slice(0, 2) : 'es';
}

function texto(clave, sustituciones) {
  return chrome.i18n.getMessage(clave, sustituciones) || clave;
}

// =============================================================================
//  La configuración y el token
// =============================================================================

async function configuracion() {
  let gestionada = {};
  try {
    gestionada = await chrome.storage.managed.get(['panel_url', 'api_url']);
  } catch (e) {
    gestionada = {};
  }
  const local = await chrome.storage.local.get(['panel_url', 'api_url', 'token']);
  const panel = String(gestionada.panel_url || local.panel_url || '').replace(/\/+$/, '');
  let api = String(gestionada.api_url || local.api_url || '').replace(/\/+$/, '');
  if (!api && panel) {
    try {
      api = new URL(panel).origin;
    } catch (e) {
      api = '';
    }
  }
  return { panel: panel, api: api, token: local.token || null, gestionada: Boolean(gestionada.panel_url) };
}

async function guardarPanel(url) {
  await chrome.storage.local.set({ panel_url: String(url || '').trim() });
}

/** Abre la página de conexión de la plataforma y se queda con el token que devuelve. */
async function conectar(conf) {
  const permiso = await chrome.permissions.request({ origins: [new URL(conf.api).origin + '/*'] });
  if (!permiso) throw new Error(texto('sinPermiso'));
  const destino = chrome.identity.getRedirectURL();
  const vuelta = await chrome.identity.launchWebAuthFlow({
    url: conf.panel + '/extension/conectar?destino=' + encodeURIComponent(destino),
    interactive: true,
  });
  const fragmento = new URL(vuelta).hash.replace(/^#/, '');
  const token = new URLSearchParams(fragmento).get('token');
  if (!token) throw new Error(texto('sinToken'));
  await chrome.storage.local.set({ token: token });
  return token;
}

async function desconectar() {
  await chrome.storage.local.remove('token');
}

// =============================================================================
//  La API
// =============================================================================

class Desconectado extends Error {}

async function llamar(conf, ruta, opciones) {
  const respuesta = await fetch(conf.api + ruta, {
    method: (opciones && opciones.method) || 'GET',
    headers: Object.assign(
      { Authorization: 'Bearer ' + conf.token },
      opciones && opciones.cuerpo ? { 'Content-Type': 'application/json' } : {}
    ),
    body: opciones && opciones.cuerpo ? JSON.stringify(opciones.cuerpo) : undefined,
  });
  if (respuesta.status === 401) {
    // Revocado o caducado: se olvida y se pide conectar de nuevo.
    await desconectar();
    throw new Desconectado(texto('reconectar'));
  }
  const cuerpo = await respuesta.json().catch(function () {
    return {};
  });
  if (!respuesta.ok) {
    const detalle = cuerpo && cuerpo.detail;
    const mensaje = typeof detalle === 'string' ? detalle : (detalle && detalle.message) || texto('fallo');
    throw new Error(mensaje);
  }
  return cuerpo;
}

function catalogo(conf) {
  return llamar(conf, '/api/v1/agentes/catalogo');
}

// El asistente sobre el que se inserta. Sólo Gemini por ahora; Copilot, después (2026-10-03).
const ASISTENTE = 'gemini';
// Cuánto se espera a que la persona envíe y el asistente termine: puede tener que adjuntar antes.
const ESPERA_DE_LA_RESPUESTA_MS = 10 * 60 * 1000;

function adaptador(conf) {
  return llamar(conf, '/api/v1/agentes/asistentes/' + ASISTENTE + '/adaptador');
}

/** Sin esperar ni molestar: si el aviso no llega, la persona sigue trabajando. */
function avisarDeUnFallo(conf, ad, selector) {
  return llamar(conf, '/api/v1/agentes/asistentes/' + ad.asistente + '/fallos', {
    method: 'POST',
    cuerpo: { version: ad.version, selector: selector },
  }).catch(function () {});
}

/**
 * La pestaña del asistente, si es la activa **en la ventana del panel**. No la de la última ventana
 * con foco: tras conectar, ésa puede ser la ventana de la conexión y no la de la persona.
 */
async function pestanaDelAsistente(ad) {
  const pestanas = await chrome.tabs.query({ active: true, currentWindow: true, url: ad.origen + '/*' });
  return pestanas[0] || null;
}

async function enLaPagina(pestana, funcion, args) {
  const resultados = await chrome.scripting.executeScript({ target: { tabId: pestana.id }, func: funcion, args: args });
  return resultados[0] && resultados[0].result;
}

function guardarRespuesta(conf, consultaId, cuerpo) {
  return llamar(conf, '/api/v1/agentes/consultas/' + consultaId + '/respuesta', { method: 'POST', cuerpo: cuerpo });
}

function valorar(conf, consultaId, cuerpo) {
  return llamar(conf, '/api/v1/agentes/consultas/' + consultaId + '/valoracion', { method: 'POST', cuerpo: cuerpo });
}

function motivosDeInforme(conf) {
  return llamar(conf, '/api/v1/agentes/motivos-de-informe?lengua=' + lengua());
}

/** Lo que leyó la extensión, en la forma que guarda la plataforma: la respuesta o por qué no la hay. */
function loLeido(leida) {
  if (leida && leida.ok) return { texto: leida.texto, fuentes: leida.fuentes || [] };
  if (leida && leida.selector) return { no_capturada: 'selector' };
  return { no_capturada: (leida && leida.motivo) || 'sin_respuesta' };
}

/** `adjunta` sólo cuenta en un agente con el adjunto opcional (#218); en los demás lo decidió la unidad. */
/** `datos` (#219): los que declara el agente, por su clave; los vacíos no se mandan. */
function consultar(conf, agenteId, pregunta, adjunta, datos) {
  return llamar(conf, '/api/v1/agentes/' + agenteId + '/consulta', {
    method: 'POST',
    cuerpo: { consulta: pregunta, lengua: lengua(), adjunta: Boolean(adjunta), datos: datos || {} },
  });
}

// =============================================================================
//  La pantalla
// =============================================================================

function el(etiqueta, atributos, hijos) {
  const nodo = document.createElement(etiqueta);
  Object.keys(atributos || {}).forEach(function (k) {
    if (k === 'texto') nodo.textContent = atributos[k];
    else if (k.slice(0, 2) === 'on') nodo.addEventListener(k.slice(2), atributos[k]);
    else nodo.setAttribute(k, atributos[k]);
  });
  (hijos || []).forEach(function (h) {
    if (h) nodo.appendChild(h);
  });
  return nodo;
}

let turno = 0;

/**
 * Vuelve a pintar el panel. Se construye aparte y se cambia de una vez: si dos llamadas se cruzan
 * —conectar mientras aún carga el catálogo—, sólo la última llega a la pantalla.
 */
async function pintar() {
  const mio = ++turno;
  const nuevo = document.createElement('div');
  await construir(nuevo);
  if (mio === turno) document.getElementById('raiz').replaceChildren(...nuevo.childNodes);
}

async function construir(raiz) {
  raiz.appendChild(el('h1', { texto: texto('titulo') }));
  const conf = await configuracion();

  if (!conf.panel) {
    const campo = el('input', { type: 'url', id: 'panel-url', placeholder: 'https://…/panel', 'aria-label': texto('direccion') });
    raiz.appendChild(el('p', { texto: texto('sinDireccion') }));
    raiz.appendChild(campo);
    raiz.appendChild(
      el('button', {
        class: 'principal',
        texto: texto('guardar'),
        onclick: async function () {
          await guardarPanel(campo.value);
          await pintar();
        },
      })
    );
    return;
  }

  if (!conf.token) {
    raiz.appendChild(el('p', { texto: texto('sinConectar') }));
    const fallo = el('p', { class: 'error', role: 'alert' });
    raiz.appendChild(
      el('button', {
        class: 'principal',
        id: 'conectar',
        texto: texto('conectar'),
        onclick: async function () {
          fallo.textContent = '';
          try {
            await conectar(conf);
            await pintar();
          } catch (e) {
            fallo.textContent = e.message;
          }
        },
      })
    );
    raiz.appendChild(fallo);
    return;
  }

  let agentes;
  try {
    agentes = await catalogo(conf);
  } catch (e) {
    raiz.appendChild(el('p', { class: 'error', role: 'alert', texto: e.message }));
    if (e instanceof Desconectado) raiz.appendChild(el('button', { texto: texto('conectar'), onclick: pintar }));
    return;
  }
  if (!agentes.length) {
    raiz.appendChild(el('p', { texto: texto('ninguno') }));
    return;
  }

  let elegido = null;
  const lista = el('fieldset', {}, [el('legend', { texto: texto('agente') })]);
  agentes.forEach(function (a) {
    const radio = el('input', { type: 'radio', name: 'agente', value: a.id, 'aria-label': a.nombre + ' — ' + a.unidad });
    radio.addEventListener('change', function () {
      elegido = a;
      casillaAdjunta.checked = false;
      pintarDatos();
      actualizar();
    });
    const avisos = [];
    if (a.adjunto === 'obligatorio') avisos.push(el('span', { class: 'aviso', texto: texto('conAdjunto') }));
    if (a.adjunto === 'opcional') avisos.push(el('span', { class: 'aviso', texto: texto('adjuntoOpcional') }));
    if (a.revision_vencida) avisos.push(el('span', { class: 'aviso', texto: texto('revisionVencida') }));
    if (a.indice_sin_actualizar) avisos.push(el('span', { class: 'aviso', texto: texto('indiceSinActualizar') }));
    if (a.modo_registro === 'validacion') avisos.push(el('span', { class: 'aviso validacion', texto: texto('enValidacion') }));
    lista.appendChild(
      el('label', { class: 'agente', 'data-agente': a.id }, [
        radio,
        el('span', {}, [
          el('strong', { texto: a.nombre }),
          el('p', { class: 'nota', texto: a.unidad }),
          el('p', { texto: a.finalidad }),
        ].concat(avisos)),
      ])
    );
  });
  raiz.appendChild(lista);

  // El adaptador se pide al pintar y no al pulsar: el permiso sobre la página del asistente hay que
  // pedirlo mientras el clic aún cuenta como gesto de la persona, sin nada esperando delante.
  let ad = null;
  try {
    ad = await adaptador(conf);
  } catch (e) {
    ad = null;
  }

  const pregunta = el('textarea', { id: 'pregunta', rows: '3', maxlength: '2000', 'aria-label': texto('pregunta') });
  const pista = el('p', { class: 'nota' });
  // #219 — los datos que pide el agente elegido: el formulario sale de lo que declara, no de aquí.
  const datosCont = el('div', { id: 'datos-consulta' });
  function pintarDatos() {
    datosCont.textContent = '';
    if (!elegido) return;
    if (elegido.indicaciones) datosCont.appendChild(el('p', { class: 'nota', id: 'indicaciones', texto: elegido.indicaciones }));
    (elegido.datos_consulta || []).forEach(function (d) {
      const id = 'dato_' + d.clave;
      const etiqueta = d.obligatorio ? d.etiqueta + ' *' : d.etiqueta;
      let campo;
      if (d.tipo === 'opciones') {
        campo = el('select', { id: id, 'data-clave': d.clave }, [el('option', { value: '', texto: texto('eligeUna') })].concat(
          (d.opciones || []).map(function (o) {
            return el('option', { value: o, texto: o });
          }),
        ));
        campo.addEventListener('change', actualizar);
      } else {
        campo = el('input', { id: id, 'data-clave': d.clave, maxlength: '200' });
        campo.addEventListener('input', actualizar);
      }
      datosCont.appendChild(el('label', { for: id, texto: etiqueta }));
      datosCont.appendChild(campo);
      if (d.ayuda) datosCont.appendChild(el('p', { class: 'nota', texto: d.ayuda }));
    });
  }
  function valoresDeLosDatos() {
    const valores = {};
    datosCont.querySelectorAll('[data-clave]').forEach(function (c) {
      if (c.value.trim()) valores[c.getAttribute('data-clave')] = c.value.trim();
    });
    return valores;
  }
  function faltaUnObligatorio() {
    if (!elegido) return false;
    const valores = valoresDeLosDatos();
    return (elegido.datos_consulta || []).some(function (d) {
      return d.obligatorio && !valores[d.clave];
    });
  }
  // #218 — en un agente con el adjunto opcional, quien pregunta dice si adjunta.
  const casillaAdjunta = el('input', { type: 'checkbox', id: 'adjunta' });
  const adjuntaOpcional = el('label', { class: 'fila', hidden: '' }, [casillaAdjunta, el('span', { texto: texto('voyAAdjuntar') })]);
  casillaAdjunta.addEventListener('change', actualizar);
  function conAdjunto() {
    if (!elegido) return false;
    return elegido.adjunto === 'obligatorio' || (elegido.adjunto === 'opcional' && casillaAdjunta.checked);
  }
  const insertar = ad ? el('button', { class: 'principal', id: 'insertar', texto: texto('insertar', [ad.nombre]) }) : null;
  const boton = el('button', { class: ad ? '' : 'principal', id: 'preparar', texto: texto('preparar') });
  const resultado = el('p', { role: 'status' });
  const lectura = el('p', { class: 'nota', id: 'lectura' });
  const aMano = el('div', { id: 'copia-a-mano' });
  const valoracion = el('div', { id: 'valoracion' });
  // La consulta en curso: contra ella van la respuesta y la valoración.
  let enCurso = null;

  function empezarConsulta(r) {
    enCurso = { id: r.consulta_id, modo: r.modo_registro, pregunta: pregunta.value.trim(), respuesta: null };
    ofrecerValoracion(enCurso);
  }

  /** 👍 o 👎 sobre la respuesta; 👎 pide el motivo y es un informe. */
  function ofrecerValoracion(consulta) {
    valoracion.textContent = '';
    if (consulta.modo === 'validacion') {
      valoracion.appendChild(el('p', { class: 'nota', texto: texto('seGuardaLaConversacion') }));
    }
    const estado = el('p', { class: 'nota', role: 'status', id: 'estado-valoracion' });
    const util = el('button', { id: 'util', texto: texto('util') });
    const inutil = el('button', { id: 'inutil', texto: texto('inutil') });
    const informe = el('div', { id: 'informe' });
    util.addEventListener('click', async function () {
      try {
        await valorar(conf, consulta.id, { puntuacion: 1 });
        informe.textContent = '';
        estado.textContent = texto('gracias');
      } catch (e) {
        estado.textContent = e.message;
      }
    });
    inutil.addEventListener('click', async function () {
      informe.textContent = '';
      let motivos = [];
      try {
        motivos = await motivosDeInforme(conf);
      } catch (e) {
        estado.textContent = e.message;
        return;
      }
      const lista = el('select', { id: 'motivo', 'aria-label': texto('motivo') }, motivos.map(function (m) {
        return el('option', { value: m.codigo, texto: m.etiqueta });
      }));
      const comentario = el('textarea', { id: 'comentario', rows: '2', maxlength: '4000', 'aria-label': texto('comentario'), placeholder: texto('comentario') });
      const enviar = el('button', { id: 'enviar-informe', class: 'principal', texto: texto('enviarInforme') });
      enviar.addEventListener('click', async function () {
        enviar.disabled = true;
        try {
          await valorar(conf, consulta.id, {
            puntuacion: -1,
            motivo: lista.value,
            comentario: comentario.value.trim() || null,
            // En incidencias es lo único que se guarda: van la pregunta y la respuesta.
            pregunta: consulta.pregunta,
            respuesta: consulta.respuesta,
          });
          informe.textContent = '';
          estado.textContent = texto('informeEnviado');
        } catch (e) {
          estado.textContent = e.message;
          enviar.disabled = false;
        }
      });
      informe.appendChild(lista);
      informe.appendChild(comentario);
      informe.appendChild(enviar);
    });
    valoracion.appendChild(el('p', { texto: texto('teHaServido') }));
    valoracion.appendChild(el('div', { class: 'fila' }, [util, inutil]));
    valoracion.appendChild(informe);
    valoracion.appendChild(estado);
  }
  pregunta.addEventListener('input', actualizar);

  /** Prepararlo tarda unos segundos: se dice, y no se puede pulsar otra vez mientras tanto. */
  function preparando() {
    resultado.textContent = texto('preparando');
    resultado.className = 'trabajando';
    lectura.textContent = '';
    aMano.textContent = '';
    valoracion.textContent = '';
    enCurso = null;
    if (insertar) insertar.disabled = true;
    boton.disabled = true;
  }

  function decir(mensaje) {
    resultado.textContent = mensaje;
    resultado.className = '';
  }

  /**
   * Copia el prompt. **Chrome sólo deja escribir en el portapapeles con el panel enfocado**, y tras
   * esperar a la plataforma la persona puede estar ya en la página del asistente. Si no deja, se
   * enseña el prompt con su propio botón: un clic nuevo enfoca el panel y entonces sí copia.
   */
  async function copiar(prompt) {
    try {
      await navigator.clipboard.writeText(prompt);
      return true;
    } catch (e) {
      aMano.textContent = '';
      const caja = el('textarea', { id: 'prompt-a-mano', rows: '6', readonly: '', 'aria-label': texto('prompt') });
      caja.value = prompt;
      const copiarAMano = el('button', { id: 'copiar-a-mano', class: 'principal', texto: texto('copiar') });
      copiarAMano.addEventListener('click', async function () {
        try {
          await navigator.clipboard.writeText(prompt);
          aMano.textContent = '';
          decir(texto('copiado'));
        } catch (otro) {
          caja.focus();
          caja.select();
          decir(texto('copiaConTeclado'));
        }
      });
      aMano.appendChild(el('p', { class: 'nota', texto: texto('pulsaCopiar') }));
      aMano.appendChild(caja);
      aMano.appendChild(copiarAMano);
      return false;
    }
  }
  if (insertar) {
    insertar.addEventListener('click', async function () {
      preparando();
      try {
        const permiso = await chrome.permissions.request({ origins: [ad.origen + '/*'] });
        if (!permiso) throw new Error(texto('sinPermisoAsistente', [ad.nombre]));
        const pestana = await pestanaDelAsistente(ad);
        const r = await consultar(conf, elegido.id, pregunta.value.trim(), conAdjunto(), valoresDeLosDatos());
        empezarConsulta(r);
        if (!pestana) {
          const copiado = await copiar(r.prompt);
          decir(texto(copiado ? 'abreElAsistente' : 'sinAsistente', [ad.nombre]));
          return;
        }
        const previas = await enLaPagina(pestana, contarRespuestas, [ad.selectores]);
        const insercion = await enLaPagina(pestana, insertarEnElAsistente, [ad.selectores, r.prompt]);
        if (!insercion || !insercion.ok) {
          avisarDeUnFallo(conf, ad, (insercion && insercion.selector) || 'insercion');
          const copiado = await copiar(r.prompt);
          decir(texto(copiado ? 'insercionFallida' : 'insercionFallidaSinCopia', [ad.nombre]));
          return;
        }
        decir(texto(r.espera_adjunto ? 'insertadoConAdjunto' : 'insertado', [ad.nombre]));
        // La lectura no bloquea el panel: la persona puede tardar en enviar.
        const consulta = enCurso;
        enLaPagina(pestana, esperarRespuesta, [ad.selectores, previas, ESPERA_DE_LA_RESPUESTA_MS])
          .catch(function () {
            return { ok: false, motivo: 'sin_respuesta' };
          })
          .then(function (leida) {
            if (leida && leida.ok) {
              consulta.respuesta = leida.texto;
              lectura.textContent = texto('respuestaLeida', [String(leida.texto.length)]);
            } else {
              if (leida && leida.selector) avisarDeUnFallo(conf, ad, leida.selector);
              lectura.textContent = texto('respuestaNoLeida');
            }
            // En validación, la plataforma guarda lo leído; si no se pudo, por qué: cuenta la cobertura.
            if (consulta.modo === 'validacion') {
              guardarRespuesta(conf, consulta.id, loLeido(leida)).catch(function () {});
            }
          });
      } catch (e) {
        resultado.textContent = e.message;
        resultado.className = 'error';
        if (e instanceof Desconectado) await pintar();
      } finally {
        actualizar();
      }
    });
  }
  boton.addEventListener('click', async function () {
    preparando();
    try {
      const r = await consultar(conf, elegido.id, pregunta.value.trim(), conAdjunto(), valoresDeLosDatos());
      empezarConsulta(r);
      const copiado = await copiar(r.prompt);
      decir(copiado ? texto(r.espera_adjunto ? 'copiadoConAdjunto' : 'copiado') : texto('preparado'));
    } catch (e) {
      resultado.textContent = e.message;
      resultado.className = 'error';
      if (e instanceof Desconectado) await pintar();
    } finally {
      boton.disabled = false;
      actualizar();
    }
  });
  raiz.appendChild(el('label', { for: 'pregunta', texto: texto('pregunta') }));
  raiz.appendChild(datosCont);
  raiz.appendChild(pregunta);
  raiz.appendChild(adjuntaOpcional);
  raiz.appendChild(pista);
  if (insertar) raiz.appendChild(insertar);
  raiz.appendChild(boton);
  raiz.appendChild(resultado);
  raiz.appendChild(aMano);
  raiz.appendChild(lectura);
  raiz.appendChild(valoracion);
  raiz.appendChild(
    el('button', {
      texto: texto('desconectar'),
      onclick: async function () {
        await desconectar();
        await pintar();
      },
    })
  );

  function actualizar() {
    boton.disabled = !elegido || !pregunta.value.trim() || faltaUnObligatorio();
    if (insertar) insertar.disabled = boton.disabled;
    adjuntaOpcional.hidden = !(elegido && elegido.adjunto === 'opcional');
    pista.textContent = conAdjunto() ? texto('describeElAdjunto') : '';
  }
  actualizar();
}

if (typeof document !== 'undefined' && document.getElementById('raiz')) {
  pintar();
}
