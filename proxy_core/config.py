import os
import json
import logging

logger = logging.getLogger("proxy")

ROTATION_CONFIG_PATH = "config_rotation.json"


def get_default_keys_location() -> str:
    env_val = os.environ.get("GEMINI_PROXY_KEYS_LOCATION")
    if env_val:
        return env_val
    legacy = r"D:\Personal\myvault\90 Private\Sensitive"
    if os.path.exists(legacy):
        return legacy
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(project_root, "keys")


DEFAULT_KEYS_LOCATION = get_default_keys_location()


def get_keys_location(config: dict | None = None) -> str:
    if config and config.get("keys_location"):
        return config["keys_location"]
    env_val = os.environ.get("GEMINI_PROXY_KEYS_LOCATION")
    if env_val:
        return env_val
    return DEFAULT_KEYS_LOCATION


def get_default_vpn_dir() -> str:
    env_val = os.environ.get("VPN_SWITCHER_DIR")
    if env_val:
        return env_val
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    local_vpn = os.path.join(project_root, "vpn")
    if os.path.exists(local_vpn):
        return local_vpn
    rel_path = os.path.abspath(
        os.path.join(project_root, "..", "server-services", "vpn_switcher")
    )
    if os.path.exists(rel_path):
        return rel_path
    legacy = r"D:\Work\Active\server-services\vpn_switcher"
    if os.path.exists(legacy):
        return legacy
    return local_vpn


DEFAULT_VPN_DIR = get_default_vpn_dir()


def get_vpn_dir(config: dict | None = None) -> str:
    if config and config.get("vpn_switcher_dir"):
        return config["vpn_switcher_dir"]
    return get_default_vpn_dir()


def get_default_opencode_config_path() -> str:
    env_val = os.environ.get("OPENCODE_CONFIG_PATH")
    if env_val:
        return env_val
    candidates = [
        os.path.expanduser("~/.config/opencode-profiles/default/opencode.jsonc"),
        os.path.expanduser("~/.config/opencode/opencode.json"),
        os.path.join(
            os.environ.get("APPDATA", ""),
            ".config",
            "opencode-profiles",
            "default",
            "opencode.jsonc",
        ),
        r"E:\Appdata\.config\opencode-profiles\default\opencode.jsonc",
    ]
    for cand in candidates:
        if cand and os.path.exists(cand):
            return cand
    return os.path.expanduser("~/.config/opencode-profiles/default/opencode.jsonc")


DEFAULT_OPENCODE_CONFIG_PATH = get_default_opencode_config_path()


def get_opencode_config_path(config: dict | None = None) -> str:
    if config and config.get("opencode_config_path"):
        return config["opencode_config_path"]
    return get_default_opencode_config_path()


USE_KAGGLE = False
SAVE_CHAT_LOGS = False
KAGGLE_BASE_URL = "https://fine-cable-outside-escape.trycloudflare.com/v1"


def load_kaggle_url(config: dict | None = None) -> str:
    path = get_opencode_config_path(config)
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            import re

            match = re.search(
                r'"kaggle"\s*:\s*\{[^}]+?"baseURL"\s*:\s*"([^"]+)"', content, re.DOTALL
            )
            if match:
                return match.group(1)
    except Exception as e:
        logger.error(f"Failed to load Kaggle URL from jsonc: {e}")
    return "https://fine-cable-outside-escape.trycloudflare.com/v1"


def save_kaggle_url(new_url: str, config: dict | None = None) -> bool:
    path = get_opencode_config_path(config)
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            import re

            # Dynamically replace the baseURL inside the kaggle provider block
            pattern = r'("kaggle"\s*:\s*\{[^}]+?"baseURL"\s*:\s*")([^"]+)(")'
            if re.search(pattern, content):
                new_content = re.sub(pattern, rf"\g<1>{new_url}\g<3>", content)
                with open(path, "w", encoding="utf-8") as f:
                    f.write(new_content)
                return True
    except Exception as e:
        logger.error(f"Failed to save Kaggle URL: {e}")
    return False


