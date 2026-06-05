import time
import json
import random
import asyncio
import logging
import datetime
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx

from proxy_core import logger as core_logger
from proxy_core.config import (
    load_rotation_config,
    save_rotation_config,
    FORCE_MODEL,
    USE_KAGGLE,
    SAVE_CHAT_LOGS,
    KAGGLE_BASE_URL,
    ROTATION_CONFIG_PATH,
)
from proxy_core.state import (
    COOLDOWNS,
    CONSECUTIVE_429S,
    LAST_429_TIME,
    CONSECUTIVE_RPD_429S,
    LAST_USED,
    LAST_REQUEST_TIME,
)
from proxy_core.rotation import (
    API_KEYS,
    OPENROUTER_KEYS,
    MISTRAL_KEYS,
    LLM7_KEYS,
    OLLAMA_KEYS,
    OLLAMA_CLOUD_KEYS,
    seconds_until_rpd_reset,
    log_non_429_error,
    remove_key_from_error_log,
    wait_for_adapter_and_add_route,
    restart_vpn_service,
)
from proxy_core.state import log_queue as global_log_queue

import sys
import os

logger = logging.getLogger("proxy")

# Dynamically add vpn_manager directory to path
vpn_dir = r"D:\Work\Active\server-services\vpn_switcher"
if vpn_dir not in sys.path:
    sys.path.insert(0, vpn_dir)

try:
    from vpn_manager import WindowsWireGuardManager

    vpn_manager = WindowsWireGuardManager()
    logger.info("Successfully imported WindowsWireGuardManager in Server.")
except Exception as ve:
    vpn_manager = None
    logger.error(f"Failed to import WindowsWireGuardManager in Server: {ve}")

# VPN Global State for Rotation
VPN_CONSECUTIVE_ERRORS = 0
VPN_CURRENT_INDEX = 1
VPN_ROTATION_LOCK = asyncio.Lock()

# Parallelism State
ACTIVE_SLOTS = [0, 1, 2]  # Default 3 active slots (Clear, VPN 1, VPN 2)
BACKUP_POOL = [3, 4, 5, 6]  # Remaining channels in reserve
REQUEST_COUNT = 0
VPN_ANY_TUNNEL_ACTIVE = False


async def rotate_vpn_on_the_fly(reason: str):
    global VPN_CURRENT_INDEX
    async with VPN_ROTATION_LOCK:
        next_index = (VPN_CURRENT_INDEX + 1) % 7
        VPN_CURRENT_INDEX = next_index
        channel_name = f"VPN {next_index}" if next_index > 0 else "Clear (No VPN)"
        logger.info(f"[VPN] Rotating bound client to {channel_name} due to {reason}...")
        global_log_queue.put(
            f"[VPN] Rotating bound client to {channel_name} due to {reason}..."
        )


# Heartbeat state
VPN_CONSECUTIVE_FAILURES = {i: 0 for i in range(1, 7)}
VPN_GRACE_PERIODS = {i: 0.0 for i in range(1, 7)}  # timestamp when grace period ends


async def vpn_heartbeat_loop(app):
    """Background task that checks the health of all 6 VPN channels every 1.0s."""
    import time
    import asyncio
    import subprocess

    logger.info(
        "[Heartbeat] Waiting 30 seconds for VPN adapters to initialize before starting health checks..."
    )
    await asyncio.sleep(30.0)

    logger.info("[Heartbeat] Starting VPN health check loop...")
    while True:
        await asyncio.sleep(1.0)
        now = time.time()

        # Check which services are actually running in the system
        running_services = set()
        try:
            # Set console output encoding to UTF-8 to handle Cyrillic output perfectly
            # Use single quotes for service name to prevent PowerShell variable interpolation
            check_services_cmd = "$OutputEncoding = [System.Text.Encoding]::UTF8; [Console]::OutputEncoding = [System.Text.Encoding]::UTF8; Get-Service -Name 'WireGuardTunnel$*' | Select-Object -Property Name, Status"
            result = await asyncio.to_thread(
                subprocess.run,
                ["powershell", "-Command", check_services_cmd],
                capture_output=True,
                text=False,
            )
            if result.returncode == 0 and result.stdout:
                stdout = result.stdout.decode("utf-8", errors="replace")
                for line in stdout.splitlines():
                    if "Running" in line:
                        for idx in range(1, 7):
                            if f"WireGuardTunnel$vpn{idx}" in line:
                                running_services.add(idx)
        except Exception as se:
            logger.debug(f"[Heartbeat] Service status check error: {se}")
            # Fallback: if check fails, assume all are running to avoid false negatives
            running_services = set(range(1, 7))

        # Update global active status
        global VPN_ANY_TUNNEL_ACTIVE
        VPN_ANY_TUNNEL_ACTIVE = len(running_services) > 0

        for i in range(1, 7):
            # Skip if service is not running
            if i not in running_services:
                # Reset failures if service is stopped/not installed
                VPN_CONSECUTIVE_FAILURES[i] = 0
                continue

            # Skip if in grace period
            if now < VPN_GRACE_PERIODS[i]:
                continue

            client = app.state.vpn_clients.get(i)
            if not client:
                continue

            # Perform lightweight GET check (using Google's connectivity check - zero rate limits!)
            try:
                resp = await client.get(
                    "http://connectivitycheck.gstatic.com/generate_204", timeout=5.0
                )
                if resp.status_code in (200, 204):
                    # Success! Reset failures
                    VPN_CONSECUTIVE_FAILURES[i] = 0
                else:
                    raise Exception(f"HTTP status {resp.status_code}")
            except Exception as e:
                # Failure! Increment consecutive failures
                VPN_CONSECUTIVE_FAILURES[i] += 1
                logger.warning(
                    f"[Heartbeat] VPN {i} check failed: {e} (Consecutive: {VPN_CONSECUTIVE_FAILURES[i]})"
                )

                # Step 1: Immediate Route Addition
                route_cmd = f'New-NetRoute -InterfaceAlias "vpn{i}" -DestinationPrefix "0.0.0.0/0" -NextHop "10.8.0.1" -RouteMetric 50 -Confirm:$false -ErrorAction SilentlyContinue'
                await asyncio.to_thread(
                    subprocess.run,
                    ["powershell", "-Command", route_cmd],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )

                # Step 2: Service Restart & Cooldown
                if VPN_CONSECUTIVE_FAILURES[i] >= 3:
                    logger.error(
                        f"[Heartbeat] VPN {i} down for 3s. Triggering service restart..."
                    )
                    VPN_CONSECUTIVE_FAILURES[i] = 0
                    VPN_GRACE_PERIODS[i] = now + 15.0  # 15s grace period

                    # Restart service in background thread
                    await asyncio.to_thread(restart_vpn_service, i)


