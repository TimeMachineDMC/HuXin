@echo off
setlocal
cd /d "%~dp0"

echo HuXin backend for Windows
echo This starts the local API at http://127.0.0.1:8000
echo After it finishes loading, open: https://timemachinedmc.github.io/HuXin/
echo.

if "%HUXIN_PORT%"=="" set HUXIN_PORT=8000
powershell -NoProfile -Command "try { Invoke-WebRequest -UseBasicParsing -TimeoutSec 3 http://127.0.0.1:%HUXIN_PORT%/api/health | Out-Null; exit 0 } catch { exit 1 }" >nul 2>nul
if "%ERRORLEVEL%"=="0" (
    echo HuXin backend is already running at http://127.0.0.1:%HUXIN_PORT%
    echo Open: https://timemachinedmc.github.io/HuXin/
    exit /b 0
)

if not exist "Code\.env" if not exist ".env" (
    echo Missing DeepSeek config.
    echo Run this once first: copy .env.example Code\.env
    echo Then edit Code\.env and fill DEEPSEEK_API_KEY.
    exit /b 1
)

if not exist ".venv" (
    python -m venv .venv
)

call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

if exist "Model\chroma_db" if not exist ".runtime\chroma_db" (
    mkdir .runtime
    xcopy /E /I /Q Model\chroma_db .runtime\chroma_db >nul
)

if "%CHROMA_DB_PATH%"=="" set CHROMA_DB_PATH=.runtime\chroma_db
if "%HUXIN_HOST%"=="" set HUXIN_HOST=127.0.0.1

python Code\dual_api_server.py
