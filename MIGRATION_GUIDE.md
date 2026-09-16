# GeminiProxy PC Migration & Deployment Guide

This document provides complete instructions for migrating and deploying **GeminiProxy** to a new computer (Windows 10/11 x64). It details environment setup, the one-command migration script (`migrate.cmd`), configuration of portable paths, API keys structure, client integration, and comprehensive instructions for configuring the multi-channel **WireGuard VPN** subsystem now located in `project_dir\vpn`.

---

## 1. Quick One-Command Setup (`migrate.cmd`)

If you have already cloned the repository or copied the project folder to the target PC:

```cmd
migrate.cmd
```

`migrate.cmd` automates the entire migration sequence:
1. **Pulls latest code:** Executes `git pull` from remote.
2. **Environment verification:** Checks for Python 3.10+ and `uv` (falls back to standard `venv` + `pip` if `uv` is not present).
3. **Dependency installation:** Installs and precompiles all required packages into `.venv`.
4. **VPN verification:** Checks for `vpn\vpn_manager.py`, `vpn\forawrd_tunnels.ps1`, and all 6 tunnel configs (`vpn\configs\vpn1.conf` - `vpn6.conf`).
5. **Config update:** Automatically sets `"vpn_switcher_dir"` in `config_rotation.json` to the local `%CD%\vpn` directory.
6. **Keys audit:** Checks configured `keys_location` and audits which API key files are found or missing.
7. **Launch prompt:** Offers to immediately launch `launch_gui.cmd`.

---

## 2. System Requirements & Prerequisites

### 2.1 Hardware & OS
- **OS:** Windows 10 (Build 19041+) or Windows 11 x64.
- **Privileges:** Standard user for running standalone proxy; **Administrator privileges (UAC elevation)** are mandatory only if using WireGuard VPN multi-channel rotation or system-wide VPN routing.

### 2.2 Software Dependencies
1. **Python 3.10+ (Recommended: 3.11 or 3.12):**
   - Ensure `python.exe` is added to system `PATH`.
