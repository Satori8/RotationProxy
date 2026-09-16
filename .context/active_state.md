# Active State

## Current Milestone / Task
- **Objective:** Eliminate hardcoded paths across GeminiProxy, implement dynamic configurable paths via settings, and produce a complete PC migration guide with in-depth WireGuard VPN instructions.
- **Status:** Complete.

## Verified Components
1. **Dynamic Path Resolution (`proxy_core/config.py`):**
   - `get_keys_location()`: Config -> `GEMINI_PROXY_KEYS_LOCATION` -> portable default `<project_root>/keys` -> legacy check.
   - `get_vpn_dir()`: Config `"vpn_switcher_dir"` -> `VPN_SWITCHER_DIR` -> relative `<project_root>/../server-services/vpn_switcher` -> legacy check.
   - `get_opencode_config_path()`: Config `"opencode_config_path"` -> `OPENCODE_CONFIG_PATH` -> auto-detection of `~/.config/opencode-profiles/default/opencode.jsonc`.
   - `load_kaggle_url()` & `save_kaggle_url()`: Updated to resolve path dynamically.
   - `load_rotation_config()`: Schema upgrade automatically ensures `"vpn_switcher_dir"` and `"opencode_config_path"` exist.
2. **Server Subsystem (`proxy_core/server.py`):**
   - Resolves `vpn_dir` via `get_vpn_dir()`.
   - `sys.path.insert` guarded by existence check.
   - WireGuard manager import wrapped gracefully for standalone zero-VPN mode.
3. **GUI Interface (`proxy_core/gui.py`):**
   - Dynamic resolution of `vpn_dir` and `forawrd_tunnels.ps1`.
   - Added GUI Settings fields in Settings Tab:
     - "VPN Switcher Directory" with directory browse dialog.
     - "OpenCode Config Path" with file browse dialog.
   - Settings persist seamlessly to `config_rotation.json`.
4. **Tools & Diagnostics (`tools/analyze_duplicates.py`):**
   - Removed absolute paths; updated to resolve relative to project root.
5. **Testing & Verification:**
   - `test_config_keys.py`: 7 tests passing.
   - `test_compactor.py`: 37 tests passing.
6. **Documentation (`MIGRATION_GUIDE.md`):**
   - Complete guide covering hardware/OS, Python/uv setup, keys layout, client integration, and comprehensive WireGuard VPN setup.

## Next Step
- System is fully portable and ready for deployment to any PC. Run `launch_gui.cmd` to start.
