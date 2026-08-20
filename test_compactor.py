import json
import pytest
from proxy_core.helpers import (
    translate_openai_chunk_to_gemini,
    flush_tool_calls_to_gemini,
    translate_payload_to_openai,
    extract_text_from_chunk,
    extract_thought_from_chunk,
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

    # OpenAI chunk with reasoning_content (should be excluded by default)
    openai_reasoning_chunk = json.dumps(
        {"choices": [{"delta": {"reasoning_content": "Thinking process"}}]}
    )
    extracted2 = extract_text_from_chunk(f"data: {openai_reasoning_chunk}", "openai")
    assert extracted2 == ""
    extracted2_with_thoughts = extract_text_from_chunk(
        f"data: {openai_reasoning_chunk}", "openai", include_thoughts=True
    )
    assert extracted2_with_thoughts == "Thinking process"

    # Gemini chunk with text part
    gemini_chunk = json.dumps(
        {"candidates": [{"content": {"parts": [{"text": "Gemini response text"}]}}]}
    )
    extracted3 = extract_text_from_chunk(f"data: {gemini_chunk}", "gemini")
    assert extracted3 == "Gemini response text"

    # Gemini chunk with thought part (should be excluded by default)
    gemini_thought_chunk = json.dumps(
        {
            "candidates": [
                {"content": {"parts": [{"text": "Internal thoughts", "thought": True}]}}
            ]
        }
    )
    extracted4 = extract_text_from_chunk(f"data: {gemini_thought_chunk}", "gemini")
    assert extracted4 == ""
    extracted4_with_thoughts = extract_text_from_chunk(
        f"data: {gemini_thought_chunk}", "gemini", include_thoughts=True
    )
    assert extracted4_with_thoughts == "Internal thoughts"


def test_extract_thought_from_chunk():
    # OpenAI reasoning chunk
    openai_reasoning_chunk = json.dumps(
        {"choices": [{"delta": {"reasoning_content": "Reasoning steps"}}]}
    )
    assert (
        extract_thought_from_chunk(f"data: {openai_reasoning_chunk}", "openai")
        == "Reasoning steps"
    )

    # Gemini thought chunk
    gemini_thought_chunk = json.dumps(
        {
            "candidates": [
                {"content": {"parts": [{"text": "Gemini thought", "thought": True}]}}
            ]
        }
    )
    assert (
        extract_thought_from_chunk(f"data: {gemini_thought_chunk}", "gemini")
        == "Gemini thought"
    )


@pytest.mark.asyncio
async def test_anomaly_detection_thoughts_only():
    from proxy_core.server import analyze_response_for_anomalies
    from proxy_core.state import RECENT_ANOMALIES

    RECENT_ANOMALIES.clear()

    # Raw response with only thought chunks
    raw_thought_resp = (
        b'data: {"candidates":[{"content":{"parts":[{"text":"Thinking only","thought":true}]},"index":0}]}\n\n'
        b'data: {"candidates":[{"content":{"parts":[]},"finishReason":"STOP","index":0}]}\n\n'
    )

    await analyze_response_for_anomalies(
        raw_response=raw_thought_resp,
        response_text="",
        model="gemini-2.5-flash",
        provider="gemini",
    )

    assert len(RECENT_ANOMALIES) > 0
    assert any("contained only reasoning thoughts" in msg for msg in RECENT_ANOMALIES)


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


def test_strip_historical_thoughts_preserving_signatures():
    from proxy_core.compactor import strip_historical_thoughts_from_contents

    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": "Hello, solve this task"}],
            },
            {
                "role": "model",
                "parts": [
                    {
                        "thought": True,
                        "thoughtSignature": "cryptographic_sig_12345",
                        "text": "Extremely long reasoning chain taking thousands of tokens...",
                    },
                    {
                        "thought": True,
                        "text": "Another thought part without signature",
                    },
                    {
                        "text": "Here is the final solution to your task.",
                    },
                    {
                        "functionCall": {
                            "name": "lookup",
                            "args": {"query": "test"},
                        }
                    },
                    {
                        "functionCall": {
                            "name": "read",
                            "args": {"path": "a.py"},
                        },
                        "thoughtSignature": "fc_sig_999",
                    },
                ],
            },
        ],
        "messages": [
            {
                "role": "assistant",
                "content": "OpenAI answer",
                "reasoning_content": "Long OpenAI reasoning",
            }
        ],
    }

    result = strip_historical_thoughts_from_contents(payload)

    # Verify Gemini contents
    model_parts = result["contents"][1]["parts"]
    # 1. Thought with signature should have text stripped to "" and signature preserved
    sig_part = next((p for p in model_parts if "thoughtSignature" in p), None)
    assert sig_part is not None
    assert sig_part["thought"] is True
    assert sig_part["thoughtSignature"] == "cryptographic_sig_12345"
    assert sig_part["text"] == ""

    # 2. Thought without signature should be stripped
    assert not any(
        p.get("text") == "Another thought part without signature" for p in model_parts
    )

    # 3. Regular text and functionCall parts must remain intact
    assert any(
        p.get("text") == "Here is the final solution to your task." for p in model_parts
    )
    assert any("functionCall" in p for p in model_parts)

    # 4. CRITICAL: functionCall part carrying a thoughtSignature must be left
    #    EXACTLY as-is (no text/thought added) — adding text would violate the
    #    Part data oneof and trigger "oneof field 'data' is already set".
    fc_sig_part = next(
        (p for p in model_parts if p.get("functionCall", {}).get("name") == "read"),
        None,
    )
    assert fc_sig_part is not None
    assert fc_sig_part == {
        "functionCall": {"name": "read", "args": {"path": "a.py"}},
        "thoughtSignature": "fc_sig_999",
    }
    assert "text" not in fc_sig_part
    assert "thought" not in fc_sig_part

    # Verify OpenAI messages reasoning stripped
    assert "reasoning_content" not in result["messages"][0]


