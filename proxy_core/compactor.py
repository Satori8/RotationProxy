import re
import os
import logging

logger = logging.getLogger("proxy")

# Code and structured file extensions that are banned for the generic 'read' tool
CODE_EXTENSIONS = {
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".rs",
    ".go",
    ".cpp",
    ".h",
    ".hpp",
    ".cs",
    ".java",
    ".php",
    ".rb",
    ".swift",
    ".kt",
    ".scala",
    ".m",
    ".h",
    ".html",
    ".css",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".xml",
    ".jsonc",
}

# --- Static compaction map for tools ---
COMPACTED_TOOLS = {
    "bash": {
        "description": "Executes a given PowerShell (7+) command with optional timeout. Be aware: OS: win32, Shell: pwsh. AVOID changing directories inside the command - use workdir instead. IMPORTANT: This tool is for terminal operations like git, npm, docker, etc. DO NOT use it for file operations (reading, writing, editing, searching, finding files) - use the specialized tools for this instead.",
        "properties": {
            "description": "Clear, concise description of what this command does in 5-10 words."
        },
    },
    "todowrite": {
        "description": "Create and maintain a structured task list for the current coding session. Tracks progress, organizes multi-step work, and surfaces status to the user. Keep exactly one in_progress while work remains. Mark completed only after the required work is actually done, including any required verification."
    },
    "task": {
        "description": "Launch a new agent to handle complex, multistep tasks autonomously. Specify a subagent_type parameter to select which agent type to use. Launch multiple agents concurrently whenever possible to maximize performance. Clearly tell the agent whether you expect it to write code or just to do research."
    },
    "edit": {
        "description": "Performs exact string replacements in files. You must use your Read tool at least once in the conversation before editing. Ensure you preserve the exact indentation (tabs/spaces) as it appears AFTER the line number prefix (e.g., '1: '). ALWAYS prefer editing existing files in the codebase. NEVER write new files unless explicitly required. The edit will FAIL if oldString is not found or found multiple times."
    },
    "cortexast_cortex_chronos": {
        "description": "⏳ CHRONOS SNAPSHOT MEGATOOL — Saves named structural AST snapshots of individual symbols under human-readable semantic tags, then compares them at the AST level — ignoring all formatting noise. Mandatory workflow for safe AI-driven code changes: save_checkpoint BEFORE any non-trivial edit, compare_checkpoint AFTER editing to structurally verify that only the intended changes were made.",
        "properties": {
            "action": "Selects the Chronos operation: save_checkpoint (Saves AST snapshot before edit), list_checkpoints (Lists saved snapshots), compare_checkpoint (Compares two snapshots, returns AST-level semantic diff), delete_checkpoint (Deletes snapshots)."
        },
    },
    "smart-context_smart_read": {
        "description": "Read a file with token-efficient modes. ALWAYS prefer outline/signatures/symbol/explain over full. Reading cascade: outline (file structure) → signatures (function signatures) → symbol (specific functions/classes) → explain (compact summary) → range (specific line range) → full (raw content, last resort for config/lock files)."
    },
    "smart-context_smart_turn": {
        "description": "Orchestrate start/end of a meaningful agent turn for multi-session tasks where context continuity matters. phase: 'start' rehydrates persisted context and returns recommendedPath guidance. phase: 'end' writes a checkpoint through smart_summary and can include compact metrics."
    },
    "smart-context_smart_summary": {
        "description": "Maintain compressed conversation state across turns. Actions: get (retrieve current/last session), update (create or replace a session), append (add to existing session), auto_append (append only if something meaningful changed), checkpoint (event-driven orchestration), reset (clear session), list_sessions (show all sessions), compact (apply retention/compaction), cleanup_legacy (remove legacy files)."
    },
    "smart-context_smart_context": {
        "description": "PREFERRED for multi-file tasks. Gets curated context in one call by combining search + graph expansion + selective reading. Primary files always include content (signatures) in balanced mode — reduces follow-up smart_read calls."
    },
    "skill": {
        "description": "Load a specialized skill when the task at hand matches one of the skills listed in the system prompt. The skill name must match one of the available skills (brainstorming, codemap, dispatching-parallel-agents, executing-plans, subagent-driven-development, using-git-worktrees, using-superpowers, writing-plans)."
    },
    "ast_grep_search": {
        "description": "Search code patterns across filesystem using AST-aware matching. Supports 25 languages. Use meta-variables: $VAR (single node), $$$ (multiple nodes). IMPORTANT: Patterns must be complete AST nodes (valid code with params and body)."
    },
    "ast_grep_replace": {
        "description": "Replace code patterns across filesystem with AST-aware rewriting. Dry-run by default. Use meta-variables in rewrite to preserve matched content."
    },
    "fff_find_files": {
        "description": "Fuzzy file search by name. Searches FILE NAMES, not file contents. Supports fuzzy matching, path prefixes, and glob constraints. IMPORTANT: Keep queries SHORT (1-2 terms max)."
    },
    "fff_grep": {
        "description": "Search file contents for bare identifiers (not code syntax or regex). Filter files with constraints (e.g. '*.rs query')."
    },
    "fff_multi_grep": {
        "description": "Search file contents for lines matching ANY of multiple patterns (OR logic). Patterns are literal text (do not escape special characters)."
    },
    "google_search": {
        "description": "Search the web using Google Search and analyze URLs. IMPORTANT: Extract any URLs mentioned in the query and pass them in the 'urls' parameter for direct analysis."
    },
    "webfetch": {
        "description": "Fetch a URL with content-focused HTML extraction, metadata, redirects, and optional prompt processing."
    },
    "sequential-thinking_sequentialthinking": {
        "description": "A detailed tool for dynamic and reflective problem-solving through thoughts. This tool helps analyze problems through a flexible thinking process that can adapt and evolve. Each thought can build on, question, or revise previous insights as understanding deepens."
    },
    "question": {
        "description": "Use this tool when you need to ask the user questions during execution to gather preferences, clarify ambiguous instructions, or get decisions."
    },
    "read": {
        "description": "Read a file or directory from the local filesystem. BANNED: Do NOT use this tool for code files (Python, TS, JS, Go, Rust, C++, C#). For code files, you MUST use 'smart-context_smart_read' (mode='outline'/'signatures') or 'token-savior' tools. Use this tool ONLY for non-code files (logs, configs, lockfiles, markdown)."
    },
    "write": {
        "description": "Writes a file to the local filesystem. BANNED: Do NOT use this tool to edit existing code files. For modifying code, you MUST use 'token-savior_replace_symbol_source' or delegate to a specialist agent. Use this tool ONLY for writing new non-code files (configs, markdown, logs) when explicitly required."
    },
    "grep": {
        "description": "Fast content search tool. BANNED: Do NOT use this tool for searching bare identifiers or conceptual queries. For identifiers, use 'fff_grep' or 'token-savior_search_codebase'. For conceptual queries, use 'smart-context_smart_search' (semantic=true). Use this tool ONLY for complex raw regex patterns across the filesystem."
    },
    "glob": {
        "description": "Fast file pattern matching tool. AVOID: Prefer 'fff_find_files' for fuzzy file search by name, or 'cortexast_cortex_code_explorer' (map_overview) for directory mapping. Use this tool ONLY when you need to match specific complex glob patterns across the filesystem."
    },
    "cortexast_cortex_code_explorer": {
        "description": "🔍 CODE EXPLORER MEGATOOL — Provides two complementary lenses on a codebase: a fast bird's-eye symbol map (map_overview) or a deep token-budgeted XML slice (deep_slice). Use map_overview to understand repo structure, discover file/symbol names, or orient yourself. Use deep_slice when you need actual function bodies or multi-file context for a specific edit."
    },
    "cortexast_cortex_symbol_analyzer": {
        "description": "🎯 SYMBOL ANALYSIS MEGATOOL — Uses tree-sitter AST analysis to deliver 100% accurate results for symbol lookups. read_source: extract the exact full source of any function/class/struct. find_usages: discover every call site, type reference, and field initialization. blast_radius: analyze incoming callers and outgoing callees before rename/move/delete. propagation_checklist: generate a checklist of every place a symbol is used when modifying shared types."
    },
    "cortexast_run_diagnostics": {
        "description": "🚨 COMPILE-TIME DIAGNOSTICS — Runs the project's primary compiler (cargo check, tsc, gcc, etc.) and maps every error and warning directly to exact AST source lines. Use this immediately after any code edit to catch compiler errors before proceeding."
    },
    "smart-context_smart_test": {
        "description": "Test orchestration tied to the import graph. action='affected': returns test files that should re-run based on git diff. action='run': executes a test runner from an allowlist (npm-test, jest, vitest, etc.) on specific files. action='last_failure': returns the last persisted failed run."
    },
    "smart-context_smart_review": {
        "description": "Code review preflight in one call. Given a git ref (default HEAD), returns per-file additions/deletions, changeType, callers, affected tests, changed symbols, and offline heuristic findings (TODO/FIXME, console.log, process.exit, alert, etc.). Optional includeBlame: true performs git blame on changed symbol lines."
    },
    "smart-context_smart_search": {
        "description": "Search code with ranked, deduplicated results and index boosting. Best for finding where a symbol is defined/used, understanding call chains, or locating implementations. Pass semantic=true to include a local semantic re-rank for conceptual queries."
    },
    "smart-context_smart_shell": {
        "description": "Run a diagnostic shell command from an allowlist. AVOID: Do NOT use this tool for compilation/linting checks or running tests. For compilation/linting, use 'cortexast_run_diagnostics'. For tests, use 'smart-context_smart_test'. Use this tool ONLY for generic git, npm, or system commands."
    },
    "smart-context_smart_status": {
        "description": "Display the current session context including goal, status, recent decisions, touched files, and progress. Returns a formatted summary of what has been done and what is being tracked in the active session."
    },
    "smart-context_build_index": {
        "description": "Build a lightweight symbol index for the project. Speeds up smart_search ranking and smart_read symbol lookups."
    },
    "smart-context_cross_project": {
        "description": "Work with multiple related projects (monorepos, microservices, shared libraries). Modes: discover, search, read, symbol, deps, stats."
    },
    "smart-context_git_blame": {
        "description": "Get symbol-level git blame attribution. Modes: symbol, file, author, recent."
    },
    "smart-context_global_memory": {
        "description": "Opt-in cross-project memory persisted to ~/.devctx/global.db. Stores canonical decisions, recurring patterns, playbook drafts, and notes across projects. Actions: save, recall, list, delete, mark_used, stats."
    },
    "smart-context_smart_doctor": {
        "description": "Run an operational health check for local devctx state. Aggregates repo hygiene, SQLite storageHealth, and retention/compaction hygiene."
    },
    "smart-context_smart_edit": {
        "description": "Batch edit multiple files with pattern replacement. Supports literal string replacement or regex patterns."
    },
    "smart-context_smart_metrics": {
        "description": "Inspect token metrics recorded in project-local SQLite storage. Returns aggregated totals, per-tool savings, and productQuality signals."
    },
    "smart-context_smart_playbook": {
        "description": "Run a declarative workflow (playbook) that composes other smart_* tools in one call. Pass list=true to list playbooks. Pass dryRun=true to validate steps."
    },
    "smart-context_smart_read_batch": {
        "description": "Read multiple files in one call. Each item accepts path, mode, symbol, startLine, endLine, and maxTokens."
    },
    "smart-context_smart_resume": {
        "description": "Lightweight entry point for the first prompt of a substantial task. Rehydrates the most recent persisted session and returns a compact recommendedPath."
    },
    "smart-context_warm_cache": {
        "description": "Preload frequently accessed files into OS cache to reduce cold-start latency."
    },
    "token-savior_find_semantic_duplicates": {
        "description": "Find duplicate functions. method='ast' (hash-based) or 'embedding' (Nomic cosine)."
    },
    "token-savior_ts_search": {
        "description": "Find the top-K Token Savior tools most relevant to a natural-language query via embedding cosine similarity."
    },
}


