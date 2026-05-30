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
        "gemini-3-flash",
        "deepseek/deepseek-v4-flash:free",
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
            "gemini-3.5-flash": target_gemini_35_list,
            "gemini-flash-lite-latest": target_lite_list,
        },
        "use_kaggle": False,
        "force_model": {"gemini-3.5-flash": "auto", "gemini-flash-lite-latest": "auto"},
        "save_chat_logs": False,
    }


def save_rotation_config(config: dict) -> None:
    try:
        with open(ROTATION_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Failed to save rotation config: {e}")
