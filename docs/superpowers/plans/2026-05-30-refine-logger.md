# Refine Logger and Cooldown Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refine proxy logging, introduce a dark red GUI button to reset daily cooldowns via a new FastAPI control endpoint, strip ANSI colors for the GUI log view, increase daily limit thresholds, reset fail sequence on success, deterministic error key logging, and robust Windows subprocess termination.

**Architecture:** 
1. Re-configure Python root logging with a `ColoredFormatter` for terminal streams and suppress verbose third-party loggers (`httpx`, `httpcore`, `uvicorn.access`).
2. Integrate a regex ANSI-stripper in `ProxyGUI.poll_queue` to keep GUI logs clean while allowing colored terminal output.
3. Expose a `/control/reset_cooldowns` route on FastAPI to reset in-memory and on-disk cooldown records, invoked by a new dark-red "Reset Daily Cooldowns" button in the GUI.
4. Fix `log_non_429_error` and `remove_key_from_error_log` JSON parsing robustness and use deterministic `hashlib.md5` hashes instead of the non-deterministic `hash()`.
5. Optimize subprocess teardown on Windows by terminating the process tree to free up bound ports cleanly.

**Tech Stack:** Python 3.12+, CustomTkinter, FastAPI, httpx, hashlib

---

### Task 1: Silence Default Loggers & Add Colored Console Logger

**Files:**
- Modify: `proxy3.py` (lines 14-36)

- [ ] **Step 1: Implement `ColoredFormatter` and apply it to console StreamHandlers**
Define `ColoredFormatter` and use it to replace standard formatters on Console/Stream handlers, and silence default verbose loggers.

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

# Configure loggers
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)

# Apply ColoredFormatter to console stream handlers
for handler in logging.root.handlers:
    if isinstance(handler, logging.StreamHandler):
        handler.setFormatter(ColoredFormatter("%(asctime)s [%(levelname)s] %(message)s"))

# Suppress verbose third-party loggers
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

