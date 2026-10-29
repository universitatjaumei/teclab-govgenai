@echo off
setlocal
cd /d "%~dp0"

echo ========================================
echo       GOV GEN AI PLATFORM
echo ========================================
echo.
echo  1. FastAPI + Frontend React (desarrollo completo)
echo  2. Solo servidor FastAPI
echo.
set /p OPCION="Selecciona [1/2]: "

if "%OPCION%"=="1" goto :completo
if "%OPCION%"=="2" goto :servidor

echo [ERROR] Opcion no valida.
pause
exit /b 1

:completo
echo.
echo [INFO] Verificando que Docker Desktop esta corriendo (PostgreSQL + almacen S3)...
echo [INFO] Levantando servidor FastAPI en http://localhost:8000
echo [INFO] Levantando frontend React en http://localhost:5173
echo.
set PYTHONUNBUFFERED=1
start "FastAPI" cmd /k "cd /d ""%~dp0"" && uv run --project server uvicorn server.app.main:app --reload --reload-dir server --host 127.0.0.1 --port 8000"
start "Frontend" cmd /k "cd /d ""%~dp0frontend"" && npm run dev"
goto :fin

:servidor
echo.
echo [INFO] Verificando que Docker Desktop esta corriendo (PostgreSQL + almacen S3)...
echo [INFO] Levantando servidor FastAPI en http://localhost:8000
echo [INFO] Swagger UI en http://localhost:8000/docs
echo.
set PYTHONUNBUFFERED=1
uv run --project server uvicorn server.app.main:app --reload --reload-dir server --host 127.0.0.1 --port 8000
goto :fin

:fin
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] La aplicacion se cerro con errores.
    pause
)
