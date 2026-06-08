# OpenCode Zen Provider Integration Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal**: Integrate OpenCode Zen as a fully supported provider in GeminiProxy (rotation proxy, model manager, and GUI) and add `opencode-zen-local` to `opencode.json` routing to our proxy.

**Architecture**: Add `OPENCODE_KEYS` loading from a secure vault file. Enable dynamic registration and routing for `opencode/` and `opencode_zen/` models, translating payloads to OpenAI format and forwarding them to `https://opencode.ai/zen/v1`. Expose model fetching and testing in the GUI.

**Tech Stack**: Python, FastAPI, httpx, CustomTkinter, JSON.

---

### Task 1: Load OpenCode Zen API Keys

**Files:**
- Modify: `proxy_core/rotation.py`

- [ ] **Step 1: Add OpenCode Keys File Path and Loader**

Add `OPENCODE_KEYS_FILE` and load `OPENCODE_KEYS` under `OLLAMA_CLOUD_KEYS`.

```python
# In proxy_core/rotation.py
OPENCODE_KEYS_FILE = (
    r"D:\Personal\myvault\90 Private\Sensitive\OpenCode API Keys.md"
)
```

And load it:

```python
# In proxy_core/rotation.py
OPENCODE_KEYS = load_keys_from_file(OPENCODE_KEYS_FILE)
```

- [ ] **Step 2: Run compilation check**

Run: `python -m py_compile proxy_core/rotation.py`
Expected: PASS with no syntax errors.

- [ ] **Step 3: Commit changes**

```bash
git add proxy_core/rotation.py
git commit -m "feat(rotation): load OpenCode Zen API keys from vault"
```

---

### Task 2: Add Provider Support and Dynamic Model Registration

**Files:**
- Modify: `proxy_core/server.py`

- [ ] **Step 1: Import `OPENCODE_KEYS`**

Import `OPENCODE_KEYS` from `proxy_core.rotation`.

```python
# In proxy_core/server.py
from proxy_core.rotation import (
    API_KEYS,
    OPENROUTER_KEYS,
    MISTRAL_KEYS,
    LLM7_KEYS,
    OLLAMA_KEYS,
    OLLAMA_CLOUD_KEYS,
    OPENCODE_KEYS,  # Add this
)
```

- [ ] **Step 2: Add Dynamic Model Registration for OpenCode**

In `get_requested_model` (around line 1360), add dynamic registration for `opencode/` and `opencode_zen/` models.

```python
            elif candidate_model.startswith("opencode/") or candidate_model.startswith(
                "opencode_zen/"
            ):
                target_model = (
                    candidate_model[9:]
                    if candidate_model.startswith("opencode/")
                    else candidate_model[13:]
                )
                MODEL_SETTINGS[candidate_model] = {
                    "provider": "opencode_zen",
                    "base_url": "https://opencode.ai/zen/v1",
                    "keys_pool": OPENCODE_KEYS,
                    "target_model": target_model,
                }
                logger.info(
                    f"Dynamically registered OpenCode Zen settings for model '{candidate_model}' with target model '{target_model}'"
                )
```

- [ ] **Step 3: Handle Path Stripping for OpenCode**

In `get_requested_model` path stripping block (around line 1465), strip `opencode/` and `opencode_zen/` prefixes.

```python
                elif path.startswith("ollama/"):
                    target_path = path[7:]
                elif path.startswith("opencode/"):
                    target_path = path[9:]
                elif path.startswith("opencode_zen/"):
                    target_path = path[13:]
```

- [ ] **Step 4: Add `opencode_zen` to Authorization Headers and Payload Translation**

In the request dispatch loop (around line 1567 and 1573), add `"opencode_zen"` to the list of providers requiring Bearer authorization and payload translation.

```python
            if provider_name in ("openrouter", "mistral", "llm7", "ollama_cloud", "opencode_zen"):
                headers["authorization"] = f"Bearer {api_key}"
            else:
                headers["x-goog-api-key"] = api_key
```

And:

```python
            if provider_name in ("openrouter", "mistral", "llm7", "ollama_cloud", "opencode_zen"):
                try:
                    body_dict = json.loads(body)
                    translated_body = translate_payload_to_openai(
                        body_dict, target_model_id
                    )
```

- [ ] **Step 5: Run compilation check**

Run: `python -m py_compile proxy_core/server.py`
Expected: PASS with no syntax errors.

- [ ] **Step 6: Commit changes**

```bash
git add proxy_core/server.py
git commit -m "feat(server): support opencode_zen provider and dynamic model registration"
```

---

### Task 3: Support OpenCode Zen in Model Testing Endpoint

**Files:**
- Modify: `proxy_core/server.py`

- [ ] **Step 1: Add `opencode_zen` to `test_model_endpoint`**

In `test_model_endpoint` (around line 950), add the provider mapping.

