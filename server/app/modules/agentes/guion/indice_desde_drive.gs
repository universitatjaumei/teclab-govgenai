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
 *   **Los datos de la consulta** (#220): si el agente declara datos ligados a una columna del
 *   índice —tipo de contrato, CPV—, el guion añade esas columnas y los extrae del documento al
 *   resumirlo. Lo que la unidad escriba en ellas **se respeta**: el guion apunta en
 *   `datos_extraidos` lo último que extrajo, y sólo vuelve a escribir una celda que sigue teniendo
 *   eso (o está vacía); si la unidad la cambió, la deja. Para que vuelva a extraer un valor
 *   corregido a mano, basta con vaciar la celda. Cualquier otra columna que la unidad añada se
 *   conserva y va a la plataforma como dato del documento.
 *
 * QUÉ NO HACE
 *   No regenera los resúmenes cuando cambia el prompt de resumen: sería cientos de llamadas contra
 *   la cuota de la unidad sin que nadie lo pidiera. Para eso está `regenerarResumenes`, a mano.
 */

const VERSION_DEL_GUION = 'indice-v2';

/** La línea que separa el resumen de los datos extraídos: el resumen se embebe, los datos no. */
const SEPARADOR_DE_DATOS = '---DATOS---';

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
  // #220 — lo último que extrajo el guion de cada documento: distingue lo extraído de lo corregido.
  'datos_extraidos',
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
  const extraer = prompt.datos || [];
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
      const leido = separar(resumir_(conf, prompt, fichero), extraer);
      // Se parte de la fila que había: sus columnas de más y lo escrito a mano se conservan.
      const anterior = porId[fichero.id] || {};
      const fila = Object.assign({}, anterior, {
        url: fichero.url,
        titulo: fichero.nombre,
        resumen: leido.resumen,
        vigente: anterior.vigente || 'sí',
        revision_prevista_en: anterior.revision_prevista_en || '',
        id_fichero: fichero.id,
        modificado: fichero.modificado,
        version_prompt_resumen: prompt.version,
        modelo_resumen: conf.modelo,
      });
      // Se reescribe lo que extrajo el guion la vez anterior, y se respeta lo que cambió la unidad.
      const previos = leerJson_(anterior.datos_extraidos);
      const extraidos = {};
      extraer.forEach(function (d) {
        const nuevo = leido.valores[d.columna] || '';
        const actual = texto_(anterior[d.columna]);
        if (!actual || actual === texto_(previos[d.columna])) fila[d.columna] = nuevo;
        extraidos[d.columna] = nuevo;
      });
      if (extraer.length) fila.datos_extraidos = JSON.stringify(extraidos);
      porId[fichero.id] = fila;
    } catch (fallo) {
      // Un documento que falla no para la pasada, pero **sale del índice**: si se quedara la ficha
      // de antes, un documento que cambió y no se pudo resumir parecería al día. Así la plataforma lo
      // cuenta como que falta, y la pasada siguiente lo vuelve a intentar.
      delete porId[fichero.id];
      Logger.log('No se ha podido resumir «' + fichero.nombre + '»: ' + fallo);
    }
  }

  const finales = plan.orden.map(function (id) {
    return porId[id];
  }).filter(Boolean);
  escribirFilas_(hoja, finales, columnasDeMas(extraer, filas));
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
  escribirFilas_(hoja, filas, columnasDeMas(prompt.datos || [], filas));
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

/**
 * Separa el resumen de los datos que el modelo puso detrás de `SEPARADOR_DE_DATOS` (#220).
 * **El resumen nunca lleva los datos**: es lo que se embebe. En una lista sólo vale una de sus
 * opciones —escrita como sea—; lo que no lo es, o lo que el modelo deja vacío, queda vacío.
 */
function separar(texto, extraer) {
  const lineas = String(texto || '').split('\n');
  const corte = lineas.findIndex(function (l) {
    return l.trim() === SEPARADOR_DE_DATOS;
  });
  const valores = {};
  if (corte < 0) return { resumen: String(texto || '').trim(), valores: valores };
  const porNombre = {};
  extraer.forEach(function (d) {
    porNombre[normalizar_(d.columna)] = d;
  });
  lineas.slice(corte + 1).forEach(function (linea) {
    const m = linea.match(/^\s*[-*]?\s*([^:]+):\s*(.*)$/);
    if (!m) return;
    const dato = porNombre[normalizar_(m[1])];
    if (!dato) return;
    let valor = m[2].trim().replace(/^[«"']+|[»"'.]+$/g, '').trim();
    if (/^(n\/a|no consta|desconocido|-+)$/i.test(valor)) valor = '';
    if (dato.tipo === 'opciones') {
      const opcion = (dato.opciones || []).find(function (o) {
        return normalizar_(o) === normalizar_(valor);
      });
      valor = opcion || '';
    }
    valores[dato.columna] = valor;
  });
  return { resumen: lineas.slice(0, corte).join('\n').trim(), valores: valores };
}

/** Las columnas que no son del guion: las de los datos y las que haya añadido la unidad. */
function columnasDeMas(extraer, filas) {
  const de_mas = extraer.map(function (d) {
    return d.columna;
  });
  filas.forEach(function (f) {
    Object.keys(f).forEach(function (c) {
      if (c && COLUMNAS.indexOf(c) < 0 && de_mas.indexOf(c) < 0) de_mas.push(c);
    });
  });
  return de_mas;
}

function texto_(valor) {
  return String(valor === undefined || valor === null ? '' : valor).trim();
}

function leerJson_(valor) {
  try {
    return valor ? JSON.parse(valor) : {};
  } catch (e) {
    return {};
  }
}

function normalizar_(texto) {
  return String(texto || '')
    .normalize('NFKD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, ' ')
    .trim();
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
      // #220 — las columnas de más, los datos de la consulta entre ellas, van como datos del
      // documento: son lo que filtra la consulta, y no se embeben.
      const metadatos = {};
      Object.keys(f).forEach(function (c) {
        if (COLUMNAS.indexOf(c) < 0 && String(f[c] === undefined || f[c] === null ? '' : f[c]).trim()) {
          metadatos[c] = String(f[c]).trim();
        }
      });
      if (Object.keys(metadatos).length) ficha.metadatos = metadatos;
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
  // El del agente (#220): si declara datos que extraer, el prompt los pide.
  const respuesta = UrlFetchApp.fetch(conf.plataforma + '/api/v1/agentes/prompt-de-resumen?agente_id=' + encodeURIComponent(conf.agenteId), {
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
    const exportado = UrlFetchApp.fetch(
      'https://www.googleapis.com/drive/v3/files/' + fichero.id + '/export?mimeType=text/plain',
      { headers: { Authorization: 'Bearer ' + ScriptApp.getOAuthToken() }, muteHttpExceptions: true },
    );
    // Un 403, 429 o 5xx trae un cuerpo de error: resumirlo daría una ficha con buena cara.
    if (exportado.getResponseCode() !== 200) {
      throw new Error('Drive no ha exportado el documento (' + exportado.getResponseCode() + ')');
    }
    partes.push({ text: exportado.getContentText() });
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

function escribirFilas_(hoja, filas, deMas) {
  const columnas = COLUMNAS.concat(deMas || []);
  const valores = [columnas].concat(
    filas.map(function (f) {
      return columnas.map(function (c) {
        return f[c] === undefined || f[c] === null ? '' : f[c];
      });
    }),
  );
  hoja.clearContents();
  hoja.getRange(1, 1, valores.length, columnas.length).setValues(valores);
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
