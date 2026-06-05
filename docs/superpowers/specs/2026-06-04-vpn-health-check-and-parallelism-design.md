# Design Spec: VPN Health Check and Parallelism System

## 1. Overview
This specification defines the architecture and implementation details for a robust VPN Health Check (Heartbeat) and Parallelism System inside the Resilient Key Rotation Proxy (`proxy3`).

The system ensures 100% uptime and stability of 6 virtual WireGuard VPN tunnels and 1 clear/non-VPN channel (7 channels in total) by actively monitoring their health and dynamically load-balancing requests across them in parallel.

---

## 2. Architecture & Components

### 2.1 VPN Health Check & Heartbeat System (In-Proxy)
A background `asyncio` task runs continuously inside the FastAPI server lifespan:
* **Frequency**: Runs once every 1.0 second.
* **Check**: Performs a lightweight `HEAD` request to `https://1.1.1.1` with a 1.5-second timeout using the bound client for each of the 6 VPN channels.
* **Grace Period**: If a channel is in a "Grace Period" (e.g., after a service restart), the health check for that channel is skipped.

### 2.2 Recovery Pipeline (Fast & Non-Blocking)
If a channel check fails:
1. **Step 1 (Immediate Route Addition)**: Directly run the PowerShell command to add the route, ignoring errors if it already exists:
   ```powershell
   New-NetRoute -InterfaceAlias "vpnX" -DestinationPrefix "0.0.0.0/0" -NextHop "10.8.0.1" -RouteMetric 50 -Confirm:$false -ErrorAction SilentlyContinue
   ```
2. **Step 2 (Service Restart & Cooldown)**: If the channel remains down for **3 consecutive checks** (3 seconds):
   * Run `Restart-Service -Name "WireGuardTunnel$vpnX" -ErrorAction SilentlyContinue` in a background thread.
   * Run `wait_for_adapter_and_add_route(vpn_index)` in that background thread to poll/wait until the adapter physically appears in the system (i.e., has its `10.8.0.X` IP address) before running the route forwarding command.
   * Place the channel on a **15-second Grace Period** (cooldown) during which all health checks for this channel are skipped.

### 2.3 Main Startup Logic (Parallelized & Independent)
Instead of starting all services and waiting for *all* of them to appear before running a global script, we parallelize the startup of each tunnel independently:
* **Parallel Threads**: Spawn **6 parallel threads** (one for each tunnel).
* **Independent Lifecycle**: Each thread will:
  1. Install and start its specific service (`vpnX`).
  2. Run `wait_for_adapter_and_add_route(vpn_index)`.
  3. Mark that specific tunnel as "Ready" in the GUI the instant its route is configured.

---

## 3. Parallelism System & GUI Controls

### 3.1 GUI Controls (In `proxy_core/gui.py`)
We will add a new "Parallelism & Performance" section to the GUI:
* **Checkbox**: `Enable Parallelism` (Saves `parallelism_enabled: bool` to `config_rotation.json`).
* **Dropdown/Slider**: `Parallel Tunnels Count` (Range: `1` to `7`, default `3`. Saves `parallel_tunnels_count: int` to `config_rotation.json`).
* **Slider**: `Per-Channel Delay (sec)` (Range: `0.1` to `2.0`, default `0.5`. Saves `per_channel_delay: float` to `config_rotation.json`).

### 3.2 Parallelism Logic & Active Slots (In `proxy_core/server.py`)
When Parallelism is enabled, we divide our 7 active channels (index `0` to `6`) into two pools:
1. **Active Slots**: A list of $N$ channels currently actively routing requests (where $N$ is the `Parallel Tunnels Count`, e.g., `3`).
   * *Example*: Active Slots = `[0, 1, 2]` (Clear, VPN 1, VPN 2).
2. **Backup Pool**: The remaining $7 - N$ channels waiting in reserve.
   * *Example*: Backup Pool = `[3, 4, 5, 6]` (VPN 3, VPN 4, VPN 5, VPN 6).

### 3.3 Request Routing & Load Balancing
When a request comes in:
1. **Round-Robin Selection**: We select the next active slot in sequence:
   ```python
   slot_idx = request_count % len(active_slots)
   channel_index = active_slots[slot_idx]
   ```
2. **Per-Channel Delay Enforcement**: Instead of a global delay, we enforce the delay **only on that specific channel**:
   ```python
   now = time.time()
   time_since_last = now - LAST_REQUEST_TIME.get((provider_name, channel_index), 0.0)
   if time_since_last < per_channel_delay:
       await asyncio.sleep(per_channel_delay - time_since_last)
   LAST_REQUEST_TIME[(provider_name, channel_index)] = time.time()
   ```

### 3.4 Active Slot Rotation (On 429 or Health Check Failure)
If a request on `channel_index` (assigned to `active_slots[slot_idx]`) hits a 429 or fails its health check:
1. **Rotate Slot**: We immediately swap that slot's channel with the next available channel from the **Backup Pool**:
   ```python
   failed_channel = active_slots[slot_idx]
   if backup_pool:
       new_channel = backup_pool.pop(0)
       active_slots[slot_idx] = new_channel
       backup_pool.append(failed_channel)  # Place failed channel in backup pool (on cooldown)
       logger.info(f"[Parallelism] Slot {slot_idx} rotated: Channel {failed_channel} -> Channel {new_channel}")
   ```
2. **Cooldown**: The `failed_channel` is placed on cooldown (e.g., 90 seconds) before it can be popped from the backup pool again.
