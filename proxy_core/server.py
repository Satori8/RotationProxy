import time
import json
import re
import random
import asyncio
import traceback
import logging
import datetime
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx

from proxy_core import logger as core_logger
from proxy_core.logger import PlainFormatter
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
    OPENCODE_KEYS,
    seconds_until_rpd_reset,
    log_non_429_error,
    remove_key_from_error_log,
    wait_for_adapter_and_add_route,
    restart_vpn_service,
)
from proxy_core.state import log_queue as global_log_queue
from proxy_core.helpers import (
    truncate_thought_signature,
    beautify_json_string,
    get_session_id,
    get_requested_model,
    extract_chat_messages,
    extract_text_from_chunk,
    extract_token_usage,
    get_next_log_index,
    write_chat_log,
    translate_payload_to_openai,
    translate_openai_chunk_to_gemini,
    add_anomaly_to_state,
)

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


def format_error_message(resp_text: str) -> str:
    if not resp_text:
        return ""
    resp_text = resp_text.strip()
    if not (resp_text.startswith("{") and resp_text.endswith("}")):
        return " ".join(resp_text.splitlines())
    try:
        import json

        data = json.loads(resp_text)
        if "error" in data:
            err = data["error"]
            if isinstance(err, dict):
                code = err.get("code")
                status = err.get("status")
                message = err.get("message")
                parts = []
                if code is not None:
                    parts.append(f"code: {code}")
                if status is not None:
                    parts.append(f"status: {status}")
                if message is not None:
                    parts.append(f"message: {message}")
                if parts:
                    return ", ".join(parts)
            elif isinstance(err, str):
                return f"error: {err}"
        return json.dumps(data, ensure_ascii=False)
    except Exception:
        return " ".join(resp_text.splitlines())


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
RUNNING_VPN_CHANNELS = set(range(1, 7))


async def vpn_heartbeat_loop(app):
    """Background task that checks the health of all 6 VPN channels every 1.0s."""
    import time
    import asyncio
    import subprocess

    logger.info(
        "[Heartbeat] Waiting 60 seconds for VPN adapters to initialize before starting health checks..."
    )
    await asyncio.sleep(60.0)

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

        # Check if system vpn is active from config
        try:
            from proxy_core.config import load_rotation_config

            cfg = load_rotation_config()
            system_vpn_active = cfg.get("system_vpn_active", False)
            system_vpn_index = cfg.get("system_vpn_index", 1)
        except Exception:
            system_vpn_active = False
            system_vpn_index = 1

        for i in range(1, 7):
            # Skip if service is not running
            if i not in running_services:
                # Reset failures if service is stopped/not installed
                VPN_CONSECUTIVE_FAILURES[i] = 0
                continue

            # If system VPN is active, skip checks for all other tunnels to prevent false-offline status
            if system_vpn_active and i != system_vpn_index:
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
                if VPN_CONSECUTIVE_FAILURES[i] >= 5:
                    logger.error(
                        f"[Heartbeat] VPN {i} down for 5s. Triggering service restart..."
                    )
                    VPN_CONSECUTIVE_FAILURES[i] = 0
                    VPN_GRACE_PERIODS[i] = now + 15.0  # 15s grace period

                    # Restart service in background thread
                    await asyncio.to_thread(restart_vpn_service, i)

        # Update RUNNING_VPN_CHANNELS based on latest check results
        global RUNNING_VPN_CHANNELS
        healthy_channels = set()
        for idx in running_services:
            if VPN_CONSECUTIVE_FAILURES[idx] < 3:
                healthy_channels.add(idx)
        RUNNING_VPN_CHANNELS = healthy_channels


class QueueLogHandler(logging.Handler):
    def emit(self, record):
        try:
            global_log_queue.put(self.format(record))
        except Exception:
            pass


queue_handler = QueueLogHandler()
queue_handler.setFormatter(PlainFormatter("%(asctime)s [%(levelname)s] %(message)s"))
logger.addHandler(queue_handler)

RECENT_ERROR_TIMESTAMPS = []


