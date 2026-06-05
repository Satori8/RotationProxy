# Multi-Channel VPN and Expanded Model Scanner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform the single-lamp VPN status indicator into a 6-channel real-time status and ping monitor (updated every 15 seconds), and expand the API tester scanner to support Ollama and LLM7 providers.

**Architecture:** Use multi-threaded asynchronous checks for VPN services and ping latency (via bound local IPs). Add dropdown selections to GUI model tester to select provider, load Ollama/LLM7 keys from Vault, and handle testing endpoints.

**Tech Stack:** Python, CustomTkinter, httpx, FastAPI, Windows PowerShell (Get-Service)

---

### Task 1: Load Ollama Keys and Update Rotation

**Files:**
- Modify: `proxy_core/rotation.py`

- [ ] **Step 1: Read the keys file path and load OLLAMA keys**

Add `OLLAMA_KEYS_FILE` and load `OLLAMA_KEYS`:
```python
OLLAMA_KEYS_FILE = r"D:\Personal\myvault\90 Private\Sensitive\Ollama API Keys.md"
# ...
OLLAMA_KEYS = load_keys_from_file(OLLAMA_KEYS_FILE)
```

Ensure `OLLAMA_KEYS` is exported in `__all__` or simply accessible.

- [ ] **Step 2: Verify import / load succeeds**
Run python syntax check or a quick import check to confirm `OLLAMA_KEYS` loading is robust.

- [ ] **Step 3: Commit**
```bash
git add proxy_core/rotation.py
git commit -m "feat(rotation): load and export Ollama API keys from Vault"
```

---

### Task 2: Support Ollama in Server Testing Endpoint

**Files:**
- Modify: `proxy_core/server.py`

- [ ] **Step 1: Import OLLAMA_KEYS and update test_model_endpoint**

Import `OLLAMA_KEYS` at the top:
```python
from proxy_core.rotation import (
    API_KEYS,
    OPENROUTER_KEYS,
    MISTRAL_KEYS,
    LLM7_KEYS,
    OLLAMA_KEYS,  # Add this
    seconds_until_rpd_reset,
    log_non_429_error,
    remove_key_from_error_log,
)
```

Update `@app.post("/control/test_model")` to resolve `"ollama"`:
```python
    elif provider_name == "ollama":
        base_url = "http://localhost:11434/v1"
        keys_pool = OLLAMA_KEYS if OLLAMA_KEYS else ["dummy"]
```

And headers:
```python
    if provider_name in ("openrouter", "mistral", "llm7", "ollama"):
        headers["authorization"] = f"Bearer {api_key}"
```

- [ ] **Step 2: Verify server starts and accepts test_model requests for Ollama**

- [ ] **Step 3: Commit**
```bash
git add proxy_core/server.py
git commit -m "feat(server): add ollama provider support to control/test_model endpoint"
```

---

### Task 3: Redesign GUI VPN Status Indicator into Per-Channel Grid

**Files:**
- Modify: `proxy_core/gui.py`

- [ ] **Step 1: Replace self.vpn_status_indicator in GUI setup**

Replace `self.vpn_status_indicator` with a custom grid container `self.channels_frame` and 6 per-channel CTkLabels:
```python
        # Container for 6 channels
        self.channels_frame = ctk.CTkFrame(self.vpn_control_frame, fg_color="transparent")
        self.channels_frame.grid(row=1, column=0, pady=(0, 20), sticky="ew")
        self.channels_frame.grid_columnconfigure((0, 1), weight=1)

        self.channel_indicators = {}
        for idx in range(1, 7):
            r = (idx - 1) // 2
            c = (idx - 1) % 2
            
            ch_row = ctk.CTkFrame(self.channels_frame, fg_color="transparent")
            ch_row.grid(row=r, column=c, padx=10, pady=5, sticky="ew")
            ch_row.grid_columnconfigure(1, weight=1)
            
            lbl_name = ctk.CTkLabel(
                ch_row, text=f"VPN {idx}:", font=ctk.CTkFont(size=11, weight="bold")
            )
            lbl_name.grid(row=0, column=0, padx=(5, 5), sticky="w")
            
            lbl_status = ctk.CTkLabel(
                ch_row, text="● Off", text_color="#7F8C8D", font=ctk.CTkFont(size=11)
            )
            lbl_status.grid(row=0, column=1, padx=(0, 5), sticky="w")
            
            self.channel_indicators[idx] = lbl_status
```

- [ ] **Step 2: Commit**
```bash
git add proxy_core/gui.py
git commit -m "feat(gui): replace single VPN status lamp with 6-channel grid UI"
```