class QueueLogHandler(logging.Handler):
    def emit(self, record):
        try:
            global_log_queue.put(self.format(record))
        except Exception:
            pass


queue_handler = QueueLogHandler()
queue_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logger.addHandler(queue_handler)

PRIMARY_MODEL = "gemini-3.5-flash"
FALLBACK_MODEL = "gemini-3-flash-preview"
RETRY_DELAY_SECONDS = 90
PROCESS_SESSION_ID = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
TARGET_BASE_URL = "https://generativelanguage.googleapis.com"

MODEL_SETTINGS = {
    "gemini-3.5-flash": {
        "provider": "gemini",
        "base_url": "https://generativelanguage.googleapis.com",
        "keys_pool": API_KEYS,
        "target_model": "gemini-3.5-flash",
    },
    "gemini-3-flash": {
        "provider": "gemini",
        "base_url": "https://generativelanguage.googleapis.com",
        "keys_pool": API_KEYS,
        "target_model": "gemini-3-flash",
    },
    "gemini-3-flash-preview": {
        "provider": "gemini",
        "base_url": "https://generativelanguage.googleapis.com",
        "keys_pool": API_KEYS,
        "target_model": "gemini-3-flash-preview",
    },
    "openrouter/owl-alpha": {
        "provider": "openrouter",
        "base_url": "https://openrouter.ai/api/v1",
        "keys_pool": OPENROUTER_KEYS,
        "target_model": "openrouter/owl-alpha",
    },
    "deepseek-v4-flash": {
        "provider": "openrouter",
        "base_url": "https://openrouter.ai/api/v1",
        "keys_pool": OPENROUTER_KEYS,
        "target_model": "deepseek-v4-flash",
    },
    "gemini-flash-lite-latest": {
        "provider": "gemini",
        "base_url": "https://generativelanguage.googleapis.com",
        "keys_pool": API_KEYS,
        "target_model": "gemini-flash-lite-latest",
    },
    "deepseek-v4-flash-free": {
        "provider": "openrouter",
        "base_url": "https://openrouter.ai/api/v1",
        "keys_pool": OPENROUTER_KEYS,
        "target_model": "deepseek-v4-flash-free",
    },
    "deepseek/deepseek-v4-flash:free": {
        "provider": "openrouter",
        "base_url": "https://openrouter.ai/api/v1",
        "keys_pool": OPENROUTER_KEYS,
        "target_model": "deepseek/deepseek-v4-flash:free",
    },
    "mimo-v2.5-free": {
        "provider": "openrouter",
        "base_url": "https://openrouter.ai/api/v1",
        "keys_pool": OPENROUTER_KEYS,
        "target_model": "mimo-v2.5-free",
    },
    "nemotron-3-super-free": {
        "provider": "openrouter",
        "base_url": "https://openrouter.ai/api/v1",
        "keys_pool": OPENROUTER_KEYS,
        "target_model": "nemotron-3-super-free",
    },
    "deepseek/deepseek-r1:free": {
        "provider": "openrouter",
        "base_url": "https://openrouter.ai/api/v1",
        "keys_pool": OPENROUTER_KEYS,
        "target_model": "deepseek/deepseek-r1:free",
    },
    "meta-llama/llama-3.3-70b-instruct:free": {
        "provider": "openrouter",
        "base_url": "https://openrouter.ai/api/v1",
        "keys_pool": OPENROUTER_KEYS,
        "target_model": "meta-llama/llama-3.3-70b-instruct:free",
    },
    "qwen/qwen3-coder:free": {
        "provider": "openrouter",
        "base_url": "https://openrouter.ai/api/v1",
        "keys_pool": OPENROUTER_KEYS,
        "target_model": "qwen/qwen3-coder:free",
    },
    "moonshotai/kimi-k2.6:free": {
        "provider": "openrouter",
        "base_url": "https://openrouter.ai/api/v1",
        "keys_pool": OPENROUTER_KEYS,
        "target_model": "moonshotai/kimi-k2.6:free",
    },
}

THINKING_MODELS = {
    "gemini-3.5-flash",
    "gemini-3-flash",
    "openrouter/owl-alpha",
    "deepseek/deepseek-v4-flash:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "qwen/qwen3-coder:free",
    "moonshotai/kimi-k2.6:free",
    "deepseek/deepseek-r1:free",
}

QUICK_MODELS = {
    "gemini-flash-lite-latest",
    "gemini-2.0-flash-lite",
    "deepseek-v4-flash-free",
    "mimo-v2.5-free",
    "nemotron-3-super-free",
    "google/gemini-2.5-flash:free",
    "google/gemma-2-9b-it:free",
    "meta-llama/llama-3.1-8b-instruct:free",
    "qwen/qwen-2.5-coder-32b-instruct:free",
}

EXCLUDED_HEADERS = {
    "content-encoding",
    "content-length",
    "transfer-encoding",
    "connection",
    "keep-alive",
    "host",
}


def get_session_id(request: Request) -> str:
    for h in ["x-session-id", "x-conversation-id", "session-id", "session_id"]:
        val = request.headers.get(h)
        if val:
            sanitized = "".join(c for c in val if c.isalnum() or c in "-_")
            if sanitized:
                return sanitized
    return f"session_{PROCESS_SESSION_ID}"


def get_requested_model(path: str, body: bytes) -> str:
    if "gemini-flash-lite-latest" in path or "gemini-2.0-flash-lite" in path:
        return "gemini-flash-lite-latest"
    if "gemini-3-flash-preview" in path:
        return "gemini-3-flash-preview"
    if "gemini-3.5-flash" in path:
        return "gemini-3.5-flash"

    try:
        data = json.loads(body)
        if isinstance(data, dict) and "model" in data:
            return data["model"]
    except Exception:
        pass
    return "gemini-3.5-flash"


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
    if provider == "gemini":
        if chunk_str.startswith("data:"):
            chunk_str = chunk_str[5:].strip()
        try:
            data = json.loads(chunk_str)
            candidates = data.get("candidates", [])
            if candidates:
                content = candidates[0].get("content", {})
                parts = content.get("parts", [])
                if parts:
                    return parts[0].get("text", "")
        except Exception:
            pass
    else:
        if chunk_str.startswith("data:"):
            chunk_str = chunk_str[5:].strip()
        try:
            data = json.loads(chunk_str)
            choices = data.get("choices", [])
            if choices:
                delta = choices[0].get("delta", {})
                if "content" in delta:
                    return delta["content"]
        except Exception:
            pass
    return ""


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
    raw_request: bytes = None,
    raw_response: bytes = None,
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

        await asyncio.to_thread(do_write_legacy)
        await asyncio.to_thread(do_write_session)
        logger.info(
            f"Saved chat log to {log_file} and session log to {session_dir} (N={idx})"
        )
    except Exception as e:
        logger.error(f"Failed to write chat log: {e}")