def track_and_check_safety_limit():
    global RECENT_ERROR_TIMESTAMPS
    now = time.time()
    RECENT_ERROR_TIMESTAMPS.append(now)
    # Keep only errors from the last 2.0 seconds
    RECENT_ERROR_TIMESTAMPS = [t for t in RECENT_ERROR_TIMESTAMPS if now - t <= 2.0]

    if len(RECENT_ERROR_TIMESTAMPS) > 3:
        # Massive, highly visible warning message
        banner = (
            "\n" + "=" * 80 + "\n"
            "!!! CRITICAL SAFETY STOP TRIGGERED !!!\n"
            "More than 3 model/server errors occurred within 2.0 seconds!\n"
            f"Error timestamps in window: {[datetime.datetime.fromtimestamp(t).strftime('%H:%M:%S.%f')[:-3] for t in RECENT_ERROR_TIMESTAMPS]}\n"
            "Something is seriously wrong (e.g., network down, invalid keys, or API block).\n"
            "ABORTING CURRENT REQUEST TO PREVENT INFINITE ERROR LOOPS...\n"
            + "=" * 80
            + "\n"
        )

        logger.critical(banner)
        global_log_queue.put(banner)

        raise RuntimeError(
            "CRITICAL SAFETY STOP: High error rate detected. Aborting current request."
        )


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


