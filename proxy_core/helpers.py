import re
import json
import time
import os
import asyncio
import datetime
import unicodedata
from fastapi import Request
from proxy_core.logger import logger

PROCESS_SESSION_ID = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


def truncate_thought_signature(text: str) -> str:
    try:

        def repl(match):
            val = match.group(2)
            if len(val) > 100:
                return f'{match.group(1)}"<truncated thoughtSignature, length: {len(val)}>"'
            return match.group(0)

        return re.sub(r'("thoughtSignature"\s*:\s*)"([^"]+)"', repl, text)
    except Exception:
        return text


def beautify_json_string(text: str) -> str:
    try:
        parsed = json.loads(text)
        return json.dumps(parsed, indent=2, ensure_ascii=False)
    except Exception:
        return text


def get_session_id(request: Request) -> str:
    for h in ["x-session-id", "x-conversation-id", "session-id", "session_id"]:
        val = request.headers.get(h)
        if val:
            sanitized = "".join(c for c in val if c.isalnum() or c in "-_")
            if sanitized:
                return sanitized
    return f"session_{PROCESS_SESSION_ID}"


def get_requested_model(path: str, body: bytes) -> str:
    # 1. Try to extract model from Gemini path (e.g., models/gemini-2.5-flash:generateContent)
    match = re.search(r"models/([^:/]+)", path)
    if match:
        return match.group(1)

    # 2. Try to extract from JSON body
    try:
        data = json.loads(body)
        if isinstance(data, dict) and "model" in data:
            return data["model"]
    except Exception:
        pass

    # 3. Fall back to primary model from rotation config
    try:
        from proxy_core.config import load_rotation_config

        config = load_rotation_config()
        primary = config.get("primary_model")
        if primary:
            return primary
    except Exception:
        pass

    return ""


def extract_chat_messages(body: bytes) -> list:
    try:
        data = json.loads(body)
        if isinstance(data, dict):
            if "contents" in data:
                msgs = []
                for content in data["contents"]:
                    role = content.get("role", "user")
                    text = ""
                    parts = content.get("parts", [])
                    if isinstance(parts, list):
                        text = " ".join(
                            p.get("text", "")
                            for p in parts
                            if isinstance(p, dict) and "text" in p
                        )
                    msgs.append({"role": role, "content": text})
                return msgs
            elif "messages" in data:
                msgs = []
                for message in data["messages"]:
                    role = message.get("role", "user")
                    content = message.get("content", "")
                    msgs.append({"role": role, "content": content})
                return msgs
    except Exception as e:
        logger.debug(f"Could not parse chat messages from body: {e}")
    return []


def extract_text_from_chunk(
    chunk_str: str, provider: str, include_thoughts: bool = False
) -> str:
    extracted_texts = []
    lines = chunk_str.split("\n")
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.startswith("data:"):
            line = line[5:].strip()
        if line == "[DONE]":
            continue
        try:
            data = json.loads(line)
            if provider == "gemini" or "candidates" in data:
                candidates = data.get("candidates", [])
                if candidates:
                    content = candidates[0].get("content", {})
                    parts = content.get("parts", [])
                    for p in parts:
                        if isinstance(p, dict):
                            is_thought = (
                                p.get("thought") is True or p.get("thought") == True
                            )
                            if "text" in p and p["text"]:
                                if not is_thought or include_thoughts:
                                    extracted_texts.append(p["text"])
                            elif "functionCall" in p or "function_call" in p:
                                fc = p.get("functionCall") or p.get("function_call")
                                if isinstance(fc, dict):
                                    extracted_texts.append(
                                        f"\n[Tool Call: {fc.get('name')}]\n"
                                    )
            else:
                choices = data.get("choices", [])
                if choices:
                    delta = choices[0].get("delta") or choices[0].get("message") or {}
                    if "content" in delta and delta["content"]:
                        extracted_texts.append(delta["content"])
                    if include_thoughts:
                        if "reasoning_content" in delta and delta["reasoning_content"]:
                            extracted_texts.append(delta["reasoning_content"])
                        elif "reasoning" in delta and delta["reasoning"]:
                            extracted_texts.append(delta["reasoning"])
                        elif "thought" in delta and delta["thought"]:
                            extracted_texts.append(delta["thought"])
                    if "tool_calls" in delta and delta["tool_calls"]:
                        for tc in delta["tool_calls"]:
                            if isinstance(tc, dict):
                                fn = tc.get("function", {})
                                if isinstance(fn, dict) and fn.get("name"):
                                    extracted_texts.append(
                                        f"\n[Tool Call: {fn.get('name')}]\n"
                                    )
        except Exception:
            pass
    return "".join(extracted_texts)


