# Resilient Proxy GUI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a CustomTkinter GUI for our resilient proxy that runs the server as an auto-restarting background subprocess, captures stdout/stderr into the GUI log, writes crash events to `proxy_errors.log`, and allows manual model selection as the top-priority model of the rotation loop.

**Architecture:** The GUI (main thread) manages the server subprocess, automatically restarting it on non-zero exit codes. Manual model selection drops the selected model to the front of the candidate array, preserving fallbacks and rotation logic.

**Tech Stack:** Python 3.12+, CustomTkinter, subprocess, threading, json/regex

---

### Task 1: Update Global State Hooks & CLI Arguments

**Files:**
- Modify: `proxy3.py`

- [ ] **Step 1: Set up manual model priority globals**
Replace `FORCE_PROVIDER` with `FORCE_MODEL`:
```python
FORCE_MODEL = {
    "gemini-3.5-flash": "auto",
    "gemini-flash-lite-latest": "auto"
}
```

- [ ] **Step 2: Commit**
```bash
git add proxy3.py
git commit -m "feat: change provider force hook to priority model force hook"
```

---

### Task 2: Implement Priority Model Injection in Candidate List

**Files:**
- Modify: `proxy3.py`

- [ ] **Step 1: Inject forced model at the top of candidate list**
Inside `transparent_proxy`, modify candidate selection to put the selected model at index 0 of the rotation loop:
```python
    # Enforce manual priority model overrides if set (Auto is default, i.e., "auto")
    forced_model = FORCE_MODEL.get(requested_model, "auto")
    if forced_model != "auto" and forced_model in candidates:
        # Move the forced model to the top priority (front of the list)
        candidates = [forced_model] + [c for c in candidates if c != forced_model]
```

- [ ] **Step 2: Commit**
```bash
git add proxy3.py
git commit -m "feat: implement manual model priority injection in candidates list"
```

---

### Task 3: Build Resilient Subprocess Controller with Auto-Restart

**Files:**
- Modify: `proxy3.py`

- [ ] **Step 1: Implement subprocess runner & output reader**
In the GUI class or helper functions, implement subprocess spawning and real-time output line-by-line reading into `log_queue`:
```python
import subprocess
import sys

def run_server_subprocess(host: str, port: int, reload: bool):
    # To run without command prompt window on Windows:
    startupinfo = None
    if sys.platform == "win32":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0 # SW_HIDE

    # Launch subprocess with sys.executable and arguments (excluding --gui to run background proxy only)
    args = [sys.executable, "proxy3.py", "--host", host, "--port", str(port)]
    if reload:
        args.append("--reload")
        
    return subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        startupinfo=startupinfo
    )
```

- [ ] **Step 2: Implement continuous subprocess health poll and error logger**
Inside the GUI main thread, check every 1000ms if the process is alive. If it exited with a non-zero exit code:
1. Log the crash time and exit code to `proxy_errors.log`.
2. Append a notification to the GUI log.
3. Automatically restart the subprocess.
```python
    def check_subprocess_health(self):
        if hasattr(self, 'server_process') and self.server_process is not None:
            ret_code = self.server_process.poll()
            if ret_code is not None:
                # Process died!
                if ret_code != 0:
                    error_msg = f"Server subprocess crashed/exited with code {ret_code}."
                    logger.error(error_msg)
                    
                    # Write to persistent proxy_errors.log
                    try:
                        with open("proxy_errors.log", "a", encoding="utf-8") as f:
                            import datetime
                            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            f.write(f"[{timestamp}] [ERROR] Subprocess exited with code {ret_code}. Auto-restarting...\n")
                    except Exception as e:
                        logger.error(f"Failed to append to proxy_errors.log: {e}")
                        
                    # Auto-restart
                    self.start_server_subprocess()
                else:
                    logger.info("Server subprocess exited normally.")
                    
        self.after(1000, self.check_subprocess_health)
```

- [ ] **Step 3: Commit**
```bash
git add proxy3.py
git commit -m "feat: implement resilient subprocess controller and auto-restart health check"
```

---

