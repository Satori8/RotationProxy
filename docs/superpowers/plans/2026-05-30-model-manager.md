# Model Manager Hub Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a CustomTkinter-based Model Manager Hub featuring live OpenRouter free model scanning, async diagnostic test button ("Hi" message), and drag-and-drop-like Up/Down priority sorting for model rotation with instant configuration saving.

**Architecture:** 
- Expose `POST /control/test_model` in `proxy_core/server.py` to securely test individual models via OpenRouter in the background.
- Replace the right-hand panel of the GUI with a `CTkTabview` containing "Console Logs" and "Model Manager" tabs.
- Implement background-threaded HTTP fetching for OpenRouter free models.
- Implement an in-memory priority editor in the GUI that updates `config_rotation.json` on save, instantly reloading the server state.

**Tech Stack:** Python 3.10+, FastAPI, CustomTkinter, HTTPX, Urllib.

---

### Task 1: Create Backend Diagnostic Endpoint

**Files:**
- Modify: `proxy_core/server.py`

- [ ] **Step 1: Implement the test_model endpoint**
Add the `/control/test_model` POST endpoint to `proxy_core/server.py` right above the lifespan event handler (or around line 290):

```python
class TestModelRequest(BaseModel):
    model: str
    provider: str

@app.post("/control/test_model")
async def test_model_endpoint(req: TestModelRequest, request: Request):
    """Securely test a model via the proxy in the background to check for 200, 429, or 404."""
    model_id = req.model
    provider_name = req.provider
    
    # Resolve keys pool and base URL
    if provider_name == "openrouter":
        base_url = "https://openrouter.ai/api/v1"
        keys_pool = OPENROUTER_KEYS
    elif provider_name == "mistral":
        base_url = "https://api.mistral.ai/v1"
        keys_pool = MISTRAL_KEYS
    elif provider_name == "llm7":
        base_url = "https://api.llm7.io/v1"
        keys_pool = LLM7_KEYS
    else:
        base_url = "https://generativelanguage.googleapis.com"
        keys_pool = API_KEYS
        
    if not keys_pool:
        return {"status": "error", "message": f"No keys configured for provider '{provider_name}'."}
        
    # Pick the first available key (not on cooldown)
    api_key = keys_pool[0]
    headers = {"Content-Type": "application/json"}
    if provider_name in ("openrouter", "mistral", "llm7"):
        headers["authorization"] = f"Bearer {api_key}"
    else:
        headers["x-goog-api-key"] = api_key
        
    # Build payload
    test_body = {
        "model": model_id,
        "messages": [{"role": "user", "content": "Hi"}]
    }
    
    url = f"{base_url}/chat/completions"
    client = request.app.state.client
    
    try:
        req_out = client.build_request(
            method="POST",
            url=url,
            headers=headers,
            content=json.dumps(test_body).encode("utf-8")
        )
        resp = await client.send(req_out, timeout=10.0)
        status_code = resp.status_code
        await resp.aclose()
        
        if status_code == 200:
            return {"status": "ok", "message": "Model responded successfully!"}
        elif status_code == 429:
            return {"status": "rate_limited", "message": "Rate limit exceeded (429)"}
        elif status_code == 404:
            return {"status": "not_found", "message": "Model not found (404)"}
        else:
            return {"status": "error", "message": f"Server returned status {status_code}"}
    except Exception as e:
        return {"status": "error", "message": f"Network/Connection error: {e}"}
```

Make sure to import `BaseModel` from `pydantic` in `proxy_core/server.py` if not already present.

- [ ] **Step 2: Verify syntax and compile**
Run: `python -m py_compile proxy_core/server.py`
Expected: Success

- [ ] **Step 3: Commit changes**
Run:
```bash
git add proxy_core/server.py
git commit -m "feat(server): add POST /control/test_model endpoint for live diagnostics"
```

---

### Task 2: Implement CTkTabview Right Panel Layout

**Files:**
- Modify: `proxy_core/gui.py`

