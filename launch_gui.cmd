@echo off
cd /d "%~dp0"
echo [LAUNCH] Starting Gemini Proxy GUI...
echo [LAUNCH] Working directory: %CD%
echo.
uv run --with customtkinter --with fastapi --with uvicorn --with httpx --with starlette --with tiktoken --with tree-sitter --with headroom-ai[all] python proxy3.py --gui 2> "gui_error.log"
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