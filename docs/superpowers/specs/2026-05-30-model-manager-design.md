# Spec: Model Manager Hub with Live Diagnostics and Rotation Priority Controls

## 1. Overview
The **Model Manager Hub** is an advanced GUI addition to the Resilient Key Rotation Proxy. It provides:
- Live fetching of free models from OpenRouter (extensible to other providers).
- Async diagnostics (sending a test "Hi" query) to evaluate if models are currently returning 200, 429 (rate-limited), or 404 (not found).
- Dynamic Drag/Drop-like prioritization (Up/Down) of the active rotation lists for the thinking domain.
- In-memory and file-based state synchronization on-the-fly.

---

## 2. Architecture & Components

### 2.1 Backend Controls (`proxy_core/server.py`)
To prevent CORS and token leakage, all model testing queries are tunneled through the proxy:
- **`POST /control/test_model`**
  - Accepts a JSON payload: `{"model": "model_id", "provider": "provider_name"}`
  - The proxy performs a real async HTTP POST to the provider's `/chat/completions` endpoint with a single message: `{"role": "user", "content": "Hi"}`.
  - Returns a structured diagnostic JSON response:
    - On HTTP 200: `{"status": "ok", "message": "Model is active"}`
    - On HTTP 429: `{"status": "rate_limited", "message": "Rate limit exceeded (429)"}`
    - On HTTP 404: `{"status": "not_found", "message": "Model not found (404)"}`
    - On Other: `{"status": "error", "message": "Error description..."}`

### 2.2 GUI Enhancements (`proxy_core/gui.py`)
The right-hand panel of the CustomTkinter GUI is upgraded from a single text logging area to a **`CTkTabview`**:
- **Tab 1: "Console Logs"**
  - Contains the original colored log output text area and the "Clear Logs" button.
- **Tab 2: "Model Manager"**
  - Left Frame: **"Live Diagnostic Monitor"**
    - Scrollable list showing available free models from OpenRouter.
    - Button **"Fetch Free Models"** to fetch from `https://openrouter.ai/api/v1/models` in a background thread.
    - Each row includes:
      - Model ID & Context Window Size.
      - **Diagnostic Color Badge**: Grey (untested), Green (OK), Yellow (429), Red (404/Error).
      - **"Test" Button**: Async background call to `POST /control/test_model`.
      - **"Add" Button**: Copy the model into the active rotation list.
  - Right Frame: **"Active Rotation Configuration"**
    - List of models currently active in the rotation list for `"gemini-3.5-flash"`.
    - Note: `"gemini-3.5-flash"` and `"gemini-3-flash"` remain at the top as core Google models, but the order of other models can be configured.
    - Each row includes:
      - Model ID.
      - **"Up" Button**: Shifts priority higher.
      - **"Down" Button**: Shifts priority lower.
      - **"Remove" Button**: Removes the model from the rotation list.
    - Bottom Button: **"Save Rotation"** which updates `config_rotation.json` and synchronizes the active list immediately.

---

## 3. Data Flow

### 3.1 Fetching Models
```
[GUI Button: Fetch] -> [Async Thread] -> API: https://openrouter.ai/api/v1/models
                      -> Filter float(pricing.prompt) == 0.0 & float(pricing.completion) == 0.0
                      -> Update CTkScrollableFrame with model rows
```

### 3.2 Testing Model
```
[GUI Row Button: Test] -> [Async Thread] -> Proxy: POST /control/test_model
                        -> [Proxy Core] -> API: https://openrouter.ai/api/v1/chat/completions
                        -> Returns status -> GUI: Update row status badge color
```

---

## 4. State Synchronization
- When **"Save Rotation"** is clicked, it saves the list under `"rotation_lists" -> "gemini-3.5-flash"` in `config_rotation.json`.
- The background server automatically reloads this JSON file on every incoming request, meaning no restarts are ever required.
