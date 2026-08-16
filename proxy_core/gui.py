import os
import sys
import json
import time
import argparse
import subprocess
import threading
import re
import datetime
import tkinter as tk
import customtkinter as ctk


ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")

from proxy_core.config import (
    load_rotation_config,
    save_rotation_config,
    USE_KAGGLE,
    SAVE_CHAT_LOGS,
    KAGGLE_BASE_URL,
    load_kaggle_url,
    save_kaggle_url,
)
from proxy_core.state import log_queue
from proxy_core.helpers import beautify_json_string
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

    # Force python subprocesses to output UTF-8 text to prevent charmap codec errors
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"

    return subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="ignore",
        bufsize=1,
        startupinfo=startupinfo,
        env=env,
    )


class CTkToolTip:
    """A simple, lightweight hover tooltip for CustomTkinter widgets."""

    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tooltip_window = None
        self.widget.bind("<Enter>", self.show_tooltip)
        self.widget.bind("<Leave>", self.hide_tooltip)

    def show_tooltip(self, event=None):
        if self.tooltip_window or not self.text:
            return
        x = self.widget.winfo_rootx() + 25
        y = self.widget.winfo_rooty() + 20
        self.tooltip_window = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        label = tk.Label(
            tw,
            text=self.text,
            justify="left",
            background="#2c2c2c",
            foreground="#ffffff",
            relief="solid",
            border=1,
            font=("Helvetica", 10, "normal"),
            padx=5,
            pady=5,
        )
        label.pack(ipadx=1)

    def hide_tooltip(self, event=None):
        tw = self.tooltip_window
        self.tooltip_window = None
        if tw:
            tw.destroy()


