import os
import tempfile
import pytest
from proxy_core.config import (
    load_rotation_config,
    DEFAULT_KEYS_LOCATION,
    DEFAULT_VPN_DIR,
    DEFAULT_OPENCODE_CONFIG_PATH,
    get_keys_location,
    get_vpn_dir,
    get_opencode_config_path,
)
from proxy_core.rotation import (
    resolve_key_file_paths,
    reload_all_keys,
    API_KEYS,
    OPENROUTER_KEYS,
    MISTRAL_KEYS,
    LLM7_KEYS,
    OLLAMA_KEYS,
    OLLAMA_CLOUD_KEYS,
    OPENCODE_KEYS,
)


def test_load_rotation_config_keys_location():
    config = load_rotation_config()
    assert "keys_location" in config
    assert isinstance(config["keys_location"], str)
    assert len(config["keys_location"]) > 0


def test_resolve_key_file_paths():
    # Test 1: with directory
    with tempfile.TemporaryDirectory() as temp_dir:
        paths = resolve_key_file_paths(temp_dir)
        assert paths["google"] == os.path.join(temp_dir, "Google API Keys.md")
        assert paths["openrouter"] == os.path.join(temp_dir, "OpenRouter API Keys.md")
        assert paths["mistral"] == os.path.join(temp_dir, "Mistral API Keys.md")
        assert paths["llm7"] == os.path.join(temp_dir, "LLM7 Api Keys.md")
        assert paths["ollama"] == os.path.join(temp_dir, "Ollama Cloud API Keys.md")
        assert paths["ollama_cloud"] == os.path.join(
            temp_dir, "Ollama Cloud API Keys.md"
        )
        assert paths["opencode"] == os.path.join(temp_dir, "Opencode Zen API Keys.md")

    # Test 2: with file
    with tempfile.TemporaryDirectory() as temp_dir:
        dummy_file = os.path.join(temp_dir, "CustomKeys.md")
        with open(dummy_file, "w", encoding="utf-8") as f:
            f.write("key1\n")
        paths = resolve_key_file_paths(dummy_file)
        assert paths["google"] == dummy_file
        assert paths["openrouter"] == os.path.join(temp_dir, "OpenRouter API Keys.md")
        assert paths["mistral"] == os.path.join(temp_dir, "Mistral API Keys.md")

    # Test 3: with None (reads from config or DEFAULT_KEYS_LOCATION)
    paths_default = resolve_key_file_paths(None)
    assert "google" in paths_default
    assert "openrouter" in paths_default


def test_reload_all_keys_from_temp_dir():
    with tempfile.TemporaryDirectory() as temp_dir:
        # Create dummy key files
        key_files = {
            "Google API Keys.md": "gkey1\ngkey2\n",
            "OpenRouter API Keys.md": "- orkey1\n- orkey2\n- orkey3\n",
            "Mistral API Keys.md": "mkey1\n",
            "LLM7 Api Keys.md": "* llm7key1\n* llm7key2\n",
            "Ollama Cloud API Keys.md": "ollamakey1\n",
            "Opencode Zen API Keys.md": "opencodekey1\nopencodekey2\n",
        }
        for filename, content in key_files.items():
            with open(os.path.join(temp_dir, filename), "w", encoding="utf-8") as f:
                f.write(content)

        counts = reload_all_keys(temp_dir)

        assert counts["API_KEYS"] == 2
        assert counts["OPENROUTER_KEYS"] == 3
        assert counts["MISTRAL_KEYS"] == 1
        assert counts["LLM7_KEYS"] == 2
        assert counts["OLLAMA_KEYS"] == 1
        assert counts["OLLAMA_CLOUD_KEYS"] == 1
        assert counts["OPENCODE_KEYS"] == 2

        assert "gkey1" in API_KEYS and "gkey2" in API_KEYS
        assert "orkey1" in OPENROUTER_KEYS
        assert "mkey1" in MISTRAL_KEYS
        assert "llm7key1" in LLM7_KEYS
        assert "ollamakey1" in OLLAMA_KEYS
        assert "opencodekey1" in OPENCODE_KEYS

    # Restore default/actual keys
    reload_all_keys()