def extract_thought_from_chunk(chunk_str: str, provider: str) -> str:
    extracted_thoughts = []
    lines = chunk_str.split("\n")
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.startswith("data:"):
            line = line[5:].strip()
        if line == "[DONE]":
            continue
        try:
            data = json.loads(line)
            if provider == "gemini" or "candidates" in data:
                candidates = data.get("candidates", [])
                if candidates:
                    content = candidates[0].get("content", {})
                    parts = content.get("parts", [])
                    for p in parts:
                        if isinstance(p, dict):
                            is_thought = (
                                p.get("thought") is True or p.get("thought") == True
                            )
                            if is_thought and "text" in p and p["text"]:
                                extracted_thoughts.append(p["text"])
            else:
                choices = data.get("choices", [])
                if choices:
                    delta = choices[0].get("delta") or choices[0].get("message") or {}
                    if "reasoning_content" in delta and delta["reasoning_content"]:
                        extracted_thoughts.append(delta["reasoning_content"])
                    elif "reasoning" in delta and delta["reasoning"]:
                        extracted_thoughts.append(delta["reasoning"])
                    elif "thought" in delta and delta["thought"]:
                        extracted_thoughts.append(delta["thought"])
        except Exception:
            pass
    return "".join(extracted_thoughts)


def extract_thought_signatures_from_chunk(chunk_str: str, provider: str) -> list[str]:
    """Extracts non-empty thoughtSignature / thought_signature strings from an SSE chunk."""
    signatures = []
    lines = chunk_str.split("\n")
    for line in lines:
        line = line.strip()
        if not line or not line.startswith("data:"):
            continue
        line = line[5:].strip()
        if line == "[DONE]":
            continue
        try:
            data = json.loads(line)
            if provider == "gemini" or "candidates" in data:
                candidates = data.get("candidates", [])
                for cand in candidates:
                    content = cand.get("content", {})
                    parts = content.get("parts", [])
                    for p in parts:
                        if isinstance(p, dict):
                            sig = p.get("thoughtSignature") or p.get(
                                "thought_signature"
                            )
                            if sig and isinstance(sig, str) and sig.strip():
                                if sig.strip() not in signatures:
                                    signatures.append(sig.strip())
            else:
                choices = data.get("choices", [])
                for choice in choices:
                    delta = choice.get("delta") or choice.get("message") or {}
                    sig = delta.get("thoughtSignature") or delta.get(
                        "thought_signature"
                    )
                    if sig and isinstance(sig, str) and sig.strip():
                        if sig.strip() not in signatures:
                            signatures.append(sig.strip())
        except Exception:
            pass
    return signatures


def build_continuation_payload(
    orig_payload: dict,
    accumulated_text: str = "",
    accumulated_thoughts: str = "",
    thought_signatures: list[str] | None = None,
    is_gemini: bool = True,
) -> dict:
    """
    Constructs a multi-turn continuation request payload from the accumulated
    model output (preserving thought signatures, thoughts, and text generated so far)
    and appends a user 'Continue' turn.
    """
    import copy

    cont_payload = copy.deepcopy(orig_payload)
    signatures = thought_signatures or []

    if is_gemini or "contents" in cont_payload:
        if "contents" not in cont_payload or not isinstance(
            cont_payload["contents"], list
        ):
            cont_payload["contents"] = []

        model_parts = []
        if signatures:
            for sig in signatures:
                model_parts.append(
                    {"thought": True, "thoughtSignature": sig, "text": ""}
                )
        elif accumulated_thoughts and accumulated_thoughts.strip():
            model_parts.append({"thought": True, "text": accumulated_thoughts.strip()})

        if accumulated_text and accumulated_text.strip():
            model_parts.append({"text": accumulated_text.strip()})

        if not model_parts:
            model_parts.append({"text": ""})

        cont_payload["contents"].append({"role": "model", "parts": model_parts})
        cont_payload["contents"].append(
            {"role": "user", "parts": [{"text": "Continue"}]}
        )

        from proxy_core.compactor import split_merged_parts_in_contents

        cont_payload = split_merged_parts_in_contents(cont_payload)
    else:
        if "messages" not in cont_payload or not isinstance(
            cont_payload["messages"], list
        ):
            cont_payload["messages"] = []

        asst_msg = {"role": "assistant", "content": accumulated_text or ""}
        if accumulated_thoughts and accumulated_thoughts.strip():
            asst_msg["reasoning_content"] = accumulated_thoughts.strip()

        cont_payload["messages"].append(asst_msg)
        cont_payload["messages"].append({"role": "user", "content": "Continue"})

    return cont_payload


def extract_token_usage(raw_response: bytes) -> dict:
    usage_info = {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "cached_tokens": 0,
    }
    try:
        response_str = raw_response.decode("utf-8", errors="ignore")

        # 1. Try to find OpenAI/OpenRouter format usage
        prompt_match = re.search(r'"prompt_tokens"\s*:\s*(\d+)', response_str)
        completion_match = re.search(r'"completion_tokens"\s*:\s*(\d+)', response_str)
        total_match = re.search(r'"total_tokens"\s*:\s*(\d+)', response_str)
        cached_match = re.search(r'"cached_tokens"\s*:\s*(\d+)', response_str)

        if prompt_match:
            usage_info["prompt_tokens"] = int(prompt_match.group(1))
        if completion_match:
            usage_info["completion_tokens"] = int(completion_match.group(1))
        if total_match:
            usage_info["total_tokens"] = int(total_match.group(1))
        if cached_match:
            usage_info["cached_tokens"] = int(cached_match.group(1))

        # 2. Try to find Gemini format usage (usageMetadata)
        prompt_gemini = re.search(r'"promptTokenCount"\s*:\s*(\d+)', response_str)
        completion_gemini = re.search(
            r'"candidatesTokenCount"\s*:\s*(\d+)', response_str
        )
        total_gemini = re.search(r'"totalTokenCount"\s*:\s*(\d+)', response_str)
        cached_gemini = re.search(
            r'"cachedContentTokenCount"\s*:\s*(\d+)', response_str
        )

        if prompt_gemini:
            usage_info["prompt_tokens"] = int(prompt_gemini.group(1))
        if completion_gemini:
            usage_info["completion_tokens"] = int(completion_gemini.group(1))
        if total_gemini:
            usage_info["total_tokens"] = int(total_gemini.group(1))
        if cached_gemini:
            usage_info["cached_tokens"] = int(cached_gemini.group(1))

    except Exception as e:
        logger.debug(f"Failed to extract token usage: {e}")

    return usage_info


