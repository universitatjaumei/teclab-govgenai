@echo off
chcp 65001 > nul
cd /d "%~dp0.."

echo ==========================================================
echo   PRUEBAS MANUALES - BLOQUE SEC.9 (endurecimiento, 3a auditoria)
echo ==========================================================
echo.
echo El bloque SEC.9 es casi todo backend y seguridad, y eso lo
echo cubren 133 tests que ya bloquean el despliegue en CI.
echo Aqui solo esta lo que una persona tiene que juzgar.
echo.
echo AVISO - un cambio de comportamiento que debes conocer:
echo   Al EDITAR un proveedor de LLM, el campo de la clave sale
echo   VACIO a proposito. La clave ya no viaja del servidor al
echo   navegador. Dejarlo vacio significa "no la cambies".
echo.
pause

echo.
echo ---------- 1. REQUISITOS PREVIOS ----------
echo.
echo   a) Docker Desktop en marcha (icono verde).
echo   b) docker compose up -d postgres
echo   c) cd server  y luego  uv run alembic upgrade head
echo   d) cd server  y luego  uv run uvicorn app.main:app --port 8000
echo   e) cd frontend  y luego  npm run dev
echo.
echo   El primer arranque del backend tarda varios minutos porque
echo   carga los modelos locales. Espera "Application startup complete".
echo.
pause

echo.
echo ---------- 2. LA MIGRACION DE SEC.9.4 ----------
echo.
echo Comprobando la revision de cabeza...
cd server
call uv run alembic current
cd ..
echo.
echo   DEBE decir: u1n2o3p4q5r6 (head)
echo.
echo   Esa migracion RETIRA la columna api_key de
echo   hub_provider_credentials. Si hubiera credenciales guardadas
echo   con metodo 'clave', la migracion SE DETIENE y explica como
echo   moverlas a una variable de entorno. No borra nada a ciegas.
echo.
pause

echo.
echo ---------- 3. EL SERVIDOR RESPONDE ----------
echo.
curl -s -o nul -w "  /health devuelve %%{http_code}\n" http://localhost:8000/health
echo.
echo   Se espera 200. Si no responde, vuelve al paso 1.
echo.
pause

echo.
echo ---------- 4. LA BIBLIOTECA YA NO ESTA ABIERTA ----------
echo.
echo Sin credencial, este endpoint devolvia el catalogo entero de
echo automatizaciones. Ahora debe negarse.
echo.
curl -s -o nul -w "  library/manifest sin token devuelve %%{http_code}\n" http://localhost:8000/api/v1/library/manifest
echo.
echo   Se espera 404: la biblioteca se retiro en #271. Un 200 seria un fallo grave: avisa.
echo.
pause

echo.
echo ---------- 5. LA CLAVE DEL PROVEEDOR NO VIAJA ----------
echo.
echo   1. Abre el panel: http://localhost:5173
echo   2. Ve a Plataforma - Modelos LLM.
echo   3. En la seccion de Proveedores, pulsa Editar en uno que
echo      tenga clave puesta.
echo.
echo   QUE DEBES VER:
echo     - El campo de la clave VACIO (solo los puntos de ejemplo).
echo     - El resto de campos rellenos: nombre, tipo, base_url.
echo.
echo   4. Cambia SOLO el nombre (anade " probando") y guarda.
echo   5. Ahora lo que de verdad importa: pulsa "Probar conexion"
echo      en un modelo que use ese proveedor.
echo.
echo   QUE DEBES VER:
echo     - Conexion correcta, con su latencia en milisegundos.
echo.
echo   SI FALLA: si "Probar conexion" da error justo despues de
echo   editar el nombre, la clave se ha borrado al guardar. Eso es
echo   un fallo y hay que reportarlo.
echo.
echo   6. Deja el nombre como estaba.
echo.
pause

echo.
echo ---------- 6. LOS PROMPTS DE ACTIVIDAD ----------
echo.
echo   1. Ve a Plataforma - Prompts.
echo   2. Elige una actividad, cambia su texto y guarda.
echo   3. Recarga la pagina.
echo.
echo   QUE DEBES VER:
echo     - Tu texto, con el origen marcado como "override".
echo.
echo   4. Ahora borra el texto (dejalo vacio) y guarda.
echo.
echo   QUE DEBES VER:
echo     - Vuelve el texto del codigo. Eso es lo correcto: vaciar
echo       significa "vuelve al valor por defecto", no "guarda vacio".
echo.
pause

echo.
echo ---------- 7. LA CONSOLA DEL NAVEGADOR ----------
echo.
echo   Abre las herramientas de desarrollo con F12, pestana Consola.
echo   Recorre Modelos LLM y Prompts.
echo.
echo   QUE DEBES VER:
echo     - Ningun error en rojo.
echo     - Ningun 403 inesperado en la pestana Red.
echo.
echo   Si sale un 403 en una pantalla que antes funcionaba, apunta
echo   la URL: podria ser una guarda de modulo de mas.
echo.
pause

echo.
echo ==========================================================
echo   PRUEBAS COMPLETADAS
echo ==========================================================
echo.
echo Para detener los servicios:
echo   - Ctrl+C en las terminales del backend y del frontend.
echo   - docker compose stop postgres
echo.
pause