### Task 4: Complete the Updated CustomTkinter GUI

**Files:**
- Modify: `proxy3.py`

- [ ] **Step 1: Write updated `ProxyGUI` class**
Replace `ProxyGUI` with the subprocess and model prioritizer controls. Add list arrays dynamically:
```python
class ProxyGUI(ctk.CTk):
    def __init__(self, host: str, port: int, reload: bool):
        super().__init__()
        self.host = host
        self.port = port
        self.reload = reload
        self.server_process = None
        self.stdout_thread = None
        self.stderr_thread = None
        
        self.title("Resilient Key Rotation Proxy")
        self.geometry("900x600")
        
        # Load custom icon if available
        if os.path.exists("app.ico"):
            try:
                self.iconbitmap("app.ico")
            except Exception as e:
                logger.warning(f"Could not load app.ico: {e}")
                
        # Grid layout
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=2)
        self.grid_rowconfigure(0, weight=1)
        
        # Left Panel (Controls)
        self.left_panel = ctk.CTkFrame(self, width=280, corner_radius=10)
        self.left_panel.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
        self.left_panel.pack_propagate(False)
        
        self.status_title = ctk.CTkLabel(self.left_panel, text="PROXY CONTROLLER", font=ctk.CTkFont(size=16, weight="bold"))
        self.status_title.pack(pady=(15, 5))
        
        self.status_badge = ctk.CTkLabel(self.left_panel, text=f"STATUS: RUNNING (Port {self.port})", font=ctk.CTkFont(size=12, weight="bold"), text_color="#4CAF50")
        self.status_badge.pack(pady=(0, 20))
        
        # Thinking Domain Selector (Auto + Candidates)
        ctk.CTkLabel(self.left_panel, text="Thinking Domain Priority:", font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", padx=20)
        thinking_models = [
            "Auto (Rotation)",
            "gemini-3.5-flash",
            "deepseek/deepseek-r1:free",
            "qwen/qwen-2.5-72b-instruct:free",
            "meta-llama/llama-3.3-70b-instruct:free",
            "deepseek/deepseek-chat:free"
        ]
        self.thinking_select = ctk.CTkOptionMenu(self.left_panel, values=thinking_models, command=self.on_thinking_select)
        self.thinking_select.pack(fill="x", padx=20, pady=(2, 15))
        
        # Quick Domain Selector (Auto + Candidates)
        ctk.CTkLabel(self.left_panel, text="Quick Domain Priority:", font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", padx=20)
        quick_models = [
            "Auto (Rotation)",
            "gemini-flash-lite-latest",
            "deepseek-v4-flash-free",
            "mimo-v2.5-free",
            "nemotron-3-super-free",
            "google/gemini-2.5-flash:free",
            "google/gemma-2-9b-it:free",
            "meta-llama/llama-3.1-8b-instruct:free",
            "qwen/qwen-2.5-coder-32b-instruct:free"
        ]
        self.quick_select = ctk.CTkOptionMenu(self.left_panel, values=quick_models, command=self.on_quick_select)
        self.quick_select.pack(fill="x", padx=20, pady=(2, 15))
        
        # Separator line
        self.sep = ctk.CTkFrame(self.left_panel, height=2, fg_color="gray30")
        self.sep.pack(fill="x", padx=10, pady=10)
        
        # Kaggle Toggle
        self.kaggle_var = ctk.BooleanVar(value=USE_KAGGLE)
        self.kaggle_checkbox = ctk.CTkCheckBox(self.left_panel, text="Use Kaggle (qwen3.6)", variable=self.kaggle_var, command=self.on_kaggle_toggle, font=ctk.CTkFont(size=12, weight="bold"))
        self.kaggle_checkbox.pack(anchor="w", padx=20, pady=(5, 10))
        
        # Kaggle URL field
        ctk.CTkLabel(self.left_panel, text="Kaggle Tunnel URL:", font=ctk.CTkFont(size=11, weight="bold")).pack(anchor="w", padx=20)
        self.url_entry = ctk.CTkEntry(self.left_panel)
        self.url_entry.insert(0, KAGGLE_BASE_URL)
        self.url_entry.pack(fill="x", padx=20, pady=(2, 8))
        
        # Save URL Button
        self.save_url_btn = ctk.CTkButton(self.left_panel, text="Save Kaggle URL", command=self.on_save_url)
        self.save_url_btn.pack(fill="x", padx=20, pady=(0, 20))
        
        # Open Script Folder Button
        self.open_folder_btn = ctk.CTkButton(self.left_panel, text="Open Folder", command=self.on_open_folder, fg_color="#3B3B3B", hover_color="#555555")
        self.open_folder_btn.pack(fill="x", padx=20, pady=(10, 10))
        
        # Right Panel (Logs)
        self.right_panel = ctk.CTkFrame(self, corner_radius=10)
        self.right_panel.grid(row=0, column=1, padx=10, pady=10, sticky="nsew")
        self.right_panel.grid_columnconfigure(0, weight=1)
        self.right_panel.grid_rowconfigure(0, weight=1)
        
        self.log_textbox = ctk.CTkTextbox(self.right_panel, font=ctk.CTkFont(family="Consolas", size=11), fg_color="#1E1E1E", text_color="#F8F8F2")
        self.log_textbox.grid(row=0, column=0, padx=10, pady=(10, 5), sticky="nsew")
        
        # Clear Logs Button
        self.clear_btn = ctk.CTkButton(self.right_panel, text="Clear Logs", command=self.on_clear_logs, width=120)
        self.clear_btn.grid(row=1, column=0, pady=10)
        
        # Spawn Subprocess
        self.start_server_subprocess()
        
        # Start Log and Subprocess Health Pollers
        self.poll_queue()
        self.check_subprocess_health()
        
        # Handle close event
        self.protocol("WM_DELETE_WINDOW", self.on_close)
```