```python
    elif provider_name == "ollama_cloud":
        base_url = "https://ollama.com/v1"
        keys_pool = OLLAMA_CLOUD_KEYS
    elif provider_name == "opencode_zen":
        base_url = "https://opencode.ai/zen/v1"
        keys_pool = OPENCODE_KEYS
```

And add `"opencode_zen"` to the authorization header check (around line 976):

```python
    if provider_name in ("openrouter", "mistral", "llm7", "ollama", "ollama_cloud", "opencode_zen"):
        headers["authorization"] = f"Bearer {api_key}"
```

- [ ] **Step 2: Run compilation check**

Run: `python -m py_compile proxy_core/server.py`
Expected: PASS with no syntax errors.

- [ ] **Step 3: Commit changes**

```bash
git add proxy_core/server.py
git commit -m "feat(server): add opencode_zen support to test_model_endpoint"
```

---

### Task 4: Expose OpenCode Zen in GUI Model Fetcher

**Files:**
- Modify: `proxy_core/gui.py`

- [ ] **Step 1: Add "OpenCode Zen" to Provider Dropdown**

In `proxy_core/gui.py` (around line 462), add `"OpenCode Zen"` to the combobox values.

```python
        self.provider_dropdown = ctk.CTkComboBox(
            self.model_tab,
            variable=self.provider_var,
            values=["OpenRouter", "Ollama", "LLM7", "Mistral", "OpenCode Zen"],
        )
```

- [ ] **Step 2: Add "OpenCode Zen" Fetch Logic**

In `do_fetch` (around line 1064), add the fetching logic for OpenCode Zen.

```python
            elif provider == "OpenCode Zen":
                url = "https://opencode.ai/zen/v1/models"
                try:
                    from proxy_core.rotation import OPENCODE_KEYS

                    headers = {"User-Agent": "Mozilla/5.0"}
                    if OPENCODE_KEYS:
                        headers["Authorization"] = f"Bearer {OPENCODE_KEYS[0]}"
                    req = urllib.request.Request(url, headers=headers)
                    with urllib.request.urlopen(req, timeout=8.0) as response:
                        data = json.loads(response.read().decode("utf-8"))
                        models = []
                        for m in data.get("data", []):
                            models.append(
                                {
                                    "id": m.get("id"),
                                    "name": m.get("id"),
                                    "context_length": "unknown",
                                    "provider": "opencode_zen",
                                }
                            )
                        # Sort by id
                        models = sorted(models, key=lambda x: x["id"])
                        self.after(0, lambda: self.render_free_models(models))
                except Exception as e:
                    logger.error(f"[GUI] Failed to fetch OpenCode Zen models: {e}")
                    self.after(
                        0,
                        lambda: self.fetch_btn.configure(
                            state="normal", text="Fetch Models"
                        ),
                    )
```

- [ ] **Step 3: Run compilation check**

Run: `python -m py_compile proxy_core/gui.py`
Expected: PASS with no syntax errors.

- [ ] **Step 4: Commit changes**

```bash
git add proxy_core/gui.py
git commit -m "feat(gui): expose OpenCode Zen provider in model fetcher dropdown"
```

---

### Task 5: Add `opencode-zen-local` Provider to `opencode.json`

**Files:**
- Modify: `E:\Appdata\.config\opencode-profiles\default\opencode.json`

- [ ] **Step 1: Add `opencode-zen-local` Configuration**

Add the `opencode-zen-local` provider under `opencode` provider in `opencode.json`.

```json
    "opencode-zen-local": {
      "models": {
        "deepseek-v4-flash-free": {
          "limit": {
            "context": 262144,
            "input": 262144,
            "output": 8192
          },
          "name": "DeepSeek V4 Flash Free (Local Proxy)",
          "temperature": true,
          "tool_call": true
        }
      },
      "name": "OpenCode Zen Local Proxy",
      "npm": "@ai-sdk/openai-compatible",
      "options": {
        "apiKey": "test",
        "baseURL": "http://127.0.0.1:4000/opencode_zen",
        "setCacheKey": true
      }
    },
```

- [ ] **Step 2: Verify JSON Validity**

Parse the modified `opencode.json` using Python to ensure it remains syntactically valid.

Run: `python -c "import json; json.load(open(r'E:\Appdata\.config\opencode-profiles\default\opencode.json', 'r', encoding='utf-8'))"`
Expected: PASS with no errors.

- [ ] **Step 3: Commit changes**

Since `opencode.json` is outside the git repository, we do not commit it to git, but we verify it is updated correctly.

---

### Task 6: End-to-End Verification and Testing

- [ ] **Step 1: Run pytest suite**

Run: `pytest`
Expected: All tests pass.

- [ ] **Step 2: Start the proxy server**

Run: `python proxy3.py`
Expected: Server starts successfully on port 4000.