- [ ] **Step 1: Replace right_panel content with CTkTabview**
Surgically replace the text-box loading code in `gui.py` (lines 203-222) with a modern `CTkTabview`:

```python
        self.right_panel = ctk.CTkFrame(self, corner_radius=10)
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.right_panel.grid(row=0, column=1, padx=10, pady=10, sticky="nsew")
        self.right_panel.grid_columnconfigure(0, weight=1)
        self.right_panel.grid_rowconfigure(0, weight=1)

        # Tabview for separation
        self.tabview = ctk.CTkTabview(self.right_panel)
        self.tabview.grid(row=0, column=0, padx=5, pady=5, sticky="nsew")
        
        self.tabview.add("Console Logs")
        self.tabview.add("Model Manager")

        # Tab 1: Console Logs
        self.tab_logs = self.tabview.tab("Console Logs")
        self.tab_logs.grid_columnconfigure(0, weight=1)
        self.tab_logs.grid_rowconfigure(0, weight=1)

        self.log_textbox = ctk.CTkTextbox(
            self.tab_logs,
            font=ctk.CTkFont(family="Consolas", size=11),
            fg_color="#1E1E1E",
            text_color="#F8F8F2",
        )
        self.log_textbox.grid(row=0, column=0, padx=10, pady=(10, 5), sticky="nsew")
        
        self.log_textbox.tag_config("info", foreground="#2ECC71")  # Emerald green
        self.log_textbox.tag_config("warning", foreground="#F1C40F")  # Sun yellow
        self.log_textbox.tag_config("error", foreground="#E74C3C")  # Alizarin red
        self.log_textbox.tag_config("critical", foreground="#C0392B")  # Dark red
        self.log_textbox.tag_config("debug", foreground="#7F8C8D")  # Asbestos grey

        self.clear_btn = ctk.CTkButton(
            self.tab_logs, text="Clear Logs", command=self.on_clear_logs, width=120
        )
        self.clear_btn.grid(row=1, column=0, pady=10)

        # Tab 2: Model Manager (Placeholder structure for next task)
        self.tab_manager = self.tabview.tab("Model Manager")
        self.tab_manager.grid_columnconfigure(0, weight=1)
        self.tab_manager.grid_columnconfigure(1, weight=1)
        self.tab_manager.grid_rowconfigure(0, weight=1)
```

- [ ] **Step 2: Verify syntax and compile**
Run: `python -m py_compile proxy_core/gui.py`
Expected: Success

- [ ] **Step 3: Commit changes**
Run:
```bash
git add proxy_core/gui.py
git commit -m "feat(gui): integrate CTkTabview layout into right-side panel"
```

---

### Task 3: Build Live Diagnostic Monitor (Left Column)

**Files:**
- Modify: `proxy_core/gui.py`

- [ ] **Step 1: Implement Free Model fetch and diagnostic tester widgets**
Add the layout and callbacks to build the OpenRouter free models list and testing actions inside `self.tab_manager`:

```python
        # Left Side of Manager: Live Diagnostics Monitor
        self.left_manager_frame = ctk.CTkFrame(self.tab_manager, corner_radius=8)
        self.left_manager_frame.grid(row=0, column=0, padx=5, pady=5, sticky="nsew")
        self.left_manager_frame.grid_columnconfigure(0, weight=1)
        self.left_manager_frame.grid_rowconfigure(2, weight=1)

        ctk.CTkLabel(
            self.left_manager_frame,
            text="OpenRouter Free Models",
            font=ctk.CTkFont(size=14, weight="bold")
        ).grid(row=0, column=0, pady=(10, 5))

        self.fetch_btn = ctk.CTkButton(
            self.left_manager_frame,
            text="Fetch Free Models",
            command=self.on_fetch_free_models
        )
        self.fetch_btn.grid(row=1, column=0, padx=10, pady=5, fill="x")

        # Scrollable container for dynamic rows
        self.models_scroll = ctk.CTkScrollableFrame(self.left_manager_frame)
        self.models_scroll.grid(row=2, column=0, padx=10, pady=5, sticky="nsew")
        self.models_scroll.grid_columnconfigure(0, weight=1)

        self.loaded_models_data = [] # List to track rendered widgets
```