def translate_payload_to_openai(gemini_payload: dict, target_model: str) -> dict:
    if "messages" in gemini_payload:
        # Already in OpenAI format, just update the model to target_model
        new_payload = dict(gemini_payload)
        new_payload["model"] = target_model
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


def mark_cooldown(key: str, duration: float = 60.0) -> None:
    COOLDOWNS[key] = time.time() + duration


def get_active_vpn_client(
    request: Request, vpn_mode: str, vpn_static_channel: int, current_vpn_index: int
) -> httpx.AsyncClient:
    """Resolve the appropriate AsyncClient based on the current VPN switching configuration."""
    vpn_clients = request.app.state.vpn_clients
    if vpn_mode == "disabled":
        if 0 < vpn_static_channel <= 6:
            return vpn_clients.get(vpn_static_channel, vpn_clients[0])
        return vpn_clients[0]
    else:
        # For 'every_request' or 'error_threshold' modes, use current_vpn_index
        return vpn_clients.get(current_vpn_index, vpn_clients[0])


@asynccontextmanager
async def lifespan(app: FastAPI):
    rotation_config = load_rotation_config()
    connect_timeout = float(rotation_config.get("connect_timeout", 15.0))
    read_timeout = float(rotation_config.get("read_timeout", 120.0))

    limits = httpx.Limits(
        max_keepalive_connections=100,
        max_connections=200,
        keepalive_expiry=30.0,  # Close idle connections after 30s to prevent stale sockets
    )
    timeout = httpx.Timeout(
        connect=connect_timeout,
        read=read_timeout,
        write=15.0,
        pool=15.0,
    )

    # Initialize 7 clients: index 0 (unbound) + indexes 1-6 (bound to corresponding VPN local IPs)
    app.state.vpn_clients = {0: httpx.AsyncClient(timeout=timeout, limits=limits)}
    for i in range(1, 7):
        try:
            transport = httpx.AsyncHTTPTransport(local_address=f"10.8.0.1{i}")
            app.state.vpn_clients[i] = httpx.AsyncClient(
                transport=transport, timeout=timeout, limits=limits
            )
            logger.info(
                f"[Lifespan] Initialized bound HTTP client for VPN {i} (10.8.0.1{i})"
            )
        except Exception as e:
            logger.error(
                f"[Lifespan] Failed to bind client to VPN IP 10.8.0.1{i} (falling back to unbound): {e}"
            )
            app.state.vpn_clients[i] = httpx.AsyncClient(timeout=timeout, limits=limits)

    # Maintain app.state.client as default fallback
    app.state.client = app.state.vpn_clients[0]

    # Start heartbeat loop
    heartbeat_task = asyncio.create_task(vpn_heartbeat_loop(app))

    yield

    # On shutdown
    heartbeat_task.cancel()

    for index, client in app.state.vpn_clients.items():
        try:
            await client.aclose()
        except Exception as ce:
            logger.error(f"[Lifespan] Error closing client {index}: {ce}")


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class TestModelRequest(BaseModel):
    model: str
    provider: str


@app.post("/control/test_model")
async def test_model_endpoint(req: TestModelRequest, request: Request):
    """Securely test a model via the proxy in the background to check for 200, 429, or 404."""
    model_id = req.model
    provider_name = req.provider

    # Resolve keys pool and base URL
    if provider_name == "openrouter":
        base_url = "https://openrouter.ai/api/v1"
        keys_pool = OPENROUTER_KEYS
    elif provider_name == "mistral":
        base_url = "https://api.mistral.ai/v1"
        keys_pool = MISTRAL_KEYS
    elif provider_name == "llm7":
        base_url = "https://api.llm7.io/v1"
        keys_pool = LLM7_KEYS
    elif provider_name == "ollama":
        base_url = "https://ollama.com"
        keys_pool = OLLAMA_KEYS if OLLAMA_KEYS else ["dummy"]
    elif provider_name == "ollama_cloud":
        base_url = "https://ollama.com/v1"
        keys_pool = OLLAMA_CLOUD_KEYS
    else:
        base_url = "https://generativelanguage.googleapis.com"
        keys_pool = API_KEYS

    if not keys_pool:
        return {
            "status": "error",
            "message": f"No keys configured for provider '{provider_name}'.",
        }

    # Pick the first available key
    api_key = keys_pool[0]
    headers = {"Content-Type": "application/json"}
    if provider_name in ("openrouter", "mistral", "llm7", "ollama", "ollama_cloud"):
        headers["authorization"] = f"Bearer {api_key}"
    else:
        headers["x-goog-api-key"] = api_key

    # Build payload
    test_body = {"model": model_id, "messages": [{"role": "user", "content": "Hi"}]}

    if provider_name == "ollama":
        url = f"{base_url}/api/chat"
        test_body["stream"] = False
    else:
        url = f"{base_url}/chat/completions"

    # Resolve the correct bound client for the test request
    rotation_config = load_rotation_config()
    vpn_mode = rotation_config.get("vpn_switching_mode", "disabled")
    vpn_static = int(rotation_config.get("vpn_static_channel", 0))

    current_vpn_index = VPN_CURRENT_INDEX if VPN_ANY_TUNNEL_ACTIVE else 0
    client = get_active_vpn_client(request, vpn_mode, vpn_static, current_vpn_index)

    start_time = time.perf_counter()
    try:
        req_out = client.build_request(
            method="POST",
            url=url,
            headers=headers,
            content=json.dumps(test_body).encode("utf-8"),
            timeout=10.0,
        )
        resp = await client.send(req_out)
        status_code = resp.status_code
        try:
            resp_text = resp.text
        except Exception:
            resp_text = "(failed to read response text)"
        await resp.aclose()

        latency_ms = int((time.perf_counter() - start_time) * 1000)
        logger.info(
            f"[Test Model] Upstream status: {status_code}, latency: {latency_ms}ms, body: {resp_text}"
        )

        if status_code == 200:
            return {
                "status": "ok",
                "message": "Model responded successfully!",
                "latency_ms": latency_ms,
            }
        elif status_code == 429:
            logger.error(f"[Test Model] Rate limit exceeded (429): {resp_text}")
            global_log_queue.put(f"[Test Model] Rate limit exceeded (429): {resp_text}")
            return {
                "status": "rate_limited",
                "message": f"Rate limit exceeded (429): {resp_text}",
                "latency_ms": latency_ms,
            }
        elif status_code == 404:
            logger.error(f"[Test Model] Model not found (404): {resp_text}")
            global_log_queue.put(f"[Test Model] Model not found (404): {resp_text}")
            return {
                "status": "not_found",
                "message": f"Model not found (404): {resp_text}",
                "latency_ms": latency_ms,
            }
        else:
            logger.error(
                f"[Test Model] Server returned status {status_code}: {resp_text}"
            )
            global_log_queue.put(
                f"[Test Model] Server returned status {status_code}: {resp_text}"
            )
            return {
                "status": "error",
                "message": f"Server returned status {status_code}: {resp_text}",
                "latency_ms": latency_ms,
            }
    except Exception as e:
        latency_ms = int((time.perf_counter() - start_time) * 1000)
        import traceback

        tb_str = traceback.format_exc()
        logger.error(
            f"[Test Model] Network/Connection error on testing '{model_id}' via '{provider_name}' to {url}: {e}\n{tb_str}"
        )
        global_log_queue.put(f"[Test Model] [ERROR] connection failed to {url}: {e}")
        return {
            "status": "error",
            "message": f"Network/Connection error: {e}",
            "latency_ms": latency_ms,
        }


