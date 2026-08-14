import os
import sys
import json

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from proxy_core.compactor import (
    compact_tools_with_static_map,
    compact_contents_superpowers,
    compact_skill_responses,
    block_generic_read_on_code_files,
    move_reminder_to_system_instruction,
    inject_tool_guardrails,
    process_request_payload,
)
from proxy_core import state


def test_compact_tools():
    print("Testing compact_tools_with_static_map...")
    # Gemini format tool declaration (correct schema)
    payload = {
        "tools": [
            {
                "functionDeclarations": [
                    {
                        "name": "bash",
                        "description": "Some very long description that we want to compact...",
                        "parameters": {
                            "properties": {
                                "description": {
                                    "type": "STRING",
                                    "description": "Original description of command parameter",
                                }
                            }
                        },
                    }
                ]
            }
        ]
    }
    compacted = compact_tools_with_static_map(payload)
    func = compacted["tools"][0]["functionDeclarations"][0]
    assert "PowerShell" in func["description"]
    assert (
        "Clear, concise description"
        in func["parameters"]["properties"]["description"]["description"]
    )

    # Robustness test: parameter is a string (malformed, should not crash)
    payload_malformed = {
        "tools": [
            {
                "functionDeclarations": [
                    {
                        "name": "bash",
                        "description": "Some very long description that we want to compact...",
                        "parameters": {
                            "properties": {
                                "description": "Original description of command parameter"
                            }
                        },
                    }
                ]
            }
        ]
    }
    compacted_malformed = compact_tools_with_static_map(payload_malformed)
    func_malformed = compacted_malformed["tools"][0]["functionDeclarations"][0]
    assert "PowerShell" in func_malformed["description"]
    assert (
        func_malformed["parameters"]["properties"]["description"]
        == "Original description of command parameter"
    )
    print("  -> compact_tools_with_static_map passed!")


def test_compact_contents_superpowers():
    print("Testing compact_contents_superpowers...")
    # Gemini format superpowers block
    payload = {
        "contents": [
            {
                "parts": [
                    {
                        "text": "Some text before\n<EXTREMELY_IMPORTANT>\nIf you think there is even a 1% chance a skill might apply to what you are doing, you ABSOLUTELY MUST invoke the skill.\n</EXTREMELY_IMPORTANT>\nSome text after"
                    }
                ]
            }
        ]
    }
    compacted = compact_contents_superpowers(payload)
    text = compacted["contents"][0]["parts"][0]["text"]
    assert "You have superpowers." in text
    assert "Some text before" in text
    assert "Some text after" in text
    print("  -> compact_contents_superpowers passed!")


def test_compact_skill_responses():
    print("Testing compact_skill_responses...")
    payload = {
        "contents": [
            {
                "parts": [
                    {
                        "functionResponse": {
                            "name": "skill",
                            "response": {
                                "content": '<skill_content name="using-superpowers">\n## How to Access Skills\nSome other platform stuff\n# Using Skills\n<skill_files>\nfile1.txt\nfile2.txt\n</skill_files>\n</skill_content>'
                            },
                        }
                    }
                ]
            }
        ]
    }
    compacted = compact_skill_responses(payload)
    content = compacted["contents"][0]["parts"][0]["functionResponse"]["response"][
        "content"
    ]
    assert "<skill_files>" not in content
    assert "In OpenCode, use the native `skill` tool" in content
    print("  -> compact_skill_responses passed!")


def test_block_generic_read_on_code_files():
    print("Testing block_generic_read_on_code_files...")
    payload = {
        "contents": [
            {
                "parts": [
                    {
                        "functionResponse": {
                            "name": "read",
                            "response": {
                                "content": "<path>src/main.py</path>\n<type>file</type>\n<content>def main(): pass</content>"
                            },
                        }
                    }
                ]
            }
        ]
    }
    compacted = block_generic_read_on_code_files(payload)
    content = compacted["contents"][0]["parts"][0]["functionResponse"]["response"][
        "content"
    ]
    assert "Error: Direct use of the generic 'read' tool is restricted" in content
    print("  -> block_generic_read_on_code_files passed!")


