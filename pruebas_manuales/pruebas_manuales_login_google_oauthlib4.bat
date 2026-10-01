@echo off
chcp 65001 > nul
rem Se ejecuta desde la raiz del repositorio, este el .bat donde este.
cd /d "%~dp0.."
title Pruebas manuales - Login con Google tras subir oauthlib a 4.0.0
echo.
echo ==========================================================
echo   LOGIN CON GOOGLE - oauthlib 3.3.1 --^> 4.0.0
echo ==========================================================
echo.
echo POR QUE ESTE GUION EXISTE
echo.
echo   El 2026-09-30 se publico CVE-2026-49265 contra oauthlib 3.3.1 y la
echo   puerta de vulnerabilidades de CI bloqueo el despliegue. Se subio a
echo   4.0.0, que es un SALTO DE MAJOR.
echo.
echo   La suite entera pasa con el: 5.702 tests, 0 rojos. Pero eso NO
echo   prueba lo que importa. La cadena es:
echo.
echo        google-auth-oauthlib  -^>  requests-oauthlib  -^>  oauthlib
echo.
echo   O sea el LOGIN CON GOOGLE. Y ningun test automatico lo cubre de
echo   verdad, porque hace falta el proveedor de identidad real. Es
echo   exactamente de las pruebas que solo puede hacer una persona.
echo.
echo   Si este guion falla, la salida NO es revertir a mano: es poner una
echo   entrada en avisos_aceptados.toml con motivo, responsable y
echo   caducidad, que es lo que la propia puerta indica.
echo.
pause
echo.
echo ----------------------------------------------------------
echo  QUE HACE FALTA ANTES DE EMPEZAR
echo ----------------------------------------------------------
echo.
echo   1. Docker Desktop arrancado, con la base de datos en pie.
echo   2. Backend y frontend corriendo:  arranque.bat  (opcion 1)
echo      OJO: el backend tarda 2-4 minutos (carga torch).
echo   3. En server\.env (NO en el .env de la raiz: la aplicacion lee el
echo      de server) estas CINCO variables:
echo        GOOGLE_OAUTH_CLIENT_ID      el de Secret Manager, uji-teclab
echo        GOOGLE_OAUTH_CLIENT_SECRET  idem, govgenai-google-oauth-client-secret
echo        GOOGLE_OAUTH_ALLOWED_DOMAIN=uji.es
echo        GOOGLE_OAUTH_REDIRECT_URI=http://localhost:8000/api/v1/auth/google/callback
echo        SAML_FRONTEND_RETURN_URL=http://localhost:5173/auth/callback
echo      La REDIRECT_URI tiene que estar dada de alta, CARACTER A CARACTER,
echo      en el cliente OAuth de la consola de Google (APIs y servicios,
echo      Credenciales). Si sobra una barra final, Google rechaza.
echo      Sin la ultima, el login funciona pero acaba en una pantalla con
echo      el token en JSON en vez de en el panel (issue #195).
echo   4. Una cuenta de Google del dominio uji.es para entrar con ella.
echo.
echo   Si falta el 3, la ruta responde 404 y el boton no aparece: eso NO
echo   es un fallo de oauthlib, es configuracion que falta.
echo.
pause
echo.
echo ----------------------------------------------------------
echo  PASO 1 - Los servicios responden
echo ----------------------------------------------------------
echo.
curl -s -o nul -w "   backend 8000 health: %%{http_code}\n" http://localhost:8000/health
curl -s -o nul -w "   frontend 5173:       %%{http_code}\n" http://localhost:5173/
echo.
echo QUE DEBES VER: 200 en las dos.
echo.
pause
echo.
echo ----------------------------------------------------------
echo  PASO 2 - La version instalada es la nueva
echo ----------------------------------------------------------
echo.
cd server
uv run python -c "import importlib.metadata as m; print('   oauthlib      ', m.version('oauthlib')); print('   requests-oauthlib', m.version('requests-oauthlib')); print('   google-auth-oauthlib', m.version('google-auth-oauthlib'))"
cd ..
echo.
echo QUE DEBES VER: oauthlib 4.0.0. Si dice 3.3.1, el entorno no esta
echo sincronizado y lo que pruebes despues no vale: ejecuta
echo   cd server
echo   uv sync --locked --extra local-models
echo   (dos ordenes por separado: asi valen en CMD y en PowerShell 5.1,
echo   que no conoce el operador de encadenar)
echo.
pause
echo.
echo ----------------------------------------------------------
echo  PASO 3 - El boton de Google existe
echo ----------------------------------------------------------
echo.
echo   1. Abre  http://localhost:5173/  en el navegador.
echo   2. Mira la pantalla de entrada.
echo.
echo QUE DEBES VER: el boton de entrar con Google, junto al formulario
echo de correo y contrasena. Los dos caminos conviven.
echo.
echo SI NO APARECE: mira la consola del navegador y el log del backend.
echo Lo mas probable sigue siendo configuracion (punto 3 de arriba), no
echo oauthlib.
echo.
pause
echo.
echo ----------------------------------------------------------
echo  PASO 4 - Entrar de verdad  (ESTE ES EL PASO QUE IMPORTA)
echo ----------------------------------------------------------
echo.
echo   1. Pulsa el boton de Google.
echo   2. Elige tu cuenta de uji.es y acepta.
echo   3. Espera a volver al panel.
echo.
echo QUE DEBES VER:
echo   - Google te pide la cuenta y vuelve al panel sin error.
echo   - Entras: se ve tu nombre o tu correo arriba.
echo   - El panel carga con el rol que te corresponde.
echo.
echo QUE SERIA UN FALLO DE oauthlib:
echo   - Un error de firma, de estado (state) o de intercambio del codigo.
echo   - Una excepcion en el log del backend nombrando oauthlib o
echo     requests_oauthlib.
echo   - Volver al login sin mensaje, en bucle.
echo.
echo COPIA EL ERROR TAL CUAL si aparece. La diferencia entre
echo "configuracion mal puesta" y "el major rompio algo" esta en el texto.
echo.
pause
echo.
echo ----------------------------------------------------------
echo  PASO 5 - El dominio sale de hd, no del correo
echo ----------------------------------------------------------
echo.
echo   Esto no es de oauthlib, pero se comprueba aqui porque es la unica
echo   vez que alguien entra con Google a mano: el dominio de la
echo   organizacion se lee del campo hd que manda Google, NUNCA de la
echo   parte de detras del correo. Un correo se puede poner a mano; hd lo
echo   afirma el proveedor.
echo.
echo   1. Con la sesion abierta, mira a que organizacion te ha asignado.
echo.
echo QUE DEBES VER: la organizacion que corresponde a uji.es.
echo.
pause
echo.
echo ----------------------------------------------------------
echo  PASO 6 - Y el camino de siempre sigue entero
echo ----------------------------------------------------------
echo.
echo   1. Sal de la sesion.
echo   2. Entra con correo y contrasena de un usuario local.
echo.
echo QUE DEBES VER: entra igual. Subir oauthlib no tenia por que tocar
echo esto, y por eso se comprueba: un major que rompe lo de al lado es
echo justo lo que no se ve mirando solo lo que cambio.
echo.
pause
echo.
echo ==========================================================
echo   RESULTADO
echo ==========================================================
echo.
echo   Los seis pasos bien  -^>  oauthlib 4.0.0 queda validado y no hay
echo                            nada que decidir.
echo.
echo   El paso 4 o el 5 mal -^>  copia el error y dilo. La salida es
echo                            avisos_aceptados.toml con motivo,
echo                            responsable y caducidad, no apagar la
echo                            puerta ni revertir en silencio.
echo.
pause
