@echo off
start "" "pythonw.exe" -c "import subprocess; subprocess.Popen(['uv', 'run', '--with', 'customtkinter', '--with', 'fastapi', '--with', 'uvicorn', '--with', 'httpx', '--with', 'starlette', 'proxy3.py', '--gui'], creationflags=subprocess.CREATE_NO_WINDOW)"
exit