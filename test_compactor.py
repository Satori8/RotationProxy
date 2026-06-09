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
    assert extract_text_from_chunk(chunk_non_stream, "ollama_cloud") == "Hello Non-Stream"

    # Test 4: Gemini SSE chunk
    chunk_gemini = 'data: {"candidates": [{"content": {"parts": [{"text": "Hello Gemini"}]}}]}'
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
"""
    payload = {"contents": [{"role": "user", "parts": [{"text": python_code}]}]}
    compacted = process_request_payload(payload)


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
        test_find_builtins_node()
        print("\n=== ALL TESTS PASSED SUCCESSFULLY! ===")
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
