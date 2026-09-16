import os
import tempfile
import pytest
from proxy_core.config import load_rotation_config, DEFAULT_KEYS_LOCATION
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