- [ ] **Step 2: Implement the callbacks for Fetching and Testing**
Add these helper methods to `ProxyGUI` class in `proxy_core/gui.py` (near other `on_` callback methods):

```python
    def on_fetch_free_models(self):
        """Asynchronously fetch free models in a background thread."""
        self.fetch_btn.configure(state="disabled", text="Fetching...")
        
        def do_fetch():
            import urllib.request
            url = "https://openrouter.ai/api/v1/models"
            try:
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=8.0) as response:
                    data = json.loads(response.read().decode('utf-8'))
                    free_models = []
                    for m in data.get('data', []):
                        pricing = m.get('pricing', {})
                        is_prompt_free = float(pricing.get('prompt', 0)) == 0.0
                        is_completion_free = float(pricing.get('completion', 0)) == 0.0
                        if is_prompt_free and is_completion_free:
                            free_models.append({
                                'id': m.get('id'),
                                'name': m.get('name'),
                                'context_length': m.get('context_length', 'unknown')
                            })
                    # Sort by id
                    free_models = sorted(free_models, key=lambda x: x['id'])
                    self.after(0, lambda: self.render_free_models(free_models))
            except Exception as e:
                logger.error(f"[GUI] Failed to fetch free models: {e}")
                self.after(0, lambda: self.fetch_btn.configure(state="normal", text="Fetch Free Models"))
                
        threading.Thread(target=do_fetch, daemon=True).start()

    def render_free_models(self, models):
        """Render list of models in the scrollable frame."""
        # Clear previous widgets
        for widget in self.models_scroll.winfo_children():
            widget.destroy()
        self.loaded_models_data.clear()

        for idx, m in enumerate(models):
            row_frame = ctk.CTkFrame(self.models_scroll, fg_color="transparent")
            row_frame.grid(row=idx, column=0, padx=2, pady=4, sticky="ew")
            row_frame.grid_columnconfigure(0, weight=1)

            # Info text (ID and context)
            info_text = f"{m['name']}\n({m['id']})\nCtx: {m['context_length']}"
            lbl = ctk.CTkLabel(row_frame, text=info_text, font=ctk.CTkFont(size=10), justify="left")
            lbl.grid(row=0, column=0, padx=5, pady=2, sticky="w")

            # Status Badge (circle indicator)
            badge = ctk.CTkLabel(row_frame, text="●", text_color="#7F8C8D", font=ctk.CTkFont(size=16))
            badge.grid(row=0, column=1, padx=5)

            # Test Button
            test_cb = lambda model_id=m['id'], b=badge: self.on_test_individual_model(model_id, b)
            btn_test = ctk.CTkButton(row_frame, text="Test", width=45, height=20, font=ctk.CTkFont(size=9), command=test_cb)
            btn_test.grid(row=0, column=2, padx=2)

            # Add to Rotation Button
            add_cb = lambda model_id=m['id']: self.on_add_model_to_rotation(model_id)
            btn_add = ctk.CTkButton(row_frame, text="+ Add", width=45, height=20, font=ctk.CTkFont(size=9), fg_color="#27AE60", hover_color="#2ECC71", command=add_cb)
            btn_add.grid(row=0, column=3, padx=2)

        self.fetch_btn.configure(state="normal", text="Fetch Free Models")

    def on_test_individual_model(self, model_id, badge_widget):
        """Test a model via background thread and update its status indicator badge."""
        badge_widget.configure(text_color="#F1C40F") # Yellow for testing...
        
        def do_test():
            import httpx
            url = f"http://{self.host}:{self.port}/control/test_model"
            try:
                r = httpx.post(url, json={"model": model_id, "provider": "openrouter"}, timeout=12.0)
                if r.status_code == 200:
                    res = r.json()
                    status = res.get("status")
                    if status == "ok":
                        self.after(0, lambda: badge_widget.configure(text_color="#2ECC71")) # Green
                    elif status == "rate_limited":
                        self.after(0, lambda: badge_widget.configure(text_color="#E67E22")) # Orange (429)
                    else:
                        self.after(0, lambda: badge_widget.configure(text_color="#E74C3C")) # Red (404/Error)
                else:
                    self.after(0, lambda: badge_widget.configure(text_color="#E74C3C"))
            except Exception:
                self.after(0, lambda: badge_widget.configure(text_color="#E74C3C"))

        threading.Thread(target=do_test, daemon=True).start()
```