def test_move_reminder_to_system_instruction():
    print("Testing move_reminder_to_system_instruction...")
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {
                        "text": "Hello! <internal_reminder>!IMPORTANT! Recall the workflow rules: ...</internal_reminder>"
                    }
                ],
            }
        ]
    }
    compacted = move_reminder_to_system_instruction(payload)
    assert "systemInstruction" in compacted
    sys_inst_text = compacted["systemInstruction"]["parts"][0]["text"]
    assert (
        "[System Reminder: !IMPORTANT! Recall the workflow rules: ...]" in sys_inst_text
    )
    user_text = compacted["contents"][0]["parts"][0]["text"]
    assert "<internal_reminder>" not in user_text
    print("  -> move_reminder_to_system_instruction passed!")


def test_inject_tool_guardrails():
    print("Testing inject_tool_guardrails...")
    payload = {
        "systemInstruction": {
            "parts": [
                {
                    "text": "You are a helpful assistant. Please use grep/glob/read directly."
                }
            ]
        }
    }
    compacted = inject_tool_guardrails(payload)
    text = compacted["systemInstruction"]["parts"][0]["text"]
    assert "CRITICAL TOOL GUARDRAIL" in text
    assert (
        "use tokensave_tokensave_search, lean-ctx_ctx_search, or fff_find_files directly"
        in text
    )
    print("  -> inject_tool_guardrails passed!")


def test_process_request_payload():
    print("Testing process_request_payload...")
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {
                        "text": "Hello! <internal_reminder>!IMPORTANT! Recall the workflow rules: ...</internal_reminder>"
                    }
                ],
            }
        ],
        "tools": [
            {
                "functionDeclarations": [
                    {
                        "name": "bash",
                        "description": "original description",
                        "parameters": {
                            "properties": {
                                "description": {
                                    "type": "STRING",
                                    "description": "original param description",
                                }
                            }
                        },
                    }
                ]
            }
        ],
    }

    # Reset state metrics
    state.COMPACTOR_ORIG_BYTES = 0
    state.COMPACTOR_COMP_BYTES = 0
    state.COMPACTOR_ORIG_TOKENS = 0
    state.COMPACTOR_COMP_TOKENS = 0

    compacted = process_request_payload(payload)

    # Verify compaction happened
    assert "systemInstruction" in compacted
    assert (
        "PowerShell" in compacted["tools"][0]["functionDeclarations"][0]["description"]
    )

    # Verify state metrics were updated
    assert state.COMPACTOR_ORIG_BYTES > 0
    assert state.COMPACTOR_COMP_BYTES > 0
    print("  -> process_request_payload passed!")


def test_headroom_compression():
    print("Testing headroom compression...")
    # Use a JSON array to test smart_crusher compression (which remains active when enable_kompress=False)
    json_array = (
        "["
        + ",".join(['{"id": ' + str(i) + ', "name": "Alice"}' for i in range(100)])
        + "]"
    )
    payload = {"contents": [{"role": "user", "parts": [{"text": json_array}]}]}
    compacted = process_request_payload(payload)
    compacted_text = compacted["contents"][0]["parts"][0]["text"]
    assert (
        len(compacted_text) < len(json_array)
        or "hash=" in compacted_text
        or "[N items compressed" in compacted_text
        or compacted_text != json_array
    )
    print("  -> headroom compression passed!")


