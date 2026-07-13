# Design Spec: System VPN Routing & Switcher

## 1. Overview
This specification defines the architecture and implementation details for a robust System VPN Routing & Switcher feature inside the Resilient Key Rotation Proxy (`proxy3`).

While GeminiProxy's default behavior is to bound outgoing requests to specific virtual WireGuard VPN tunnels at the socket level (leaving standard system-wide routing untouched), this feature introduces a user-controlled switcher to route **all local system traffic** (PC-wide) through a selected WireGuard tunnel.

---

## 2. Architecture & Components

### 2.1 UI Switcher Controls (In `proxy_core/gui.py`)
We will add a new "System VPN Routing" control group inside the existing `vpn_control_frame` (on the left side of the VPN tab, below the "Configure Forwarding" button):
*   **Title Label**: A section divider label "System VPN Routing" with a bold font.
*   **Toggle Switch**: A `ctk.CTkSwitch` labeled "Route All PC Traffic".
    *   By default, it is OFF.
    *   When toggled, it calls `self.on_system_vpn_toggle()`.
*   **Tunnel Dropdown**: A `ctk.CTkOptionMenu` to select the target tunnel:
    *   Values: `["VPN 1", "VPN 2", "VPN 3", "VPN 4", "VPN 5", "VPN 6"]`.
    *   By default, it selects `"VPN 1"`.
    *   Disabled when System VPN routing is active to prevent changing the tunnel mid-route without first toggling off.

### 2.2 Logic Flow & Background Threading

#### 2.2.1 Toggling ON (Enabling)
1.  **Admin Check**: Verify UAC administrator privileges via `self.vpn_manager.is_admin()`. If not admin, prompt UAC elevation via `self.vpn_manager.elevate()`.
2.  **UI Lock**: Temporarily disable the switch and dropdown to prevent concurrent operations.
3.  **Background Worker Thread**:
    *   Parse selected index from the dropdown (e.g., `"VPN 3"` $\rightarrow$ `3`).
    *   **Auto-Start Check**: Query the status of service `WireGuardTunnel$vpn{index}`.
        *   If the service is stopped or not installed, register and start it.
        *   Wait for the adapter IP (`10.8.0.1{index}`) to appear and configure its route via `wait_for_adapter_and_add_route(index)`.
    *   **Route System**: Call `self.vpn_manager.enable_system_routing_via(index, print_cb=log_queue.put)`.
    *   **State Update**: Set `self.system_vpn_active = True`.
4.  **UI Unlock**: Re-enable the switch (now in ON state) and keep the dropdown disabled (so the user cannot change tunnels while routing is active).

#### 2.2.2 Toggling OFF (Disabling)
1.  **UI Lock**: Temporarily disable the switch.
2.  **Background Worker Thread**:
    *   **Clear Routes**: Call `self.vpn_manager.disable_system_routing(print_cb=log_queue.put)`.
    *   **State Update**: Set `self.system_vpn_active = False`.
3.  **UI Unlock**: Re-enable the switch (now in OFF state) and re-enable the dropdown.

---

## 3. Integration & Safety Gates

### 3.1 UAC Elevation/Cancellation Safety
If UAC elevation is requested but the user cancels/denies it, the switch should gracefully revert to the OFF state without crashing, and log a warning: `[GUI] [WARNING] Administrator privileges required to configure system routes.`

### 3.2 Startup Safety
On application startup, the System VPN switch is always initialized to OFF, and system routing is cleared via `self.vpn_manager.disable_system_routing()` to ensure a clean, un-hijacked network state.

### 3.3 Clean Exit
When the GUI is closed (`on_close` method), the application will call `self.vpn_manager.disable_system_routing()` to restore default internet connectivity.

### 3.4 Tunnels Shutdown Coordination
If the user clicks the "Stop Tunnels" button while System VPN is active, the application will automatically turn OFF the System VPN switch and restore default system routing before stopping the services.