def get_next_log_index(session_dir: str) -> int:
    import re

    max_idx = 0
    if os.path.exists(session_dir):
        for fname in os.listdir(session_dir):
            m = re.match(r"^(\d+)_request", fname)
            if m:
                max_idx = max(max_idx, int(m.group(1)))
            m2 = re.match(r"^N_request(\d+)", fname)
            if m2:
                max_idx = max(max_idx, int(m2.group(1)))
    return max_idx + 1


async def write_chat_log(
    model: str,
    provider: str,
    messages: list,
    response: str,
    session_id: str,
    raw_request: bytes | None = None,
    raw_response: bytes | None = None,
):
    import os
    import json
    from datetime import datetime

    try:
        log_dir = "chat_logs"
        os.makedirs(log_dir, exist_ok=True)
        today = datetime.now().strftime("%Y-%m-%d")
        log_file = os.path.join(log_dir, f"chat_log_{today}.txt")
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        def do_write_legacy():
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"\n{'=' * 80}\n")
                f.write(f"TIMESTAMP: {timestamp}\n")
                f.write(f"SESSION ID: {session_id}\n")
                f.write(f"MODEL: {model} (Provider: {provider})\n")
                f.write(f"{'-' * 80}\n")
                f.write("REQUEST MESSAGES:\n")
                for m in messages:
                    f.write(f"[{m.get('role', 'user')}]: {m.get('content', '')}\n")
                f.write(f"{'-' * 80}\n")
                f.write("RESPONSE:\n")
                f.write(response)
                f.write(f"\n{'=' * 80}\n")

        # Session-based logging
        session_dir = os.path.join(log_dir, session_id)
        os.makedirs(session_dir, exist_ok=True)

        idx = get_next_log_index(session_dir)

        # Prepare request string representation (no truncation)
        req_str = ""
        if raw_request is not None:
            try:
                parsed_json = json.loads(raw_request)
                req_str = json.dumps(parsed_json, indent=2, ensure_ascii=False)
            except Exception:
                req_str = raw_request.decode("utf-8", errors="ignore")

        # Prepare response string representation (no truncation)
        resp_str = ""
        if raw_response is not None:
            try:
                # If valid JSON, pretty-print
                parsed_json = json.loads(raw_response)
                resp_str = json.dumps(parsed_json, indent=2, ensure_ascii=False)
            except Exception:
                resp_str = raw_response.decode("utf-8", errors="ignore")
        else:
            resp_str = response

        def do_write_session():
            req_path = os.path.join(session_dir, f"{idx}_request.txt")
            with open(req_path, "w", encoding="utf-8") as f:
                f.write(req_str.replace("\\n", "\n"))

            resp_path = os.path.join(session_dir, f"{idx}_response.txt")
            with open(resp_path, "w", encoding="utf-8") as f:
                f.write(resp_str.replace("\\n", "\n"))

        await asyncio.to_thread(do_write_session)
        logger.info(f"Saved session log to {session_dir} (N={idx})")
    except Exception as e:
        logger.error(f"Failed to write chat log: {e}")


def sanitize_schema(schema):
    if isinstance(schema, dict):
        new_s = {}
        for k, v in schema.items():
            if k == "type" and isinstance(v, str):
                new_s[k] = v.lower()
            else:
                new_s[k] = sanitize_schema(v)
        return new_s
    elif isinstance(schema, list):
        return [sanitize_schema(item) for item in schema]
    return schema


ALLOWED_GEMINI_OPENAI_KEYS = {
    "model",
    "messages",
    "temperature",
    "top_p",
    "max_tokens",
    "max_completion_tokens",
    "stream",
    "stop",
    "presence_penalty",
    "frequency_penalty",
    "seed",
    "tools",
    "tool_choice",
    "response_format",
    "n",
    "user",
    "stream_options",
    "logit_bias",
    "logprobs",
    "top_logprobs",
    "parallel_tool_calls",
    "function_call",
    "functions",
}