def compact_tools_with_static_map(data):
    """Compact tool descriptions using the static map."""
    if "tools" not in data:
        return data

    for tool_group in data["tools"]:
        if "functionDeclarations" not in tool_group:
            continue
        for func in tool_group["functionDeclarations"]:
            name = func.get("name")
            if name in COMPACTED_TOOLS:
                cfg = COMPACTED_TOOLS[name]
                if "description" in cfg:
                    func["description"] = cfg["description"]
                if (
                    "properties" in cfg
                    and "parameters" in func
                    and "properties" in func["parameters"]
                ):
                    for param_name, new_desc in cfg["properties"].items():
                        if param_name in func["parameters"]["properties"]:
                            func["parameters"]["properties"][param_name][
                                "description"
                            ] = new_desc
    return data


def compact_using_superpowers_block(content):
    """Replace the <EXTREMELY_IMPORTANT> block with a compacted version."""
    compacted_block = """<EXTREMELY_IMPORTANT>
You have superpowers.

<SUBAGENT-STOP>
If you were dispatched as a subagent to execute a specific task, skip this skill.
</SUBAGENT-STOP>

If you think there is even a 1% chance a skill might apply to what you are doing, you ABSOLUTELY MUST invoke the skill. This is not negotiable.

## Instruction Priority
1. User's explicit instructions (CLAUDE.md, GEMINI.md, AGENTS.md, direct requests) — highest priority
2. Superpowers skills — override default system behavior where they conflict
3. Default system prompt — lowest priority

## How to Access Skills in OpenCode
Use OpenCode's native `skill` tool to list and load skills.

## The Rule
Invoke relevant or requested skills BEFORE any response or action.
</EXTREMELY_IMPORTANT>"""

    pattern = r"<EXTREMELY_IMPORTANT>.*?</EXTREMELY_IMPORTANT>"
    return re.sub(pattern, compacted_block, content, flags=re.DOTALL)


