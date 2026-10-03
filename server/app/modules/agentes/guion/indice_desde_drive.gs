/**
 * Guion del índice de un agente de unidad — Gov Gen AI Platform (#174).
 *
 * Mantiene el índice de un agente a partir de una carpeta de Drive: recorre la carpeta, resume con
 * Gemini lo nuevo o cambiado, lo apunta en una hoja de cálculo y manda el índice completo a la
 * plataforma. Corre con la cuenta de la unidad, así que ve exactamente lo que ve la unidad, y **los
 * documentos no salen de Google**: a la plataforma sólo llegan la URL, el título y el resumen.
 *
 * CÓMO SE INSTALA
 *   1. Crea una hoja de cálculo vacía junto a la carpeta y, desde ella, Extensiones › Apps Script.
 *      Mejor en una unidad compartida o con una cuenta de grupo: un guion atado a una cuenta
 *      personal desaparece cuando esa persona se va.
 *   2. Pega este código. Configuración del proyecto › marca «Mostrar appsscript.json» y pega el
 *      manifiesto que da la plataforma.
 *   3. Propiedades del guion (Configuración del proyecto › Propiedades del guion):
 *        PLATAFORMA_URL  la dirección de la plataforma, tal como la da su pantalla de actualización
 *        AGENTE_ID       el identificador del agente (lo da la plataforma)
 *        TOKEN           el token del guion (Agentes › Publicar y gestionar › Actualización automática)
 *        CARPETA_ID      el identificador de la carpeta (lo que va tras /folders/ en su dirección)
 *        HOJA_ID         el identificador de esta hoja (lo que va tras /d/ en su dirección)
 *        PROYECTO_GCP    el proyecto de Google Cloud con Vertex AI activado
 *        REGION          opcional; por defecto europe-southwest1
 *        MODELO          opcional; por defecto gemini-2.5-flash
 *   4. Ejecuta una vez `actualizarIndice` para autorizarlo y ver que funciona, y después
 *      `instalarActualizacionDiaria`, que lo programa para cada mañana.
 *
 * LA HOJA
 *   El guion escribe los resúmenes. **La unidad puede escribir a mano** la columna `vigente`
 *   («no» para lo superado) y `revision_prevista_en`, y el guion lo respeta y lo manda.
 *
 * QUÉ NO HACE
 *   No regenera los resúmenes cuando cambia el prompt de resumen: sería cientos de llamadas contra
 *   la cuota de la unidad sin que nadie lo pidiera. Para eso está `regenerarResumenes`, a mano.
 */

const VERSION_DEL_GUION = 'indice-v1';

/** Por debajo de los 6 minutos que Apps Script deja por ejecución, con margen para escribir. */
const MAXIMO_MS = 4.5 * 60 * 1000;

/** Más que esto no cabe con holgura en una petición a Vertex. */
const MAXIMO_BYTES = 15 * 1024 * 1024;

const COLUMNAS = [
  'url',
  'titulo',
  'resumen',
  'vigente',
  'revision_prevista_en',
  'id_fichero',
  'modificado',
  'version_prompt_resumen',
  'modelo_resumen',
];

const LEGIBLES = {
  'application/pdf': 'pdf',
  'application/vnd.google-apps.document': 'documento',
  'text/plain': 'texto',
  'text/markdown': 'texto',
};

// =============================================================================
//  Lo que se ejecuta
// =============================================================================

