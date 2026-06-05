# VPN Health Check and Parallelism Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement a robust VPN Health Check (Heartbeat) and Parallelism System inside `proxy3` to ensure 100% uptime and load-balance requests across 7 active channels.

**Architecture:** A background `asyncio` task in `server.py` monitors the 6 VPN channels every 1.0s. If a channel fails, it runs a fast, non-blocking PowerShell route recovery and service restart with adapter polling. The proxy load-balances requests across $N$ active slots with per-channel delays and rotates failed slots to backup channels.

**Tech Stack:** Python, FastAPI, CustomTkinter, PowerShell, `httpx`

---

### Task 1: Implement Adapter Polling and Route Recovery in `proxy_core/rotation.py`

**Files:**
- Modify: `proxy_core/rotation.py`

- [ ] **Step 1: Add adapter polling and route recovery helpers**

Add these functions to `proxy_core/rotation.py`:

```python
def wait_for_adapter_and_add_route(vpn_index: int, timeout: float = 10.0) -> bool:
    """Polls every 0.5s until the VPN adapter's IP appears, then adds the default route."""
    import time
    import subprocess
    
    ip_address = f"10.8.0.1{vpn_index}"
    interface_alias = f"vpn{vpn_index}"
    start_time = time.time()
    
    while time.time() - start_time < timeout:
        # Check if IP is present
        check_cmd = f'Get-NetIPAddress -IPAddress "{ip_address}" -AddressFamily IPv4 -ErrorAction SilentlyContinue'
        result = subprocess.run(
            ["powershell", "-Command", check_cmd],
            capture_output=True,
            text=True,
            errors="replace"
        )
        if result.stdout and ip_address in result.stdout:
            # IP found! Add default route
            route_cmd = f'New-NetRoute -InterfaceAlias "{interface_alias}" -DestinationPrefix "0.0.0.0/0" -NextHop "10.8.0.1" -RouteMetric 50 -Confirm:$false -ErrorAction SilentlyContinue'
            subprocess.run(
                ["powershell", "-Command", route_cmd],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            logger.info(f"[VPN {vpn_index}] Adapter detected and default route configured successfully.")
            return True
        time.sleep(0.5)
        
    logger.warning(f"[VPN {vpn_index}] Timeout waiting for adapter IP {ip_address} to appear.")
    return False


def restart_vpn_service(vpn_index: int) -> None:
    """Restarts the specific WireGuard service and triggers adapter polling."""
    import subprocess
    
    service_name = f"WireGuardTunnel$vpn{vpn_index}"
    logger.info(f"[VPN {vpn_index}] Restarting WireGuard service...")
    
    # Restart service
    subprocess.run(
        ["powershell", "-Command", f'Restart-Service -Name "{service_name}" -ErrorAction SilentlyContinue'],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    
    # Wait for adapter and add route
    wait_for_adapter_and_add_route(vpn_index)
```

- [ ] **Step 2: Run syntax check**

Run: `python -m py_compile proxy_core/rotation.py`
Expected: PASS with no syntax errors.

- [ ] **Step 3: Commit**

```bash
git add proxy_core/rotation.py
git commit -m "feat: add adapter polling and route recovery helpers"
```

---

### Task 2: Implement Heartbeat Loop in `proxy_core/server.py`

**Files:**
- Modify: `proxy_core/server.py`

- [ ] **Step 1: Import helpers and initialize heartbeat state**

Import `wait_for_adapter_and_add_route` and `restart_vpn_service` from `proxy_core.rotation`.
Initialize global heartbeat state:
```python
# Heartbeat state
VPN_CONSECUTIVE_FAILURES = {i: 0 for i in range(1, 7)}
VPN_GRACE_PERIODS = {i: 0.0 for i in range(1, 7)}  # timestamp when grace period ends
```

- [ ] **Step 2: Implement the heartbeat background task**

Add `vpn_heartbeat_loop` to `proxy_core/server.py`:

```python
async def vpn_heartbeat_loop(app):
    """Background task that checks the health of all 6 VPN channels every 1.0s."""
    import time
    import asyncio
    
    logger.info("[Heartbeat] Starting VPN health check loop...")
    while True:
        await asyncio.sleep(1.0)
        now = time.time()
        
        for i in range(1, 7):
            # Skip if in grace period
            if now < VPN_GRACE_PERIODS[i]:
                continue
                
            client = app.state.vpn_clients.get(i)
            if not client:
                continue
                
            # Perform lightweight HEAD check
            try:
                start_time = time.perf_counter()
                resp = await client.build_request("HEAD", "https://1.1.1.1", timeout=1.5)
                await client.send(resp)
                # Success! Reset failures
                VPN_CONSECUTIVE_FAILURES[i] = 0
            except Exception:
                # Failure! Increment consecutive failures
                VPN_CONSECUTIVE_FAILURES[i] += 1
                logger.warning(f"[Heartbeat] VPN {i} check failed (Consecutive: {VPN_CONSECUTIVE_FAILURES[i]})")
                
                # Step 1: Immediate Route Addition
                import subprocess
                route_cmd = f'New-NetRoute -InterfaceAlias "vpn{i}" -DestinationPrefix "0.0.0.0/0" -NextHop "10.8.0.1" -RouteMetric 50 -Confirm:$false -ErrorAction SilentlyContinue'
                await asyncio.to_thread(
                    subprocess.run,
                    ["powershell", "-Command", route_cmd],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                
                # Step 2: Service Restart & Cooldown
                if VPN_CONSECUTIVE_FAILURES[i] >= 3:
                    logger.error(f"[Heartbeat] VPN {i} down for 3s. Triggering service restart...")
                    VPN_CONSECUTIVE_FAILURES[i] = 0
                    VPN_GRACE_PERIODS[i] = now + 15.0  # 15s grace period
                    
                    # Restart service in background thread
                    await asyncio.to_thread(restart_vpn_service, i)
```

