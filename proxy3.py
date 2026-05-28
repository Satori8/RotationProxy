import asyncio
import json
import os
import time
import random
import logging
import queue
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import httpx

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("proxy")

log_queue = queue.Queue()


class QueueLogHandler(logging.Handler):
    def emit(self, record):
        try:
            log_queue.put(self.format(record))
        except Exception:
            pass


# Add the queue handler globally to capture proxy and uvicorn logs
queue_handler = QueueLogHandler()
queue_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logger.addHandler(queue_handler)
logging.getLogger("uvicorn").addHandler(queue_handler)
logging.getLogger("uvicorn.access").addHandler(queue_handler)

# Пути к вашим Markdown-файлам с ключами
KEYS_FILE_PATH = r"D:\Personal\myvault\90 Private\Sensitive\Google API Keys.md"
OPENROUTER_KEYS_FILE = (
    r"D:\Personal\myvault\90 Private\Sensitive\OpenRouter API Keys.md"
)
MISTRAL_KEYS_FILE = r"D:\Personal\myvault\90 Private\Sensitive\Mistral API Keys.md"

PRIMARY_MODEL = "gemini-3.5-flash"
FALLBACK_MODEL = "gemini-3-flash-preview"
RETRY_DELAY_SECONDS = 90


def load_keys_from_file(filepath: str) -> list[str]:
    keys: list[str] = []
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


# Инициализация всех пулов ключей
API_KEYS = load_keys_from_file(KEYS_FILE_PATH)
OPENROUTER_KEYS = load_keys_from_file(OPENROUTER_KEYS_FILE)
MISTRAL_KEYS = load_keys_from_file(MISTRAL_KEYS_FILE)

COOLDOWNS: dict[str, float] = {}
CONSECUTIVE_429S: dict[str, int] = {}
IS_SEARCHING: dict[str, bool] = {}
LAST_USED: dict[str, float] = {}
LAST_REQUEST_TIME: dict[str, float] = {}
TARGET_BASE_URL = "https://generativelanguage.googleapis.com"

# Global state hooks for GUI and CLI overrides
FORCE_MODEL = {"gemini-3.5-flash": "auto", "gemini-flash-lite-latest": "auto"}
USE_KAGGLE = False
KAGGLE_BASE_URL = "https://fine-cable-outside-escape.trycloudflare.com/v1"

ROTATION_CONFIG_PATH = "config_rotation.json"