2. **Package Manager (uv or pip):**
   - Recommended: [uv](https://github.com/astral-sh/uv) (`winget install astral-sh.uv` or `pip install uv`).
   - If `uv` is not present, standard `python -m venv` and `pip` are automatically used.
3. **WireGuard for Windows (Optional, needed for VPN rotation):**
   - Download and install official MSI from [wireguard.com/install](https://www.wireguard.com/install/).
   - Default install path: `C:\Program Files\WireGuard\wireguard.exe`.
4. **Git:**
   - For cloning and updating the repository.

---

## 3. Directory Structure & Files Overview

All VPN components and configs are now self-contained inside the project root under `vpn\`:

```text
GeminiProxy\                            # Repository Root
├── migrate.cmd                         # One-click target PC migration & pull script
├── launch_gui.cmd                      # One-click startup script
├── proxy3.py                           # CLI / GUI entrypoint
├── config_rotation.json                # Central settings & model lists
├── keys\                               # (Default) Local folder for API keys
│   ├── Google API Keys.md
│   ├── OpenRouter API Keys.md
│   ├── Mistral API Keys.md
│   ├── LLM7 Api Keys.md
│   ├── Ollama Cloud API Keys.md
│   └── Opencode Zen API Keys.md
├── vpn\                                # Project-local VPN switcher files
│   ├── vpn_manager.py                  # WindowsWireGuardManager class
│   ├── forawrd_tunnels.ps1             # Route forwarder script
│   └── configs\
│       ├── vpn1.conf
│       ├── vpn2.conf
│       ├── vpn3.conf
│       ├── vpn4.conf
│       ├── vpn5.conf
│       └── vpn6.conf
└── proxy_core\                         # Core server, GUI, compactor, rotation
```

---

## 4. Configurable Paths & Settings

All filesystem paths in GeminiProxy are dynamically resolved and fully configurable via GUI or JSON.

### 4.1 Path Resolution Order
Each path resolves in the following priority order:
1. **Explicit setting in `config_rotation.json`** (configured via GUI Settings tab or JSON editor).
2. **Environment variable override** (if set).
3. **Auto-detected portable default** (e.g. `<project_root>\vpn`, `<project_root>\keys`).
4. **Legacy fallback** (if existing on disk).

### 4.2 Configurable Items

| Setting | JSON Key | Environment Variable | Default / Fallback |
| :--- | :--- | :--- | :--- |
| **API Keys Location** | `"keys_location"` | `GEMINI_PROXY_KEYS_LOCATION` | `<project_root>/keys` or custom vault path |
| **VPN Switcher Directory** | `"vpn_switcher_dir"` | `VPN_SWITCHER_DIR` | `<project_root>/vpn` |
| **OpenCode Config Path** | `"opencode_config_path"` | `OPENCODE_CONFIG_PATH` | `~/.config/opencode-profiles/default/opencode.jsonc` |

### 4.3 Configuring via GUI
1. Open the proxy GUI (`launch_gui.cmd`).
2. Navigate to the **Settings** tab.
3. Use the **Browse** buttons:
   - **Keys Location:** Select the folder containing your API key Markdown files.
   - **VPN Switcher Directory:** Select the folder containing `vpn_manager.py` and `configs\` (defaults to `.\vpn`).
   - **OpenCode Config Path:** Select your `opencode.jsonc` file (used for automatic Kaggle Cloudflare URL synchronization).
4. Click **Save Settings**. Changes persist to `config_rotation.json` and keys are immediately reloaded.

---

## 5. API Keys Configuration

GeminiProxy extracts API keys from Markdown (`.md`) or text files. The file reader extracts raw keys while ignoring markdown headers (`#`), bullet points (`- `, `* `), and backticks (`` ` ``).

### 5.1 Key Files Reference
Place these files in your configured `keys_location` directory:
- `Google API Keys.md`: Google AI Studio / Gemini API keys (one per line).
- `OpenRouter API Keys.md`: OpenRouter keys (`sk-or-v1-...`).
- `Mistral API Keys.md`: Mistral AI API keys.
- `LLM7 Api Keys.md`: LLM7 API keys.
- `Ollama Cloud API Keys.md`: Ollama Cloud API keys.
- `Opencode Zen API Keys.md`: OpenCode Zen API keys.

---

## 6. Deep Dive: WireGuard VPN Subsystem in `.\vpn`

The VPN subsystem provides multi-tunnel IP rotation, allowing the proxy to bypass upstream IP rate limits (such as Google 429s or Cloudflare WAF restrictions) by binding individual HTTP socket connections to specific WireGuard tunnel virtual network adapters.

### 6.1 Two Operational Modes

1. **Zero-VPN / Standalone Mode (Default):**
   - If `vpn\` is not present, WireGuard is not installed, or VPN mode is set to `Disabled`:
     - GeminiProxy runs in 100% standalone mode.
     - All outbound requests use standard Windows internet connectivity via unbound sockets (`vpn_clients[0]`).
     - No background tunnel checks, no route modifications, and no administrator privileges required.

2. **Multi-Channel VPN Rotation Mode:**
   - 6 WireGuard tunnel interfaces (`vpn1` through `vpn6`) run simultaneously as Windows services.
   - Each tunnel has a distinct local IP:
     - `vpn1`: `10.8.0.11`
     - `vpn2`: `10.8.0.12`
     - `vpn3`: `10.8.0.13`
     - `vpn4`: `10.8.0.14`
     - `vpn5`: `10.8.0.15`
     - `vpn6`: `10.8.0.16`
     - Gateway: `10.8.0.1`
   - In `proxy_core/server.py`, 7 distinct `httpx.AsyncClient` instances are instantiated:
     - Client `0`: unbound (default connection).
     - Clients `1-6`: bound strictly to local IP `10.8.0.1{i}` via socket binding.
   - When requests occur, the proxy routes them through different tunnels via Round-Robin or on error threshold (rotating to another clean IP upon 429 or 503).

### 6.2 Target PC WireGuard Setup

#### Step 1: Install WireGuard
- Install WireGuard for Windows. Verify `wireguard.exe` exists at:
  ```text
  C:\Program Files\WireGuard\wireguard.exe
  ```

#### Step 2: Verify `vpn\` Folder
- Verify that `vpn\configs\` contains `vpn1.conf` through `vpn6.conf`.
- Each config defines its local address (`10.8.0.11/24` to `10.8.0.16/24`) and remote server endpoint.

#### Step 3: Run as Administrator
- Launch `launch_gui.cmd` as Administrator (required for WireGuard NT service creation and route injection).
- In the **VPN Manager** tab:
  - Click **Start Tunnels**: Installs and starts all 6 tunnel services in parallel.
  - Click **Check Tunnels IP**: Sends test requests from each tunnel to `api.ipify.org` and verifies public IP addresses.

---

## 7. OpenCode & Client Integration

Configure your AI coding assistant (OpenCode, Claude Dev, Cline, Continue) to connect to GeminiProxy:

### 7.1 OpenCode Configuration (`opencode.jsonc`)
Add GeminiProxy as a provider in your `opencode.jsonc`:

```jsonc
{
  "provider": {
    "gemini": {
      "npm": "@ai-sdk/google",
      "baseURL": "http://127.0.0.1:4000/v1beta",
      "apiKey": "dummy"
    },
    "openrouter": {
      "npm": "@ai-sdk/openai-compatible",
      "baseURL": "http://127.0.0.1:4000/openrouter",
      "apiKey": "dummy"
    }
  }
}
```

### 7.2 Automatic Port Forwarding
The proxy listens on port `4000` by default. You can change the port with `--port <port>`:
```cmd
python proxy3.py --gui --port 4000
```