---

### Task 4: Implement Non-blocking Per-Channel Status Check in GUI

**Files:**
- Modify: `proxy_core/gui.py`

- [ ] **Step 1: Update polling interval to 15 seconds**

Modify `poll_vpn_status_loop`:
```python
    def poll_vpn_status_loop(self):
        """Periodic loop to poll the status of VPN tunnels every 15 seconds."""
        self.do_poll_vpn_status()
        self.after(15000, self.poll_vpn_status_loop)
```

- [ ] **Step 2: Rewrite do_poll_vpn_status to check service + ping in parallel**

```python
    def do_poll_vpn_status(self):
        """Run per-channel checks on background threads to prevent UI lag."""
        if not hasattr(self, "vpn_manager") or self.vpn_manager is None:
            return

        def run_check():
            results = {}
            threads = []

            # 1. Get running services status via fast single PS command
            active_services = []
            try:
                output, _ = self.vpn_manager.run_ps_cmd(
                    'Get-Service -Name "WireGuardTunnel$*" | Where-Object {$_.Status -eq "Running"} | Select-Object -ExpandProperty Name'
                )
                active_services = [line.strip() for line in output.split("\n") if line.strip()]
            except Exception as e:
                logger.error(f"[VPN Status] Error checking services: {e}")

            # 2. Check channel function
            def check_channel(idx):
                service_name = f"WireGuardTunnel$vpn{idx}"
                is_running = any(service_name in svc for svc in active_services)
                
                if not is_running:
                    results[idx] = {"running": False, "ping": None}
                    return
                
                # Check internet connection / latency via bound IP
                local_ip = f"10.8.0.1{idx}"
                start_time = time.perf_counter()
                try:
                    import httpx
                    transport = httpx.HTTPTransport(local_address=local_ip)
                    with httpx.Client(transport=transport, timeout=2.0) as client:
                        resp = client.get("https://api.ipify.org")
                        if resp.status_code == 200:
                            latency_ms = int((time.perf_counter() - start_time) * 1000)
                            results[idx] = {"running": True, "ping": latency_ms}
                            return
                except Exception:
                    pass
                results[idx] = {"running": True, "ping": -1} # Running but offline

            # Start 6 parallel threads
            for i in range(1, 7):
                t = threading.Thread(target=check_channel, args=(i,), daemon=True)
                threads.append(t)
                t.start()

            for t in threads:
                t.join(timeout=3.0)

            # Update GUI
            def update_gui():
                for idx, res in results.items():
                    widget = self.channel_indicators.get(idx)
                    if not widget:
                        continue
                    if not res["running"]:
                        widget.configure(text="● Off", text_color="#7F8C8D") # Grey
                    elif res["ping"] == -1:
                        widget.configure(text="● Offline", text_color="#E74C3C") # Red
                    else:
                        widget.configure(text=f"● {res['ping']}ms", text_color="#2ECC71") # Green

            self.after(0, update_gui)

        threading.Thread(target=run_check, daemon=True).start()
```

- [ ] **Step 3: Commit**
```bash
git add proxy_core/gui.py
git commit -m "feat(gui): implement parallel service status and latency checks for VPN channels"
```

---

### Task 5: Add Provider Dropdown and Update Fetching in GUI Scanner

**Files:**
- Modify: `proxy_core/gui.py`

- [ ] **Step 1: Replace OpenRouter Free Models header with CTkOptionMenu**

Change:
```python
        ctk.CTkLabel(
            self.left_manager_frame,
            text="API Model Tester",
            font=ctk.CTkFont(size=14, weight="bold"),
        ).grid(row=0, column=0, pady=(10, 5))

        # Provider Selector
        self.tester_provider_var = ctk.StringVar(value="OpenRouter")
        self.tester_provider_menu = ctk.CTkOptionMenu(
            self.left_manager_frame,
            values=["OpenRouter", "Ollama", "LLM7"],
            variable=self.tester_provider_var,
        )
        self.tester_provider_menu.grid(row=1, column=0, padx=10, pady=5, sticky="ew")

        self.fetch_btn = ctk.CTkButton(
            self.left_manager_frame,
            text="Fetch Models",
            command=self.on_fetch_free_models,
        )
        self.fetch_btn.grid(row=2, column=0, padx=10, pady=5, sticky="ew")

        # Scrollable container for dynamic rows
        self.models_scroll = ctk.CTkScrollableFrame(self.left_manager_frame)
        self.models_scroll.grid(row=3, column=0, padx=10, pady=5, sticky="nsew")
        self.models_scroll.grid_columnconfigure(0, weight=1)
```

