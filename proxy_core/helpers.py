import re
import json
import time
import os
import asyncio
import datetime
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
        model_name = match.group(1)
        if model_name == "gemini-2.0-flash-lite":
            return "gemini-flash-lite-latest"
        return model_name

    # 2. Fall back to explicit path checks
    if "gemini-flash-lite-latest" in path or "gemini-2.0-flash-lite" in path:
        return "gemini-flash-lite-latest"
    if "gemini-3-flash-preview" in path:
        return "gemini-3-flash-preview"
    if "gemini-3.6-flash" in path:
        return "gemini-3.6-flash"

    # 3. Try to extract from JSON body
    try:
        data = json.loads(body)
        if isinstance(data, dict) and "model" in data:
            return data["model"]
    except Exception:
        pass
    return "gemini-3.6-flash"


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


def extract_text_from_chunk(chunk_str: str, provider: str) -> str:
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
            if provider == "gemini":
                candidates = data.get("candidates", [])
                if candidates:
                    content = candidates[0].get("content", {})
                    parts = content.get("parts", [])
                    if parts:
                        text = parts[0].get("text", "")
                        if text:
                            extracted_texts.append(text)
            else:
                choices = data.get("choices", [])
                if choices:
                    delta = choices[0].get("delta", {})
                    if "content" in delta:
                        content = delta["content"]
                        if content:
                            extracted_texts.append(content)
                    elif "message" in delta:
                        content = delta["message"].get("content", "")
                        if content:
                            extracted_texts.append(content)
                    elif "message" in choices[0]:
                        content = choices[0]["message"].get("content", "")
                        if content:
                            extracted_texts.append(content)
        except Exception:
            pass
    return "".join(extracted_texts)


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


def translate_payload_to_openai(gemini_payload: dict, target_model: str) -> dict:
    is_mistral_medium = "mistral-medium" in target_model.lower()

    if "messages" in gemini_payload:
        # Already in OpenAI format, just update the model to target_model
        new_payload = dict(gemini_payload)
        new_payload["model"] = target_model

        if is_mistral_medium:
            # Inject loop mitigation parameters
            if "frequency_penalty" not in new_payload:
                new_payload["frequency_penalty"] = 0.5
            if "presence_penalty" not in new_payload:
                new_payload["presence_penalty"] = 0.5
            # If temperature is too low, raise it slightly to break loops
            temp = new_payload.get("temperature")
            if temp is not None and float(temp) < 0.3:
                new_payload["temperature"] = 0.3

        return new_payload

    openai_payload = {"model": target_model, "messages": []}
    if "contents" in gemini_payload:
        for content in gemini_payload["contents"]:
            role = content.get("role", "user")
            if role == "model":
                role = "assistant"
            parts = content.get("parts", [])
            text = " ".join(
                p.get("text", "") for p in parts if isinstance(p, dict) and "text" in p
            )
            openai_payload["messages"].append({"role": role, "content": text})
    if "generationConfig" in gemini_payload:
        gc = gemini_payload["generationConfig"]
        if "temperature" in gc:
            openai_payload["temperature"] = gc["temperature"]
        if "maxOutputTokens" in gc:
            openai_payload["max_tokens"] = gc["maxOutputTokens"]
        if "topP" in gc:
            openai_payload["top_p"] = gc["topP"]

    if is_mistral_medium:
        # Inject loop mitigation parameters for translated payloads too
        if "frequency_penalty" not in openai_payload:
            openai_payload["frequency_penalty"] = 0.5
        if "presence_penalty" not in openai_payload:
            openai_payload["presence_penalty"] = 0.5
        temp = openai_payload.get("temperature")
        if temp is not None and float(temp) < 0.3:
            openai_payload["temperature"] = 0.3

    return openai_payload


def translate_openai_chunk_to_gemini(openai_chunk_str: str) -> str:
    """Translate an OpenAI SSE chunk to a Gemini SSE chunk."""
    if openai_chunk_str.startswith("data:"):
        data_content = openai_chunk_str[5:].strip()
        if data_content == "[DONE]":
            return "data: [DONE]"
        try:
            openai_data = json.loads(data_content)
            choices = openai_data.get("choices", [])
            if choices:
                delta = choices[0].get("delta", {})
                content = delta.get("content", "")

                openai_finish_reason = choices[0].get("finish_reason")
                gemini_finish_reason = None
                if openai_finish_reason == "stop":
                    gemini_finish_reason = "STOP"
                elif openai_finish_reason == "length":
                    gemini_finish_reason = "MAX_TOKENS"
                elif openai_finish_reason is not None:
                    gemini_finish_reason = str(openai_finish_reason).upper()

                gemini_data = {
                    "candidates": [
                        {
                            "content": {"parts": [{"text": content}], "role": "model"},
                            "index": 0,
                        }
                    ]
                }
                if gemini_finish_reason:
                    gemini_data["candidates"][0]["finishReason"] = gemini_finish_reason

                return f"data: {json.dumps(gemini_data)}"
        except Exception:
            pass
    return openai_chunk_str


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
