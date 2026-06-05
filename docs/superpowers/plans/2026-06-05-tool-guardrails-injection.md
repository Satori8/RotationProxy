# Tool Guardrails Injection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the Tool Guardrails Injection feature across the codebase to surgically modify system prompts in incoming requests, replacing bad instructions and appending strict tool guardrails to force the use of optimized tools.

**Architecture:** 
- Add `inject_tool_guardrails` function in `proxy_core/compactor.py` and call it in `process_request_payload` when `compactor_inject_guardrails` is enabled.
- Expose `compactor_injections_count` in the `/control/stats` endpoint in `proxy_core/server.py`.
- Add a checkbox for `compactor_inject_guardrails` in the Compactor Settings window in `proxy_core/gui.py`, and update its label with the injections count in real-time.

**Tech Stack:** Python, FastAPI, CustomTkinter

---

### Task 1: Implement `inject_tool_guardrails` in `proxy_core/compactor.py`

**Files:**
- Modify: `proxy_core/compactor.py`

- [ ] **Step 1: Save AST checkpoint before editing**
  Save AST checkpoint of `proxy_core/compactor.py` using `cortexast_cortex_chronos`.

- [ ] **Step 2: Add `inject_tool_guardrails` function and call it in `process_request_payload`**
  Add the function right above `process_request_payload` and call it at the end of `process_request_payload` (right before `return payload_dict`).

  ```python
  def inject_tool_guardrails(data):
      """
      Surgically modifies the system prompt (systemInstruction or system message) 
      to replace instructions that encourage using generic read/write on code,
      and appends a strict tool guardrail block to enforce optimized tools.
      """
      import re
      from proxy_core import state

      guardrail_block = """

[CRITICAL TOOL GUARDRAIL:
1. You are STRICTLY FORBIDDEN from using the generic 'read' or 'write' tools for any code files (Python, TS, JS, Go, Rust, C++, C#, etc.).
2. For reading code files, you MUST use 'smart-context_smart_read' (mode='outline'/'signatures'/'symbol') or 'token-savior_get_function_source'.
3. For modifying code files, you MUST use 'token-savior_replace_symbol_source' or 'edit'.
4. Direct 'read' and 'write' tools are restricted and will fail if used on code files. Always prefer optimized tools.]"""

      # Helper to clean up bad instructions in Fixer/Refactorer prompts
      def clean_bad_instructions(text: str) -> str:
          if not isinstance(text, str):
              return text
          # Replace "use grep/glob/read directly"
          text = re.sub(
              r"use grep/glob/read directly",
              "use smart-context_smart_read and token-savior tools directly",
              text,
              flags=re.IGNORECASE
          )
          # Replace "Read files before using edit/write tools"
          text = re.sub(
              r"Read files before using edit/write tools",
              "Read files using smart-context_smart_read before using edit/token-savior tools",
              text,
              flags=re.IGNORECASE
          )
          return text

      injected = False

      # --- Gemini Format ---
      if "systemInstruction" in data:
          sys_inst = data["systemInstruction"]
          if "parts" in sys_inst:
              for part in sys_inst["parts"]:
                  if "text" in part and isinstance(part["text"], str):
                      text = part["text"]
                      text = clean_bad_instructions(text)
                      if "CRITICAL TOOL GUARDRAIL" not in text:
                          text += guardrail_block
                          injected = True
                      part["text"] = text
                      logger.debug("[Compactor] Injected tool guardrails into Gemini systemInstruction")

      # --- OpenAI Format ---
      # 1. Top-level system field
      if "system" in data and isinstance(data["system"], str):
          text = data["system"]
          text = clean_bad_instructions(text)
          if "CRITICAL TOOL GUARDRAIL" not in text:
              text += guardrail_block
              injected = True
          data["system"] = text
          logger.debug("[Compactor] Injected tool guardrails into top-level system field")

      # 2. System message in messages array
      if "messages" in data:
          for msg in data["messages"]:
              if msg.get("role") == "system" and "content" in msg and isinstance(msg["content"], str):
                  text = msg["content"]
                  text = clean_bad_instructions(text)
                  if "CRITICAL TOOL GUARDRAIL" not in text:
                      text += guardrail_block
                      injected = True
                  msg["content"] = text
                  logger.debug("[Compactor] Injected tool guardrails into OpenAI system message")

      if injected:
          state.COMPACTOR_INJECTIONS_COUNT = getattr(state, "COMPACTOR_INJECTIONS_COUNT", 0) + 1

      return data
  ```

  And call it at the end of `process_request_payload`:
  ```python
      # 7. Inject Tool Guardrails to force optimized tools
      if config.get("compactor_inject_guardrails", True):
          payload_dict = inject_tool_guardrails(payload_dict)
  ```

- [ ] **Step 3: Compare AST checkpoint after editing**
  Compare AST checkpoint of `proxy_core/compactor.py` using `cortexast_cortex_chronos` to verify only the intended changes were made.

---

### Task 2: Expose `compactor_injections_count` in `proxy_core/server.py`

**Files:**
- Modify: `proxy_core/server.py`

- [ ] **Step 1: Save AST checkpoint before editing**
  Save AST checkpoint of `proxy_core/server.py` using `cortexast_cortex_chronos`.

- [ ] **Step 2: Expose `compactor_injections_count` in `/control/stats` endpoint**
  Update the `/control/stats` endpoint to return `"compactor_injections_count": getattr(state, "COMPACTOR_INJECTIONS_COUNT", 0)`.

- [ ] **Step 3: Compare AST checkpoint after editing**
  Compare AST checkpoint of `proxy_core/server.py` using `cortexast_cortex_chronos` to verify only the intended changes were made.

---

### Task 3: Add Checkbox and Update Label in `proxy_core/gui.py`

**Files:**
- Modify: `proxy_core/gui.py`

- [ ] **Step 1: Save AST checkpoint before editing**
  Save AST checkpoint of `proxy_core/gui.py` using `cortexast_cortex_chronos`.

- [ ] **Step 2: Increase window geometry height slightly to `"480x420"`**
  In `open_compactor_settings_window`, increase the window geometry height slightly to `"480x420"` to fit the new checkbox.

- [ ] **Step 3: Add the checkbox inside `open_compactor_settings_window`**
  ```python
          self.var_inject_guardrails = tk.BooleanVar(value=config.get("compactor_inject_guardrails", True))
          self.cb_inject_guardrails = ctk.CTkCheckBox(
              cb_frame,
              text="Inject Tool Guardrails (Injected: 0 times)",
              variable=self.var_inject_guardrails,
              font=ctk.CTkFont(size=11),
          )
          self.cb_inject_guardrails.pack(anchor="w", pady=5)
  ```

- [ ] **Step 4: Save its value in the `save_settings` callback**
  ```python
              cfg["compactor_inject_guardrails"] = self.var_inject_guardrails.get()
  ```

- [ ] **Step 5: Update the label with the injections count in `update_stats_ui`**
  ```python
                  injections_count = data.get("compactor_injections_count", 0)
                  self.cb_inject_guardrails.configure(text=f"Inject Tool Guardrails (Injected: {injections_count} times)")
  ```

- [ ] **Step 6: Compare AST checkpoint after editing**
  Compare AST checkpoint of `proxy_core/gui.py` using `cortexast_cortex_chronos` to verify only the intended changes were made.

---

### Task 4: Verification and Diagnostics

- [ ] **Step 1: Run compile-time diagnostics**
  Run `cortexast_run_diagnostics` to verify that the code compiles successfully and has no syntax or type errors.