def sanitize_openai_payload_for_gemini(payload: dict, target_model: str) -> dict:
    """Sanitize OpenAI-format payload specifically for Google's /v1beta/chat/completions endpoint.
    Google strictly rejects unknown JSON keys like promptCacheKey, separate_reasoning, thinking, options, etc.
    """
    if not isinstance(payload, dict):
        return payload
    new_payload = {}
    for k, v in payload.items():
        if k in ALLOWED_GEMINI_OPENAI_KEYS:
            new_payload[k] = v
    clean_target = (
        target_model[7:] if target_model.startswith("google/") else target_model
    )
    new_payload["model"] = clean_target
    if "tools" in new_payload and isinstance(new_payload["tools"], list):
        new_payload["tools"] = sanitize_schema(new_payload["tools"])
    return new_payload


def translate_payload_to_openai(gemini_payload: dict, target_model: str) -> dict:
    is_mistral_medium = "mistral-medium" in target_model.lower()

    if "messages" in gemini_payload:
        # Already in OpenAI format, just update the model to target_model
        new_payload = dict(gemini_payload)
        new_payload["model"] = target_model

        if "tools" in new_payload and isinstance(new_payload["tools"], list):
            new_payload["tools"] = sanitize_schema(new_payload["tools"])

        if is_mistral_medium:
            # Inject loop mitigation parameters
            if "frequency_penalty" not in new_payload:
                new_payload["frequency_penalty"] = 0.5
            if "presence_penalty" not in new_payload:
                new_payload["presence_penalty"] = 0.5

        return new_payload

    openai_payload = {"model": target_model, "messages": []}

    # Translate systemInstruction / system_instruction
    sys_inst = gemini_payload.get("systemInstruction") or gemini_payload.get(
        "system_instruction"
    )
    if sys_inst and isinstance(sys_inst, dict):
        parts = sys_inst.get("parts", [])
        if isinstance(parts, list):
            sys_text = "\n".join(
                p.get("text", "")
                for p in parts
                if isinstance(p, dict) and "text" in p and p.get("text")
            )
            if sys_text:
                openai_payload["messages"].append(
                    {"role": "system", "content": sys_text}
                )

    # Track generated tool call IDs so functionResponse IDs match assistant tool_calls IDs exactly!
    pending_tool_call_ids = {}  # fn_name -> list of call_ids
    tool_call_counter = 0

    # Translate contents
    if "contents" in gemini_payload and isinstance(gemini_payload["contents"], list):
        for content in gemini_payload["contents"]:
            if not isinstance(content, dict):
                continue
            role = content.get("role", "user")
            if role in ("model", "assistant"):
                role = "assistant"

            parts = content.get("parts", [])
            text_parts = []
            tool_calls = []
            tool_responses = []

            if isinstance(parts, list):
                for p in parts:
                    if not isinstance(p, dict):
                        continue
                    if "text" in p and p["text"]:
                        text_parts.append(p["text"])
                    if "functionCall" in p or "function_call" in p:
                        fc = p.get("functionCall") or p.get("function_call")
                        if isinstance(fc, dict):
                            fn_name = fc.get("name", "")
                            args = fc.get("args", {})
                            args_str = (
                                json.dumps(args, ensure_ascii=False)
                                if isinstance(args, (dict, list))
                                else str(args)
                            )
                            tool_call_counter += 1
                            call_id = (
                                fc.get("id") or f"call_{tool_call_counter}_{fn_name}"
                            )
                            pending_tool_call_ids.setdefault(fn_name, []).append(
                                call_id
                            )
                            tool_calls.append(
                                {
                                    "id": call_id,
                                    "type": "function",
                                    "function": {
                                        "name": fn_name,
                                        "arguments": args_str,
                                    },
                                }
                            )
                    if "functionResponse" in p or "function_response" in p:
                        fr = p.get("functionResponse") or p.get("function_response")
                        if isinstance(fr, dict):
                            fn_name = fr.get("name", "")
                            resp = fr.get("response", {})
                            resp_str = (
                                json.dumps(resp, ensure_ascii=False)
                                if isinstance(resp, (dict, list))
                                else str(resp)
                            )
                            if (
                                fn_name in pending_tool_call_ids
                                and pending_tool_call_ids[fn_name]
                            ):
                                call_id = pending_tool_call_ids[fn_name].pop(0)
                            else:
                                call_id = fr.get("id") or f"call_{fn_name}"
                            tool_responses.append(
                                {
                                    "role": "tool",
                                    "tool_call_id": call_id,
                                    "name": fn_name,
                                    "content": resp_str,
                                }
                            )

            if tool_responses:
                for tr in tool_responses:
                    openai_payload["messages"].append(tr)
                if text_parts:
                    openai_payload["messages"].append(
                        {"role": "user", "content": "\n".join(text_parts)}
                    )
            else:
                content_text = "\n".join(text_parts) if text_parts else ""
                msg = {"role": role}
                if content_text or not tool_calls:
                    msg["content"] = content_text
                else:
                    msg["content"] = None
                if tool_calls:
                    msg["tool_calls"] = tool_calls
                openai_payload["messages"].append(msg)

    # Translate tools
    tools = gemini_payload.get("tools")
    if tools and isinstance(tools, list):
        openai_tools = []
        for tg in tools:
            if not isinstance(tg, dict):
                continue
            fds = (
                tg.get("functionDeclarations") or tg.get("function_declarations") or []
            )
            if isinstance(fds, list):
                for fd in fds:
                    if isinstance(fd, dict):
                        params = sanitize_schema(fd.get("parameters", {}))
                        openai_tools.append(
                            {
                                "type": "function",
                                "function": {
                                    "name": fd.get("name", ""),
                                    "description": fd.get("description", ""),
                                    "parameters": params,
                                },
                            }
                        )
        if openai_tools:
            openai_payload["tools"] = openai_tools

    # Translate generationConfig
    gc = (
        gemini_payload.get("generationConfig")
        or gemini_payload.get("generation_config")
        or {}
    )
    if isinstance(gc, dict):
        if "temperature" in gc:
            openai_payload["temperature"] = gc["temperature"]
        if "maxOutputTokens" in gc:
            openai_payload["max_tokens"] = gc["maxOutputTokens"]
        elif "max_output_tokens" in gc:
            openai_payload["max_tokens"] = gc["max_output_tokens"]
        if "topP" in gc:
            openai_payload["top_p"] = gc["topP"]
        elif "top_p" in gc:
            openai_payload["top_p"] = gc["top_p"]

    if is_mistral_medium:
        # Inject loop mitigation parameters for translated payloads too
        if "frequency_penalty" not in openai_payload:
            openai_payload["frequency_penalty"] = 0.5
        if "presence_penalty" not in openai_payload:
            openai_payload["presence_penalty"] = 0.5

    return openai_payload