- [ ] **Step 3: Verify syntax and compile**
Run: `python -m py_compile proxy_core/gui.py`
Expected: Success

- [ ] **Step 4: Commit changes**
Run:
```bash
git add proxy_core/gui.py
git commit -m "feat(gui): build free model scan frame and async test runner"
```

---

### Task 4: Build Active Rotation Configurator (Right Column)

**Files:**
- Modify: `proxy_core/gui.py`

- [ ] **Step 1: Implement Rotation priorities GUI list & Save callback**
Add the list and order sorting widgets in the right column of the Model Manager tab:

```python
        # Right Side of Manager: Active Rotation Configuration
        self.right_manager_frame = ctk.CTkFrame(self.tab_manager, corner_radius=8)
        self.right_manager_frame.grid(row=0, column=1, padx=5, pady=5, sticky="nsew")
        self.right_manager_frame.grid_columnconfigure(0, weight=1)
        self.right_manager_frame.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(
            self.right_manager_frame,
            text="Active Rotation Configuration",
            font=ctk.CTkFont(size=14, weight="bold")
        ).grid(row=0, column=0, pady=(10, 5))

        self.rotation_scroll = ctk.CTkScrollableFrame(self.right_manager_frame)
        self.rotation_scroll.grid(row=1, column=0, padx=10, pady=5, sticky="nsew")
        self.rotation_scroll.grid_columnconfigure(0, weight=1)

        self.save_rotation_btn = ctk.CTkButton(
            self.right_manager_frame,
            text="Save Rotation Config",
            fg_color="#2980B9",
            hover_color="#3498DB",
            command=self.on_save_active_rotation
        )
        self.save_rotation_btn.grid(row=2, column=0, padx=10, pady=10, fill="x")

        # Load active rotation models on start
        self.active_rotation_list = []
        self.load_active_rotation_from_disk()
```

- [ ] **Step 2: Implement rotation state actions (Up, Down, Remove, Add)**
Add these order manipulation methods inside the `ProxyGUI` class in `proxy_core/gui.py`:

