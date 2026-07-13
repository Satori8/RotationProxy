# System VPN Routing & Switcher Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a user-controlled switcher to the main GUI to route all PC/system traffic through a selected WireGuard tunnel.

**Architecture:** Integrate a toggle switch and dropdown in the GUI's VPN control panel. Use a background thread to handle checking tunnel status, starting the service if stopped, and applying/reverting system-wide routing tables using the existing `WindowsWireGuardManager`.

**Tech Stack:** Python, CustomTkinter, PowerShell, WireGuard.

---

### Task 1: Initialize System VPN UI Elements

**Files:**
- Modify: `proxy_core/gui.py` (Add UI widgets to `__init__` and initialize state)

- [ ] **Step 1: Locate insertion point**
Find the `vpn_forward_btn` grid layout in `proxy_core/gui.py` (around line 637).

- [ ] **Step 2: Add UI widget initialization code**
Immediately after `self.vpn_forward_btn.grid(...)`, add the following code block to initialize the System VPN frame, switcher, dropdown, and state variable:
```python
        # System VPN Routing Frame
        self.system_vpn_frame = ctk.CTkFrame(self.vpn_control_frame, fg_color="transparent")
        self.system_vpn_frame.grid(row=5, column=0, padx=20, pady=(15, 10), sticky="ew")
        self.system_vpn_frame.grid_columnconfigure(0, weight=1)
        self.system_vpn_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            self.system_vpn_frame,
            text="System VPN Routing",
            font=ctk.CTkFont(size=12, weight="bold"),
        ).grid(row=0, column=0, columnspan=2, pady=(0, 5), sticky="w")

        self.system_vpn_switch = ctk.CTkSwitch(
            self.system_vpn_frame,
            text="Route All PC Traffic",
            command=self.on_system_vpn_toggle,
        )
        self.system_vpn_switch.grid(row=1, column=0, pady=5, sticky="w")

        self.system_vpn_dropdown = ctk.CTkOptionMenu(
            self.system_vpn_frame,
            values=["VPN 1", "VPN 2", "VPN 3", "VPN 4", "VPN 5", "VPN 6"],
            width=80,
        )
        self.system_vpn_dropdown.grid(row=1, column=1, padx=(10, 0), pady=5, sticky="e")
        self.system_vpn_dropdown.set("VPN 1")

        self.system_vpn_active = False
```

- [ ] **Step 3: Commit UI layout changes**
```bash
git add proxy_core/gui.py
git commit -m "feat: add system vpn ui elements to gui"
```

---

### Task 2: Implement Toggle Logic & Background Threading

**Files:**
- Modify: `proxy_core/gui.py` (Implement `on_system_vpn_toggle` event handler)

