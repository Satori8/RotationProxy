# Resilient Key and Model Rotation Proxy Implementation Plan (Updated)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Further optimize the proxy's fault tolerance and purity:
1. **Remove Groq:** Remove Groq keys, endpoints, and conditions entirely from `proxy3.py`.
2. **Deduplicate Code:** Eliminate the duplicate `MODEL_SETTINGS` declaration.
3. **Global Provider Rate Limiting:** Enforce a strict 1 request per second per provider rate limit, returning 429 immediately on violations.
4. **Error Log Cleanup:** Successfully utilized keys are automatically removed from `error_keys_log.json`.
5. **Rework fallback list:**
   - Use only FREE models.
   - For `gemini-flash-lite`, the correct name is `gemini-flash-lite-latest`.
   - Expand `gemini-3.6-flash` with the "most thinking" free models (such as deepseek R1 free, qwen coder free, or other thinking free models from OpenRouter).
   - Expand `gemini-flash-lite-latest` with the "fastest" free models (OpenCode Zen + OpenRouter free).

**Tech Stack:** FastAPI, Asyncio, httpx, Python 3.12+

---

### Task 6: Remove Groq Keys and Provider

**Files:**
- Modify: `proxy3.py`

- [ ] **Step 1: Remove Groq constants and loader**
Delete `GROQ_KEYS_FILE` and `GROQ_KEYS = load_keys_from_file(GROQ_KEYS_FILE)`.

- [ ] **Step 2: Clean path prefix and auth handlers for Groq**
Remove `elif path.startswith("groq/")` routing check in `transparent_proxy`.
Change `provider_name in ("openrouter", "mistral", "groq")` to `provider_name in ("openrouter", "mistral")`.

- [ ] **Step 3: Run py_compile to ensure no syntax errors**
Run: `python -m py_compile proxy3.py`

---

### Task 7: Implement Global Rate Limit of 1 req/sec per Provider

**Files:**
- Modify: `proxy3.py`

- [ ] **Step 1: Initialize `LAST_REQUEST_TIME` global dict**
Define `LAST_REQUEST_TIME: dict[str, float] = {}` at the top level.

- [ ] **Step 2: Add rate limit check after provider resolution**
Directly after identifying the incoming `provider_name`, add:
```python
    now = time.time()
    last_time = LAST_REQUEST_TIME.get(provider_name, 0.0)
    if now - last_time < 1.0:
        return JSONResponse(
            status_code=429,
            content={
                "error": {
                    "message": f"Rate limit exceeded for provider '{provider_name}'. Max 1 request per second."
                }
            },
        )
    LAST_REQUEST_TIME[provider_name] = now
```

---

### Task 8: Implement Key Removal from Error Log Upon Success

**Files:**
- Modify: `proxy3.py`

- [ ] **Step 1: Define `remove_key_from_error_log` helper**
Implement a helper to delete matched model/key pairs from `error_keys_log.json`:
```python
def remove_key_from_error_log(model: str, key: str) -> None:
    ERROR_LOG_PATH = "error_keys_log.json"
    try:
        if os.path.exists(ERROR_LOG_PATH):
            with open(ERROR_LOG_PATH, "r", encoding="utf-8") as f:
                error_log = json.load(f)
            
            prefix_to_match = f"{model}|{key}|"
            keys_to_remove = [k for k in error_log if k.startswith(prefix_to_match)]
            
            if keys_to_remove:
                for k in keys_to_remove:
                    del error_log[k]
                with open(ERROR_LOG_PATH, "w", encoding="utf-8") as f:
                    json.dump(error_log, f, indent=2, ensure_ascii=False)
                logger.info(f"Removed key {key[:8]}... from error log after successful request.")
    except Exception as e:
        logger.error(f"Failed to remove key from error log: {e}")
```

- [ ] **Step 2: Call helper upon HTTP 200**
In the successful `response.status_code == 200` branch, call `remove_key_from_error_log(candidate_model, api_key)`.

---

### Task 9: Deduplicate and Expand MODEL_SETTINGS and Fallback Lists

**Files:**
- Modify: `proxy3.py`
- Modify: `config_rotation.json`

- [ ] **Step 1: Replace duplicate `MODEL_SETTINGS` with unified expanded version**
Clean up the duplicate dictionaries and define one complete `MODEL_SETTINGS` mapping at the top of `proxy3.py` featuring the expanded free models:
- google-flash-3.5 domain: `gemini-3.6-flash`, `deepseek/deepseek-r1:free`, `qwen/qwen-2.5-72b-instruct:free`, `meta-llama/llama-3.3-70b-instruct:free`, `deepseek/deepseek-chat:free`.
- flash-lite domain: `gemini-flash-lite-latest`, `deepseek-v4-flash-free`, `mimo-v2.5-free`, `nemotron-3-super-free`, `google/gemini-2.5-flash:free`, `google/gemma-2-9b-it:free`, `meta-llama/llama-3.1-8b-instruct:free`, `qwen/qwen-2.5-coder-32b-instruct:free`.

- [ ] **Step 2: Rename `gemini-2.0-flash-lite` to `gemini-flash-lite-latest`**
Update `get_requested_model` and the load config defaults to use the correct model name.

- [ ] **Step 3: Update `config_rotation.json` defaults and clean existing file**
Write the updated lists and states into `config_rotation.json`.
