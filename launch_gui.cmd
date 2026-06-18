@echo off
cd /d "%~dp0"
echo [LAUNCH] Starting Gemini Proxy GUI...
echo [LAUNCH] Working directory: %CD%
echo.

if not exist ".venv" (
    echo [LAUNCH] Creating virtual environment...
    uv venv
    echo [LAUNCH] Installing dependencies...
    .venv\Scripts\uv pip install customtkinter fastapi uvicorn httpx starlette tiktoken tree-sitter
    echo [LAUNCH] Precompiling Python files...
    .venv\Scripts\python.exe -m compileall -q .
)

.venv\Scripts\python.exe proxy3.py --gui
set EXIT_CODE=%ERRORLEVEL%
if %EXIT_CODE% NEQ 0 (
    echo.
    echo =============================================
    echo [ERROR] GUI exited with code %EXIT_CODE%.
    echo.
    if exist "gui_error.log" (
        echo --- Last 20 lines of gui_error.log ---
        type "gui_error.log"
        echo ---------------------------------------
    ) else (
        echo No error log found. Check console output above.
    )
    echo =============================================
    echo.
    pause
) else (
    if exist "gui_error.log" del "gui_error.log"
)