- [ ] **Step 1: Add the `on_system_vpn_toggle` method**
Add the following method to the `ProxyGUI` class:
```python
    def on_system_vpn_toggle(self):
        """Handle toggling of system-wide VPN routing."""
        if not hasattr(self, "vpn_manager") or self.vpn_manager is None:
            log_queue.put("[GUI] [ERROR] VPN Manager library is not loaded.")
            self.system_vpn_switch.deselect()
            return

        # Check admin privileges
        if not self.vpn_manager.is_admin():
            log_queue.put("[GUI] [SYSTEM] WireGuard requires Administrator privileges. Requesting UAC elevation...")
            self.system_vpn_switch.deselect()
            self.vpn_manager.elevate()
            return

        is_on = self.system_vpn_switch.get() == 1
        self.system_vpn_switch.configure(state="disabled")
        self.system_vpn_dropdown.configure(state="disabled")

        def run_toggle():
            try:
                if is_on:
                    selected_val = self.system_vpn_dropdown.get()
                    # Parse index (e.g. "VPN 3" -> 3)
                    idx = int(selected_val.split()[-1])
                    log_queue.put(f"[GUI] [SYSTEM] Enabling System VPN routing via VPN {idx}...")
                    
                    # Ensure service is running
                    from proxy_core.rotation import wait_for_adapter_and_add_route
                    
                    # Check if service is active
                    output, _ = self.vpn_manager.run_ps_cmd(
                        f'Get-Service -Name "WireGuardTunnel$vpn{idx}" | Where-Object {{$_.Status -eq "Running"}}'
                    )
                    if not output:
                        log_queue.put(f"[GUI] [SYSTEM] Service vpn{idx} is offline. Starting service...")
                        conf_path = os.path.join(self.vpn_manager.configs_dir, f"vpn{idx}.conf")
                        if os.path.exists(conf_path):
                            subprocess.run(
                                [self.vpn_manager.wg_path, "/installtunnelservice", conf_path],
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL,
                            )
                            # Set startup to Manual
                            subprocess.run(
                                ["powershell", "-Command", f"Set-Service -Name 'WireGuardTunnel$vpn{idx}' -StartupType Manual"],
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL,
                            )
                            success = wait_for_adapter_and_add_route(idx, timeout=60.0)
                            if not success:
                                log_queue.put(f"[GUI] [ERROR] Failed to start VPN {idx} service or configure adapter.")
                                self.after(0, lambda: self.system_vpn_switch.deselect())
                                return
                        else:
                            log_queue.put(f"[GUI] [ERROR] Config not found for vpn{idx}")
                            self.after(0, lambda: self.system_vpn_switch.deselect())
                            return

                    # Enable system-wide routing
                    self.vpn_manager.enable_system_routing_via(idx, print_cb=log_queue.put)
                    self.system_vpn_active = True
                else:
                    log_queue.put("[GUI] [SYSTEM] Disabling System VPN routing...")
                    self.vpn_manager.disable_system_routing(print_cb=log_queue.put)
                    self.system_vpn_active = False
            except Exception as e:
                logger.error(f"[GUI] Error toggling system VPN: {e}")
                log_queue.put(f"[GUI] [ERROR] Failed to toggle system VPN: {e}")
                if is_on:
                    self.after(0, lambda: self.system_vpn_switch.deselect())
            finally:
                self.after(0, lambda: self.system_vpn_switch.configure(state="normal"))
                if not self.system_vpn_active:
                    self.after(0, lambda: self.system_vpn_dropdown.configure(state="normal"))

        threading.Thread(target=run_toggle, daemon=True).start()
```

- [ ] **Step 2: Commit logic changes**
```bash
git add proxy_core/gui.py
git commit -m "feat: implement on_system_vpn_toggle logic and background thread"
```

---

### Task 3: Integrate Safety Gates & Cleanup

**Files:**
- Modify: `proxy_core/gui.py` (Add safety gates to startup, exit, and stop tunnels commands)

- [ ] **Step 1: Add startup routing cleanup**
In the `__init__` method of `ProxyGUI`, right after loading `self.vpn_manager` (around line 164), add a clean-slate routing reset:
```python
        # Clean up system routing on startup to ensure a clean slate
        if hasattr(self, "vpn_manager") and self.vpn_manager is not None:
            import threading
            threading.Thread(target=lambda: self.vpn_manager.disable_system_routing(), daemon=True).start()
```

- [ ] **Step 2: Update `on_vpn_stop_tunnels`**
In the `on_vpn_stop_tunnels` method, inside the `run_stop` nested function (around line 1995), add the following lines to reset the UI switch state:
```python
                if hasattr(self, "system_vpn_switch") and self.system_vpn_switch:
                    self.after(0, lambda: self.system_vpn_switch.deselect())
                    self.after(0, lambda: self.system_vpn_dropdown.configure(state="normal"))
                self.system_vpn_active = False
```

- [ ] **Step 3: Update `on_close`**
In the `on_close` method (around line 975), ensure `disable_system_routing` is called synchronously on exit:
```python
        if hasattr(self, "vpn_manager") and self.vpn_manager is not None:
            self.vpn_manager.disable_system_routing()
            self.vpn_manager.uninstall_all_services()
```

- [ ] **Step 4: Commit safety integration**
```bash
git add proxy_core/gui.py
git commit -m "feat: integrate system vpn safety gates and cleanups"
```
