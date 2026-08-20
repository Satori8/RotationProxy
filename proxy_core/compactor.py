import re
import os
import logging

logger = logging.getLogger("proxy")

# Check for required dependencies at startup
try:
    import headroom
except ImportError:
    logger.debug("=" * 80)
    logger.debug("CRITICAL SYSTEM ERROR: 'headroom' module is NOT installed!")
    logger.debug(
        "Headroom context compression will NOT work. Please run with 'uv run --with headroom-ai[all]'."
    )
    logger.debug("=" * 80)

try:
    import tree_sitter
except ImportError:
    logger.debug("=" * 80)
    logger.debug("CRITICAL SYSTEM ERROR: 'tree_sitter' module is NOT installed!")
    logger.debug("AST-aware parsing and monkey-patches will NOT work.")
    logger.debug("=" * 80)

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


# ЧЕРНЫЙ СПИСОК: Эти инструменты будут полностью вырезаны из промпта
BANNED_COMPRESSED_TOOLS = {
    # 1. Избыточные академические и метрические утилиты tokensave (БЛОКИРУЕМ)
    "tokensave_gini",
    "tokensave_complexity",
    "tokensave_god_class",
    "tokensave_coupling",
    "tokensave_dsm",
    "tokensave_circular",
    "tokensave_recursion",
    "tokensave_redundancy",
    "tokensave_health",
    "tokensave_hotspots",
    "tokensave_distribution",
    "tokensave_largest",
    "tokensave_dependency_depth",
    "tokensave_inheritance_depth",
    "tokensave_test_risk",
    "tokensave_doc_coverage",
    "tokensave_runtime",
    "tokensave_diagnose",
    "tokensave_simplify_scan",
    # 2. Неиспользуемые или дублирующиеся гит- и вспомогательные утилиты tokensave (БЛОКИРУЕМ)
    "tokensave_port_order",
    "tokensave_port_status",
    "tokensave_branch_list",
    "tokensave_branch_search",
    "tokensave_branch_diff",
    "tokensave_commit_context",
    "tokensave_pr_context",
    "tokensave_session_start",
    "tokensave_session_end",
    "tokensave_record_code_area",
    "tokensave_test_map",
    "tokensave_config",
    "tokensave_signature_search",
    "tokensave_type_hierarchy",
    "tokensave_run_affected_tests",
    "tokensave_callers_for",
    "tokensave_derives",
    "tokensave_impls",
    "tokensave_similar",
    "tokensave_call_chain",
    "tokensave_status",
    # 3. Неиспользуемые или избыточные утилиты tokensave (БЛОКИРУЕМ)
    "tokensave_annotations",
    "tokensave_ast_grep_rewrite",
    "tokensave_blame",
    "tokensave_changelog",
    "tokensave_constructors",
    "tokensave_context",
    "tokensave_log",
    "tokensave_rank",
    "tokensave_record_decision",
    "tokensave_session_recall",
    "tokensave_test_coverage",
    "tokensave_unused_imports",
    # 4. Тяжелые или ненужные утилиты из lean-ctx (БЛОКИРУЕМ)
    "ctx_architecture",
    "ctx_agent",
    "ctx_compress",
    "ctx_pack",
    "ctx_refactor",
    "ctx_delta",
    "ctx_multi_read",
    "ctx_overview",
    "ctx_knowledge",
    "shell",
}


def prune_mcp_xml_descriptions(tools_payload, blacklist=BANNED_COMPRESSED_TOOLS):
    """
    Парсит описание мета-инструментов get_tool_schema и удаляет из XML-списка
    все инструменты, входящие в черный список (blacklist).
    """
    if not tools_payload:
        return tools_payload

    for tool_entry in tools_payload:
        funcs = []
        if "function" in tool_entry:
            funcs = [tool_entry["function"]]
        elif "functionDeclarations" in tool_entry:
            funcs = tool_entry["functionDeclarations"]

        for func in funcs:
            desc = func.get("description", "")
            if desc and "Available tools are:" in desc:
                # Находим все блоки вида <tool>имя_инструмента(...)</tool>
                # Используем улучшенный регулярный паттерн для максимальной надежности
                blocks = re.findall(
                    r"(<tool>([\w-]+)(?:\(.*?\))?.*?</tool>)", desc, re.DOTALL
                )
                if not blocks:
                    continue

                header = desc.split("Available tools are:")[0].strip()
                new_desc_lines = [header, "\n\nAvailable tools are:"]

                for full_block, tool_name in blocks:
                    t_name = tool_name.strip()
                    # Проверяем как точное совпадение, так и базовое имя без лишних префиксов
                    is_banned = False
                    if t_name in blacklist:
                        is_banned = True
                    elif (
                        t_name.startswith("tokensave_tokensave_")
                        and t_name[11:] in blacklist
                    ):
                        is_banned = True
                    elif t_name.startswith("tokensave_") and t_name[10:] in blacklist:
                        is_banned = True

                    if not is_banned:
                        new_desc_lines.append(full_block)

                func["description"] = "\n".join(new_desc_lines)

    return tools_payload


