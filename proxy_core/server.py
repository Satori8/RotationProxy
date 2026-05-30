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
from pydantic import BaseModel
import httpx

from proxy_core import logger as core_logger
from proxy_core.config import (
    load_rotation_config,
    save_rotation_config,
    FORCE_MODEL,
    USE_KAGGLE,
    SAVE_CHAT_LOGS,
    KAGGLE_BASE_URL,
    ROTATION_CONFIG_PATH,
)
from proxy_core.state import (
    COOLDOWNS,
    CONSECUTIVE_429S,
    LAST_429_TIME,
    CONSECUTIVE_RPD_429S,
    LAST_USED,
    LAST_REQUEST_TIME,
)
from proxy_core.rotation import (
    API_KEYS,
    OPENROUTER_KEYS,
    MISTRAL_KEYS,
    LLM7_KEYS,
    seconds_until_rpd_reset,
    log_non_429_error,
    remove_key_from_error_log,
)
from proxy_core.state import log_queue as global_log_queue

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

PRIMARY_MODEL = "gemini-3.5-flash"
FALLBACK_MODEL = "gemini-3-flash-preview"
RETRY_DELAY_SECONDS = 90
PROCESS_SESSION_ID = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
TARGET_BASE_URL = "https://generativelanguage.googleapis.com"

