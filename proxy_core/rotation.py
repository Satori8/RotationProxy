import os
import json
import time
import re
import logging
import datetime
from proxy_core.config import (
    load_rotation_config,
    save_rotation_config,
    DEFAULT_KEYS_LOCATION,
)

logger = logging.getLogger("proxy")


def resolve_key_file_paths(keys_location: str | None = None) -> dict[str, str]:
    if not keys_location:
        config_val = load_rotation_config().get("keys_location")
        keys_loc: str = str(config_val) if config_val else DEFAULT_KEYS_LOCATION
    else:
        keys_loc = keys_location
    if os.path.isfile(keys_loc):
        base_dir = os.path.dirname(keys_loc)
        google_path = keys_loc
    else:
        base_dir = keys_loc
        google_path = os.path.join(base_dir, "Google API Keys.md")
    return {
        "google": google_path,
        "openrouter": os.path.join(base_dir, "OpenRouter API Keys.md"),
        "mistral": os.path.join(base_dir, "Mistral API Keys.md"),
        "llm7": os.path.join(base_dir, "LLM7 Api Keys.md"),
        "ollama": os.path.join(base_dir, "Ollama Cloud API Keys.md"),
        "ollama_cloud": os.path.join(base_dir, "Ollama Cloud API Keys.md"),
        "opencode": os.path.join(base_dir, "Opencode Zen API Keys.md"),
    }


_initial_paths = resolve_key_file_paths()
KEYS_FILE_PATH = _initial_paths["google"]
OPENROUTER_KEYS_FILE = _initial_paths["openrouter"]
MISTRAL_KEYS_FILE = _initial_paths["mistral"]
LLM7_KEYS_FILE = _initial_paths["llm7"]
OLLAMA_KEYS_FILE = _initial_paths["ollama"]
OLLAMA_CLOUD_KEYS_FILE = _initial_paths["ollama_cloud"]
OPENCODE_KEYS_FILE = _initial_paths["opencode"]


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