def flush_tool_calls_to_gemini(tool_call_acc: dict) -> tuple[str, bool]:
    """Build a Gemini candidate chunk for any accumulated tool calls."""
    calls = tool_call_acc.get("calls", {})
    if not calls:
        return ("", False)

    parts = []
    for idx in sorted(calls.keys()):
        c = calls[idx]
        fn_name = c.get("name", "")
        args_str = c.get("args_str", "")
        if fn_name:
            try:
                args_dict = json.loads(args_str) if args_str else {}
            except Exception:
                args_dict = {"raw": args_str}
            parts.append({"functionCall": {"name": fn_name, "args": args_dict}})

    calls.clear()
    if not parts:
        return ("", False)

    gemini_data = {
        "candidates": [
            {
                "content": {"parts": parts, "role": "model"},
                "finishReason": "TOOL_CALLS",
                "index": 0,
            }
        ]
    }
    return (f"data: {json.dumps(gemini_data, ensure_ascii=False)}", True)


def extract_leaked_gemini_tool_calls(text: str) -> tuple[str, list[dict]]:
    """
    Detects and extracts Gemini internal raw tool-call tokens (e.g. 'tool_nameuseeland{...}'
    or 'call:tool_name{...}') that leaked into plain text output, converting them back
    into structured functionCall part objects for client execution.

    Returns:
        (cleaned_text: str, recovered_function_calls: list[dict])
    """
    if not text or (
        "useeland" not in text and "use_tool" not in text and "call:" not in text
    ):
        return text, []

    recovered_calls = []
    cleaned_text = text

    for keyword in ("useeland", "use_tool"):
        while keyword in cleaned_text:
            pos = cleaned_text.find(keyword)
            # Find the tool name preceding the keyword
            prefix = cleaned_text[:pos]
            name_match = re.search(r"([a-zA-Z0-9_\-\.:]+)$", prefix)
            if not name_match:
                break
            fn_name = name_match.group(1).strip()
            name_start = name_match.start()

            # Find the JSON body starting after keyword
            after_kw = cleaned_text[pos + len(keyword) :].lstrip()
            if not after_kw.startswith("{"):
                break

            # Find matching closing brace
            brace_depth = 0
            json_end = -1
            for idx, ch in enumerate(after_kw):
                if ch == "{":
                    brace_depth += 1
                elif ch == "}":
                    brace_depth -= 1
                    if brace_depth == 0:
                        json_end = idx + 1
                        break

            if json_end == -1:
                break

            raw_json = after_kw[:json_end]
            try:
                args_dict = json.loads(raw_json)
            except Exception:
                args_dict = {"raw": raw_json}

            recovered_calls.append(
                {"functionCall": {"name": fn_name, "args": args_dict}}
            )

            # Replace the entire leaked token block from name_start to end of json
            total_block_len = (
                (pos - name_start)
                + len(keyword)
                + (len(cleaned_text[pos + len(keyword) :]) - len(after_kw))
                + json_end
            )
            cleaned_text = (
                cleaned_text[:name_start] + cleaned_text[name_start + total_block_len :]
            ).strip()

    return cleaned_text, recovered_calls


