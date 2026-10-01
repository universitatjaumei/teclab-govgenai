@echo off
cd /d "%~dp0.."
title Pruebas manuales - Utilidades (issues #190 y #191)
echo.
echo ==========================================================
echo   UTILIDADES: PDF Y ANONIMIZAR UN FICHERO
echo ==========================================================
echo.
echo POR QUE ESTE GUION EXISTE
echo.
echo   El agente ya verifico las dos pantallas en el navegador con
echo   ficheros sinteticos: unir, dividir, optimizar, y anonimizar de
echo   punta a punta. Lo que NO puede hacer es lo que sigue, porque
echo   lleva datos personales reales o pide criterio de una persona.
echo.
echo ANTES DE EMPEZAR
echo.
echo   1. Docker con la base de datos en pie, y backend y frontend
echo      arrancados (arranque.bat, opcion 1).
echo   2. Una cuenta de UNA organizacion con el modulo Utilidades.
echo      El superadmin sin organizacion recibe un aviso y no opera:
echo      el uso se anota en el registro de la organizacion, y sin
echo      una no hay donde anotarlo. Es a proposito.
echo.
pause
echo.
echo ----------------------------------------------------------
echo  PASO 1 - Anonimizar un fichero REAL (el que importa)
echo ----------------------------------------------------------
echo.
echo   1. Abre  http://localhost:5173/utilidades/anonimizar
echo   2. Sube un listado real de los que se comparten de verdad
echo      (becas, inscritos, proveedores...). CSV o Excel.
echo   3. Mira la regla que se propone para cada columna.
echo   4. Pulsa "Ver como queda" y revisa la vista previa.
echo.
echo QUE DEBES VER:
echo   - Cada columna con datos personales propone una regla.
echo   - DNI con el criterio AEPD (solo las cifras centrales).
echo   - En una columna de texto libre, solo cambian los nombres.
echo.
echo APUNTA LO QUE SE LE ESCAPE: una columna sin proponer, o un
echo nombre que sigue a la vista. Esa es la medicion que la #191
echo pedia sobre un fichero real y que se aplazo.
echo.
pause
echo.
echo ----------------------------------------------------------
echo  PASO 2 - Lo que se descarga se puede compartir
echo ----------------------------------------------------------
echo.
echo   1. Marca la confirmacion y descarga el fichero.
echo   2. Abrelo en Excel.
echo.
echo QUE DEBES VER: el mismo fichero que en la vista previa, con
echo sus columnas y sus numeros, y sin datos personales que tu no
echo compartirias. Este juicio es tuyo, no del detector.
echo.
pause
echo.
echo ----------------------------------------------------------
echo  PASO 3 - Un PDF de los de verdad
echo ----------------------------------------------------------
echo.
echo   1. Abre  http://localhost:5173/utilidades/pdf
echo   2. Une dos anexos reales y divide un expediente por rangos.
echo.
echo QUE DEBES VER: los PDF se abren, con las paginas en su orden.
echo Si uno escaneado o protegido da un aviso, copia el texto.
echo.
pause