MODEL_SETTINGS = {
    "gemini-3.5-flash": {
        "provider": "gemini",
        "base_url": "https://generativelanguage.googleapis.com",
        "keys_pool": API_KEYS,
        "target_model": "gemini-3.5-flash",
    },
    "gemini-3-flash": {
        "provider": "gemini",
        "base_url": "https://generativelanguage.googleapis.com",
        "keys_pool": API_KEYS,
        "target_model": "gemini-3-flash",
    },
    "gemini-3-flash-preview": {
        "provider": "gemini",
        "base_url": "https://generativelanguage.googleapis.com",
        "keys_pool": API_KEYS,
        "target_model": "gemini-3-flash-preview",
    },
    "openrouter/owl-alpha": {
        "provider": "openrouter",
        "base_url": "https://openrouter.ai/api/v1",
        "keys_pool": OPENROUTER_KEYS,
        "target_model": "openrouter/owl-alpha",
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
    "deepseek/deepseek-v4-flash:free": {
        "provider": "openrouter",
        "base_url": "https://openrouter.ai/api/v1",
        "keys_pool": OPENROUTER_KEYS,
        "target_model": "deepseek/deepseek-v4-flash:free",
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
    "meta-llama/llama-3.3-70b-instruct:free": {
        "provider": "openrouter",
        "base_url": "https://openrouter.ai/api/v1",
        "keys_pool": OPENROUTER_KEYS,
        "target_model": "meta-llama/llama-3.3-70b-instruct:free",
    },
    "qwen/qwen3-coder:free": {
        "provider": "openrouter",
        "base_url": "https://openrouter.ai/api/v1",
        "keys_pool": OPENROUTER_KEYS,
        "target_model": "qwen/qwen3-coder:free",
    },
    "moonshotai/kimi-k2.6:free": {
        "provider": "openrouter",
        "base_url": "https://openrouter.ai/api/v1",
        "keys_pool": OPENROUTER_KEYS,
        "target_model": "moonshotai/kimi-k2.6:free",
    },
}

THINKING_MODELS = {
    "gemini-3.5-flash",
    "gemini-3-flash",
    "openrouter/owl-alpha",
    "deepseek/deepseek-v4-flash:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "qwen/qwen3-coder:free",
    "moonshotai/kimi-k2.6:free",
    "deepseek/deepseek-r1:free",
}

QUICK_MODELS = {
    "gemini-flash-lite-latest",
    "gemini-2.0-flash-lite",
    "deepseek-v4-flash-free",
    "mimo-v2.5-free",
    "nemotron-3-super-free",
    "google/gemini-2.5-flash:free",
    "google/gemma-2-9b-it:free",
    "meta-llama/llama-3.1-8b-instruct:free",
    "qwen/qwen-2.5-coder-32b-instruct:free",
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
    if "gemini-3.5-flash" in path:
        return "gemini-3.5-flash"

    try:
        data = json.loads(body)
        if isinstance(data, dict) and "model" in data:
            return data["model"]
    except Exception:
        pass
    return "gemini-3.5-flash"


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
                        text = " ".join(
                            p.get("text", "")
                            for p in parts
                            if isinstance(p, dict) and "text" in p
                        )
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


async def write_chat_log(
    model: str, provider: str, messages: list, response: str, session_id: str
):
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
                f.write(f"\n{'=' * 80}\n")
                f.write(f"TIMESTAMP: {timestamp}\n")
                f.write(f"SESSION ID: {session_id}\n")
                f.write(f"MODEL: {model} (Provider: {provider})\n")
                f.write(f"{'-' * 80}\n")
                f.write("REQUEST MESSAGES:\n")
                for m in messages:
                    f.write(f"[{m.get('role', 'user')}]: {m.get('content', '')}\n")
                f.write(f"{'-' * 80}\n")
                f.write("RESPONSE:\n")
                f.write(response)
                f.write(f"\n{'=' * 80}\n")

        await asyncio.to_thread(do_write)
        logger.info(f"Saved chat log to {log_file}")
    except Exception as e:
        logger.error(f"Failed to write chat log: {e}")


def translate_payload_to_openai(gemini_payload: dict, target_model: str) -> dict:
    if "messages" in gemini_payload:
        # Already in OpenAI format, just update the model to target_model
        new_payload = dict(gemini_payload)
        new_payload["model"] = target_model
        return new_payload

    openai_payload = {"model": target_model, "messages": []}
    if "contents" in gemini_payload:
        for content in gemini_payload["contents"]:
            role = content.get("role", "user")
            if role == "model":
                role = "assistant"
            parts = content.get("parts", [])
            text = " ".join(
                p.get("text", "") for p in parts if isinstance(p, dict) and "text" in p
            )
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


def translate_openai_chunk_to_gemini(openai_chunk_str: str) -> str:
    """Translate an OpenAI SSE chunk to a Gemini SSE chunk."""
    if openai_chunk_str.startswith("data:"):
        data_content = openai_chunk_str[5:].strip()
        if data_content == "[DONE]":
            return "data: [DONE]"
        try:
            openai_data = json.loads(data_content)
            choices = openai_data.get("choices", [])
            if choices:
                delta = choices[0].get("delta", {})
                content = delta.get("content", "")

                openai_finish_reason = choices[0].get("finish_reason")
                gemini_finish_reason = None
                if openai_finish_reason == "stop":
                    gemini_finish_reason = "STOP"
                elif openai_finish_reason == "length":
                    gemini_finish_reason = "MAX_TOKENS"
                elif openai_finish_reason is not None:
                    gemini_finish_reason = str(openai_finish_reason).upper()

                gemini_data = {
                    "candidates": [
                        {
                            "content": {"parts": [{"text": content}], "role": "model"},
                            "index": 0,
                        }
                    ]
                }
                if gemini_finish_reason:
                    gemini_data["candidates"][0]["finishReason"] = gemini_finish_reason

                return f"data: {json.dumps(gemini_data)}"
        except Exception:
            pass
    return openai_chunk_str


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


class TestModelRequest(BaseModel):
    model: str
    provider: str


@app.post("/control/test_model")
async def test_model_endpoint(req: TestModelRequest, request: Request):
    """Securely test a model via the proxy in the background to check for 200, 429, or 404."""
    model_id = req.model
    provider_name = req.provider

    # Resolve keys pool and base URL
    if provider_name == "openrouter":
        base_url = "https://openrouter.ai/api/v1"
        keys_pool = OPENROUTER_KEYS
    elif provider_name == "mistral":
        base_url = "https://api.mistral.ai/v1"
        keys_pool = MISTRAL_KEYS
    elif provider_name == "llm7":
        base_url = "https://api.llm7.io/v1"
        keys_pool = LLM7_KEYS
    else:
        base_url = "https://generativelanguage.googleapis.com"
        keys_pool = API_KEYS

    if not keys_pool:
        return {
            "status": "error",
            "message": f"No keys configured for provider '{provider_name}'.",
        }

    # Pick the first available key
    api_key = keys_pool[0]
    headers = {"Content-Type": "application/json"}
    if provider_name in ("openrouter", "mistral", "llm7"):
        headers["authorization"] = f"Bearer {api_key}"
    else:
        headers["x-goog-api-key"] = api_key

    # Build payload
    test_body = {"model": model_id, "messages": [{"role": "user", "content": "Hi"}]}

    url = f"{base_url}/chat/completions"
    client = request.app.state.client

    start_time = time.perf_counter()
    try:
        req_out = client.build_request(
            method="POST",
            url=url,
            headers=headers,
            content=json.dumps(test_body).encode("utf-8"),
            timeout=10.0,
        )
        resp = await client.send(req_out)
        status_code = resp.status_code
        try:
            resp_text = resp.text
        except Exception:
            resp_text = "(failed to read response text)"
        await resp.aclose()

        latency_ms = int((time.perf_counter() - start_time) * 1000)
        logger.info(
            f"[Test Model] Upstream status: {status_code}, latency: {latency_ms}ms, body: {resp_text}"
        )

        if status_code == 200:
            return {
                "status": "ok",
                "message": "Model responded successfully!",
                "latency_ms": latency_ms,
            }
        elif status_code == 429:
            return {
                "status": "rate_limited",
                "message": f"Rate limit exceeded (429): {resp_text}",
                "latency_ms": latency_ms,
            }
        elif status_code == 404:
            return {
                "status": "not_found",
                "message": f"Model not found (404): {resp_text}",
                "latency_ms": latency_ms,
            }
        else:
            return {
                "status": "error",
                "message": f"Server returned status {status_code}: {resp_text}",
                "latency_ms": latency_ms,
            }
    except Exception as e:
        latency_ms = int((time.perf_counter() - start_time) * 1000)
        return {
            "status": "error",
            "message": f"Network/Connection error: {e}",
            "latency_ms": latency_ms,
        }


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

    candidates = rotation_config["rotation_lists"].get(
        requested_model, [requested_model]
    )
    if not candidates:
        candidates = [requested_model]

    if USE_KAGGLE and "qwen3.6" not in candidates:
        candidates = list(candidates) + ["qwen3.6"]

    # Identify domain and check for manual override
    forced_model = "auto"
    if requested_model in THINKING_MODELS or requested_model == "gemini-3.5-flash":
        forced_model = FORCE_MODEL.get("gemini-3.5-flash", "auto")
    elif (
        requested_model in QUICK_MODELS or requested_model == "gemini-flash-lite-latest"
    ):
        forced_model = FORCE_MODEL.get("gemini-flash-lite-latest", "auto")
    else:
        forced_model = FORCE_MODEL.get(requested_model, "auto")

    now = time.time()
    if forced_model != "auto":
        available_candidates = [forced_model]
    else:
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

        if active_index > 0 and (
            now - rotation_config["last_fallback_switch_time"] > 300
        ):
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
                logger.info(
                    f"Dynamically registered Kaggle settings for model '{candidate_model}' with URL: {KAGGLE_BASE_URL}"
                )
            elif (
                path.startswith("openrouter/")
                or "/" in candidate_model
                or candidate_model.endswith(":free")
            ):
                MODEL_SETTINGS[candidate_model] = {
                    "provider": "openrouter",
                    "base_url": "https://openrouter.ai/api/v1",
                    "keys_pool": OPENROUTER_KEYS,
                    "target_model": candidate_model,
                }
                logger.info(
                    f"Dynamically registered OpenRouter settings for model '{candidate_model}'"
                )
            elif path.startswith("mistral/"):
                MODEL_SETTINGS[candidate_model] = {
                    "provider": "mistral",
                    "base_url": "https://api.mistral.ai/v1",
                    "keys_pool": MISTRAL_KEYS,
                    "target_model": candidate_model,
                }
                logger.info(
                    f"Dynamically registered Mistral settings for model '{candidate_model}'"
                )
            elif path.startswith("llm7/"):
                MODEL_SETTINGS[candidate_model] = {
                    "provider": "llm7",
                    "base_url": "https://api.llm7.io/v1",
                    "keys_pool": LLM7_KEYS,
                    "target_model": candidate_model,
                }
                logger.info(
                    f"Dynamically registered LLM7 settings for model '{candidate_model}'"
                )
            else:
                MODEL_SETTINGS[candidate_model] = {
                    "provider": "gemini",
                    "base_url": "https://generativelanguage.googleapis.com",
                    "keys_pool": API_KEYS,
                    "target_model": candidate_model,
                }
                logger.info(
                    f"Dynamically registered Gemini settings for model '{candidate_model}'"
                )

        model_settings = MODEL_SETTINGS[candidate_model]
        provider_name = model_settings["provider"]
        target_base_url = model_settings["base_url"]
        keys_pool = model_settings["keys_pool"]
        target_model_id = model_settings["target_model"]

        is_gemini_client = "generateContent" in path or "models/" in path
        needs_gemini_response_translation = False

        if provider_name == "gemini":
            target_path = path
            if "gemini-3.5-flash" in path and candidate_model != "gemini-3.5-flash":
                target_path = path.replace("gemini-3.5-flash", target_model_id)
            elif (
                "gemini-flash-lite-latest" in path
                and candidate_model != "gemini-flash-lite-latest"
            ):
                target_path = path.replace("gemini-flash-lite-latest", target_model_id)
            elif (
                "gemini-2.0-flash-lite" in path
                and candidate_model != "gemini-flash-lite-latest"
            ):
                target_path = path.replace("gemini-2.0-flash-lite", target_model_id)
        else:
            if is_gemini_client:
                target_path = "chat/completions"
                needs_gemini_response_translation = True
            else:
                if path.startswith("openrouter/"):
                    target_path = path[11:]
                elif path.startswith("mistral/"):
                    target_path = path[8:]
                elif path.startswith("llm7/"):
                    target_path = path[5:]
                else:
                    target_path = path

                # Strip v1beta/ or v1/ prefix if present
                if target_path.startswith("v1beta/"):
                    target_path = target_path[7:]
                elif target_path.startswith("v1/"):
                    target_path = target_path[3:]

                # Strip duplicate 'v1/' prefix if the base URL ends with 'v1'
                if target_path.startswith("v1/") and (
                    target_base_url.endswith("/v1") or target_base_url.endswith("/v1/")
                ):
                    target_path = target_path[3:]

        target_url = f"{target_base_url}/{target_path}"

        if not keys_pool:
            logger.warning(
                f"No keys available for model '{candidate_model}' (provider: '{provider_name}')"
            )
            continue

        available_keys = [k for k in keys_pool if COOLDOWNS.get(k, 0.0) < now]

        if not available_keys:
            logger.warning(
                f"[{provider_name}] All keys for model '{candidate_model}' are on cooldown. Rotating model."
            )
            continue
        else:
            available_keys = sorted(available_keys, key=lambda k: LAST_USED.get(k, 0.0))

        max_attempts = len(available_keys)
        model_success = False
        consecutive_503s = 0

        for attempt, api_key in enumerate(available_keys, start=1):
            if attempt > 1 and await request.is_disconnected():
                logger.warning(
                    f"[{provider_name}] Client disconnected during key search for model '{candidate_model}'. Aborting."
                )
                break

            current_config = load_rotation_config()
            current_force_model = current_config.get("force_model", {})
            if (
                requested_model in THINKING_MODELS
                or requested_model == "gemini-3.5-flash"
            ):
                current_forced_model = current_force_model.get(
                    "gemini-3.5-flash", "auto"
                )
            elif (
                requested_model in QUICK_MODELS
                or requested_model == "gemini-flash-lite-latest"
            ):
                current_forced_model = current_force_model.get(
                    "gemini-flash-lite-latest", "auto"
                )
            else:
                current_forced_model = current_force_model.get(requested_model, "auto")

            if current_forced_model != forced_model:
                logger.info(
                    f"[{provider_name}] Manual model switch detected during 429 retry sequence: '{forced_model}' -> '{current_forced_model}'. Restarting routing."
                )
                return "RESTART"

            key_index = keys_pool.index(api_key) + 1

            headers = {
                k: v
                for k, v in request.headers.items()
                if k.lower()
                not in (
                    "host",
                    "content-length",
                    "content-encoding",
                    "accept-encoding",
                    "authorization",
                    "x-goog-api-key",
                    "x-api-key",
                )
            }

            if provider_name in ("openrouter", "mistral", "llm7"):
                headers["authorization"] = f"Bearer {api_key}"
            else:
                headers["x-goog-api-key"] = api_key

            request_body = body
            if provider_name in ("openrouter", "mistral", "llm7"):
                try:
                    body_dict = json.loads(body)
                    translated_body = translate_payload_to_openai(
                        body_dict, target_model_id
                    )
                    request_body = json.dumps(translated_body).encode("utf-8")
                except Exception as e:
                    logger.warning(
                        f"Failed to translate payload for OpenAI format: {e}"
                    )

            current_query_params = {
                k: v for k, v in query_params.items() if k.lower() != "key"
            }

            try:
                req = client.build_request(
                    method=request.method,
                    url=target_url,
                    headers=headers,
                    params=current_query_params,
                    content=request_body
                    if request.method in ("POST", "PUT", "PATCH")
                    else None,
                )
                LAST_USED[api_key] = time.time()
                response = await client.send(req, stream=True)

                if response.status_code == 200:
                    rotation_config["consecutive_model_failures"][candidate_model] = 0
                    CONSECUTIVE_429S[provider_name] = 0
                    CONSECUTIVE_RPD_429S[api_key] = 0  # Reset on success!

                    current_active_index = (
                        candidates.index(candidate_model)
                        if candidate_model in candidates
                        else -1
                    )
                    if current_active_index < active_index:
                        rotation_config["last_fallback_switch_time"] = time.time()
                        save_rotation_config(rotation_config)
                        logger.info(
                            f"Successfully recovered to higher-priority model: {candidate_model}"
                        )

                    model_success = True
                    remove_key_from_error_log(candidate_model, api_key)

                    # Custom single-line completion log!
                    logger.info(
                        f"[{candidate_model}] [key#{key_index}-{api_key[-4:]}] [200]"
                    )

                    response_headers = {
                        k: v
                        for k, v in response.headers.items()
                        if k.lower() not in EXCLUDED_HEADERS
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
                                chunk_str = ""
                                if SAVE_CHAT_LOGS or needs_gemini_response_translation:
                                    try:
                                        chunk_str = chunk.decode(
                                            "utf-8", errors="ignore"
                                        )
                                    except Exception:
                                        pass

                                if SAVE_CHAT_LOGS and chunk_str:
                                    try:
                                        text_part = extract_text_from_chunk(
                                            chunk_str, provider_name
                                        )
                                        if text_part:
                                            response_text_buffer.append(text_part)
                                    except Exception as ce:
                                        logger.debug(
                                            f"Error extracting text from chunk: {ce}"
                                        )

                                if needs_gemini_response_translation and chunk_str:
                                    try:
                                        translated_lines = []
                                        for line in chunk_str.split("\n"):
                                            line_stripped = line.strip()
                                            if line_stripped:
                                                translated_line = (
                                                    translate_openai_chunk_to_gemini(
                                                        line_stripped
                                                    )
                                                )
                                                translated_lines.append(translated_line)
                                            else:
                                                translated_lines.append(line)
                                        translated_chunk = "\n".join(translated_lines)
                                        yield translated_chunk.encode("utf-8")
                                    except Exception as te:
                                        logger.debug(
                                            f"Failed to translate response chunk: {te}"
                                        )
                                        yield chunk
                                else:
                                    yield chunk
                        finally:
                            await response.aclose()
                            if SAVE_CHAT_LOGS and (
                                req_messages or response_text_buffer
                            ):
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
                                    logger.error(
                                        f"[{provider_name}] Key #{key_index} RPD limit. Wait {cooldown_duration / 3600:.1f}h"
                                    )
                                else:
                                    cooldown_duration = 86400.0
                                    logger.error(
                                        f"[{provider_name}] Key #{key_index} daily limit. Wait 24h"
                                    )
                                CONSECUTIVE_RPD_429S[api_key] = 0
                        else:
                            pass
                    else:
                        CONSECUTIVE_RPD_429S[api_key] = 1

                    mark_cooldown(api_key, duration=cooldown_duration)

                    logger.warning(
                        f"[{provider_name}] Key #{key_index} 429 ({candidate_model}) on {request.method} {target_url}. Cooldown {cooldown_duration:.1f}s. Attempt {attempt}/{max_attempts}"
                    )

                    # Exponential retry sleep: 1, 2, 4, 8, 16, then 65s
                    if consecutive_429 == 1:
                        retry_sleep = 1.0
                    elif consecutive_429 == 2:
                        retry_sleep = 2.0
                    elif consecutive_429 == 3:
                        retry_sleep = 4.0
                    elif consecutive_429 == 4:
                        retry_sleep = 8.0
                    elif consecutive_429 == 5:
                        retry_sleep = 16.0
                    else:
                        retry_sleep = 65.0

                    logger.info(f"[{provider_name}] Sleeping {retry_sleep:.2f}s...")
                    await asyncio.sleep(retry_sleep)
                    continue
                elif response.status_code == 403:
                    await response.aclose()
                    mark_cooldown(api_key, duration=86400.0)
                    error_msg = f"HTTP {response.status_code}: Forbidden"
                    log_non_429_error(candidate_model, api_key, error_msg)
                    logger.error(
                        f"[{provider_name}] Key #{key_index} 403 ({candidate_model}) on {request.method} {target_url}. Cooldown 24h"
                    )
                    continue
                elif response.status_code == 503:
                    await response.aclose()
                    mark_cooldown(api_key, duration=10.0)
                    error_msg = "HTTP 503: Service Unavailable"
                    log_non_429_error(candidate_model, api_key, error_msg)

                    consecutive_503s += 1
                    logger.error(
                        f"[{provider_name}] Key #{key_index} HTTP 503 ({candidate_model}) on {request.method} {target_url}. Consecutive 503s: {consecutive_503s}/10"
                    )

                    if consecutive_503s >= 10:
                        logger.error(
                            f"[{provider_name}] Hit 10 consecutive 503s for model '{candidate_model}'. Forcing provider switch!"
                        )
                        break  # Break out of the key loop to switch candidate model (change provider)

                    if consecutive_503s >= 3:
                        logger.info(
                            f"[{provider_name}] 3+ consecutive 503s. Sleeping 60s before trying next key..."
                        )
                        await asyncio.sleep(60.0)
                    continue
                elif response.status_code in (500, 502):
                    await response.aclose()
                    mark_cooldown(api_key, duration=10.0)
                    error_msg = f"HTTP {response.status_code}: Server Error"
                    log_non_429_error(candidate_model, api_key, error_msg)
                    logger.error(
                        f"[{provider_name}] Key #{key_index} HTTP {response.status_code} ({candidate_model}) on {request.method} {target_url}"
                    )
                    continue
                else:
                    await response.aclose()
                    error_msg = f"HTTP {response.status_code}: Unexpected status"
                    log_non_429_error(candidate_model, api_key, error_msg)
                    logger.warning(
                        f"[{provider_name}] Key #{key_index} HTTP {response.status_code} ({candidate_model}) on {request.method} {target_url}"
                    )
                    continue

            except Exception as e:
                logger.error(
                    f"[{provider_name}] Key #{key_index} conn error ({candidate_model}) on {request.method} {target_url}: {e}"
                )
                log_non_429_error(candidate_model, api_key, str(e))
                mark_cooldown(api_key, duration=10.0)
                continue

        if not model_success:
            rotation_config["model_cooldowns"][candidate_model] = now + 86400.0
            rotation_config["consecutive_model_failures"][candidate_model] = 0

            current_index = (
                candidates.index(candidate_model)
                if candidate_model in candidates
                else -1
            )
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