def translate_openai_chunk_to_gemini(
    openai_chunk_str: str, tool_call_acc: dict | None = None
) -> tuple[str, bool]:
    """Translate an OpenAI SSE chunk or raw JSON to a Gemini SSE chunk."""
    raw_json = openai_chunk_str.strip()
    if raw_json.startswith("data:"):
        raw_json = raw_json[5:].strip()

    # DO NOT forward [DONE] to Gemini client; Gemini SSE stream ends by closing HTTP stream
    if raw_json == "[DONE]":
        if tool_call_acc and tool_call_acc.get("calls"):
            return flush_tool_calls_to_gemini(tool_call_acc)
        return ("", False)

    if not raw_json or not raw_json.startswith("{"):
        return ("", False)

    try:
        openai_data = json.loads(raw_json)
        choices = openai_data.get("choices", [])
        if not choices:
            return ("", False)

        choice = choices[0]
        delta = choice.get("delta") or choice.get("message") or {}
        openai_finish_reason = choice.get("finish_reason")

        content = delta.get("content") or ""
        reasoning = (
            delta.get("reasoning_content")
            or delta.get("reasoning")
            or delta.get("thought")
            or ""
        )

        parts = []
        if reasoning:
            parts.append({"text": reasoning, "thought": True})
        if content:
            # Check if Gemini leaked raw tool tokens into plain text
            cleaned_content, leaked_calls = extract_leaked_gemini_tool_calls(content)
            if cleaned_content:
                parts.append({"text": cleaned_content})
            if leaked_calls:
                parts.extend(leaked_calls)

        # Accumulate streaming tool calls
        tool_calls = delta.get("tool_calls") or choice.get("tool_calls") or []
        if tool_calls:
            for tc in tool_calls:
                if not isinstance(tc, dict):
                    continue
                idx = tc.get("index", 0)
                fn = tc.get("function", {})
                if not isinstance(fn, dict):
                    continue
                fn_name = fn.get("name", "")
                fn_args = fn.get("arguments", "")

                if tool_call_acc is not None:
                    calls = tool_call_acc.setdefault("calls", {})
                    call_entry = calls.setdefault(idx, {"name": "", "args_str": ""})
                    if fn_name:
                        call_entry["name"] = fn_name
                    if fn_args:
                        call_entry["args_str"] += fn_args
                else:
                    args_dict = {}
                    if isinstance(fn_args, dict):
                        args_dict = fn_args
                    elif isinstance(fn_args, str) and fn_args.strip():
                        try:
                            args_dict = json.loads(fn_args)
                        except Exception:
                            args_dict = {"raw": fn_args}
                    parts.append({"functionCall": {"name": fn_name, "args": args_dict}})

        # If finish_reason indicates end of tool calls, flush accumulated tool calls
        if (
            openai_finish_reason in ("tool_calls", "function_call", "stop")
            and tool_call_acc
            and tool_call_acc.get("calls")
        ):
            calls = tool_call_acc.get("calls", {})
            for idx in sorted(calls.keys()):
                c = calls[idx]
                fn_name = c.get("name", "")
                args_str = c.get("args_str", "")
                if fn_name:
                    try:
                        args_dict = json.loads(args_str) if args_str else {}
                    except Exception:
                        args_dict = {"raw": args_str}
                    parts.append({"functionCall": {"name": fn_name, "args": args_dict}})
            calls.clear()

        gemini_finish_reason = None
        if openai_finish_reason in ("tool_calls", "function_call"):
            gemini_finish_reason = "TOOL_CALLS"
        elif openai_finish_reason == "stop":
            gemini_finish_reason = "STOP"
        elif openai_finish_reason == "length":
            gemini_finish_reason = "MAX_TOKENS"
        elif openai_finish_reason is not None:
            gemini_finish_reason = str(openai_finish_reason).upper()

        if not parts and not gemini_finish_reason:
            return ("", False)

        candidate = {
            "content": {"parts": parts if parts else [{"text": ""}], "role": "model"},
            "index": 0,
        }
        is_terminal = False
        if gemini_finish_reason:
            candidate["finishReason"] = gemini_finish_reason
            is_terminal = True
        else:
            # CRITICAL: newer @ai-sdk/google treats a chunk without willContinue
            # as the final chunk of the response. Intermediate chunks MUST carry
            # willContinue: true so OpenCode keeps accumulating parts into ONE
            # assistant message (prevents orphaned functionCall turns -> 400).
            candidate["willContinue"] = True

        gemini_data = {"candidates": [candidate]}
        return (f"data: {json.dumps(gemini_data, ensure_ascii=False)}", is_terminal)
    except Exception:
        pass

    return ("", False)


def add_anomaly_to_state(model: str, msg: str):
    try:
        from proxy_core import state
        from datetime import datetime

        timestamp = datetime.now().strftime("%H:%M:%S")
        anomaly_str = f"[{timestamp}] [{model}] {msg}"
        if not hasattr(state, "RECENT_ANOMALIES"):
            state.RECENT_ANOMALIES = []
        state.RECENT_ANOMALIES.append(anomaly_str)
        if len(state.RECENT_ANOMALIES) > 100:
            state.RECENT_ANOMALIES.pop(0)
    except Exception as e:
        logger.error(f"Failed to add anomaly to state: {e}")


# Strict code keywords that unambiguously indicate truncated statements
TRUNCATED_KEYWORDS = {
    "def",
    "class",
    "import",
    "from",
    "return",
    "yield",
    "raise",
    "throw",
    "function",
    "const",
    "let",
    "var",
    "if",
    "elif",
    "else",
    "async",
    "await",
    "for",
    "while",
    "try",
    "except",
    "finally",
    "with",
    "switch",
    "interface",
    "struct",
    "enum",
    "fn",
    "impl",
    "trait",
    "namespace",
}

