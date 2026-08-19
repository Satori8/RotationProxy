import json
from proxy_core.helpers import (
    translate_openai_chunk_to_gemini,
    flush_tool_calls_to_gemini,
    translate_payload_to_openai,
    extract_text_from_chunk,
)


def test_translate_text_chunk_has_willcontinue():
    chunk = json.dumps(
        {
            "choices": [
                {
                    "delta": {"content": "Hello"},
                    "finish_reason": None,
                }
            ]
        }
    )
    line, is_terminal = translate_openai_chunk_to_gemini(f"data: {chunk}")
    assert not is_terminal
    assert '"willContinue": true' in line
    assert '"text": "Hello"' in line or '"text":"Hello"' in line


def test_translate_finish_chunk_terminal():
    chunk = json.dumps(
        {
            "choices": [
                {
                    "delta": {"content": "Hi"},
                    "finish_reason": "stop",
                }
            ]
        }
    )
    line, is_terminal = translate_openai_chunk_to_gemini(f"data: {chunk}")
    assert is_terminal is True
    assert '"finishReason": "STOP"' in line or '"finishReason":"STOP"' in line
    assert "willContinue" not in line


def test_translate_tool_calls_accumulate_and_flush():
    tool_call_acc = {"calls": {}}
    chunk1 = json.dumps(
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "function": {
                                    "name": "get_weather",
                                    "arguments": '{"city":',
                                },
                            }
                        ]
                    },
                    "finish_reason": None,
                }
            ]
        }
    )
    chunk2 = json.dumps(
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "function": {
                                    "arguments": '"Paris"}',
                                },
                            }
                        ]
                    },
                    "finish_reason": "tool_calls",
                }
            ]
        }
    )

    line1, is_terminal1 = translate_openai_chunk_to_gemini(
        f"data: {chunk1}", tool_call_acc
    )
    assert line1 == ""
    assert not is_terminal1
    assert 0 in tool_call_acc["calls"]

    line2, is_terminal2 = translate_openai_chunk_to_gemini(
        f"data: {chunk2}", tool_call_acc
    )
    assert is_terminal2 is True
    assert "functionCall" in line2
    assert "get_weather" in line2
    assert (
        '"finishReason": "TOOL_CALLS"' in line2
        or '"finishReason":"TOOL_CALLS"' in line2
    )
    assert not tool_call_acc["calls"]


def test_translate_done_no_calls():
    tool_call_acc = {"calls": {}}
    line, is_terminal = translate_openai_chunk_to_gemini("data: [DONE]", tool_call_acc)
    assert line == ""
    assert not is_terminal


def test_translate_done_with_calls_flushes():
    tool_call_acc = {"calls": {0: {"name": "fn", "args_str": "{}"}}}
    line, is_terminal = translate_openai_chunk_to_gemini("data: [DONE]", tool_call_acc)
    assert is_terminal is True
    assert (
        '"finishReason": "TOOL_CALLS"' in line or '"finishReason":"TOOL_CALLS"' in line
    )
    assert not tool_call_acc["calls"]


def test_flush_tool_calls_to_gemini():
    tool_call_acc = {"calls": {0: {"name": "fn", "args_str": '{"a":1}'}}}
    line, is_terminal = flush_tool_calls_to_gemini(tool_call_acc)
    assert is_terminal is True
    assert "functionCall" in line
    assert "fn" in line
    assert (
        '"finishReason": "TOOL_CALLS"' in line or '"finishReason":"TOOL_CALLS"' in line
    )
    assert not tool_call_acc["calls"]

    empty_acc = {"calls": {}}
    line_empty, is_terminal_empty = flush_tool_calls_to_gemini(empty_acc)
    assert line_empty == ""
    assert not is_terminal_empty


def test_translate_payload_to_openai():
    gemini_payload = {
        "systemInstruction": {"parts": [{"text": "You are a helpful assistant."}]},
        "contents": [
            {
                "role": "model",
                "parts": [
                    {
                        "functionCall": {
                            "name": "lookup",
                            "args": {"query": "test"},
                        }
                    }
                ],
            },
            {
                "role": "user",
                "parts": [
                    {
                        "functionResponse": {
                            "name": "lookup",
                            "response": {"result": "success"},
                        }
                    }
                ],
            },
        ],
        "tools": [
            {
                "functionDeclarations": [
                    {
                        "name": "lookup",
                        "description": "Perform lookup",
                        "parameters": {
                            "type": "OBJECT",
                            "properties": {"query": {"type": "STRING"}},
                            "required": ["query"],
                        },
                    }
                ]
            }
        ],
    }

    openai_payload = translate_payload_to_openai(gemini_payload, "deepseek-chat")
    messages = openai_payload["messages"]

    # Assert system message
    assert any(
        m["role"] == "system" and "helpful assistant" in m["content"] for m in messages
    )

    # Assert assistant message with tool_calls
    assistant_msg = next(m for m in messages if m["role"] == "assistant")
    assert "tool_calls" in assistant_msg
    tool_call = assistant_msg["tool_calls"][0]
    expected_call_id = "call_1_lookup"
    assert tool_call["id"] == expected_call_id
    assert tool_call["function"]["name"] == "lookup"

    # Assert tool response message
    tool_msg = next(m for m in messages if m["role"] == "tool")
    assert tool_msg["tool_call_id"] == expected_call_id
    assert "success" in tool_msg["content"]

    # Assert tools schema sanitized to lowercase
    tools = openai_payload["tools"]
    assert len(tools) == 1
    assert tools[0]["type"] == "function"
    assert tools[0]["function"]["name"] == "lookup"
    params = tools[0]["function"]["parameters"]
    assert params["type"] == "object"
    assert params["properties"]["query"]["type"] == "string"


def test_extract_text_from_chunk():
    # OpenAI chunk with content
    openai_content_chunk = json.dumps(
        {"choices": [{"delta": {"content": "Hello World"}}]}
    )
    extracted1 = extract_text_from_chunk(f"data: {openai_content_chunk}", "openai")
    assert extracted1 == "Hello World"

    # OpenAI chunk with reasoning_content
    openai_reasoning_chunk = json.dumps(
        {"choices": [{"delta": {"reasoning_content": "Thinking process"}}]}
    )
    extracted2 = extract_text_from_chunk(f"data: {openai_reasoning_chunk}", "openai")
    assert extracted2 == "Thinking process"

    # Gemini chunk with text part
    gemini_chunk = json.dumps(
        {"candidates": [{"content": {"parts": [{"text": "Gemini response text"}]}}]}
    )
    extracted3 = extract_text_from_chunk(f"data: {gemini_chunk}", "gemini")
    assert extracted3 == "Gemini response text"


def test_sse_keepalive_config_and_stream_tracking():
    from proxy_core.config import load_rotation_config
    from proxy_core.state import ACTIVE_STREAMS_PER_VPN

    cfg = load_rotation_config()
    assert "sse_keepalive" in cfg
    assert isinstance(cfg["sse_keepalive"], bool)

    # Verify ACTIVE_STREAMS_PER_VPN structure
    assert isinstance(ACTIVE_STREAMS_PER_VPN, dict)
    assert 0 in ACTIVE_STREAMS_PER_VPN
    assert 6 in ACTIVE_STREAMS_PER_VPN