def test_split_merged_functioncall_text_parts():
    from proxy_core.compactor import split_merged_parts_in_contents

    payload = {
        "contents": [
            {"role": "user", "parts": [{"text": "hi"}]},
            {
                "role": "model",
                "parts": [
                    {
                        "functionCall": {"name": "lookup", "args": {"q": "x"}},
                        "text": "undefined\n",
                    },
                    {
                        "functionCall": {"name": "read", "args": {"path": "a.py"}},
                        "text": "Let me check",
                        "thoughtSignature": "sig_abc",
                    },
                    {"text": "normal answer"},
                    {"inlineData": {"mimeType": "image/png", "data": "base64"}},
                ],
            },
        ]
    }

    result = split_merged_parts_in_contents(payload)
    model_parts = result["contents"][1]["parts"]

    # Merged functionCall+text part must be split into two separate parts
    assert model_parts[0] == {"functionCall": {"name": "lookup", "args": {"q": "x"}}}
    assert model_parts[1] == {"text": "undefined\n"}

    # Signature stays on the functionCall part; text becomes its own part
    assert model_parts[2] == {
        "functionCall": {"name": "read", "args": {"path": "a.py"}},
        "thoughtSignature": "sig_abc",
    }
    assert model_parts[3] == {"text": "Let me check"}

    # Unmerged parts pass through untouched
    assert model_parts[4] == {"text": "normal answer"}
    assert model_parts[5] == {"inlineData": {"mimeType": "image/png", "data": "base64"}}


def test_auto_continue_config_default():
    from proxy_core.config import load_rotation_config

    cfg = load_rotation_config()
    assert "auto_continue" in cfg
    assert isinstance(cfg["auto_continue"], bool)
    assert "max_auto_continues" in cfg
    assert isinstance(cfg["max_auto_continues"], int)
    assert 1 <= cfg["max_auto_continues"] <= 5


def test_extract_thought_signatures_from_chunk():
    from proxy_core.helpers import extract_thought_signatures_from_chunk

    gemini_chunk = json.dumps(
        {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "thought": True,
                                "thoughtSignature": "gemini_sig_123",
                                "text": "thinking...",
                            }
                        ]
                    }
                }
            ]
        }
    )
    sigs = extract_thought_signatures_from_chunk(
        f"data: {gemini_chunk}", provider="gemini"
    )
    assert sigs == ["gemini_sig_123"]

    openai_chunk = json.dumps(
        {
            "choices": [
                {
                    "delta": {
                        "thoughtSignature": "openai_sig_456",
                        "reasoning_content": "reasoning...",
                    }
                }
            ]
        }
    )
    sigs_oa = extract_thought_signatures_from_chunk(
        f"data: {openai_chunk}", provider="openai"
    )
    assert sigs_oa == ["openai_sig_456"]


def test_build_continuation_payload_gemini():
    from proxy_core.helpers import build_continuation_payload

    orig = {
        "contents": [
            {"role": "user", "parts": [{"text": "Hello"}]},
        ]
    }
    cont = build_continuation_payload(
        orig_payload=orig,
        accumulated_text="Partial answer text",
        accumulated_thoughts="Some thoughts",
        thought_signatures=None,
        is_gemini=True,
    )
    contents = cont["contents"]
    assert len(contents) == 3
    assert contents[0] == {"role": "user", "parts": [{"text": "Hello"}]}
    assert contents[1]["role"] == "model"
    # Thought part + text part in model turn
    assert any(p.get("thought") is True for p in contents[1]["parts"])
    assert any(p.get("text") == "Partial answer text" for p in contents[1]["parts"])
    # User turn with Continue
    assert contents[2] == {"role": "user", "parts": [{"text": "Continue"}]}


def test_build_continuation_payload_gemini_with_signature():
    from proxy_core.helpers import build_continuation_payload

    orig = {
        "contents": [
            {"role": "user", "parts": [{"text": "Hello"}]},
        ]
    }
    cont = build_continuation_payload(
        orig_payload=orig,
        accumulated_text="Answer part 1",
        accumulated_thoughts="",
        thought_signatures=["sig_xyz"],
        is_gemini=True,
    )
    contents = cont["contents"]
    assert len(contents) == 3
    model_parts = contents[1]["parts"]
    sig_part = next((p for p in model_parts if "thoughtSignature" in p), None)
    assert sig_part is not None
    assert sig_part["thoughtSignature"] == "sig_xyz"
    assert sig_part["text"] == ""
    assert sig_part["thought"] is True
    assert contents[2] == {"role": "user", "parts": [{"text": "Continue"}]}


def test_build_continuation_payload_openai():
    from proxy_core.helpers import build_continuation_payload

    orig = {
        "messages": [
            {"role": "user", "content": "Hello OpenAI"},
        ]
    }
    cont = build_continuation_payload(
        orig_payload=orig,
        accumulated_text="OpenAI answer part 1",
        accumulated_thoughts="OpenAI reasoning",
        thought_signatures=None,
        is_gemini=False,
    )
    messages = cont["messages"]
    assert len(messages) == 3
    assert messages[0] == {"role": "user", "content": "Hello OpenAI"}
    assert messages[1] == {
        "role": "assistant",
        "content": "OpenAI answer part 1",
        "reasoning_content": "OpenAI reasoning",
    }
    assert messages[2] == {"role": "user", "content": "Continue"}
