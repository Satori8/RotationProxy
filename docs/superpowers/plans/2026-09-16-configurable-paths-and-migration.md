# Configurable Paths & Multi-PC Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate all hardcoded filesystem paths across the codebase, make paths configurable via `config_rotation.json` and the GUI Settings tab with portable defaults, and provide a comprehensive PC migration guide with in-depth WireGuard VPN instructions.

**Architecture:** 
- Centralize path resolution in `proxy_core/config.py` with fallback chains (config value -> environment variable -> relative/detected default -> author legacy fallback if exists).
- Introduce configurable keys: `keys_location`, `vpn_switcher_dir`, `opencode_config_path`.
- Bind `proxy_core/server.py` and `proxy_core/gui.py` to use centralized path resolvers.
- Add GUI Settings fields with file/folder "Browse" dialogs in `proxy_core/gui.py`.
- Create a self-contained `MIGRATION_GUIDE.md` documenting porting to any Windows PC, dependency installation, keys directory structure, and WireGuard VPN setup.

**Tech Stack:** Python 3.10+, FastAPI, CustomTkinter, WireGuard for Windows, PowerShell, pytest.

---

### Task 1: Centralized Path Resolvers and Config Upgrades in `proxy_core/config.py`

**Files:**
- Modify: `proxy_core/config.py`
- Modify: `test_config_keys.py`

- [ ] **Step 1: Write tests for new path resolvers and config upgrade**
Add tests to `test_config_keys.py` verifying:
- `get_keys_location`
- `get_vpn_dir`
- `get_opencode_config_path`
- `load_rotation_config` upgrading config with new keys `vpn_switcher_dir` and `opencode_config_path`.

- [ ] **Step 2: Run test to verify it fails**
Run: `pytest test_config_keys.py -v`
Expected: FAIL on missing resolvers.

- [ ] **Step 3: Implement centralized path resolvers in `proxy_core/config.py`**
- Define `DEFAULT_KEYS_LOCATION` (portable default `./keys`, checking env var or legacy fallback).
- Add `get_keys_location(config: dict | None = None) -> str`.
- Define `DEFAULT_VPN_DIR` and `get_vpn_dir(config: dict | None = None) -> str`.
- Define `DEFAULT_OPENCODE_CONFIG_PATH` and `get_opencode_config_path(config: dict | None = None) -> str`.
- Update `load_kaggle_url()` and `save_kaggle_url(new_url: str)` to use `get_opencode_config_path()`.
- Update `load_rotation_config()` to include `vpn_switcher_dir` and `opencode_config_path` in default dict and upgrade checks.

- [ ] **Step 4: Run test to verify it passes**
Run: `pytest test_config_keys.py -v`
Expected: PASS.

---

### Task 2: Refactor `proxy_core/server.py` to Use Dynamic VPN Directory

**Files:**
- Modify: `proxy_core/server.py`

- [ ] **Step 1: Replace hardcoded `vpn_dir` with `get_vpn_dir()`**
In `proxy_core/server.py`:
- Import `get_vpn_dir` from `proxy_core.config`.
- Resolve `vpn_dir = get_vpn_dir()`.
- Ensure `sys.path.insert(0, vpn_dir)` only runs if `vpn_dir` exists on disk.
- Gracefully log whether `vpn_manager` was found or running in standalone (no-VPN) mode.

- [ ] **Step 2: Verify syntax and imports**
Run diagnostics / compile check on `proxy_core/server.py`.

---

### Task 3: Refactor `proxy_core/gui.py` for Dynamic Paths & Settings Tab UI

**Files:**
- Modify: `proxy_core/gui.py`

- [ ] **Step 1: Replace hardcoded `vpn_dir` and `script_path`**
- Import `get_vpn_dir` and `get_opencode_config_path` from `proxy_core.config`.
- Update `__init__` in `ProxyGUI` to resolve `vpn_dir = get_vpn_dir()`.
- Update `run_manual_forward` to resolve `script_path = os.path.join(get_vpn_dir(), "forawrd_tunnels.ps1")` (with fallback to `forward_tunnels.ps1`).

- [ ] **Step 2: Add GUI Settings entries for `vpn_switcher_dir` and `opencode_config_path`**
In `load_settings_ui`:
- Add "VPN Switcher Directory" entry + "Browse" button.
- Add "OpenCode Config Path" entry + "Browse" button.
- Update `on_save_settings` to save `vpn_switcher_dir` and `opencode_config_path` to `config_rotation.json`.
- Add browse handler for OpenCode config file (`askopenfilename`).
- Add browse handler for VPN switcher directory (`askdirectory`).

- [ ] **Step 3: Update `tools/analyze_duplicates.py` and other tool scripts to use relative paths**
- Remove hardcoded `D:\Work\Active\...` in `tools/analyze_duplicates.py`.

---

### Task 4: Create Comprehensive `MIGRATION_GUIDE.md`

**Files:**
- Create: `MIGRATION_GUIDE.md`

- [ ] **Step 1: Write complete PC Migration Guide**
Include:
1. Overview & Architecture (Standalone mode vs Multi-VPN Mode).
2. Prerequisites on Target PC (Python 3.10+, uv / pip, Git, Windows 10/11 x64).
3. Installation Steps:
   - Cloning repository.
   - Setting up virtual environment via `launch_gui.cmd` or manual `python -m venv`.
   - Dependency installation.
4. API Keys Configuration:
   - File formats (`Google API Keys.md`, `OpenRouter API Keys.md`, `Mistral API Keys.md`, etc.).
   - Configuring `keys_location` in GUI Settings or `config_rotation.json`.
   - Relative vs absolute path options.
5. In-Depth WireGuard VPN Setup & Migration:
   - Purpose of multi-channel VPN rotation (bypassing IP rate limits across 6 tunnels).
   - WireGuard installation (`C:\Program Files\WireGuard\wireguard.exe`).
   - Transferring `vpn_switcher` directory and configs (`vpn1.conf` - `vpn6.conf`).
   - IP addressing schema (`10.8.0.11` - `10.8.0.16`, Gateway `10.8.0.1`).
   - Configuring `vpn_switcher_dir` in GeminiProxy Settings.
   - Windows Administrator / UAC permissions required for service creation and route injection.
   - Firewall, Antivirus, and Network Adapter requirements (avoiding BSODs from third-party NDIS filter drivers).
   - Running in Standalone / Zero-VPN Mode (fallback when no WireGuard is present).
   - Verifying VPN health: "Check Tunnels IP" and ping latency diagnostics.
6. OpenCode / Claude Dev Integration:
   - Configuring `opencode.jsonc` provider endpoint (`http://127.0.0.1:4000/v1`).
   - Auto-updating Kaggle URL and OpenCode config path.
7. Verification & Troubleshooting Checklist.

---

### Task 5: Verification, Git Commit, and CADP Sync

**Files:**
- Modify/Create: `.context/active_state.md`, `.context/architecture.md`, `.context/decisions.md`

- [ ] **Step 1: Run complete test suite**
Run: `pytest test_config_keys.py test_compactor.py -v`
Expected: ALL PASS.

- [ ] **Step 2: Commit changes to Git**
Git commit all modified and newly created files.

- [ ] **Step 3: Update Context Anchors (.context/)**
Sync active state, architecture, and decisions atomically.
