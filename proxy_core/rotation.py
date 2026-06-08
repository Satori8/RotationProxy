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
OLLAMA_KEYS_FILE = r"D:\Personal\myvault\90 Private\Sensitive\Ollama Cloud API Keys.md"
OLLAMA_CLOUD_KEYS_FILE = (
    r"D:\Personal\myvault\90 Private\Sensitive\Ollama Cloud API Keys.md"
)
OPENCODE_KEYS_FILE = r"D:\Personal\myvault\90 Private\Sensitive\OpenCode API Keys.md"


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
OLLAMA_KEYS = load_keys_from_file(OLLAMA_KEYS_FILE)
OLLAMA_CLOUD_KEYS = load_keys_from_file(OLLAMA_CLOUD_KEYS_FILE)
OPENCODE_KEYS = load_keys_from_file(OPENCODE_KEYS_FILE)


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


def wait_for_adapter_and_add_route(vpn_index: int, timeout: float = 60.0) -> bool:
    """Polls every 0.5s until the VPN adapter's IP appears, then adds the default route."""
    import time
    import subprocess

    ip_address = f"10.8.0.1{vpn_index}"
    interface_alias = f"vpn{vpn_index}"
    start_time = time.time()

    while time.time() - start_time < timeout:
        # Check if IP is present
        check_cmd = f'$OutputEncoding = [System.Text.Encoding]::UTF8; [Console]::OutputEncoding = [System.Text.Encoding]::UTF8; Get-NetIPAddress -IPAddress "{ip_address}" -AddressFamily IPv4 -ErrorAction SilentlyContinue'
        result = subprocess.run(
            ["powershell", "-Command", check_cmd],
            capture_output=True,
            text=False,
        )
        stdout = result.stdout.decode("utf-8", errors="replace")
        if stdout and ip_address in stdout:
            # IP found! Add default route
            route_cmd = f'New-NetRoute -InterfaceAlias "{interface_alias}" -DestinationPrefix "0.0.0.0/0" -NextHop "10.8.0.1" -RouteMetric 50 -Confirm:$false -ErrorAction SilentlyContinue'
            subprocess.run(
                ["powershell", "-Command", route_cmd],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            logger.info(
                f"[VPN {vpn_index}] Adapter detected and default route configured successfully."
            )
            return True
        time.sleep(0.5)

    logger.warning(
        f"[VPN {vpn_index}] Timeout waiting for adapter IP {ip_address} to appear."
    )
    return False


def restart_vpn_service(vpn_index: int) -> None:
    """Restarts the specific WireGuard service and triggers adapter polling."""
    import subprocess

    service_name = f"WireGuardTunnel$vpn{vpn_index}"
    logger.info(f"[VPN {vpn_index}] Restarting WireGuard service...")

    # Restart service
    subprocess.run(
        [
            "powershell",
            "-Command",
            f"Restart-Service -Name 'WireGuardTunnel$vpn{vpn_index}' -ErrorAction SilentlyContinue",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Wait for adapter and add route
    wait_for_adapter_and_add_route(vpn_index)
