# Modular Proxy Split & Refined Logger Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor `proxy3.py` into a clean subpackage `proxy_core/` while implementing refined colored logging, silenced third-party logs, deterministic hashing of error files, success key sequence reset, increased daily limit thresholds, and robust Windows process tree termination upon GUI closure.

**Architecture:**
* Split into modules inside `proxy_core/`: `logger.py`, `config.py`, `state.py`, `rotation.py`, `server.py`, `gui.py`.
* Expose `/control/reset_cooldowns` to safely reset memory/disk states across processes.
* Add a dark red "Reset Daily Cooldowns" button to the GUI.
* Ensure ANSI codes are stripped in the GUI.
* `proxy3.py` remains as the direct entry point.

---

### Task 1: Create Shared Modules (`logger.py`, `config.py`, `state.py`)

**Files:**
- Create: `proxy_core/__init__.py`
- Create: `proxy_core/logger.py`
- Create: `proxy_core/config.py`
- Create: `proxy_core/state.py`

- [ ] **Step 1: Create `proxy_core/__init__.py`**
Create an empty package marker.

- [ ] **Step 2: Create `proxy_core/logger.py`**
Implement the colorized formatter and silence third-party loggers:

```python
import logging

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

- [ ] **Step 3: Create `proxy_core/config.py`**
Define configurations and config file load/save actions:

```python
import os
import json
import logging

logger = logging.getLogger("proxy")

ROTATION_CONFIG_PATH = "config_rotation.json"

FORCE_MODEL = {"gemini-3.6-flash": "auto", "gemini-flash-lite-latest": "auto"}
USE_KAGGLE = False
SAVE_CHAT_LOGS = False
KAGGLE_BASE_URL = "https://fine-cable-outside-escape.trycloudflare.com/v1"

def load_rotation_config() -> dict:
    target_gemini_35_list = [
        "gemini-3.6-flash",
        "deepseek/deepseek-r1:free",
        "qwen/qwen-2.5-72b-instruct:free",
        "meta-llama/llama-3.3-70b-instruct:free",
        "deepseek/deepseek-chat:free",
    ]
    target_lite_list = [
        "gemini-flash-lite-latest",
        "deepseek-v4-flash-free",
        "mimo-v2.5-free",
        "nemotron-3-super-free",
        "google/gemini-2.5-flash:free",
        "google/gemma-2-9b-it:free",
        "meta-llama/llama-3.1-8b-instruct:free",
        "qwen/qwen-2.5-coder-32b-instruct:free",
    ]

    try:
        if os.path.exists(ROTATION_CONFIG_PATH):
            with open(ROTATION_CONFIG_PATH, "r", encoding="utf-8") as f:
                config = json.load(f)

            needs_upgrade = False
            if "rotation_lists" not in config:
                config["rotation_lists"] = {}
                needs_upgrade = True

            if "gemini-2.0-flash-lite" in config.get("rotation_lists", {}):
                del config["rotation_lists"]["gemini-2.0-flash-lite"]
                needs_upgrade = True

            if "gemini-3.6-flash" not in config["rotation_lists"]:
                config["rotation_lists"]["gemini-3.6-flash"] = target_gemini_35_list
                needs_upgrade = True
            else:
                current_35_list = config["rotation_lists"]["gemini-3.6-flash"]
                for model in target_gemini_35_list:
                    if model not in current_35_list:
                        current_35_list.append(model)
                        needs_upgrade = True

            if "gemini-flash-lite-latest" not in config["rotation_lists"]:
                config["rotation_lists"]["gemini-flash-lite-latest"] = target_lite_list
                needs_upgrade = True
            else:
                current_lite_list = config["rotation_lists"]["gemini-flash-lite-latest"]
                for model in target_lite_list:
                    if model not in current_lite_list:
                        current_lite_list.append(model)
                        needs_upgrade = True

            if "use_kaggle" not in config:
                config["use_kaggle"] = USE_KAGGLE
                needs_upgrade = True

            if "force_model" not in config:
                config["force_model"] = FORCE_MODEL
                needs_upgrade = True

            if "save_chat_logs" not in config:
                config["save_chat_logs"] = SAVE_CHAT_LOGS
                needs_upgrade = True

            if needs_upgrade:
                save_rotation_config(config)
                logger.info("Rotation config upgraded to latest resilient schema.")

            return config
    except Exception as e:
        logger.error(f"Failed to load rotation config: {e}")

    return {
        "last_fallback_switch_time": 0.0,
        "model_cooldowns": {},
        "consecutive_model_failures": {},
        "rotation_lists": {
            "gemini-3.6-flash": target_gemini_35_list,
            "gemini-flash-lite-latest": target_lite_list,
        },
        "use_kaggle": False,
        "force_model": {"gemini-3.6-flash": "auto", "gemini-flash-lite-latest": "auto"},
        "save_chat_logs": False,
    }