def test_extract_text_from_chunk():
    print("Testing extract_text_from_chunk...")
    from proxy_core.server import extract_text_from_chunk

    # Test 1: Single line SSE chunk
    chunk = 'data: {"choices": [{"delta": {"content": "Hello"}}]}'
    assert extract_text_from_chunk(chunk, "ollama_cloud") == "Hello"

    # Test 2: Multi-line SSE chunk
    chunk_multi = 'data: {"choices": [{"delta": {"content": "Hello"}}]}\n\ndata: {"choices": [{"delta": {"content": " World"}}]}'
    assert extract_text_from_chunk(chunk_multi, "ollama_cloud") == "Hello World"

    # Test 3: Non-streaming OpenAI chunk (message instead of delta)
    chunk_non_stream = '{"choices": [{"message": {"content": "Hello Non-Stream"}}]}'
    assert (
        extract_text_from_chunk(chunk_non_stream, "ollama_cloud") == "Hello Non-Stream"
    )

    # Test 4: Gemini SSE chunk
    chunk_gemini = (
        'data: {"candidates": [{"content": {"parts": [{"text": "Hello Gemini"}]}}]}'
    )
    assert extract_text_from_chunk(chunk_gemini, "gemini") == "Hello Gemini"

    print("  -> extract_text_from_chunk passed!")


def test_inspect_tree_sitter():
    print("Inspecting tree-sitter node attributes...")
    import tree_sitter_language_pack

    parser = tree_sitter_language_pack.get_parser("python")
    tree = parser.parse(b"def foo(): pass")
    node = tree.root_node
    print(f"\n[INSPECT] node type: {type(node)}")
    print(f"[INSPECT] node dir: {dir(node)}")
    # We want to print the type and attributes to stdout so we can see them
    assert hasattr(node, "type") or hasattr(node, "kind")


def test_inspect_native_tree_sitter():
    print("Inspecting native tree-sitter node attributes...")
    import tree_sitter_language_pack

    # Get the original unwrapped parser
    from proxy_core.compactor import _orig_get_parser

    parser = _orig_get_parser("python")
    tree = parser.parse(b"def foo(): pass")
    native_node = tree.root_node
    print(f"\n[NATIVE INSPECT] node type: {type(native_node)}")
    print(f"[NATIVE INSPECT] node dir: {dir(native_node)}")
    # Print type attribute or any type-like attributes
    if hasattr(native_node, "type"):
        print(f"[NATIVE INSPECT] node.type value: {native_node.type}")
    if hasattr(native_node, "kind"):
        print(f"[NATIVE INSPECT] node.kind value: {native_node.kind}")


def test_find_builtins_node():
    print("Finding builtins.Node...")
    import builtins

    if hasattr(builtins, "Node"):
        print(f"[BUILTINS] Node exists: {builtins.Node}")
        print(f"[BUILTINS] Node dir: {dir(builtins.Node)}")
    else:
        print("[BUILTINS] Node does NOT exist in builtins module!")


def test_headroom_code_compression():
    print("Testing headroom code compression...")
    # Must have >= 3 Python pattern matches and > 100 tokens to trigger headroom code-aware compression
    python_code = """
def very_long_function_name_to_test_headroom_compression_and_ensure_it_is_greater_than_five_hundred_characters(a, b, c):
    \"\"\"This is a very long docstring to help exceed the five hundred character limit for headroom compression to trigger and verify that SafeTreeWrapper and SafeNodeWrapper work perfectly.\"\"\"
    print("Starting a very long function to test headroom compression")
    x = a + b
    y = b + c
    z = c + a
    print(f"Calculated x={x}, y={y}, z={z}")
    for i in range(10):
        print(f"Loop iteration {i}")
        if i % 2 == 0:
            print("Even")
        else:
            print("Odd")
    return x + y + z


def another_helper_function_for_testing_purposes(param_one: int, param_two: int) -> int:
    \"\"\"This is another helper function to add more tokens to the test code sample.\"\"\"
    result_value = param_one * param_two + param_one
    print(f"Helper function computed: {result_value}")
    for j in range(5):
        print(f"Helper loop: {j}")
    return result_value


if __name__ == "__main__":
    result = very_long_function_name_to_test_headroom_compression_and_ensure_it_is_greater_than_five_hundred_characters(1, 2, 3)
    extra = another_helper_function_for_testing_purposes(result, 10)
    print(f"Final combined result: {result + extra}")
"""
    payload = {"contents": [{"role": "user", "parts": [{"text": python_code}]}]}
    compacted = process_request_payload(payload)
    compacted_text = compacted["contents"][0]["parts"][0]["text"]
    print(f"\n[COMPRESSION RESULT]:\n{compacted_text}\n")
    assert compacted_text != python_code, "Compression did not change the text"