/** La pasada de cada día: resume lo nuevo o cambiado y manda el índice. */
function actualizarIndice() {
  const inicio = Date.now();
  const conf = configuracion_();
  const prompt = promptDeResumen_(conf);
  const ficheros = ficherosDeLaCarpeta_(conf.carpetaId);
  const hoja = SpreadsheetApp.openById(conf.hojaId).getSheets()[0];
  const filas = leerFilas_(hoja);

  const plan = planificar(ficheros, filas);
  const porId = {};
  plan.filas.forEach(function (f) {
    porId[f.id_fichero] = f;
  });

  for (let i = 0; i < plan.porResumir.length; i++) {
    // Se mira ANTES de empezar cada uno: lo que no quepa, lo hará la pasada siguiente.
    if (Date.now() - inicio >= MAXIMO_MS) {
      Logger.log('Límite de tiempo: quedan ' + (plan.porResumir.length - i) + ' para la próxima pasada.');
      break;
    }
    const fichero = plan.porResumir[i];
    try {
      const resumen = resumir_(conf, prompt, fichero);
      porId[fichero.id] = {
        url: fichero.url,
        titulo: fichero.nombre,
        resumen: resumen,
        vigente: (porId[fichero.id] && porId[fichero.id].vigente) || 'sí',
        revision_prevista_en: (porId[fichero.id] && porId[fichero.id].revision_prevista_en) || '',
        id_fichero: fichero.id,
        modificado: fichero.modificado,
        version_prompt_resumen: prompt.version,
        modelo_resumen: conf.modelo,
      };
    } catch (fallo) {
      // Un documento que falla no para la pasada: se queda sin ficha, y la plataforma lo cuenta.
      Logger.log('No se ha podido resumir «' + fichero.nombre + '»: ' + fallo);
    }
  }

  const finales = plan.orden.map(function (id) {
    return porId[id];
  }).filter(Boolean);
  escribirFilas_(hoja, finales);
  mandarIndice_(conf, componerIndice(finales, ficheros.length));
}

/**
 * Vuelve a resumir lo que se resumió con una versión del prompt que ya no es la vigente.
 * **A mano**: es decisión de la unidad cuándo gastar esa cuota.
 */
function regenerarResumenes() {
  const conf = configuracion_();
  const prompt = promptDeResumen_(conf);
  const hoja = SpreadsheetApp.openById(conf.hojaId).getSheets()[0];
  const filas = leerFilas_(hoja).map(function (f) {
    if (f.version_prompt_resumen && f.version_prompt_resumen !== prompt.version) {
      f.resumen = '';
    }
    return f;
  });
  escribirFilas_(hoja, filas);
  actualizarIndice();
}

/** Programa `actualizarIndice` cada mañana. Se puede ejecutar más de una vez sin duplicarlo. */
function instalarActualizacionDiaria() {
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction && t.getHandlerFunction() === 'actualizarIndice') {
      ScriptApp.deleteTrigger(t);
    }
  });
  ScriptApp.newTrigger('actualizarIndice').timeBased().everyDays(1).atHour(6).create();
}

// =============================================================================
//  Lo que decide (sin tocar Google: se prueba fuera)
// =============================================================================

/**
 * Qué hay que resumir y qué filas siguen. Se resume lo nuevo, lo cambiado desde su resumen y lo
 * que no tiene resumen; **no** lo resumido con otra versión del prompt (eso es `regenerarResumenes`).
 * Lo que ya no está en la carpeta, se va.
 */
function planificar(ficheros, filas) {
  const porId = {};
  filas.forEach(function (f) {
    if (f.id_fichero) porId[f.id_fichero] = f;
  });
  const porResumir = [];
  const siguen = [];
  const orden = [];
  ficheros.forEach(function (fichero) {
    if (!fichero.legible) return;
    orden.push(fichero.id);
    const fila = porId[fichero.id];
    if (fila) {
      // El título y la dirección los manda Drive; lo demás es de la fila.
      fila.url = fichero.url;
      fila.titulo = fichero.nombre;
      siguen.push(fila);
    }
    if (!fila || !fila.resumen || String(fichero.modificado) > String(fila.modificado)) {
      porResumir.push(fichero);
    }
  });
  return { porResumir: porResumir, filas: siguen, orden: orden };
}