- [ ] **Step 3: Start heartbeat loop in lifespan**

Inside `lifespan` context manager, start the background task:
```python
    # Start heartbeat loop
    heartbeat_task = asyncio.create_task(vpn_heartbeat_loop(app))
```
And cancel it on shutdown:
```python
    # On shutdown
    heartbeat_task.cancel()
```

- [ ] **Step 4: Run syntax check**

Run: `python -m py_compile proxy_core/server.py`
Expected: PASS with no syntax errors.

- [ ] **Step 5: Commit**

```bash
git add proxy_core/server.py
git commit -m "feat: implement background VPN heartbeat loop"
```

---

### Task 3: Implement Parallelized Startup in `proxy_core/gui.py`

**Files:**
- Modify: `proxy_core/gui.py`

- [ ] **Step 1: Update `run_start` to start tunnels in parallel threads**

Modify `run_start` in `proxy_core/gui.py` to start each tunnel in its own thread and run `wait_for_adapter_and_add_route` independently:

```python
        def run_start():
            import threading
            from proxy_core.rotation import wait_for_adapter_and_add_route
            
            try:
                self.vpn_manager.uninstall_all_services(print_cb=log_queue.put)
                log_queue.put("[GUI] [SYSTEM] Installing and starting all 6 VPN tunnels in parallel...")
                
                def start_single_tunnel(i):
                    name = f"vpn{i}"
                    conf_path = os.path.join(self.vpn_manager.configs_dir, f"{name}.conf")
                    if os.path.exists(conf_path):
                        # Install service
                        subprocess.run(
                            [self.vpn_manager.wg_path, "/installtunnelservice", conf_path],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL
                        )
                        log_queue.put(f"[GUI] [SYSTEM] Service vpn{i} started. Waiting for adapter...")
                        
                        # Wait for adapter and add route
                        if wait_for_adapter_and_add_route(i, timeout=15.0):
                            log_queue.put(f"[GUI] [SUCCESS] VPN {i} is fully ready and routed!")
                        else:
                            log_queue.put(f"[GUI] [WARNING] VPN {i} failed to initialize route within timeout.")
                    else:
                        log_queue.put(f"[GUI] [ERROR] Config not found for vpn{i}")
                
                threads = []
                for i in range(1, 7):
                    t = threading.Thread(target=start_single_tunnel, args=(i,), daemon=True)
                    t.start()
                    threads.append(t)
                    
                # Wait for all threads to complete
                for t in threads:
                    t.join()
                    
                log_queue.put("[GUI] [SUCCESS] Parallel VPN startup completed!")
            except Exception as e:
                logger.error(f"[GUI] Error starting tunnels: {e}")
                log_queue.put(f"[GUI] [ERROR] Error starting tunnels: {e}")
```

- [ ] **Step 2: Run syntax check**

Run: `python -m py_compile proxy_core/gui.py`
Expected: PASS with no syntax errors.

- [ ] **Step 3: Commit**

```bash
git add proxy_core/gui.py
git commit -m "feat: parallelize VPN startup and route configuration"
```

---

### Task 4: Add Parallelism GUI Controls in `proxy_core/gui.py`

**Files:**
- Modify: `proxy_core/gui.py`

- [ ] **Step 1: Add GUI controls for Parallelism**

Add the checkbox, dropdown, and slider to `proxy_core/gui.py` in the "Active Rotation Configuration" frame:

