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
echo  PASO 4 - El texto en valenciano
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
echo ==========================================================
echo   FIN. Anota lo que no cuadre en la issue #176, que es la
echo   siguiente del hito y la que mide el uso real.
echo ==========================================================
echo.
pause