/** El cuerpo que espera la plataforma: el estado completo y cuántos documentos hay en la carpeta. */
function componerIndice(filas, documentosEnCarpeta) {
  const fichas = filas
    .filter(function (f) {
      return f.resumen && String(f.resumen).trim();
    })
    .map(function (f) {
      const ficha = {
        url: f.url,
        titulo: f.titulo,
        resumen: String(f.resumen).trim(),
        vigente: vigente_(f.vigente),
        version_prompt_resumen: f.version_prompt_resumen || null,
        modelo_resumen: f.modelo_resumen || null,
      };
      const revision = fecha_(f.revision_prevista_en);
      if (revision) ficha.revision_prevista_en = revision;
      return ficha;
    });
  return { fichas: fichas, documentos_en_carpeta: documentosEnCarpeta };
}

function vigente_(valor) {
  if (valor === true || valor === false) return valor;
  const texto = String(valor || '').trim().toLowerCase();
  return !(texto === 'no' || texto === 'false' || texto === 'no vigente' || texto === 'derogado' || texto === 'superado');
}

function fecha_(valor) {
  if (!valor) return null;
  // Una celda de fecha llega como objeto fecha, a medianoche **en la zona del guion**: pasada a
  // UTC, el 31 de enero en Madrid sería el 30. Se mira la forma y no la clase.
  if (typeof valor.getTime === 'function') {
    return Utilities.formatDate(valor, Session.getScriptTimeZone(), 'yyyy-MM-dd');
  }
  const texto = String(valor).trim();
  if (/^\d{4}-\d{2}-\d{2}/.test(texto)) return texto.slice(0, 10);
  const partes = texto.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})$/);
  if (partes) return partes[3] + '-' + ('0' + partes[2]).slice(-2) + '-' + ('0' + partes[1]).slice(-2);
  return null;
}

// =============================================================================
//  Lo que habla con Google y con la plataforma
// =============================================================================

function configuracion_() {
  const p = PropertiesService.getScriptProperties();
  const conf = {
    plataforma: String(p.getProperty('PLATAFORMA_URL') || '').replace(/\/+$/, ''),
    agenteId: p.getProperty('AGENTE_ID'),
    token: p.getProperty('TOKEN'),
    carpetaId: p.getProperty('CARPETA_ID'),
    hojaId: p.getProperty('HOJA_ID'),
    proyecto: p.getProperty('PROYECTO_GCP'),
    region: p.getProperty('REGION') || 'europe-southwest1',
    modelo: p.getProperty('MODELO') || 'gemini-2.5-flash',
    propiedades: p,
  };
  ['plataforma', 'agenteId', 'token', 'carpetaId', 'hojaId', 'proyecto'].forEach(function (k) {
    if (!conf[k]) throw new Error('Falta una propiedad del guion: mira las instrucciones de la cabecera (' + k + ').');
  });
  return conf;
}

/** El prompt vigente; si la plataforma no responde, el último guardado, **con su versión**. */
function promptDeResumen_(conf) {
  const respuesta = UrlFetchApp.fetch(conf.plataforma + '/api/v1/agentes/prompt-de-resumen', {
    method: 'get',
    headers: { Authorization: 'Bearer ' + conf.token },
    muteHttpExceptions: true,
  });
  if (respuesta.getResponseCode() === 200) {
    const prompt = JSON.parse(respuesta.getContentText());
    conf.propiedades.setProperty('PROMPT_CACHEADO', JSON.stringify(prompt));
    return prompt;
  }
  const guardado = conf.propiedades.getProperty('PROMPT_CACHEADO');
  if (guardado) {
    Logger.log('La plataforma no ha respondido: se usa el último prompt guardado.');
    return JSON.parse(guardado);
  }
  throw new Error('La plataforma no ha dado el prompt de resumen (' + respuesta.getResponseCode() + ') y no hay uno guardado.');
}