async def analyze_response_for_anomalies(
    raw_response: bytes, response_text: str, model: str, provider: str
):
    try:
        if not raw_response:
            logger.warning(
                f"[{model}] [Anomaly] Response is completely empty (0 bytes)."
            )
            add_anomaly_to_state(model, "Response is completely empty (0 bytes).")
            return

        # Parse chunks to extract finish reasons and check JSON validity
        finish_reasons = set()
        has_valid_json = False
        has_data_lines = False
        has_tool_calls = False

        lines = raw_response.decode("utf-8", errors="ignore").split("\n")
        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Handle SSE data: prefix
            if line.startswith("data:"):
                has_data_lines = True
                data_content = line[5:].strip()
                if data_content == "[DONE]":
                    continue
                try:
                    data = json.loads(data_content)
                    has_valid_json = True

                    # Check Gemini format
                    candidates = data.get("candidates", [])
                    for cand in candidates:
                        fr = cand.get("finishReason")
                        if fr:
                            finish_reasons.add(str(fr).upper())
                        content = cand.get("content", {})
                        parts = content.get("parts", [])
                        for part in parts:
                            if isinstance(part, dict) and (
                                "functionCall" in part or "functionCalls" in part
                            ):
                                has_tool_calls = True

                    # Check OpenAI format
                    choices = data.get("choices", [])
                    for choice in choices:
                        fr = choice.get("finish_reason")
                        if fr:
                            finish_reasons.add(str(fr).upper())
                        delta = choice.get("delta", {})
                        if "tool_calls" in delta or "tool_calls" in choice:
                            has_tool_calls = True
                except Exception:
                    pass
            else:
                # If it's not SSE, try to parse the whole thing as a single JSON
                if not has_data_lines:
                    try:
                        data = json.loads(line)
                        has_valid_json = True
                        candidates = data.get("candidates", [])
                        for cand in candidates:
                            fr = cand.get("finishReason")
                            if fr:
                                finish_reasons.add(str(fr).upper())
                            content = cand.get("content", {})
                            parts = content.get("parts", [])
                            for part in parts:
                                if isinstance(part, dict) and (
                                    "functionCall" in part or "functionCalls" in part
                                ):
                                    has_tool_calls = True
                        choices = data.get("choices", [])
                        for choice in choices:
                            fr = choice.get("finish_reason")
                            if fr:
                                finish_reasons.add(str(fr).upper())
                            delta = choice.get("delta", {})
                            if "tool_calls" in delta or "tool_calls" in choice:
                                has_tool_calls = True
                    except Exception:
                        pass

        # Check if accumulated text is empty (only if there are no tool calls)
        if not response_text or not response_text.strip():
            if not has_tool_calls:
                msg = (
                    f"Response text is empty or only whitespace (Provider: {provider})."
                )
                logger.warning(f"[{model}] [Anomaly] {msg}")
                add_anomaly_to_state(model, msg)

        # Check for finishReason anomalies
        for fr in finish_reasons:
            if fr not in ("STOP", "NONE", "TOOL_CALLS", "TOOL_CALL"):
                msg = f"Stream finished with non-standard reason: '{fr}' (Provider: {provider})"
                logger.warning(f"[{model}] [Anomaly] {msg}")
                logger.warning(
                    f"[{model}] [Anomaly Raw Response] {truncate_thought_signature(raw_response.decode('utf-8', errors='ignore'))}"
                )
                add_anomaly_to_state(model, msg)

        # Check for format anomalies
        if has_data_lines and not has_valid_json:
            msg = "Received SSE stream but failed to parse any valid JSON chunks."
            logger.warning(f"[{model}] [Anomaly] {msg}")
            add_anomaly_to_state(model, msg)
        elif not has_data_lines and not has_valid_json:
            msg = f"Response is not valid JSON and not an SSE stream. Raw: {raw_response[:200]}"
            logger.warning(f"[{model}] [Anomaly] {msg}")
            add_anomaly_to_state(model, msg)

    except Exception as e:
        logger.error(f"Error during response anomaly analysis: {e}")


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
    elif provider_name == "opencode_zen":
        base_url = "https://opencode.ai/zen/v1"
        keys_pool = OPENCODE_KEYS
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
    if provider_name in (
        "openrouter",
        "mistral",
        "llm7",
        "ollama",
        "ollama_cloud",
        "opencode_zen",
    ):
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
    if vpn_mode == "disabled":
        actual_vpn_index = vpn_static if 0 < vpn_static <= 6 else 0
    else:
        actual_vpn_index = current_vpn_index if VPN_ANY_TUNNEL_ACTIVE else 0
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
            resp_text = truncate_thought_signature(resp.text)
        except Exception:
            resp_text = "(failed to read response text)"
        await resp.aclose()

        latency_ms = int((time.perf_counter() - start_time) * 1000)
        beautified_body = beautify_json_string(resp_text)
        formatted_error = format_error_message(resp_text)
        logger.info(
            f"[Test Model] [vpn#{actual_vpn_index}] Upstream status: {status_code}, latency: {latency_ms}ms, body:\n{beautified_body}"
        )

        if status_code == 200:
            return {
                "status": "ok",
                "message": "Model responded successfully!",
                "latency_ms": latency_ms,
            }
        elif status_code == 429:
            logger.error(
                f"[Test Model] [vpn#{actual_vpn_index}] Rate limit exceeded (429): {formatted_error}"
            )
            return {
                "status": "rate_limited",
                "message": f"Rate limit exceeded (429): {formatted_error}",
                "latency_ms": latency_ms,
            }
        elif status_code == 404:
            logger.error(
                f"[Test Model] [vpn#{actual_vpn_index}] Model not found (404): {formatted_error}"
            )
            return {
                "status": "not_found",
                "message": f"Model not found (404): {formatted_error}",
                "latency_ms": latency_ms,
            }
        else:
            logger.error(
                f"[Test Model] [vpn#{actual_vpn_index}] Server returned status {status_code}: {formatted_error}"
            )
            return {
                "status": "error",
                "message": f"Server returned status {status_code}: {formatted_error}",
                "latency_ms": latency_ms,
            }
    except Exception as e:
        latency_ms = int((time.perf_counter() - start_time) * 1000)
        logger.error(
            f"[Test Model] [vpn#{actual_vpn_index}] Network/Connection error on testing '{model_id}' via '{provider_name}' to {url}: {e}"
        )
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


