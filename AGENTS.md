<!-- devctx:start -->
## devctx

**First time in project?** Run build_index(incremental=true) to enable search/context quality.

Prefer devctx MCP for non-trivial tasks:
- smart_turn(start, userPrompt, ensureSession=true) before multi-step work
- smart_context(...) or smart_search(intent=...) to build context cheaply
- smart_read(outline|signatures|symbol) before full reads
- smart_shell instead of Shell for safe diagnostics
- smart_turn(end, event=milestone) after meaningful progress

Tool substitution rules (use devctx INSTEAD of native tools):
- smart_search OVER Grep/SemanticSearch for any codebase exploration or "how does X work" queries
- smart_read/smart_read_batch OVER Read when reading multiple files or large files (>200 lines) for context
- smart_shell OVER Shell for build/test/lint/git checks
- smart_turn(end, event=milestone) after EVERY significant code change, not just at session end

If devctx MCP is installed and enabled, default to devctx on every non-trivial multi-file or multi-step task. Skip it only for genuinely trivial work, and then state why it was skipped.

Client contract:
- Treat smart_turn as the task entry point for non-trivial work.
- If smart_turn returns mutationSafety.blocked = true, stop write-heavy work, surface blockedBy, and follow recommendedActions before retrying persisted steps.
- If smart_turn or smart_doctor reports storageHealth.issue !== "ok", pause persisted context writes and remediate local state before continuing.
- Use smart_doctor when repo safety or SQLite health is unhealthy or unclear.
- Use workflow, continuity, recommendedPath, mutationSafety, and storageHealth as the current operational state for the task.

Cursor assisted mode:
- For long or continuity-sensitive tasks, prefer the local launcher `./.devctx/bin/cursor-devctx`
- Usage: `./.devctx/bin/cursor-devctx task --prompt "your task" -- <agent-command> [args...]`
- Specialized flows: `review`, `debug`, `refactor`, `test`, `doctor`, `status`, `checkpoint`, `cleanup`
- This launcher wraps the prompt with smart_turn(start/end) orchestration and the shared operational contract

Reading cascade: outline → signatures → symbol → full (last resort)

Detailed workflows: .cursor/rules/profiles-compact/ (debugging, code-review, refactoring, testing, architecture)

---

If you didn't use devctx tools in a non-trivial programming task, add at the end:

**Note:** devctx not used because: [task too simple | MCP unavailable | index not built | already had sufficient context | native tool more direct for this case]. To use devctx next time: "Use smart-context-mcp: smart_turn(start, userPrompt, ensureSession=true) → smart_context/smart_search → smart_read → smart_turn(end, event=milestone)"
<!-- devctx:end -->

## 🇷🇺 Russian Windows Encoding Guardrail
* **System Environment:** The user's system runs Windows with Russian language settings (default console encodings: CP1251 / CP866).
* **Encoding Rule:** When executing PowerShell or cmd commands via `bash`, `smart-context_smart_shell`, or other shell tools, ALWAYS force transcoding of the output to UTF-8 (e.g., by prepending `[Console]::OutputEncoding = [System.Text.Encoding]::UTF8;` or similar commands in PowerShell) and decode using `utf-8` with fallback to avoid encoding errors or mangled Cyrillic characters.