function ficherosDeLaCarpeta_(carpetaId) {
  const ficheros = [];
  const it = DriveApp.getFolderById(carpetaId).getFiles();
  while (it.hasNext()) {
    const f = it.next();
    const tipo = LEGIBLES[f.getMimeType()];
    const tamano = f.getSize ? f.getSize() : 0;
    ficheros.push({
      id: f.getId(),
      nombre: f.getName(),
      mime: f.getMimeType(),
      url: f.getUrl(),
      modificado: f.getLastUpdated().toISOString(),
      // Lo que no se sabe leer cuenta en la carpeta, pero no tendrá ficha: la plataforma dirá que falta.
      legible: Boolean(tipo) && (tipo === 'documento' || tamano <= MAXIMO_BYTES),
    });
  }
  return ficheros;
}

function resumir_(conf, prompt, fichero) {
  const partes = [{ text: prompt.texto }, { text: 'Documento: ' + fichero.nombre }];
  if (LEGIBLES[fichero.mime] === 'documento') {
    const texto = UrlFetchApp.fetch(
      'https://www.googleapis.com/drive/v3/files/' + fichero.id + '/export?mimeType=text/plain',
      { headers: { Authorization: 'Bearer ' + ScriptApp.getOAuthToken() }, muteHttpExceptions: true },
    ).getContentText();
    partes.push({ text: texto });
  } else {
    const bytes = DriveApp.getFileById ? DriveApp.getFileById(fichero.id).getBlob().getBytes() : [];
    partes.push({ inlineData: { mimeType: fichero.mime, data: Utilities.base64Encode(bytes) } });
  }
  const url =
    'https://' + conf.region + '-aiplatform.googleapis.com/v1/projects/' + conf.proyecto +
    '/locations/' + conf.region + '/publishers/google/models/' + conf.modelo + ':generateContent';
  const respuesta = UrlFetchApp.fetch(url, {
    method: 'post',
    contentType: 'application/json',
    headers: { Authorization: 'Bearer ' + ScriptApp.getOAuthToken() },
    payload: JSON.stringify({ contents: [{ role: 'user', parts: partes }] }),
    muteHttpExceptions: true,
  });
  if (respuesta.getResponseCode() !== 200) {
    throw new Error('Vertex respondió ' + respuesta.getResponseCode() + ': ' + respuesta.getContentText());
  }
  const cuerpo = JSON.parse(respuesta.getContentText());
  const texto = cuerpo.candidates[0].content.parts.map(function (p) {
    return p.text || '';
  }).join('').trim();
  if (!texto) throw new Error('el modelo no devolvió resumen');
  return texto;
}

function leerFilas_(hoja) {
  const valores = hoja.getDataRange().getValues();
  if (!valores.length || !valores[0].length || valores[0][0] === '') return [];
  const cabecera = valores[0].map(String);
  return valores.slice(1).map(function (fila) {
    const registro = {};
    cabecera.forEach(function (columna, i) {
      registro[columna] = fila[i];
    });
    return registro;
  });
}

function escribirFilas_(hoja, filas) {
  const valores = [COLUMNAS].concat(
    filas.map(function (f) {
      return COLUMNAS.map(function (c) {
        return f[c] === undefined || f[c] === null ? '' : f[c];
      });
    }),
  );
  hoja.clearContents();
  hoja.getRange(1, 1, valores.length, COLUMNAS.length).setValues(valores);
}

function mandarIndice_(conf, cuerpo) {
  const respuesta = UrlFetchApp.fetch(conf.plataforma + '/api/v1/agentes/' + conf.agenteId + '/indice', {
    method: 'put',
    contentType: 'application/json',
    headers: { Authorization: 'Bearer ' + conf.token },
    payload: JSON.stringify(cuerpo),
    muteHttpExceptions: true,
  });
  if (respuesta.getResponseCode() >= 300) {
    // Que falle a la vista: Apps Script avisa por correo de las ejecuciones fallidas.
    throw new Error('La plataforma no ha aceptado el índice (' + respuesta.getResponseCode() + '): ' + respuesta.getContentText());
  }
}
