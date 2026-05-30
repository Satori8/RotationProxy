# Design Specification: Refine Logger, Subprocess Management, and Rotation Cooldowns

**Date:** 2026-05-30
**Status:** Approved

## 1. Overview
This specification details changes to `proxy3.py` to refine the logging output format, suppress verbose default log messages, introduce a cooldown reset control in the GUI, optimize daily rate limit threshold logic, fix the non-deterministic non-429 error logger bug, and guarantee robust shutdown of the server subprocess on Windows.

## 2. Requirements

### 2.1 Single-Line Log Formatting & Suppressing Default Logs
* Replace default verbose `httpx` and `uvicorn.access` log messages with a single, highly readable log entry for every proxy request:
  `[TIMESTAMP] [LEVEL] [model] [key#suffix] [status_code]`
  * *Example:* `[2026-05-30 16:35:48,358] [INFO] [gemini-3.5-flash] [key#3-abcd] [200]`
* Suppress automatic INFO-level logs from `httpx`, `httpcore`, and `uvicorn.access`.

### 2.2 Shortened Cooldown and Sleep Messages
* Format sleep and retry messages to be extremely concise:
  * Cooldown warning: `[gemini] Key #3 429 (gemini-3.5-flash). Cooldown 90.0s. Attempt 1/5`
  * Sleep info: `[gemini] Sleeping 1.50s...`
  * Daily RPD limit: `[gemini] Key #3 RPD limit. Wait 12.3h`
  * Daily non-Gemini limit: `[gemini] Key #3 daily limit. Wait 24h`
  * Model failure: `Model 'gemini-3.5-flash' failed. Cooldown 24h`

### 2.3 CustomTkinter GUI Integration & Cooldown Reset
* Add a **"Reset Daily Cooldowns"** button (styled in dark red/firebrick) to the GUI's left control panel.
* Clicking this button will send a non-blocking `POST` request to the proxy server's control endpoint.
* Expose a `/control/reset_cooldowns` POST endpoint on the FastAPI app (registered before the wildcard route) to:
  * Clear global in-memory cooldown dicts (`COOLDOWNS`, `CONSECUTIVE_429S`, `CONSECUTIVE_RPD_429S`).
  * Reset `model_cooldowns` and `consecutive_model_failures` in `config_rotation.json`.
* Strip ANSI escape codes dynamically in `ProxyGUI.poll_queue` to ensure no garbage color codes render in the GUI text box.

### 2.4 Rotation Cooldown & Error Log Bug Fixes
* **Increase RPD daily threshold:** Raise the limit of consecutive failures before hitting the daily RPD limit to `3` (from `2`).
* **Success key sequence reset:** Reset `CONSECUTIVE_RPD_429S[api_key] = 0` upon any successful request (status `200`) using that key.
* **Non-deterministic 403 logging fix:** Replace the built-in non-deterministic `hash(error_msg)` with `hashlib.md5(error_msg.encode('utf-8')).hexdigest()`, preventing duplicate errors from being appended across process restarts.
* **Corrupt error log protection:** Add robust handling for empty or invalid `error_keys_log.json` files in `log_non_429_error` and `remove_key_from_error_log`.

### 2.5 Robust Windows Subprocess Termination
* On Windows, uvicorn subprocesses can sometimes survive parent termination if started under standard options. We will:
  * Force-kill the process tree if needed.
  * Register a `win32` graceful termination sequence or use taskkill on Windows specifically to guarantee complete cleanup of the port binding.

## 3. Architecture & Implementation Plan

### 3.1 Logging Configurations
A new `ColoredFormatter` will inherit from `logging.Formatter` to color-code console output based on severity:
```python
class ColoredFormatter(logging.Formatter):
    GREY = "\x1b[90m"
    GREEN = "\x1b[32m"
    YELLOW = "\x1b[33m"
    RED = "\x1b[31m"
    BOLD_RED = "\x1b[31;1m"
    RESET = "\x1b[0m"

    COLORS = {
        logging.DEBUG: GREY,
        logging.INFO: GREEN,
        logging.WARNING: YELLOW,
        logging.ERROR: RED,
        logging.CRITICAL: BOLD_RED,
    }

    def format(self, record):
        import copy
        rec = copy.copy(record)
        color = self.COLORS.get(rec.levelno, self.RESET)
        rec.levelname = f"{color}{rec.levelname}{self.RESET}"
        rec.msg = f"{color}{rec.msg}{self.RESET}"
        return super().format(rec)
```

We will strip ANSI codes in the GUI:
```python
import re
ANSI_ESCAPE = re.compile(r'\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
```

### 3.2 Robust Subprocess Closing
Update `stop_server_subprocess`:
```python
    def stop_server_subprocess(self):
        if self.server_process is not None:
            try:
                # Under Windows, terminate the whole process tree to prevent orphaned ports
                if os.name == "nt":
                    import subprocess
                    subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", str(self.server_process.pid)],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                else:
                    self.server_process.terminate()
                    self.server_process.wait(timeout=2.0)
            except Exception:
                try:
                    self.server_process.kill()
                except Exception:
                    pass
            self.server_process = None
```