@app.get("/control/stats")
async def get_control_stats():
    from proxy_core import state

    return {
        "compactor_orig_bytes": getattr(state, "COMPACTOR_ORIG_BYTES", 0),
        "compactor_comp_bytes": getattr(state, "COMPACTOR_COMP_BYTES", 0),
        "compactor_orig_tokens": getattr(state, "COMPACTOR_ORIG_TOKENS", 0),
        "compactor_comp_tokens": getattr(state, "COMPACTOR_COMP_TOKENS", 0),
        "compactor_saved_tools": getattr(state, "COMPACTOR_SAVED_TOOLS", 0),
        "compactor_saved_superpowers": getattr(state, "COMPACTOR_SAVED_SUPERPOWERS", 0),
        "compactor_saved_skills": getattr(state, "COMPACTOR_SAVED_SKILLS", 0),
        "compactor_saved_devctx": getattr(state, "COMPACTOR_SAVED_DEVCTX", 0),
        "compactor_saved_generic_read": getattr(
            state, "COMPACTOR_SAVED_GENERIC_READ", 0
        ),
        "compactor_saved_reminders": getattr(state, "COMPACTOR_SAVED_REMINDERS", 0),
        "compactor_injections_count": getattr(state, "COMPACTOR_INJECTIONS_COUNT", 0),
        "anomalies": getattr(state, "RECENT_ANOMALIES", []),
    }


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
    request_received_time = time.perf_counter()
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

            payload_dict = json.loads(body_str, strict=False)
            compacted_dict = process_request_payload(payload_dict, rotation_config)
            body = json.dumps(
                compacted_dict, ensure_ascii=False, separators=(",", ":")
            ).encode("utf-8")
        except Exception as ce:
            logger.error(f"[Compactor] Failed to compact context: {ce}")

    explicit_provider = None
    if path.startswith("openrouter/"):
        target_base = "https://openrouter.ai/api/v1"
        current_path = path[11:]
        keys_pool = OPENROUTER_KEYS
        provider_name = "openrouter"
        explicit_provider = "openrouter"
    elif path.startswith("mistral/"):
        target_base = "https://api.mistral.ai/v1"
        current_path = path[8:]
        keys_pool = MISTRAL_KEYS
        provider_name = "mistral"
        explicit_provider = "mistral"
    elif path.startswith("llm7/"):
        target_base = "https://api.llm7.io/v1"
        current_path = path[5:]
        keys_pool = LLM7_KEYS
        provider_name = "llm7"
        explicit_provider = "llm7"
    elif path.startswith("ollama_cloud/"):
        target_base = "https://ollama.com/v1"
        current_path = path[13:]
        keys_pool = OLLAMA_CLOUD_KEYS
        provider_name = "ollama_cloud"
        explicit_provider = "ollama_cloud"
    elif path.startswith("ollama/"):
        target_base = "https://ollama.com/v1"
        current_path = path[7:]
        keys_pool = OLLAMA_CLOUD_KEYS
        provider_name = "ollama_cloud"
        explicit_provider = "ollama_cloud"
    elif path.startswith("opencode_zen/"):
        target_base = "https://opencode.ai/zen/v1"
        current_path = path[13:]
        keys_pool = OPENCODE_KEYS
        provider_name = "opencode_zen"
        explicit_provider = "opencode_zen"
    elif path.startswith("opencode/"):
        target_base = "https://opencode.ai/zen/v1"
        current_path = path[9:]
        keys_pool = OPENCODE_KEYS
        provider_name = "opencode_zen"
        explicit_provider = "opencode_zen"
    else:
        target_base = TARGET_BASE_URL
        current_path = path
        keys_pool = API_KEYS
        provider_name = "gemini"

    rotation_config = load_rotation_config()
    parallelism_enabled = rotation_config.get("parallelism_enabled", False)
    parallel_count = rotation_config.get("parallel_tunnels_count", 3)
    per_channel_delay = rotation_config.get("per_channel_delay", 0.5)

    # Dynamically adjust active slots and backup pool size based on running VPN channels
    available_channels = [0] + sorted(list(RUNNING_VPN_CHANNELS))
    # Ensure parallel_count doesn't exceed available channels
    actual_parallel_count = min(parallel_count, len(available_channels))
    if actual_parallel_count < 1:
        actual_parallel_count = 1

    # Re-initialize ACTIVE_SLOTS and BACKUP_POOL if available channels changed or count changed
    current_pool_set = set(ACTIVE_SLOTS).union(set(BACKUP_POOL))
    if (
        current_pool_set != set(available_channels)
        or len(ACTIVE_SLOTS) != actual_parallel_count
    ):
        ACTIVE_SLOTS = available_channels[:actual_parallel_count]
        BACKUP_POOL = available_channels[actual_parallel_count:]
        logger.info(
            f"[Parallelism] Re-initialized pools: ACTIVE_SLOTS={ACTIVE_SLOTS}, BACKUP_POOL={BACKUP_POOL}"
        )

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

    actual_vpn_index = current_vpn_index

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

    enable_model_rotation = rotation_config.get("enable_model_rotation", False)
    if enable_model_rotation:
        candidates = rotation_config["rotation_lists"].get(
            requested_model, [requested_model]
        )
    else:
        candidates = [requested_model]
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
    elif not enable_model_rotation:
        available_candidates = candidates  # bypass cooldowns when rotation is disabled
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
            elif candidate_model.startswith("opencode/") or candidate_model.startswith(
                "opencode_zen/"
            ):
                target_model = (
                    candidate_model[9:]
                    if candidate_model.startswith("opencode/")
                    else candidate_model[13:]
                )
                MODEL_SETTINGS[candidate_model] = {
                    "provider": "opencode_zen",
                    "base_url": "https://opencode.ai/zen/v1",
                    "keys_pool": OPENCODE_KEYS,
                    "target_model": target_model,
                }
                logger.info(
                    f"Dynamically registered OpenCode Zen settings for model '{candidate_model}' with target model '{target_model}'"
                )
            elif candidate_model.startswith("ollama/") or candidate_model.startswith(
                "ollama_cloud/"
            ):
                target_model = (
                    candidate_model[7:]
                    if candidate_model.startswith("ollama/")
                    else candidate_model[13:]
                )
                MODEL_SETTINGS[candidate_model] = {
                    "provider": "ollama_cloud",
                    "base_url": "https://ollama.com/v1",
                    "keys_pool": OLLAMA_CLOUD_KEYS,
                    "target_model": target_model,
                }
                logger.info(
                    f"Dynamically registered Ollama Cloud settings for model '{candidate_model}' with target model '{target_model}'"
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
            elif path.startswith("ollama_cloud/") or path.startswith("ollama/"):
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

        if explicit_provider == "openrouter":
            model_settings = {
                "provider": "openrouter",
                "base_url": "https://openrouter.ai/api/v1",
                "keys_pool": OPENROUTER_KEYS,
                "target_model": candidate_model,
            }
        elif explicit_provider == "mistral":
            model_settings = {
                "provider": "mistral",
                "base_url": "https://api.mistral.ai/v1",
                "keys_pool": MISTRAL_KEYS,
                "target_model": candidate_model,
            }
        elif explicit_provider == "llm7":
            model_settings = {
                "provider": "llm7",
                "base_url": "https://api.llm7.io/v1",
                "keys_pool": LLM7_KEYS,
                "target_model": candidate_model,
            }
        elif explicit_provider == "ollama_cloud":
            model_settings = {
                "provider": "ollama_cloud",
                "base_url": "https://ollama.com/v1",
                "keys_pool": OLLAMA_CLOUD_KEYS,
                "target_model": candidate_model,
            }
        elif explicit_provider == "opencode_zen":
            model_settings = {
                "provider": "opencode_zen",
                "base_url": "https://opencode.ai/zen/v1",
                "keys_pool": OPENCODE_KEYS,
                "target_model": candidate_model,
            }
        else:
            model_settings = MODEL_SETTINGS[candidate_model]

        provider_name = model_settings["provider"]
        target_base_url = model_settings["base_url"]
        keys_pool = model_settings["keys_pool"]
        target_model_id = model_settings["target_model"]

        is_gemini_client = "generateContent" in path or "models/" in path
        is_streaming_request = (
            "streamGenerateContent" in path
            or "serverSentEvents" in path
            or query_params.get("alt") == "sse"
        )
        if not is_streaming_request and body:
            try:
                body_dict = json.loads(body)
                if body_dict.get("stream") is True:
                    is_streaming_request = True
            except Exception:
                pass
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
                elif path.startswith("ollama/"):
                    target_path = path[7:]
                elif path.startswith("opencode/"):
                    target_path = path[9:]
                elif path.startswith("opencode_zen/"):
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

            if provider_name in (
                "openrouter",
                "mistral",
                "llm7",
                "ollama_cloud",
                "opencode_zen",
            ):
                headers["authorization"] = f"Bearer {api_key}"
            else:
                headers["x-goog-api-key"] = api_key

            request_body = body
            if provider_name in (
                "openrouter",
                "mistral",
                "llm7",
                "ollama_cloud",
                "opencode_zen",
            ):
                try:
                    body_dict = json.loads(body)
                    translated_body = translate_payload_to_openai(
                        body_dict, target_model_id
                    )
                    if is_gemini_client and is_streaming_request:
                        translated_body["stream"] = True
                    request_body = json.dumps(translated_body).encode("utf-8")
                except Exception as e:
                    logger.warning(
                        f"Failed to translate payload for OpenAI format: {e}"
                    )

            current_query_params = {
                k: v for k, v in query_params.items() if k.lower() != "key"
            }

            request_sent_time = request_received_time
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
                    if vpn_mode == "disabled":
                        actual_vpn_index = vpn_static if 0 < vpn_static <= 6 else 0
                    else:
                        actual_vpn_index = current_vpn_index
                except Exception as ve:
                    actual_vpn_index = 0
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
                request_sent_time = time.perf_counter()
                response = await client.send(req, stream=True)
                response_received_time = time.perf_counter()

                internal_latency_ms = int(
                    (request_sent_time - request_received_time) * 1000
                )
                upstream_latency_ms = int(
                    (response_received_time - request_sent_time) * 1000
                )

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
                    if is_streaming_request:
                        logger.info(
                            f"[{provider_name}/{candidate_model}] [vpn#{actual_vpn_index}] STREAM START [key#{key_index}-{api_key[-4:]}] [Proxy Latency: {internal_latency_ms}ms] [Upstream Latency: {upstream_latency_ms}ms]",
                            extra={"no_level": True},
                        )
                    else:
                        logger.info(
                            f"[{provider_name}/{candidate_model}] [vpn#{actual_vpn_index}] [key#{key_index}-{api_key[-4:]}] [200] [Proxy Latency: {internal_latency_ms}ms] [Upstream Latency: {upstream_latency_ms}ms]",
                            extra={"no_level": True},
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

                            async def iter_bytes():
                                try:
                                    async for chunk in response.aiter_bytes():
                                        raw_chunks_buffer.append(chunk)
                                        yield chunk
                                except (httpx.ReadError, httpx.HTTPError) as he:
                                    logger.error(
                                        f"[{candidate_model}] [vpn#{actual_vpn_index}] Upstream stream read error (abrupt disconnect or timeout): {he}"
                                    )
                                    raise  # Propagate to prevent silent 200 OK on failure
                                except asyncio.CancelledError:
                                    logger.warning(
                                        f"[{candidate_model}] [vpn#{actual_vpn_index}] Stream transmission cancelled by client (OpenCode disconnected)."
                                    )
                                    raise
                                except Exception as se:
                                    logger.error(
                                        f"[{candidate_model}] [vpn#{actual_vpn_index}] Unexpected stream exception: {se}"
                                    )
                                    raise

                            async def iter_translated_chunks():
                                async for chunk in iter_bytes():
                                    chunk_str = ""
                                    try:
                                        chunk_str = chunk.decode(
                                            "utf-8", errors="ignore"
                                        )
                                    except Exception:
                                        pass

                                    if chunk_str:
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
                        except asyncio.CancelledError:
                            logger.warning(
                                f"[{candidate_model}] [vpn#{actual_vpn_index}] Stream generator task cancelled."
                            )
                            raise
                        except Exception as e:
                            logger.error(
                                f"[{candidate_model}] [vpn#{actual_vpn_index}] Stream generator encountered an error: {e}"
                            )
                            raise
                        finally:
                            await response.aclose()
                            response_text = "".join(response_text_buffer)
                            raw_req_bytes = body
                            raw_resp_bytes = b"".join(raw_chunks_buffer)

                            # Extract and log token usage
                            usage = extract_token_usage(raw_resp_bytes)
                            usage_str = ""
                            if usage["total_tokens"] > 0:
                                cached_str = (
                                    f", Cached: {usage['cached_tokens']}"
                                    if usage["cached_tokens"] > 0
                                    else ""
                                )
                                usage_str = f" Prompt: {usage['prompt_tokens']}, Completion: {usage['completion_tokens']}, Total: {usage['total_tokens']}{cached_str}"
                            logger.info(
                                f"[{provider_name}/{candidate_model}] [vpn#{actual_vpn_index}] STREAM END. Chunks: {len(raw_chunks_buffer)}{usage_str}",
                                extra={"no_level": True},
                            )

                            # Always analyze response for anomalies in the background
                            asyncio.create_task(
                                analyze_response_for_anomalies(
                                    raw_response=raw_resp_bytes,
                                    response_text=response_text,
                                    model=candidate_model,
                                    provider=provider_name,
                                )
                            )

                            if SAVE_CHAT_LOGS:
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
                        resp_text = truncate_thought_signature(response.text)
                    except Exception as re:
                        resp_text = f"<Failed to read response body: {re}>"
                    await response.aclose()

                    # Trigger safety check for model/server errors
                    track_and_check_safety_limit()

                    if response.status_code == 429:
                        if parallelism_enabled:
                            failed_channel = ACTIVE_SLOTS[slot_idx]
                            if BACKUP_POOL:
                                new_channel = BACKUP_POOL.pop(0)
                                ACTIVE_SLOTS[slot_idx] = new_channel
                                BACKUP_POOL.append(failed_channel)
                                logger.info(
                                    f"[Parallelism] [vpn#{actual_vpn_index}] Slot {slot_idx} rotated: Channel {failed_channel} -> Channel {new_channel}"
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
                            f"[{provider_name}] [vpn#{actual_vpn_index}] Key #{key_index} 429 ({candidate_model}) on {request.method} {target_url}. Error: {format_error_message(resp_text)}. Cooldown {cooldown_duration:.1f}s. Attempt {attempt}/{max_attempts} [Proxy Latency: {internal_latency_ms}ms] [Upstream Latency: {upstream_latency_ms}ms]"
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
                        mark_cooldown(api_key, duration=43200.0)
                        error_msg = f"HTTP 403 Forbidden: {resp_text}"
                        log_non_429_error(candidate_model, api_key, error_msg)
                        logger.error(
                            f"[{provider_name}] [vpn#{actual_vpn_index}] Key #{key_index} 403 ({candidate_model}) on {request.method} {target_url}. Error: {format_error_message(resp_text)}. Cooldown 12h [Proxy Latency: {internal_latency_ms}ms] [Upstream Latency: {upstream_latency_ms}ms]"
                        )
                        continue
                    elif response.status_code == 503:
                        mark_cooldown(api_key, duration=10.0)
                        error_msg = f"HTTP 503 Service Unavailable: {resp_text}"
                        log_non_429_error(candidate_model, api_key, error_msg)

                        consecutive_503s += 1
                        logger.error(
                            f"[{provider_name}] [vpn#{actual_vpn_index}] Key #{key_index} HTTP 503 ({candidate_model}) on {request.method} {target_url}. Error: {format_error_message(resp_text)}. Consecutive 503s: {consecutive_503s}/10 [Proxy Latency: {internal_latency_ms}ms] [Upstream Latency: {upstream_latency_ms}ms]"
                        )

                        # VPN Integration: Track consecutive 503 errors
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
                                f"[VPN] 503 Error threshold reached ({VPN_CONSECUTIVE_ERRORS}/{vpn_threshold}). Rotating VPN immediately..."
                            )
                            await rotate_vpn_on_the_fly("503 error threshold")
                            VPN_CONSECUTIVE_ERRORS = 0
                            # Immediately retry without sleeping
                            continue

                        if consecutive_503s >= 10:
                            logger.error(
                                f"[{provider_name}] [vpn#{actual_vpn_index}] Hit 10 consecutive 503s for model '{candidate_model}'. Forcing provider switch!"
                            )
                            break  # Break out of the key loop to switch candidate model (change provider)

                        if consecutive_503s >= 3:
                            import random

                            sleep_duration = random.uniform(15.0, 90.0)
                            logger.info(
                                f"[{provider_name}] [vpn#{actual_vpn_index}] 3+ consecutive 503s. Sleeping {sleep_duration:.1f}s before trying next key..."
                            )
                            await asyncio.sleep(sleep_duration)
                        continue
                    elif response.status_code in (500, 502):
                        mark_cooldown(api_key, duration=10.0)
                        error_msg = (
                            f"HTTP {response.status_code} Server Error: {resp_text}"
                        )
                        log_non_429_error(candidate_model, api_key, error_msg)
                        logger.error(
                            f"[{provider_name}] [vpn#{actual_vpn_index}] Key #{key_index} HTTP {response.status_code} ({candidate_model}) on {request.method} {target_url}. Error: {format_error_message(resp_text)} [Proxy Latency: {internal_latency_ms}ms] [Upstream Latency: {upstream_latency_ms}ms]"
                        )
                        continue
                    else:
                        error_msg = f"HTTP {response.status_code} Unexpected Status: {resp_text}"
                        log_non_429_error(candidate_model, api_key, error_msg)
                        logger.warning(
                            f"[{provider_name}] [vpn#{actual_vpn_index}] Key #{key_index} HTTP {response.status_code} ({candidate_model}) on {request.method} {target_url}. Error: {format_error_message(resp_text)} [Proxy Latency: {internal_latency_ms}ms] [Upstream Latency: {upstream_latency_ms}ms]"
                        )
                        continue

            except Exception as e:
                response_received_time = time.perf_counter()
                internal_latency_ms = int(
                    (request_sent_time - request_received_time) * 1000
                )
                upstream_latency_ms = int(
                    (response_received_time - request_sent_time) * 1000
                )

                logger.error(
                    f"[{provider_name}] [vpn#{actual_vpn_index}] Key #{key_index} conn error ({candidate_model}) on {request.method} {target_url}: {type(e).__name__} - {e} [Proxy Latency: {internal_latency_ms}ms] [Upstream Latency: {upstream_latency_ms}ms]"
                )
                log_non_429_error(candidate_model, api_key, f"{type(e).__name__}: {e}")
                mark_cooldown(api_key, duration=10.0)

                # Trigger safety check for connection errors
                track_and_check_safety_limit()

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
            if enable_model_rotation:
                rotation_config["model_cooldowns"][candidate_model] = now + 86400.0
                logger.warning(f"Model '{candidate_model}' failed. Cooldown 24h")
            else:
                logger.warning(
                    f"Model '{candidate_model}' failed. No cooldown applied because model rotation is disabled."
                )
            rotation_config["consecutive_model_failures"][candidate_model] = 0

            current_index = (
                candidates.index(candidate_model)
                if candidate_model in candidates
                else -1
            )
            next_index = (current_index + 1) % len(candidates)
            rotation_config["last_fallback_switch_time"] = now

            save_rotation_config(rotation_config)

    logger.error(f"[{requested_model}] [all-keys-failed] [503]")
    return JSONResponse(
        status_code=503,
        content={
            "error": {
                "message": f"All candidate models for '{requested_model}' failed or are unavailable."
            }
        },
    )
