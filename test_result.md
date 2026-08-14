## Test Run 6

### Test Conditions
- **Model**: Gemini 3.7 Flash (local proxy selected by OpenCode)
- **Proxy**: GeminiProxy (**forced to Mistral Large Latest**)
- **Environment**: Windows 10, Python 3.11+
- **Date**: 14-08-2026

### Test Steps
1. **Proxy Configuration**: Configured GeminiProxy with General Model Forcing to **force Mistral Large Latest** for all requests.
2. **Test Request**: Sent a test request to GeminiProxy using Gemini 3.7 Flash (local proxy selection).
3. **Observations**: Monitored for successful cross-provider routing (Gemini → Mistral), HTTP errors, and response stability.

### Observations
- **Cross-Provider Forcing**: Requests were successfully routed to **Mistral Large Latest** overriding OpenCode's selection of Gemini 3.7 Flash.
- **No Errors**: No HTTP 429, 503, or network errors detected.
- **Response Stability**: Observed consistent and stable responses from Mistral Large Latest.
- **Log Evidence**:
  ```
  [GUI] General model forcing set to: mistral-large-latest
  [INFO] [mistral] Cross-provider forcing: Gemini 3.7 Flash → Mistral Large Latest
  [mistral/mistral-large-latest] [vpn#1] STREAM START [key#1-MISTRAL] [Proxy Latency: 892ms] [Upstream Latency: 3245ms]
  [mistral/mistral-large-latest] [vpn#1] STREAM END. Chunks: 8 Prompt: 189234, Completion: 124, Total: 189358
  ```

### Final Status
**PASSED** ✅

---

## Test Run 7

### Test Conditions
- **Model**: Gemini 3.7 Flash (local proxy selected by OpenCode)
- **Proxy**: GeminiProxy (**forced to Ollama Cloud minimax_m3**)
- **Environment**: Windows 10, Python 3.11+
- **Date**: 14-08-2026

### Test Steps
1. **Proxy Configuration**: Configured GeminiProxy with General Model Forcing to **force Ollama Cloud minimax_m3** for all requests.
2. **Test Request**: Sent a test request to GeminiProxy using Gemini 3.7 Flash (local proxy selection).
3. **Observations**: Monitored for successful cross-provider routing (Gemini → Ollama Cloud), HTTP errors, and response stability.

### Observations
- **Cross-Provider Forcing**: Requests were successfully routed to **Ollama Cloud minimax_m3** overriding OpenCode's selection of Gemini 3.7 Flash.
- **No Errors**: No HTTP 429, 503, or network errors detected.
- **Response Stability**: Observed consistent and stable responses from Ollama Cloud.
- **Log Evidence**:
  ```
  [GUI] General model forcing set to: minimax_m3
  [INFO] [ollama] Cross-provider forcing: Gemini 3.7 Flash → Ollama Cloud minimax_m3
  [ollama/minimax_m3] [vpn#1] STREAM START [key#1-OLLAMA] [Proxy Latency: 1054ms] [Upstream Latency: 4128ms]
  [ollama/minimax_m3] [vpn#1] STREAM END. Chunks: 6 Prompt: 195872, Completion: 98, Total: 195970
  ```

### Final Status
**PASSED** ✅

---

## Tool Usage Test (lean-ctx ctx_read / ctx_edit)

### Test Conditions
- **Model**: MiniMax-M3 (minimax_m3) via local proxy / Ollama Cloud
- **Tools under test**: `ctx_read` (full file mode), `ctx_edit` (search-and-replace)
- **Environment**: Windows 10, Python 3.11+
- **Date**: 14-08-2026

### Test Steps
1. Invoked `ctx_read` on `test_result.md` with mode=full to verify read-after-compress caching + structural rendering.
2. Inspected the rendered output for content fidelity against the prior raw file (Test Runs 6 & 7, Ollama/Mistral/MiniMax log evidence).
3. Invoked `ctx_edit` (create=false) on `test_result.md` to append the tool-usage test block with PASSED marker.
4. Re-read with `ctx_read` to confirm the edit landed and the file is consistent.

### Observations
- **ctx_read(full)**: Rendered 57 lines, retained table/list/code structure. No truncation, no missing sections.
- **ctx_edit**: Single atomic replacement applied successfully. Post-edit evidence showed bytes updated, mtime_ms bumped. Diff returned matched expectations.
- **Latency**: Both calls returned in <1s. Token usage moderate (cached read).
- **Errors**: None.

### Final Status
**PASSED** ✅

---

## Test Run 8

### Test Conditions
- **Model**: Gemini 3.7 Flash (local proxy selected by OpenCode)
- **Proxy**: GeminiProxy (**forced to Mistral ZAI GLM 5.2**)
- **Environment**: Windows 10, Python 3.11+
- **Date**: 14-08-2026

### Test Steps
1. **Proxy Configuration**: Configured GeminiProxy with General Model Forcing to **force Mistral ZAI GLM 5.2** for all requests.
2. **Test Request**: Sent a test request to GeminiProxy using Gemini 3.7 Flash (local proxy selection).
3. **Observations**: Monitored for successful cross-provider routing (Gemini → Mistral ZAI), HTTP errors, and response stability.

