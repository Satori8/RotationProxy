# Expand Tool Guardrails Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Update the `inject_tool_guardrails` function in `proxy_core/compactor.py` to expand the guardrails and bad instruction replacements to cover all non-optimal tools (such as generic grep, glob, and shell) as defined in `tool_guardrails.md`.

**Architecture:**
- Update the `guardrail_block` string in `inject_tool_guardrails` to explicitly cover search, file finding, and shell tools.
- Update the `clean_bad_instructions` helper function in `inject_tool_guardrails` to replace "use grep/glob/read directly" with "use smart-context_smart_search, token-savior_search_codebase, or fff_find_files directly".

**Tech Stack:** Python

---

### Task 1: Update `inject_tool_guardrails` in `proxy_core/compactor.py`

**Files:**
- Modify: `proxy_core/compactor.py`

- [ ] **Step 1: Save AST checkpoint before editing**

  Save AST checkpoint of `proxy_core/compactor.py` using `cortexast_cortex_chronos`.

- [ ] **Step 2: Update `guardrail_block` and `clean_bad_instructions`**

  Modify `proxy_core/compactor.py` to update `guardrail_block` and `clean_bad_instructions` inside `inject_tool_guardrails`.

  **Original Code:**
  ```python
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
              flags=re.IGNORECASE,
          )
          # Replace "Read files before using edit/write tools"
          text = re.sub(
              r"Read files before using edit/write tools",
              "Read files using smart-context_smart_read before using edit/token-savior tools",
              text,
              flags=re.IGNORECASE,
          )
          return text
  ```

  **New Code:**
  ```python
      guardrail_block = """

[CRITICAL TOOL GUARDRAIL:
1. You are STRICTLY FORBIDDEN from using the generic 'read' or 'write' tools for any code files (Python, TS, JS, Go, Rust, C++, C#, etc.).
2. For reading code files, you MUST use 'smart-context_smart_read' (mode='outline'/'signatures'/'symbol') or 'token-savior_get_function_source'.
3. For modifying code files, you MUST use 'token-savior_replace_symbol_source' or 'edit'.
4. For searching code or text, you MUST use 'smart-context_smart_search' or 'token-savior_search_codebase' instead of generic 'grep' or 'search'.
5. For finding files by name, you MUST use 'fff_find_files' or 'cortexast_cortex_code_explorer' instead of generic 'glob' or 'find'.
6. For running build, test, lint, or git checks, you MUST use 'smart-context_smart_shell' instead of generic 'shell'.
7. Direct 'read', 'write', 'grep', 'glob', and 'shell' tools are restricted and should be avoided in favor of optimized tools.]"""

      # Helper to clean up bad instructions in Fixer/Refactorer prompts
      def clean_bad_instructions(text: str) -> str:
          if not isinstance(text, str):
              return text
          # Replace "use grep/glob/read directly"
          text = re.sub(
              r"use grep/glob/read directly",
              "use smart-context_smart_search, token-savior_search_codebase, or fff_find_files directly",
              text,
              flags=re.IGNORECASE,
          )
          # Replace "Read files before using edit/write tools"
          text = re.sub(
              r"Read files before using edit/write tools",
              "Read files using smart-context_smart_read before using edit/token-savior tools",
              text,
              flags=re.IGNORECASE,
          )
          return text
  ```

- [ ] **Step 3: Compare AST checkpoint after editing**

  Compare AST checkpoint of `proxy_core/compactor.py` using `cortexast_cortex_chronos` to verify only the intended changes were made.

- [ ] **Step 4: Run python compilation check**

  Run `python -m py_compile proxy_core/compactor.py` to verify that the code compiles successfully.
