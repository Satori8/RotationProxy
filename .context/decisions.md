# Architectural Decisions (ADRs)

## ADR-001: Portable & Dynamic Path Resolution Hierarchy

### Context
Previous implementation contained hardcoded paths across server, GUI, configuration, and tools (e.g. `D:\Personal\myvault...`, `D:\Work\Active\server-services\vpn_switcher`, `E:\Appdata\.config\opencode-profiles\...`). This prevented porting to another computer or operating system without manually finding and modifying lines of source code.

### Decision
1. **Centralized Resolvers:** Centralized path resolution in `proxy_core/config.py` for:
   - `keys_location`
   - `vpn_switcher_dir`
   - `opencode_config_path`
2. **Fallback Chain:** Each resolver follows a resilient hierarchy:
   - User configuration in `config_rotation.json`
   - Environment variables (`GEMINI_PROXY_KEYS_LOCATION`, `VPN_SWITCHER_DIR`, `OPENCODE_CONFIG_PATH`)
   - Auto-detected portable relative path / standard user directory
   - Legacy author path check (if existing on current disk)
3. **GUI Integration:** Added native "Browse" dialogs in the GUI Settings tab, persisting values directly to `config_rotation.json`.
4. **Zero-VPN Graceful Degradation:** When `vpn_switcher` is not found or WireGuard is not installed, the proxy operates seamlessly in standalone zero-VPN mode without errors or elevation prompts.

### Consequences
- Porting to any PC requires zero code modifications.
- Paths can be customized via GUI, JSON file, or environment variables.
- Legacy setups continue to function without disruption.