def compact_skill_responses(data):
    """
    Inspects the contents array for any functionResponse from the 'skill' tool.
    If the skill is 'using-superpowers', strips out other platform instructions
    and the useless <skill_files> block to save tokens.
    """
    if "contents" not in data:
        return data

    for message in data["contents"]:
        if "parts" not in message:
            continue
        for part in message["parts"]:
            if "functionResponse" in part:
                func_resp = part["functionResponse"]
                if func_resp.get("name") == "skill" and "response" in func_resp:
                    resp_obj = func_resp["response"]
                    if "content" in resp_obj and isinstance(resp_obj["content"], str):
                        content_str = resp_obj["content"]
                        if '<skill_content name="using-superpowers">' in content_str:
                            # 1. Strip other platform instructions
                            pattern_access = r"## How to Access Skills.*?# Using Skills"
                            replacement_access = "## How to Access Skills\n\nIn OpenCode, use the native `skill` tool to list and load skills.\n\n# Using Skills"
                            content_str = re.sub(
                                pattern_access,
                                replacement_access,
                                content_str,
                                flags=re.DOTALL,
                            )

                            # 2. Strip <skill_files> block
                            pattern_files = r"<skill_files>.*?</skill_files>"
                            content_str = re.sub(
                                pattern_files, "", content_str, flags=re.DOTALL
                            )

                            resp_obj["content"] = content_str
    return data