def load_rotation_config() -> dict:
    try:
        if os.path.exists(ROTATION_CONFIG_PATH):
            with open(ROTATION_CONFIG_PATH, "r", encoding="utf-8") as f:
                config = json.load(f)

            needs_upgrade = False
            if "rotation_lists" not in config:
                config["rotation_lists"] = {}
                needs_upgrade = True

            if "enable_model_rotation" not in config:
                config["enable_model_rotation"] = False
                needs_upgrade = True

            if "use_kaggle" not in config:
                config["use_kaggle"] = USE_KAGGLE
                needs_upgrade = True

            if "force_model" not in config:
                config["force_model"] = {}
                needs_upgrade = True

            if "save_chat_logs" not in config:
                config["save_chat_logs"] = SAVE_CHAT_LOGS
                needs_upgrade = True

            if "filter_context" not in config:
                config["filter_context"] = True
                needs_upgrade = True

            if "auto_continue" not in config:
                config["auto_continue"] = True
                needs_upgrade = True

            if "max_auto_continues" not in config:
                config["max_auto_continues"] = 2
                needs_upgrade = True

            if "history_hardening" not in config:
                config["history_hardening"] = True
                needs_upgrade = True

            # VPN Config Upgrade
            if "vpn_switching_mode" not in config:
                config["vpn_switching_mode"] = "disabled"
                needs_upgrade = True
            if "vpn_static_channel" not in config:
                config["vpn_static_channel"] = 0
                needs_upgrade = True
            if "vpn_errors_threshold" not in config:
                config["vpn_errors_threshold"] = 5
                needs_upgrade = True
            if "key_cooldown_duration" not in config:
                config["key_cooldown_duration"] = 90
                needs_upgrade = True
            if "vpn_disabled_pause_sleep" not in config:
                config["vpn_disabled_pause_sleep"] = 65.0
                needs_upgrade = True
            if "max_exponential_sleep" not in config:
                config["max_exponential_sleep"] = 65.0
                needs_upgrade = True
            if "connect_timeout" not in config:
                config["connect_timeout"] = 15.0
                needs_upgrade = True
            if "read_timeout" not in config:
                config["read_timeout"] = 120.0
                needs_upgrade = True
            if "keys_location" not in config:
                config["keys_location"] = DEFAULT_KEYS_LOCATION
                needs_upgrade = True
            if "vpn_switcher_dir" not in config:
                config["vpn_switcher_dir"] = DEFAULT_VPN_DIR
                needs_upgrade = True
            if "opencode_config_path" not in config:
                config["opencode_config_path"] = DEFAULT_OPENCODE_CONFIG_PATH
                needs_upgrade = True

            if needs_upgrade:
                save_rotation_config(config)
                logger.info(
                    "Rotation config upgraded to latest resilient schema with VPN controls."
                )

            return config
    except Exception as e:
        logger.error(f"Failed to load rotation config: {e}")

    return {
        "last_fallback_switch_time": 0.0,
        "model_cooldowns": {},
        "consecutive_model_failures": {},
        "rotation_lists": {},
        "enable_model_rotation": False,
        "use_kaggle": False,
        "force_model": {},
        "save_chat_logs": False,
        "filter_context": True,
        "history_hardening": True,
        "auto_continue": True,
        "max_auto_continues": 2,
        "truncation_detection": True,
        "vpn_switching_mode": "disabled",
        "vpn_static_channel": 0,
        "vpn_errors_threshold": 5,
        "key_cooldown_duration": 90,
        "vpn_disabled_pause_sleep": 65.0,
        "max_exponential_sleep": 65.0,
        "connect_timeout": 15.0,
        "read_timeout": 120.0,
        "keys_location": DEFAULT_KEYS_LOCATION,
        "vpn_switcher_dir": DEFAULT_VPN_DIR,
        "opencode_config_path": DEFAULT_OPENCODE_CONFIG_PATH,
    }


def save_rotation_config(config: dict) -> None:
    try:
        with open(ROTATION_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Failed to save rotation config: {e}")