# Trailing grammatical continuation words (articles, prepositions, conjunctions, pronouns, open adverbs/gerunds)
TRAILING_CONTINUATION_WORDS = {
    "a",
    "an",
    "the",
    "this",
    "that",
    "these",
    "those",
    "which",
    "whose",
    "each",
    "every",
    "some",
    "any",
    "such",
    "of",
    "to",
    "in",
    "for",
    "on",
    "with",
    "at",
    "by",
    "from",
    "up",
    "about",
    "into",
    "over",
    "after",
    "under",
    "above",
    "through",
    "between",
    "before",
    "behind",
    "beyond",
    "during",
    "without",
    "within",
    "along",
    "across",
    "since",
    "until",
    "via",
    "onto",
    "upon",
    "toward",
    "towards",
    "and",
    "or",
    "but",
    "nor",
    "so",
    "yet",
    "because",
    "although",
    "though",
    "while",
    "where",
    "when",
    "why",
    "how",
    "if",
    "unless",
    "as",
    "than",
    "whether",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "being",
    "have",
    "has",
    "had",
    "having",
    "do",
    "does",
    "did",
    "doing",
    "will",
    "would",
    "shall",
    "should",
    "can",
    "could",
    "may",
    "might",
    "must",
    "automatically",
    "manually",
    "directly",
    "properly",
    "specifically",
    "dynamically",
    "using",
    "including",
    "defining",
    "creating",
    "implementing",
    "providing",
    "allowing",
    "enabling",
    "generating",
    "в",
    "во",
    "на",
    "с",
    "со",
    "по",
    "к",
    "ко",
    "из",
    "изо",
    "от",
    "ото",
    "у",
    "о",
    "об",
    "обо",
    "за",
    "под",
    "подо",
    "над",
    "надо",
    "перед",
    "передо",
    "при",
    "через",
    "для",
    "до",
    "без",
    "безо",
    "сквозь",
    "между",
    "среди",
    "около",
    "возле",
    "вдоль",
    "поперек",
    "вокруг",
    "про",
    "и",
    "или",
    "но",
    "а",
    "да",
    "если",
    "то",
    "что",
    "чтобы",
    "как",
    "где",
    "когда",
    "почему",
    "зачем",
    "также",
    "тоже",
    "хотя",
    "пока",
    "будто",
    "словно",
    "бы",
    "же",
    "ли",
    "ведь",
    "даже",
    "только",
    "лишь",
    "который",
    "которая",
    "которое",
    "которые",
    "которого",
    "которой",
    "которых",
    "которому",
    "которым",
    "какой",
    "какая",
    "какое",
    "какие",
    "чей",
    "чья",
    "чье",
    "чьи",
    "этот",
    "эта",
    "это",
    "эти",
    "тот",
    "та",
    "то",
    "те",
    "автоматически",
    "вручную",
    "напрямую",
    "динамически",
    "специально",
    "используя",
    "включая",
    "создавая",
    "реализуя",
    "предоставляя",
    "позволяя",
}

# Trailing code operators (excluding table boundary '|')
TRAILING_OPERATORS = (
    ",",
    "=",
    "+",
    "-",
    "*",
    "/",
    "\\",
    "->",
    "=>",
    "&&",
    "||",
    "&",
    "^",
    "%",
    "==",
    "!=",
    "<=",
    ">=",
)

# Extended terminal characters (including Cyrillic/Unicode punctuation & quotes)
TERMINAL_CHARS = (
    ".",
    "!",
    "?",
    ":",
    ";",
    '"',
    "'",
    "`",
    ")",
    "]",
    "}",
    ">",
    "_",
    "*",
    "~",
    "|",
    "/",
    "%",
    "…",
    "»",
    "”",
    "’",
    "„",
    "。",
    "！",
    "？",
    "」",
    "』",
    "】",
)