def strip_cursor_mode_from_devctx(text):
    """Strips the Cursor assisted mode section from devctx instructions."""
    if "<!-- devctx:start -->" not in text:
        return text
    pattern = r"Cursor assisted mode:.*?Reading cascade:"
    return re.sub(pattern, "Reading cascade:", text, flags=re.DOTALL)


def compact_devctx_instructions(data):
    """
    Looks for the <!-- devctx:start --> block in systemInstruction or contents,
    and strips out the 'Cursor assisted mode' section since we are in OpenCode.
    """
    if "systemInstruction" in data:
        sys_inst = data["systemInstruction"]
        if "parts" in sys_inst:
            for part in sys_inst["parts"]:
                if "text" in part and isinstance(part["text"], str):
                    part["text"] = strip_cursor_mode_from_devctx(part["text"])

    if "contents" in data:
        for message in data["contents"]:
            if "parts" not in message:
                continue
            for part in message["parts"]:
                if "text" in part and isinstance(part["text"], str):
                    part["text"] = strip_cursor_mode_from_devctx(part["text"])

    return data


def compact_contents_superpowers(data):
    """Compact the using-superpowers skill block in the contents array."""
    if "contents" not in data:
        return data

    for message in data["contents"]:
        if "parts" not in message:
            continue
        for part in message["parts"]:
            if "text" in part and isinstance(part["text"], str):
                part["text"] = compact_using_superpowers_block(part["text"])
    return data


