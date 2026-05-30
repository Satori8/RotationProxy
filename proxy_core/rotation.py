import os
import json
import time
import hashlib
import logging
from proxy_core.config import load_rotation_config, save_rotation_config

logger = logging.getLogger("proxy")

KEYS_FILE_PATH = r"D:\Personal\myvault\90 Private\Sensitive\Google API Keys.md"
OPENROUTER_KEYS_FILE = (
    r"D:\Personal\myvault\90 Private\Sensitive\OpenRouter API Keys.md"
)
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