class ProxyGUI(ctk.CTk):
    def __init__(self, host: str, port: int, reload: bool):
        super().__init__()
        self.withdraw()  # Hide during init, show after_idle when mainloop starts
        self.host = host
        self.port = port
        self.reload = reload
        self.server_process = None
        self.stdout_thread = None
        self.stderr_thread = None
        self.restart_count = 0
        self.restart_backoff = 1.0
        self._restart_pending = False
        self.compactor_settings_win = None

        # Reusable fonts to optimize performance and memory usage
        self.font_title = ctk.CTkFont(size=12, weight="bold")
        self.font_badge = ctk.CTkFont(size=10, weight="bold")
        self.font_bold_10 = ctk.CTkFont(size=10, weight="bold")
        self.font_normal_10 = ctk.CTkFont(size=10)
        self.font_bold_11 = ctk.CTkFont(size=11, weight="bold")
        self.font_bold_12 = ctk.CTkFont(size=12, weight="bold")
        self.font_bold_14 = ctk.CTkFont(size=14, weight="bold")
        self.font_bold_16 = ctk.CTkFont(size=16, weight="bold")
        self.font_normal_9 = ctk.CTkFont(size=9)
        self.font_bold_9 = ctk.CTkFont(size=9, weight="bold")
        self.font_normal_8 = ctk.CTkFont(size=8)
        self.font_bold_8 = ctk.CTkFont(size=8, weight="bold")

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

        # Clean up system routing on startup to ensure a clean slate
        if hasattr(self, "vpn_manager") and self.vpn_manager is not None:
            import threading

            def startup_cleanup():
                self.vpn_manager.disable_system_routing()
                try:
                    from proxy_core.config import (
                        load_rotation_config,
                        save_rotation_config,
                    )

                    config = load_rotation_config()
                    config["system_vpn_active"] = False
                    save_rotation_config(config)
                except Exception:
                    pass

            threading.Thread(target=startup_cleanup, daemon=True).start()

        # Start VPN tunnels early, in parallel with UI construction
        self.on_vpn_start_tunnels()

        config = load_rotation_config()
        config_force_model = config.get("force_model", {})
        primary_model = config.get("primary_model", "")
        thinking_models_list = config.get("thinking_models", [])
        quick_models_list = config.get("quick_models", [])
        quick_primary_model = quick_models_list[0] if quick_models_list else ""

        self.title("Resilient Key Rotation Proxy")
        self.geometry("1200x700")

        if os.path.exists("app.ico"):
            try:
                self.iconbitmap("app.ico")
            except Exception as e:
                logger.warning(f"Could not load app.ico: {e}")

        self.grid_columnconfigure(0, weight=0)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.left_panel = ctk.CTkFrame(self, width=180, corner_radius=10)
        self.left_panel.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
        self.left_panel.pack_propagate(False)

        self.status_title = ctk.CTkLabel(
            self.left_panel,
            text="PROXY CONTROLLER",
            font=self.font_bold_12,
        )
        self.status_title.pack(pady=(10, 5))

        self.status_badge = ctk.CTkLabel(
            self.left_panel,
            text=f"RUNNING (Port {self.port})",
            font=self.font_badge,
            text_color="#4CAF50",
        )
        self.status_badge.pack(pady=(0, 10))

        # VPN status lamps in sidebar
        self.sidebar_vpn_frame = ctk.CTkFrame(self.left_panel, fg_color="transparent")
        self.sidebar_vpn_frame.pack(fill="x", padx=10, pady=(0, 10))
        self.sidebar_vpn_lamps = {}
        for i in range(1, 7):
            lamp = ctk.CTkLabel(
                self.sidebar_vpn_frame,
                text=f"● VPN {i}",
                text_color="#7F8C8D",
                font=ctk.CTkFont(size=10),
                cursor="hand2",
            )
            lamp.pack(side="left", padx=2)
            lamp.bind(
                "<Button-1>", lambda event, idx=i: self.on_restart_single_tunnel(idx)
            )
            CTkToolTip(lamp, f"VPN {i}: Off")
            self.sidebar_vpn_lamps[i] = lamp

        ctk.CTkLabel(
            self.left_panel,
            text="Force Model (All Requests):",
            font=ctk.CTkFont(size=10, weight="bold"),
        ).pack(anchor="w", padx=10)
        active_rotation_models = config.get("rotation_lists", {}).get(primary_model, [])
        if not active_rotation_models:
            active_rotation_models = thinking_models_list
        forced_models = ["Auto (Rotation)"] + [
            m for m in active_rotation_models if m and m != "Auto (Rotation)"
        ]
        self.thinking_select = ctk.CTkOptionMenu(
            self.left_panel, values=forced_models, command=self.on_thinking_select
        )
        self.thinking_select.pack(fill="x", padx=10, pady=(2, 10))
        self.force_select = self.thinking_select
        forced_val = config_force_model.get("all") or config_force_model.get(
            primary_model, "auto"
        )
        if forced_val == "auto" or forced_val not in forced_models:
            self.thinking_select.set("Auto (Rotation)")
        else:
            self.thinking_select.set(forced_val)

        self.sep = ctk.CTkFrame(self.left_panel, height=2, fg_color="gray30")
        self.sep.pack(fill="x", padx=5, pady=5)

        self.kaggle_var = ctk.BooleanVar(value=config.get("use_kaggle", False))
        self.kaggle_checkbox = ctk.CTkCheckBox(
            self.left_panel,
            text="Use Kaggle",
            variable=self.kaggle_var,
            command=self.on_kaggle_toggle,
            font=ctk.CTkFont(size=10, weight="bold"),
        )
        self.kaggle_checkbox.pack(anchor="w", padx=10, pady=(3, 3))

        self.chat_log_var = ctk.BooleanVar(value=config.get("save_chat_logs", False))
        self.chat_log_checkbox = ctk.CTkCheckBox(
            self.left_panel,
            text="Save Chat Logs",
            variable=self.chat_log_var,
            command=self.on_chat_log_toggle,
            font=ctk.CTkFont(size=10, weight="bold"),
        )
        self.chat_log_checkbox.pack(anchor="w", padx=10, pady=(3, 3))

        self.filter_context_var = ctk.BooleanVar(
            value=config.get("filter_context", True)
        )
        self.filter_context_checkbox = ctk.CTkCheckBox(
            self.left_panel,
            text="Filter context",
            variable=self.filter_context_var,
            command=self.on_filter_context_toggle,
            font=ctk.CTkFont(size=10, weight="bold"),
        )
        self.filter_context_checkbox.pack(anchor="w", padx=10, pady=(3, 5))

        self.model_rotation_var = ctk.BooleanVar(
            value=config.get("enable_model_rotation", False)
        )
        self.model_rotation_checkbox = ctk.CTkCheckBox(
            self.left_panel,
            text="Models Rotation",
            variable=self.model_rotation_var,
            command=self.on_model_rotation_toggle,
            font=self.font_bold_10,
        )
        self.model_rotation_checkbox.pack(anchor="w", padx=10, pady=(3, 3))

        # Parallelism Checkbox
        self.parallelism_var = ctk.BooleanVar(value=False)
        self.parallelism_cb = ctk.CTkCheckBox(
            self.left_panel,
            text="Parallelism",
            variable=self.parallelism_var,
            command=self.on_save_parallelism_settings,
            font=ctk.CTkFont(size=10, weight="bold"),
        )
        self.parallelism_cb.pack(anchor="w", padx=10, pady=(3, 3))

        # Parallel Tunnels Count Frame
        self.parallel_count_frame = ctk.CTkFrame(
            self.left_panel, fg_color="transparent"
        )
        self.parallel_count_frame.pack(fill="x", padx=10, pady=3)

        self.parallel_count_var = ctk.IntVar(value=3)
        self.parallel_count_label = ctk.CTkLabel(
            self.parallel_count_frame,
            text="Tunnels:",
            font=ctk.CTkFont(size=10, weight="bold"),
        )
        self.parallel_count_label.pack(side="left", padx=(0, 5))
        self.parallel_count_dropdown = ctk.CTkOptionMenu(
            self.parallel_count_frame,
            values=[str(i) for i in range(1, 8)],
            variable=self.parallel_count_var,
            command=lambda _: self.on_save_parallelism_settings(),
            width=50,
        )
        self.parallel_count_dropdown.pack(side="right", fill="x", expand=True)

        # Per-Channel Delay Frame
        self.per_channel_delay_frame = ctk.CTkFrame(
            self.left_panel, fg_color="transparent"
        )
        self.per_channel_delay_frame.pack(fill="x", padx=10, pady=3)

        self.per_channel_delay_label = ctk.CTkLabel(
            self.per_channel_delay_frame,
            text="Delay (sec):",
            font=ctk.CTkFont(size=10, weight="bold"),
        )
        self.per_channel_delay_label.pack(side="left", padx=(0, 5))

        self.per_channel_delay_entry = ctk.CTkEntry(
            self.per_channel_delay_frame,
            width=40,
        )
        self.per_channel_delay_entry.pack(side="right")
        self.per_channel_delay_entry.bind(
            "<KeyRelease>", lambda _: self.on_save_parallelism_settings()
        )

        # Reset Daily Cooldowns Button
        self.reset_cooldowns_btn = ctk.CTkButton(
            self.left_panel,
            text="Reset Cooldowns",
            command=self.on_reset_cooldowns,
            fg_color="#8B0000",
            hover_color="#B22222",
        )
        self.reset_cooldowns_btn.pack(fill="x", padx=10, pady=(5, 5))

        self.open_folder_btn = ctk.CTkButton(
            self.left_panel,
            text="Open Folder",
            command=self.on_open_folder,
            fg_color="#3B3B3B",
            hover_color="#555555",
        )
        self.open_folder_btn.pack(fill="x", padx=10, pady=(5, 5))

        # Compactor Statistics Frame
        self.stats_frame = ctk.CTkFrame(self.left_panel, fg_color="transparent")
        self.stats_frame.pack(fill="x", padx=10, pady=(3, 3))

        self.stats_title = ctk.CTkLabel(
            self.stats_frame,
            text="COMPACTION:",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color="#3498DB",
        )
        self.stats_title.pack(anchor="w")

        self.stats_label = ctk.CTkLabel(
            self.stats_frame,
            text="Saved: 0 B (-0.0%)",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color="gray70",
        )
        self.stats_label.pack(anchor="w")

        # Compactor Settings Button
        self.compactor_settings_btn = ctk.CTkButton(
            self.stats_frame,
            text="⚙ Settings",
            font=ctk.CTkFont(size=9, weight="bold"),
            height=20,
            command=self.open_compactor_settings_window,
            fg_color="#34495E",
            hover_color="#2C3E50",
        )
        self.compactor_settings_btn.pack(anchor="w", pady=(5, 0))

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
        self.tabview.add("Settings")

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

        self.log_textbox._textbox.tag_config(
            "info", foreground="#2ECC71"
        )  # Emerald green
        self.log_textbox._textbox.tag_config(
            "warning", foreground="#F1C40F"
        )  # Sun yellow
        self.log_textbox._textbox.tag_config(
            "error", foreground="#E74C3C"
        )  # Alizarin red
        self.log_textbox._textbox.tag_config(
            "critical", foreground="#C0392B"
        )  # Dark red
        self.log_textbox._textbox.tag_config(
            "debug", foreground="#7F8C8D"
        )  # Asbestos grey

        self.autoscroll = True

        def custom_yscroll(*args):
            if args:
                try:
                    first, last = float(args[0]), float(args[1])
                    if last >= 0.99:
                        self.autoscroll = True
                    else:
                        self.autoscroll = False
                except Exception:
                    pass
            try:
                self.log_textbox._scrollbar.set(*args)
            except Exception:
                pass

        self.log_textbox._textbox.configure(yscrollcommand=custom_yscroll)

        def custom_key_binding(event):
            ctrl = (event.state & 0x4) != 0
            if ctrl:
                key = event.keysym.lower()
                if key in ("c", "cyrillic_es") or event.keycode == 67:
                    self.log_textbox._textbox.event_generate("<<Copy>>")
                    return "break"
                elif key in ("a", "cyrillic_fef") or event.keycode == 65:
                    self.log_textbox._textbox.tag_add("sel", "1.0", "end")
                    return "break"
            return None

        self.log_textbox._textbox.bind("<Control-KeyPress>", custom_key_binding)

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

        # Provider selection dropdown
        self.provider_var = ctk.StringVar(value="OpenRouter")
        self.provider_dropdown = ctk.CTkOptionMenu(
            self.left_manager_frame,
            values=[
                "OpenRouter",
                "Ollama",
                "LLM7",
                "Mistral",
                "OpenCode Zen",
                "Google",
            ],
            variable=self.provider_var,
            command=self.on_provider_change,
        )
        self.provider_dropdown.grid(row=0, column=0, padx=10, pady=(10, 5), sticky="ew")

        # Fetch button
        self.fetch_btn = ctk.CTkButton(
            self.left_manager_frame,
            text="Fetch Models",
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
        self.right_manager_frame.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(
            self.right_manager_frame,
            text="Active Rotation Configuration",
            font=ctk.CTkFont(size=14, weight="bold"),
        ).grid(row=0, column=0, pady=(10, 5))

        self.rotation_scroll = ctk.CTkScrollableFrame(self.right_manager_frame)
        self.rotation_scroll.grid(row=1, column=0, padx=10, pady=5, sticky="nsew")
        self.rotation_scroll.grid_columnconfigure(0, weight=1)

        self.save_rotation_btn = ctk.CTkButton(
            self.right_manager_frame,
            text="Save Rotation Config",
            fg_color="#2980B9",
            hover_color="#3498DB",
            command=self.on_save_active_rotation,
        )
        self.save_rotation_btn.grid(row=2, column=0, padx=10, pady=10, sticky="ew")

        # Load active rotation models on start
        self.active_domain_key = "gemini-3.6-flash"
        self.active_rotation_list = []
        self.load_active_rotation_from_disk()

        # Load parallelism settings
        config = load_rotation_config()
        self.parallelism_var.set(config.get("parallelism_enabled", False))
        self.parallel_count_var.set(config.get("parallel_tunnels_count", 3))
        self.per_channel_delay_entry.insert(
            0, str(config.get("per_channel_delay", 0.5))
        )

        # Tab 3: VPN Manager
        self.tab_vpn = self.tabview.tab("VPN Manager")
        self.tab_vpn.grid_columnconfigure(0, weight=1)
        self.tab_vpn.grid_columnconfigure(1, weight=1)
        self.tab_vpn.grid_rowconfigure(0, weight=1)

        # Tab 4: Settings
        self.tab_settings = self.tabview.tab("Settings")
        self.tab_settings.grid_columnconfigure(0, weight=1)
        self.tab_settings.grid_rowconfigure(0, weight=1)

        # Load settings UI
        self.load_settings_ui()

        # Left subframe: VPN Tunnel Controller
        self.vpn_control_frame = ctk.CTkFrame(self.tab_vpn, corner_radius=8)
        self.vpn_control_frame.grid(row=0, column=0, padx=5, pady=5, sticky="nsew")
        self.vpn_control_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            self.vpn_control_frame,
            text="VPN Tunnel Status",
            font=ctk.CTkFont(size=14, weight="bold"),
        ).grid(row=0, column=0, pady=(10, 10))

        # Create a grid frame for 6 channel indicators
        self.channels_frame = ctk.CTkFrame(
            self.vpn_control_frame, fg_color="transparent"
        )
        self.channels_frame.grid(row=1, column=0, pady=(0, 20))
        self.channels_frame.grid_columnconfigure(0, weight=1)
        self.channels_frame.grid_columnconfigure(1, weight=1)
        self.channels_frame.grid_columnconfigure(2, weight=1)

        # Initialize 6 channel status indicators
        self.channel_indicators = {}
        for i in range(1, 7):
            label = ctk.CTkLabel(
                self.channels_frame,
                text=f"● VPN {i} Off",
                text_color="#7F8C8D",
                font=ctk.CTkFont(size=12),
                cursor="hand2",
            )
            label.grid(row=(i - 1) // 3, column=(i - 1) % 3, padx=5, pady=2, sticky="w")
            label.bind(
                "<Button-1>", lambda event, idx=i: self.on_restart_single_tunnel(idx)
            )
            self.channel_indicators[i] = label

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

        self.vpn_forward_btn = ctk.CTkButton(
            self.vpn_control_frame,
            text="Configure Forwarding",
            fg_color="#2980B9",
            hover_color="#3498DB",
            command=self.on_vpn_configure_forwarding,
        )
        self.vpn_forward_btn.grid(row=4, column=0, padx=20, pady=10, sticky="ew")

        # System VPN Routing Frame
        self.system_vpn_frame = ctk.CTkFrame(
            self.vpn_control_frame, fg_color="transparent"
        )
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

        self.vpn_check_ips_btn = ctk.CTkButton(
            self.vpn_control_frame,
            text="Check Tunnels IP",
            fg_color="#8E44AD",
            hover_color="#9B59B6",
            command=self.on_vpn_check_ips,
        )
        self.vpn_check_ips_btn.grid(row=6, column=0, padx=20, pady=10, sticky="ew")

        self.vpn_reset_defaults_btn = ctk.CTkButton(
            self.vpn_control_frame,
            text="Reset to Defaults",
            fg_color="#D35400",
            hover_color="#E67E22",
            command=self.on_vpn_reset_defaults,
        )
        self.vpn_reset_defaults_btn.grid(row=7, column=0, padx=20, pady=10, sticky="ew")

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

        # Refresh model select dropdown lists with current rotation lists
        self.refresh_model_dropdowns()

        self.start_server_subprocess()
        self.poll_queue()
        self.check_subprocess_health()
        self.poll_compactor_stats_loop()

        # Hide briefly for a smooth single-frame layout pass, then show
        self.withdraw()
        self.update_idletasks()
        self.after_idle(self.deiconify)

    def on_thinking_select(self, val):
        config = load_rotation_config()
        primary_model = config.get("primary_model", "")
        if "force_model" not in config or not isinstance(config["force_model"], dict):
            config["force_model"] = {}
        if val in ("Auto (Rotation)", "auto", "Auto (No Forcing)"):
            config["force_model"]["all"] = "auto"
            if primary_model:
                config["force_model"][primary_model] = "auto"
            logger.info("General model forcing disabled (set to Auto).")
            log_queue.put("[GUI] General model forcing disabled (Auto).")
        else:
            config["force_model"]["all"] = val
            if primary_model:
                config["force_model"][primary_model] = val
            logger.info(
                f"General model forcing set to: {val} (all requests forced to this model)"
            )
            log_queue.put(f"[GUI] General model forcing set to: {val}")
        save_rotation_config(config)

    on_force_select = on_thinking_select

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

    def on_filter_context_toggle(self):
        config = load_rotation_config()
        val = self.filter_context_var.get()
        config["filter_context"] = val
        save_rotation_config(config)
        logger.info(f"Filter context set to: {val}")

    def on_model_rotation_toggle(self):
        config = load_rotation_config()
        val = self.model_rotation_var.get()
        config["enable_model_rotation"] = val
        save_rotation_config(config)
        logger.info(f"Models Rotation set to: {val}")

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

    def on_provider_change(self, val):
        logger.info(f"[GUI] Provider changed to: {val}")
        log_queue.put(f"[GUI] Provider changed to: {val}")
        for widget in self.models_scroll.winfo_children():
            widget.destroy()
        self.loaded_models_data.clear()

    def poll_queue(self):
        while not log_queue.empty():
            try:
                msg = log_queue.get_nowait()
                msg = ANSI_ESCAPE.sub("", msg)

                # Color tagging: first check for [LEVELNAME] blocks
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
                elif "[200]" in msg:
                    tag = "info"
                elif "STREAM START" in msg:
                    tag = "info"
                elif "STREAM END" in msg:
                    tag = "info"
                elif "[Compactor]" in msg:
                    tag = "info"
                elif "[VPN " in msg:
                    if "check failed" in msg or "Timeout" in msg:
                        tag = "warning"
                    else:
                        tag = "info"

                self.log_textbox._textbox.insert("end", msg + "\n", tag)
                if self.autoscroll:
                    self.log_textbox._textbox.see("end")
            except Exception:
                break
        self.after(300, self.poll_queue)

    def start_server_subprocess(self):
        self.stop_server_subprocess()
        # Kill any orphan process still holding our port
        self._free_port(self.port)
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

    def _free_port(self, port: int):
        """Kill any orphan process holding the given TCP port."""
        try:
            result = subprocess.run(
                [
                    "powershell",
                    "-Command",
                    f"Get-NetTCPConnection -LocalPort {port} -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess",
                ],
                capture_output=True,
                text=True,
                errors="replace",
                timeout=5.0,
            )
            if result.stdout and result.stdout.strip():
                for pid in result.stdout.strip().splitlines():
                    pid = pid.strip()
                    if pid and pid.isdigit():
                        subprocess.run(
                            ["taskkill", "/F", "/PID", pid],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                        )
                        logger.info(
                            f"[GUI] Killed orphan process PID {pid} holding port {port}."
                        )
        except Exception as e:
            logger.debug(f"[GUI] Failed to free port {port}: {e}")

    def check_subprocess_health(self):
        """Monitor server subprocess health. Only schedules next check if process is alive."""
        if self.server_process is not None and not self._restart_pending:
            ret_code = self.server_process.poll()
            if ret_code is not None:
                # Read any remaining stderr from the dying process for diagnostics
                stderr_debug = ""
                try:
                    remaining = self.server_process.stderr.read()
                    if remaining:
                        stderr_debug = remaining[-500:]
                except Exception:
                    pass

                log_queue.put(
                    f"[GUI] [WARNING] Proxy server subprocess died with code {ret_code}."
                )
                if stderr_debug:
                    log_queue.put(f"[GUI] [DEBUG] Last stderr: {stderr_debug}")

                timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                ERROR_LOG_PATH = "proxy_errors.log"
                try:
                    with open(ERROR_LOG_PATH, "a", encoding="utf-8") as f:
                        f.write(
                            f"[{timestamp}] [ERROR] Proxy subprocess crashed/exited with code {ret_code}.\n"
                        )
                        if stderr_debug:
                            f.write(f"[{timestamp}] [STDERR] {stderr_debug}\n")
                except Exception as e:
                    logger.error(f"Failed to write to proxy_errors.log: {e}")

                self.restart_count += 1
                if self.restart_count >= 10:
                    log_queue.put(
                        "[GUI] [CRITICAL] Proxy server crashed 10+ times. Giving up. Please check proxy_errors.log and fix the issue."
                    )
                    logger.error(
                        f"Proxy server crashed {self.restart_count} times. Auto-restart disabled."
                    )
                    self.server_process = None
                    return

                delay = min(self.restart_backoff, 30.0)
                log_queue.put(
                    f"[GUI] [SYSTEM] Restarting in {delay:.0f}s (attempt #{self.restart_count}/10)..."
                )
                self.restart_backoff = min(self.restart_backoff * 2, 30.0)
                self._restart_pending = True
                self.server_process = None
                # Don't schedule next health check — _do_restart will resume it
                self.after(int(delay * 1000), self._do_restart)
                return
            else:
                # Server is alive — reset backoff
                self.restart_count = 0
                self.restart_backoff = 1.0
        # Schedule next check only when process is alive or no restart pending
        self.after(1000, self.check_subprocess_health)

    def _do_restart(self):
        """Internal restart helper — starts process and resumes health check loop."""
        self._restart_pending = False
        self.start_server_subprocess()
        self.after(1000, self.check_subprocess_health)

    def on_close(self):
        self.stop_server_subprocess()
        if hasattr(self, "vpn_manager") and self.vpn_manager is not None:
            try:
                logger.info("[GUI] Cleaning up VPN tunnels on close...")
                self.vpn_manager.disable_system_routing()
                self.vpn_manager.uninstall_all_services()
                # Update config
                from proxy_core.config import load_rotation_config, save_rotation_config

                config = load_rotation_config()
                config["system_vpn_active"] = False
                save_rotation_config(config)
            except Exception as e:
                logger.error(f"[GUI] Error during VPN cleanup on close: {e}")
        self.destroy()

    def on_fetch_free_models(self):
        """Asynchronously fetch models from selected provider in a background thread."""
        self.fetch_btn.configure(state="disabled", text="Fetching...")
        provider = self.provider_var.get()

        def do_fetch():
            import urllib.request

            if provider == "OpenRouter":
                url = "https://openrouter.ai/api/v1/models"
                try:
                    req = urllib.request.Request(
                        url, headers={"User-Agent": "Mozilla/5.0"}
                    )
                    with urllib.request.urlopen(req, timeout=8.0) as response:
                        raw_data = response.read().decode("utf-8")
                        logger.info(
                            f"[GUI] OpenRouter models response:\n{beautify_json_string(raw_data)}"
                        )
                        data = json.loads(raw_data)
                        free_models = []
                        for m in data.get("data", []):
                            pricing = m.get("pricing", {})
                            is_prompt_free = float(pricing.get("prompt", 0)) == 0.0
                            is_completion_free = (
                                float(pricing.get("completion", 0)) == 0.0
                            )
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
                        # Sort by id
                        free_models = sorted(free_models, key=lambda x: x["id"])
                        self.after(0, lambda: self.render_free_models(free_models))
                except Exception as e:
                    logger.error(f"[GUI] Failed to fetch OpenRouter models: {e}")
                    self.after(
                        0,
                        lambda: self.fetch_btn.configure(
                            state="normal", text="Fetch Models"
                        ),
                    )

            elif provider == "Ollama":
                url = "https://ollama.com/v1/models"
                try:
                    from proxy_core.rotation import OLLAMA_CLOUD_KEYS

                    headers = {"User-Agent": "Mozilla/5.0"}
                    if OLLAMA_CLOUD_KEYS:
                        headers["Authorization"] = f"Bearer {OLLAMA_CLOUD_KEYS[0]}"
                    req = urllib.request.Request(url, headers=headers)
                    with urllib.request.urlopen(req, timeout=8.0) as response:
                        raw_data = response.read().decode("utf-8")
                        logger.info(
                            f"[GUI] Ollama models response:\n{beautify_json_string(raw_data)}"
                        )
                        data = json.loads(raw_data)
                        models = []
                        for m in data.get("data", []):
                            models.append(
                                {
                                    "id": m.get("id"),
                                    "name": m.get("id"),
                                    "context_length": "unknown",
                                    "provider": "ollama_cloud",
                                }
                            )
                        # Sort by id
                        models = sorted(models, key=lambda x: x["id"])
                        self.after(0, lambda: self.render_free_models(models))
                except Exception as e:
                    logger.error(f"[GUI] Failed to fetch Ollama models: {e}")
                    self.after(
                        0,
                        lambda: self.fetch_btn.configure(
                            state="normal", text="Fetch Models"
                        ),
                    )

            elif provider == "LLM7":
                url = "https://api.llm7.io/v1/models"
                try:
                    from proxy_core.rotation import LLM7_KEYS

                    headers = {"User-Agent": "Mozilla/5.0"}
                    if LLM7_KEYS:
                        headers["Authorization"] = f"Bearer {LLM7_KEYS[0]}"
                    req = urllib.request.Request(url, headers=headers)
                    with urllib.request.urlopen(req, timeout=8.0) as response:
                        raw_data = response.read().decode("utf-8")
                        logger.info(
                            f"[GUI] LLM7 models response:\n{beautify_json_string(raw_data)}"
                        )
                        data = json.loads(raw_data)
                        models = []
                        # Since LLM7 returns a list directly
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
                        # Sort by id
                        models = sorted(models, key=lambda x: x["id"])
                        self.after(0, lambda: self.render_free_models(models))
                except Exception as e:
                    logger.error(f"[GUI] Failed to fetch LLM7 models: {e}")
                    self.after(
                        0,
                        lambda: self.fetch_btn.configure(
                            state="normal", text="Fetch Models"
                        ),
                    )

            elif provider == "Mistral":
                url = "https://api.mistral.ai/v1/models"
                try:
                    from proxy_core.rotation import MISTRAL_KEYS

                    headers = {"User-Agent": "Mozilla/5.0"}
                    if MISTRAL_KEYS:
                        headers["Authorization"] = f"Bearer {MISTRAL_KEYS[0]}"
                    req = urllib.request.Request(url, headers=headers)
                    with urllib.request.urlopen(req, timeout=8.0) as response:
                        raw_data = response.read().decode("utf-8")
                        logger.info(
                            f"[GUI] Mistral models response:\n{beautify_json_string(raw_data)}"
                        )
                        data = json.loads(raw_data)
                        models = []
                        for m in data.get("data", []):
                            models.append(
                                {
                                    "id": m.get("id"),
                                    "name": m.get("id"),
                                    "context_length": "unknown",
                                    "provider": "mistral",
                                }
                            )
                        # Sort by id
                        models = sorted(models, key=lambda x: x["id"])
                        self.after(0, lambda: self.render_free_models(models))
                except Exception as e:
                    logger.error(f"[GUI] Failed to fetch Mistral models: {e}")
                    self.after(
                        0,
                        lambda: self.fetch_btn.configure(
                            state="normal", text="Fetch Models"
                        ),
                    )

            elif provider == "OpenCode Zen":
                url = "https://opencode.ai/zen/v1/models"
                try:
                    from proxy_core.rotation import OPENCODE_KEYS

                    headers = {"User-Agent": "Mozilla/5.0"}
                    if OPENCODE_KEYS:
                        headers["Authorization"] = f"Bearer {OPENCODE_KEYS[0]}"
                    req = urllib.request.Request(url, headers=headers)
                    with urllib.request.urlopen(req, timeout=8.0) as response:
                        raw_data = response.read().decode("utf-8")
                        logger.info(
                            f"[GUI] OpenCode Zen models response:\n{beautify_json_string(raw_data)}"
                        )
                        data = json.loads(raw_data)
                        models = []
                        for m in data.get("data", []):
                            models.append(
                                {
                                    "id": m.get("id"),
                                    "name": m.get("id"),
                                    "context_length": "unknown",
                                    "provider": "opencode_zen",
                                }
                            )
                        # Sort by id
                        models = sorted(models, key=lambda x: x["id"])
                        self.after(0, lambda: self.render_free_models(models))
                except Exception as e:
                    logger.error(f"[GUI] Failed to fetch OpenCode Zen models: {e}")
                    self.after(
                        0,
                        lambda: self.fetch_btn.configure(
                            state="normal", text="Fetch Models"
                        ),
                    )

            elif provider == "Google":
                try:
                    from proxy_core.rotation import API_KEYS
                    from proxy_core.state import COOLDOWNS, LAST_USED

                    if not API_KEYS:
                        raise ValueError("No Google API keys configured.")

                    now = time.time()
                    available_keys = [
                        k for k in API_KEYS if COOLDOWNS.get(k, 0.0) < now
                    ]
                    if not available_keys:
                        available_keys = API_KEYS
                    available_keys = sorted(
                        available_keys, key=lambda k: LAST_USED.get(k, 0.0)
                    )

                    raw_data = None
                    last_err = None
                    for api_key in available_keys:
                        url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
                        headers = {
                            "User-Agent": "Mozilla/5.0",
                            "x-goog-api-key": api_key,
                        }
                        try:
                            req = urllib.request.Request(url, headers=headers)
                            with urllib.request.urlopen(req, timeout=8.0) as response:
                                raw_data = response.read().decode("utf-8")
                                LAST_USED[api_key] = time.time()
                                break
                        except Exception as err:
                            last_err = err
                            key_num = (
                                API_KEYS.index(api_key) + 1
                                if api_key in API_KEYS
                                else 0
                            )
                            logger.warning(
                                f"[GUI] Fetch Google models failed with key [key#{key_num}]: {err}. Rotating key..."
                            )

                    if raw_data is None:
                        raise last_err or RuntimeError(
                            "Failed to fetch Google models with available keys."
                        )

                    logger.info(
                        f"[GUI] Google models response:\n{beautify_json_string(raw_data)}"
                    )
                    data = json.loads(raw_data)
                    models = []
                    for m in data.get("models", []):
                        model_id = m.get("name", "")
                        if model_id.startswith("models/"):
                            model_id = model_id[7:]
                        models.append(
                            {
                                "id": model_id,
                                "name": m.get("displayName", model_id),
                                "context_length": m.get("inputTokenLimit", "unknown"),
                                "provider": "google",
                            }
                        )
                    # Sort by id
                    models = sorted(models, key=lambda x: x["id"])
                    self.after(0, lambda: self.render_free_models(models))
                except Exception as e:
                    logger.error(f"[GUI] Failed to fetch Google models: {e}")
                    self.after(
                        0,
                        lambda: self.fetch_btn.configure(
                            state="normal", text="Fetch Models"
                        ),
                    )

        threading.Thread(target=do_fetch, daemon=True).start()

    def load_settings_ui(self):
        """Load and render the Settings tab UI."""
        config = load_rotation_config()

        # Main settings frame
        settings_frame = ctk.CTkFrame(self.tab_settings, corner_radius=8)
        settings_frame.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
        settings_frame.grid_columnconfigure(0, weight=1)
        settings_frame.grid_columnconfigure(1, weight=1)

        # Key Cooldown Duration
        ctk.CTkLabel(
            settings_frame,
            text="Key Cooldown Duration (seconds):",
            font=ctk.CTkFont(size=12, weight="bold"),
        ).grid(row=0, column=0, padx=10, pady=(10, 2), sticky="w")

        self.cooldown_entry = ctk.CTkEntry(settings_frame)
        self.cooldown_entry.insert(0, str(config.get("key_cooldown_duration", 90)))
        self.cooldown_entry.grid(row=1, column=0, padx=10, pady=(0, 10), sticky="ew")

        # Connect Timeout (Column 1)
        connect_label = ctk.CTkLabel(
            settings_frame,
            text="Connect Timeout (seconds):",
            font=ctk.CTkFont(size=12, weight="bold"),
        )
        connect_label.grid(row=0, column=1, padx=10, pady=(10, 2), sticky="w")
        self.connect_timeout_entry = ctk.CTkEntry(settings_frame)
        self.connect_timeout_entry.insert(0, str(config.get("connect_timeout", 15.0)))
        self.connect_timeout_entry.grid(
            row=1, column=1, padx=10, pady=(0, 10), sticky="ew"
        )

        CTkToolTip(
            connect_label,
            "Тайм-аут установки TCP-соединения с сервером.\nРекомендуется: 10-15 сек.",
        )
        CTkToolTip(
            self.connect_timeout_entry,
            "Тайм-аут установки TCP-соединения с сервером.\nРекомендуется: 10-15 сек.",
        )

        # VPN Disabled Pause Sleep
        ctk.CTkLabel(
            settings_frame,
            text="VPN Disabled Pause Sleep (seconds):",
            font=ctk.CTkFont(size=12, weight="bold"),
        ).grid(row=2, column=0, padx=10, pady=(10, 2), sticky="w")

        self.pause_sleep_entry = ctk.CTkEntry(settings_frame)
        self.pause_sleep_entry.insert(
            0, str(config.get("vpn_disabled_pause_sleep", 65.0))
        )
        self.pause_sleep_entry.grid(row=3, column=0, padx=10, pady=(0, 10), sticky="ew")

        # Read Timeout (Column 1)
        read_label = ctk.CTkLabel(
            settings_frame,
            text="Read Timeout (seconds):",
            font=ctk.CTkFont(size=12, weight="bold"),
        )
        read_label.grid(row=2, column=1, padx=10, pady=(10, 2), sticky="w")
        self.read_timeout_entry = ctk.CTkEntry(settings_frame)
        self.read_timeout_entry.insert(0, str(config.get("read_timeout", 120.0)))
        self.read_timeout_entry.grid(
            row=3, column=1, padx=10, pady=(0, 10), sticky="ew"
        )

        CTkToolTip(
            read_label,
            "Тайм-аут ожидания ответа/чанка от модели.\nУвеличьте для медленных моделей с большим контекстом.\nРекомендуется: 60-180 сек.",
        )
        CTkToolTip(
            self.read_timeout_entry,
            "Тайм-аут ожидания ответа/чанка от модели.\nУвеличьте для медленных моделей с большим контекстом.\nРекомендуется: 60-180 сек.",
        )

        # Max Exponential Sleep
        ctk.CTkLabel(
            settings_frame,
            text="Max Exponential Sleep (seconds):",
            font=ctk.CTkFont(size=12, weight="bold"),
        ).grid(row=4, column=0, padx=10, pady=(10, 2), sticky="w")

        self.max_sleep_entry = ctk.CTkEntry(settings_frame)
        self.max_sleep_entry.insert(0, str(config.get("max_exponential_sleep", 65.0)))
        self.max_sleep_entry.grid(row=5, column=0, padx=10, pady=(0, 10), sticky="ew")

        # Save Settings Button
        self.save_settings_btn = ctk.CTkButton(
            settings_frame,
            text="Save Settings",
            fg_color="#27AE60",
            hover_color="#2ECC71",
            command=self.on_save_settings,
        )
        self.save_settings_btn.grid(row=6, column=0, padx=10, pady=20, sticky="ew")

        # Global Reset Button (prominent and red)
        self.global_reset_btn = ctk.CTkButton(
            settings_frame,
            text="⚠️ GLOBAL SYSTEM RESET ⚠️",
            fg_color="#C0392B",
            hover_color="#E74C3C",
            font=ctk.CTkFont(size=14, weight="bold"),
            command=self.on_global_reset,
        )
        self.global_reset_btn.grid(row=7, column=0, padx=10, pady=10, sticky="ew")

    def on_save_settings(self):
        """Save the settings to config_rotation.json."""
        try:
            config = load_rotation_config()

            # Update settings from entry fields
            config["key_cooldown_duration"] = float(self.cooldown_entry.get())
            config["vpn_disabled_pause_sleep"] = float(self.pause_sleep_entry.get())
            config["max_exponential_sleep"] = float(self.max_sleep_entry.get())
            config["connect_timeout"] = float(self.connect_timeout_entry.get())
            config["read_timeout"] = float(self.read_timeout_entry.get())

            save_rotation_config(config)
            logger.info("[GUI] Settings saved successfully.")
            log_queue.put("[GUI] Settings saved successfully.")
        except Exception as e:
            logger.error(f"[GUI] Failed to save settings: {e}")
            log_queue.put(f"[GUI] [ERROR] Failed to save settings: {e}")

    def on_global_reset(self):
        """Trigger a global system reset via the new endpoint."""
        import httpx
        import threading

        def do_global_reset():
            url = f"http://{self.host}:{self.port}/control/global_reset"
            try:
                r = httpx.post(url, timeout=5.0)
                if r.status_code == 200:
                    logger.info("[GUI] Global reset completed successfully.")
                    log_queue.put("[GUI] Global reset completed successfully.")
                else:
                    logger.error(f"[GUI] Global reset failed: HTTP {r.status_code}")
                    log_queue.put(
                        f"[GUI] [ERROR] Global reset failed: HTTP {r.status_code}"
                    )
            except Exception as ex:
                logger.error(f"[GUI] Failed to connect for global reset: {ex}")
                log_queue.put(f"[GUI] [ERROR] Failed to connect for global reset: {ex}")

        self.global_reset_btn.configure(state="disabled", text="Resetting...")
        threading.Thread(target=do_global_reset, daemon=True).start()
        self.after(
            2000,
            lambda: self.global_reset_btn.configure(
                state="normal", text="⚠️ GLOBAL SYSTEM RESET ⚠️"
            ),
        )

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

            # Info text (ID, provider and context)
            info_text = f"{m['name']}\n({m['id']})\nProv: {m.get('provider', 'unknown')}\nCtx: {m['context_length']}"
            lbl = ctk.CTkLabel(
                row_frame, text=info_text, font=self.font_normal_10, justify="left"
            )
            lbl.grid(row=0, column=0, padx=5, pady=2, sticky="w")

            # Status Badge (circle indicator)
            badge = ctk.CTkLabel(
                row_frame, text="●", text_color="#7F8C8D", font=self.font_bold_16
            )
            badge.grid(row=0, column=1, padx=5)

            # Test Button
            provider = m.get("provider", "openrouter")
            test_cb = lambda model_id=m["id"], b=badge, p=provider: (
                self.on_test_individual_model(model_id, b, p)
            )
            btn_test = ctk.CTkButton(
                row_frame,
                text="Test",
                width=45,
                height=20,
                font=self.font_normal_9,
                corner_radius=2,
                command=test_cb,
            )
            btn_test.grid(row=0, column=2, padx=2)

            # Add to Rotation Button
            add_cb = lambda model_id=m["id"], p=m.get("provider", "openrouter"): (
                self.on_add_model_to_rotation(model_id, p)
            )
            btn_add = ctk.CTkButton(
                row_frame,
                text="+ Add",
                width=45,
                height=20,
                font=self.font_normal_9,
                fg_color="#27AE60",
                hover_color="#2ECC71",
                corner_radius=2,
                command=add_cb,
            )
            btn_add.grid(row=0, column=3, padx=2)

        self.fetch_btn.configure(state="normal", text="Fetch Models")

    def on_test_individual_model(self, model_id, badge_widget, provider):
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
                    json={"model": model_id, "provider": provider},
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

    def on_add_model_to_rotation(self, model_id, provider=None):
        """Add a model from scan to the end of the active rotation list and thinking_models list, with provider prefix."""
        prefixed_model_id = model_id
        if (
            provider
            and provider != "gemini"
            and not model_id.startswith(f"{provider}/")
        ):
            prefixed_model_id = f"{provider}/{model_id}"

        if prefixed_model_id not in self.active_rotation_list:
            self.active_rotation_list.append(prefixed_model_id)
            self.render_rotation_list()

            # Automatically sync to thinking_models and rotation_lists in config so it is available to force
            try:
                config = load_rotation_config()
                if "rotation_lists" not in config:
                    config["rotation_lists"] = {}
                config["rotation_lists"][self.active_domain_key] = list(
                    self.active_rotation_list
                )
                config["thinking_models"] = list(self.active_rotation_list)
                save_rotation_config(config)
                self.refresh_model_dropdowns()
            except Exception as e:
                logger.warning(f"Failed to auto-add model to rotation config: {e}")

            logger.info(
                f"[GUI] Added model '{prefixed_model_id}' to rotation and forced model lists."
            )
            log_queue.put(
                f"[GUI] Added model '{prefixed_model_id}' to rotation and forced model lists."
            )

    def load_active_rotation_from_disk(self):
        """Load and display the active rotation list from config based on active domain."""
        config = load_rotation_config()
        self.active_rotation_list = config.get("rotation_lists", {}).get(
            self.active_domain_key, []
        )
        self.render_rotation_list()

    def on_save_parallelism_settings(self):
        config = load_rotation_config()
        config["parallelism_enabled"] = self.parallelism_var.get()
        config["parallel_tunnels_count"] = int(self.parallel_count_var.get())

        # Parse delay entry safely
        try:
            delay_val = float(self.per_channel_delay_entry.get())
            if delay_val < 0.0:
                delay_val = 0.0
            config["per_channel_delay"] = delay_val
        except ValueError:
            # Fallback to current config value or 0.5 if invalid
            config["per_channel_delay"] = config.get("per_channel_delay", 0.5)

        save_rotation_config(config)
        log_queue.put("[GUI] Parallelism settings saved.")

    def render_rotation_list(self):
        """Render the ordered rotation models in the configurator frame with status badges and test buttons."""
        for widget in self.rotation_scroll.winfo_children():
            widget.destroy()

        for idx, model_id in enumerate(self.active_rotation_list):
            row_frame = ctk.CTkFrame(self.rotation_scroll, fg_color="transparent")
            row_frame.grid(row=idx, column=0, padx=2, pady=2, sticky="ew")
            row_frame.grid_columnconfigure(0, weight=1)

            lbl = ctk.CTkLabel(row_frame, text=model_id, font=self.font_bold_10)
            lbl.grid(row=0, column=0, padx=5, pady=2, sticky="w")

            # Status Badge (circle indicator)
            badge = ctk.CTkLabel(
                row_frame,
                text="●",
                text_color="#7F8C8D",
                font=self.font_bold_14,
            )
            badge.grid(row=0, column=1, padx=5)

            # Test Button
            # Determine provider and clean model ID from the rotation string
            provider = "gemini"
            clean_model_id = model_id
            for p in [
                "openrouter",
                "ollama",
                "llm7",
                "mistral",
                "gemini",
                "ollama_cloud",
                "opencode_zen",
                "opencode",
                "google",
            ]:
                if model_id.startswith(f"{p}/"):
                    provider = p
                    clean_model_id = model_id[len(p) + 1 :]
                    break
            else:
                if "/" in model_id or model_id.endswith(":free"):
                    provider = "openrouter"
                elif model_id.startswith("llm7-") or model_id.startswith("qwen3-"):
                    provider = "llm7"

            # OpenCode Zen is the canonical provider for both opencode_zen/ and opencode/ prefixes
            if provider == "opencode":
                provider = "opencode_zen"
            # Ollama rotation entries route through the cloud provider
            if provider == "ollama":
                provider = "ollama_cloud"

            test_cb = lambda m=clean_model_id, b=badge, p=provider: (
                self.on_test_individual_model(m, b, p)
            )
            btn_test = ctk.CTkButton(
                row_frame,
                text="Test",
                width=40,
                height=18,
                font=self.font_bold_8,
                corner_radius=2,
                command=test_cb,
            )
            btn_test.grid(row=0, column=2, padx=2)

            # Up button
            up_cb = lambda i=idx: self.on_shift_model_priority(i, direction=-1)
            btn_up = ctk.CTkButton(
                row_frame,
                text="▲",
                width=22,
                height=18,
                font=self.font_normal_8,
                corner_radius=2,
                command=up_cb,
            )
            btn_up.grid(row=0, column=3, padx=1)

            # Down button
            down_cb = lambda i=idx: self.on_shift_model_priority(i, direction=1)
            btn_down = ctk.CTkButton(
                row_frame,
                text="▼",
                width=22,
                height=18,
                font=self.font_normal_8,
                corner_radius=2,
                command=down_cb,
            )
            btn_down.grid(row=0, column=4, padx=1)

            # Remove button
            del_cb = lambda m=model_id: self.on_remove_model_from_rotation(m)
            btn_del = ctk.CTkButton(
                row_frame,
                text="✕",
                width=22,
                height=18,
                text_color="#E74C3C",
                font=self.font_normal_8,
                fg_color="transparent",
                hover_color="#2c2c2c",
                corner_radius=2,
                command=del_cb,
            )
            btn_del.grid(row=0, column=5, padx=1)

    def on_shift_model_priority(self, index, direction):
        """Shift model priority up (-1) or down (+1) in the rotation list."""
        new_index = index + direction
        if 0 <= new_index < len(self.active_rotation_list):
            self.active_rotation_list[index], self.active_rotation_list[new_index] = (
                self.active_rotation_list[new_index],
                self.active_rotation_list[index],
            )
            self.render_rotation_list()

    def on_remove_model_from_rotation(self, model_id):
        """Remove a model from the local in-memory rotation list."""
        if model_id in self.active_rotation_list:
            self.active_rotation_list.remove(model_id)
            self.render_rotation_list()

    def on_save_active_rotation(self):
        """Save the configured rotation lists and sync all models to thinking_models in config_rotation.json."""
        try:
            config = load_rotation_config()
            if "rotation_lists" not in config:
                config["rotation_lists"] = {}
            config["rotation_lists"][self.active_domain_key] = list(
                self.active_rotation_list
            )
            config["thinking_models"] = list(self.active_rotation_list)
            save_rotation_config(config)
            logger.info(
                f"[GUI] Successfully saved active {self.active_domain_key} rotation configuration on disk!"
            )
            log_queue.put(
                f"[GUI] Successfully saved active {self.active_domain_key} rotation configuration!"
            )
            self.refresh_model_dropdowns()
        except Exception as e:
            logger.error(f"[GUI] Failed to save rotation config: {e}")
            log_queue.put(f"[GUI] [ERROR] Failed to save rotation config: {e}")

    def refresh_model_dropdowns(self):
        """Refresh the general forced model selection dropdown list on the left panel."""
        try:
            config = load_rotation_config()
            rotation_lists = config.get("rotation_lists", {})
            primary_model = config.get("primary_model", "gemini-3.6-flash")

            if hasattr(self, "active_rotation_list") and self.active_rotation_list:
                active_list = list(self.active_rotation_list)
            else:
                active_list = rotation_lists.get(primary_model, [])
                if not active_list:
                    active_list = config.get("thinking_models", [])

            # Ensure unique and preserve order, prepend Auto (Rotation)
            forced_values = ["Auto (Rotation)"]
            for m in active_list:
                if m and m not in forced_values:
                    forced_values.append(m)

            # Update option menu values
            self.thinking_select.configure(values=forced_values)

            # Restore current selection or set to Auto if not found
            force_model_config = config.get("force_model", {})
            if isinstance(force_model_config, dict):
                forced_val = force_model_config.get("all") or force_model_config.get(
                    primary_model, "auto"
                )
            elif isinstance(force_model_config, str):
                forced_val = force_model_config
            else:
                forced_val = "auto"

            if forced_val == "auto" or forced_val not in forced_values:
                self.thinking_select.set("Auto (Rotation)")
                if (
                    forced_val != "auto"
                    and forced_val not in forced_values
                    and primary_model
                ):
                    if isinstance(force_model_config, dict):
                        config.setdefault("force_model", {})["all"] = "auto"
                        config.setdefault("force_model", {})[primary_model] = "auto"
                    else:
                        config["force_model"] = {"all": "auto"}
                    save_rotation_config(config)
            else:
                self.thinking_select.set(forced_val)

            logger.info(
                "[GUI] Refreshed forced model selection dropdown list with active rotation models."
            )
        except Exception as e:
            logger.error(f"[GUI] Failed to refresh model dropdowns: {e}")

    def on_restart_single_tunnel(self, idx: int):
        """Restart a single VPN tunnel by index in a background thread."""
        if not hasattr(self, "vpn_manager") or self.vpn_manager is None:
            log_queue.put("[GUI] [ERROR] VPN Manager library is not loaded.")
            return
        if not self.vpn_manager.is_admin():
            log_queue.put(
                "[GUI] [WARNING] Admin privileges required to restart tunnels."
            )
            return

        log_queue.put(
            f"[GUI] [SYSTEM] Restarting VPN tunnel {idx} in the background..."
        )

        # Immediate visual feedback - yellow for restarting
        for indicators in (self.channel_indicators, self.sidebar_vpn_lamps):
            if idx in indicators:
                indicators[idx].configure(text_color="#F1C40F")
        CTkToolTip(self.sidebar_vpn_lamps[idx], f"VPN {idx}: Restarting...")

        def run_restart():
            try:
                from proxy_core.rotation import restart_vpn_service

                success = restart_vpn_service(idx)
                if not success:
                    for attempt in range(1, 4):
                        log_queue.put(
                            f"[GUI] [WARNING] VPN {idx} failed to initialize route. Retrying restart (attempt {attempt}/3)..."
                        )
                        success = restart_vpn_service(idx)
                        if success:
                            break
                if success:
                    log_queue.put(
                        f"[GUI] [SUCCESS] VPN {idx} is fully ready and routed after retry!"
                    )
                else:
                    log_queue.put(
                        f"[GUI] [WARNING] VPN {idx} failed to initialize route within timeout after 3 retries."
                    )
            except Exception as e:
                logger.error(f"[GUI] Failed to restart VPN tunnel {idx}: {e}")
                log_queue.put(f"[GUI] [ERROR] Failed to restart VPN tunnel {idx}: {e}")
            finally:
                self.after(0, self.do_poll_vpn_status)

        import threading

        threading.Thread(target=run_restart, daemon=True).start()

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

        if hasattr(self, "vpn_start_btn") and self.vpn_start_btn:
            self.vpn_start_btn.configure(state="disabled", text="Starting...")
        log_queue.put(
            "[GUI] [SYSTEM] Installing and starting all 6 VPN tunnels in the background..."
        )

        def run_start():
            import threading
            from proxy_core.rotation import wait_for_adapter_and_add_route

            try:
                self.vpn_manager.uninstall_all_services(print_cb=log_queue.put)
                log_queue.put(
                    "[GUI] [SYSTEM] Installing and starting all 6 VPN tunnels in parallel..."
                )

                def start_single_tunnel(i):
                    name = f"vpn{i}"
                    conf_path = os.path.join(
                        self.vpn_manager.configs_dir, f"{name}.conf"
                    )
                    if os.path.exists(conf_path):
                        # Install service
                        subprocess.run(
                            [
                                self.vpn_manager.wg_path,
                                "/installtunnelservice",
                                conf_path,
                            ],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                        )
                        # Set startup type to Manual
                        subprocess.run(
                            [
                                "powershell",
                                "-Command",
                                f"Set-Service -Name 'WireGuardTunnel$vpn{i}' -StartupType Manual",
                            ],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                        )
                        log_queue.put(
                            f"[GUI] [SYSTEM] Service vpn{i} started. Waiting for adapter..."
                        )

                        # Wait for adapter and add route (with retries)
                        success = wait_for_adapter_and_add_route(i, timeout=60.0)
                        if not success:
                            for attempt in range(1, 4):
                                log_queue.put(
                                    f"[GUI] [WARNING] VPN {i} failed to initialize route. Retrying (attempt {attempt}/3)..."
                                )
                                subprocess.run(
                                    [
                                        "powershell",
                                        "-Command",
                                        f"Restart-Service -Name 'WireGuardTunnel$vpn{i}' -ErrorAction SilentlyContinue",
                                    ],
                                    stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL,
                                )
                                success = wait_for_adapter_and_add_route(
                                    i, timeout=60.0
                                )
                                if success:
                                    break
                        if success:
                            log_queue.put(
                                f"[GUI] [SUCCESS] VPN {i} is fully ready and routed!"
                            )
                        else:
                            log_queue.put(
                                f"[GUI] [WARNING] VPN {i} failed to initialize route within timeout."
                            )
                    else:
                        log_queue.put(f"[GUI] [ERROR] Config not found for vpn{i}")

                threads = []
                for i in range(1, 7):
                    t = threading.Thread(
                        target=start_single_tunnel, args=(i,), daemon=True
                    )
                    t.start()
                    threads.append(t)

                # Wait for all threads to complete
                for t in threads:
                    t.join()

                log_queue.put("[GUI] [SUCCESS] Parallel VPN startup completed!")
            except Exception as e:
                logger.error(f"[GUI] Error starting tunnels: {e}")
                log_queue.put(f"[GUI] [ERROR] Error starting tunnels: {e}")
            finally:
                self.after(
                    0,
                    lambda: (
                        hasattr(self, "vpn_start_btn")
                        and self.vpn_start_btn
                        and self.vpn_start_btn.configure(
                            state="normal", text="Start Tunnels"
                        )
                    ),
                )
                self.after(0, self.do_poll_vpn_status)

        threading.Thread(target=run_start, daemon=True).start()

    def on_vpn_configure_forwarding(self):
        """Manually execute the forward tunnel routing script in a background thread."""
        if not hasattr(self, "vpn_manager") or self.vpn_manager is None:
            log_queue.put("[GUI] [ERROR] VPN Manager library is not loaded.")
            return

        if not self.vpn_manager.is_admin():
            logger.info(
                "[GUI] Requesting Windows Administrator privileges to run forwarding setup..."
            )
            log_queue.put(
                "[GUI] [SYSTEM] WireGuard requires Administrator privileges. Requesting UAC elevation..."
            )
            self.vpn_manager.elevate()
            return

        self.vpn_forward_btn.configure(state="disabled", text="Configuring...")
        log_queue.put(
            "[GUI] [SYSTEM] Manually configuring forward tunnel routes via forawrd_tunnels.ps1..."
        )

        def run_manual_forward():
            try:
                script_path = (
                    r"D:\Work\Active\server-services\vpn_switcher\forawrd_tunnels.ps1"
                )
                result = subprocess.run(
                    [
                        "powershell",
                        "-ExecutionPolicy",
                        "Bypass",
                        "-File",
                        script_path,
                    ],
                    capture_output=True,
                    text=True,
                    errors="replace",
                    timeout=30.0,
                )
                if result.stdout and result.stdout.strip():
                    for line in result.stdout.strip().splitlines():
                        log_queue.put(f"[PS1] {line}")
                if result.stderr and result.stderr.strip():
                    logger.warning(f"[PS1] Stderr: {result.stderr.strip()[-300:]}")
                if result.returncode == 0:
                    log_queue.put(
                        "[GUI] [SUCCESS] Forward tunnel routes configured successfully."
                    )
                else:
                    log_queue.put(
                        f"[GUI] [WARNING] forawrd_tunnels.ps1 exited with code {result.returncode}."
                    )
            except subprocess.TimeoutExpired:
                log_queue.put(
                    "[GUI] [WARNING] forawrd_tunnels.ps1 timed out after 30s."
                )
            except Exception as e:
                logger.error(f"[GUI] Error running forawrd_tunnels.ps1: {e}")
                log_queue.put(
                    f"[GUI] [ERROR] Failed to configure forward tunnel routes: {e}"
                )
            finally:
                self.after(
                    0,
                    lambda: self.vpn_forward_btn.configure(
                        state="normal", text="Configure Forwarding"
                    ),
                )

        threading.Thread(target=run_manual_forward, daemon=True).start()

    def on_vpn_check_ips(self):
        """Check and display the external IP of every active tunnel in a background thread."""
        if not hasattr(self, "vpn_manager") or self.vpn_manager is None:
            log_queue.put("[GUI] [ERROR] VPN Manager library is not loaded.")
            return

        if hasattr(self, "vpn_check_ips_btn") and self.vpn_check_ips_btn:
            self.vpn_check_ips_btn.configure(state="disabled", text="Checking IPs...")

        log_queue.put("[GUI] [SYSTEM] Checking external IPs of all VPN tunnels...")

        def run_check():
            import httpx
            import threading

            results = {}
            threads = []

            def check_ip(idx):
                try:
                    transport = httpx.HTTPTransport(local_address=f"10.8.0.1{idx}")
                    with httpx.Client(transport=transport, timeout=5.0) as client:
                        resp = client.get("https://api.ipify.org?format=json")
                        if resp.status_code == 200:
                            results[idx] = resp.json().get("ip", "Unknown")
                        else:
                            results[idx] = f"HTTP {resp.status_code}"
                except Exception:
                    results[idx] = "Offline/Unreachable"

            for i in range(1, 7):
                t = threading.Thread(target=check_ip, args=(i,))
                threads.append(t)
                t.start()

            for t in threads:
                t.join()

            log_queue.put("=" * 50)
            log_queue.put("🌍 EXTERNAL IP STATUS FOR ALL TUNNELS:")
            log_queue.put("=" * 50)
            for i in sorted(results.keys()):
                log_queue.put(f"  -> VPN {i} (10.8.0.1{i}): {results[i]}")
            log_queue.put("=" * 50)

            if hasattr(self, "vpn_check_ips_btn") and self.vpn_check_ips_btn:
                self.after(
                    0,
                    lambda: self.vpn_check_ips_btn.configure(
                        state="normal", text="Check Tunnels IP"
                    ),
                )

        import threading

        threading.Thread(target=run_check, daemon=True).start()

    def on_vpn_reset_defaults(self):
        """Uninstall all tunnels, clear all custom routes, turn off System VPN, and restore default Windows routing."""
        if not hasattr(self, "vpn_manager") or self.vpn_manager is None:
            log_queue.put("[GUI] [ERROR] VPN Manager library is not loaded.")
            return

        if not self.vpn_manager.is_admin():
            self.vpn_manager.elevate()
            return

        import tkinter.messagebox as messagebox

        if not messagebox.askyesno(
            "Reset to Defaults",
            "This will completely stop and uninstall all 6 VPN tunnels, clear all custom system routes, and restore your default Windows routing table.\n\nAre you sure you want to proceed?",
        ):
            return

        if hasattr(self, "vpn_reset_defaults_btn") and self.vpn_reset_defaults_btn:
            self.vpn_reset_defaults_btn.configure(state="disabled", text="Resetting...")

        log_queue.put(
            "[GUI] [SYSTEM] Reverting all VPN and routing changes to system defaults..."
        )

        def run_reset():
            try:
                # 1. Turn off System VPN toggle in GUI and config
                self.after(0, lambda: self.system_vpn_switch.deselect())
                self.system_vpn_active = False

                try:
                    from proxy_core.config import (
                        load_rotation_config,
                        save_rotation_config,
                    )

                    cfg = load_rotation_config()
                    cfg["system_vpn_active"] = False
                    save_rotation_config(cfg)
                except Exception as ce:
                    logger.error(f"[GUI] Failed to update config on reset: {ce}")

                # 2. Clear system routing
                self.vpn_manager.disable_system_routing(print_cb=log_queue.put)

                # 3. Uninstall all 6 tunnels
                self.vpn_manager.uninstall_all_services(print_cb=log_queue.put)

                log_queue.put(
                    "[GUI] [SYSTEM] System routing and tunnel configurations successfully reset to defaults!"
                )
            except Exception as e:
                logger.error(f"[GUI] Error resetting to defaults: {e}")
                log_queue.put(f"[GUI] [ERROR] Reset failed: {e}")
            finally:
                if (
                    hasattr(self, "vpn_reset_defaults_btn")
                    and self.vpn_reset_defaults_btn
                ):
                    self.after(
                        0,
                        lambda: self.vpn_reset_defaults_btn.configure(
                            state="normal", text="Reset to Defaults"
                        ),
                    )

        import threading

        threading.Thread(target=run_reset, daemon=True).start()

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
                self.vpn_manager.uninstall_all_services(print_cb=log_queue.put)
                self.vpn_manager.disable_system_routing(print_cb=log_queue.put)
                if hasattr(self, "system_vpn_switch") and self.system_vpn_switch:
                    self.after(0, lambda: self.system_vpn_switch.deselect())
                    self.after(
                        0, lambda: self.system_vpn_dropdown.configure(state="normal")
                    )
                self.system_vpn_active = False
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
        """Periodic loop to poll the status of VPN tunnels every 15 seconds."""
        self.do_poll_vpn_status()
        self.after(15000, self.poll_vpn_status_loop)

    def format_size(self, size_bytes):
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        else:
            return f"{size_bytes / (1024 * 1024):.2f} MB"

    def poll_compactor_stats_loop(self):
        """Periodic loop to poll compactor statistics from the server and update UI using a single long-running background thread."""
        if (
            hasattr(self, "_compactor_stats_thread_started")
            and self._compactor_stats_thread_started
        ):
            return
        self._compactor_stats_thread_started = True

        def poll_loop():
            import httpx
            import time

            while True:
                try:
                    url = f"http://{self.host}:{self.port}/control/stats"
                    response = httpx.get(url, timeout=1.0)
                    if response.status_code == 200:
                        data = response.json()
                        self.after(0, lambda d=data: self.update_stats_ui(d))
                except Exception:
                    # Server might be offline or starting
                    pass
                time.sleep(2.0)

        threading.Thread(target=poll_loop, daemon=True).start()

    def open_compactor_settings_window(self):
        """Open a settings window for the context compactor."""
        if (
            self.compactor_settings_win is not None
            and self.compactor_settings_win.winfo_exists()
        ):
            self.compactor_settings_win.focus()
            return

        self.compactor_settings_win = ctk.CTkToplevel(self)
        self.compactor_settings_win.title("Compactor Settings")
        self.compactor_settings_win.geometry("480x450")
        self.compactor_settings_win.resizable(False, False)
        self.compactor_settings_win.attributes("-topmost", True)

        # Main frame
        main_frame = ctk.CTkFrame(self.compactor_settings_win, corner_radius=10)
        main_frame.pack(fill="both", expand=True, padx=15, pady=15)

        # Title
        title_lbl = ctk.CTkLabel(
            main_frame,
            text="Context Compactor Settings",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color="#3498DB",
        )
        title_lbl.pack(pady=(10, 15))

        # Checkboxes frame
        cb_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        cb_frame.pack(fill="both", expand=True, padx=10)

        config = load_rotation_config()

        # Checkboxes for other compactor settings
        self.var_compact_tools = tk.BooleanVar(
            value=config.get("compactor_compact_tools", True)
        )
        self.cb_compact_tools = ctk.CTkCheckBox(
            cb_frame,
            text="Compact Tool Descriptions",
            variable=self.var_compact_tools,
            font=ctk.CTkFont(size=11),
        )
        self.cb_compact_tools.pack(anchor="w", pady=5)

        self.var_compact_superpowers = tk.BooleanVar(
            value=config.get("compactor_compact_superpowers", True)
        )
        self.cb_compact_superpowers = ctk.CTkCheckBox(
            cb_frame,
            text="Compact Superpowers Instructions",
            variable=self.var_compact_superpowers,
            font=ctk.CTkFont(size=11),
        )
        self.cb_compact_superpowers.pack(anchor="w", pady=5)

        self.var_compact_skills = tk.BooleanVar(
            value=config.get("compactor_compact_skills", True)
        )
        self.cb_compact_skills = ctk.CTkCheckBox(
            cb_frame,
            text="Compact Skill Responses",
            variable=self.var_compact_skills,
            font=ctk.CTkFont(size=11),
        )
        self.cb_compact_skills.pack(anchor="w", pady=5)

        self.var_compact_devctx = tk.BooleanVar(
            value=config.get("compactor_compact_devctx", True)
        )
        self.cb_compact_devctx = ctk.CTkCheckBox(
            cb_frame,
            text="Compact Devctx Instructions",
            variable=self.var_compact_devctx,
            font=ctk.CTkFont(size=11),
        )
        self.cb_compact_devctx.pack(anchor="w", pady=5)

        self.var_block_generic_read = tk.BooleanVar(
            value=config.get("compactor_block_generic_read", True)
        )
        self.cb_block_generic_read = ctk.CTkCheckBox(
            cb_frame,
            text="Block Generic Read on Code Files",
            variable=self.var_block_generic_read,
            font=ctk.CTkFont(size=11),
        )
        self.cb_block_generic_read.pack(anchor="w", pady=5)

        self.var_move_reminders = tk.BooleanVar(
            value=config.get("compactor_move_reminders", True)
        )
        self.cb_move_reminders = ctk.CTkCheckBox(
            cb_frame,
            text="Move Reminders to System Instruction",
            variable=self.var_move_reminders,
            font=ctk.CTkFont(size=11),
        )
        self.cb_move_reminders.pack(anchor="w", pady=5)

        self.var_inject_guardrails = tk.BooleanVar(
            value=config.get("compactor_inject_guardrails", True)
        )
        self.cb_inject_guardrails = ctk.CTkCheckBox(
            cb_frame,
            text="Inject Tool Guardrails (Injected: 0 times)",
            variable=self.var_inject_guardrails,
            font=ctk.CTkFont(size=11),
        )
        self.cb_inject_guardrails.pack(anchor="w", pady=5)

        self.var_enable_headroom = tk.BooleanVar(
            value=config.get("compactor_enable_headroom", True)
        )
        self.cb_enable_headroom = ctk.CTkCheckBox(
            cb_frame,
            text="Enable Headroom Context Compression",
            variable=self.var_enable_headroom,
            font=ctk.CTkFont(size=11),
        )
        self.cb_enable_headroom.pack(anchor="w", pady=5)

        # Save settings callback
        def save_settings():
            try:
                cfg = load_rotation_config()
                cfg["compactor_compact_tools"] = self.var_compact_tools.get()
                cfg["compactor_compact_superpowers"] = (
                    self.var_compact_superpowers.get()
                )
                cfg["compactor_compact_skills"] = self.var_compact_skills.get()
                cfg["compactor_compact_devctx"] = self.var_compact_devctx.get()
                cfg["compactor_block_generic_read"] = self.var_block_generic_read.get()
                cfg["compactor_move_reminders"] = self.var_move_reminders.get()
                cfg["compactor_inject_guardrails"] = self.var_inject_guardrails.get()
                cfg["compactor_enable_headroom"] = self.var_enable_headroom.get()
                save_rotation_config(cfg)
                logger.info("[GUI] Compactor settings saved successfully.")
                log_queue.put("[GUI] Compactor settings saved successfully.")
                self.compactor_settings_win.destroy()
            except Exception as e:
                logger.error(f"[GUI] Failed to save compactor settings: {e}")
                log_queue.put(f"[GUI] [ERROR] Failed to save compactor settings: {e}")

        # Save button
        save_btn = ctk.CTkButton(
            main_frame,
            text="Save & Close",
            fg_color="#27AE60",
            hover_color="#2ECC71",
            command=save_settings,
        )
        save_btn.pack(pady=(15, 10))

    def update_stats_ui(self, data):
        """Update the compactor statistics labels and settings window in real-time."""
        orig = data.get("compactor_orig_bytes", 0)
        comp = data.get("compactor_comp_bytes", 0)
        saved = orig - comp
        pct = (saved / orig) * 100 if orig > 0 else 0.0

        self.stats_label.configure(
            text=f"Saved: {self.format_size(saved)} (-{pct:.1f}%)"
        )

        # Update the injections count label if the settings window is open
        if (
            self.compactor_settings_win is not None
            and self.compactor_settings_win.winfo_exists()
            and hasattr(self, "cb_inject_guardrails")
        ):
            injections_count = data.get("compactor_injections_count", 0)
            self.cb_inject_guardrails.configure(
                text=f"Inject Tool Guardrails (Injected: {injections_count} times)"
            )

    def do_poll_vpn_status(self):
        """Run parallel ping checks for active VPN channels to measure latency and service state."""
        if not hasattr(self, "vpn_manager") or self.vpn_manager is None:
            return

        def run_check():
            try:
                import httpx
                import threading
                import subprocess

                # Check service status using PowerShell command
                running_channels = set()
                try:
                    result = subprocess.run(
                        [
                            "powershell",
                            "-Command",
                            "Get-Service -Name WireGuardTunnel$* | Select-Object -Property Name, Status",
                        ],
                        capture_output=True,
                        text=True,
                        errors="replace",
                        timeout=5.0,
                    )
                    if result.returncode == 0 and result.stdout:
                        for line in result.stdout.splitlines():
                            if "Running" in line:
                                for idx in range(1, 7):
                                    if f"WireGuardTunnel$vpn{idx}" in line:
                                        running_channels.add(idx)
                except Exception as se:
                    logger.debug(f"[VPN Service Check Error] {se}")
                    # If check fails, assume all are running to fall back to ping checks
                    running_channels = set(range(1, 7))

                results = {}
                threads = []

                def ping_channel(channel):
                    if channel not in running_channels:
                        results[channel] = {"status": "off", "latency": None}
                        return

                    # If system VPN is active, only ping the selected channel and skip others
                    if getattr(self, "system_vpn_active", False):
                        try:
                            selected_val = self.system_vpn_dropdown.get()
                            sys_vpn_idx = int(selected_val.split()[-1])
                        except Exception:
                            sys_vpn_idx = 1
                        if channel != sys_vpn_idx:
                            results[channel] = {"status": "running", "latency": None}
                            return

                    local_ip = f"10.8.0.1{channel}"
                    url = "https://api.ipify.org"
                    try:
                        transport = httpx.HTTPTransport(local_address=local_ip)
                        with httpx.Client(transport=transport, timeout=2.0) as client:
                            start = time.perf_counter()
                            resp = client.get(url)
                            latency_ms = int((time.perf_counter() - start) * 1000)
                            results[channel] = {
                                "status": "running",
                                "latency": latency_ms,
                            }
                    except Exception:
                        results[channel] = {"status": "offline", "latency": None}

                # Start threads for all 6 channels
                for i in range(1, 7):
                    t = threading.Thread(target=ping_channel, args=(i,), daemon=True)
                    threads.append(t)
                    t.start()

                # Wait for all threads
                for t in threads:
                    t.join()

                # Update UI on main thread
                def update_ui():
                    if (
                        not hasattr(self, "channel_indicators")
                        or not self.channel_indicators
                    ):
                        return
                    for i in range(1, 7):
                        data = results.get(i, {"status": "off", "latency": None})
                        status = data["status"]
                        if status == "off":
                            self.channel_indicators[i].configure(
                                text="● Off", text_color="#7F8C8D"
                            )
                            self.sidebar_vpn_lamps[i].configure(
                                text="●", text_color="#7F8C8D"
                            )
                            CTkToolTip(self.sidebar_vpn_lamps[i], f"VPN {i}: Off")
                        elif status == "offline":
                            self.channel_indicators[i].configure(
                                text="● Offline", text_color="#E74C3C"
                            )
                            self.sidebar_vpn_lamps[i].configure(
                                text="●", text_color="#E74C3C"
                            )
                            CTkToolTip(self.sidebar_vpn_lamps[i], f"VPN {i}: Offline")
                        else:
                            self.channel_indicators[i].configure(
                                text=f"● {data['latency']}ms", text_color="#2ECC71"
                            )
                            self.sidebar_vpn_lamps[i].configure(
                                text="●", text_color="#2ECC71"
                            )
                            CTkToolTip(
                                self.sidebar_vpn_lamps[i],
                                f"VPN {i}: {data['latency']}ms",
                            )

                self.after(0, update_ui)
            except Exception as e:
                logger.debug(f"[VPN Status Check Error] {e}")

        threading.Thread(target=run_check, daemon=True).start()

    def on_system_vpn_toggle(self):
        """Handle toggling of system-wide VPN routing."""
        if not hasattr(self, "vpn_manager") or self.vpn_manager is None:
            log_queue.put("[GUI] [ERROR] VPN Manager library is not loaded.")
            self.system_vpn_switch.deselect()
            return

        # Check admin privileges
        if not self.vpn_manager.is_admin():
            log_queue.put(
                "[GUI] [SYSTEM] WireGuard requires Administrator privileges. Requesting UAC elevation..."
            )
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
                    log_queue.put(
                        f"[GUI] [SYSTEM] Enabling System VPN routing via VPN {idx}..."
                    )

                    # Ensure service is running
                    from proxy_core.rotation import wait_for_adapter_and_add_route

                    # Check if service is active
                    output, _ = self.vpn_manager.run_ps_cmd(
                        f'Get-Service -Name "WireGuardTunnel$vpn{idx}" | Where-Object {{$_.Status -eq "Running"}}'
                    )
                    if not output:
                        log_queue.put(
                            f"[GUI] [SYSTEM] Service vpn{idx} is offline. Starting service..."
                        )
                        conf_path = os.path.join(
                            self.vpn_manager.configs_dir, f"vpn{idx}.conf"
                        )
                        if os.path.exists(conf_path):
                            subprocess.run(
                                [
                                    self.vpn_manager.wg_path,
                                    "/installtunnelservice",
                                    conf_path,
                                ],
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL,
                            )
                            # Set startup to Manual
                            subprocess.run(
                                [
                                    "powershell",
                                    "-Command",
                                    f"Set-Service -Name 'WireGuardTunnel$vpn{idx}' -StartupType Manual",
                                ],
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL,
                            )
                            success = wait_for_adapter_and_add_route(idx, timeout=60.0)
                            if not success:
                                log_queue.put(
                                    f"[GUI] [ERROR] Failed to start VPN {idx} service or configure adapter."
                                )
                                self.after(0, lambda: self.system_vpn_switch.deselect())
                                return
                            # Let the adapter stabilize in the kernel to prevent race conditions and BSODs
                            import time

                            time.sleep(2.0)
                        else:
                            log_queue.put(
                                f"[GUI] [ERROR] Config not found for vpn{idx}"
                            )
                            self.after(0, lambda: self.system_vpn_switch.deselect())
                            return

                    # Enable system-wide routing
                    self.vpn_manager.enable_system_routing_via(
                        idx, print_cb=log_queue.put
                    )
                    self.system_vpn_active = True
                    # Update config
                    from proxy_core.config import (
                        load_rotation_config,
                        save_rotation_config,
                    )

                    config = load_rotation_config()
                    config["system_vpn_active"] = True
                    config["system_vpn_index"] = idx
                    save_rotation_config(config)
                else:
                    log_queue.put("[GUI] [SYSTEM] Disabling System VPN routing...")
                    self.vpn_manager.disable_system_routing(print_cb=log_queue.put)
                    self.system_vpn_active = False
                    # Update config
                    from proxy_core.config import (
                        load_rotation_config,
                        save_rotation_config,
                    )

                    config = load_rotation_config()
                    config["system_vpn_active"] = False
                    save_rotation_config(config)
            except Exception as e:
                logger.error(f"[GUI] Error toggling system VPN: {e}")
                log_queue.put(f"[GUI] [ERROR] Failed to toggle system VPN: {e}")
                if is_on:
                    self.after(0, lambda: self.system_vpn_switch.deselect())
            finally:
                self.after(0, lambda: self.system_vpn_switch.configure(state="normal"))
                if not self.system_vpn_active:
                    self.after(
                        0, lambda: self.system_vpn_dropdown.configure(state="normal")
                    )

        import threading

        threading.Thread(target=run_toggle, daemon=True).start()

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
            threshold_val = int(self.threshold_entry.get().strip())
            if threshold_val < 1:
                threshold_val = 1
        except ValueError:
            threshold_val = 5

        config["vpn_errors_threshold"] = threshold_val
        save_rotation_config(config)
        logger.info(f"[GUI] Saved VPN errors threshold: {threshold_val}")