def block_generic_read_on_code_files(data):
    """
    Inspects the contents array for any functionResponse from the generic 'read' tool.
    If the file being read is a code or structured file, replaces its content with a hard warning.
    """
    if "contents" not in data:
        return data

    for message in data["contents"]:
        if "parts" not in message:
            continue
        for part in message["parts"]:
            if "functionResponse" in part:
                func_resp = part["functionResponse"]
                if func_resp.get("name") == "read" and "response" in func_resp:
                    resp_obj = func_resp["response"]
                    if "content" in resp_obj and isinstance(resp_obj["content"], str):
                        content_str = resp_obj["content"]
                        # Extract path from <path>...</path>
                        match = re.search(r"<path>(.*?)</path>", content_str)
                        if match:
                            file_path = match.group(1)
                            _, ext = os.path.splitext(file_path.lower())
                            if ext in CODE_EXTENSIONS:
                                # Replace the content with a hard warning!
                                warning_msg = f"<path>{file_path}</path>\n<type>file</type>\n<content>Error: Direct use of the generic 'read' tool is restricted for code and structured files. You MUST use 'smart-context_smart_read' with mode='outline' or mode='signatures' (for code) or mode='explain'/'outline' (for structured files) first to inspect the file structure, or 'token-savior_get_function_source' for specific symbols.</content>"
                                resp_obj["content"] = warning_msg
                                logger.debug(
                                    f"[Compactor] Blocked generic 'read' on code/structured file: {file_path}"
                                )
    return data


def clean_json_escapes(content):
    """Universal fix for odd number of backslashes followed by newline."""
    pattern = r"((?<!\\)\\(?:\\\\)*)(\r?\n)"

    def replace_odd_slashes(match):
        slashes = match.group(1)
        newline = match.group(2)
        return slashes + "\\" + newline

    return re.sub(pattern, replace_odd_slashes, content)


def move_reminder_to_system_instruction(data):
    """
    Extracts the <internal_reminder> block from contents, strips it from all messages
    to preserve prompt caching, and appends it to the systemInstruction so it is
    always active and never lost during history compaction.
    """
    if "contents" not in data:
        return data

    reminder_content = None
    pattern = r"<internal_reminder>(.*?)</internal_reminder>"

    # 1. Find and extract the first reminder block
    for message in data["contents"]:
        if "parts" not in message:
            continue
        for part in message["parts"]:
            if "text" in part and isinstance(part["text"], str):
                match = re.search(pattern, part["text"], flags=re.DOTALL)
                if match:
                    reminder_content = match.group(1).strip()
                    break
        if reminder_content:
            break

    # 2. Strip all reminder blocks from contents
    for message in data["contents"]:
        if "parts" not in message:
            continue
        for part in message["parts"]:
            if "text" in part and isinstance(part["text"], str):
                text = part["text"]
                if re.search(
                    r"<internal_reminder>.*?</internal_reminder>", text, flags=re.DOTALL
                ):
                    part["text"] = re.sub(
                        r"<internal_reminder>.*?</internal_reminder>",
                        "",
                        text,
                        flags=re.DOTALL,
                    )
                    logger.debug(
                        "[Compactor] Stripped <internal_reminder> block from message"
                    )

    # 3. Append reminder to systemInstruction
    if reminder_content:
        formatted_reminder = f"\n\n[System Reminder: {reminder_content}]"

        if "systemInstruction" not in data:
            data["systemInstruction"] = {
                "parts": [{"text": formatted_reminder.strip()}]
            }
            logger.debug("[Compactor] Created systemInstruction with reminder")
        else:
            sys_inst = data["systemInstruction"]
            if "parts" in sys_inst:
                appended = False
                for part in sys_inst["parts"]:
                    if "text" in part and isinstance(part["text"], str):
                        if reminder_content[:30] not in part["text"]:
                            part["text"] += formatted_reminder
                            logger.debug(
                                "[Compactor] Appended reminder to systemInstruction"
                            )
                        appended = True
                        break
                if not appended:
                    sys_inst["parts"].append({"text": formatted_reminder.strip()})
                    logger.debug("[Compactor] Appended new part to systemInstruction")

    return data


def process_request_payload(payload_dict):
    """Main entry point for GeminiProxy context compaction."""
    # 1. Compact tools
    payload_dict = compact_tools_with_static_map(payload_dict)
    # 2. Compact superpowers block in contents
    payload_dict = compact_contents_superpowers(payload_dict)
    # 3. Compact skill responses
    payload_dict = compact_skill_responses(payload_dict)
    # 4. Compact devctx instructions
    payload_dict = compact_devctx_instructions(payload_dict)
    # 5. Block generic read on code files
    payload_dict = block_generic_read_on_code_files(payload_dict)
    # 6. Move internal reminders to systemInstruction to preserve prompt cache
    payload_dict = move_reminder_to_system_instruction(payload_dict)
    return payload_dict
