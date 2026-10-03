/**
 * Panel lateral de la extensión de agentes de unidad — Gov Gen AI Platform (#176).
 *
 * La biblioteca: los agentes que la plataforma ofrece al colectivo de quien mira. Se elige uno, se
 * escribe la pregunta, y la extensión **pide el prompt vigente a la API** —que es lo que queda
 * registrado— y lo copia para pegarlo en el asistente general. Por eso existe la extensión: con
 * copiar y pegar a mano, quien reutiliza un prompt viejo no vuelve a pasar por la plataforma, y el
 * registro subcuenta y el prompt se queda desfasado.
 *
 * **No toca la interfaz del asistente** (decisión del usuario, 2026-10-03): inyectar en su cuadro
 * de texto depende de lo que permitan sus condiciones y es lo frágil. **No es un control de
 * acceso**: cualquiera puede usar el asistente sin la extensión.
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

function consultar(conf, agenteId, pregunta) {
  return llamar(conf, '/api/v1/agentes/' + agenteId + '/consulta', {
    method: 'POST',
    cuerpo: { consulta: pregunta, lengua: lengua() },
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
      actualizar();
    });
    const avisos = [];
    if (a.espera_adjunto) avisos.push(el('span', { class: 'aviso', texto: texto('conAdjunto') }));
    if (a.revision_vencida) avisos.push(el('span', { class: 'aviso', texto: texto('revisionVencida') }));
    if (a.indice_sin_actualizar) avisos.push(el('span', { class: 'aviso', texto: texto('indiceSinActualizar') }));
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

  const pregunta = el('textarea', { id: 'pregunta', rows: '3', maxlength: '2000', 'aria-label': texto('pregunta') });
  const pista = el('p', { class: 'nota' });
  const boton = el('button', { class: 'principal', id: 'preparar', texto: texto('preparar') });
  const resultado = el('p', { role: 'status' });
  pregunta.addEventListener('input', actualizar);
  boton.addEventListener('click', async function () {
    resultado.textContent = '';
    resultado.className = '';
    boton.disabled = true;
    try {
      const r = await consultar(conf, elegido.id, pregunta.value.trim());
      await navigator.clipboard.writeText(r.prompt);
      resultado.textContent = r.espera_adjunto ? texto('copiadoConAdjunto') : texto('copiado');
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
  raiz.appendChild(pregunta);
  raiz.appendChild(pista);
  raiz.appendChild(boton);
  raiz.appendChild(resultado);
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
    boton.disabled = !elegido || !pregunta.value.trim();
    pista.textContent = elegido && elegido.espera_adjunto ? texto('describeElAdjunto') : '';
  }
  actualizar();
}

if (typeof document !== 'undefined' && document.getElementById('raiz')) {
  pintar();
}