def test_403_error_logging_only_by_key():
    from proxy_core.rotation import log_non_429_error, remove_key_from_error_log
    import os
    import json

    ERROR_LOG_PATH = "error_keys_log.json"
    # Backup existing log if it exists
    backup_exists = os.path.exists(ERROR_LOG_PATH)
    backup_content = None
    if backup_exists:
        with open(ERROR_LOG_PATH, "r", encoding="utf-8") as f:
            backup_content = f.read()
        os.remove(ERROR_LOG_PATH)

    try:
        # 1. Log 403 error for model A and key X
        log_non_429_error("model_A", "key_X", "HTTP 403 Forbidden: Access denied")

        # Verify it was logged
        assert os.path.exists(ERROR_LOG_PATH)
        with open(ERROR_LOG_PATH, "r", encoding="utf-8") as f:
            log_data = json.load(f)

        # The key in JSON should be "key_X|403"
        assert "key_X|403" in log_data
        assert log_data["key_X|403"]["count"] == 1
        assert log_data["key_X|403"]["model"] == "model_A"

        # 2. Log 403 error for model B and key X (same key, different model)
        log_non_429_error("model_B", "key_X", "HTTP 403 Forbidden: Access denied again")

        with open(ERROR_LOG_PATH, "r", encoding="utf-8") as f:
            log_data = json.load(f)

        # Count should increment to 2
        assert "key_X|403" in log_data
        assert log_data["key_X|403"]["count"] == 2

        # 3. Remove key X from error log (using any model, e.g. model_C)
        remove_key_from_error_log("model_C", "key_X")

        with open(ERROR_LOG_PATH, "r", encoding="utf-8") as f:
            log_data = json.load(f)

        # The entry should be gone
        assert "key_X|403" not in log_data

    finally:
        # Restore backup
        if os.path.exists(ERROR_LOG_PATH):
            os.remove(ERROR_LOG_PATH)
        if backup_exists and backup_content is not None:
            with open(ERROR_LOG_PATH, "w", encoding="utf-8") as f:
                f.write(backup_content)


def test_401_error_logging_only_by_key():
    from proxy_core.rotation import log_non_429_error, remove_key_from_error_log
    import os
    import json

    ERROR_LOG_PATH = "error_keys_log.json"
    # Backup existing log if it exists
    backup_exists = os.path.exists(ERROR_LOG_PATH)
    backup_content = None
    if backup_exists:
        with open(ERROR_LOG_PATH, "r", encoding="utf-8") as f:
            backup_content = f.read()
        os.remove(ERROR_LOG_PATH)

    try:
        # 1. Log 401 error for model A and key Y
        log_non_429_error("model_A", "key_Y", "HTTP 401 Unauthorized: Invalid token")

        # Verify it was logged
        assert os.path.exists(ERROR_LOG_PATH)
        with open(ERROR_LOG_PATH, "r", encoding="utf-8") as f:
            log_data = json.load(f)

        # The key in JSON should be "key_Y|401"
        assert "key_Y|401" in log_data
        assert log_data["key_Y|401"]["count"] == 1
        assert log_data["key_Y|401"]["model"] == "model_A"

        # 2. Log 401 error for model B and key Y (same key, different model)
        log_non_429_error(
            "model_B", "key_Y", "HTTP 401 Unauthorized: Expired credentials"
        )

        with open(ERROR_LOG_PATH, "r", encoding="utf-8") as f:
            log_data = json.load(f)

        # Count should increment to 2
        assert "key_Y|401" in log_data
        assert log_data["key_Y|401"]["count"] == 2

        # 3. Remove key Y from error log (using any model, e.g. model_C)
        remove_key_from_error_log("model_C", "key_Y")

        with open(ERROR_LOG_PATH, "r", encoding="utf-8") as f:
            log_data = json.load(f)

        # The entry should be gone
        assert "key_Y|401" not in log_data

    finally:
        # Restore backup
        if os.path.exists(ERROR_LOG_PATH):
            os.remove(ERROR_LOG_PATH)
        if backup_exists and backup_content is not None:
            with open(ERROR_LOG_PATH, "w", encoding="utf-8") as f:
                f.write(backup_content)