def is_response_text_truncated(text: str) -> tuple[bool, str]:
    """
    Detects if generated response text was cut off / truncated mid-stream,
    even if the upstream API reported finishReason: "STOP".

    Returns (is_truncated: bool, reason: str).
    """
    if not text or not isinstance(text, str):
        return False, ""

    stripped = text.rstrip()
    if len(stripped) < 20:
        # Too short to reliably determine truncation (e.g. "Yes", "42", "true", "Done.")
        return False, ""

    # 1. Unclosed Markdown code blocks (odd number of triple backticks)
    # Exempt valid tool call markers: [Tool Call: ...]
    if (
        stripped.endswith("[Tool Call:")
        or "[Tool Call: " in stripped[-50:]
        or stripped.endswith("[Tool Call: skill]")
    ):
        pass  # Skip unclosed code block check for tool call markers
    elif stripped.count("```") % 2 == 1:
        reason = "UNCLOSED_CODE_BLOCK"
        logger.info(
            f"[Truncation Detection] Truncated output detected (Rule: {reason}, tail: {repr(stripped[-60:])})"
        )
        return True, reason

    # 2. Markdown Horizontal Rules (---, ___, ***, --) are complete endings, exempt them
    if stripped.endswith(("---", "___", "***", "--")):
        return False, ""

    # 3. Trailing syntax / operators / open brackets (excluding single '|')
    if stripped.endswith(TRAILING_OPERATORS) or stripped.endswith(("(", "[", "{")):
        reason = "TRAILING_CODE_SYNTAX"
        logger.info(
            f"[Truncation Detection] Truncated output detected (Rule: {reason}, tail: {repr(stripped[-60:])})"
        )
        return True, reason

    # 4. Trailing unfinished language keywords or continuation words
    words = stripped.split()
    if words:
        last_word = words[-1].lower().strip(" \t\r\n`'\"")
        if last_word in TRUNCATED_KEYWORDS or last_word in TRAILING_CONTINUATION_WORDS:
            reason = "TRAILING_KEYWORD"
            logger.info(
                f"[Truncation Detection] Truncated output detected (Rule: {reason}, word: '{last_word}', tail: {repr(stripped[-60:])})"
            )
            return True, reason

    # 5. Unbalanced code delimiters (open > closed)
    is_cleanly_punctuated = stripped.endswith(
        (
            ".",
            "!",
            "?",
            "\n",
            "```",
            "…",
            "»",
            "”",
            "’",
            "„",
            "。",
            "！",
            "？",
            "」",
            "』",
            "】",
        )
    )
    if not is_cleanly_punctuated:
        blocks = stripped.split("\n\n")
        tail_section = blocks[-1] if len(blocks) == 1 else "\n\n".join(blocks[-2:])
        open_parens = tail_section.count("(") - tail_section.count(")")
        open_brackets = tail_section.count("[") - tail_section.count("]")
        open_braces = tail_section.count("{") - tail_section.count("}")

        if open_parens > 0 or open_brackets > 0 or open_braces > 0:
            reason = "UNBALANCED_DELIMITERS"
            logger.info(
                f"[Truncation Detection] Truncated output detected (Rule: {reason}, tail: {repr(stripped[-60:])})"
            )
            return True, reason

    # 6. Long response ending mid-sentence without terminal punctuation
    if len(stripped) >= 60:
        lines = stripped.splitlines()
        last_line = lines[-1].strip() if lines else ""

        if not stripped.endswith(TERMINAL_CHARS):
            # Check if last character is a Unicode Emoji or Symbol (Category: So, Sm, Sk)
            last_char = stripped[-1]
            cat = unicodedata.category(last_char)
            if cat in ("So", "Sm", "Sk"):
                return False, ""

            # Check if last line is a markdown header, checklist, or bullet/numbered list item
            if last_line.startswith("#"):
                content = re.sub(r"^#+\s*", "", last_line).strip()
                last_word = (
                    content.split()[-1].lower().strip(" \t\r\n`'\"")
                    if content.split()
                    else ""
                )
                is_continuation = (
                    last_word in TRUNCATED_KEYWORDS
                    or last_word in TRAILING_CONTINUATION_WORDS
                )
                if len(content) <= 80 and not is_continuation:
                    return False, ""

            elif bool(re.match(r"^(\*|-)\s*\[[ xX]\]", last_line)):
                content = re.sub(r"^(\*|-)\s*\[[ xX]\]\s*", "", last_line).strip()
                last_word = (
                    content.split()[-1].lower().strip(" \t\r\n`'\"")
                    if content.split()
                    else ""
                )
                is_continuation = (
                    last_word in TRUNCATED_KEYWORDS
                    or last_word in TRAILING_CONTINUATION_WORDS
                )
                if len(content) <= 60 and not is_continuation:
                    return False, ""

            elif bool(re.match(r"^(-|\*|>|\d+\.)\s*", last_line)):
                content = re.sub(r"^(-|\*|>|\d+\.)\s*", "", last_line).strip()
                last_word = (
                    content.split()[-1].lower().strip(" \t\r\n`'\"")
                    if content.split()
                    else ""
                )
                is_continuation = (
                    last_word in TRUNCATED_KEYWORDS
                    or last_word in TRAILING_CONTINUATION_WORDS
                )
                if is_continuation:
                    reason = "INCOMPLETE_SENTENCE"
                    logger.info(
                        f"[Truncation Detection] Truncated output detected (Rule: {reason}, tail: {repr(stripped[-60:])})"
                    )
                    return True, reason

                if ":" in content:
                    _, _, desc = content.partition(":")
                    desc_clean = desc.strip()
                    desc_words = desc_clean.split()
                    if len(desc_words) >= 2 or len(desc_clean) >= 15:
                        reason = "INCOMPLETE_SENTENCE"
                        logger.info(
                            f"[Truncation Detection] Truncated output detected (Rule: {reason}, tail: {repr(stripped[-60:])})"
                        )
                        return True, reason
                    elif len(desc_words) <= 1 and len(desc_clean) < 15:
                        # Atomic key-value (e.g. "- Platform: win32", "- Port: 8080")
                        return False, ""
                else:
                    # Plain list item without colon
                    if len(content.split()) <= 3 and len(content) <= 25:
                        return False, ""
                    else:
                        reason = "INCOMPLETE_SENTENCE"
                        logger.info(
                            f"[Truncation Detection] Truncated output detected (Rule: {reason}, tail: {repr(stripped[-60:])})"
                        )
                        return True, reason

            reason = "INCOMPLETE_SENTENCE"
            logger.info(
                f"[Truncation Detection] Truncated output detected (Rule: {reason}, tail: {repr(stripped[-60:])})"
            )
            return True, reason

    return False, ""