```python
        # Parallelism Checkbox
        self.parallelism_var = ctk.BooleanVar(value=False)
        self.parallelism_cb = ctk.CTkCheckBox(
            self.right_manager_frame,
            text="Enable Parallelism",
            variable=self.parallelism_var,
            command=self.on_save_parallelism_settings
        )
        self.parallelism_cb.grid(row=10, column=0, columnspan=2, padx=10, pady=5, sticky="w")
        
        # Parallel Tunnels Count
        self.parallel_count_var = ctk.IntVar(value=3)
        self.parallel_count_label = ctk.CTkLabel(self.right_manager_frame, text="Parallel Tunnels Count:")
        self.parallel_count_label.grid(row=11, column=0, padx=10, pady=5, sticky="w")
        self.parallel_count_dropdown = ctk.CTkOptionMenu(
            self.right_manager_frame,
            values=[str(i) for i in range(1, 8)],
            variable=self.parallel_count_var,
            command=lambda _: self.on_save_parallelism_settings()
        )
        self.parallel_count_dropdown.grid(row=11, column=1, padx=10, pady=5, sticky="ew")
        
        # Per-Channel Delay
        self.per_channel_delay_var = ctk.DoubleVar(value=0.5)
        self.per_channel_delay_label = ctk.CTkLabel(self.right_manager_frame, text="Per-Channel Delay (sec):")
        self.per_channel_delay_label.grid(row=12, column=0, padx=10, pady=5, sticky="w")
        self.per_channel_delay_slider = ctk.CTkSlider(
            self.right_manager_frame,
            from_=0.1,
            to=2.0,
            number_of_steps=19,
            variable=self.per_channel_delay_var,
            command=lambda _: self.on_save_parallelism_settings()
        )
        self.per_channel_delay_slider.grid(row=12, column=1, padx=10, pady=5, sticky="ew")
```

- [ ] **Step 2: Implement save/load settings**

Add `on_save_parallelism_settings` and update `load_rotation_config` integration:
```python
    def on_save_parallelism_settings(self):
        config = load_rotation_config()
        config["parallelism_enabled"] = self.parallelism_var.get()
        config["parallel_tunnels_count"] = int(self.parallel_count_var.get())
        config["per_channel_delay"] = float(self.per_channel_delay_var.get())
        save_rotation_config(config)
        log_queue.put("[GUI] Parallelism settings saved.")
```

- [ ] **Step 3: Run syntax check**

Run: `python -m py_compile proxy_core/gui.py`
Expected: PASS with no syntax errors.

- [ ] **Step 4: Commit**

```bash
git add proxy_core/gui.py
git commit -m "feat: add Parallelism GUI controls and settings persistence"
```

---

### Task 5: Implement Parallel Request Routing and Delay in `proxy_core/server.py`

**Files:**
- Modify: `proxy_core/server.py`

- [ ] **Step 1: Initialize active slots and backup pool**

Initialize global parallelism state:
```python
# Parallelism State
ACTIVE_SLOTS = [0, 1, 2]  # Default 3 active slots (Clear, VPN 1, VPN 2)
BACKUP_POOL = [3, 4, 5, 6]  # Remaining channels in reserve
REQUEST_COUNT = 0
```

- [ ] **Step 2: Update `_transparent_proxy_attempt` to support Parallelism**

Modify `_transparent_proxy_attempt` to load-balance requests across active slots and enforce per-channel delays:

```python
    global REQUEST_COUNT, ACTIVE_SLOTS, BACKUP_POOL
    
    rotation_config = load_rotation_config()
    parallelism_enabled = rotation_config.get("parallelism_enabled", False)
    parallel_count = rotation_config.get("parallel_tunnels_count", 3)
    per_channel_delay = rotation_config.get("per_channel_delay", 0.5)
    
    # Dynamically adjust active slots and backup pool size
    if len(ACTIVE_SLOTS) != parallel_count:
        all_channels = list(range(7))
        ACTIVE_SLOTS = all_channels[:parallel_count]
        BACKUP_POOL = all_channels[parallel_count:]
        
    if parallelism_enabled:
        # Round-robin selection
        REQUEST_COUNT += 1
        slot_idx = REQUEST_COUNT % len(ACTIVE_SLOTS)
        current_vpn_index = ACTIVE_SLOTS[slot_idx]
    else:
        current_vpn_index = VPN_CURRENT_INDEX
        
    # Per-channel delay enforcement
    now = time.time()
    if parallelism_enabled:
        time_since_last = now - LAST_REQUEST_TIME.get((provider_name, current_vpn_index), 0.0)
        if time_since_last < per_channel_delay:
            await asyncio.sleep(per_channel_delay - time_since_last)
        LAST_REQUEST_TIME[(provider_name, current_vpn_index)] = time.time()
    else:
        time_since_last = now - LAST_REQUEST_TIME.get(provider_name, 0.0)
        if time_since_last < 0.5:  # Global delay
            await asyncio.sleep(0.5 - time_since_last)
        LAST_REQUEST_TIME[provider_name] = time.time()
```

- [ ] **Step 3: Implement slot rotation on 429 or failure**

If a request fails or hits a 429, rotate the slot:
```python
    if parallelism_enabled and response.status_code == 429:
        failed_channel = ACTIVE_SLOTS[slot_idx]
        if BACKUP_POOL:
            new_channel = BACKUP_POOL.pop(0)
            ACTIVE_SLOTS[slot_idx] = new_channel
            BACKUP_POOL.append(failed_channel)
            logger.info(f"[Parallelism] Slot {slot_idx} rotated: Channel {failed_channel} -> Channel {new_channel}")
```

- [ ] **Step 4: Run syntax check**

Run: `python -m py_compile proxy_core/server.py`
Expected: PASS with no syntax errors.

- [ ] **Step 5: Commit**

```bash
git add proxy_core/server.py
git commit -m "feat: implement parallel request routing, per-channel delays, and slot rotation"
```
