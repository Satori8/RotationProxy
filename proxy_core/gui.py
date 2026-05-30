import os
import sys
import json
import time
import argparse
import subprocess
import threading
import re
import datetime
import customtkinter as ctk


ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")

from proxy_core.config import (
    load_rotation_config,
    save_rotation_config,
    FORCE_MODEL,
    USE_KAGGLE,
    SAVE_CHAT_LOGS,
    KAGGLE_BASE_URL,
    load_kaggle_url,
    save_kaggle_url,
)
from proxy_core.state import log_queue
import logging

logger = logging.getLogger("proxy")


def run_server_subprocess(host: str, port: int, reload: bool):
    cmd = [sys.executable, "proxy3.py", "--host", host, "--port", str(port)]
    if reload:
        cmd.append("--reload")

    startupinfo = None
    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

    return subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        startupinfo=startupinfo,
    )


class ProxyGUI(ctk.CTk):
    def __init__(self, host: str, port: int, reload: bool):
        super().__init__()
        self.host = host
        self.port = port
        self.reload = reload
        self.server_process = None
        self.stdout_thread = None
        self.stderr_thread = None

        import sys

        vpn_dir = r"D:\Work\Active\server-services\vpn_switcher"
        if vpn_dir not in sys.path:
            sys.path.insert(0, vpn_dir)
        try:
            from vpn_manager import WindowsWireGuardManager

            self.vpn_manager = WindowsWireGuardManager()
            logger.info("Successfully loaded WindowsWireGuardManager in GUI.")
        except Exception as ve:
            self.vpn_manager = None
            logger.error(f"Failed to load WindowsWireGuardManager in GUI: {ve}")

        config = load_rotation_config()
        config_force_model = config.get("force_model", {})
        for k, v in config_force_model.items():
            FORCE_MODEL[k] = v

        self.title("Resilient Key Rotation Proxy")
        self.geometry("900x600")

        if os.path.exists("app.ico"):
            try:
                self.iconbitmap("app.ico")
            except Exception as e:
                logger.warning(f"Could not load app.ico: {e}")

        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=2)
        self.grid_rowconfigure(0, weight=1)

        self.left_panel = ctk.CTkFrame(self, width=280, corner_radius=10)
        self.left_panel.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
        self.left_panel.pack_propagate(False)

        self.status_title = ctk.CTkLabel(
            self.left_panel,
            text="PROXY CONTROLLER",
            font=ctk.CTkFont(size=16, weight="bold"),
        )
        self.status_title.pack(pady=(15, 5))

        self.status_badge = ctk.CTkLabel(
            self.left_panel,
            text=f"STATUS: RUNNING (Port {self.port})",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#4CAF50",
        )
        self.status_badge.pack(pady=(0, 20))

        ctk.CTkLabel(
            self.left_panel,
            text="Thinking Domain Priority:",
            font=ctk.CTkFont(size=12, weight="bold"),
        ).pack(anchor="w", padx=20)
        thinking_models = [
            "Auto (Rotation)",
            "gemini-3.5-flash",
            "gemini-3-flash",
            "openrouter/owl-alpha",
            "deepseek/deepseek-v4-flash:free",
            "deepseek/deepseek-r1:free",
            "meta-llama/llama-3.3-70b-instruct:free",
            "qwen/qwen3-coder:free",
            "moonshotai/kimi-k2.6:free",
        ]
        self.thinking_select = ctk.CTkOptionMenu(
            self.left_panel, values=thinking_models, command=self.on_thinking_select
        )
        self.thinking_select.pack(fill="x", padx=20, pady=(2, 15))
        thinking_val = FORCE_MODEL.get("gemini-3.5-flash", "auto")
        if thinking_val == "auto":
            self.thinking_select.set("Auto (Rotation)")
        else:
            self.thinking_select.set(thinking_val)

        ctk.CTkLabel(
            self.left_panel,
            text="Quick Domain Priority:",
            font=ctk.CTkFont(size=12, weight="bold"),
        ).pack(anchor="w", padx=20)
        quick_models = [
            "Auto (Rotation)",
            "gemini-flash-lite-latest",
            "deepseek-v4-flash-free",
            "mimo-v2.5-free",
            "nemotron-3-super-free",
            "google/gemini-2.5-flash:free",
            "google/gemma-2-9b-it:free",
            "meta-llama/llama-3.1-8b-instruct:free",
            "qwen/qwen-2.5-coder-32b-instruct:free",
        ]
        self.quick_select = ctk.CTkOptionMenu(
            self.left_panel, values=quick_models, command=self.on_quick_select
        )
        self.quick_select.pack(fill="x", padx=20, pady=(2, 15))
        quick_val = FORCE_MODEL.get("gemini-flash-lite-latest", "auto")
        if quick_val == "auto":
            self.quick_select.set("Auto (Rotation)")
        else:
            self.quick_select.set(quick_val)

        self.sep = ctk.CTkFrame(self.left_panel, height=2, fg_color="gray30")
        self.sep.pack(fill="x", padx=10, pady=10)

        self.kaggle_var = ctk.BooleanVar(value=config.get("use_kaggle", False))
        self.kaggle_checkbox = ctk.CTkCheckBox(
            self.left_panel,
            text="Use Kaggle (qwen3.6)",
            variable=self.kaggle_var,
            command=self.on_kaggle_toggle,
            font=ctk.CTkFont(size=12, weight="bold"),
        )
        self.kaggle_checkbox.pack(anchor="w", padx=20, pady=(5, 5))

        self.chat_log_var = ctk.BooleanVar(value=config.get("save_chat_logs", False))
        self.chat_log_checkbox = ctk.CTkCheckBox(
            self.left_panel,
            text="Save Chat Logs",
            variable=self.chat_log_var,
            command=self.on_chat_log_toggle,
            font=ctk.CTkFont(size=12, weight="bold"),
        )
        self.chat_log_checkbox.pack(anchor="w", padx=20, pady=(5, 10))

        ctk.CTkLabel(
            self.left_panel,
            text="Kaggle Tunnel URL:",
            font=ctk.CTkFont(size=11, weight="bold"),
        ).pack(anchor="w", padx=20)
        self.url_entry = ctk.CTkEntry(self.left_panel)
        self.url_entry.insert(0, KAGGLE_BASE_URL)
        self.url_entry.pack(fill="x", padx=20, pady=(2, 8))

        self.save_url_btn = ctk.CTkButton(
            self.left_panel, text="Save Kaggle URL", command=self.on_save_url
        )
        self.save_url_btn.pack(fill="x", padx=20, pady=(0, 10))

        # Reset Daily Cooldowns Button
        self.reset_cooldowns_btn = ctk.CTkButton(
            self.left_panel,
            text="Reset Daily Cooldowns",
            command=self.on_reset_cooldowns,
            fg_color="#8B0000",
            hover_color="#B22222",
        )
        self.reset_cooldowns_btn.pack(fill="x", padx=20, pady=(5, 10))

        self.open_folder_btn = ctk.CTkButton(
            self.left_panel,
            text="Open Folder",
            command=self.on_open_folder,
            fg_color="#3B3B3B",
            hover_color="#555555",
        )
        self.open_folder_btn.pack(fill="x", padx=20, pady=(10, 10))

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
        self.tabview.add("VPN Manager")

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

        # Tab 2: Model Manager
        self.tab_manager = self.tabview.tab("Model Manager")
        self.tab_manager.grid_columnconfigure(0, weight=1)
        self.tab_manager.grid_columnconfigure(1, weight=1)
        self.tab_manager.grid_rowconfigure(0, weight=1)

        # Left Side of Manager: Live Diagnostics Monitor
        self.left_manager_frame = ctk.CTkFrame(self.tab_manager, corner_radius=8)
        self.left_manager_frame.grid(row=0, column=0, padx=5, pady=5, sticky="nsew")
        self.left_manager_frame.grid_columnconfigure(0, weight=1)
        self.left_manager_frame.grid_rowconfigure(2, weight=1)

        ctk.CTkLabel(
            self.left_manager_frame,
            text="OpenRouter Free Models",
            font=ctk.CTkFont(size=14, weight="bold"),
        ).grid(row=0, column=0, pady=(10, 5))

        self.fetch_btn = ctk.CTkButton(
            self.left_manager_frame,
            text="Fetch Free Models",
            command=self.on_fetch_free_models,
        )
        self.fetch_btn.grid(row=1, column=0, padx=10, pady=5, sticky="ew")

        # Scrollable container for dynamic rows
        self.models_scroll = ctk.CTkScrollableFrame(self.left_manager_frame)
        self.models_scroll.grid(row=2, column=0, padx=10, pady=5, sticky="nsew")
        self.models_scroll.grid_columnconfigure(0, weight=1)

        self.loaded_models_data = []  # List to track rendered widgets

        # Right Side of Manager: Active Rotation Configuration
        self.right_manager_frame = ctk.CTkFrame(self.tab_manager, corner_radius=8)
        self.right_manager_frame.grid(row=0, column=1, padx=5, pady=5, sticky="nsew")
        self.right_manager_frame.grid_columnconfigure(0, weight=1)
        self.right_manager_frame.grid_rowconfigure(2, weight=1)

        ctk.CTkLabel(
            self.right_manager_frame,
            text="Active Rotation Configuration",
            font=ctk.CTkFont(size=14, weight="bold"),
        ).grid(row=0, column=0, pady=(10, 2))

        # Dropdown to select active domain rotation
        self.domain_select = ctk.CTkOptionMenu(
            self.right_manager_frame,
            values=[
                "Thinking Models (gemini-3.5-flash)",
                "Quick Models (gemini-flash-lite-latest)",
            ],
            command=self.on_manager_domain_change,
        )
        self.domain_select.grid(row=1, column=0, padx=10, pady=5, sticky="ew")

        self.rotation_scroll = ctk.CTkScrollableFrame(self.right_manager_frame)
        self.rotation_scroll.grid(row=2, column=0, padx=10, pady=5, sticky="nsew")
        self.rotation_scroll.grid_columnconfigure(0, weight=1)

        self.save_rotation_btn = ctk.CTkButton(
            self.right_manager_frame,
            text="Save Rotation Config",
            fg_color="#2980B9",
            hover_color="#3498DB",
            command=self.on_save_active_rotation,
        )
        self.save_rotation_btn.grid(row=3, column=0, padx=10, pady=10, sticky="ew")

        # Load active rotation models on start
        self.active_domain_key = "gemini-3.5-flash"
        self.active_rotation_list = []
        self.load_active_rotation_from_disk()

        # Tab 3: VPN Manager
        self.tab_vpn = self.tabview.tab("VPN Manager")
        self.tab_vpn.grid_columnconfigure(0, weight=1)
        self.tab_vpn.grid_columnconfigure(1, weight=1)
        self.tab_vpn.grid_rowconfigure(0, weight=1)

        # Left subframe: VPN Tunnel Controller
        self.vpn_control_frame = ctk.CTkFrame(self.tab_vpn, corner_radius=8)
        self.vpn_control_frame.grid(row=0, column=0, padx=5, pady=5, sticky="nsew")
        self.vpn_control_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            self.vpn_control_frame,
            text="VPN Tunnel Status",
            font=ctk.CTkFont(size=14, weight="bold"),
        ).grid(row=0, column=0, pady=(10, 10))

        self.vpn_status_indicator = ctk.CTkLabel(
            self.vpn_control_frame,
            text="🔴 VPN Inactive",
            text_color="#E74C3C",
            font=ctk.CTkFont(size=16, weight="bold"),
        )
        self.vpn_status_indicator.grid(row=1, column=0, pady=(0, 20))

        self.vpn_start_btn = ctk.CTkButton(
            self.vpn_control_frame,
            text="Start Tunnels",
            fg_color="#27AE60",
            hover_color="#2ECC71",
            command=self.on_vpn_start_tunnels,
        )
        self.vpn_start_btn.grid(row=2, column=0, padx=20, pady=10, sticky="ew")

        self.vpn_stop_btn = ctk.CTkButton(
            self.vpn_control_frame,
            text="Stop Tunnels",
            fg_color="#C0392B",
            hover_color="#E74C3C",
            command=self.on_vpn_stop_tunnels,
        )
        self.vpn_stop_btn.grid(row=3, column=0, padx=20, pady=10, sticky="ew")

        # Right subframe: VPN Rotation Settings
        self.vpn_config_frame = ctk.CTkFrame(self.tab_vpn, corner_radius=8)
        self.vpn_config_frame.grid(row=0, column=1, padx=5, pady=5, sticky="nsew")
        self.vpn_config_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            self.vpn_config_frame,
            text="VPN Rotation Settings",
            font=ctk.CTkFont(size=14, weight="bold"),
        ).grid(row=0, column=0, pady=(10, 10))

        ctk.CTkLabel(
            self.vpn_config_frame, text="VPN Switching Mode:", font=ctk.CTkFont(size=11)
        ).grid(row=1, column=0, padx=10, sticky="w")

        self.vpn_mode_dropdown = ctk.CTkOptionMenu(
            self.vpn_config_frame,
            values=[
                "Disabled (Выкл)",
                "Every Request (Каждый запрос)",
                "After N Errors (Смена после N ошибок)",
            ],
            command=self.on_vpn_mode_dropdown_change,
        )
        self.vpn_mode_dropdown.grid(row=2, column=0, padx=10, pady=(2, 15), sticky="ew")

        # Container for dynamic mode-specific widgets
        self.vpn_dynamic_container = ctk.CTkFrame(
            self.vpn_config_frame, fg_color="transparent"
        )
        self.vpn_dynamic_container.grid(row=3, column=0, padx=10, pady=5, sticky="nsew")
        self.vpn_dynamic_container.grid_columnconfigure(0, weight=1)

        # Initialize and render dynamic settings
        self.load_vpn_ui_settings()

        # Start periodic 5s status check loop
        self.poll_vpn_status_loop()

        self.start_server_subprocess()
        self.poll_queue()
        self.check_subprocess_health()

    def on_thinking_select(self, val):
        config = load_rotation_config()
        if val == "Auto (Rotation)":
            config["force_model"]["gemini-3.5-flash"] = "auto"
            logger.info("Thinking domain priority model reset to Auto.")
        else:
            config["force_model"]["gemini-3.5-flash"] = val
            logger.info(f"Thinking domain priority model set to: {val}")
        save_rotation_config(config)

    def on_quick_select(self, val):
        config = load_rotation_config()
        if val == "Auto (Rotation)":
            config["force_model"]["gemini-flash-lite-latest"] = "auto"
            logger.info("Quick domain priority model reset to Auto.")
        else:
            config["force_model"]["gemini-flash-lite-latest"] = val
            logger.info(f"Quick domain priority model set to: {val}")
        save_rotation_config(config)

    def on_kaggle_toggle(self):
        config = load_rotation_config()
        val = self.kaggle_var.get()
        config["use_kaggle"] = val
        save_rotation_config(config)
        logger.info(f"Use Kaggle (qwen3.6) set to: {val}")

    def on_chat_log_toggle(self):
        config = load_rotation_config()
        val = self.chat_log_var.get()
        config["save_chat_logs"] = val
        save_rotation_config(config)
        logger.info(f"Save Chat Logs set to: {val}")

    def on_save_url(self):
        url = self.url_entry.get().strip()
        if url:
            if save_kaggle_url(url):
                logger.info(f"Updated active Kaggle URL to: {url}")
                log_queue.put(f"[GUI] Saved active Kaggle URL: {url}")
            else:
                log_queue.put("[GUI] [ERROR] Failed to save Kaggle URL.")

    def on_reset_cooldowns(self):
        import httpx

        def do_reset():
            url = f"http://{self.host}:{self.port}/control/reset_cooldowns"
            try:
                r = httpx.post(url, timeout=2.0)
                if r.status_code == 200:
                    logger.info("[GUI] Cooldowns reset successfully.")
                    log_queue.put("[GUI] Cooldowns reset successfully.")
                else:
                    logger.error(
                        f"[GUI] Failed to reset cooldowns: HTTP {r.status_code}"
                    )
                    log_queue.put(
                        f"[GUI] [ERROR] Failed to reset cooldowns: HTTP {r.status_code}"
                    )
            except Exception as ex:
                logger.error(
                    f"[GUI] Failed to connect to proxy to reset cooldowns: {ex}"
                )
                log_queue.put(f"[GUI] [ERROR] Failed to connect to proxy: {ex}")

        threading.Thread(target=do_reset, daemon=True).start()

    def on_open_folder(self):
        try:
            folder = os.getcwd()
            if os.name == "nt":
                os.startfile(folder)
            else:
                subprocess.run(["xdg-open", folder])
            logger.info(f"Opened script directory: {folder}")
        except Exception as e:
            logger.error(f"Failed to open script folder: {e}")
            log_queue.put(f"[GUI] [ERROR] Failed to open script folder: {e}")

    def on_clear_logs(self):
        self.log_textbox.delete("1.0", "end")

    def poll_queue(self):
        while not log_queue.empty():
            try:
                msg = log_queue.get_nowait()
                msg = ANSI_ESCAPE.sub("", msg)

                tag = None
                if "[INFO]" in msg:
                    tag = "info"
                elif "[WARNING]" in msg:
                    tag = "warning"
                elif "[ERROR]" in msg:
                    tag = "error"
                elif "[CRITICAL]" in msg:
                    tag = "critical"
                elif "[DEBUG]" in msg:
                    tag = "debug"

                self.log_textbox.insert("end", msg + "\n", tag)
                self.log_textbox.see("end")
            except Exception:
                break
        self.after(100, self.poll_queue)

    def start_server_subprocess(self):
        self.stop_server_subprocess()
        logger.info(f"Starting resilient server subprocess on port {self.port}...")
        log_queue.put(f"[GUI] Launching proxy server subprocess on port {self.port}...")
        self.server_process = run_server_subprocess(self.host, self.port, self.reload)

        self.stdout_thread = threading.Thread(
            target=self.pipe_stream, args=(self.server_process.stdout,), daemon=True
        )
        self.stdout_thread.start()

        self.stderr_thread = threading.Thread(
            target=self.pipe_stream, args=(self.server_process.stderr,), daemon=True
        )
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
                if os.name == "nt":
                    # Fully kill the entire process tree on Windows to release port bindings!
                    subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", str(self.server_process.pid)],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                else:
                    self.server_process.terminate()
                    self.server_process.wait(timeout=2.0)
            except Exception:
                try:
                    self.server_process.kill()
                except Exception:
                    pass
            self.server_process = None

    def check_subprocess_health(self):
        if self.server_process is not None:
            ret_code = self.server_process.poll()
            if ret_code is not None:
                log_queue.put(
                    f"[GUI] [WARNING] Proxy server subprocess died with code {ret_code}."
                )
                timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                ERROR_LOG_PATH = "proxy_errors.log"
                try:
                    with open(ERROR_LOG_PATH, "a", encoding="utf-8") as f:
                        f.write(
                            f"[{timestamp}] [ERROR] Proxy subprocess crashed/exited with code {ret_code}. Auto-restarting...\n"
                        )
                except Exception as e:
                    logger.error(f"Failed to write to proxy_errors.log: {e}")

                log_queue.put(
                    "[GUI] [SYSTEM] Initiating automatic subprocess recovery restart..."
                )
                self.start_server_subprocess()
        self.after(1000, self.check_subprocess_health)

    def on_close(self):
        self.stop_server_subprocess()
        if hasattr(self, "vpn_manager") and self.vpn_manager is not None:
            try:
                logger.info("[GUI] Cleaning up VPN tunnels on close...")
                self.vpn_manager.uninstall_all_services()
            except Exception as e:
                logger.error(f"[GUI] Error during VPN cleanup on close: {e}")
        self.destroy()

    def on_fetch_free_models(self):
        """Asynchronously fetch free models in a background thread."""
        self.fetch_btn.configure(state="disabled", text="Fetching...")

        def do_fetch():
            import urllib.request

            url = "https://openrouter.ai/api/v1/models"
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
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
                                }
                            )
                    # Sort by id
                    free_models = sorted(free_models, key=lambda x: x["id"])
                    self.after(0, lambda: self.render_free_models(free_models))
            except Exception as e:
                logger.error(f"[GUI] Failed to fetch free models: {e}")
                self.after(
                    0,
                    lambda: self.fetch_btn.configure(
                        state="normal", text="Fetch Free Models"
                    ),
                )

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
            lbl = ctk.CTkLabel(
                row_frame, text=info_text, font=ctk.CTkFont(size=10), justify="left"
            )
            lbl.grid(row=0, column=0, padx=5, pady=2, sticky="w")

            # Status Badge (circle indicator)
            badge = ctk.CTkLabel(
                row_frame, text="●", text_color="#7F8C8D", font=ctk.CTkFont(size=16)
            )
            badge.grid(row=0, column=1, padx=5)

            # Test Button
            test_cb = lambda model_id=m["id"], b=badge: self.on_test_individual_model(
                model_id, b
            )
            btn_test = ctk.CTkButton(
                row_frame,
                text="Test",
                width=45,
                height=20,
                font=ctk.CTkFont(size=9),
                command=test_cb,
            )
            btn_test.grid(row=0, column=2, padx=2)

            # Add to Rotation Button
            add_cb = lambda model_id=m["id"]: self.on_add_model_to_rotation(model_id)
            btn_add = ctk.CTkButton(
                row_frame,
                text="+ Add",
                width=45,
                height=20,
                font=ctk.CTkFont(size=9),
                fg_color="#27AE60",
                hover_color="#2ECC71",
                command=add_cb,
            )
            btn_add.grid(row=0, column=3, padx=2)

        self.fetch_btn.configure(state="normal", text="Fetch Free Models")

    def on_test_individual_model(self, model_id, badge_widget):
        """Test a model via background thread and update its status indicator badge and response latency."""
        badge_widget.configure(
            text_color="#F1C40F", text="● ..."
        )  # Yellow for testing...

        def do_test():
            import httpx

            url = f"http://{self.host}:{self.port}/control/test_model"
            try:
                r = httpx.post(
                    url,
                    json={"model": model_id, "provider": "openrouter"},
                    timeout=12.0,
                )
                if r.status_code == 200:
                    res = r.json()
                    status = res.get("status")
                    latency = res.get("latency_ms", 0)
                    if status == "ok":
                        self.after(
                            0,
                            lambda: badge_widget.configure(
                                text_color="#2ECC71", text=f"● {latency}ms"
                            ),
                        )  # Green
                    elif status == "rate_limited":
                        self.after(
                            0,
                            lambda: badge_widget.configure(
                                text_color="#E67E22", text=f"● 429 ({latency}ms)"
                            ),
                        )  # Orange (429)
                    elif status == "not_found":
                        self.after(
                            0,
                            lambda: badge_widget.configure(
                                text_color="#E74C3C", text="● 404"
                            ),
                        )  # Red (404)
                    else:
                        logger.error(f"[GUI] Model test returned status: {status}")
                        log_queue.put(
                            f"[GUI] [WARNING] Model {model_id} test status: {status}"
                        )
                        self.after(
                            0,
                            lambda: badge_widget.configure(
                                text_color="#E74C3C", text="● ERR"
                            ),
                        )  # Red (Error)
                else:
                    logger.error(f"[GUI] Model test HTTP error: {r.status_code}")
                    log_queue.put(
                        f"[GUI] [WARNING] Model {model_id} HTTP error: {r.status_code}"
                    )
                    self.after(
                        0,
                        lambda: badge_widget.configure(
                            text_color="#E74C3C", text=f"● HTTP {r.status_code}"
                        ),
                    )
            except Exception as e:
                import traceback

                tb = traceback.format_exc()
                logger.error(f"[GUI] Model test exception: {e}\n{tb}")
                log_queue.put(f"[GUI] [ERROR] Model test exception for {model_id}: {e}")
                self.after(
                    0,
                    lambda: badge_widget.configure(text_color="#E74C3C", text="● ERR"),
                )

        threading.Thread(target=do_test, daemon=True).start()

    def on_manager_domain_change(self, val):
        """Handle active domain choice change from the selector menu."""
        if "Thinking Models" in val:
            self.active_domain_key = "gemini-3.5-flash"
        else:
            self.active_domain_key = "gemini-flash-lite-latest"
        self.load_active_rotation_from_disk()
        logger.info(
            f"[GUI] Switched manager domain selection to: {self.active_domain_key}"
        )
        log_queue.put(
            f"[GUI] Switched manager domain selection to: {self.active_domain_key}"
        )

    def on_add_model_to_rotation(self, model_id):
        """Add a model from scan to the end of the active domain's rotation list."""
        if model_id not in self.active_rotation_list:
            self.active_rotation_list.append(model_id)
            self.render_rotation_list()
            logger.info(
                f"[GUI] Added model '{model_id}' to current {self.active_domain_key} rotation configuration."
            )
            log_queue.put(
                f"[GUI] Added model '{model_id}' to current {self.active_domain_key} rotation configuration."
            )

    def load_active_rotation_from_disk(self):
        """Load and display the active rotation list from config based on active domain."""
        config = load_rotation_config()
        self.active_rotation_list = config.get("rotation_lists", {}).get(
            self.active_domain_key, []
        )
        self.render_rotation_list()

    def render_rotation_list(self):
        """Render the ordered rotation models in the configurator frame."""
        for widget in self.rotation_scroll.winfo_children():
            widget.destroy()

        protected_id = self.active_domain_key
        for idx, model_id in enumerate(self.active_rotation_list):
            row_frame = ctk.CTkFrame(self.rotation_scroll, fg_color="transparent")
            row_frame.grid(row=idx, column=0, padx=2, pady=2, sticky="ew")
            row_frame.grid_columnconfigure(0, weight=1)

            lbl = ctk.CTkLabel(
                row_frame, text=model_id, font=ctk.CTkFont(size=10, weight="bold")
            )
            lbl.grid(row=0, column=0, padx=5, pady=2, sticky="w")

            # Check core boundaries (don't allow removing protected first element)
            if model_id != protected_id:
                # Up button
                up_cb = lambda i=idx: self.on_shift_model_priority(i, direction=-1)
                btn_up = ctk.CTkButton(
                    row_frame,
                    text="▲",
                    width=22,
                    height=18,
                    font=ctk.CTkFont(size=8),
                    command=up_cb,
                )
                btn_up.grid(row=0, column=1, padx=1)

                # Down button
                down_cb = lambda i=idx: self.on_shift_model_priority(i, direction=1)
                btn_down = ctk.CTkButton(
                    row_frame,
                    text="▼",
                    width=22,
                    height=18,
                    font=ctk.CTkFont(size=8),
                    command=down_cb,
                )
                btn_down.grid(row=0, column=2, padx=1)

                # Remove button
                del_cb = lambda m=model_id: self.on_remove_model_from_rotation(m)
                btn_del = ctk.CTkButton(
                    row_frame,
                    text="✕",
                    width=22,
                    height=18,
                    text_color="#E74C3C",
                    font=ctk.CTkFont(size=8),
                    fg_color="transparent",
                    hover_color="#2c2c2c",
                    command=del_cb,
                )
                btn_del.grid(row=0, column=3, padx=1)

    def on_shift_model_priority(self, index, direction):
        """Shift model priority up (-1) or down (+1) in the rotation list."""
        new_index = index + direction
        protected_id = self.active_domain_key
        if 0 <= new_index < len(self.active_rotation_list):
            # Maintain boundary at index 0
            if self.active_rotation_list[0] == protected_id and (
                index == 0 or new_index == 0
            ):
                return

            # Swap items
            self.active_rotation_list[index], self.active_rotation_list[new_index] = (
                self.active_rotation_list[new_index],
                self.active_rotation_list[index],
            )
            self.render_rotation_list()

    def on_remove_model_from_rotation(self, model_id):
        """Remove a model from the local in-memory rotation list."""
        protected_id = self.active_domain_key
        if model_id != protected_id and model_id in self.active_rotation_list:
            self.active_rotation_list.remove(model_id)
            self.render_rotation_list()

    def on_save_active_rotation(self):
        """Save the configured rotation lists to config_rotation.json."""
        try:
            config = load_rotation_config()
            if "rotation_lists" not in config:
                config["rotation_lists"] = {}
            config["rotation_lists"][self.active_domain_key] = list(
                self.active_rotation_list
            )
            save_rotation_config(config)
            logger.info(
                f"[GUI] Successfully saved active {self.active_domain_key} rotation configuration on disk!"
            )
            log_queue.put(
                f"[GUI] Successfully saved active {self.active_domain_key} rotation configuration!"
            )
        except Exception as e:
            logger.error(f"[GUI] Failed to save rotation config: {e}")
            log_queue.put(f"[GUI] [ERROR] Failed to save rotation config: {e}")

    def on_vpn_start_tunnels(self):
        """Install and start all 6 WireGuard tunnels in a background thread."""
        if not hasattr(self, "vpn_manager") or self.vpn_manager is None:
            log_queue.put("[GUI] [ERROR] VPN Manager library is not loaded.")
            return

        if not self.vpn_manager.is_admin():
            logger.info(
                "[GUI] Requesting Windows Administrator privileges to install tunnels..."
            )
            log_queue.put(
                "[GUI] [SYSTEM] WireGuard requires Administrator privileges. Requesting UAC elevation..."
            )
            self.vpn_manager.elevate()
            return

        self.vpn_start_btn.configure(state="disabled", text="Starting...")
        log_queue.put(
            "[GUI] [SYSTEM] Installing and starting all 6 VPN tunnels in the background..."
        )

        def run_start():
            try:
                self.vpn_manager.install_and_start_all_services()
                log_queue.put(
                    "[GUI] [SUCCESS] All 6 WireGuard tunnels started and gateway routes configured!"
                )
            except Exception as e:
                logger.error(f"[GUI] Error starting tunnels: {e}")
                log_queue.put(f"[GUI] [ERROR] Error starting tunnels: {e}")
            finally:
                self.after(
                    0,
                    lambda: self.vpn_start_btn.configure(
                        state="normal", text="Start Tunnels"
                    ),
                )
                self.after(0, self.do_poll_vpn_status)

        threading.Thread(target=run_start, daemon=True).start()

    def on_vpn_stop_tunnels(self):
        """Stop and cleanly uninstall all 6 WireGuard tunnels in a background thread."""
        if not hasattr(self, "vpn_manager") or self.vpn_manager is None:
            log_queue.put("[GUI] [ERROR] VPN Manager library is not loaded.")
            return

        if not self.vpn_manager.is_admin():
            logger.info(
                "[GUI] Requesting Windows Administrator privileges to stop tunnels..."
            )
            log_queue.put(
                "[GUI] [SYSTEM] WireGuard requires Administrator privileges. Requesting UAC elevation..."
            )
            self.vpn_manager.elevate()
            return

        self.vpn_stop_btn.configure(state="disabled", text="Stopping...")
        log_queue.put("[GUI] [SYSTEM] Stopping and cleanly removing all VPN tunnels...")

        def run_stop():
            try:
                self.vpn_manager.uninstall_all_services()
                self.vpn_manager.disable_system_routing()
                log_queue.put(
                    "[GUI] [SUCCESS] All WireGuard tunnels removed. System routing restored to default."
                )
            except Exception as e:
                logger.error(f"[GUI] Error stopping tunnels: {e}")
                log_queue.put(f"[GUI] [ERROR] Error stopping tunnels: {e}")
            finally:
                self.after(
                    0,
                    lambda: self.vpn_stop_btn.configure(
                        state="normal", text="Stop Tunnels"
                    ),
                )
                self.after(0, self.do_poll_vpn_status)

        threading.Thread(target=run_stop, daemon=True).start()

    def poll_vpn_status_loop(self):
        """Periodic loop to poll the status of VPN tunnels every 5 seconds."""
        self.do_poll_vpn_status()
        self.after(5000, self.poll_vpn_status_loop)

    def do_poll_vpn_status(self):
        """Run is_any_tunnel_active on a background thread to prevent UI lag."""
        if not hasattr(self, "vpn_manager") or self.vpn_manager is None:
            return

        def run_check():
            try:
                active = self.vpn_manager.is_any_tunnel_active()
                if active:
                    self.after(
                        0,
                        lambda: self.vpn_status_indicator.configure(
                            text="🟢 VPN Active", text_color="#2ECC71"
                        ),
                    )
                else:
                    self.after(
                        0,
                        lambda: self.vpn_status_indicator.configure(
                            text="🔴 VPN Inactive", text_color="#E74C3C"
                        ),
                    )
            except Exception as e:
                logger.debug(f"[VPN Status Check Error] {e}")

        threading.Thread(target=run_check, daemon=True).start()

    def load_vpn_ui_settings(self):
        """Load VPN mode and settings from disk configuration."""
        config = load_rotation_config()
        mode = config.get("vpn_switching_mode", "disabled")

        if mode == "every_request":
            self.vpn_mode_dropdown.set("Every Request (Каждый запрос)")
        elif mode == "error_threshold":
            self.vpn_mode_dropdown.set("After N Errors (Смена после N ошибок)")
        else:
            self.vpn_mode_dropdown.set("Disabled (Выкл)")

        self.render_vpn_dynamic_options(mode, config)

    def render_vpn_dynamic_options(self, mode, config):
        """Dynamically render the appropriate fields based on VPN Switching Mode."""
        for widget in self.vpn_dynamic_container.winfo_children():
            widget.destroy()

        if mode == "disabled":
            lbl = ctk.CTkLabel(
                self.vpn_dynamic_container,
                text="Static VPN Channel:",
                font=ctk.CTkFont(size=11, weight="bold"),
            )
            lbl.grid(row=0, column=0, padx=10, sticky="w", pady=(5, 2))

            static_channels = [
                "No VPN",
                "VPN 1",
                "VPN 2",
                "VPN 3",
                "VPN 4",
                "VPN 5",
                "VPN 6",
            ]
            self.static_dropdown = ctk.CTkOptionMenu(
                self.vpn_dynamic_container,
                values=static_channels,
                command=self.on_vpn_static_change,
            )
            self.static_dropdown.grid(
                row=1, column=0, padx=10, pady=(0, 10), sticky="ew"
            )

            current_static = config.get("vpn_static_channel", 0)
            if 0 < current_static <= 6:
                self.static_dropdown.set(f"VPN {current_static}")
            else:
                self.static_dropdown.set("No VPN")

        elif mode == "error_threshold":
            lbl = ctk.CTkLabel(
                self.vpn_dynamic_container,
                text="Errors Threshold (N):",
                font=ctk.CTkFont(size=11, weight="bold"),
            )
            lbl.grid(row=0, column=0, padx=10, sticky="w", pady=(5, 2))

            self.threshold_entry = ctk.CTkEntry(self.vpn_dynamic_container, width=100)
            self.threshold_entry.grid(
                row=1, column=0, padx=10, pady=(0, 10), sticky="w"
            )
            self.threshold_entry.insert(0, str(config.get("vpn_errors_threshold", 5)))

            btn_save = ctk.CTkButton(
                self.vpn_dynamic_container,
                text="Save Threshold",
                width=110,
                fg_color="#27AE60",
                hover_color="#2ECC71",
                command=self.on_vpn_threshold_save,
            )
            btn_save.grid(row=1, column=1, padx=10, pady=(0, 10), sticky="w")

    def on_vpn_mode_dropdown_change(self, val):
        """Update and save switching mode from dropdown selection."""
        config = load_rotation_config()
        if "Every Request" in val:
            mode = "every_request"
        elif "After N Errors" in val:
            mode = "error_threshold"
        else:
            mode = "disabled"

        config["vpn_switching_mode"] = mode
        save_rotation_config(config)

        self.render_vpn_dynamic_options(mode, config)
        logger.info(f"[GUI] Saved VPN switching mode to: {mode}")
        log_queue.put(f"[GUI] Saved VPN switching mode to: {mode}")

    def on_vpn_static_change(self, val):
        """Handle manual static VPN routing change (now isolated to proxy socket binding)."""
        config = load_rotation_config()
        if "VPN " in val:
            try:
                channel = int(val.replace("VPN ", ""))
            except ValueError:
                channel = 0
        else:
            channel = 0

        config["vpn_static_channel"] = channel
        save_rotation_config(config)
        log_queue.put(f"[GUI] [SUCCESS] Static proxy socket binding updated: {val}.")

    def on_vpn_threshold_save(self):
        """Save errors threshold when clicked."""
        config = load_rotation_config()
        try:
            val = int(self.threshold_entry.get().strip())
            if val < 1:
                val = 1
        except ValueError:
            val = 5

        config["vpn_errors_threshold"] = val
        save_rotation_config(config)
        logger.info(f"[GUI] Saved VPN errors threshold: {val}")
        log_queue.put(f"[GUI] Saved VPN errors threshold: {val}")