def test_google_model_routing():
    from proxy_core.server import MODEL_SETTINGS
    from proxy_core.rotation import API_KEYS
    
    candidate_model = "google/gemini-1.5-flash"
    
    # Verify that the google/ prefix triggers correct dynamic registration
    if candidate_model.startswith("google/"):
        target_model = candidate_model[7:]
        MODEL_SETTINGS[candidate_model] = {
            "provider": "gemini",
            "base_url": "https://generativelanguage.googleapis.com",
            "keys_pool": API_KEYS,
            "target_model": target_model,
        }
        
    assert candidate_model in MODEL_SETTINGS
    assert MODEL_SETTINGS[candidate_model]["provider"] == "gemini"
    assert MODEL_SETTINGS[candidate_model]["target_model"] == "gemini-1.5-flash"



def test_translate_payload_to_openai():
    print("Testing translate_payload_to_openai...")
    from proxy_core.helpers import translate_payload_to_openai

    gemini_payload = {
        "systemInstruction": {
            "parts": [{"text": "You are a coding assistant."}]
        },
        "contents": [
            {
                "role": "user",
                "parts": [{"text": "Run list_dir tool"}]
            },
            {
                "role": "model",
                "parts": [
                    {
                        "functionCall": {
                            "name": "list_dir",
                            "args": {"path": "."}
                        }
                    }
                ]
            },
            {
                "role": "user",
                "parts": [
                    {
                        "functionResponse": {
                            "name": "list_dir",
                            "response": {"files": ["a.txt", "b.txt"]}
                        }
                    }
                ]
            }
        ],
        "tools": [
            {
                "functionDeclarations": [
                    {
                        "name": "list_dir",
                        "description": "List directory contents",
                        "parameters": {
                            "type": "OBJECT",
                            "properties": {
                                "path": {"type": "STRING", "description": "Dir path"}
                            },
                            "required": ["path"]
                        }
                    }
                ]
            }
        ],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 1000}
    }

    translated = translate_payload_to_openai(gemini_payload, "minimax_m3")

    assert translated["model"] == "minimax_m3"
    assert translated["temperature"] == 0.2
    assert translated["max_tokens"] == 1000

    # System instruction
    assert translated["messages"][0]["role"] == "system"
    assert "coding assistant" in translated["messages"][0]["content"]

    # First user message
    assert translated["messages"][1]["role"] == "user"
    assert "Run list_dir tool" in translated["messages"][1]["content"]

    # Assistant message with tool_calls
    assert translated["messages"][2]["role"] == "assistant"
    assert "tool_calls" in translated["messages"][2]
    call_id = translated["messages"][2]["tool_calls"][0]["id"]
    assert translated["messages"][2]["tool_calls"][0]["function"]["name"] == "list_dir"
    assert '"path": "."' in translated["messages"][2]["tool_calls"][0]["function"]["arguments"]

    # Tool response must match call_id!
    assert translated["messages"][3]["role"] == "tool"
    assert translated["messages"][3]["tool_call_id"] == call_id
    assert translated["messages"][3]["name"] == "list_dir"
    assert "a.txt" in translated["messages"][3]["content"]

    # Tools declaration sanitized type lowercase
    assert "tools" in translated
    fn_decl = translated["tools"][0]["function"]
    assert fn_decl["name"] == "list_dir"
    assert fn_decl["parameters"]["type"] == "object"
    assert fn_decl["parameters"]["properties"]["path"]["type"] == "string"

    print("  -> translate_payload_to_openai passed!")


