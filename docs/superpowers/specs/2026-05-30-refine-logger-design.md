# Design Specification: Refine Logger, Subprocess Management, and Modular Split

**Date:** 2026-05-30
**Status:** Approved

## 1. Overview
This specification details the architecture and requirements for refactoring `proxy3.py` (originally 1700+ lines) into a highly modular, maintainable, and clean Python package (`proxy_core`). At the same time, it integrates deep improvements to the logging system (colored output, silenced third-party logs, custom single-line request tracking), optimizes cooldown states (adding a reset button in the GUI and a control endpoint in the API), resolves multiple bugs (JSON encoding, error counter, Windows subprocess port leakages), and preserves maximum performance.

The main entry point will remain `proxy3.py` in the repository root. All application logic will reside in the subpackage `proxy_core`.

---

## 2. Architecture & Directory Layout

To keep the root folder clean, all modules are organized inside the `proxy_core` subdirectory.

```
├── proxy3.py                # Main entry point (CLI argument parser, boots GUI or Foreground Server)
└── proxy_core/              # Modular proxy library package
    ├── __init__.py          # Package initialization
    ├── logger.py            # Custom ColoredFormatter, log configuration, and third-party silencer
    ├── config.py            # Disk configuration (config_rotation.json) & global settings (USE_KAGGLE, etc.)
    ├── state.py             # Global in-memory runtime states (COOLDOWNS, CONSECUTIVE_RPD_429S, etc.)
    ├── rotation.py          # Key loading, key sorting, daily limit checks, error logging
    ├── server.py            # FastAPI App, transparent proxy routing, payload translation, reset route
    └── gui.py               # CustomTkinter GUI layout, log polling, robust Windows subprocess closing
```

---

## 3. Detailed Module Specifications

### 3.1 `proxy_core/logger.py` (Logging Setup)
* **ColoredFormatter:** Defines an ANSI color log formatter that highlights different severity levels:
  * `DEBUG` -> Grey (`\x1b[90m`)
  * `INFO` -> Green (`\x1b[32m`)
  * `WARNING` -> Yellow (`\x1b[33m`)
  * `ERROR` -> Red (`\x1b[31m`)
  * `CRITICAL` -> Bold Red (`\x1b[31;1m`)
  * Applies `ColoredFormatter` to all console `StreamHandler` instances.
* **Third-Party Suppression:** Configures `httpx`, `httpcore`, and `uvicorn.access` loggers to level `WARNING` to eliminate automatic, noisy HTTP request/response line logging.

### 3.2 `proxy_core/config.py` (Configuration Manager)
* Manages loading/saving of `config_rotation.json`.
* Defines global settings which can be modified dynamically:
  * `USE_KAGGLE` (Boolean)
  * `SAVE_CHAT_LOGS` (Boolean)
  * `FORCE_MODEL` (Dict of forced models)
  * `KAGGLE_BASE_URL` (String)

### 3.3 `proxy_core/state.py` (Runtime Mutable State)
* Defines global, thread-safe in-memory collections:
  * `COOLDOWNS = {}` (Key cooldowns)
  * `CONSECUTIVE_429S = {}` (Consecutive 429s per provider)
  * `LAST_429_TIME = {}` (Last 429 timestamp per key)
  * `CONSECUTIVE_RPD_429S = {}` (Requests Per Day failure history per key)
  * `LAST_USED = {}` (Last used timestamp per key)
  * `LAST_REQUEST_TIME = {}` (Last request timestamp per provider)

### 3.4 `proxy_core/rotation.py` (Key Pool & Cooldown Management)
* **Key Loading:** Loads API keys from `.md` files dynamically.
* **Error Log Handling:**
  * Uses `hashlib.md5(error_msg.encode('utf-8')).hexdigest()` to uniquely and deterministically group errors. This fixes the previous python `hash()` process-randomization bug (where 403 error files grew indefinitely because hashes changed on every start).
  * Implements robust file checks (`os.path.getsize` and catching `JSONDecodeError`) to prevent crashes when `error_keys_log.json` is empty or corrupted.

### 3.5 `proxy_core/server.py` (FastAPI Server)
* Implements the core proxy endpoints, request payload translations, and response stream generator.
* **Single-Line Completion Logs:** Outputs exactly one structured log line per completed request:
  `[TIMESTAMP] [LEVEL] [model] [key#suffix] [status_code]`
  * *Example:* `[2026-05-30 16:35:48,358] [INFO] [gemini-3.6-flash] [key#3-abcd] [200]`
* **Short Cooldown Logs:** All warning/sleep messages are compressed to minimize clutter:
  * `[gemini] Key #3 429 (gemini-3.6-flash). Cooldown 90.0s. Attempt 1/5`
  * `[gemini] Sleeping 1.50s...`
  * `[gemini] Key #3 RPD limit. Wait 12.3h`
* **Control API:** Exposes a `POST /control/reset_cooldowns` endpoint to clear all runtime states in `state.py` and resets config list cooldowns in `config_rotation.json`.
* **Fail Sequence and Thresholds:**
  * Increases daily RPD threshold to `3` consecutive failures before marking daily cooldown.
  * Resets `CONSECUTIVE_RPD_429S[api_key] = 0` instantly when a request succeeds (status `200`).

### 3.6 `proxy_core/gui.py` (CustomTkinter Controller)
* Renders the control application.
* **Reset Button:** Adds a dark red/firebrick "Reset Daily Cooldowns" button that calls `/control/reset_cooldowns` asynchronously using `httpx`.
* **ANSI Stripping:** Strips ANSI escape codes from incoming subprocess lines in `poll_queue` to keep the GUI textbox clean and readable.
* **Robust Subprocess Closing:** On Windows, it terminates the server subprocess using `taskkill /F /T` to fully clean up bound ports and prevent orphaned uvicorn instances.

### 3.7 `proxy3.py` (Main Entry Point)
* Command-line argument parser. If `--gui` is passed, boots `gui.py`. Else, starts foreground `uvicorn.run("proxy_core.server:app")`.

---

## 4. Migration & Verification Plan
1. Move the code out of `proxy3.py` into individual modules inside `proxy_core/`.
2. Re-wire `proxy3.py` to act as the simple entry point wrapper.
3. Validate that standard uvicorn-access and httpx logging are silenced.
4. Verify colored console logging.
5. Validate that ANSI codes are stripped in the GUI.
6. Verify "Reset Daily Cooldowns" correctly resets in-memory and on-disk cooldown records.
7. Test robust process termination on Windows by closing the GUI.
