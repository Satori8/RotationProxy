# Context Compactor Analysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Analyze the massive chat log, extract tool call statistics, identify duplicate blocks with their starting fragments, and compile a report on context compaction methods.

**Architecture:** A Python script `analyze_logs.py` that parses the chat logs, filters out conversational text while keeping metadata, system prompts, and tool calls/responses, calculates tool usage statistics, and detects duplicate blocks with detailed fragments and sources.

**Tech Stack:** Python 3.12, standard libraries (`json`, `re`, `collections`, `os`).

---

### Task 1: Create the Log Filtering and Tool Statistics Script

**Files:**
- Create: `d:\Work\Active\GeminiProxy\analyze_logs.py`

- [ ] **Step 1: Implement log parsing, filtering, and tool statistics calculation**
  Write a script that:
  1. Reads the log file (which contains JSON payloads or raw text).
  2. Extracts system prompts, tool declarations, tool calls, and tool responses.
  3. Filters out conversational parts (user messages and assistant chat text) to keep only headers/tails and protocol metadata.
  4. Calculates tool statistics: call count, total characters, average characters.
  5. Saves the filtered log to `filtered_chat_log.txt`.

- [ ] **Step 2: Add enhanced duplicate detection**
  Enhance the duplicate detection logic (inspired by `analyze_duplicates.py`) to:
  1. Find duplicate blocks (>100 characters) in the filtered content.
  2. Count the number of duplicate blocks.
  3. Extract the first 150 characters of each duplicate block as a snippet.
  4. Report the exact wasted characters and sources for each duplicate block.

- [ ] **Step 3: Add command-line interface**
  Add a CLI to accept the input log file path and output report path.

---

### Task 2: Run the Analysis on the Recent Log File

**Files:**
- Modify: `d:\Work\Active\GeminiProxy\analyze_logs.py` (to run)
- Create: `d:\Work\Active\GeminiProxy\context_analysis_report.txt`

- [ ] **Step 1: Execute the script on `chat_log_2026-06-04.txt`**
  Run the script on the massive 31MB log file:
  `python d:\Work\Active\GeminiProxy\analyze_logs.py --input d:\Work\Active\GeminiProxy\chat_logs\chat_log_2026-06-04.txt --output d:\Work\Active\GeminiProxy\context_analysis_report.txt`

- [ ] **Step 2: Verify the generated report and filtered log**
  Check that `context_analysis_report.txt` contains detailed tool statistics and duplicate block details (with count, wasted characters, and starting fragments).

---

### Task 3: Analyze Duplicates and Compile Compaction Recommendations

**Files:**
- Create: `d:\Work\Active\GeminiProxy\docs\superpowers\plans\2026-06-04-compaction-recommendations.md`

- [ ] **Step 1: Analyze one prominent duplicate block**
  Identify a major duplicate block from the report and analyze its origin, frequency, and impact.

- [ ] **Step 2: Compile context compaction recommendations**
  Write a comprehensive report detailing:
  1. OpenCode configuration methods (adjusting compaction settings, pruning, etc.).
  2. Proxy compactor improvements (more compactors, dynamic truncation, etc.).
