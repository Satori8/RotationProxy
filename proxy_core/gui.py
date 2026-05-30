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
            "qwen/qwen-2.5-72b-instruct:free",
            "meta-llama/llama-3.3-70b-instruct:free",
            "deepseek/deepseek-chat:free",
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

        self.log_textbox = ctk.CTkTextbox(
            self.right_panel,
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
            self.right_panel, text="Clear Logs", command=self.on_clear_logs, width=120
        )
        self.clear_btn.grid(row=1, column=0, pady=10)

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
        self.destroy()
