# GUI Timeout Settings and Tooltips Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Connect Timeout and Read Timeout entry fields to the Settings tab in the GUI, implement a custom hover tooltip class, and bind tooltips to the new settings. Ensure these timeouts are loaded from and saved to `config_rotation.json` and dynamically applied by the proxy server.

**Architecture:**
- Create a lightweight `CTkToolTip` class in `proxy_core/gui.py` using standard `tkinter.Toplevel` to render hover tooltips.
- Add `connect_timeout` and `read_timeout` to the schema upgrade logic in `proxy_core/config.py`.
- Render Connect Timeout and Read Timeout fields in the second column (`column=1`) of the Settings tab grid in `proxy_core/gui.py`.
- Bind tooltips to the labels and entries of the new timeout settings.
- Update `proxy_core/server.py` to dynamically load `connect_timeout` and `read_timeout` from the rotation config on startup.

**Tech Stack:** Python, CustomTkinter, Tkinter, FastAPI, HTTPX

---

### Task 1: Upgrade Configuration Schema in `proxy_core/config.py`

**Files:**
- Modify: `proxy_core/config.py:140-175`

- [ ] **Step 1: Add connect_timeout and read_timeout to config schema**
  Update `load_rotation_config` in `proxy_core/config.py` to ensure `connect_timeout` (default: 15.0) and `read_timeout` (default: 120.0) are present in the config and upgraded if missing. Also add them to the default fallback dictionary.

  *Code change preview:*
  ```python
            if "max_exponential_sleep" not in config:
                config["max_exponential_sleep"] = 65.0
                needs_upgrade = True
            if "connect_timeout" not in config:
                config["connect_timeout"] = 15.0
                needs_upgrade = True
            if "read_timeout" not in config:
                config["read_timeout"] = 120.0
                needs_upgrade = True

            if needs_upgrade:
                save_rotation_config(config)
  ```
  And in the fallback dict at the end of the file:
  ```python
        "vpn_disabled_pause_sleep": 65.0,
        "max_exponential_sleep": 65.0,
        "connect_timeout": 15.0,
        "read_timeout": 120.0,
    }
  ```

- [ ] **Step 2: Verify compilation**
  Run: `python -m py_compile proxy_core/config.py`
  Expected: Success with no errors.

---

### Task 2: Dynamically Load Timeouts in `proxy_core/server.py`

**Files:**
- Modify: `proxy_core/server.py:597-620`

- [ ] **Step 1: Load timeouts from config in lifespan**
  Modify the `lifespan` function in `proxy_core/server.py` to load `connect_timeout` and `read_timeout` from the rotation config instead of using hardcoded values.

  *Code change preview:*
  ```python
  @asynccontextmanager
  async def lifespan(app: FastAPI):
      rotation_config = load_rotation_config()
      connect_timeout = float(rotation_config.get("connect_timeout", 15.0))
      read_timeout = float(rotation_config.get("read_timeout", 120.0))

      limits = httpx.Limits(
          max_keepalive_connections=100,
          max_connections=200,
          keepalive_expiry=30.0,  # Close idle connections after 30s to prevent stale sockets
      )
      timeout = httpx.Timeout(
          connect=connect_timeout,
          read=read_timeout,
          write=15.0,
          pool=15.0,
      )

      # Initialize 7 clients: index 0 (unbound) + indexes 1-6 (bound to corresponding VPN local IPs)
      app.state.vpn_clients = {0: httpx.AsyncClient(timeout=timeout, limits=limits)}
  ```

- [ ] **Step 2: Verify compilation**
  Run: `python -m py_compile proxy_core/server.py`
  Expected: Success with no errors.

---

### Task 3: Implement Tooltips and Settings UI in `proxy_core/gui.py`

**Files:**
- Modify: `proxy_core/gui.py`

- [ ] **Step 1: Import tkinter and define CTkToolTip**
  Import `tkinter as tk` at the top of `proxy_core/gui.py` and define the `CTkToolTip` class right above `ProxyGUI`.

  *Code change preview:*
  ```python
  import tkinter as tk
  import customtkinter as ctk
  ```

  ```python
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
              font=("Helvetica", "10", "normal"),
              padx=5,
              pady=5,
          )
          label.pack(ipadx=1)

      def hide_tooltip(self, event=None):
          tw = self.tooltip_window
          self.tooltip_window = None
          if tw:
              tw.destroy()
  ```

- [ ] **Step 2: Add Connect and Read Timeout fields in `load_settings_ui`**
  Modify `load_settings_ui` in `proxy_core/gui.py` to render the new timeout fields in column 1 of the grid, and bind tooltips to them.

  *Code change preview:*
  ```python
          # Connect Timeout (Column 1)
          connect_label = ctk.CTkLabel(
              settings_frame,
              text="Connect Timeout (seconds):",
              font=ctk.CTkFont(size=12, weight="bold"),
          )
          connect_label.grid(row=0, column=1, padx=10, pady=(10, 2), sticky="w")
          self.connect_timeout_entry = ctk.CTkEntry(settings_frame)
          self.connect_timeout_entry.insert(0, str(config.get("connect_timeout", 15.0)))
          self.connect_timeout_entry.grid(row=1, column=1, padx=10, pady=(0, 10), sticky="ew")

          CTkToolTip(
              connect_label,
              "Тайм-аут установки TCP-соединения с сервером.\nРекомендуется: 10-15 сек."
          )
          CTkToolTip(
              self.connect_timeout_entry,
              "Тайм-аут установки TCP-соединения с сервером.\nРекомендуется: 10-15 сек."
          )

          # Read Timeout (Column 1)
          read_label = ctk.CTkLabel(
              settings_frame,
              text="Read Timeout (seconds):",
              font=ctk.CTkFont(size=12, weight="bold"),
          )
          read_label.grid(row=2, column=1, padx=10, pady=(10, 2), sticky="w")
          self.read_timeout_entry = ctk.CTkEntry(settings_frame)
          self.read_timeout_entry.insert(0, str(config.get("read_timeout", 120.0)))
          self.read_timeout_entry.grid(row=3, column=1, padx=10, pady=(0, 10), sticky="ew")

          CTkToolTip(
              read_label,
              "Тайм-аут ожидания ответа/чанка от модели.\nУвеличьте для медленных моделей с большим контекстом.\nРекомендуется: 60-180 сек."
          )
          CTkToolTip(
              self.read_timeout_entry,
              "Тайм-аут ожидания ответа/чанка от модели.\nУвеличьте для медленных моделей с большим контекстом.\nРекомендуется: 60-180 сек."
          )
  ```

- [ ] **Step 3: Update `on_save_settings` to save new timeouts**
  Modify `on_save_settings` in `proxy_core/gui.py` to read values from the new entries and save them to the config.

  *Code change preview:*
  ```python
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
  ```

- [ ] **Step 4: Verify compilation**
  Run: `python -m py_compile proxy_core/gui.py`
  Expected: Success with no errors.