```python
    def load_active_rotation_from_disk(self):
        """Load and display the active rotation list from config."""
        config = load_rotation_config()
        self.active_rotation_list = config.get("rotation_lists", {}).get("gemini-3.6-flash", [])
        self.render_rotation_list()

    def render_rotation_list(self):
        """Render the ordered rotation models in the configurator frame."""
        for widget in self.rotation_scroll.winfo_children():
            widget.destroy()

        for idx, model_id in enumerate(self.active_rotation_list):
            row_frame = ctk.CTkFrame(self.rotation_scroll, fg_color="transparent")
            row_frame.grid(row=idx, column=0, padx=2, pady=2, sticky="ew")
            row_frame.grid_columnconfigure(0, weight=1)

            lbl = ctk.CTkLabel(row_frame, text=model_id, font=ctk.CTkFont(size=10, weight="bold"))
            lbl.grid(row=0, column=0, padx=5, pady=2, sticky="w")

            # Check core boundaries (don't allow removing gemini-3.6-flash)
            if model_id != "gemini-3.6-flash":
                # Up button
                up_cb = lambda i=idx: self.on_shift_model_priority(i, direction=-1)
                btn_up = ctk.CTkButton(row_frame, text="▲", width=22, height=18, font=ctk.CTkFont(size=8), command=up_cb)
                btn_up.grid(row=0, column=1, padx=1)

                # Down button
                down_cb = lambda i=idx: self.on_shift_model_priority(i, direction=1)
                btn_down = ctk.CTkButton(row_frame, text="▼", width=22, height=18, font=ctk.CTkFont(size=8), command=down_cb)
                btn_down.grid(row=0, column=2, padx=1)

                # Remove button
                del_cb = lambda m=model_id: self.on_remove_model_from_rotation(m)
                btn_del = ctk.CTkButton(row_frame, text="✕", width=22, height=18, text_color="#E74C3C", font=ctk.CTkFont(size=8), fg_color="transparent", hover_color="#2c2c2c", command=del_cb)
                btn_del.grid(row=0, column=3, padx=1)

    def on_shift_model_priority(self, index, direction):
        """Shift model priority up (-1) or down (+1) in the rotation list."""
        new_index = index + direction
        if 0 <= new_index < len(self.active_rotation_list):
            # Maintain gemini-3.6-flash boundary at index 0
            if self.active_rotation_list[0] == "gemini-3.6-flash" and (index == 0 or new_index == 0):
                return
            
            # Swap items
            self.active_rotation_list[index], self.active_rotation_list[new_index] = \
                self.active_rotation_list[new_index], self.active_rotation_list[index]
            self.render_rotation_list()

    def on_remove_model_from_rotation(self, model_id):
        """Remove a model from the local in-memory rotation list."""
        if model_id != "gemini-3.6-flash" and model_id in self.active_rotation_list:
            self.active_rotation_list.remove(model_id)
            self.render_rotation_list()

    def on_add_model_to_rotation(self, model_id):
        """Add a model from scan to the end of the local in-memory rotation list."""
        if model_id not in self.active_rotation_list:
            self.active_rotation_list.append(model_id)
            self.render_rotation_list()
            logger.info(f"[GUI] Added model '{model_id}' to current rotation configuration.")

    def on_save_active_rotation(self):
        """Save the configured rotation lists to config_rotation.json."""
        try:
            config = load_rotation_config()
            if "rotation_lists" not in config:
                config["rotation_lists"] = {}
            config["rotation_lists"]["gemini-3.6-flash"] = list(self.active_rotation_list)
            save_rotation_config(config)
            logger.info("[GUI] Successfully saved active rotation configuration on disk!")
            log_queue.put("[GUI] Successfully saved active rotation configuration!")
        except Exception as e:
            logger.error(f"[GUI] Failed to save rotation config: {e}")
            log_queue.put(f"[GUI] [ERROR] Failed to save rotation config: {e}")
```

- [ ] **Step 3: Verify syntax and compile**
Run: `python -m py_compile proxy_core/gui.py`
Expected: Success

- [ ] **Step 4: Commit changes**
Run:
```bash
git add proxy_core/gui.py
git commit -m "feat(gui): build rotation priority list, shift-sorting handlers, and save action"
```

---

### Task 5: End-to-End System Testing & Integration

**Files:**
- Test: Manual integration run using `proxy3.py --gui`

- [ ] **Step 1: Spin up the GUI**
Run: `python proxy3.py --gui`
Expected: Main window loads up successfully, exhibiting a `CTkTabview` in the right-side panel with "Console Logs" and "Model Manager" tabs.

- [ ] **Step 2: Fetch free models**
Select "Model Manager" tab, click **"Fetch Free Models"**.
Expected: Fetches from OpenRouter API smoothly in a background thread and populates the left scrollable list with 20+ active free models with grey status dots.

- [ ] **Step 3: Test a model dynamically**
Click the **"Test"** button next to `"openrouter/owl-alpha"` (or any other free model).
Expected: Status badge turns Yellow, queries the secure `/control/test_model` backend endpoint with a test "Hi", and turns Green (or Orange/Red if blocked/dead) on response.

- [ ] **Step 4: Update priority**
Click the **"Add"** button on several free models, use **"▲"** and **"▼"** to sort priorities, and click **"Save Rotation Config"**. Check `config_rotation.json` to verify correct persistent tracking.
Expected: Config saves cleanly, and subsequent proxy queries dynamically adhere to the new sorted priority!

- [ ] **Step 5: Final git cleanup**
Verify working directory is clean:
Run: `git status`
Expected: Working tree clean.
