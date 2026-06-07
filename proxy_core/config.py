import os
import json
import logging

logger = logging.getLogger("proxy")

ROTATION_CONFIG_PATH = "config_rotation.json"

FORCE_MODEL = {"gemini-3.5-flash": "auto", "gemini-flash-lite-latest": "auto"}
USE_KAGGLE = False
SAVE_CHAT_LOGS = False
KAGGLE_BASE_URL = "https://fine-cable-outside-escape.trycloudflare.com/v1"


def load_kaggle_url() -> str:
    path = r"E:\Appdata\.config\opencode-profiles\default\opencode.jsonc"
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


def save_kaggle_url(new_url: str) -> bool:
    path = r"E:\Appdata\.config\opencode-profiles\default\opencode.jsonc"
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
    target_gemini_35_list = [
        "gemini-3.5-flash",
        "gemini-3-flash-preview",
        "openrouter/owl-alpha",
        "deepseek/deepseek-v4-flash:free",
        "meta-llama/llama-3.3-70b-instruct:free",
        "qwen/qwen3-coder:free",
        "moonshotai/kimi-k2.6:free",
    ]
    target_lite_list = [
        "gemini-flash-lite-latest",
        "deepseek/deepseek-v4-flash:free",
        "liquid/lfm-2.5-1.2b-thinking:free",
        "liquid/lfm-2.5-1.2b-instruct:free",
        "nvidia/nemotron-nano-9b-v2:free",
        "z-ai/glm-4.5-air:free",
        "meta-llama/llama-3.2-3b-instruct:free",
        "qwen/qwen3-coder:free",
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

            if "gemini-3.5-flash" not in config["rotation_lists"]:
                config["rotation_lists"]["gemini-3.5-flash"] = target_gemini_35_list
                needs_upgrade = True
            else:
                current_35_list = config["rotation_lists"]["gemini-3.5-flash"]
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

            if "enable_model_rotation" not in config:
                config["enable_model_rotation"] = False
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

            if "filter_context" not in config:
                config["filter_context"] = True
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
        "rotation_lists": {
            "gemini-3.5-flash": target_gemini_35_list,
            "gemini-flash-lite-latest": target_lite_list,
        },
        "enable_model_rotation": False,
        "use_kaggle": False,
        "force_model": {"gemini-3.5-flash": "auto", "gemini-flash-lite-latest": "auto"},
        "save_chat_logs": False,
        "filter_context": True,
        "vpn_switching_mode": "disabled",
        "vpn_static_channel": 0,
        "vpn_errors_threshold": 5,
        "key_cooldown_duration": 90,
        "vpn_disabled_pause_sleep": 65.0,
        "max_exponential_sleep": 65.0,
        "connect_timeout": 15.0,
        "read_timeout": 120.0,
    }


def save_rotation_config(config: dict) -> None:
    try:
        with open(ROTATION_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Failed to save rotation config: {e}")