- [ ] **Step 2: Add Subprocess Spawning & IO Piping**
```python
    def start_server_subprocess(self):
        # Stop existing if running
        self.stop_server_subprocess()
        
        logger.info(f"Starting resilient server subprocess on port {self.port}...")
        self.server_process = run_server_subprocess(self.host, self.port, self.reload)
        
        # Start pipe threads
        self.stdout_thread = threading.Thread(target=self.pipe_stream, args=(self.server_process.stdout,), daemon=True)
        self.stdout_thread.start()
        
        self.stderr_thread = threading.Thread(target=self.pipe_stream, args=(self.server_process.stderr,), daemon=True)
        self.stderr_thread.start()
        
    def pipe_stream(self, stream):
        for line in iter(stream.readline, ""):
            line = line.strip()
            if line:
                log_queue.put(line)
        stream.close()
        
    def stop_server_subprocess(self):
        if self.server_process is not None:
            try:
                self.server_process.terminate()
                self.server_process.wait(timeout=2.0)
            except Exception:
                try:
                    self.server_process.kill()
                except Exception:
                    pass
            self.server_process = None
            
    def on_close(self):
        self.stop_server_subprocess()
        self.destroy()
```

- [ ] **Step 3: Update Dropdown Events to change priority models**
```python
    def on_thinking_select(self, val):
        if val == "Auto (Rotation)":
            FORCE_MODEL["gemini-3.5-flash"] = "auto"
            logger.info("Thinking domain manual priority cleared (set to Auto).")
        else:
            FORCE_MODEL["gemini-3.5-flash"] = val
            logger.info(f"Thinking domain priority model set to: {val}")
            
    def on_quick_select(self, val):
        if val == "Auto (Rotation)":
            FORCE_MODEL["gemini-flash-lite-latest"] = "auto"
            logger.info("Quick domain manual priority cleared (set to Auto).")
        else:
            FORCE_MODEL["gemini-flash-lite-latest"] = val
            logger.info(f"Quick domain priority model set to: {val}")
```

- [ ] **Step 4: Commit**
```bash
git add proxy3.py
git commit -m "feat: complete the updated CustomTkinter GUI layout with priority model override dropdowns and auto-restarting subprocesses"
```
