@echo off
cd /d "%~dp0.."
title Pruebas manuales - Agentes de unidad (issues #172, #173 y #175)
echo.
echo ==========================================================
echo   AGENTES DE UNIDAD: PUBLICAR, INDICE Y CONSULTA
echo ==========================================================
echo.
echo POR QUE ESTE GUION EXISTE
echo.
echo   El agente ya verifico las pantallas en el navegador con
echo   cuentas y documentos de prueba: publicar, versionar, revisar,
echo   suspender, retirar, cargar el indice desde una hoja, y
echo   consultar y preparar el prompt con los embeddings de verdad.
echo   Lo que NO puede hacer es lo que sigue: pegar el prompt en el
echo   asistente general de la UJI y ver que abre tus documentos con
echo   TU cuenta. Eso solo lo puede comprobar una persona.
echo.
echo ANTES DE EMPEZAR
echo.
echo   1. Docker con la base de datos en pie, y backend y frontend
echo      arrancados (arranque.bat, opcion 1).
echo   2. Una cuenta de una organizacion con el modulo Agentes de
echo      unidad concedido (Plataforma - Modulos). Consultar no lo
echo      necesita: es de oficio.
echo   3. Los documentos, en TU Drive de la UJI (la misma cuenta con
echo      la que entras en Gemini). Se explica en la pantalla siguiente.
echo.
pause
echo.
echo ----------------------------------------------------------
echo  PREPARAR LOS DOCUMENTOS DE PRUEBA
echo ----------------------------------------------------------
echo.
echo   La plataforma no abre ningun documento: guarda los enlaces, y
echo   los abre Gemini con tu cuenta. Por eso van en tu Drive.
echo.
echo   a) Crea una carpeta, por ejemplo "Prueba agentes", y sube DOS
echo      documentos con contenido que conozcas (por ejemplo, PDF de
echo      normativa.uji.es). No hace falta compartirlos con nadie.
echo.
echo   b) Enlace de cada documento: clic derecho, Compartir, Copiar
echo      enlace. Queda asi:  https://drive.google.com/file/d/.../view
echo      Enlace de la carpeta: abrela y copia la direccion del
echo      navegador. Es el campo "Carpeta de documentos" del agente.
echo.
echo   c) Un TERCER enlace que no puedas abrir: copia el de uno de tus
echo      documentos y cambia unas letras del identificador. Ese
echo      fichero no existe, y sirve para ver la abstencion. (Tambien
echo      vale un documento de otra persona que no te hayan compartido.)
echo.
echo   d) La hoja del indice, en Excel o CSV, con las columnas
echo      url, titulo y resumen, una fila por enlace. Los resumenes
echo      los escribes tu, en dos lineas. Haz que el del enlace falso
echo      se parezca a lo que vas a preguntar, para que lo seleccione.
echo.
echo   e) Para el paso del adjunto, cualquier fichero de tu equipo:
echo      un pliego, una memoria, un borrador.
echo.
echo   SI GEMINI NO PUEDE ABRIR NINGUN ENLACE, ni siquiera los tuyos,
echo   apuntalo: puede que la conexion de Gemini con Drive no este
echo   activada en tu cuenta. Tambien es un resultado.
echo.
pause
echo.
echo ----------------------------------------------------------
echo  PASO 1 - Publicar un agente y cargar su indice
echo ----------------------------------------------------------
echo.
echo   1. Abre  http://localhost:5173/agentes/gestion  y publica un agente.
echo   2. Prepara una hoja (CSV o Excel) con las columnas url, titulo
echo      y resumen, una fila por documento, con los tres enlaces.
echo   3. Pulsa "Cargar el indice" y sube la hoja.
echo.
echo QUE DEBES VER: "Indice cargado: 3 nuevas..." y "3 fichas" en la
echo ficha del agente. Si vuelves a subir la misma hoja: "3 sin
echo cambios".
echo.
pause
echo.
echo ----------------------------------------------------------
echo  PASO 2 - Consultar y pegar en el asistente general (el que importa)
echo ----------------------------------------------------------
echo.
echo   1. Abre  http://localhost:5173/agentes/consultar
echo   2. Elige el agente, escribe una pregunta que respondan tus
echo      documentos y pulsa "Preparar el prompt".
echo   3. Pulsa "Copiar el prompt". Debe decir "Copiado".
echo   4. Pegalo en el asistente general de la UJI (Gemini) con tu
echo      cuenta institucional.
echo.
echo QUE DEBES VER:
echo   - El asistente abre los documentos enlazados y responde a
echo     partir de ellos.
echo   - Si el prompt enlaza el documento que NO puedes abrir, el
echo     asistente DICE que no puede abrirlo, y no se inventa la
echo     respuesta. Esa es la instruccion de abstencion.
echo.
echo APUNTA: cuantos enlaces abrio de verdad, y si alguna vez
echo contesto sin poder abrir un documento. Sirve para fijar el
echo presupuesto de documentos por consulta, que la #175 deja por medir.
echo.
pause
echo.
echo ----------------------------------------------------------
echo  PASO 3 - Un agente de revision, con documento adjunto
echo ----------------------------------------------------------
echo.
echo   1. Publica otro agente y marca "Quien consulta adjuntara un
echo      documento". Cargale el indice con la normativa del paso 1.
echo   2. En Agentes - Consultar, eligelo, describe en la pregunta el
echo      documento que vas a adjuntar y prepara el prompt.
echo   3. Pega el prompt en el asistente general y, en el MISMO
echo      mensaje, adjunta un documento de prueba (un pliego, una
echo      memoria...). Repite una vez SIN adjuntarlo.
echo.
echo QUE DEBES VER:
echo   - Con el adjunto: lo analiza usando como criterio los
echo     documentos enlazados.
echo   - Sin el adjunto: dice que no le ha llegado el documento, y
echo     no se inventa la revision.
echo.
pause
echo.
echo ----------------------------------------------------------
echo  PASO 4 - El guion que mantiene el indice (issue #174)
echo ----------------------------------------------------------
echo.
echo   OJO: el guion corre en los servidores de Google y NO puede
echo   llegar a tu localhost. Este paso se hace contra PRODUCCION
echo   despues de desplegar, o contra un entorno publicado.
echo.
echo   1. En Agentes - Publicar y gestionar, pulsa "Actualizacion del
echo      indice" en tu agente. Apunta el identificador del agente y
echo      la direccion de la plataforma. Pulsa "Ver el guion".
echo   2. Crea una hoja de calculo junto a la carpeta del agente y,
echo      desde ella, Extensiones - Apps Script. Pega el guion y, en
echo      Configuracion del proyecto, el manifiesto (appsscript.json).
echo   3. Pulsa "Emitir un token para el guion" y copialo: solo se ve
echo      una vez.
echo   4. En Propiedades del guion pon PLATAFORMA_URL, AGENTE_ID, TOKEN,
echo      CARPETA_ID, HOJA_ID y PROYECTO_GCP (un proyecto con Vertex AI
echo      activado). La cabecera del guion lo explica.
echo   5. Ejecuta actualizarIndice. La primera vez pide permisos.
echo.
echo QUE DEBES VER:
echo   - La hoja se llena con una fila por documento y su resumen.
echo   - En la plataforma, el agente dice "actualizado
echo     automaticamente" y, si hay documentos que no sabe leer (fotos,
echo     Word), cuantos faltan.
echo   - Marca un documento como "no" en la columna vigente de la hoja,
echo     ejecuta otra vez actualizarIndice y comprueba que ese documento
echo     ya no sale en la consulta.
echo.
echo   6. Ejecuta instalarActualizacionDiaria y, al dia siguiente,
echo      comprueba que la fecha de actualizacion ha cambiado sola.
echo.
echo APUNTA: cuanto tardo la primera pasada y cuantos documentos
echo resumio. Es la medida de las cuotas que la #174 pedia tomar con la
echo primera unidad antes de replicar.
echo.
pause
echo.
echo ----------------------------------------------------------
echo  PASO 5 - El asistente que propone el prompt (issue #213)
echo ----------------------------------------------------------
echo.
echo   1. Al publicar un agente, pulsa "Redactar con ayuda de IA" y
echo      describe con tus palabras para que lo quieres. Prueba uno de
echo      preguntas y otro de revision con adjunto.
echo   2. Pulsa "Proponer un prompt".
echo.
echo QUE DEBES VER:
echo   - Una propuesta en el campo del prompt, que puedes editar.
echo   - Que no repite la instruccion de abstencion ni lista enlaces:
echo     eso lo anade la plataforma.
echo   - Al publicar, la ficha dice "Prompt redactado con ayuda de IA".
echo.
echo JUZGA: si la propuesta te ahorra trabajo y si la publicarias con
echo pocos cambios. Es la medida que decide si el asistente sirve.
echo.
pause
echo.
echo ----------------------------------------------------------
echo  PASO 6 - El texto en valenciano
echo ----------------------------------------------------------
echo.
echo   1. Cambia el idioma de la pantalla a Valencia.
echo   2. Repite la consulta del paso 2.
echo.
echo QUE DEBES VER: las instrucciones que anade la plataforma al
echo prompt (la pregunta, la lista de documentos y la abstencion) en
echo un valenciano que publicarias. El tono es juicio tuyo.
echo.
pause
echo.
echo ----------------------------------------------------------
echo  PASO 7 - La extension del navegador (issue #176)
echo ----------------------------------------------------------
echo.
echo   1. En Chrome, abre chrome://extensions, activa "Modo de
echo      desarrollador" y pulsa "Cargar descomprimida". Elige la
echo      carpeta extension\ del repositorio.
echo   2. Copia el ID que Chrome le pone. En server\.env anade
echo      AGENTES_EXTENSION_IDS=ese-id y reinicia el backend.
echo   3. Pulsa el icono de la extension: se abre un panel lateral.
echo      Escribe la direccion del panel (http://localhost:5173) y
echo      pulsa Guardar y luego Conectar. Chrome te pedira permiso para
echo      hablar con localhost: aceptalo.
echo   4. En la ventana que se abre, entra si hace falta y pulsa
echo      "Conectar".
echo   5. Abre Gemini en la pestana activa. En el panel lateral, elige un
echo      agente, escribe una pregunta y pulsa "Insertar en Gemini". Chrome
echo      pedira permiso sobre gemini.google.com: aceptalo. Revisa el texto
echo      en Gemini y envialo tu.
echo   6. En el panel web, Agentes - Consultar: abajo, "Extension del
echo      navegador". Pulsa Desconectar y vuelve a usar la extension.
echo.
echo QUE DEBES VER:
echo   - Si no tenias sesion, tras entrar vuelves a la pagina de
echo     conexion, no a tu primer modulo.
echo   - El panel lateral lista los mismos agentes que "Consultar".
echo   - El prompt aparece en el cuadro de Gemini, sin enviarse.
echo   - Tras la respuesta, el panel dice "Respuesta leida (N caracteres)".
echo   - Con Gemini en otra pestana, "Insertar" copia y te pide abrirlo.
echo   - En "Consultar" aparece la conexion, con su caducidad.
echo   - Tras desconectarla alli, la extension pide conectar de nuevo.
echo   - Con el login de Google tambien vuelves a la pagina de conexion.
echo.
echo   - Como superadministrador: Agentes - Integracion con Gemini dice
echo     "Sin fallos en esta version".
echo.
echo JUZGA: si insertar y leer funcionan con tus agentes reales durante
echo unos dias. Es la prueba que decide si el modulo sigue (issue #215).
echo.
pause
echo.
echo ----------------------------------------------------------
echo  PASO 8 - Las conversaciones: validacion e incidencias (#216)
echo ----------------------------------------------------------
echo.
echo   1. En chrome://extensions, recarga la extension (flecha circular)
echo      y vuelve a abrir el panel lateral.
echo   2. En el panel: el agente lleva la marca "En validacion".
echo      Insertalo en Gemini, envialo y espera la respuesta.
echo   3. Pulsa "Si" o "No" en "Te ha servido la respuesta?". Con "No",
echo      elige un motivo, escribe un comentario y envia el informe.
echo   4. En el panel web, Agentes - Publicar y gestionar: la ficha dice
echo      "Registro de conversaciones: En validacion". Pulsa "Pasar a solo
echo      incidencias" y repite los pasos 2 y 3.
echo.
echo QUE DEBES VER:
echo   - En validacion, el panel avisa de que se guardan la pregunta y
echo     la respuesta; en solo incidencias, no.
echo   - Los motivos salen en tu idioma.
echo   - Tras enviar: "Gracias" o "Informe enviado".
echo.
echo JUZGA: si el aviso es claro para quien usa el agente, y si los
echo motivos cubren lo que te ha fallado. Lo que se guarda lo veras en
echo la pantalla de calidad (#217).
echo.
pause
echo.
echo ----------------------------------------------------------
echo  PASO 9 - La lengua de la respuesta y el adjunto (#218)
echo ----------------------------------------------------------
echo.
echo   1. En Publicar y gestionar, publica o versiona un agente con
echo      "Lengua de la respuesta: Siempre en castellano" y
echo      "Documento adjunto: Puede adjuntar un documento".
echo   2. Recarga la extension. Elige ese agente y pregunta en
echo      valenciano. Inserta en Gemini sin marcar "Adjuntare un
echo      document" y envialo.
echo   3. Repite marcando la casilla y adjuntando un documento.
echo.
echo QUE DEBES VER:
echo   - La respuesta en castellano aunque preguntes en valenciano.
echo   - Sin marcar, el prompt no habla de adjunto; marcada, pide
echo     analizar tu documento con los de la carpeta.
echo   - La ficha del agente dice la lengua y el adjunto.
echo.
echo JUZGA: si el asistente de prompts propone algo coherente con lo
echo declarado, sin repetir la instruccion de lengua.
echo.
pause
echo.
echo ----------------------------------------------------------
echo  PASO 10 - Los datos de la consulta (#219)
echo ----------------------------------------------------------
echo.
echo   1. Versiona un agente de pliegos. En "Datos de la consulta":
echo      - "Tipo de contrato", lista con "Obras, Servicios, Suministros",
echo        obligatorio, columna del indice "Tipo de contrato".
echo      - "Codigo CPV", texto, "Casa por el principio", columna "CPV".
echo      Escribe unas indicaciones.
echo   2. Sube una hoja del indice con columnas "Tipo de contrato" y
echo      "CPV" en algunos documentos (y otros sin rellenar).
echo   3. En la extension (recargala) y en Consultar: elige el agente,
echo      rellena los datos y pregunta.
echo.
echo QUE DEBES VER:
echo   - Las indicaciones y el formulario, sin poder preparar el prompt
echo     hasta elegir el tipo de contrato.
echo   - El prompt con "Datos de la consulta".
echo   - Ningun documento de otro tipo de contrato o de otro CPV; si
echo     los que no tienen el dato rellenado.
echo.
echo JUZGA: si los documentos elegidos son mejores que sin los datos.
echo.
pause
echo.
echo ==========================================================
echo   FIN. Anota lo que no cuadre en las issues del hito 5.
echo ==========================================================
echo.
pause
