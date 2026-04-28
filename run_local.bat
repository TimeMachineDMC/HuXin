@echo off
setlocal
cd /d "%~dp0"

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

python Code\dual_api_server.py
