@echo off
cd /d "%~dp0"
echo [LAUNCH] Starting Gemini Proxy GUI...
echo [LAUNCH] Working directory: %CD%

:venv_check
if not exist ".venv" goto venv_setup
".venv\Scripts\python.exe" -c "import customtkinter" 2>nul
if not errorlevel 1 goto run
echo [LAUNCH] Virtual environment is incomplete. Recreating...
rmdir /s /q ".venv" 2>nul

:venv_setup
echo [LAUNCH] Creating virtual environment...
uv venv
if errorlevel 1 (
    echo [LAUNCH] [FATAL] Failed to create virtual environment. Is 'uv' installed?
    pause
    exit /b 1
)
echo [LAUNCH] Installing dependencies...
uv pip install --python ".venv\Scripts\python.exe" customtkinter fastapi uvicorn httpx starlette tiktoken tree-sitter
if errorlevel 1 (
    echo [LAUNCH] [FATAL] Failed to install dependencies.
    pause
    exit /b 1
)
echo [LAUNCH] Precompiling Python files...
".venv\Scripts\python.exe" -m compileall -q .

:run
".venv\Scripts\python.exe" proxy3.py --gui
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