logger = logging.getLogger("proxy")
```

- [ ] **Step 2: Run proxy in terminal to verify logger configuration**
Run `python proxy3.py --help` or similar, check if root logger successfully loads. No third-party uvicorn or httpx logs should flood the standard stream once it runs.

---

### Task 2: Implement Single-Line Log Output on Request Completion

**Files:**
- Modify: `proxy3.py:760-1285`

- [ ] **Step 1: Write Custom Single-Line Log Messages at all Return Points**
Add explicit log statements to print request outcomes in the format `[model] [key#suffix] [status_code]`. Since the default `basicConfig` format prepends timestamp and level, this results in the exact requested format.

In `_transparent_proxy_attempt`:
1. For rate-limiting:
```python
    if time_since_last_request < 1.0:
        logger.warning(f"[{requested_model}] [rate-limited] [429]")
        return JSONResponse(...)
```
2. For candidate models cooldown check:
```python
    if not available_candidates:
        logger.warning(f"[{requested_model}] [cooldown] [503]")
        return JSONResponse(...)
```
3. For successful response:
```python
                if response.status_code == 200:
                    ...
                    # Add explicit request success log
                    logger.info(f"[{candidate_model}] [key#{key_index}-{api_key[-4:]}] [200]")
```
4. For all candidate models failing:
```python
    logger.error(f"[{requested_model}] [all-keys-failed] [503]")
    return JSONResponse(...)
```

---

### Task 3: Shorten Sleep, Delay, Cooldown and Failure Log Messages

**Files:**
- Modify: `proxy3.py:1180-1280`

- [ ] **Step 1: Update Retry, Sleep and Cooldown warnings to be extremely short**
Update verbose logs to compact statements:

1. For RPD Daily limit:
```python
                                    logger.error(
                                        f"[{provider_name}] Key #{key_index} RPD limit. Wait {cooldown_duration / 3600:.1f}h"
                                    )
```
2. For Non-Gemini Daily limit:
```python
                                    logger.error(
                                        f"[{provider_name}] Key #{key_index} daily limit. Wait 24h"
                                    )
```
3. For Key hit 429:
```python
                    logger.warning(
                        f"[{provider_name}] Key #{key_index} 429 ({candidate_model}). Cooldown {cooldown_duration:.1f}s. Attempt {attempt}/{max_attempts}"
                    )
```
4. For Sleep delay:
```python
                    logger.info(
                        f"[{provider_name}] Sleeping {retry_sleep:.2f}s..."
                    )
```
5. For Key 403:
```python
                    logger.error(
                        f"[{provider_name}] Key #{key_index} 403 ({candidate_model}). Cooldown 24h"
                    )
```
6. For Key HTTP 500/502/503:
```python
                    logger.error(
                        f"[{provider_name}] Key #{key_index} HTTP {response.status_code} ({candidate_model})"
                    )
```
7. For Key Connection/Unexpected:
```python
                    logger.warning(
                        f"[{provider_name}] Key #{key_index} HTTP {response.status_code} ({candidate_model})"
                    )
```
8. For Key connection error exception:
```python
                logger.error(
                    f"[{provider_name}] Key #{key_index} conn error ({candidate_model}): {e}"
                )
```
9. For Model cooldown transition:
```python
            logger.warning(
                f"Model '{candidate_model}' failed. Cooldown 24h"
            )
```

---

### Task 4: Success Sequence Reset, Limit Threshold increase & Deterministic Error Log Fixes

**Files:**
- Modify: `proxy3.py:340-415`, `proxy3.py:1164-1215`

- [ ] **Step 1: Increase daily RPD limit failure threshold to 3**
In `_transparent_proxy_attempt` (previously around line 1181):
```python
                            if rpd_consec >= 3:
```

- [ ] **Step 2: Reset Key Fail Sequence on Success**
In `_transparent_proxy_attempt` where `response.status_code == 200`:
```python
                    # Reset consecutive 429 counter for this specific key
                    CONSECUTIVE_RPD_429S[api_key] = 0
```

- [ ] **Step 3: Fix Error Log to use deterministic MD5 hash & Robust File Handling**
In `log_non_429_error`:
```python
def log_non_429_error(model: str, key: str, error_msg: str) -> None:
    """Log non-429 errors with full details including unmasked keys for debugging."""
    ERROR_LOG_PATH = "error_keys_log.json"

    try:
        import hashlib
        error_hash = hashlib.md5(error_msg.encode("utf-8")).hexdigest()
        error_id = f"{model}|{key}|{error_hash}"

        # Load existing log or create new
        if os.path.exists(ERROR_LOG_PATH) and os.path.getsize(ERROR_LOG_PATH) > 0:
            with open(ERROR_LOG_PATH, "r", encoding="utf-8") as f:
                try:
                    error_log = json.load(f)
                except json.JSONDecodeError:
                    error_log = {}
        else:
            error_log = {}
```

In `remove_key_from_error_log`:
```python
def remove_key_from_error_log(model: str, key: str) -> None:
    """Remove all error log entries for a key that has successfully completed a request."""
    ERROR_LOG_PATH = "error_keys_log.json"

    try:
        # Check if error log exists
        if not os.path.exists(ERROR_LOG_PATH) or os.path.getsize(ERROR_LOG_PATH) == 0:
            return

        # Load existing log
        with open(ERROR_LOG_PATH, "r", encoding="utf-8") as f:
            try:
                error_log = json.load(f)
            except json.JSONDecodeError:
                return
```

---

### Task 5: Add Control Endpoint and Reset Cooldown Button

**Files:**
- Modify: `proxy3.py:760-770`, `proxy3.py:1450-1670`

- [ ] **Step 1: Expose `/control/reset_cooldowns` route on FastAPI app**
Define this route *before* the wildcard route `/{path:path}`:
```python
@app.post("/control/reset_cooldowns")
async def reset_cooldowns_endpoint():
    global COOLDOWNS, CONSECUTIVE_429S, CONSECUTIVE_RPD_429S
    COOLDOWNS.clear()
    CONSECUTIVE_429S.clear()
    CONSECUTIVE_RPD_429S.clear()

    # Also clear model cooldowns and failure counts in config_rotation.json
    try:
        config = load_rotation_config()
        config["model_cooldowns"] = {}
        config["consecutive_model_failures"] = {}
        save_rotation_config(config)
    except Exception as e:
        logger.error(f"Failed to clear model cooldowns in config: {e}")

    logger.info("Daily cooldowns and consecutive failure counters have been reset.")
    return {"status": "success", "message": "Cooldowns reset successfully."}
```

- [ ] **Step 2: Add "Reset Daily Cooldowns" Button and Handler in `ProxyGUI`**
Place the button in the left control panel under the "Open Folder" button:
```python
        # Reset Daily Cooldowns Button
        self.reset_cooldowns_btn = ctk.CTkButton(
            self.left_panel,
            text="Reset Daily Cooldowns",
            command=self.on_reset_cooldowns,
            fg_color="#8B0000",       # Dark Red
            hover_color="#B22222",    # Firebrick Red
        )
        self.reset_cooldowns_btn.pack(fill="x", padx=20, pady=(10, 10))
```

And add the non-blocking click handler in `ProxyGUI`:
```python
    def on_reset_cooldowns(self):
        import httpx
        import threading

        def do_reset():
            url = f"http://{self.host}:{self.port}/control/reset_cooldowns"
            try:
                r = httpx.post(url, timeout=2.0)
                if r.status_code == 200:
                    logger.info("[GUI] Cooldowns reset successfully.")
                    log_queue.put("[GUI] Cooldowns reset successfully.")
                else:
                    logger.error(f"[GUI] Failed to reset cooldowns: HTTP {r.status_code}")
                    log_queue.put(f"[GUI] [ERROR] Failed to reset cooldowns: HTTP {r.status_code}")
            except Exception as ex:
                logger.error(f"[GUI] Failed to connect to proxy to reset cooldowns: {ex}")
                log_queue.put(f"[GUI] [ERROR] Failed to connect to proxy: {ex}")

        threading.Thread(target=do_reset, daemon=True).start()
```

---

### Task 6: Strip ANSI Escapes in GUI and Handle Robust Windows Subprocess Closing

**Files:**
- Modify: `proxy3.py:1510-1545`, `proxy3.py:1660-1675`

- [ ] **Step 1: Strip ANSI color escapes inside `ProxyGUI.poll_queue`**
```python
    def poll_queue(self):
        import re
        ansi_escape = re.compile(r'\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
        while not log_queue.empty():
            try:
                msg = log_queue.get_nowait()
                msg = ansi_escape.sub('', msg)
                self.log_textbox.insert("end", msg + "\n")
                self.log_textbox.see("end")
            except Exception:
                break
        self.after(100, self.poll_queue)
```

- [ ] **Step 2: Ensure complete process tree termination on Windows inside `stop_server_subprocess`**
```python
    def stop_server_subprocess(self):
        if self.server_process is not None:
            try:
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