def save_rotation_config(config: dict) -> None:
    try:
        with open(ROTATION_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Failed to save rotation config: {e}")
```

- [ ] **Step 4: Create `proxy_core/state.py`**
Declare runtime states:

```python
import queue

log_queue = queue.Queue()

COOLDOWNS = {}
CONSECUTIVE_429S = {}
LAST_429_TIME = {}
CONSECUTIVE_RPD_429S = {}
LAST_USED = {}
LAST_REQUEST_TIME = {}
```

- [ ] **Step 5: Commit**
```bash
git add proxy_core/__init__.py proxy_core/logger.py proxy_core/config.py proxy_core/state.py
git commit -m "feat: create core configurations, logger, and runtime state modules"
```

---

### Task 2: Create Rotation Business Logic (`rotation.py`)

**Files:**
- Create: `proxy_core/rotation.py`

- [ ] **Step 1: Implement keys loading and error logging with deterministic MD5**
This includes checking for empty or corrupted error logging files, and using MD5 to aggregate error records correctly.

```python
import os
import json
import time
import hashlib
import logging
from proxy_core.config import load_rotation_config, save_rotation_config

logger = logging.getLogger("proxy")

KEYS_FILE_PATH = r"D:\Personal\myvault\90 Private\Sensitive\Google API Keys.md"
OPENROUTER_KEYS_FILE = r"D:\Personal\myvault\90 Private\Sensitive\OpenRouter API Keys.md"
MISTRAL_KEYS_FILE = r"D:\Personal\myvault\90 Private\Sensitive\Mistral API Keys.md"
LLM7_KEYS_FILE = r"D:\Personal\myvault\90 Private\Sensitive\LLM7 Api Keys.md"

def load_keys_from_file(filepath: str) -> list[str]:
    keys = []
    try:
        if os.path.exists(filepath):
            with open(filepath, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if line.startswith("- ") or line.startswith("* "):
                        line = line[2:].strip()
                    elif line.startswith("-") or line.startswith("*"):
                        line = line[1:].strip()
                    line = line.replace("`", "")
                    if line:
                        keys.append(line)
            logger.info(f"Loaded {len(keys)} keys from '{filepath}'.")
        else:
            logger.warning(f"Keys file not found at '{filepath}'.")
    except Exception as e:
        logger.error(f"Failed to read keys from '{filepath}': {e}")
    return keys

API_KEYS = load_keys_from_file(KEYS_FILE_PATH)
OPENROUTER_KEYS = load_keys_from_file(OPENROUTER_KEYS_FILE)
MISTRAL_KEYS = load_keys_from_file(MISTRAL_KEYS_FILE)
LLM7_KEYS = load_keys_from_file(LLM7_KEYS_FILE)

def seconds_until_rpd_reset() -> float:
    import datetime
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    reset_today = now_utc.replace(hour=8, minute=0, second=0, microsecond=0)
    if now_utc >= reset_today:
        reset_time = reset_today + datetime.timedelta(days=1)
    else:
        reset_time = reset_today
    return (reset_time - now_utc).total_seconds()

def log_non_429_error(model: str, key: str, error_msg: str) -> None:
    ERROR_LOG_PATH = "error_keys_log.json"
    try:
        error_hash = hashlib.md5(error_msg.encode("utf-8")).hexdigest()
        error_id = f"{model}|{key}|{error_hash}"

        if os.path.exists(ERROR_LOG_PATH) and os.path.getsize(ERROR_LOG_PATH) > 0:
            with open(ERROR_LOG_PATH, "r", encoding="utf-8") as f:
                try:
                    error_log = json.load(f)
                except json.JSONDecodeError:
                    error_log = {}
        else:
            error_log = {}

        if error_id in error_log:
            error_log[error_id]["count"] += 1
            error_log[error_id]["last_occurrence"] = time.time()
        else:
            error_log[error_id] = {
                "model": model,
                "key": key,
                "error_message": error_msg,
                "count": 1,
                "first_occurrence": time.time(),
                "last_occurrence": time.time(),
            }

        with open(ERROR_LOG_PATH, "w", encoding="utf-8") as f:
            json.dump(error_log, f, indent=2, ensure_ascii=False)

        logger.info(
            f"Logged error for {model} with key {key[:8]}... (count: {error_log[error_id]['count']})"
        )
    except Exception as e:
        logger.error(f"Failed to log error to {ERROR_LOG_PATH}: {e}")

def remove_key_from_error_log(model: str, key: str) -> None:
    ERROR_LOG_PATH = "error_keys_log.json"
    try:
        if not os.path.exists(ERROR_LOG_PATH) or os.path.getsize(ERROR_LOG_PATH) == 0:
            return

        with open(ERROR_LOG_PATH, "r", encoding="utf-8") as f:
            try:
                error_log = json.load(f)
            except json.JSONDecodeError:
                return

        prefix = f"{model}|{key}|"
        keys_to_remove = [
            error_id for error_id in error_log.keys() if error_id.startswith(prefix)
        ]

        if keys_to_remove:
            for error_id in keys_to_remove:
                del error_log[error_id]

            with open(ERROR_LOG_PATH, "w", encoding="utf-8") as f:
                json.dump(error_log, f, indent=2, ensure_ascii=False)

            logger.info(
                f"Removed {len(keys_to_remove)} error log entries for {model} with key {key[:8]}..."
            )
    except Exception as e:
        logger.error(
            f"Failed to remove error log entries for {model} with key {key[:8]}...: {e}"
        )
```

- [ ] **Step 2: Commit**
```bash
git add proxy_core/rotation.py
git commit -m "feat: implement key loading and robust error log tracking"
```

---

### Task 3: Create FastAPI Server Module (`server.py`)

**Files:**
- Create: `proxy_core/server.py`

- [ ] **Step 1: Implement Server core, Reset route, and Request routing with Custom formatting**
This incorporates:
* Increasing daily RPD limit failure threshold to `3`.
* Resetting the sequence limit on success (`CONSECUTIVE_RPD_429S[api_key] = 0`).
* Outputting exactly one request log in custom format: `[TIMESTAMP] [LEVEL] [model] [key#suffix] [status_code]`.
* Using shorter, concise warnings/delay messages.
* Injecting uvicorn/logger dependencies explicitly.

```python
import time
import json
import random
import asyncio
import logging
import datetime
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import httpx

from proxy_core import logger as core_logger
from proxy_core.config import (
    load_rotation_config,
    save_rotation_config,
    FORCE_MODEL,
    USE_KAGGLE,
    SAVE_CHAT_LOGS,
    KAGGLE_BASE_URL,
    ROTATION_CONFIG_PATH
)
from proxy_core.state import (
    log_queue,
    COOLDOWNS,
    CONSECUTIVE_429S,
    LAST_429_TIME,
    CONSECUTIVE_RPD_429S,
    LAST_USED,
    LAST_REQUEST_TIME
)
from proxy_core.rotation import (
    API_KEYS,
    OPENROUTER_KEYS,
    MISTRAL_KEYS,
    LLM7_KEYS,
    seconds_until_rpd_reset,
    log_non_429_error,
    remove_key_from_error_log
)
from proxy_core.state import log_queue as global_log_queue
import queue

logger = logging.getLogger("proxy")

class QueueLogHandler(logging.Handler):
    def emit(self, record):
        try:
            global_log_queue.put(self.format(record))
        except Exception:
            pass

queue_handler = QueueLogHandler()
queue_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logger.addHandler(queue_handler)

PRIMARY_MODEL = "gemini-3.6-flash"
FALLBACK_MODEL = "gemini-3-flash-preview"
RETRY_DELAY_SECONDS = 90
PROCESS_SESSION_ID = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
TARGET_BASE_URL = "https://generativelanguage.googleapis.com"

MODEL_SETTINGS = {
    "gemini-3.6-flash": {
        "provider": "gemini",
        "base_url": "https://generativelanguage.googleapis.com",
        "keys_pool": API_KEYS,
        "target_model": "gemini-3.6-flash",
    },
    "gemini-3-flash-preview": {
        "provider": "gemini",
        "base_url": "https://generativelanguage.googleapis.com",
        "keys_pool": API_KEYS,
        "target_model": "gemini-3-flash-preview",
    },
    "deepseek-v4-flash": {
        "provider": "openrouter",
        "base_url": "https://openrouter.ai/api/v1",
        "keys_pool": OPENROUTER_KEYS,
        "target_model": "deepseek-v4-flash",
    },
    "gemini-flash-lite-latest": {
        "provider": "gemini",
        "base_url": "https://generativelanguage.googleapis.com",
        "keys_pool": API_KEYS,
        "target_model": "gemini-flash-lite-latest",
    },
    "deepseek-v4-flash-free": {
        "provider": "openrouter",
        "base_url": "https://openrouter.ai/api/v1",
        "keys_pool": OPENROUTER_KEYS,
        "target_model": "deepseek-v4-flash-free",
    },
    "mimo-v2.5-free": {
        "provider": "openrouter",
        "base_url": "https://openrouter.ai/api/v1",
        "keys_pool": OPENROUTER_KEYS,
        "target_model": "mimo-v2.5-free",
    },
    "nemotron-3-super-free": {
        "provider": "openrouter",
        "base_url": "https://openrouter.ai/api/v1",
        "keys_pool": OPENROUTER_KEYS,
        "target_model": "nemotron-3-super-free",
    },
    "deepseek/deepseek-r1:free": {
        "provider": "openrouter",
        "base_url": "https://openrouter.ai/api/v1",
        "keys_pool": OPENROUTER_KEYS,
        "target_model": "deepseek/deepseek-r1:free",
    },
    "qwen/qwen-2.5-72b-instruct:free": {
        "provider": "openrouter",
        "base_url": "https://openrouter.ai/api/v1",
        "keys_pool": OPENROUTER_KEYS,
        "target_model": "qwen/qwen-2.5-72b-instruct:free",
    },
}

EXCLUDED_HEADERS = {
    "content-encoding",
    "content-length",
    "transfer-encoding",
    "connection",
    "keep-alive",
    "host",
}

def get_session_id(request: Request) -> str:
    for h in ["x-session-id", "x-conversation-id", "session-id", "session_id"]:
        val = request.headers.get(h)
        if val:
            sanitized = "".join(c for c in val if c.isalnum() or c in "-_")
            if sanitized:
                return sanitized
    return f"session_{PROCESS_SESSION_ID}"

def get_requested_model(path: str, body: bytes) -> str:
    if "gemini-flash-lite-latest" in path or "gemini-2.0-flash-lite" in path:
        return "gemini-flash-lite-latest"
    if "gemini-3-flash-preview" in path:
        return "gemini-3-flash-preview"
    if "gemini-3.6-flash" in path:
        return "gemini-3.6-flash"

    try:
        data = json.loads(body)
        if isinstance(data, dict) and "model" in data:
            return data["model"]
    except Exception:
        pass
    return "gemini-3.6-flash"

def extract_chat_messages(body: bytes) -> list:
    try:
        data = json.loads(body)
        if isinstance(data, dict):
            if "contents" in data:
                msgs = []
                for content in data["contents"]:
                    role = content.get("role", "user")
                    text = ""
                    parts = content.get("parts", [])
                    if isinstance(parts, list):
                        text = " ".join(p.get("text", "") for p in parts if isinstance(p, dict) and "text" in p)
                    msgs.append({"role": role, "content": text})
                return msgs
            elif "messages" in data:
                msgs = []
                for message in data["messages"]:
                    role = message.get("role", "user")
                    content = message.get("content", "")
                    msgs.append({"role": role, "content": content})
                return msgs
    except Exception as e:
        logger.debug(f"Could not parse chat messages from body: {e}")
    return []

def extract_text_from_chunk(chunk_str: str, provider: str) -> str:
    if provider == "gemini":
        if chunk_str.startswith("data:"):
            chunk_str = chunk_str[5:].strip()
        try:
            data = json.loads(chunk_str)
            candidates = data.get("candidates", [])
            if candidates:
                content = candidates[0].get("content", {})
                parts = content.get("parts", [])
                if parts:
                    return parts[0].get("text", "")
        except Exception:
            pass
    else:
        if chunk_str.startswith("data:"):
            chunk_str = chunk_str[5:].strip()
        try:
            data = json.loads(chunk_str)
            choices = data.get("choices", [])
            if choices:
                delta = choices[0].get("delta", {})
                if "content" in delta:
                    return delta["content"]
        except Exception:
            pass
    return ""

async def write_chat_log(model: str, provider: str, messages: list, response: str, session_id: str):
    import os
    from datetime import datetime
    try:
        log_dir = "chat_logs"
        os.makedirs(log_dir, exist_ok=True)
        today = datetime.now().strftime("%Y-%m-%d")
        log_file = os.path.join(log_dir, f"chat_log_{today}.txt")
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        def do_write():
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"\n{'='*80}\n")
                f.write(f"TIMESTAMP: {timestamp}\n")
                f.write(f"SESSION ID: {session_id}\n")
                f.write(f"MODEL: {model} (Provider: {provider})\n")
                f.write(f"{'-'*80}\n")
                f.write("REQUEST MESSAGES:\n")
                for m in messages:
                    f.write(f"[{m.get('role', 'user')}]: {m.get('content', '')}\n")
                f.write(f"{'-'*80}\n")
                f.write("RESPONSE:\n")
                f.write(response)
                f.write(f"\n{'='*80}\n")

        await asyncio.to_thread(do_write)
        logger.info(f"Saved chat log to {log_file}")
    except Exception as e:
        logger.error(f"Failed to write chat log: {e}")

def translate_payload_to_openai(gemini_payload: dict, target_model: str) -> dict:
    openai_payload = {"model": target_model, "messages": []}
    if "contents" in gemini_payload:
        for content in gemini_payload["contents"]:
            role = content.get("role", "user")
            if role == "model":
                role = "assistant"
            parts = content.get("parts", [])
            text = " ".join(p.get("text", "") for p in parts if isinstance(p, dict) and "text" in p)
            openai_payload["messages"].append({"role": role, "content": text})
    if "generationConfig" in gemini_payload:
        gc = gemini_payload["generationConfig"]
        if "temperature" in gc:
            openai_payload["temperature"] = gc["temperature"]
        if "maxOutputTokens" in gc:
            openai_payload["max_tokens"] = gc["maxOutputTokens"]
        if "topP" in gc:
            openai_payload["top_p"] = gc["topP"]
    return openai_payload

def mark_cooldown(key: str, duration: float = 60.0) -> None:
    COOLDOWNS[key] = time.time() + duration

@asynccontextmanager
async def lifespan(app: FastAPI):
    limits = httpx.Limits(max_keepalive_connections=100, max_connections=200)
    app.state.client = httpx.AsyncClient(timeout=300.0, limits=limits)
    yield
    await app.state.client.aclose()

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post("/control/reset_cooldowns")
async def reset_cooldowns_endpoint():
    global COOLDOWNS, CONSECUTIVE_429S, CONSECUTIVE_RPD_429S
    COOLDOWNS.clear()
    CONSECUTIVE_429S.clear()
    CONSECUTIVE_RPD_429S.clear()
    try:
        config = load_rotation_config()
        config["model_cooldowns"] = {}
        config["consecutive_model_failures"] = {}
        save_rotation_config(config)
    except Exception as e:
        logger.error(f"Failed to clear model cooldowns in config: {e}")
    logger.info("Daily cooldowns and consecutive failure counters have been reset.")
    return {"status": "success", "message": "Cooldowns reset successfully."}

@app.api_route(
    "/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"]
)
async def transparent_proxy(request: Request, path: str):
    max_restarts = 10
    for restart_attempt in range(max_restarts):
        res = await _transparent_proxy_attempt(request, path)
        if res == "RESTART":
            continue
        return res
    return JSONResponse(
        status_code=503,
        content={"error": {"message": "Too many model switches in a single request."}},
    )

async def _transparent_proxy_attempt(request: Request, path: str):
    client = request.app.state.client
    body = await request.body()
    query_params = dict(request.query_params)
    session_id = get_session_id(request)

    if path.startswith("openrouter/"):
        target_base = "https://openrouter.ai/api/v1"
        current_path = path[11:]
        keys_pool = OPENROUTER_KEYS
        provider_name = "openrouter"
    elif path.startswith("mistral/"):
        target_base = "https://api.mistral.ai/v1"
        current_path = path[8:]
        keys_pool = MISTRAL_KEYS
        provider_name = "mistral"
    elif path.startswith("llm7/"):
        target_base = "https://api.llm7.io/v1"
        current_path = path[5:]
        keys_pool = LLM7_KEYS
        provider_name = "llm7"
    else:
        target_base = TARGET_BASE_URL
        current_path = path
        keys_pool = API_KEYS
        provider_name = "gemini"

    current_time = time.time()
    last_request_time = LAST_REQUEST_TIME.get(provider_name, 0.0)
    time_since_last_request = current_time - last_request_time

    if time_since_last_request < 1.0:
        logger.warning(f"[{get_requested_model(path, body)}] [rate-limited] [429]")
        return JSONResponse(
            status_code=429,
            content={
                "error": {
                    "message": f"Rate limit exceeded for provider '{provider_name}'. Please wait {1.0 - time_since_last_request:.2f} seconds before trying again."
                }
            },
        )

    LAST_REQUEST_TIME[provider_name] = current_time

    requested_model = get_requested_model(path, body)
    rotation_config = load_rotation_config()

    global USE_KAGGLE, FORCE_MODEL, SAVE_CHAT_LOGS
    USE_KAGGLE = rotation_config.get("use_kaggle", USE_KAGGLE)
    SAVE_CHAT_LOGS = rotation_config.get("save_chat_logs", SAVE_CHAT_LOGS)
    config_force_model = rotation_config.get("force_model", {})
    for k, v in config_force_model.items():
        FORCE_MODEL[k] = v

    candidates = rotation_config["rotation_lists"].get(requested_model, [requested_model])
    if not candidates:
        candidates = [requested_model]

    if USE_KAGGLE and "qwen3.6" not in candidates:
        candidates = list(candidates) + ["qwen3.6"]

    forced_model = FORCE_MODEL.get(requested_model, "auto")
    if forced_model != "auto" and forced_model in candidates:
        candidates = [forced_model] + [c for c in candidates if c != forced_model]

    now = time.time()
    available_candidates = [
        candidate
        for candidate in candidates
        if rotation_config["model_cooldowns"].get(candidate, 0.0) <= now
    ]

    if not available_candidates:
        logger.warning(f"[{requested_model}] [cooldown] [503]")
        return JSONResponse(
            status_code=503,
            content={
                "error": {
                    "message": f"All candidate models for '{requested_model}' are on 24-hour cooldown."
                }
            },
        )

    active_index = 0
    if len(candidates) > 1:
        for i, candidate in enumerate(candidates):
            if candidate in available_candidates:
                active_index = i
                break

        if active_index > 0 and (now - rotation_config["last_fallback_switch_time"] > 300):
            primary_candidate = candidates[0]
            if primary_candidate in available_candidates:
                available_candidates.insert(0, primary_candidate)

    for candidate_model in available_candidates:
        if candidate_model not in MODEL_SETTINGS:
            if candidate_model == "qwen3.6":
                MODEL_SETTINGS[candidate_model] = {
                    "provider": "kaggle",
                    "base_url": KAGGLE_BASE_URL,
                    "keys_pool": ["test"],
                    "target_model": "qwen3.6",
                }
                logger.info(f"Dynamically registered Kaggle settings for model '{candidate_model}' with URL: {KAGGLE_BASE_URL}")
            elif path.startswith("openrouter/") or "/" in candidate_model or candidate_model.endswith(":free"):
                MODEL_SETTINGS[candidate_model] = {
                    "provider": "openrouter",
                    "base_url": "https://openrouter.ai/api/v1",
                    "keys_pool": OPENROUTER_KEYS,
                    "target_model": candidate_model,
                }
                logger.info(f"Dynamically registered OpenRouter settings for model '{candidate_model}'")
            elif path.startswith("mistral/"):
                MODEL_SETTINGS[candidate_model] = {
                    "provider": "mistral",
                    "base_url": "https://api.mistral.ai/v1",
                    "keys_pool": MISTRAL_KEYS,
                    "target_model": candidate_model,
                }
                logger.info(f"Dynamically registered Mistral settings for model '{candidate_model}'")
            elif path.startswith("llm7/"):
                MODEL_SETTINGS[candidate_model] = {
                    "provider": "llm7",
                    "base_url": "https://api.llm7.io/v1",
                    "keys_pool": LLM7_KEYS,
                    "target_model": candidate_model,
                }
                logger.info(f"Dynamically registered LLM7 settings for model '{candidate_model}'")
            else:
                MODEL_SETTINGS[candidate_model] = {
                    "provider": "gemini",
                    "base_url": "https://generativelanguage.googleapis.com",
                    "keys_pool": API_KEYS,
                    "target_model": candidate_model,
                }
                logger.info(f"Dynamically registered Gemini settings for model '{candidate_model}'")

        model_settings = MODEL_SETTINGS[candidate_model]
        provider_name = model_settings["provider"]
        target_base_url = model_settings["base_url"]
        keys_pool = model_settings["keys_pool"]
        target_model_id = model_settings["target_model"]

        if provider_name == "gemini":
            target_path = path
            if "gemini-3.6-flash" in path and candidate_model != "gemini-3.6-flash":
                target_path = path.replace("gemini-3.6-flash", target_model_id)
            elif "gemini-flash-lite-latest" in path and candidate_model != "gemini-flash-lite-latest":
                target_path = path.replace("gemini-flash-lite-latest", target_model_id)
            elif "gemini-2.0-flash-lite" in path and candidate_model != "gemini-flash-lite-latest":
                target_path = path.replace("gemini-2.0-flash-lite", target_model_id)
        else:
            if path.startswith("openrouter/"):
                target_path = path[11:]
            elif path.startswith("mistral/"):
                target_path = path[8:]
            elif path.startswith("llm7/"):
                target_path = path[5:]
            else:
                target_path = path

        target_url = f"{target_base_url}/{target_path}"

        if not keys_pool:
            logger.warning(f"No keys available for model '{candidate_model}' (provider: '{provider_name}')")
            continue

        available_keys = [k for k in keys_pool if COOLDOWNS.get(k, 0.0) < now]

        if not available_keys:
            logger.warning(f"[{provider_name}] All keys for model '{candidate_model}' are on cooldown. Rotating model.")
            continue
        else:
            available_keys = sorted(available_keys, key=lambda k: LAST_USED.get(k, 0.0))

        max_attempts = len(available_keys)
        model_success = False

        for attempt, api_key in enumerate(available_keys, start=1):
            if attempt > 1 and await request.is_disconnected():
                logger.warning(f"[{provider_name}] Client disconnected during key search for model '{candidate_model}'. Aborting.")
                break

            current_config = load_rotation_config()
            current_force_model = current_config.get("force_model", {})
            current_forced_model = current_force_model.get(requested_model, "auto")
            if current_forced_model != forced_model:
                logger.info(f"[{provider_name}] Manual model switch detected during 429 retry sequence: '{forced_model}' -> '{current_forced_model}'. Restarting routing.")
                return "RESTART"

            key_index = keys_pool.index(api_key) + 1

            headers = {
                k: v
                for k, v in request.headers.items()
                if k.lower() not in ("host", "content-length", "authorization", "x-goog-api-key", "x-api-key")
            }

            if provider_name in ("openrouter", "mistral", "llm7"):
                headers["authorization"] = f"Bearer {api_key}"
            else:
                headers["x-goog-api-key"] = api_key

            request_body = body
            if provider_name in ("openrouter", "mistral", "llm7"):
                try:
                    body_dict = json.loads(body)
                    translated_body = translate_payload_to_openai(body_dict, target_model_id)
                    request_body = json.dumps(translated_body).encode("utf-8")
                except Exception as e:
                    logger.warning(f"Failed to translate payload for OpenAI format: {e}")

            current_query_params = {k: v for k, v in query_params.items() if k.lower() != "key"}

            try:
                req = client.build_request(
                    method=request.method,
                    url=target_url,
                    headers=headers,
                    params=current_query_params,
                    content=request_body if request.method in ("POST", "PUT", "PATCH") else None,
                )
                LAST_USED[api_key] = time.time()
                response = await client.send(req, stream=True)

                if response.status_code == 200:
                    rotation_config["consecutive_model_failures"][candidate_model] = 0
                    CONSECUTIVE_429S[provider_name] = 0
                    CONSECUTIVE_RPD_429S[api_key] = 0  # Reset on success!

                    current_active_index = candidates.index(candidate_model) if candidate_model in candidates else -1
                    if current_active_index < active_index:
                        rotation_config["last_fallback_switch_time"] = time.time()
                        save_rotation_config(rotation_config)
                        logger.info(f"Successfully recovered to higher-priority model: {candidate_model}")

                    model_success = True
                    remove_key_from_error_log(candidate_model, api_key)

                    # Custom single-line completion log!
                    logger.info(f"[{candidate_model}] [key#{key_index}-{api_key[-4:]}] [200]")

                    response_headers = {
                        k: v for k, v in response.headers.items() if k.lower() not in EXCLUDED_HEADERS
                    }

                    req_messages = []
                    if SAVE_CHAT_LOGS:
                        req_messages = extract_chat_messages(body)

                    response_text_buffer = []

                    async def stream_generator():
                        try:
                            async def iter_bytes():
                                async for chunk in response.aiter_bytes():
                                    yield chunk

                            async for chunk in iter_bytes():
                                if SAVE_CHAT_LOGS:
                                    try:
                                        chunk_str = chunk.decode("utf-8", errors="ignore")
                                        text_part = extract_text_from_chunk(chunk_str, provider_name)
                                        if text_part:
                                            response_text_buffer.append(text_part)
                                    except Exception as ce:
                                        logger.debug(f"Error extracting text from chunk: {ce}")
                                yield chunk
                        finally:
                            await response.aclose()
                            if SAVE_CHAT_LOGS and (req_messages or response_text_buffer):
                                response_text = "".join(response_text_buffer)
                                asyncio.create_task(
                                    write_chat_log(
                                        model=candidate_model,
                                        provider=provider_name,
                                        messages=req_messages,
                                        response=response_text,
                                        session_id=session_id,
                                    )
                                )

                    return StreamingResponse(
                        stream_generator(),
                        status_code=response.status_code,
                        headers=response_headers,
                    )
                elif response.status_code == 429:
                    await response.aclose()
                    consecutive_429 = CONSECUTIVE_429S.get(provider_name, 0) + 1
                    CONSECUTIVE_429S[provider_name] = consecutive_429

                    now_ts = time.time()
                    prev_429_ts = LAST_429_TIME.get(api_key, 0.0)
                    LAST_429_TIME[api_key] = now_ts

                    cooldown_duration = RETRY_DELAY_SECONDS

                    if prev_429_ts > 0.0:
                        time_diff = now_ts - prev_429_ts
                        if time_diff > 300.0:
                            rpd_consec = CONSECUTIVE_RPD_429S.get(api_key, 0) + 1
                            CONSECUTIVE_RPD_429S[api_key] = rpd_consec
                            if rpd_consec >= 3:  # Increased threshold to 3!
                                if provider_name == "gemini":
                                    cooldown_duration = seconds_until_rpd_reset()
                                    logger.error(f"[{provider_name}] Key #{key_index} RPD limit. Wait {cooldown_duration / 3600:.1f}h")
                                else:
                                    cooldown_duration = 86400.0
                                    logger.error(f"[{provider_name}] Key #{key_index} daily limit. Wait 24h")
                                CONSECUTIVE_RPD_429S[api_key] = 0
                        else:
                            pass
                    else:
                        CONSECUTIVE_RPD_429S[api_key] = 1

                    mark_cooldown(api_key, duration=cooldown_duration)

                    logger.warning(
                        f"[{provider_name}] Key #{key_index} 429 ({candidate_model}). Cooldown {cooldown_duration:.1f}s. Attempt {attempt}/{max_attempts}"
                    )

                    retry_sleep = min(1.5 * consecutive_429, 15.0)
                    logger.info(f"[{provider_name}] Sleeping {retry_sleep:.2f}s...")
                    await asyncio.sleep(retry_sleep)
                    continue
                elif response.status_code == 403:
                    await response.aclose()
                    mark_cooldown(api_key, duration=86400.0)
                    error_msg = f"HTTP {response.status_code}: Forbidden"
                    log_non_429_error(candidate_model, api_key, error_msg)
                    logger.error(f"[{provider_name}] Key #{key_index} 403 ({candidate_model}). Cooldown 24h")
                    continue
                elif response.status_code in (500, 502, 503):
                    await response.aclose()
                    mark_cooldown(api_key, duration=10.0)
                    error_msg = f"HTTP {response.status_code}: Server Error"
                    log_non_429_error(candidate_model, api_key, error_msg)
                    logger.error(f"[{provider_name}] Key #{key_index} HTTP {response.status_code} ({candidate_model})")
                    continue
                else:
                    await response.aclose()
                    error_msg = f"HTTP {response.status_code}: Unexpected status"
                    log_non_429_error(candidate_model, api_key, error_msg)
                    logger.warning(f"[{provider_name}] Key #{key_index} HTTP {response.status_code} ({candidate_model})")
                    continue

            except Exception as e:
                logger.error(f"[{provider_name}] Key #{key_index} conn error ({candidate_model}): {e}")
                log_non_429_error(candidate_model, api_key, str(e))
                mark_cooldown(api_key, duration=10.0)
                continue

        if not model_success:
            rotation_config["model_cooldowns"][candidate_model] = now + 86400.0
            rotation_config["consecutive_model_failures"][candidate_model] = 0

            current_index = candidates.index(candidate_model) if candidate_model in candidates else -1
            next_index = (current_index + 1) % len(candidates)
            rotation_config["last_fallback_switch_time"] = now

            save_rotation_config(rotation_config)
            logger.warning(f"Model '{candidate_model}' failed. Cooldown 24h")

    logger.error(f"[{requested_model}] [all-keys-failed] [503]")
    return JSONResponse(
        status_code=503,
        content={
            "error": {
                "message": f"All candidate models for '{requested_model}' failed or are unavailable."
            }
        },
    )
```

- [ ] **Step 2: Commit**
```bash
git add proxy_core/server.py
git commit -m "feat: implement high-performance server proxy routing logic"
```

---

### Task 4: Create GUI Module (`gui.py`)

**Files:**
- Create: `proxy_core/gui.py`

- [ ] **Step 1: Implement CTk-based ProxyGUI, reset-cooldown thread, and robust taskkill**
This implements:
* The dark-red styled **"Reset Daily Cooldowns"** button.
* Async cooldown-reset API caller.
* ANSI colors dynamic remover within log queue poller.
* Comprehensive Windows subprocess termination via `taskkill /F /T`.

```python
import os
import sys
import json
import time
import argparse
import subprocess
import threading
import re
import customtkinter as ctk

from proxy_core.config import (
    load_rotation_config,
    save_rotation_config,
    FORCE_MODEL,
    USE_KAGGLE,
    SAVE_CHAT_LOGS,
    KAGGLE_BASE_URL,
    load_kaggle_url,
    save_kaggle_url
)
from proxy_core.state import log_queue
import logging

logger = logging.getLogger("proxy")

def run_server_subprocess(host: str, port: int, reload: bool):
    cmd = [sys.executable, "proxy3.py", "--host", host, "--port", str(port)]
    if reload:
        cmd.append("--reload")

    startupinfo = None
    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

    return subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        startupinfo=startupinfo
    )

class ProxyGUI(ctk.CTk):
    def __init__(self, host: str, port: int, reload: bool):
        super().__init__()
        self.host = host
        self.port = port
        self.reload = reload
        self.server_process = None
        self.stdout_thread = None
        self.stderr_thread = None

        config = load_rotation_config()
        global USE_KAGGLE, FORCE_MODEL, SAVE_CHAT_LOGS
        USE_KAGGLE = config.get("use_kaggle", USE_KAGGLE)
        SAVE_CHAT_LOGS = config.get("save_chat_logs", SAVE_CHAT_LOGS)
        config_force_model = config.get("force_model", {})
        for k, v in config_force_model.items():
            FORCE_MODEL[k] = v

        self.title("Resilient Key Rotation Proxy")
        self.geometry("900x600")

        if os.path.exists("app.ico"):
            try:
                self.iconbitmap("app.ico")
            except Exception as e:
                logger.warning(f"Could not load app.ico: {e}")

        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=2)
        self.grid_rowconfigure(0, weight=1)

        self.left_panel = ctk.CTkFrame(self, width=280, corner_radius=10)
        self.left_panel.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
        self.left_panel.pack_propagate(False)

        self.status_title = ctk.CTkLabel(
            self.left_panel,
            text="PROXY CONTROLLER",
            font=ctk.CTkFont(size=16, weight="bold"),
        )
        self.status_title.pack(pady=(15, 5))

        self.status_badge = ctk.CTkLabel(
            self.left_panel,
            text=f"STATUS: RUNNING (Port {self.port})",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#4CAF50",
        )
        self.status_badge.pack(pady=(0, 20))

        ctk.CTkLabel(
            self.left_panel,
            text="Thinking Domain Priority:",
            font=ctk.CTkFont(size=12, weight="bold"),
        ).pack(anchor="w", padx=20)
        thinking_models = [
            "Auto (Rotation)",
            "gemini-3.6-flash",
            "deepseek/deepseek-r1:free",
            "qwen/qwen-2.5-72b-instruct:free",
            "meta-llama/llama-3.3-70b-instruct:free",
            "deepseek/deepseek-chat:free",
        ]
        self.thinking_select = ctk.CTkOptionMenu(
            self.left_panel, values=thinking_models, command=self.on_thinking_select
        )
        self.thinking_select.pack(fill="x", padx=20, pady=(2, 15))
        thinking_val = FORCE_MODEL.get("gemini-3.6-flash", "auto")
        if thinking_val == "auto":
            self.thinking_select.set("Auto (Rotation)")
        else:
            self.thinking_select.set(thinking_val)

        ctk.CTkLabel(
            self.left_panel,
            text="Quick Domain Priority:",
            font=ctk.CTkFont(size=12, weight="bold"),
        ).pack(anchor="w", padx=20)
        quick_models = [
            "Auto (Rotation)",
            "gemini-flash-lite-latest",
            "deepseek-v4-flash-free",
            "mimo-v2.5-free",
            "nemotron-3-super-free",
            "google/gemini-2.5-flash:free",
            "google/gemma-2-9b-it:free",
            "meta-llama/llama-3.1-8b-instruct:free",
            "qwen/qwen-2.5-coder-32b-instruct:free",
        ]
        self.quick_select = ctk.CTkOptionMenu(
            self.left_panel, values=quick_models, command=self.on_quick_select
        )
        self.quick_select.pack(fill="x", padx=20, pady=(2, 15))
        quick_val = FORCE_MODEL.get("gemini-flash-lite-latest", "auto")
        if quick_val == "auto":
            self.quick_select.set("Auto (Rotation)")
        else:
            self.quick_select.set(quick_val)

        self.sep = ctk.CTkFrame(self.left_panel, height=2, fg_color="gray30")
        self.sep.pack(fill="x", padx=10, pady=10)

        self.kaggle_var = ctk.BooleanVar(value=USE_KAGGLE)
        self.kaggle_checkbox = ctk.CTkCheckBox(
            self.left_panel,
            text="Use Kaggle (qwen3.6)",
            variable=self.kaggle_var,
            command=self.on_kaggle_toggle,
            font=ctk.CTkFont(size=12, weight="bold"),
        )
        self.kaggle_checkbox.pack(anchor="w", padx=20, pady=(5, 5))

        self.chat_log_var = ctk.BooleanVar(value=SAVE_CHAT_LOGS)
        self.chat_log_checkbox = ctk.CTkCheckBox(
            self.left_panel,
            text="Save Chat Logs",
            variable=self.chat_log_var,
            command=self.on_chat_log_toggle,
            font=ctk.CTkFont(size=12, weight="bold"),
        )
        self.chat_log_checkbox.pack(anchor="w", padx=20, pady=(5, 10))

        ctk.CTkLabel(
            self.left_panel,
            text="Kaggle Tunnel URL:",
            font=ctk.CTkFont(size=11, weight="bold"),
        ).pack(anchor="w", padx=20)
        self.url_entry = ctk.CTkEntry(self.left_panel)
        self.url_entry.insert(0, KAGGLE_BASE_URL)
        self.url_entry.pack(fill="x", padx=20, pady=(2, 8))

        self.save_url_btn = ctk.CTkButton(
            self.left_panel, text="Save Kaggle URL", command=self.on_save_url
        )
        self.save_url_btn.pack(fill="x", padx=20, pady=(0, 10))

        # Reset Daily Cooldowns Button
        self.reset_cooldowns_btn = ctk.CTkButton(
            self.left_panel,
            text="Reset Daily Cooldowns",
            command=self.on_reset_cooldowns,
            fg_color="#8B0000",
            hover_color="#B22222",
        )
        self.reset_cooldowns_btn.pack(fill="x", padx=20, pady=(5, 10))

        self.open_folder_btn = ctk.CTkButton(
            self.left_panel,
            text="Open Folder",
            command=self.on_open_folder,
            fg_color="#3B3B3B",
            hover_color="#555555",
        )
        self.open_folder_btn.pack(fill="x", padx=20, pady=(10, 10))

        self.right_panel = ctk.CTkFrame(self, corner_radius=10)
        self.right_panel.grid(row=0, column=1, padx=10, pady=10, sticky="nsew")
        self.right_panel.grid_columnconfigure(0, weight=1)
        self.right_panel.grid_rowconfigure(0, weight=1)

        self.log_textbox = ctk.CTkTextbox(
            self.right_panel,
            font=ctk.CTkFont(family="Consolas", size=11),
            fg_color="#1E1E1E",
            text_color="#F8F8F2",
        )
        self.log_textbox.grid(row=0, column=0, padx=10, pady=(10, 5), sticky="nsew")

        self.clear_btn = ctk.CTkButton(
            self.right_panel, text="Clear Logs", command=self.on_clear_logs, width=120
        )
        self.clear_btn.grid(row=1, column=0, pady=10)

        self.start_server_subprocess()
        self.poll_queue()
        self.check_subprocess_health()

    def on_thinking_select(self, val):
        config = load_rotation_config()
        if val == "Auto (Rotation)":
            config["force_model"]["gemini-3.6-flash"] = "auto"
            logger.info("Thinking domain priority model reset to Auto.")
        else:
            config["force_model"]["gemini-3.6-flash"] = val
            logger.info(f"Thinking domain priority model set to: {val}")
        save_rotation_config(config)

    def on_quick_select(self, val):
        config = load_rotation_config()
        if val == "Auto (Rotation)":
            config["force_model"]["gemini-flash-lite-latest"] = "auto"
            logger.info("Quick domain priority model reset to Auto.")
        else:
            config["force_model"]["gemini-flash-lite-latest"] = val
            logger.info(f"Quick domain priority model set to: {val}")
        save_rotation_config(config)

    def on_kaggle_toggle(self):
        config = load_rotation_config()
        val = self.kaggle_var.get()
        config["use_kaggle"] = val
        save_rotation_config(config)
        logger.info(f"Use Kaggle (qwen3.6) set to: {val}")

    def on_chat_log_toggle(self):
        config = load_rotation_config()
        val = self.chat_log_var.get()
        config["save_chat_logs"] = val
        save_rotation_config(config)
        logger.info(f"Save Chat Logs set to: {val}")

    def on_save_url(self):
        url = self.url_entry.get().strip()
        if url:
            if save_kaggle_url(url):
                logger.info(f"Updated active Kaggle URL to: {url}")
                log_queue.put(f"[GUI] Saved active Kaggle URL: {url}")
            else:
                log_queue.put("[GUI] [ERROR] Failed to save Kaggle URL.")

    def on_reset_cooldowns(self):
        import httpx
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

    def on_open_folder(self):
        try:
            folder = os.path.dirname(os.path.abspath(__file__))
            if os.name == "nt":
                os.startfile(folder)
            else:
                subprocess.run(["xdg-open", folder])
            logger.info(f"Opened script directory: {folder}")
        except Exception as e:
            logger.error(f"Failed to open script folder: {e}")
            log_queue.put(f"[GUI] [ERROR] Failed to open script folder: {e}")

    def on_clear_logs(self):
        self.log_textbox.delete("1.0", "end")

    def poll_queue(self):
        ansi_escape = re.compile(r'\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
        while not log_queue.empty():
            try:
                msg = log_queue.get_nowait()
                # Dynamically strip all ANSI color codes!
                msg = ansi_escape.sub('', msg)
                self.log_textbox.insert("end", msg + "\n")
                self.log_textbox.see("end")
            except Exception:
                break
        self.after(100, self.poll_queue)

    def start_server_subprocess(self):
        self.stop_server_subprocess()
        logger.info(f"Starting resilient server subprocess on port {self.port}...")
        log_queue.put(f"[GUI] Launching proxy server subprocess on port {self.port}...")
        self.server_process = run_server_subprocess(self.host, self.port, self.reload)

        self.stdout_thread = threading.Thread(
            target=self.pipe_stream, args=(self.server_process.stdout,), daemon=True
        )
        self.stdout_thread.start()

        self.stderr_thread = threading.Thread(
            target=self.pipe_stream, args=(self.server_process.stderr,), daemon=True
        )
        self.stderr_thread.start()

    def pipe_stream(self, stream):
        for line in iter(stream.readline, ""):
            line = line.strip()
            if line:
                log_queue.put(line)
        stream.close()

    def stop_server_subprocess(self):
        if self.server_process is not None:
            try:
                if os.name == "nt":
                    # Fully kill the entire process tree on Windows to release port bindings!
                    subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", str(self.server_process.pid)],
                        stdout=subprocess.DEVDEV = subprocess.DEVNULL,
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

    def check_subprocess_health(self):
        if self.server_process is not None:
            ret_code = self.server_process.poll()
            if ret_code is not None:
                log_queue.put(f"[GUI] [WARNING] Proxy server subprocess died with code {ret_code}.")
                timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                ERROR_LOG_PATH = "error_keys_log.json"
                try:
                    with open(ERROR_LOG_PATH, "a", encoding="utf-8") as f:
                        f.write(f"[{timestamp}] [ERROR] Proxy subprocess crashed/exited with code {ret_code}. Auto-restarting...\n")
                except Exception as e:
                    logger.error(f"Failed to write to proxy_errors.log: {e}")

                log_queue.put("[GUI] [SYSTEM] Initiating automatic subprocess recovery restart...")
                self.start_server_subprocess()
        self.after(1000, self.check_subprocess_health)

    def on_close(self):
        self.stop_server_subprocess()
        self.destroy()
```

- [ ] **Step 2: Commit**
```bash
git add proxy_core/gui.py
git commit -m "feat: implement graphical customtkinter controller layout"
```

---

### Task 5: Rewrite Direct Entry Point (`proxy3.py`)

**Files:**
- Modify: `proxy3.py` (lines 1-1715)

- [ ] **Step 1: Overwrite entry-point wrapper `proxy3.py`**
Replace `proxy3.py` entirely with the lightweight arg-parser that launches `gui` or `server`.

```python
import os
import sys
import argparse

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from proxy_core.rotation import load_kaggle_url

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Resilient Gemini Proxy Server")
    parser.add_argument("--gui", action="store_true", help="Launch with GUI interface")
    parser.add_argument("--host", default="127.0.0.1", help="Host address to bind to")
    parser.add_argument("--port", type=int, default=4000, help="Port to listen on")
    parser.add_argument(
        "--reload", action="store_true", help="Enable auto-reload for development"
    )

    args = parser.parse_args()

    if args.gui:
        # Load CustomTkinter dynamically to save start-up overhead if running CLI server
        import customtkinter as ctk
        from proxy_core.gui import ProxyGUI

        ctk.set_appearance_mode("Dark")
        ctk.set_default_color_theme("blue")

        gui_app = ProxyGUI(host=args.host, port=args.port, reload=args.reload)
        
        # Override the GUI close handler
        gui_app.protocol("WM_DELETE_WINDOW", gui_app.on_close)
        
        gui_app.mainloop()
    else:
        import uvicorn
        # Run Foreground Server via Uvicorn
        uvicorn.run("proxy_core.server:app", host=args.host, port=args.port, reload=args.reload)
```

- [ ] **Step 2: Run verification on compiler & startup**
Compile check and run:
`python proxy3.py --help`
Verify that everything is perfectly structured and starts up cleanly!

- [ ] **Step 3: Commit**
```bash
git add proxy3.py
git commit -m "feat: rewire entry-point proxy3.py as modular wrapper"
```
