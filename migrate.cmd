@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ============================================================
echo         GeminiProxy Target PC Setup ^& Migration
echo ============================================================
echo [MIGRATE] Working directory: %CD%
echo.

:: 1. Git Pull Latest Code
where git >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    echo [MIGRATE] Pulling latest updates from Git remote...
    git pull
    if %ERRORLEVEL% NEQ 0 (
        echo [WARNING] Git pull failed or encountered conflicts. Continuing with local files...
    ) else (
        echo [SUCCESS] Git repository updated successfully.
    )
) else (
    echo [WARNING] Git is not installed or not in PATH. Skipping git pull.
)
echo.

:: 2. Check Python
where python >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo [FATAL] Python is not installed or not in PATH!
    echo Please install Python 3.10+ from https://www.python.org/
    pause
    exit /b 1
)
python --version

:: 3. Setup Virtual Environment & Install Dependencies
echo.
echo [MIGRATE] Setting up Python virtual environment (.venv)...
if not exist ".venv" (
    where uv >nul 2>nul
    if %ERRORLEVEL% EQU 0 (
        echo [MIGRATE] Creating virtualenv with uv...
        uv venv .venv
    ) else (
        echo [MIGRATE] uv not detected. Creating virtualenv with standard python...
        python -m venv .venv
    )
)

echo [MIGRATE] Installing / updating required dependencies...
where uv >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    uv pip install --python ".venv\Scripts\python.exe" customtkinter fastapi uvicorn httpx starlette tiktoken tree-sitter pytest
) else (
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    ".venv\Scripts\python.exe" -m pip install customtkinter fastapi uvicorn httpx starlette tiktoken tree-sitter pytest
)

if %ERRORLEVEL% NEQ 0 (
    echo [FATAL] Failed to install Python dependencies.
    pause
    exit /b 1
)
echo [SUCCESS] Dependencies installed successfully.
echo.

:: 4. Verify Project-Local VPN Directory
echo [MIGRATE] Verifying VPN files in project dir: %CD%\vpn
if exist "vpn\vpn_manager.py" (
    echo [SUCCESS] Found vpn\vpn_manager.py
) else (
    echo [WARNING] vpn\vpn_manager.py not found in %CD%\vpn!
)

if exist "vpn\forawrd_tunnels.ps1" (
    echo [SUCCESS] Found vpn\forawrd_tunnels.ps1
) else (
    echo [WARNING] vpn\forawrd_tunnels.ps1 not found!
)

set CONF_COUNT=0
for /L %%i in (1,1,6) do (
    if exist "vpn\configs\vpn%%i.conf" (
        set /a CONF_COUNT+=1
    )
)
echo [MIGRATE] WireGuard configs found: !CONF_COUNT! / 6 tunnels in vpn\configs\

if exist "C:\Program Files\WireGuard\wireguard.exe" (
    echo [SUCCESS] WireGuard for Windows is installed at C:\Program Files\WireGuard\wireguard.exe
) else (
    echo [NOTICE] WireGuard is not installed at C:\Program Files\WireGuard\wireguard.exe
    echo          (If you plan to use VPN multi-channel rotation, install it from https://www.wireguard.com/install/)
    echo          (The proxy will automatically run in standalone zero-VPN mode without it.)
)
echo.

:: 5. Update / Ensure Config Defaults
echo [MIGRATE] Updating config_rotation.json with local project paths...
".venv\Scripts\python.exe" -c "import os, json; p='config_rotation.json'; cfg = json.load(open(p, 'r', encoding='utf-8')) if os.path.exists(p) else {}; cfg['vpn_switcher_dir'] = os.path.abspath('vpn'); json.dump(cfg, open(p, 'w', encoding='utf-8'), indent=2, ensure_ascii=False); print('[SUCCESS] Updated config_rotation.json: vpn_switcher_dir =', os.path.abspath('vpn'))"

:: 6. Check API Keys Location
echo.
echo [MIGRATE] Checking API keys configuration...
".venv\Scripts\python.exe" -c "import os; from proxy_core.config import load_rotation_config, get_keys_location; from proxy_core.rotation import resolve_key_file_paths; cfg = load_rotation_config(); loc = get_keys_location(cfg); paths = resolve_key_file_paths(loc); print(f'Keys directory: {loc}'); [print(f'  - {k}: {\"EXISTS\" if os.path.exists(v) else \"MISSING\"} ({v})') for k, v in paths.items()]"

echo.
echo ============================================================
echo [SUCCESS] Migration and setup completed!
echo.
echo To start the proxy GUI now, run: launch_gui.cmd
echo To start headless server, run: .venv\Scripts\python.exe proxy3.py
echo ============================================================
echo.
set /p LAUNCH_NOW="Do you want to launch the proxy GUI now? (Y/N): "
if /i "%LAUNCH_NOW%"=="Y" (
    call launch_gui.cmd
)

endlocal