@app.post("/control/reset_cooldowns")
async def reset_cooldowns_endpoint():
    global COOLDOWNS, CONSECUTIVE_429S, CONSECUTIVE_RPD_429S
    COOLDOWNS.clear()
    CONSECUTIVE_429S.clear()
    CONSECUTIVE_RPD_429S.clear()
    try:
        config = load_rotation_config()
        config["model_cooldowns"] = {}
        config["consecutive_model_failures"] = {}
        save_rotation_config(config)
    except Exception as e:
        logger.error(f"Failed to clear model cooldowns in config: {e}")
    logger.info("Daily cooldowns and consecutive failure counters have been reset.")
    return {"status": "success", "message": "Cooldowns reset successfully."}


@app.post("/control/global_reset")
async def global_reset_endpoint():
    global \
        COOLDOWNS, \
        CONSECUTIVE_429S, \
        CONSECUTIVE_RPD_429S, \
        LAST_429_TIME, \
        LAST_USED, \
        LAST_REQUEST_TIME, \
        VPN_CONSECUTIVE_ERRORS, \
        VPN_CURRENT_INDEX
    COOLDOWNS.clear()
    CONSECUTIVE_429S.clear()
    CONSECUTIVE_RPD_429S.clear()
    LAST_429_TIME.clear()
    LAST_USED.clear()
    LAST_REQUEST_TIME.clear()
    VPN_CONSECUTIVE_ERRORS = 0
    VPN_CURRENT_INDEX = 1

    try:
        config = load_rotation_config()
        config["model_cooldowns"] = {}
        config["consecutive_model_failures"] = {}
        save_rotation_config(config)
    except Exception as e:
        logger.error(f"Failed to reset config in global reset: {e}")

    logger.info(
        "Global reset completed. All cooldowns, consecutive errors, and rotation states have been cleared!"
    )
    return {"status": "success", "message": "Global reset successful."}


@app.api_route(
    "/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"]
)
async def transparent_proxy(request: Request, path: str):
    max_restarts = 10
    for restart_attempt in range(max_restarts):
        res = await _transparent_proxy_attempt(request, path)
        if res == "RESTART":
            continue
        return res
    return JSONResponse(
        status_code=503,
        content={"error": {"message": "Too many model switches in a single request."}},
    )