def compact_tools_with_static_map(data):
    """Compact tool descriptions using the static map."""
    if "tools" not in data:
        return data

    for tool_group in data["tools"]:
        # Gemini format
        if "functionDeclarations" in tool_group:
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
                                param_obj = func["parameters"]["properties"][param_name]
                                if isinstance(param_obj, dict):
                                    param_obj["description"] = new_desc
        # OpenAI format
        elif tool_group.get("type") == "function" and "function" in tool_group:
            func = tool_group["function"]
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
                            param_obj = func["parameters"]["properties"][param_name]
                            if isinstance(param_obj, dict):
                                param_obj["description"] = new_desc

    # Prune MCP XML descriptions to filter out banned/unwanted tools
    data["tools"] = prune_mcp_xml_descriptions(data["tools"])

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
    Inspects the contents array (Gemini) or messages array (OpenAI) for any functionResponse from the 'skill' tool.
    If the skill is 'using-superpowers', strips out other platform instructions
    and the useless <skill_files> block to save tokens.
    """
    # --- Gemini Format ---
    if "contents" in data:
        for message in data["contents"]:
            if "parts" not in message:
                continue
            for part in message["parts"]:
                if "functionResponse" in part:
                    func_resp = part["functionResponse"]
                    if func_resp.get("name") == "skill" and "response" in func_resp:
                        resp_obj = func_resp["response"]
                        if "content" in resp_obj and isinstance(
                            resp_obj["content"], str
                        ):
                            content_str = resp_obj["content"]
                            if (
                                '<skill_content name="using-superpowers">'
                                in content_str
                            ):
                                # 1. Strip other platform instructions
                                pattern_access = (
                                    r"## How to Access Skills.*?# Using Skills"
                                )
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

    # --- OpenAI Format ---
    if "messages" in data:
        for msg in data["messages"]:
            if (
                msg.get("role") == "tool"
                and "content" in msg
                and isinstance(msg["content"], str)
            ):
                content_str = msg["content"]
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

                    msg["content"] = content_str
    return data


def strip_cursor_mode_from_devctx(text):
    """Strips the Cursor assisted mode section from devctx instructions."""
    if "<!-- devctx:start -->" not in text:
        return text
    pattern = r"Cursor assisted mode:.*?Reading cascade:"
    return re.sub(pattern, "Reading cascade:", text, flags=re.DOTALL)


def compact_devctx_instructions(data):
    """
    Looks for the <!-- devctx:start --> block in systemInstruction or contents (Gemini),
    or system/messages (OpenAI), and strips out the 'Cursor assisted mode' section.
    """
    # --- Gemini Format ---
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

    # --- OpenAI Format ---
    if "system" in data and isinstance(data["system"], str):
        data["system"] = strip_cursor_mode_from_devctx(data["system"])

    if "messages" in data:
        for msg in data["messages"]:
            if "content" in msg and isinstance(msg["content"], str):
                msg["content"] = strip_cursor_mode_from_devctx(msg["content"])

    return data


def compact_contents_superpowers(data):
    """Compact the using-superpowers skill block in the contents array (Gemini) or messages array (OpenAI)."""
    # --- Gemini Format ---
    if "contents" in data:
        for message in data["contents"]:
            if "parts" not in message:
                continue
            for part in message["parts"]:
                if "text" in part and isinstance(part["text"], str):
                    part["text"] = compact_using_superpowers_block(part["text"])

    # --- OpenAI Format ---
    if "messages" in data:
        for msg in data["messages"]:
            if "content" in msg and isinstance(msg["content"], str):
                msg["content"] = compact_using_superpowers_block(msg["content"])
    return data


def block_generic_read_on_code_files(data):
    """
    Inspects the contents array (Gemini) or messages array (OpenAI) for any functionResponse from the generic 'read' tool.
    If the file being read is a code or structured file, replaces its content with a hard warning.
    """
    # --- Gemini Format ---
    if "contents" in data:
        for message in data["contents"]:
            if "parts" not in message:
                continue
            for part in message["parts"]:
                if "functionResponse" in part:
                    func_resp = part["functionResponse"]
                    if func_resp.get("name") == "read" and "response" in func_resp:
                        resp_obj = func_resp["response"]
                        if "content" in resp_obj and isinstance(
                            resp_obj["content"], str
                        ):
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

    # --- OpenAI Format ---
    if "messages" in data:
        for msg in data["messages"]:
            if (
                msg.get("role") == "tool"
                and "content" in msg
                and isinstance(msg["content"], str)
            ):
                content_str = msg["content"]
                match = re.search(r"<path>(.*?)</path>", content_str)
                if match:
                    file_path = match.group(1)
                    _, ext = os.path.splitext(file_path.lower())
                    if ext in CODE_EXTENSIONS:
                        # Replace the content with a hard warning!
                        warning_msg = f"<path>{file_path}</path>\n<type>file</type>\n<content>Error: Direct use of the generic 'read' tool is restricted for code and structured files. You MUST use 'smart-context_smart_read' with mode='outline' or mode='signatures' (for code) or mode='explain'/'outline' (for structured files) first to inspect the file structure, or 'token-savior_get_function_source' for specific symbols.</content>"
                        msg["content"] = warning_msg
                        logger.debug(
                            f"[Compactor] Blocked generic 'read' on code/structured file in messages: {file_path}"
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
    Extracts the <internal_reminder> block from contents (Gemini) or messages (OpenAI),
    strips it from all messages to preserve prompt caching, and appends it to the
    systemInstruction (Gemini) or system field/messages (OpenAI) so it is always active.
    """
    reminder_content = None
    pattern = r"<internal_reminder>(.*?)</internal_reminder>"

    # --- Gemini Format ---
    if "contents" in data:
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
                        r"<internal_reminder>.*?</internal_reminder>",
                        text,
                        flags=re.DOTALL,
                    ):
                        part["text"] = re.sub(
                            r"<internal_reminder>.*?</internal_reminder>",
                            "",
                            text,
                            flags=re.DOTALL,
                        )
                        logger.debug(
                            "[Compactor] Stripped <internal_reminder> block from Gemini message"
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
                        logger.debug(
                            "[Compactor] Appended new part to systemInstruction"
                        )

    # --- OpenAI Format ---
    if "messages" in data:
        # 1. Find and extract the first reminder block
        for msg in data["messages"]:
            if "content" in msg and isinstance(msg["content"], str):
                match = re.search(pattern, msg["content"], flags=re.DOTALL)
                if match:
                    reminder_content = match.group(1).strip()
                    break

        # 2. Strip all reminder blocks from messages
        for msg in data["messages"]:
            if "content" in msg and isinstance(msg["content"], str):
                text = msg["content"]
                if re.search(
                    r"<internal_reminder>.*?</internal_reminder>", text, flags=re.DOTALL
                ):
                    msg["content"] = re.sub(
                        r"<internal_reminder>.*?</internal_reminder>",
                        "",
                        text,
                        flags=re.DOTALL,
                    )
                    logger.debug(
                        "[Compactor] Stripped <internal_reminder> block from OpenAI message"
                    )

        # 3. Append reminder to system prompt
        if reminder_content:
            formatted_reminder = f"\n\n[System Reminder: {reminder_content}]"

            # Check top-level system field
            if "system" in data and isinstance(data["system"], str):
                if reminder_content[:30] not in data["system"]:
                    data["system"] += formatted_reminder
                    logger.debug(
                        "[Compactor] Appended reminder to top-level system field"
                    )
            else:
                # Find system message in messages
                system_msg = None
                for msg in data["messages"]:
                    if msg.get("role") == "system":
                        system_msg = msg
                        break

                if system_msg:
                    if "content" in system_msg and isinstance(
                        system_msg["content"], str
                    ):
                        if reminder_content[:30] not in system_msg["content"]:
                            system_msg["content"] += formatted_reminder
                            logger.debug(
                                "[Compactor] Appended reminder to system message"
                            )
                else:
                    # Create a new system message at the beginning
                    data["messages"].insert(
                        0, {"role": "system", "content": formatted_reminder.strip()}
                    )
                    logger.debug("[Compactor] Created system message with reminder")

    return data


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
2. For reading code files, you MUST use 'tokensave_tokensave_node' or 'cortexast_cortex_symbol_analyzer(action="read_source")' to extract specific functions/classes by name. No raw full-file reading.
3. For modifying code files, you MUST use 'tokensave_tokensave_str_replace' or 'tokensave_tokensave_multi_str_replace' for precise, safe string replacements. Fails if 0 or >1 matches to protect against multi-edit bugs. No full file overwrites.
4. For searching code or text, you MUST use 'tokensave_tokensave_search' or 'lean-ctx_ctx_search' instead of generic 'grep' or 'search'.
5. For finding files by name, you MUST use 'fff_find_files' or 'cortexast_cortex_code_explorer(action="map_overview")' instead of generic 'glob' or 'find'.
6. For running build, test, lint, or git checks, you MUST use 'lean-ctx_ctx_shell' or 'cortexast_run_diagnostics' instead of generic 'shell' or 'bash'.
7. Direct 'read', 'write', 'grep', 'glob', and 'shell' tools are restricted and should be avoided in favor of optimized tokensave and lean-ctx tools.]"""

    # Helper to clean up bad instructions in Fixer/Refactorer prompts
    def clean_bad_instructions(text: str) -> str:
        if not isinstance(text, str):
            return text
        # Replace "use grep/glob/read directly"
        text = re.sub(
            r"use grep/glob/read directly",
            "use tokensave_tokensave_search, lean-ctx_ctx_search, or fff_find_files directly",
            text,
            flags=re.IGNORECASE,
        )
        # Replace "Read files before using edit/write tools"
        text = re.sub(
            r"Read files before using edit/write tools",
            "Read files using tokensave_tokensave_node or lean-ctx_ctx_read before using edit/tokensave tools",
            text,
            flags=re.IGNORECASE,
        )
        # Replace smart-context and token-savior tools with current ones
        text = re.sub(
            r"smart-context_smart_search",
            "lean-ctx_ctx_search",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(
            r"token-savior_search_codebase",
            "tokensave_tokensave_search",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(
            r"smart-context_smart_read",
            "lean-ctx_ctx_read",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(
            r"token-savior_get_function_source",
            "tokensave_tokensave_node",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(
            r"token-savior_replace_symbol_source",
            "tokensave_tokensave_replace_symbol",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(
            r"smart-context_smart_shell",
            "lean-ctx_ctx_shell",
            text,
            flags=re.IGNORECASE,
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
                    logger.debug(
                        "[Compactor] Injected tool guardrails into Gemini systemInstruction"
                    )

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
            if (
                msg.get("role") == "system"
                and "content" in msg
                and isinstance(msg["content"], str)
            ):
                text = msg["content"]
                text = clean_bad_instructions(text)
                if "CRITICAL TOOL GUARDRAIL" not in text:
                    text += guardrail_block
                    injected = True
                msg["content"] = text
                logger.debug(
                    "[Compactor] Injected tool guardrails into OpenAI system message"
                )

    if injected:
        state.COMPACTOR_INJECTIONS_COUNT = (
            getattr(state, "COMPACTOR_INJECTIONS_COUNT", 0) + 1
        )

    return data


GEMINI_PART_DATA_FIELDS = (
    "inlineData",
    "functionCall",
    "functionResponse",
    "fileData",
    "executableCode",
    "codeExecutionResult",
)


def split_merged_parts_in_contents(data):
    """
    Splits Gemini Part objects that illegally combine a data oneof field
    (functionCall / inlineData / functionResponse / fileData / ...) with `text`
    into separate parts.

    Some SDK versions (e.g. @ai-sdk/google / google-genai / nodejs-vertexai)
    merge streamed text + functionCall into a SINGLE Part when the model emits
    text and a tool call in the same stream. Google rejects such parts with:
        "Invalid value at 'contents[N].parts[0]' (oneof),
         oneof field 'data' is already set. Cannot set 'text'"
    The correct format is separate parts:
        [{"functionCall": {...}}, {"text": "..."}]
    """
    if "contents" in data and isinstance(data["contents"], list):
        for msg in data["contents"]:
            if (
                not isinstance(msg, dict)
                or "parts" not in msg
                or not isinstance(msg["parts"], list)
            ):
                continue
            new_parts = []
            for part in msg["parts"]:
                if not isinstance(part, dict):
                    new_parts.append(part)
                    continue
                data_field = next(
                    (k for k in GEMINI_PART_DATA_FIELDS if k in part), None
                )
                if data_field and "text" in part:
                    # Split into separate parts; keep thought/signature metadata
                    # on the data part (functionCall parts carry thoughtSignature).
                    data_part = {k: v for k, v in part.items() if k != "text"}
                    new_parts.append(data_part)
                    text_val = part.get("text")
                    if isinstance(text_val, str) and text_val.strip():
                        new_parts.append({"text": text_val})
                else:
                    new_parts.append(part)
            msg["parts"] = new_parts
    return data


def strip_historical_thoughts_from_contents(data):
    """
    Strips bulky reasoning thought text from historical model turns in outgoing requests
    while preserving cryptographic thought signatures (thoughtSignature / thought_signature)
    and thought markers required by Google Gemini API to maintain multi-turn validation.
    """
    if "contents" in data and isinstance(data["contents"], list):
        for msg in data["contents"]:
            if (
                msg.get("role") == "model"
                and "parts" in msg
                and isinstance(msg["parts"], list)
            ):
                new_parts = []
                for p in msg["parts"]:
                    if isinstance(p, dict):
                        is_thought = (
                            p.get("thought") is True or p.get("thought") == True
                        )
                        has_signature = (
                            "thoughtSignature" in p or "thought_signature" in p
                        )

                        if is_thought or has_signature:
                            if has_signature:
                                # Preserve the thought signature and marker while stripping the bulky thought text
                                sig_part = {
                                    k: v for k, v in p.items() if k not in ("text",)
                                }
                                sig_part["thought"] = True
                                sig_part["text"] = ""
                                new_parts.append(sig_part)
                            # If it's a thought part without a signature, omit it to save tokens
                        else:
                            new_parts.append(p)

                if new_parts:
                    msg["parts"] = new_parts
                else:
                    msg["parts"] = [{"text": ""}]

    if "messages" in data and isinstance(data["messages"], list):
        for msg in data["messages"]:
            if msg.get("role") == "assistant":
                if "reasoning_content" in msg:
                    del msg["reasoning_content"]
                if "reasoning" in msg:
                    del msg["reasoning"]

    return data


def normalize_thinking_config(data):
    """
    Normalizes thinkingConfig in generationConfig:
    - Replaces invalid 'budgetTokens' key with valid 'thinkingBudget'.
    - Removes 'thinkingLevel' if 'thinkingBudget' is also present (API only allows one).
    """
    if "generationConfig" in data and isinstance(data["generationConfig"], dict):
        gc = data["generationConfig"]
        if "thinkingConfig" in gc and isinstance(gc["thinkingConfig"], dict):
            tc = gc["thinkingConfig"]
            if "budgetTokens" in tc:
                budget = tc.pop("budgetTokens")
                tc["thinkingBudget"] = budget
                logger.debug(
                    f"[Compactor] Normalized thinkingConfig.budgetTokens -> thinkingBudget: {budget}"
                )
            # Gemini API only allows one of thinkingBudget or thinkingLevel
            if "thinkingBudget" in tc and "thinkingLevel" in tc:
                logger.debug(
                    "[Compactor] Removing thinkingLevel since thinkingBudget is also set (API only allows one)"
                )
                tc.pop("thinkingLevel", None)

    return data


def normalize_gemini_thinking_temperature(data):
    """
    Ensure temperature is at least 0.7 for Gemini thinking models to prevent
    'Thinking Collapse' (where low temp causes the model to output STOP immediately after thoughts).
    """
    # Gemini native format
    if "generationConfig" in data and isinstance(data["generationConfig"], dict):
        gc = data["generationConfig"]
        if "temperature" in gc and gc["temperature"] is not None:
            if float(gc["temperature"]) < 0.7:
                gc["temperature"] = 0.7
                logger.debug(
                    "[Compactor] Clamped generationConfig.temperature to 0.7 for Gemini thinking stability"
                )

    # OpenAI format
    if "temperature" in data and data["temperature"] is not None:
        if float(data["temperature"]) < 0.7:
            data["temperature"] = 0.7
            logger.debug(
                "[Compactor] Clamped payload.temperature to 0.7 for Gemini thinking stability"
            )

    return data


def process_request_payload(payload_dict, config=None):
    """Main entry point for GeminiProxy context compaction."""
    if config is None:
        config = {}

    import json
    from proxy_core import state

    try:
        import tiktoken

        encoding = tiktoken.get_encoding("cl100k_base")
    except Exception:
        encoding = None

    def get_metrics(data):
        try:
            serialized = json.dumps(data, ensure_ascii=False)
            size_bytes = len(serialized.encode("utf-8"))
            if encoding:
                tokens = len(encoding.encode(serialized))
            else:
                tokens = 0
            return size_bytes, tokens
        except Exception:
            return 0, 0

    def get_payload_size(data):
        try:
            return len(json.dumps(data, ensure_ascii=False))
        except Exception:
            return 0

    # Stage 1: Input from OpenCode
    orig_bytes, orig_tokens = get_metrics(payload_dict)

    # 1. Compact tools
    if config.get("compactor_compact_tools", True):
        size_before = get_payload_size(payload_dict)
        payload_dict = compact_tools_with_static_map(payload_dict)
        size_after = get_payload_size(payload_dict)
        state.COMPACTOR_SAVED_TOOLS = getattr(state, "COMPACTOR_SAVED_TOOLS", 0) + max(
            0, size_before - size_after
        )

    # 2. Compact superpowers block in contents
    if config.get("compactor_compact_superpowers", True):
        size_before = get_payload_size(payload_dict)
        payload_dict = compact_contents_superpowers(payload_dict)
        size_after = get_payload_size(payload_dict)
        state.COMPACTOR_SAVED_SUPERPOWERS = getattr(
            state, "COMPACTOR_SAVED_SUPERPOWERS", 0
        ) + max(0, size_before - size_after)

    # 3. Compact skill responses
    if config.get("compactor_compact_skills", True):
        size_before = get_payload_size(payload_dict)
        payload_dict = compact_skill_responses(payload_dict)
        size_after = get_payload_size(payload_dict)
        state.COMPACTOR_SAVED_SKILLS = getattr(
            state, "COMPACTOR_SAVED_SKILLS", 0
        ) + max(0, size_before - size_after)

    # 4. Compact devctx instructions
    if config.get("compactor_compact_devctx", True):
        size_before = get_payload_size(payload_dict)
        payload_dict = compact_devctx_instructions(payload_dict)
        size_after = get_payload_size(payload_dict)
        state.COMPACTOR_SAVED_DEVCTX = getattr(
            state, "COMPACTOR_SAVED_DEVCTX", 0
        ) + max(0, size_before - size_after)

    # 5. Block generic read on code files
    if config.get("compactor_block_generic_read", True):
        size_before = get_payload_size(payload_dict)
        payload_dict = block_generic_read_on_code_files(payload_dict)
        size_after = get_payload_size(payload_dict)
        state.COMPACTOR_SAVED_GENERIC_READ = getattr(
            state, "COMPACTOR_SAVED_GENERIC_READ", 0
        ) + max(0, size_before - size_after)

    # 6. Move internal reminders to systemInstruction to preserve prompt cache
    if config.get("compactor_move_reminders", True):
        size_before = get_payload_size(payload_dict)
        payload_dict = move_reminder_to_system_instruction(payload_dict)
        size_after = get_payload_size(payload_dict)
        state.COMPACTOR_SAVED_REMINDERS = getattr(
            state, "COMPACTOR_SAVED_REMINDERS", 0
        ) + max(0, size_before - size_after)

    # 7. Inject Tool Guardrails to force optimized tools
    if config.get("compactor_inject_guardrails", True):
        payload_dict = inject_tool_guardrails(payload_dict)

    # Stage 2: After our local compaction
    local_bytes, local_tokens = get_metrics(payload_dict)

    # Check if headroom is available
    has_headroom = False
    try:
        import headroom

        has_headroom = True
    except ImportError:
        pass

    # Check if tree_sitter is available
    has_tree_sitter = False
    try:
        import tree_sitter

        has_tree_sitter = True
    except ImportError:
        pass

    if has_headroom:
        # Monkey-patch headroom content router to avoid hanging on Rust detect_content_type
        try:
            import headroom.transforms.content_router as cr

            if cr._detect_content != cr._regex_detect_content_type:
                cr._detect_content = cr._regex_detect_content_type
                logger.debug(
                    "[Compactor] Monkey-patched headroom._detect_content to use pure Python regex detector"
                )
            # Monkey-patch is_mixed_content to prevent splitting pure code/diff/results/html into uncompressed plain text
            _orig_is_mixed_content = cr.is_mixed_content

            def _safe_is_mixed_content(content: str) -> bool:
                detection = cr._detect_content(content)
                if detection.content_type in (
                    cr.ContentType.SOURCE_CODE,
                    cr.ContentType.GIT_DIFF,
                    cr.ContentType.SEARCH_RESULTS,
                    cr.ContentType.HTML,
                ):
                    return False
                return _orig_is_mixed_content(content)

            cr.is_mixed_content = _safe_is_mixed_content
            logger.debug(
                "[Compactor] Monkey-patched headroom.is_mixed_content to prevent splitting pure blocks"
            )
        except Exception as e:
            logger.debug(f"[Compactor] Failed to monkey-patch headroom: {e}")

        # Monkey-patch CodeLanguage to handle unknown languages (like 'dot') gracefully
        try:
            from headroom.transforms.code_compressor import CodeLanguage

            _orig_new = CodeLanguage.__new__

            def _safe_new(cls, value):
                try:
                    return _orig_new(cls, value)
                except ValueError:
                    return CodeLanguage.UNKNOWN

            CodeLanguage.__new__ = _safe_new
            logger.debug(
                "[Compactor] Monkey-patched CodeLanguage to handle unknown languages gracefully"
            )
        except Exception as e:
            logger.debug(f"[Compactor] Failed to monkey-patch CodeLanguage: {e}")

        # Monkey-patch CodeAwareCompressor._fallback_compress to prevent slow ONNX model loading/inference
        try:
            from headroom.transforms.code_compressor import (
                CodeAwareCompressor,
                CodeCompressionResult,
            )

            def _safe_fallback_compress(self, code: str, original_tokens: int):
                return CodeCompressionResult(
                    compressed=code,
                    original=code,
                    original_tokens=original_tokens,
                    compressed_tokens=original_tokens,
                    compression_ratio=1.0,
                    language=CodeLanguage.UNKNOWN,
                    language_confidence=0.0,
                    syntax_valid=True,
                )

            CodeAwareCompressor._fallback_compress = _safe_fallback_compress
            logger.debug(
                "[Compactor] Monkey-patched CodeAwareCompressor._fallback_compress to disable slow ONNX fallback"
            )
        except Exception as e:
            logger.debug(
                f"[Compactor] Failed to monkey-patch CodeAwareCompressor fallback: {e}"
            )
    else:
        logger.debug(
            "[Compactor] ERROR: 'headroom' module is missing! Headroom context compression is disabled."
        )

    if has_tree_sitter:
        # Monkey-patch tree_sitter_language_pack.get_parser to return a SafeParserWrapper
        try:
            import tree_sitter_language_pack

            class SafeNodeWrapper:
                def __init__(self, node):
                    self._node = node

                @property
                def type(self):
                    val = self._node.type
                    if callable(val):
                        val = val()
                    return val

                @property
                def children(self):
                    children_list = self._node.children
                    if callable(children_list):
                        children_list = children_list()
                    return (
                        [SafeNodeWrapper(c) for c in children_list]
                        if children_list is not None
                        else []
                    )

                def __getattr__(self, name):
                    if name == "_node":
                        raise AttributeError
                    val = getattr(self._node, name)
                    if callable(val) and name in ("type", "children", "root_node"):
                        return val()
                    return val

                def __eq__(self, other):
                    if isinstance(other, SafeNodeWrapper):
                        return self._node == other._node
                    return self._node == other

                def __hash__(self):
                    return hash(self._node)

                def __repr__(self):
                    return repr(self._node)

                def __str__(self):
                    return str(self._node)

            class SafeTreeWrapper:
                def __init__(self, tree):
                    self._tree = tree

                @property
                def root_node(self):
                    node = self._tree.root_node
                    if callable(node):
                        node = node()
                    return SafeNodeWrapper(node) if node is not None else None

                def __getattr__(self, name):
                    if name == "_tree":
                        raise AttributeError
                    return getattr(self._tree, name)

                def __eq__(self, other):
                    if isinstance(other, SafeTreeWrapper):
                        return self._tree == other._tree
                    return self._tree == other

                def __hash__(self):
                    return hash(self._tree)

                def __repr__(self):
                    return repr(self._tree)

                def __str__(self):
                    return str(self._tree)

            class SafeParserWrapper:
                def __init__(self, parser):
                    self._parser = parser

                def parse(self, source, *args, **kwargs):
                    if isinstance(source, bytes):
                        try:
                            tree = self._parser.parse(source, *args, **kwargs)
                        except TypeError as te:
                            if "bytes" in str(te) or "str" in str(te):
                                tree = self._parser.parse(
                                    source.decode("utf-8", errors="replace"),
                                    *args,
                                    **kwargs,
                                )
                            else:
                                raise
                    else:
                        tree = self._parser.parse(source, *args, **kwargs)
                    return SafeTreeWrapper(tree) if tree is not None else None

                def __getattr__(
                    self, name
                ):  # Prevent infinite recursion on inspection/copying
                    if (
                        name == "_parser"
                    ):  # Explicitly block access to _parser via getattr
                        raise AttributeError  # This prevents recursion when tree-sitter inspects the wrapper
                    return getattr(self._parser, name)

            _orig_get_parser = tree_sitter_language_pack.get_parser
            import sys

            _mod = sys.modules[__name__]
            if not hasattr(_mod, "_orig_get_parser"):
                _mod._orig_get_parser = _orig_get_parser

            def _safe_get_parser(language):
                parser = _orig_get_parser(language)
                return SafeParserWrapper(parser)

            tree_sitter_language_pack.get_parser = _safe_get_parser
            logger.debug(
                "[Compactor] Monkey-patched tree_sitter_language_pack.get_parser to handle bytes vs str gracefully"
            )
        except Exception as e:
            logger.debug(
                f"[Compactor] Failed to monkey-patch tree_sitter_language_pack: {e}"
            )
    else:
        logger.debug(
            "[Compactor] ERROR: 'tree_sitter' module is missing! AST monkey-patches are disabled."
        )

    # 8. Headroom compression strictly after our local message compaction
    if has_headroom and config.get("compactor_enable_headroom", True):
        try:
            from headroom.transforms.content_router import (
                ContentRouter,
                ContentRouterConfig,
                CompressionStrategy,
            )

            # Configure ContentRouter to disable slow ONNX-based Kompress ML model,
            # preventing 2+ second delays while keeping fast SmartCrusher active for JSON
            # and enabling fast, AST-aware CodeCompressor for Python code
            cfg = ContentRouterConfig(
                enable_kompress=False,
                enable_code_aware=True,
                fallback_strategy=CompressionStrategy.PASSTHROUGH,
                prefer_code_aware_for_code=True,
                skip_user_messages=False,
                protect_recent_code=0,
                protect_analysis_context=False,
            )
            router = ContentRouter(config=cfg)

            # Monkey-patch _try_ml_compressor to prevent fallback from
            # replacing successful code_aware compression. CodeAwareCompressor
            # reports compressed_tokens as chars/4 while the ContentRouter
            # uses word count as original_tokens. This mismatch causes the
            # fallback to always replace the code_aware result with the
            # original content when kompress is disabled.
            _orig_try_ml = router._try_ml_compressor

            def _patched_try_ml(content, context, question=None):
                if router.config.enable_kompress:
                    return _orig_try_ml(content, context, question)
                # Return high token count so fallback never beats code_aware
                return content, len(content)

            router._try_ml_compressor = _patched_try_ml

            _orig_compress = ContentRouter.compress

            def _safe_compress(self, *args, **kwargs):
                try:
                    return _orig_compress(self, *args, **kwargs)
                except Exception as ex:
                    import traceback

                    logger.error(
                        f"[Compactor] Traceback for headroom error:\n{traceback.format_exc()}"
                    )
                    raise ex

            ContentRouter.compress = _safe_compress

            # Monkey-patch CodeAwareCompressor._compress_with_ast to capture tree-sitter tracebacks
            from headroom.transforms.code_compressor import CodeAwareCompressor

            _orig_compress_with_ast = CodeAwareCompressor._compress_with_ast

            def _safe_compress_with_ast(self, *args, **kwargs):
                try:
                    return _orig_compress_with_ast(self, *args, **kwargs)
                except Exception as ex:
                    import traceback

                    logger.error(
                        f"[Compactor] Traceback for headroom _compress_with_ast error:\n{traceback.format_exc()}"
                    )
                    raise ex

            CodeAwareCompressor._compress_with_ast = _safe_compress_with_ast

            if "messages" in payload_dict:
                # OpenAI format: compress only string content fields directly to preserve tool_calls and structure
                for msg in payload_dict["messages"]:
                    if isinstance(msg, dict) and "content" in msg:
                        content = msg["content"]
                        if isinstance(content, str) and len(content) > 500:
                            res = router.compress(content)
                            if len(res.compressed) < len(content):
                                msg["content"] = res.compressed
            elif "contents" in payload_dict:
                # Gemini format: compress text parts and functionResponse content fields directly to preserve structure
                for content in payload_dict["contents"]:
                    parts = content.get("parts", [])
                    for part in parts:
                        if isinstance(part, dict):
                            if "text" in part:
                                text = part["text"]
                                if isinstance(text, str) and len(text) > 500:
                                    res = router.compress(text)
                                    if len(res.compressed) < len(text):
                                        part["text"] = res.compressed
                            elif "functionResponse" in part:
                                func_resp = part["functionResponse"]
                                if (
                                    isinstance(func_resp, dict)
                                    and "response" in func_resp
                                ):
                                    resp = func_resp["response"]
                                    if isinstance(resp, dict) and "content" in resp:
                                        tool_content = resp["content"]
                                        if (
                                            isinstance(tool_content, str)
                                            and len(tool_content) > 500
                                        ):
                                            res = router.compress(tool_content)
                                            if len(res.compressed) < len(tool_content):
                                                resp["content"] = res.compressed
        except Exception as e:
            import traceback

            logger.error(
                f"Error in headroom compression: {e}\n{traceback.format_exc()}"
            )

    # Stage 3: After headroom compression (final)
    final_bytes, final_tokens = get_metrics(payload_dict)

    # Calculate savings percentages
    saved_bytes = orig_bytes - final_bytes
    pct_bytes = (saved_bytes / orig_bytes) * 100 if orig_bytes > 0 else 0.0

    saved_tokens = orig_tokens - final_tokens
    pct_tokens = (saved_tokens / orig_tokens) * 100 if orig_tokens > 0 else 0.0

    # Log the detailed statistics
    logger.info(
        f"[Compactor] Input {orig_bytes / 1024:.1f}KB ({orig_tokens:,} tok) -> Final {final_bytes / 1024:.1f}KB ({final_tokens:,} tok) | Saved {saved_bytes / 1024:.1f}KB (-{pct_bytes:.1f}%) | {saved_tokens:,} tok (-{pct_tokens:.1f}%)"
    )

    # Update state variables
    state.COMPACTOR_ORIG_BYTES = getattr(state, "COMPACTOR_ORIG_BYTES", 0) + orig_bytes
    state.COMPACTOR_COMP_BYTES = getattr(state, "COMPACTOR_COMP_BYTES", 0) + final_bytes
    state.COMPACTOR_ORIG_TOKENS = (
        getattr(state, "COMPACTOR_ORIG_TOKENS", 0) + orig_tokens
    )
    state.COMPACTOR_COMP_TOKENS = (
        getattr(state, "COMPACTOR_COMP_TOKENS", 0) + final_tokens
    )

    # Split merged functionCall+text parts (SDK serialization bug workaround).
    # Runs unconditionally: it only repairs invalid payloads and is independent
    # of the compactor_strip_thoughts checkbox.
    payload_dict = split_merged_parts_in_contents(payload_dict)

    if config.get("compactor_strip_thoughts", False):
        payload_dict = strip_historical_thoughts_from_contents(payload_dict)
    payload_dict = normalize_thinking_config(payload_dict)
    payload_dict = normalize_gemini_thinking_temperature(payload_dict)

    return payload_dict