def reload_all_keys(keys_location: str | None = None) -> dict[str, int]:
    global \
        KEYS_FILE_PATH, \
        OPENROUTER_KEYS_FILE, \
        MISTRAL_KEYS_FILE, \
        LLM7_KEYS_FILE, \
        OLLAMA_KEYS_FILE, \
        OLLAMA_CLOUD_KEYS_FILE, \
        OPENCODE_KEYS_FILE
    paths = resolve_key_file_paths(keys_location)
    KEYS_FILE_PATH = paths["google"]
    OPENROUTER_KEYS_FILE = paths["openrouter"]
    MISTRAL_KEYS_FILE = paths["mistral"]
    LLM7_KEYS_FILE = paths["llm7"]
    OLLAMA_KEYS_FILE = paths["ollama"]
    OLLAMA_CLOUD_KEYS_FILE = paths["ollama_cloud"]
    OPENCODE_KEYS_FILE = paths["opencode"]

    new_api = load_keys_from_file(KEYS_FILE_PATH)
    API_KEYS.clear()
    API_KEYS.extend(new_api)
    new_openrouter = load_keys_from_file(OPENROUTER_KEYS_FILE)
    OPENROUTER_KEYS.clear()
    OPENROUTER_KEYS.extend(new_openrouter)
    new_mistral = load_keys_from_file(MISTRAL_KEYS_FILE)
    MISTRAL_KEYS.clear()
    MISTRAL_KEYS.extend(new_mistral)
    new_llm7 = load_keys_from_file(LLM7_KEYS_FILE)
    LLM7_KEYS.clear()
    LLM7_KEYS.extend(new_llm7)
    new_ollama = load_keys_from_file(OLLAMA_KEYS_FILE)
    OLLAMA_KEYS.clear()
    OLLAMA_KEYS.extend(new_ollama)
    new_ollama_cloud = load_keys_from_file(OLLAMA_CLOUD_KEYS_FILE)
    OLLAMA_CLOUD_KEYS.clear()
    OLLAMA_CLOUD_KEYS.extend(new_ollama_cloud)
    new_opencode = load_keys_from_file(OPENCODE_KEYS_FILE)
    OPENCODE_KEYS.clear()
    OPENCODE_KEYS.extend(new_opencode)
    return {
        "API_KEYS": len(API_KEYS),
        "OPENROUTER_KEYS": len(OPENROUTER_KEYS),
        "MISTRAL_KEYS": len(MISTRAL_KEYS),
        "LLM7_KEYS": len(LLM7_KEYS),
        "OLLAMA_KEYS": len(OLLAMA_KEYS),
        "OLLAMA_CLOUD_KEYS": len(OLLAMA_CLOUD_KEYS),
        "OPENCODE_KEYS": len(OPENCODE_KEYS),
    }


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
        # Only log 403 and 401 errors
        match = re.search(r"HTTP (\d{3})", error_msg)
        if not match or match.group(1) not in ("403", "401"):
            return

        error_code = match.group(1)
        error_id = f"{key}|{error_code}"

        if os.path.exists(ERROR_LOG_PATH) and os.path.getsize(ERROR_LOG_PATH) > 0:
            with open(ERROR_LOG_PATH, "r", encoding="utf-8") as f:
                try:
                    error_log = json.load(f)
                except json.JSONDecodeError:
                    error_log = {}
        else:
            error_log = {}

        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if error_id in error_log:
            error_log[error_id]["count"] += 1
            error_log[error_id]["last_occurrence"] = now_str
            error_log[error_id]["error_message"] = error_msg
        else:
            error_log[error_id] = {
                "model": model,
                "key": key,
                "error_message": error_msg,
                "count": 1,
                "first_occurrence": now_str,
                "last_occurrence": now_str,
            }

        with open(ERROR_LOG_PATH, "w", encoding="utf-8") as f:
            json.dump(error_log, f, indent=2, ensure_ascii=False)

        logger.info(
            f"Logged error for {model} with key {key[:8]}...{key[-4:]} (count: {error_log[error_id]['count']})"
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

        keys_to_remove = []
        for error_id in error_log.keys():
            parts = error_id.split("|")
            # Old format: [model, key, code]
            # New format: [key, code]
            if len(parts) == 3 and parts[1] == key:
                keys_to_remove.append(error_id)
            elif len(parts) == 2 and parts[0] == key:
                keys_to_remove.append(error_id)
            elif error_id == key:
                keys_to_remove.append(error_id)

        if keys_to_remove:
            for error_id in keys_to_remove:
                del error_log[error_id]

            with open(ERROR_LOG_PATH, "w", encoding="utf-8") as f:
                json.dump(error_log, f, indent=2, ensure_ascii=False)

            logger.info(
                f"Removed {len(keys_to_remove)} error log entries for {model} with key {key[:8]}...{key[-4:]}"
            )
    except Exception as e:
        logger.error(
            f"Failed to remove error log entries for {model} with key {key[:8]}...{key[-4:]}: {e}"
        )


def get_interface_index(interface_alias: str) -> str:
    """Resolve interface index for a given alias safely using PowerShell (read-only)."""
    import subprocess

    try:
        cmd = f'Get-NetIPInterface -InterfaceAlias "{interface_alias}" -AddressFamily IPv4 | Select-Object -ExpandProperty InterfaceIndex'
        result = subprocess.run(
            ["powershell", "-Command", cmd],
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()
    except Exception:
        return ""


def ensure_vps_loop_protection(vps_ip: str = "158.178.159.108") -> bool:
    """Adds a /32 bypass route to the VPS IP via the physical gateway (Ethernet/Wi-Fi)
    to prevent routing loops when tunnels add default routes."""
    import subprocess

    try:
        ps_cmd = (
            '$r = Get-NetRoute -DestinationPrefix "0.0.0.0/0" | '
            'Where-Object { $_.NextHop -ne "0.0.0.0" -and $_.NextHop -ne "10.8.0.1" -and '
            '$_.InterfaceAlias -notlike "*WireGuard*" -and $_.InterfaceAlias -notlike "vpn*" } | '
            "Select-Object -First 1; "
            'if ($r) { "$($r.NextHop)|$($r.InterfaceIndex)" }'
        )
        res = subprocess.run(
            ["powershell", "-Command", ps_cmd], capture_output=True, text=True
        )
        out = res.stdout.strip()
        if out and "|" in out:
            gw, p_if = out.split("|", 1)
            route_cmd = [
                "route",
                "ADD",
                vps_ip,
                "MASK",
                "255.255.255.255",
                gw.strip(),
                "METRIC",
                "1",
                "IF",
                p_if.strip(),
            ]
            subprocess.run(
                route_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            logger.info(
                f"[Route] Added VPS bypass route: {vps_ip}/32 -> {gw.strip()} (IF {p_if.strip()})"
            )
            return True
    except Exception as e:
        logger.debug(f"[Route] Failed to add VPS bypass route: {e}")
    return False


def wait_for_adapter_and_add_route(vpn_index: int, timeout: float = 60.0) -> bool:
    """Polls every 0.5s until the VPN adapter's IP appears, then adds the default route."""
    import time
    import subprocess

    ip_address = f"10.8.0.1{vpn_index}"
    interface_alias = f"vpn{vpn_index}"
    start_time = time.time()

    # Check if system VPN is active from config to skip route addition if needed
    try:
        cfg = load_rotation_config()
        system_vpn_active = cfg.get("system_vpn_active", False)
    except Exception:
        system_vpn_active = False

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
            # IP found! Add default route only if system VPN is not active
            if not system_vpn_active:
                if_index = get_interface_index(interface_alias)
                if if_index:
                    ensure_vps_loop_protection()
                    route_cmd = [
                        "route",
                        "ADD",
                        "0.0.0.0",
                        "MASK",
                        "0.0.0.0",
                        "10.8.0.1",
                        "METRIC",
                        "50",
                        "IF",
                        if_index,
                    ]
                    subprocess.run(
                        route_cmd,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    logger.info(
                        f"[VPN {vpn_index}] Adapter detected and default route configured successfully via route.exe."
                    )
                else:
                    logger.warning(
                        f"[VPN {vpn_index}] Adapter detected but failed to resolve interface index."
                    )
            else:
                logger.info(
                    f"[VPN {vpn_index}] Adapter detected. Skipping default route addition because System VPN is active."
                )
            return True
        time.sleep(0.5)

    logger.warning(
        f"[VPN {vpn_index}] Timeout waiting for adapter IP {ip_address} to appear."
    )
    return False


def restart_vpn_service(vpn_index: int) -> bool:
    """Restarts the specific WireGuard service and triggers adapter polling.

    Returns:
        True if the adapter was detected and route added successfully, False otherwise.
    """
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
    return wait_for_adapter_and_add_route(vpn_index)