def test_get_keys_location(monkeypatch):
    monkeypatch.delenv("GEMINI_PROXY_KEYS_LOCATION", raising=False)
    # 1. Config takes precedence
    assert get_keys_location({"keys_location": "D:/Custom/Keys"}) == "D:/Custom/Keys"
    # 2. Env takes precedence over default
    monkeypatch.setenv("GEMINI_PROXY_KEYS_LOCATION", "D:/Env/Keys")
    assert get_keys_location({}) == "D:/Env/Keys"
    assert get_keys_location(None) == "D:/Env/Keys"
    # 3. Default fallback
    monkeypatch.delenv("GEMINI_PROXY_KEYS_LOCATION", raising=False)
    assert get_keys_location({}) == DEFAULT_KEYS_LOCATION
    assert get_keys_location(None) == DEFAULT_KEYS_LOCATION


def test_get_vpn_dir(monkeypatch):
    monkeypatch.delenv("VPN_SWITCHER_DIR", raising=False)
    # 1. Config takes precedence
    assert get_vpn_dir({"vpn_switcher_dir": "D:/Custom/VPN"}) == "D:/Custom/VPN"
    # 2. Env takes precedence over default
    monkeypatch.setenv("VPN_SWITCHER_DIR", "D:/Env/VPN")
    assert get_vpn_dir({}) == "D:/Env/VPN"
    assert get_vpn_dir(None) == "D:/Env/VPN"
    # 3. Default fallback
    monkeypatch.delenv("VPN_SWITCHER_DIR", raising=False)
    assert get_vpn_dir({}) == DEFAULT_VPN_DIR
    assert get_vpn_dir(None) == DEFAULT_VPN_DIR


def test_get_opencode_config_path(monkeypatch):
    monkeypatch.delenv("OPENCODE_CONFIG_PATH", raising=False)
    # 1. Config takes precedence
    assert (
        get_opencode_config_path({"opencode_config_path": "D:/Custom/opencode.jsonc"})
        == "D:/Custom/opencode.jsonc"
    )
    # 2. Env takes precedence over default
    monkeypatch.setenv("OPENCODE_CONFIG_PATH", "D:/Env/opencode.jsonc")
    assert get_opencode_config_path({}) == "D:/Env/opencode.jsonc"
    assert get_opencode_config_path(None) == "D:/Env/opencode.jsonc"
    # 3. Default fallback
    monkeypatch.delenv("OPENCODE_CONFIG_PATH", raising=False)
    assert get_opencode_config_path({}) == DEFAULT_OPENCODE_CONFIG_PATH
    assert get_opencode_config_path(None) == DEFAULT_OPENCODE_CONFIG_PATH


def test_load_rotation_config_schema_upgrade(monkeypatch):
    import json

    with tempfile.TemporaryDirectory() as temp_dir:
        fake_config_path = os.path.join(temp_dir, "fake_config_rotation.json")
        # Write minimal config missing new fields
        with open(fake_config_path, "w", encoding="utf-8") as f:
            json.dump({"enable_model_rotation": True}, f)

        monkeypatch.setattr("proxy_core.config.ROTATION_CONFIG_PATH", fake_config_path)

        loaded = load_rotation_config()
        assert "vpn_switcher_dir" in loaded
        assert loaded["vpn_switcher_dir"] == DEFAULT_VPN_DIR
        assert "opencode_config_path" in loaded
        assert loaded["opencode_config_path"] == DEFAULT_OPENCODE_CONFIG_PATH
        assert "keys_location" in loaded
        assert loaded["keys_location"] == DEFAULT_KEYS_LOCATION

        # Verify it was saved back to disk
        with open(fake_config_path, "r", encoding="utf-8") as f:
            saved = json.load(f)
        assert "vpn_switcher_dir" in saved
        assert "opencode_config_path" in saved
        assert "keys_location" in saved