# Model settings for each candidate model
MODEL_SETTINGS = {
    "gemini-3.5-flash": {
        "provider": "gemini",
        "base_url": "https://generativelanguage.googleapis.com",
        "keys_pool": API_KEYS,
        "target_model": "gemini-3.5-flash",
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
    "meta-llama/llama-3.3-70b-instruct:free": {
        "provider": "openrouter",
        "base_url": "https://openrouter.ai/api/v1",
        "keys_pool": OPENROUTER_KEYS,
        "target_model": "meta-llama/llama-3.3-70b-instruct:free",
    },
    "deepseek/deepseek-chat:free": {
        "provider": "openrouter",
        "base_url": "https://openrouter.ai/api/v1",
        "keys_pool": OPENROUTER_KEYS,
        "target_model": "deepseek/deepseek-chat:free",
    },
    "google/gemma-2-9b-it:free": {
        "provider": "openrouter",
        "base_url": "https://openrouter.ai/api/v1",
        "keys_pool": OPENROUTER_KEYS,
        "target_model": "google/gemma-2-9b-it:free",
    },
    "nvidia/nemotron-4-340b-instruct:free": {
        "provider": "openrouter",
        "base_url": "https://openrouter.ai/api/v1",
        "keys_pool": OPENROUTER_KEYS,
        "target_model": "nvidia/nemotron-4-340b-instruct:free",
    },
    "google/gemini-2.5-flash:free": {
        "provider": "openrouter",
        "base_url": "https://openrouter.ai/api/v1",
        "keys_pool": OPENROUTER_KEYS,
        "target_model": "google/gemini-2.5-flash:free",
    },
    "meta-llama/llama-3.1-8b-instruct:free": {
        "provider": "openrouter",
        "base_url": "https://openrouter.ai/api/v1",
        "keys_pool": OPENROUTER_KEYS,
        "target_model": "meta-llama/llama-3.1-8b-instruct:free",
    },
    "qwen/qwen-2.5-coder-32b-instruct:free": {
        "provider": "openrouter",
        "base_url": "https://openrouter.ai/api/v1",
        "keys_pool": OPENROUTER_KEYS,
        "target_model": "qwen/qwen-2.5-coder-32b-instruct:free",
    },
}


def load_rotation_config() -> dict:
    """Load rotation configuration from disk or return default structure."""
    target_gemini_35_list = [
        "gemini-3.5-flash",
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

            # If the old gemini-2.0-flash-lite is there, remove it
            if "gemini-2.0-flash-lite" in config["rotation_lists"]:
                del config["rotation_lists"]["gemini-2.0-flash-lite"]
                needs_upgrade = True

            # Check if gemini-3.5-flash list needs update
            if (
                config["rotation_lists"].get("gemini-3.5-flash")
                != target_gemini_35_list
            ):
                config["rotation_lists"]["gemini-3.5-flash"] = target_gemini_35_list
                needs_upgrade = True

            # Check if gemini-flash-lite-latest list needs update
            if (
                config["rotation_lists"].get("gemini-flash-lite-latest")
                != target_lite_list
            ):
                config["rotation_lists"]["gemini-flash-lite-latest"] = target_lite_list
                needs_upgrade = True

            # Update any active model references
            if "active_models" in config:
                for model_list in config["active_models"].values():
                    if (
                        isinstance(model_list, list)
                        and "gemini-2.0-flash-lite" in model_list
                    ):
                        index = model_list.index("gemini-2.0-flash-lite")
                        model_list[index] = "gemini-flash-lite-latest"
                        needs_upgrade = True

            if needs_upgrade:
                save_rotation_config(config)
                logger.info("Rotation config upgraded to latest resilient schema.")

            return config
    except Exception as e:
        logger.error(f"Failed to load rotation config: {e}")

    # Default structure with new model names
    return {
        "last_fallback_switch_time": 0.0,
        "model_cooldowns": {},
        "consecutive_model_failures": {},
        "rotation_lists": {
            "gemini-3.5-flash": target_gemini_35_list,
            "gemini-flash-lite-latest": target_lite_list,
        },
    }


def save_rotation_config(config: dict) -> None:
    """Save rotation configuration to disk."""
    try:
        with open(ROTATION_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Failed to save rotation config: {e}")


def log_non_429_error(model: str, key: str, error_msg: str) -> None:
    """Log non-429 errors with full details including unmasked keys for debugging."""
    ERROR_LOG_PATH = "error_keys_log.json"

    try:
        # Create a unique ID for this error combination
        error_id = f"{model}|{key}|{hash(error_msg)}"

        # Load existing log or create new
        if os.path.exists(ERROR_LOG_PATH):
            with open(ERROR_LOG_PATH, "r", encoding="utf-8") as f:
                error_log = json.load(f)
        else:
            error_log = {}

        # Update or create entry
        if error_id in error_log:
            error_log[error_id]["count"] += 1
            error_log[error_id]["last_occurrence"] = time.time()
        else:
            error_log[error_id] = {
                "model": model,
                "key": key,  # Store unmasked key for debugging
                "error_message": error_msg,
                "count": 1,
                "first_occurrence": time.time(),
                "last_occurrence": time.time(),
            }

        # Save back to disk
        with open(ERROR_LOG_PATH, "w", encoding="utf-8") as f:
            json.dump(error_log, f, indent=2, ensure_ascii=False)

        logger.info(
            f"Logged error for {model} with key {key[:8]}... (count: {error_log[error_id]['count']})"
        )

    except Exception as e:
        logger.error(f"Failed to log error to {ERROR_LOG_PATH}: {e}")


def remove_key_from_error_log(model: str, key: str) -> None:
    """Remove all error log entries for a key that has successfully completed a request."""
    ERROR_LOG_PATH = "error_keys_log.json"

    try:
        # Check if error log exists
        if not os.path.exists(ERROR_LOG_PATH):
            return

        # Load existing log
        with open(ERROR_LOG_PATH, "r", encoding="utf-8") as f:
            error_log = json.load(f)

        # Find all entries that match this model|key combination
        prefix = f"{model}|{key}|"
        keys_to_remove = [
            error_id for error_id in error_log.keys() if error_id.startswith(prefix)
        ]

        if keys_to_remove:
            # Remove matching entries
            for error_id in keys_to_remove:
                del error_log[error_id]

            # Save updated log back to disk
            with open(ERROR_LOG_PATH, "w", encoding="utf-8") as f:
                json.dump(error_log, f, indent=2, ensure_ascii=False)

            logger.info(
                f"Removed {len(keys_to_remove)} error log entries for {model} with key {key[:8]}..."
            )

    except Exception as e:
        logger.error(
            f"Failed to remove error log entries for {model} with key {key[:8]}...: {e}"
        )


def load_kaggle_url() -> str:
    path = r"E:\Appdata\.config\opencode-profiles\default\opencode.jsonc"
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            # Match the baseURL inside the kaggle provider block
            import re

            match = re.search(
                r'"kaggle"\s*:\s*\{[^}]+?"baseURL"\s*:\s*"([^"]+)"', content, re.DOTALL
            )
            if match:
                return match.group(1)
    except Exception as e:
        logger.error(f"Failed to load Kaggle URL from jsonc: {e}")
    return "https://fine-cable-outside-escape.trycloudflare.com/v1"


def save_kaggle_url(new_url: str) -> bool:
    path = r"E:\Appdata\.config\opencode-profiles\default\opencode.jsonc"
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            import re

            # Regex to locate the baseURL of kaggle and replace it
            pattern = r'("kaggle"\s*:\s*\{[^}]+?"baseURL"\s*:\s*")[^"]+(")'
            updated, count = re.subn(
                pattern, r"\g<1>" + new_url + r"\g<2>", content, flags=re.DOTALL
            )
            if count > 0:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(updated)
                logger.info(
                    f"Successfully saved Kaggle URL {new_url} to opencode.jsonc"
                )
                return True
    except Exception as e:
        logger.error(f"Failed to save Kaggle URL: {e}")
    return False


def get_requested_model(path: str, body: bytes) -> str:
    """Identify the requested model from the path and body."""
    try:
        # First check if the model is in the path
        if "gemini-3.5-flash" in path:
            return "gemini-3.5-flash"
        elif "gemini-flash-lite-latest" in path:
            return "gemini-flash-lite-latest"
        elif "gemini-2.0-flash-lite" in path:
            # Backward compatibility: map old name to new name
            return "gemini-flash-lite-latest"
        elif "gemini-3-flash-preview" in path:
            return "gemini-3-flash-preview"

        # If not in path, try to parse from body (Gemini generateContent format)
        try:
            body_dict = json.loads(body)
            if "model" in body_dict:
                model_name = body_dict["model"]
                # Map old model name to new one for backward compatibility
                if model_name == "gemini-2.0-flash-lite":
                    return "gemini-flash-lite-latest"
                return model_name
            elif "contents" in body_dict and len(body_dict["contents"]) > 0:
                # This might be a Gemini request, check for model in the structure
                pass
        except json.JSONDecodeError:
            pass

        # Default to primary model if we can't determine
        return "gemini-3.5-flash"
    except Exception as e:
        logger.error(f"Error identifying requested model: {e}")
        return "gemini-3.5-flash"


def translate_payload_to_openai(body_dict: dict, target_model: str) -> dict:
    """Translate Gemini's generateContent JSON body to OpenAI chat/completions format."""
    try:
        # Check if this is already in OpenAI format
        if "messages" in body_dict and "model" in body_dict:
            return body_dict

        # Convert Gemini generateContent format to OpenAI format
        openai_payload = {
            "model": target_model,
            "messages": [],
            "stream": body_dict.get("stream", False),
        }

        # Convert Gemini contents to OpenAI messages
        if "contents" in body_dict:
            for content in body_dict["contents"]:
                if "parts" in content:
                    message_content = ""
                    for part in content["parts"]:
                        if isinstance(part, str):
                            message_content += part
                        elif isinstance(part, dict) and "text" in part:
                            message_content += part["text"]

                    role = content.get("role", "user")
                    if role == "user":
                        openai_payload["messages"].append(
                            {"role": "user", "content": message_content}
                        )
                    elif role == "model":
                        openai_payload["messages"].append(
                            {"role": "assistant", "content": message_content}
                        )

        return openai_payload

    except Exception as e:
        logger.error(f"Error translating payload: {e}")
        # Return a basic payload if translation fails
        return {
            "model": target_model,
            "messages": [{"role": "user", "content": "Hello"}],
            "stream": False,
        }


EXCLUDED_HEADERS = {
    "content-length",
    "transfer-encoding",
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "upgrade",
    "content-encoding",
}


def mark_cooldown(key: str, duration: float = 60.0) -> None:
    COOLDOWNS[key] = time.time() + duration


@asynccontextmanager
async def lifespan(app: FastAPI):
    limits = httpx.Limits(max_keepalive_connections=80, max_connections=150)
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


@app.api_route(
    "/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"]
)
async def transparent_proxy(request: Request, path: str):
    client: httpx.AsyncClient = request.app.state.client
    body = await request.body()
    query_params = dict(request.query_params)

    # Динамическая маршрутизация провайдеров по первому сегменту пути
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

    else:
        target_base = TARGET_BASE_URL
        current_path = path
        keys_pool = API_KEYS
        provider_name = "gemini"

    # Implement rate limiting: 1 request per second per provider
    current_time = time.time()
    last_request_time = LAST_REQUEST_TIME.get(provider_name, 0.0)
    time_since_last_request = current_time - last_request_time

    if time_since_last_request < 1.0:
        return JSONResponse(
            status_code=429,
            content={
                "error": {
                    "message": f"Rate limit exceeded for provider '{provider_name}'. Please wait {1.0 - time_since_last_request:.2f} seconds before trying again."
                }
            },
        )

    # Update the last request time for this provider
    LAST_REQUEST_TIME[provider_name] = current_time

    # Implement the new model rotation and recovery logic
    requested_model = get_requested_model(path, body)
    rotation_config = load_rotation_config()

    # Get candidate list for the requested model
    candidates = rotation_config["rotation_lists"].get(
        requested_model, [requested_model]
    )
    if not candidates:
        candidates = [requested_model]

    # If USE_KAGGLE is enabled, append "qwen3.6" as a fallback candidate
    if USE_KAGGLE and "qwen3.6" not in candidates:
        candidates = list(candidates) + ["qwen3.6"]

    # Enforce manual priority model overrides if set (Auto is default, i.e., "auto")
    forced_model = FORCE_MODEL.get(requested_model, "auto")
    if forced_model != "auto" and forced_model in candidates:
        # Move the forced model to the top priority (front of the list)
        candidates = [forced_model] + [c for c in candidates if c != forced_model]

    # Filter out models on 24-hour cooldown
    now = time.time()
    available_candidates = [
        candidate
        for candidate in candidates
        if rotation_config["model_cooldowns"].get(candidate, 0.0) <= now
    ]

    if not available_candidates:
        return JSONResponse(
            status_code=503,
            content={
                "error": {
                    "message": f"All candidate models for '{requested_model}' are on 24-hour cooldown."
                }
            },
        )

    # Check if we're using a fallback and 5 minutes have passed - try to recover to primary
    active_index = 0
    if len(candidates) > 1:
        # Find which candidate is currently active (first one not on cooldown)
        for i, candidate in enumerate(candidates):
            if candidate in available_candidates:
                active_index = i
                break

        # If we're on a fallback (index > 0) and 5 minutes have passed, try primary first
        if active_index > 0 and (
            now - rotation_config["last_fallback_switch_time"] > 300
        ):
            primary_candidate = candidates[0]
            if primary_candidate in available_candidates:
                # Probe the primary model first
                available_candidates.insert(0, primary_candidate)

    # Try each candidate model
    for candidate_model in available_candidates:
        if candidate_model not in MODEL_SETTINGS:
            # Dynamically register model settings if provider can be determined
            if candidate_model == "qwen3.6":
                MODEL_SETTINGS[candidate_model] = {
                    "provider": "kaggle",
                    "base_url": KAGGLE_BASE_URL,
                    "keys_pool": ["test"],  # Kaggle Ollama does not require keys
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
            else:
                # Default to gemini provider
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

        # Build the target URL
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
                # Handle backward compatibility: old path with new model
                target_path = path.replace("gemini-2.0-flash-lite", target_model_id)
        else:
            # For non-Gemini providers, we need to translate the path
            if path.startswith("openrouter/"):
                target_path = path[11:]
            elif path.startswith("mistral/"):
                target_path = path[8:]

            else:
                target_path = path

        target_url = f"{target_base_url}/{target_path}"

        # Check if keys are available
        if not keys_pool:
            logger.warning(
                f"No keys available for model '{candidate_model}' (provider: '{provider_name}')"
            )
            continue

        # Filter available keys (not on cooldown)
        available_keys = [k for k in keys_pool if COOLDOWNS.get(k, 0.0) < now]

        if not available_keys:
            # Check if we should wait for the shortest cooldown
            attempt_keys = sorted(keys_pool, key=lambda k: COOLDOWNS.get(k, 0.0))
            shortest_key = attempt_keys[0]
            expiry = COOLDOWNS.get(shortest_key, 0.0)
            wait_time = expiry - now

            if 0 < wait_time <= 5.0:
                logger.info(
                    f"[{provider_name}] Waiting {wait_time:.2f}s for key release for model '{candidate_model}'..."
                )
                await asyncio.sleep(wait_time)
                available_keys = [shortest_key]
            else:
                logger.warning(
                    f"[{provider_name}] All keys for model '{candidate_model}' are on cooldown (shortest wait: {wait_time:.1f}s). Skipping."
                )
                continue
        else:
            # Sort keys by last used time (oldest first)
            available_keys = sorted(available_keys, key=lambda k: LAST_USED.get(k, 0.0))

        max_attempts = len(available_keys)
        model_success = False

        for attempt, api_key in enumerate(available_keys, start=1):
            # Check if client disconnected
            if attempt > 1 and await request.is_disconnected():
                logger.warning(
                    f"[{provider_name}] Client disconnected during key search for model '{candidate_model}'. Aborting."
                )
                break

            key_index = keys_pool.index(api_key) + 1

            # Build headers
            headers = {
                k: v
                for k, v in request.headers.items()
                if k.lower()
                not in (
                    "host",
                    "content-length",
                    "authorization",
                    "x-goog-api-key",
                    "x-api-key",
                )
            }

            if provider_name in ("openrouter", "mistral"):
                headers["authorization"] = f"Bearer {api_key}"
            else:
                headers["x-goog-api-key"] = api_key

            # For OpenAI-compatible endpoints, translate the payload
            request_body = body
            if provider_name in ("openrouter", "mistral"):
                try:
                    body_dict = json.loads(body)
                    translated_body = translate_payload_to_openai(
                        body_dict, target_model_id
                    )
                    request_body = json.dumps(translated_body).encode("utf-8")
                except (json.JSONDecodeError, Exception) as e:
                    logger.warning(
                        f"Failed to translate payload for OpenAI format: {e}"
                    )
                    # Continue with original body

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

                # Check response status
                if response.status_code == 200:
                    # Success! Reset failure counter for this model
                    rotation_config["consecutive_model_failures"][candidate_model] = 0

                    # Reset consecutive 429 counter for this key
                    CONSECUTIVE_429S[api_key] = 0

                    # If we successfully used a higher-priority model after fallback, update state
                    current_active_index = (
                        candidates.index(candidate_model)
                        if candidate_model in candidates
                        else -1
                    )
                    if current_active_index < active_index:
                        # We recovered to a higher-priority model
                        rotation_config["last_fallback_switch_time"] = time.time()
                        save_rotation_config(rotation_config)
                        logger.info(
                            f"Successfully recovered to higher-priority model: {candidate_model}"
                        )

                    model_success = True

                    # Remove error log entries for this key since it successfully completed a request
                    remove_key_from_error_log(candidate_model, api_key)

                    response_headers = {
                        k: v
                        for k, v in response.headers.items()
                        if k.lower() not in EXCLUDED_HEADERS
                    }

                    async def stream_generator():
                        try:
                            async for chunk in response.aiter_bytes():
                                yield chunk
                        finally:
                            await response.aclose()

                    return StreamingResponse(
                        stream_generator(),
                        status_code=response.status_code,
                        headers=response_headers,
                    )
                elif response.status_code == 429:
                    await response.aclose()

                    # Track consecutive 429s for this key to apply incremental cooldown and sleep
                    consecutive_429 = CONSECUTIVE_429S.get(api_key, 0) + 1
                    CONSECUTIVE_429S[api_key] = consecutive_429

                    # Incremental cooldown: base RETRY_DELAY_SECONDS scaled by consecutive 429 occurrences
                    cooldown_duration = RETRY_DELAY_SECONDS * (
                        2 ** (consecutive_429 - 1)
                    )
                    cooldown_duration = min(
                        cooldown_duration, 86400.0
                    )  # Cap at 24 hours
                    mark_cooldown(api_key, duration=cooldown_duration)

                    logger.warning(
                        f"[{provider_name}] Key #{key_index} hit 429 for model '{candidate_model}'. "
                        f"Consecutive 429s: {consecutive_429}. Cooldown set to {cooldown_duration}s. "
                        f"Attempt {attempt}/{max_attempts}"
                    )

                    # Sleep incrementally before retrying the next key to avoid immediate rate limit spam on the provider
                    retry_sleep = min(1.5 * consecutive_429, 10.0)
                    logger.info(
                        f"[{provider_name}] Sleeping for {retry_sleep:.2f}s before trying next key to prevent rate limit spam..."
                    )
                    await asyncio.sleep(retry_sleep)
                    continue
                elif response.status_code == 403:
                    await response.aclose()
                    mark_cooldown(api_key, duration=86400.0)
                    error_msg = f"HTTP {response.status_code}: Forbidden"
                    log_non_429_error(candidate_model, api_key, error_msg)
                    logger.error(
                        f"[{provider_name}] Key #{key_index} returned 403 for model '{candidate_model}'. Put on 24h global cooldown."
                    )
                    continue
                elif response.status_code in (500, 502, 503):
                    await response.aclose()
                    mark_cooldown(api_key, duration=10.0)
                    error_msg = f"HTTP {response.status_code}: Server Error"
                    log_non_429_error(candidate_model, api_key, error_msg)
                    logger.error(
                        f"[{provider_name}] Key #{key_index} returned {response.status_code} for model '{candidate_model}'"
                    )
                    continue
                else:
                    await response.aclose()
                    error_msg = f"HTTP {response.status_code}: Unexpected status"
                    log_non_429_error(candidate_model, api_key, error_msg)
                    logger.warning(
                        f"[{provider_name}] Key #{key_index} returned unexpected status {response.status_code} for model '{candidate_model}'"
                    )
                    continue

            except Exception as e:
                logger.error(
                    f"[{provider_name}] Key #{key_index} connection error for model '{candidate_model}': {e}"
                )
                log_non_429_error(candidate_model, api_key, str(e))
                mark_cooldown(api_key, duration=10.0)
                continue

        # If we get here, all keys for this candidate model failed
        if not model_success:
            # Increment failure counter
            current_failures = rotation_config["consecutive_model_failures"].get(
                candidate_model, 0
            )
            rotation_config["consecutive_model_failures"][candidate_model] = (
                current_failures + 1
            )

            # Check if we've reached 3 consecutive failures
            if current_failures + 1 >= 3:
                # Put model on 24-hour cooldown
                rotation_config["model_cooldowns"][candidate_model] = now + 86400.0
                rotation_config["consecutive_model_failures"][candidate_model] = 0

                # Find next available candidate
                current_index = (
                    candidates.index(candidate_model)
                    if candidate_model in candidates
                    else -1
                )
                next_index = (current_index + 1) % len(candidates)

                # Update fallback switch time
                rotation_config["last_fallback_switch_time"] = now

                save_rotation_config(rotation_config)
                logger.warning(
                    f"Model '{candidate_model}' failed 3 times. Put on 24-hour cooldown and switching to next candidate."
                )
            else:
                save_rotation_config(rotation_config)
                logger.warning(
                    f"Model '{candidate_model}' failed. Consecutive failures: {current_failures + 1}/3"
                )

    # If we get here, all candidate models failed
    return JSONResponse(
        status_code=503,
        content={
            "error": {
                "message": f"All candidate models for '{requested_model}' failed or are unavailable."
            }
        },
    )


import subprocess
import sys
import argparse
import threading
import customtkinter as ctk


def run_server_subprocess(host: str, port: int, reload: bool):
    startupinfo = None
    if sys.platform == "win32":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0  # SW_HIDE

    # Launch subprocess with sys.executable and arguments (excluding --gui to run background proxy only)
    args = [sys.executable, "proxy3.py", "--host", host, "--port", str(port)]
    if reload:
        args.append("--reload")

    return subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        startupinfo=startupinfo,
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

        self.title("Resilient Key Rotation Proxy")
        self.geometry("900x600")

        # Load custom icon if available
        if os.path.exists("app.ico"):
            try:
                self.iconbitmap("app.ico")
            except Exception as e:
                logger.warning(f"Could not load app.ico: {e}")

        # Configure Grid Layout (2 columns, 1 row)
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=2)
        self.grid_rowconfigure(0, weight=1)

        # LEFT PANEL: Controls (1/3 width)
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

        # Thinking Domain Selector (Auto + Candidates)
        ctk.CTkLabel(
            self.left_panel,
            text="Thinking Domain Priority:",
            font=ctk.CTkFont(size=12, weight="bold"),
        ).pack(anchor="w", padx=20)
        thinking_models = [
            "Auto (Rotation)",
            "gemini-3.5-flash",
            "deepseek/deepseek-r1:free",
            "qwen/qwen-2.5-72b-instruct:free",
            "meta-llama/llama-3.3-70b-instruct:free",
            "deepseek/deepseek-chat:free",
        ]
        self.thinking_select = ctk.CTkOptionMenu(
            self.left_panel, values=thinking_models, command=self.on_thinking_select
        )
        self.thinking_select.pack(fill="x", padx=20, pady=(2, 15))

        # Quick Domain Selector (Auto + Candidates)
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

        # Separator line
        self.sep = ctk.CTkFrame(self.left_panel, height=2, fg_color="gray30")
        self.sep.pack(fill="x", padx=10, pady=10)

        # Kaggle Toggle
        self.kaggle_var = ctk.BooleanVar(value=USE_KAGGLE)
        self.kaggle_checkbox = ctk.CTkCheckBox(
            self.left_panel,
            text="Use Kaggle (qwen3.6)",
            variable=self.kaggle_var,
            command=self.on_kaggle_toggle,
            font=ctk.CTkFont(size=12, weight="bold"),
        )
        self.kaggle_checkbox.pack(anchor="w", padx=20, pady=(5, 10))

        # Kaggle URL field
        ctk.CTkLabel(
            self.left_panel,
            text="Kaggle Tunnel URL:",
            font=ctk.CTkFont(size=11, weight="bold"),
        ).pack(anchor="w", padx=20)
        self.url_entry = ctk.CTkEntry(self.left_panel)
        self.url_entry.insert(0, KAGGLE_BASE_URL)
        self.url_entry.pack(fill="x", padx=20, pady=(2, 8))

        # Save URL Button
        self.save_url_btn = ctk.CTkButton(
            self.left_panel, text="Save Kaggle URL", command=self.on_save_url
        )
        self.save_url_btn.pack(fill="x", padx=20, pady=(0, 20))

        # Open Script Folder Button
        self.open_folder_btn = ctk.CTkButton(
            self.left_panel,
            text="Open Folder",
            command=self.on_open_folder,
            fg_color="#3B3B3B",
            hover_color="#555555",
        )
        self.open_folder_btn.pack(fill="x", padx=20, pady=(10, 10))

        # Right Panel (Logs)
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

        # Clear Logs Button
        self.clear_btn = ctk.CTkButton(
            self.right_panel, text="Clear Logs", command=self.on_clear_logs, width=120
        )
        self.clear_btn.grid(row=1, column=0, pady=10)

        # Spawn Subprocess
        self.start_server_subprocess()

        # Start Log and Subprocess Health Pollers
        self.poll_queue()
        self.check_subprocess_health()

        # Handle window close cleanly
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def start_server_subprocess(self):
        self.stop_server_subprocess()
        logger.info(f"Starting resilient server subprocess on port {self.port}...")
        log_queue.put(f"[GUI] Launching proxy server subprocess on port {self.port}...")

        self.server_process = run_server_subprocess(self.host, self.port, self.reload)

        # Start logging pipes
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
                # Subprocess exited!
                log_queue.put(
                    f"[GUI] [WARNING] Proxy server subprocess died with code {ret_code}."
                )

                if ret_code != 0:
                    # Log to persistent error log only
                    try:
                        with open("proxy_errors.log", "a", encoding="utf-8") as f:
                            import datetime

                            timestamp = datetime.datetime.now().strftime(
                                "%Y-%m-%d %H:%M:%S"
                            )
                            f.write(
                                f"[{timestamp}] [ERROR] Proxy subprocess crashed/exited with code {ret_code}. Auto-restarting...\n"
                            )
                    except Exception as e:
                        logger.error(f"Failed to write to proxy_errors.log: {e}")

                    log_queue.put(
                        "[GUI] [SYSTEM] Initiating automatic subprocess recovery restart..."
                    )
                    self.start_server_subprocess()
                else:
                    log_queue.put(
                        "[GUI] Proxy server subprocess terminated gracefully."
                    )

        self.after(1000, self.check_subprocess_health)

    def on_thinking_select(self, val):
        if val == "Auto (Rotation)":
            FORCE_MODEL["gemini-3.5-flash"] = "auto"
            logger.info("Thinking domain priority model reset to Auto.")
            log_queue.put("[GUI] Thinking domain priority model reset to Auto.")
        else:
            FORCE_MODEL["gemini-3.5-flash"] = val
            logger.info(f"Thinking domain priority model set to: {val}")
            log_queue.put(f"[GUI] Thinking domain priority model set to: {val}")

    def on_quick_select(self, val):
        if val == "Auto (Rotation)":
            FORCE_MODEL["gemini-flash-lite-latest"] = "auto"
            logger.info("Quick domain priority model reset to Auto.")
            log_queue.put("[GUI] Quick domain priority model reset to Auto.")
        else:
            FORCE_MODEL["gemini-flash-lite-latest"] = val
            logger.info(f"Quick domain priority model set to: {val}")
            log_queue.put(f"[GUI] Quick domain priority model set to: {val}")

    def on_kaggle_toggle(self):
        global USE_KAGGLE
        USE_KAGGLE = self.kaggle_var.get()
        logger.info(f"Use Kaggle (qwen3.6) set to: {USE_KAGGLE}")
        log_queue.put(f"[GUI] Use Kaggle (qwen3.6) set to: {USE_KAGGLE}")

    def on_save_url(self):
        global KAGGLE_BASE_URL
        url = self.url_entry.get().strip()
        if url:
            KAGGLE_BASE_URL = url
            save_kaggle_url(url)
            logger.info(f"Updated active Kaggle URL to: {url}")
            log_queue.put(f"[GUI] Updated active Kaggle URL to: {url}")

    def on_open_folder(self):
        try:
            folder = os.path.dirname(os.path.abspath(__file__))
            os.startfile(folder)
            logger.info(f"Opened script directory: {folder}")
            log_queue.put(f"[GUI] Opened script directory: {folder}")
        except Exception as e:
            logger.error(f"Failed to open script folder: {e}")
            log_queue.put(f"[GUI] [ERROR] Failed to open script folder: {e}")

    def on_clear_logs(self):
        self.log_textbox.delete("1.0", "end")

    def poll_queue(self):
        while not log_queue.empty():
            try:
                msg = log_queue.get_nowait()
                self.log_textbox.insert("end", msg + "\n")
                self.log_textbox.see("end")
            except Exception:
                break
        self.after(100, self.poll_queue)

    def on_close(self):
        self.stop_server_subprocess()
        self.destroy()


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
        # Load Kaggle URL dynamically on start from config
        KAGGLE_BASE_URL = load_kaggle_url()

        # Run CustomTkinter application and manage background subprocess
        ctk.set_appearance_mode("Dark")
        ctk.set_default_color_theme("blue")

        gui_app = ProxyGUI(host=args.host, port=args.port, reload=args.reload)
        gui_app.mainloop()
    else:
        import uvicorn

        # Run in foreground background proxy mode without log_config=None to preserve standard console formatting
        uvicorn.run("proxy3:app", host=args.host, port=args.port, reload=args.reload)
