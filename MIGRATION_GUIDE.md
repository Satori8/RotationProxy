# GeminiProxy PC Migration & Deployment Guide

This document provides complete instructions for migrating and deploying **GeminiProxy** to a new computer (Windows 10/11 x64). It details environment setup, configuration of portable paths, API keys structure, client integration, and comprehensive instructions for configuring the multi-channel **WireGuard VPN** subsystem.

---

## 1. System Requirements & Prerequisites

### 1.1 Hardware & OS
- **OS:** Windows 10 (Build 19041+) or Windows 11 x64.
- **Privileges:** Standard user for running standalone proxy; **Administrator privileges (UAC elevation)** are mandatory only if using WireGuard VPN multi-channel rotation or system-wide VPN routing.

### 1.2 Software Dependencies
1. **Python 3.10+ (Recommended: 3.11 or 3.12):**
   - Ensure `python.exe` is added to system `PATH`.
2. **Package Manager (uv or pip):**
   - Recommended: [uv](https://github.com/astral-sh/uv) (`winget install astral-sh.uv` or `pip install uv`).
   - If `uv` is not present, standard `python -m venv` and `pip` can be used.
3. **WireGuard for Windows (Optional, needed for VPN rotation):**
   - Download and install official MSI from [wireguard.com/install](https://www.wireguard.com/install/).
   - Default install path: `C:\Program Files\WireGuard\wireguard.exe`.
4. **Git:**
   - For cloning and updating the repository.

---

## 2. Directory Structure & Files Overview

When deploying to a new PC, organize your working directories cleanly. A recommended layout is:

```text
D:\Work\Active\  (or C:\Projects\)
├── GeminiProxy\                        # This repository
│   ├── launch_gui.cmd                  # One-click startup script
│   ├── proxy3.py                       # CLI / GUI entrypoint
│   ├── config_rotation.json            # Central settings & model lists
│   ├── keys\                           # (Optional) Local folder for API keys
│   │   ├── Google API Keys.md
│   │   ├── OpenRouter API Keys.md
│   │   ├── Mistral API Keys.md
│   │   ├── LLM7 Api Keys.md
│   │   ├── Ollama Cloud API Keys.md
│   │   └── Opencode Zen API Keys.md
│   └── proxy_core\                     # Core server, GUI, compactor, rotation
└── server-services\                    # Optional VPN switcher repository
    └── vpn_switcher\
        ├── vpn_manager.py              # WindowsWireGuardManager class
        ├── forawrd_tunnels.ps1         # Route forwarder script
        └── configs\
            ├── vpn1.conf
            ├── vpn2.conf
            ├── vpn3.conf
            ├── vpn4.conf
            ├── vpn5.conf
            └── vpn6.conf
```

---

## 3. Quickstart Installation

1. **Clone or copy the repository:**
   ```powershell
   git clone <repo_url> GeminiProxy
   cd GeminiProxy
   ```

2. **Launch with automated virtual environment setup:**
   - Double-click `launch_gui.cmd` or run in terminal:
     ```cmd
     launch_gui.cmd
     ```
   - `launch_gui.cmd` automatically checks for `.venv`, installs dependencies (`customtkinter`, `fastapi`, `uvicorn`, `httpx`, `starlette`, `tiktoken`, `tree-sitter`), and boots the GUI.

3. **Manual CLI / Headless Launch (without GUI):**
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install customtkinter fastapi uvicorn httpx starlette tiktoken tree-sitter
   python proxy3.py --host 127.0.0.1 --port 4000
   ```

---

## 4. Configurable Paths & Settings

All filesystem paths in GeminiProxy are now dynamically resolved and fully configurable. You do not need to edit code to run on a new computer.

### 4.1 Path Resolution Order
Each path resolves in the following priority order:
1. **Explicit setting in `config_rotation.json`** (configured via GUI Settings tab or JSON editor).
2. **Environment variable override** (if set).
3. **Auto-detected portable default** (relative paths or common OS standard paths).
4. **Legacy fallback** (if existing on disk).

### 4.2 Configurable Items

| Setting | JSON Key | Environment Variable | Default / Fallback |
| :--- | :--- | :--- | :--- |
| **API Keys Location** | `"keys_location"` | `GEMINI_PROXY_KEYS_LOCATION` | `<project_root>/keys` or custom folder/file |
| **VPN Switcher Directory** | `"vpn_switcher_dir"` | `VPN_SWITCHER_DIR` | `<project_root>/../server-services/vpn_switcher` |
| **OpenCode Config Path** | `"opencode_config_path"` | `OPENCODE_CONFIG_PATH` | `~/.config/opencode-profiles/default/opencode.jsonc` |

### 4.3 Configuring via GUI
1. Open the proxy GUI (`launch_gui.cmd`).
2. Navigate to the **Settings** tab.
3. Use the **Browse** buttons:
   - **Keys Location:** Select the folder containing your API key Markdown files.
   - **VPN Switcher Directory:** Select the folder containing `vpn_manager.py` and `configs\`.
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

*Note:* If you point `keys_location` directly to a single file (e.g. `MyKeys.md`), that file will be used as the primary Google keys file.

---

## 6. Deep Dive: WireGuard VPN Subsystem

The VPN subsystem provides multi-tunnel IP rotation, allowing the proxy to bypass upstream IP rate limits (such as Google 429s or Cloudflare WAF restrictions) by binding individual HTTP socket connections to specific WireGuard tunnel virtual network adapters.

### 6.1 Two Operational Modes

1. **Zero-VPN / Standalone Mode (Default):**
   - If `vpn_switcher` is not present, WireGuard is not installed, or VPN mode is set to `Disabled`:
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

### 6.2 Setting Up WireGuard on the New PC

#### Step 1: Install WireGuard
- Install WireGuard for Windows. Verify `wireguard.exe` exists at:
  ```text
  C:\Program Files\WireGuard\wireguard.exe
  ```

#### Step 2: Prepare Tunnel Configurations
- On your remote WireGuard server (e.g. VPS / Oracle Cloud), generate 6 peer configs.
- Place them in `vpn_switcher/configs/`:
  - `vpn1.conf`, `vpn2.conf`, `vpn3.conf`, `vpn4.conf`, `vpn5.conf`, `vpn6.conf`.
- Example `vpn1.conf`:
  ```ini
  [Interface]
  PrivateKey = <Client_Private_Key_1>
  Address = 10.8.0.11/24
  DNS = 1.1.1.1, 8.8.8.8

  [Peer]
  PublicKey = <Server_Public_Key>
  Endpoint = 158.178.159.108:51820
  AllowedIPs = 0.0.0.0/0
  PersistentKeepalive = 25
  ```
  *(Repeat for `vpn2.conf` with Address `10.8.0.12/24` up to `vpn6.conf` with `10.8.0.16/24`).*

#### Step 3: Configure `vpn_manager.py`
In `vpn_switcher/vpn_manager.py`, verify/adjust the server parameters:
- `self.vps_ip = "<YOUR_SERVER_PUBLIC_IP>"` (e.g. `158.178.159.108`)
- `self.wg_gateway = "10.8.0.1"`
- `self.wg_path = r"C:\Program Files\WireGuard\wireguard.exe"`

#### Step 4: Administrator Privileges (UAC)
WireGuard installs Windows NT Services (`WireGuardTunnel$vpn1` ... `WireGuardTunnel$vpn6`) and dynamically manages network routes via `route.exe` and `powershell.exe`.
- Always launch the GUI or command prompt with **Run as Administrator** when interacting with VPN tunnels.
- If launched non-elevated, clicking **Start Tunnels** or **Configure Forwarding** triggers an automated UAC prompt.

### 6.3 Routing & Kernel Stability Protections
Windows networking (specifically `ndu.sys` and NDIS filter drivers) can encounter BSODs or routing loops if default gateways are improperly swapped. GeminiProxy uses several safety mechanisms:

1. **Split Default Route `/1` Scheme:**
   Rather than overriding `0.0.0.0/0` with high metric, system routing injects two `/1` routes:
   - `0.0.0.0 MASK 128.0.0.0 -> 10.8.0.1`
   - `128.0.0.0 MASK 128.0.0.0 -> 10.8.0.1`
   This cleanly directs all internet traffic without breaking local subnet routes.

2. **VPS Endpoint Route Pinning:**
   A direct host route to the VPS IP is pinned to your physical network interface gateway:
   - `route ADD <vps_ip> MASK 255.255.255.255 <physical_gateway> METRIC 1 IF <physical_if_index>`
   This prevents recursive encapsulation loops (tunnel disconnecting itself).

3. **Per-Socket Client Binding (Multi-Channel):**
   In standard proxy operation, system routing is **NOT** redirected. Instead, the proxy binds sockets directly to `10.8.0.1{i}`. The PowerShell script `forawrd_tunnels.ps1` sets a low-priority default gateway for each WireGuard interface index so Windows socket stack routes the packets correctly.

4. **Periodic Health Check & Auto-Healing:**
   A background task (`vpn_heartbeat_loop` in `server.py`) polls `http://connectivitycheck.gstatic.com/generate_204` across all 6 tunnel sockets.
   - If a tunnel drops 3 checks: the route is re-injected.
   - If a tunnel drops 5 checks: the specific service `WireGuardTunnel$vpn{i}` is automatically restarted without interrupting streams on other tunnels.

### 6.4 VPN Verification & Diagnostic Tools
In the GUI **VPN Manager** tab:
- **VPN Tunnel Status:** Shows live status and ping latency (ms) for all 6 tunnels.
- **Check Tunnels IP:** Sends HTTP requests from each bound client to `https://api.ipify.org` and prints the external IP of each tunnel in console logs. All 6 should show distinct or server IPs.
- **Route All PC Traffic (System VPN Routing):** Routes the entire Windows operating system traffic through any chosen tunnel (VPN 1-6).
- **Reset to Defaults:** Cleanly stops and uninstalls all 6 tunnel services, removes all custom routes from Windows routing table, and restores standard networking.

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

---

## 8. Migration Checklist

Use this checklist when setting up a fresh machine:

- [ ] Python 3.10+ installed and in system PATH.
- [ ] Repository cloned to local disk.
- [ ] Dependencies installed (`launch_gui.cmd` executed).
- [ ] API keys copied to `<project_root>/keys/` or custom folder.
- [ ] In GUI **Settings** tab:
  - [ ] Verified/set `Keys Location`.
  - [ ] Verified/set `VPN Switcher Directory` (if using VPN).
  - [ ] Verified/set `OpenCode Config Path`.
  - [ ] Clicked **Save Settings**.
- [ ] In GUI **Model Manager** tab:
  - [ ] Clicked **Fetch Models** (or tested individual models) to confirm upstream connectivity.
- [ ] (If using WireGuard):
  - [ ] Installed WireGuard for Windows.
  - [ ] Copied `configs/vpn1.conf` ... `vpn6.conf` into `vpn_switcher/configs/`.
  - [ ] Ran proxy GUI as Administrator.
  - [ ] In **VPN Manager** tab: clicked **Start Tunnels** and **Check Tunnels IP**.
- [ ] Configured client (`opencode.jsonc`) to target `http://127.0.0.1:4000`.
