# Active State

## Current Milestone / Task
- **Objective:** Support project-local `vpn\` directory, implement one-command migration script (`migrate.cmd`) with git pull, and prepare repository for commit and push to remote.
- **Status:** Complete.

## Verified Components
1. **Project-Local VPN Directory (`vpn/`):**
   - Moved/copied all WireGuard switching files to `vpn/` (`vpn_manager.py`, `forawrd_tunnels.ps1`, `register.ps1`, `unregister.ps1`, `configs/vpn1.conf` ... `vpn6.conf`).
   - Updated `get_default_vpn_dir()` in `proxy_core/config.py` to prioritize `os.path.join(project_root, "vpn")`.
   - Verified via `test_config_keys.py` (7 tests passing).
2. **One-Command Migration Script (`migrate.cmd`):**
   - Performs `git pull` from remote.
   - Detects / provisions `.venv` via `uv` or standard Python `venv`.
   - Installs and upgrades all runtime requirements.
   - Validates project-local `vpn\` folder and WireGuard configurations.
   - Checks WireGuard Windows installation (`C:\Program Files\WireGuard\wireguard.exe`).
   - Automatically sets `"vpn_switcher_dir"` in `config_rotation.json` to local `%CD%\vpn`.
   - Audits configured API key files and paths.
   - Prompts for immediate GUI launch.
3. **Documentation:**
   - Updated `MIGRATION_GUIDE.md` detailing `migrate.cmd` workflow, `project_dir\vpn` structure, and WireGuard setup.

## Next Actionable Step
- Commit changes and push to `origin main`.
