# Resilient Key Rotation Proxy GUI Design Spec

## Overview
This specification details a lightweight, high-performance desktop GUI application built with `customtkinter` for managing our FastAPI-based Resilient Key and Model Rotation Proxy. 

The GUI runs in the main thread while the FastAPI server (uvicorn) runs in a background thread. This allows the GUI to control proxy states, configure routing options at runtime, and display real-time logs without locking or latency.

---

## Core Requirements & Specifications

### 1. Unified Process Lifecycle & Logger Integration
* **FastAPI Server Backgrounding:** The FastAPI/uvicorn server will be started in a separate `threading.Thread`. When the CustomTkinter GUI window is closed, the thread will be gracefully terminated and resources cleaned up.
* **Real-time Log Interception:** We will implement a custom `logging.Handler` in `proxy3.py` that intercepts all proxy server events and logs, piping them safely (via `app.after` for thread safety) into a CustomTkinter scrolling text box.

### 2. Kaggle Provider Integration & Configuration Management
* **`opencode.jsonc` Modification:** We will parse and modify `E:\Appdata\.config\opencode-profiles\default\opencode.jsonc` at runtime.
  * A text input in the GUI allows changing the Kaggle Ollama Tunnel `baseURL` value.
  * Clicking "Save URL" will perform a safe regex-based replacement on the `.jsonc` file to preserve comments and other provider properties.
* **"Use Kaggle" Checkbox:** A checkbox in the GUI toggles the inclusion of the Kaggle model (`qwen3.6`) in both rotation domains:
  * When checked, `"qwen3.6"` is appended to the available fallback lists for both domains at runtime.
  * When unchecked (default), it is filtered out of both rotation lists.
* **Kaggle Settings dynamically injected:**
  ```python
  "qwen3.6": {
      "provider": "kaggle",
      "base_url": KAGGLE_URL_FROM_JSONC,
      "keys_pool": ["test"], # Kaggle/Ollama does not require authenticating API keys
      "target_model": "qwen3.6"
  }
  ```

### 3. Manual Provider Selection (Non-Interruptive)
* Dropdowns in the GUI let the user force the active provider for the **Thinking** and **Quick** domains respectively:
  * **Options:** `Auto` (default), `Gemini Only`, `OpenRouter Only`, `Kaggle Only`.
  * **Logic:** Does not alter the original rotation configuration or cooldown structures. Instead, when filtering `available_candidates` for a request, we restrict the candidates to only those belonging to the selected provider. Cooldowns, recovery probing, and model rotation behave normally *within* that forced provider scope.

### 4. Open Folder Button
* A dedicated button in the GUI "Open Folder" will open the script directory on Windows using `os.startfile()`.

### 5. Silent Command Launcher with Custom Icon
* We will create a CMD script (`launch_gui.cmd`) to start the GUI.
* It will use `uv run --with customtkinter --with uvicorn --with fastapi --with httpx --with starlette pythonw proxy3.py` to launch with `pythonw` (suppressing the CMD console window).
* It will bind a custom `.ico` file.

---

## UI Layout & Hierarchy

```
+--------------------------------------------------------------------------------+
|  Gemini & OpenRouter Key Rotation Proxy GUI                             [ - ] [x]  |
+--------------------------------------------------------------------------------+
|  [Status: RUNNING] [Port: 4000]                                                |
+------------------------------------+-------------------------------------------+
|  DOMAIN SETTINGS                   |  REAL-TIME PROXY LOGS                     |
|                                    |                                           |
|  Thinking Domain (gemini-3.5):     |  [2026-05-28 19:15] Server started...     |
|  [ Auto-rotation / Gemini / OR ] v |  [2026-05-28 19:15] Loaded 85 keys.       |
|                                    |  [2026-05-28 19:16] GET /v1beta/models    |
|  Quick Domain (gemini-flash-lite): |  [2026-05-28 19:17] Post /openrouter/chat |
|  [ Auto-rotation / Gemini / OR ] v |                                           |
|                                    |                                           |
|------------------------------------|                                           |
|  KAGGLE TUNNEL                     |                                           |
|  [ ] Use Kaggle (qwen3.6)          |                                           |
|  Kaggle URL:                       |                                           |
|  [ https://...trycloudflare.com ]  |                                           |
|  [ Save URL ]                      |                                           |
|                                    |                                           |
|------------------------------------|                                           |
|  [ Open Script Folder ]            |  [ Clear Log ]                            |
+------------------------------------+-------------------------------------------+
```