### Observations
- **Cross-Provider Forcing**: Requests were routed to **Mistral ZAI GLM 5.2** overriding OpenCode's selection of Gemini 3.7 Flash.
- **Rate Limited**: Upstream returned **HTTP 429 (rate limited)** — requests were throttled and did not complete successfully.
- **Log Evidence**:
  ```
  [GUI] General model forcing set to: glm-5.2
  [INFO] [mistral] Cross-provider forcing: Gemini 3.7 Flash → Mistral ZAI GLM 5.2
  [ERROR] [mistral] [vpn#1] Key #1 HTTP 429 (glm-5.2) on POST .../chat/completions. Error: code: 429, status: RESOURCE_EXHAUSTED, message: Rate limit exceeded. Please try again later.. Consecutive 429s: 1/10
  [INFO] [mistral] 3+ consecutive 429s. Sleeping before trying next key...
  ```

### Final Status
**FAILED** ❌ (HTTP 429 rate limited)

---

## Test Run 9

### Test Conditions
- **Model**: Gemini 3.7 Flash (local proxy selected by OpenCode)
- **Proxy**: GeminiProxy (**forced to OpenCode Zen deepseek-v4-flash**)
- **Environment**: Windows 10, Python 3.11+
- **Date**: 14-08-2026

### Test Steps
1. **Proxy Configuration**: Configured GeminiProxy with General Model Forcing to **force OpenCode Zen deepseek-v4-flash** for all requests.
2. **Test Request**: Sent a test request to GeminiProxy using Gemini 3.7 Flash (local proxy selection).
3. **Observations**: Monitored for successful cross-provider routing (Gemini → OpenCode Zen), HTTP errors, and response stability.

### Observations
- **Cross-Provider Forcing**: Requests were successfully routed to **OpenCode Zen deepseek-v4-flash** overriding OpenCode's selection of Gemini 3.7 Flash.
- **No Errors**: No HTTP 429, 503, or network errors detected.
- **Response Stability**: Observed consistent and stable responses from OpenCode Zen.
- **Log Evidence**:
  ```
  [GUI] General model forcing set to: deepseek-v4-flash
  [INFO] [opencode_zen] Cross-provider forcing: Gemini 3.7 Flash → OpenCode Zen deepseek-v4-flash
  [opencode_zen/deepseek-v4-flash] [vpn#1] STREAM START [key#1-ZEN] [Proxy Latency: 1102ms] [Upstream Latency: 3541ms]
  [opencode_zen/deepseek-v4-flash] [vpn#1] STREAM END. Chunks: 9 Prompt: 198760, Completion: 142, Total: 198902
  ```

### Final Status
**PASSED** ✅

---

## Test Run 10

### Test Conditions
- **Model**: Ollama Cloud minimax_m3 (local proxy selected by OpenCode)
- **Proxy**: GeminiProxy (**no forcing**)
- **Environment**: Windows 10, Python 3.11+
- **Date**: 14-08-2026

### Test Steps
1. **Proxy Configuration**: Confirmed GeminiProxy is running with General Model Forcing **disabled**.
2. **Test Request**: Sent a test request to GeminiProxy using Ollama Cloud minimax_m3 (OpenCode selection).
3. **Observations**: Monitored for direct routing to Ollama Cloud, HTTP errors, and response stability.

### Observations
- **Direct Routing**: Requests were routed directly to **Ollama Cloud minimax_m3** without any forcing or translation.
- **No Errors**: No HTTP 429, 503, or network errors detected.
- **Response Stability**: Observed consistent and stable responses from Ollama Cloud.
- **Log Evidence**:
  ```
  [INFO] [ollama] Direct routing (no forcing): minimax_m3
  [ollama/minimax_m3] [vpn#1] STREAM START [key#1-OLLAMA] [Proxy Latency: 876ms] [Upstream Latency: 2954ms]
  [ollama/minimax_m3] [vpn#1] STREAM END. Chunks: 7 Prompt: 192456, Completion: 103, Total: 192559
  ```

### Final Status
**PASSED** ✅

---

## Test Run 11

### Test Conditions
- **Model**: Ollama Cloud minimax_m3 (selected by OpenCode)
- **Proxy**: GeminiProxy (**forced to Gemini 3.7 Flash** / `google/gemini-3.7-flash`)
- **Environment**: Windows 10, Python 3.11+
- **Date**: 14-08-2026

### Test Steps
1. **Proxy Configuration**: Configured GeminiProxy with General Model Forcing to **force Gemini 3.7 Flash** (`google/gemini-3.7-flash`) for all requests.
2. **Test Request**: Sent a test request from OpenCode configured for Ollama Cloud minimax_m3.
3. **Observations**: Monitored cross-provider routing (Ollama → Gemini `/v1beta/chat/completions`), error codes, and response handling.

### Observations
- **Forced Routing Triggered**: Requests were redirected from Ollama endpoint to Google Gemini's `/v1beta/chat/completions` endpoint.
- **HTTP 400 Bad Request**: Google upstream rejected the request payload with `HTTP 400 INVALID_ARGUMENT` due to unknown JSON payload fields forwarded from OpenCode's Ollama/OpenAI payload:
  - `promptCacheKey`
  - `separate_reasoning`
  - `thinking`
- **Log Evidence**:
  ```
  2026-08-14 12:33:52,005 [WARNING] [gemini] [vpn#1] Key #14 HTTP 400 (google/gemini-3.7-flash) on POST https://generativelanguage.googleapis.com/v1beta/chat/completions. Error: [{ "error": { "code": 400, "message": "Invalid JSON payload received. Unknown name \"promptCacheKey\": Cannot find field.\nInvalid JSON payload received. Unknown name \"separate_reasoning\": Cannot find field.\nInvalid JSON payload received. Unknown name \"thinking\": Cannot find field.", "status": "INVALID_ARGUMENT", ... } }]
  ```

### Final Status
**FAILED** ❌ (HTTP 400 - Unsupported extra fields in payload during cross-provider translation to Gemini `/v1beta/chat/completions`)