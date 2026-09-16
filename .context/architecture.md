# GeminiProxy Architecture

## Subsystem Overview
GeminiProxy is a high-throughput, resilient reverse proxy for AI coding assistants (OpenCode, Claude Dev, Cline) providing transparent model translation, token compaction, error handling, key rotation, and multi-channel WireGuard VPN network routing.

```text
+--------------------------------------------------------+
|          AI Client (OpenCode / Claude Dev)             |
+---------------------------+----------------------------+
                            | HTTP / SSE
                            v
+--------------------------------------------------------+
|      GeminiProxy Server (FastAPI / Uvicorn :4000)      |
|  - Compactor: dynamic AST context & tool compression   |
|  - Key Rotation: pool balancing, 429 backoff, cooldowns|
|  - Model Translation: OpenAI <-> Gemini schemas        |
|  - Dynamic Paths Resolver: config -> env -> defaults   |
+---------------------------+----------------------------+
                            | Bound HTTP Sockets
                            v
+--------------------------------------------------------+
|     HTTP Client Sockets Pool (httpx.AsyncClient)       |
|  [0]: Unbound Default Gateway                          |
|  [1]: Bound to 10.8.0.11 (WireGuard Tunnel 1)          |
|  [2]: Bound to 10.8.0.12 (WireGuard Tunnel 2)          |
|  [3]: Bound to 10.8.0.13 (WireGuard Tunnel 3)          |
|  [4]: Bound to 10.8.0.14 (WireGuard Tunnel 4)          |
|  [5]: Bound to 10.8.0.15 (WireGuard Tunnel 5)          |
|  [6]: Bound to 10.8.0.16 (WireGuard Tunnel 6)          |
+---------------------------+----------------------------+
                            |
                            v
               Upstream Model APIs (Google /
              OpenRouter / Mistral / Ollama)
```

## Toolchain Commands
- Launch GUI: `launch_gui.cmd` (or `python proxy3.py --gui`)
- Run CLI Server: `python proxy3.py --host 127.0.0.1 --port 4000`
- Run Tests: `pytest test_config_keys.py test_compactor.py -v`

## Dependency Stack
- **GUI:** `customtkinter`
- **Server:** `fastapi`, `uvicorn`, `starlette`
- **Networking:** `httpx` (with local socket address binding)
- **Tokenization:** `tiktoken`, `tree-sitter`
- **VPN Subsystem (Optional):** `WindowsWireGuardManager` via WireGuard for Windows (`wireguard.exe`) + PowerShell NetTCPIP cmdlets.

## Path Management Subsystem
- `proxy_core/config.py`:
  - `get_keys_location()`: Evaluates `"keys_location"`, `GEMINI_PROXY_KEYS_LOCATION`, `<root>/keys`.
  - `get_vpn_dir()`: Evaluates `"vpn_switcher_dir"`, `VPN_SWITCHER_DIR`, `<root>/../server-services/vpn_switcher`.
  - `get_opencode_config_path()`: Evaluates `"opencode_config_path"`, `OPENCODE_CONFIG_PATH`, `~/.config/opencode-profiles/default/opencode.jsonc`.