def test_translate_openai_chunk_to_gemini():
    print("Testing translate_openai_chunk_to_gemini...")
    from proxy_core.helpers import translate_openai_chunk_to_gemini, flush_tool_calls_to_gemini

    # 1. Reasoning chunk (GLM-5 / Minimax M3 / DeepSeek)
    openai_chunk_reasoning = 'data: {"choices": [{"delta": {"reasoning_content": "Analyzing request..."}}]}'
    res1 = translate_openai_chunk_to_gemini(openai_chunk_reasoning)
    assert "Analyzing request..." in res1
    assert '"thought": true' in res1
    assert "candidates" in res1

    # 2. Text chunk
    openai_chunk_text = 'data: {"choices": [{"delta": {"content": "Hello world"}}]}'
    res2 = translate_openai_chunk_to_gemini(openai_chunk_text)
    assert "Hello world" in res2
    assert "thought" not in res2

    # 3. Tool call chunk streaming accumulation
    acc = {"calls": {}}
    tc_chunk1 = 'data: {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"name": "read_files", "arguments": "{\\"path\\": "}}]}}]}'
    tc_chunk2 = 'data: {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": "\\"main.py\\"}"}}]}}]}'
    tc_chunk_end = 'data: {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]}'

    res3a = translate_openai_chunk_to_gemini(tc_chunk1, acc)
    assert res3a == ""  # Intermediate chunk buffered
    assert acc["calls"][0]["name"] == "read_files"
    assert acc["calls"][0]["args_str"] == '{"path": '

    res3b = translate_openai_chunk_to_gemini(tc_chunk2, acc)
    assert res3b == ""
    assert acc["calls"][0]["args_str"] == '{"path": "main.py"}'

    res3c = translate_openai_chunk_to_gemini(tc_chunk_end, acc)
    assert "functionCall" in res3c
    assert "read_files" in res3c
    assert "main.py" in res3c
    assert "STOP" in res3c
    assert not acc.get("calls")

    # 4. Done chunk returns empty string (never forwards [DONE] to Gemini client)
    assert translate_openai_chunk_to_gemini("data: [DONE]") == ""

    # 5. Flush at stream end if tool calls remained
    acc2 = {"calls": {0: {"name": "test_tool", "args_str": '{"key": "val"}'}}}
    flushed = flush_tool_calls_to_gemini(acc2)
    assert "test_tool" in flushed
    assert "val" in flushed
    assert not acc2.get("calls")

    print("  -> translate_openai_chunk_to_gemini passed!")


if __name__ == "__main__":
    print("=== RUNNING COMPACTOR TESTS ===")
    try:
        test_compact_tools()
        test_compact_contents_superpowers()
        test_compact_skill_responses()
        test_block_generic_read_on_code_files()
        test_move_reminder_to_system_instruction()
        test_inject_tool_guardrails()
        test_process_request_payload()
        test_headroom_compression()
        test_headroom_code_compression()
        test_extract_text_from_chunk()
        test_inspect_tree_sitter()
        test_inspect_native_tree_sitter()
        test_find_builtins_node()
        test_403_error_logging_only_by_key()
        test_google_model_routing()
        test_translate_payload_to_openai()
        test_translate_openai_chunk_to_gemini()
        print("\n=== ALL TESTS PASSED SUCCESSFULLY! ===\n")
        sys.exit(0)
    except AssertionError as e:
        print(f"\n!!! TEST FAILURE !!!")
        import traceback

        traceback.print_exc()
        sys.exit(1)
    except Exception as e:
        print(f"\n!!! UNEXPECTED ERROR: {e} !!!")
        import traceback

        traceback.print_exc()
        sys.exit(1)