async def _transparent_proxy_attempt(request: Request, path: str):
    global \
        VPN_CONSECUTIVE_ERRORS, \
        VPN_CURRENT_INDEX, \
        REQUEST_COUNT, \
        ACTIVE_SLOTS, \
        BACKUP_POOL, \
        VPN_ANY_TUNNEL_ACTIVE
    body = await request.body()
    query_params = dict(request.query_params)
    session_id = get_session_id(request)

    # Apply context filtering if enabled in rotation config
    rotation_config = load_rotation_config()
    if rotation_config.get("filter_context", True) and request.method == "POST":
        try:
            from proxy_core.compactor import process_request_payload

            # Parse body to dict with strict=False to allow literal control characters
            body_str = body.decode("utf-8", errors="ignore")
            # Clean up escape sequences before parsing (same logic as our test script)
            from proxy_core.compactor import clean_json_escapes

            body_str = clean_json_escapes(body_str)

            orig_size = len(body)
            payload_dict = json.loads(body_str, strict=False)
            compacted_dict = process_request_payload(payload_dict)
            body = json.dumps(
                compacted_dict, ensure_ascii=False, separators=(",", ":")
            ).encode("utf-8")
            comp_size = len(body)

            saved = orig_size - comp_size
            pct = (saved / orig_size) * 100 if orig_size > 0 else 0.0
            logger.info(
                f"[Compactor] Compacted request context: {orig_size:,} -> {comp_size:,} bytes (Saved {saved:,} B, -{pct:.1f}%)"
            )

            # Update session-wide statistics in state
            from proxy_core import state

            state.COMPACTOR_ORIG_BYTES += orig_size
            state.COMPACTOR_COMP_BYTES += comp_size
        except Exception as ce:
            logger.error(f"[Compactor] Failed to compact context: {ce}")

    if path.startswith("openrouter/"):
        target_base = "https://openrouter.ai/api/v1"
        current_path = path[11:]
        keys_pool = OPENROUTER_KEYS
        provider_name = "openrouter"
    elif path.startswith("mistral/"):
        target_base = "https://api.mistral.ai/v1"
        current_path = path[8:]
        keys_pool = MISTRAL_KEYS
        provider_name = "mistral"
    elif path.startswith("llm7/"):
        target_base = "https://api.llm7.io/v1"
        current_path = path[5:]
        keys_pool = LLM7_KEYS
        provider_name = "llm7"
    elif path.startswith("ollama_cloud/"):
        target_base = "https://ollama.com/v1"
        current_path = path[13:]
        keys_pool = OLLAMA_CLOUD_KEYS
        provider_name = "ollama_cloud"
    else:
        target_base = TARGET_BASE_URL
        current_path = path
        keys_pool = API_KEYS
        provider_name = "gemini"

    rotation_config = load_rotation_config()
    parallelism_enabled = rotation_config.get("parallelism_enabled", False)
    parallel_count = rotation_config.get("parallel_tunnels_count", 3)
    per_channel_delay = rotation_config.get("per_channel_delay", 0.5)

    # Dynamically adjust active slots and backup pool size
    if len(ACTIVE_SLOTS) != parallel_count:
        all_channels = list(range(7))
        ACTIVE_SLOTS = all_channels[:parallel_count]
        BACKUP_POOL = all_channels[parallel_count:]

    if parallelism_enabled:
        # Round-robin selection
        REQUEST_COUNT += 1
        slot_idx = REQUEST_COUNT % len(ACTIVE_SLOTS)
        current_vpn_index = ACTIVE_SLOTS[slot_idx]
    else:
        current_vpn_index = VPN_CURRENT_INDEX
        slot_idx = 0

    # If no VPN tunnels are active in the system, always fall back to the unbound client (index 0)
    if not VPN_ANY_TUNNEL_ACTIVE:
        current_vpn_index = 0

    # Per-channel delay check
    current_time = time.time()
    if parallelism_enabled:
        time_since_last_request = current_time - LAST_REQUEST_TIME.get(
            (provider_name, current_vpn_index), 0.0
        )
        if time_since_last_request < per_channel_delay:
            await asyncio.sleep(per_channel_delay - time_since_last_request)
        LAST_REQUEST_TIME[(provider_name, current_vpn_index)] = time.time()
    else:
        time_since_last_request = current_time - LAST_REQUEST_TIME.get(
            provider_name, 0.0
        )
        if time_since_last_request < 0.5:  # 0.5s global delay
            await asyncio.sleep(0.5 - time_since_last_request)
        LAST_REQUEST_TIME[provider_name] = time.time()

    requested_model = get_requested_model(path, body)

    global USE_KAGGLE, FORCE_MODEL, SAVE_CHAT_LOGS
    USE_KAGGLE = rotation_config.get("use_kaggle", USE_KAGGLE)
    SAVE_CHAT_LOGS = rotation_config.get("save_chat_logs", SAVE_CHAT_LOGS)
    config_force_model = rotation_config.get("force_model", {})
    for k, v in config_force_model.items():
        FORCE_MODEL[k] = v

    candidates = rotation_config["rotation_lists"].get(
        requested_model, [requested_model]
    )
    if not candidates:
        candidates = [requested_model]

    if USE_KAGGLE and "qwen3.6" not in candidates:
        candidates = list(candidates) + ["qwen3.6"]

    # Identify domain and check for manual override
    forced_model = "auto"
    if requested_model in THINKING_MODELS or requested_model == "gemini-3.5-flash":
        forced_model = FORCE_MODEL.get("gemini-3.5-flash", "auto")
    elif (
        requested_model in QUICK_MODELS or requested_model == "gemini-flash-lite-latest"
    ):
        forced_model = FORCE_MODEL.get("gemini-flash-lite-latest", "auto")
    else:
        forced_model = FORCE_MODEL.get(requested_model, "auto")

    now = time.time()
    if forced_model != "auto":
        available_candidates = [forced_model]
    else:
        available_candidates = [
            candidate
            for candidate in candidates
            if rotation_config["model_cooldowns"].get(candidate, 0.0) <= now
        ]

    if not available_candidates:
        logger.warning(f"[{requested_model}] [cooldown] [503]")
        return JSONResponse(
            status_code=503,
            content={
                "error": {
                    "message": f"All candidate models for '{requested_model}' are on 24-hour cooldown."
                }
            },
        )

    active_index = 0
    if len(candidates) > 1:
        for i, candidate in enumerate(candidates):
            if candidate in available_candidates:
                active_index = i
                break

        if active_index > 0 and (
            now - rotation_config["last_fallback_switch_time"] > 300
        ):
            primary_candidate = candidates[0]
            if primary_candidate in available_candidates:
                available_candidates.insert(0, primary_candidate)

    for candidate_model in available_candidates:
        if candidate_model not in MODEL_SETTINGS:
            if candidate_model == "qwen3.6":
                MODEL_SETTINGS[candidate_model] = {
                    "provider": "kaggle",
                    "base_url": KAGGLE_BASE_URL,
                    "keys_pool": ["test"],
                    "target_model": "qwen3.6",
                }
                logger.info(
                    f"Dynamically registered Kaggle settings for model '{candidate_model}' with URL: {KAGGLE_BASE_URL}"
                )
            elif (
                path.startswith("openrouter/")
                or "/" in candidate_model
                or candidate_model.endswith(":free")
            ):
                MODEL_SETTINGS[candidate_model] = {
                    "provider": "openrouter",
                    "base_url": "https://openrouter.ai/api/v1",
                    "keys_pool": OPENROUTER_KEYS,
                    "target_model": candidate_model,
                }
                logger.info(
                    f"Dynamically registered OpenRouter settings for model '{candidate_model}'"
                )
            elif path.startswith("mistral/"):
                MODEL_SETTINGS[candidate_model] = {
                    "provider": "mistral",
                    "base_url": "https://api.mistral.ai/v1",
                    "keys_pool": MISTRAL_KEYS,
                    "target_model": candidate_model,
                }
                logger.info(
                    f"Dynamically registered Mistral settings for model '{candidate_model}'"
                )
            elif path.startswith("llm7/"):
                MODEL_SETTINGS[candidate_model] = {
                    "provider": "llm7",
                    "base_url": "https://api.llm7.io/v1",
                    "keys_pool": LLM7_KEYS,
                    "target_model": candidate_model,
                }
                logger.info(
                    f"Dynamically registered LLM7 settings for model '{candidate_model}'"
                )
            elif path.startswith("ollama_cloud/"):
                MODEL_SETTINGS[candidate_model] = {
                    "provider": "ollama_cloud",
                    "base_url": "https://ollama.com/v1",
                    "keys_pool": OLLAMA_CLOUD_KEYS,
                    "target_model": candidate_model,
                }
                logger.info(
                    f"Dynamically registered Ollama Cloud settings for model '{candidate_model}'"
                )
            else:
                MODEL_SETTINGS[candidate_model] = {
                    "provider": "gemini",
                    "base_url": "https://generativelanguage.googleapis.com",
                    "keys_pool": API_KEYS,
                    "target_model": candidate_model,
                }
                logger.info(
                    f"Dynamically registered Gemini settings for model '{candidate_model}'"
                )

        model_settings = MODEL_SETTINGS[candidate_model]
        provider_name = model_settings["provider"]
        target_base_url = model_settings["base_url"]
        keys_pool = model_settings["keys_pool"]
        target_model_id = model_settings["target_model"]

        is_gemini_client = "generateContent" in path or "models/" in path
        needs_gemini_response_translation = False

        if provider_name == "gemini":
            target_path = path
            if "gemini-3.5-flash" in path and candidate_model != "gemini-3.5-flash":
                target_path = path.replace("gemini-3.5-flash", target_model_id)
            elif (
                "gemini-flash-lite-latest" in path
                and candidate_model != "gemini-flash-lite-latest"
            ):
                target_path = path.replace("gemini-flash-lite-latest", target_model_id)
            elif (
                "gemini-2.0-flash-lite" in path
                and candidate_model != "gemini-flash-lite-latest"
            ):
                target_path = path.replace("gemini-2.0-flash-lite", target_model_id)
        else:
            if is_gemini_client:
                target_path = "chat/completions"
                needs_gemini_response_translation = True
            else:
                if path.startswith("openrouter/"):
                    target_path = path[11:]
                elif path.startswith("mistral/"):
                    target_path = path[8:]
                elif path.startswith("llm7/"):
                    target_path = path[5:]
                elif path.startswith("ollama_cloud/"):
                    target_path = path[13:]
                else:
                    target_path = path

                # Strip v1beta/ or v1/ prefix if present
                if target_path.startswith("v1beta/"):
                    target_path = target_path[7:]
                elif target_path.startswith("v1/"):
                    target_path = target_path[3:]

                # Strip duplicate 'v1/' prefix if the base URL ends with 'v1'
                if target_path.startswith("v1/") and (
                    target_base_url.endswith("/v1") or target_base_url.endswith("/v1/")
                ):
                    target_path = target_path[3:]

        target_url = f"{target_base_url}/{target_path}"

        if not keys_pool:
            logger.warning(
                f"No keys available for model '{candidate_model}' (provider: '{provider_name}')"
            )
            continue

        available_keys = [k for k in keys_pool if COOLDOWNS.get(k, 0.0) < now]

        if not available_keys:
            logger.warning(
                f"[{provider_name}] All keys for model '{candidate_model}' are on cooldown. Rotating model."
            )
            continue
        else:
            available_keys = sorted(available_keys, key=lambda k: LAST_USED.get(k, 0.0))

        # Distribute keys across parallel channels to ensure different channels use different keys
        if parallelism_enabled and len(available_keys) > 1:
            key_idx = current_vpn_index % len(available_keys)
            selected_key = available_keys[key_idx]
            available_keys.remove(selected_key)
            available_keys.insert(0, selected_key)

        max_attempts = len(available_keys)
        model_success = False
        consecutive_503s = 0

        for attempt, api_key in enumerate(available_keys, start=1):
            if attempt > 1 and await request.is_disconnected():
                logger.warning(
                    f"[{provider_name}] Client disconnected during key search for model '{candidate_model}'. Aborting."
                )
                break

            current_config = load_rotation_config()
            current_force_model = current_config.get("force_model", {})
            if (
                requested_model in THINKING_MODELS
                or requested_model == "gemini-3.5-flash"
            ):
                current_forced_model = current_force_model.get(
                    "gemini-3.5-flash", "auto"
                )
            elif (
                requested_model in QUICK_MODELS
                or requested_model == "gemini-flash-lite-latest"
            ):
                current_forced_model = current_force_model.get(
                    "gemini-flash-lite-latest", "auto"
                )
            else:
                current_forced_model = current_force_model.get(requested_model, "auto")

            if current_forced_model != forced_model:
                logger.info(
                    f"[{provider_name}] Manual model switch detected during 429 retry sequence: '{forced_model}' -> '{current_forced_model}'. Restarting routing."
                )
                return "RESTART"

            key_index = keys_pool.index(api_key) + 1

            headers = {
                k: v
                for k, v in request.headers.items()
                if k.lower()
                not in (
                    "host",
                    "content-length",
                    "content-encoding",
                    "accept-encoding",
                    "authorization",
                    "x-goog-api-key",
                    "x-api-key",
                )
            }

            if provider_name in ("openrouter", "mistral", "llm7", "ollama_cloud"):
                headers["authorization"] = f"Bearer {api_key}"
            else:
                headers["x-goog-api-key"] = api_key

            request_body = body
            if provider_name in ("openrouter", "mistral", "llm7", "ollama_cloud"):
                try:
                    body_dict = json.loads(body)
                    translated_body = translate_payload_to_openai(
                        body_dict, target_model_id
                    )
                    request_body = json.dumps(translated_body).encode("utf-8")
                except Exception as e:
                    logger.warning(
                        f"Failed to translate payload for OpenAI format: {e}"
                    )

            current_query_params = {
                k: v for k, v in query_params.items() if k.lower() != "key"
            }

            try:
                # Resolve and rotate VPN client on demand
                try:
                    rotation_config = load_rotation_config()
                    vpn_mode = rotation_config.get("vpn_switching_mode", "disabled")
                    vpn_static = int(rotation_config.get("vpn_static_channel", 0))

                    if vpn_mode == "every_request":
                        await rotate_vpn_on_the_fly("every_request mode trigger")

                    # Pick the appropriate client (either default, static, or active rotating index)
                    client = get_active_vpn_client(
                        request, vpn_mode, vpn_static, current_vpn_index
                    )
                except Exception as ve:
                    logger.error(f"[VPN] Error during client resolution: {ve}")
                    client = request.app.state.vpn_clients[0]  # Safe fallback

                req = client.build_request(
                    method=request.method,
                    url=target_url,
                    headers=headers,
                    params=current_query_params,
                    content=request_body
                    if request.method in ("POST", "PUT", "PATCH")
                    else None,
                )

                LAST_USED[api_key] = time.time()
                response = await client.send(req, stream=True)

                if response.status_code == 200:
                    VPN_CONSECUTIVE_ERRORS = (
                        0  # Reset consecutive error counter on success!
                    )

                    rotation_config["consecutive_model_failures"][candidate_model] = 0
                    CONSECUTIVE_429S[provider_name] = 0
                    CONSECUTIVE_RPD_429S[api_key] = 0  # Reset on success!

                    current_active_index = (
                        candidates.index(candidate_model)
                        if candidate_model in candidates
                        else -1
                    )
                    if current_active_index < active_index:
                        rotation_config["last_fallback_switch_time"] = time.time()
                        save_rotation_config(rotation_config)
                        logger.info(
                            f"Successfully recovered to higher-priority model: {candidate_model}"
                        )

                    model_success = True
                    remove_key_from_error_log(candidate_model, api_key)

                    # Custom single-line completion log!
                    logger.info(
                        f"[{candidate_model}] [key#{key_index}-{api_key[-4:]}] [200]"
                    )

                    response_headers = {
                        k: v
                        for k, v in response.headers.items()
                        if k.lower() not in EXCLUDED_HEADERS
                    }

                    req_messages = []
                    if SAVE_CHAT_LOGS:
                        req_messages = extract_chat_messages(body)

                    response_text_buffer = []
                    raw_chunks_buffer = []

                    async def stream_generator():
                        try:
                            logger.info(
                                f"[{candidate_model}] Starting stream transmission..."
                            )

                            async def iter_bytes():
                                try:
                                    async for chunk in response.aiter_bytes():
                                        if SAVE_CHAT_LOGS:
                                            raw_chunks_buffer.append(chunk)
                                        yield chunk
                                except (httpx.ReadError, httpx.HTTPError) as he:
                                    logger.error(
                                        f"[{candidate_model}] Upstream stream read error (abrupt disconnect or timeout): {he}"
                                    )
                                    raise  # Propagate to prevent silent 200 OK on failure
                                except asyncio.CancelledError:
                                    logger.warning(
                                        f"[{candidate_model}] Stream transmission cancelled by client (OpenCode disconnected)."
                                    )
                                    raise
                                except Exception as se:
                                    logger.error(
                                        f"[{candidate_model}] Unexpected stream exception: {se}"
                                    )
                                    raise

                            async def iter_translated_chunks():
                                async for chunk in iter_bytes():
                                    chunk_str = ""
                                    if (
                                        SAVE_CHAT_LOGS
                                        or needs_gemini_response_translation
                                    ):
                                        try:
                                            chunk_str = chunk.decode(
                                                "utf-8", errors="ignore"
                                            )
                                        except Exception:
                                            pass

                                    if SAVE_CHAT_LOGS and chunk_str:
                                        try:
                                            text_part = extract_text_from_chunk(
                                                chunk_str, provider_name
                                            )
                                            if text_part:
                                                response_text_buffer.append(text_part)
                                        except Exception as ce:
                                            logger.debug(
                                                f"Error extracting text from chunk: {ce}"
                                            )

                                    if needs_gemini_response_translation and chunk_str:
                                        try:
                                            translated_lines = []
                                            for line in chunk_str.split("\n"):
                                                line_stripped = line.strip()
                                                if line_stripped:
                                                    translated_line = translate_openai_chunk_to_gemini(
                                                        line_stripped
                                                    )
                                                    translated_lines.append(
                                                        translated_line
                                                    )
                                                else:
                                                    translated_lines.append(line)
                                            translated_chunk = "\n".join(
                                                translated_lines
                                            )
                                            yield translated_chunk.encode("utf-8")
                                        except Exception as te:
                                            logger.debug(
                                                f"Failed to translate response chunk: {te}"
                                            )
                                            yield chunk
                                    else:
                                        yield chunk

                            async for trans_chunk in iter_translated_chunks():
                                yield trans_chunk

                            logger.info(
                                f"[{candidate_model}] Stream transmission completed successfully. Total chunks: {len(raw_chunks_buffer)}"
                            )
                        except asyncio.CancelledError:
                            logger.warning(
                                f"[{candidate_model}] Stream generator task cancelled."
                            )
                            raise
                        except Exception as e:
                            logger.error(
                                f"[{candidate_model}] Stream generator encountered an error: {e}"
                            )
                            raise
                        finally:
                            await response.aclose()
                            if SAVE_CHAT_LOGS:
                                response_text = "".join(response_text_buffer)
                                raw_req_bytes = body
                                raw_resp_bytes = b"".join(raw_chunks_buffer)
                                asyncio.create_task(
                                    write_chat_log(
                                        model=candidate_model,
                                        provider=provider_name,
                                        messages=req_messages,
                                        response=response_text,
                                        session_id=session_id,
                                        raw_request=raw_req_bytes,
                                        raw_response=raw_resp_bytes,
                                    )
                                )

                    return StreamingResponse(
                        stream_generator(),
                        status_code=response.status_code,
                        headers=response_headers,
                    )
                else:
                    # For any non-200 status code, read the full response body without truncation
                    try:
                        await response.aread()
                        resp_text = response.text
                    except Exception as re:
                        resp_text = f"<Failed to read response body: {re}>"
                    await response.aclose()

                    if response.status_code == 429:
                        if parallelism_enabled:
                            failed_channel = ACTIVE_SLOTS[slot_idx]
                            if BACKUP_POOL:
                                new_channel = BACKUP_POOL.pop(0)
                                ACTIVE_SLOTS[slot_idx] = new_channel
                                BACKUP_POOL.append(failed_channel)
                                logger.info(
                                    f"[Parallelism] Slot {slot_idx} rotated: Channel {failed_channel} -> Channel {new_channel}"
                                )

                        consecutive_429 = CONSECUTIVE_429S.get(provider_name, 0) + 1
                        CONSECUTIVE_429S[provider_name] = consecutive_429

                        # VPN Integration: Track consecutive 429 errors
                        VPN_CONSECUTIVE_ERRORS += 1

                        rotation_config = load_rotation_config()
                        vpn_mode = rotation_config.get("vpn_switching_mode", "disabled")
                        vpn_threshold = int(
                            rotation_config.get("vpn_errors_threshold", 5)
                        )

                        if (
                            VPN_ANY_TUNNEL_ACTIVE
                            and vpn_mode == "error_threshold"
                            and VPN_CONSECUTIVE_ERRORS >= vpn_threshold
                        ):
                            logger.warning(
                                f"[VPN] Error threshold reached ({VPN_CONSECUTIVE_ERRORS}/{vpn_threshold}). Rotating VPN immediately..."
                            )
                            await rotate_vpn_on_the_fly("429 error threshold")
                            VPN_CONSECUTIVE_ERRORS = 0
                            # Immediately retry without sleeping
                            continue

                        if vpn_mode == "disabled" and VPN_CONSECUTIVE_ERRORS >= 5:
                            pause_sleep = float(
                                rotation_config.get("vpn_disabled_pause_sleep", 65.0)
                            )
                            logger.warning(
                                f"[VPN] Consecutive 429 errors reached 5 in Disabled mode. Sleep {pause_sleep}s pause..."
                            )
                            await asyncio.sleep(pause_sleep)
                            VPN_CONSECUTIVE_ERRORS = 0
                            continue

                        now_ts = time.time()
                        prev_429_ts = LAST_429_TIME.get(api_key, 0.0)
                        LAST_429_TIME[api_key] = now_ts

                        cooldown_duration = float(
                            rotation_config.get("key_cooldown_duration", 90)
                        )

                        if prev_429_ts > 0.0:
                            time_diff = now_ts - prev_429_ts
                            if time_diff > 300.0:
                                rpd_consec = CONSECUTIVE_RPD_429S.get(api_key, 0) + 1
                                CONSECUTIVE_RPD_429S[api_key] = rpd_consec
                                if rpd_consec >= 3:  # Increased threshold to 3!
                                    if provider_name == "gemini":
                                        cooldown_duration = seconds_until_rpd_reset()
                                        logger.error(
                                            f"[{provider_name}] Key #{key_index} RPD limit. Wait {cooldown_duration / 3600:.1f}h"
                                        )
                                    else:
                                        cooldown_duration = 86400.0
                                        logger.error(
                                            f"[{provider_name}] Key #{key_index} daily limit. Wait 24h"
                                        )
                                    CONSECUTIVE_RPD_429S[api_key] = 0
                            else:
                                pass
                        else:
                            CONSECUTIVE_RPD_429S[api_key] = 1

                        mark_cooldown(api_key, duration=cooldown_duration)

                        logger.warning(
                            f"[{provider_name}] Key #{key_index} 429 ({candidate_model}) on {request.method} {target_url}. Error: {resp_text}. Cooldown {cooldown_duration:.1f}s. Attempt {attempt}/{max_attempts}"
                        )

                        # Exponential retry sleep: 1, 2, 4, 8, 16, then 65s
                        if consecutive_429 == 1:
                            retry_sleep = 1.0
                        elif consecutive_429 == 2:
                            retry_sleep = 2.0
                        elif consecutive_429 == 3:
                            retry_sleep = 4.0
                        elif consecutive_429 == 4:
                            retry_sleep = 8.0
                        elif consecutive_429 == 5:
                            retry_sleep = 16.0
                        else:
                            retry_sleep = float(
                                rotation_config.get("max_exponential_sleep", 65.0)
                            )

                        logger.info(f"[{provider_name}] Sleeping {retry_sleep:.2f}s...")
                        await asyncio.sleep(retry_sleep)
                        continue
                    elif response.status_code == 403:
                        mark_cooldown(api_key, duration=86400.0)
                        error_msg = f"HTTP 403 Forbidden: {resp_text}"
                        log_non_429_error(candidate_model, api_key, error_msg)
                        logger.error(
                            f"[{provider_name}] Key #{key_index} 403 ({candidate_model}) on {request.method} {target_url}. Error: {resp_text}. Cooldown 24h"
                        )
                        continue
                    elif response.status_code == 503:
                        mark_cooldown(api_key, duration=10.0)
                        error_msg = f"HTTP 503 Service Unavailable: {resp_text}"
                        log_non_429_error(candidate_model, api_key, error_msg)

                        consecutive_503s += 1
                        logger.error(
                            f"[{provider_name}] Key #{key_index} HTTP 503 ({candidate_model}) on {request.method} {target_url}. Error: {resp_text}. Consecutive 503s: {consecutive_503s}/10"
                        )

                        if consecutive_503s >= 10:
                            logger.error(
                                f"[{provider_name}] Hit 10 consecutive 503s for model '{candidate_model}'. Forcing provider switch!"
                            )
                            break  # Break out of the key loop to switch candidate model (change provider)

                        if consecutive_503s >= 3:
                            logger.info(
                                f"[{provider_name}] 3+ consecutive 503s. Sleeping 60s before trying next key..."
                            )
                            await asyncio.sleep(60.0)
                        continue
                    elif response.status_code in (500, 502):
                        mark_cooldown(api_key, duration=10.0)
                        error_msg = (
                            f"HTTP {response.status_code} Server Error: {resp_text}"
                        )
                        log_non_429_error(candidate_model, api_key, error_msg)
                        logger.error(
                            f"[{provider_name}] Key #{key_index} HTTP {response.status_code} ({candidate_model}) on {request.method} {target_url}. Error: {resp_text}"
                        )
                        continue
                    else:
                        error_msg = f"HTTP {response.status_code} Unexpected Status: {resp_text}"
                        log_non_429_error(candidate_model, api_key, error_msg)
                        logger.warning(
                            f"[{provider_name}] Key #{key_index} HTTP {response.status_code} ({candidate_model}) on {request.method} {target_url}. Error: {resp_text}"
                        )
                        continue

            except Exception as e:
                logger.error(
                    f"[{provider_name}] Key #{key_index} conn error ({candidate_model}) on {request.method} {target_url}: {e}"
                )
                log_non_429_error(candidate_model, api_key, str(e))
                mark_cooldown(api_key, duration=10.0)

                # VPN Integration: Track consecutive connection errors / timeouts
                try:
                    if VPN_ANY_TUNNEL_ACTIVE:
                        VPN_CONSECUTIVE_ERRORS += 1

                        rotation_config = load_rotation_config()
                        vpn_mode = rotation_config.get("vpn_switching_mode", "disabled")
                        vpn_threshold = int(
                            rotation_config.get("vpn_errors_threshold", 5)
                        )

                        if (
                            vpn_mode == "error_threshold"
                            and VPN_CONSECUTIVE_ERRORS >= vpn_threshold
                        ):
                            logger.warning(
                                f"[VPN] Connection error threshold reached ({VPN_CONSECUTIVE_ERRORS}/{vpn_threshold}). Rotating VPN immediately..."
                            )
                            await rotate_vpn_on_the_fly(
                                "network error/timeout threshold"
                            )
                            VPN_CONSECUTIVE_ERRORS = 0
                            # Immediately retry the failed request
                            continue
                except Exception as ve:
                    logger.error(
                        f"[VPN] Error in network exception rotation handling: {ve}"
                    )

                continue

        if not model_success:
            rotation_config["model_cooldowns"][candidate_model] = now + 86400.0
            rotation_config["consecutive_model_failures"][candidate_model] = 0

            current_index = (
                candidates.index(candidate_model)
                if candidate_model in candidates
                else -1
            )
            next_index = (current_index + 1) % len(candidates)
            rotation_config["last_fallback_switch_time"] = now

            save_rotation_config(rotation_config)
            logger.warning(f"Model '{candidate_model}' failed. Cooldown 24h")

    logger.error(f"[{requested_model}] [all-keys-failed] [503]")
    return JSONResponse(
        status_code=503,
        content={
            "error": {
                "message": f"All candidate models for '{requested_model}' failed or are unavailable."
            }
        },
    )