And adjust the grid configuration:
```python
        self.left_manager_frame.grid_rowconfigure(3, weight=1) # Row 3 is now scrollable frame
```

- [ ] **Step 2: Update on_fetch_free_models to support multi-provider model scanning**

Update `on_fetch_free_models` to handle Ollama and LLM7:
```python
    def on_fetch_free_models(self):
        """Asynchronously fetch models from selected provider in a background thread."""
        provider = self.tester_provider_var.get()
        self.fetch_btn.configure(state="disabled", text=f"Fetching {provider}...")

        def do_fetch():
            import urllib.request
            
            try:
                headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
                
                if provider == "OpenRouter":
                    url = "https://openrouter.ai/api/v1/models"
                    req = urllib.request.Request(url, headers=headers)
                    with urllib.request.urlopen(req, timeout=8.0) as response:
                        data = json.loads(response.read().decode("utf-8"))
                        free_models = []
                        for m in data.get("data", []):
                            pricing = m.get("pricing", {})
                            is_prompt_free = float(pricing.get("prompt", 0)) == 0.0
                            is_completion_free = float(pricing.get("completion", 0)) == 0.0
                            if is_prompt_free and is_completion_free:
                                free_models.append(
                                    {
                                        "id": m.get("id"),
                                        "name": m.get("name"),
                                        "context_length": m.get(
                                            "context_length", "unknown"
                                        ),
                                        "provider": "openrouter",
                                    }
                                )
                        free_models = sorted(free_models, key=lambda x: x["id"])
                        self.after(0, lambda: self.render_free_models(free_models))
                        
                elif provider == "Ollama":
                    url = "https://ollama.com/api/tags"
                    req = urllib.request.Request(url, headers=headers)
                    with urllib.request.urlopen(req, timeout=8.0) as response:
                        data = json.loads(response.read().decode("utf-8"))
                        models = []
                        for m in data.get("models", []):
                            models.append(
                                {
                                    "id": m.get("model"),
                                    "name": m.get("name"),
                                    "context_length": "unknown",
                                    "provider": "ollama",
                                }
                            )
                        models = sorted(models, key=lambda x: x["id"])
                        self.after(0, lambda: self.render_free_models(models))
                        
                elif provider == "LLM7":
                    url = "https://api.llm7.io/v1/models"
                    from proxy_core.rotation import LLM7_KEYS
                    if LLM7_KEYS:
                        headers["Authorization"] = f"Bearer {LLM7_KEYS[0]}"
                    req = urllib.request.Request(url, headers=headers)
                    with urllib.request.urlopen(req, timeout=8.0) as response:
                        data = json.loads(response.read().decode("utf-8"))
                        models = []
                        for m in data:
                            ctx = m.get("context_window")
                            if isinstance(ctx, dict):
                                context_length = ctx.get("tokens", "unknown")
                            else:
                                context_length = ctx if ctx else "unknown"
                            models.append(
                                {
                                    "id": m.get("id"),
                                    "name": m.get("id"),
                                    "context_length": context_length,
                                    "provider": "llm7",
                                }
                            )
                        models = sorted(models, key=lambda x: x["id"])
                        self.after(0, lambda: self.render_free_models(models))
                        
            except Exception as e:
                logger.error(f"[GUI] Failed to fetch {provider} models: {e}")
                self.after(
                    0,
                    lambda: self.fetch_btn.configure(
                        state="normal", text="Fetch Models"
                    ),
                )

        threading.Thread(target=do_fetch, daemon=True).start()
```

- [ ] **Step 3: Update render_free_models and test callbacks**

```python
    def render_free_models(self, models):
        ...
            # Test Button
            test_cb = lambda model_id=m["id"], p=m.get("provider", "openrouter"), b=badge: self.on_test_individual_model(
                model_id, p, b
            )
```

And in `on_test_individual_model`:
```python
    def on_test_individual_model(self, model_id, provider, badge_widget):
        badge_widget.configure(
            text_color="#F1C40F", text="● ..."
        )

        def do_test():
            import httpx

            url = f"http://{self.host}:{self.port}/control/test_model"
            try:
                r = httpx.post(
                    url,
                    json={"model": model_id, "provider": provider},
                    timeout=12.0,
                )
```

Update `self.fetch_btn.configure` at the end of `render_free_models` to say `"Fetch Models"` instead of `"Fetch Free Models"`.

- [ ] **Step 4: Commit**
```bash
git add proxy_core/gui.py
git commit -m "feat(gui): expand Model Scanner to scan and test Ollama & LLM7 providers"
```
