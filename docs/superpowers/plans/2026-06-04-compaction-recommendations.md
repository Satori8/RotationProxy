# Context Compactor & Optimization Recommendations

## 1. Analysis of Prominent Duplicate Blocks

Our analysis of the massive 31MB log file `chat_log_2026-06-04.txt` revealed a staggering **808,429 wasted characters** across 1,181 requests.

### The Most Prominent Duplicate Block:
* **Count:** 140 times
* **Wasted Characters:** 630,921 characters (representing **78% of all wasted space**!)
* **Snippet:**
  ```html
  <EXTREMELY_IMPORTANT>
  You have superpowers.
  
  **IMPORTANT: The using-superpowers skill content is included below. It is ALREADY LOADED - you are currently following it. Do NOT use the skill tool to load "using-superpowers" again - that would be redundant.**
  ...
  ```

### Origin & Impact:
This block is injected by OpenCode's system prompt or the `using-superpowers` skill content at the start of every message turn. Because the context window accumulates previous turns, this massive block is repeated in every single message of the conversation history, bloating the input context and costing thousands of tokens per turn.

---

## 2. Context Compaction Recommendations

To achieve maximum context compaction, we recommend a two-pronged approach: OpenCode configuration tuning and Proxy Compactor enhancements.

### A. OpenCode Configuration Tuning (`opencode.json`)

1. **Enable Aggressive Turn Compaction:**
   Ensure the following settings are active in `opencode.json` under `"compaction"`:
   ```json
   "compaction": {
     "auto": true,
     "prune": true,
     "reserved": 8192,
     "tail_turns": 8,
     "preserve_recent_tokens": 12000
   }
   ```
   *Reducing `tail_turns` from 12 to 8 dramatically limits the history depth sent to the model, pruning old duplicate blocks.*

2. **Disable Unused MCP Servers:**
   Disable any unused local or remote MCP servers (e.g., `github`, `sqlite`, `playwright`, `a2asearch`) in `opencode.json` to keep the tool manifest small and save up to 5,000 tokens per turn.

---

### B. Proxy Compactor Improvements (`proxy_core/compactor.py`)

1. **Dynamic Deduplication of System Instructions:**
   Implement a dynamic deduplicator in `compactor.py` that parses the request body and strips duplicate system instructions or repetitive skill blocks from older messages in the `contents` array, leaving only the most recent one.

2. **Aggressive Tool Description Compaction:**
   Expand the `COMPACTED_TOOLS` static map in `compactor.py` to cover all newly added or active MCP servers, reducing their schema descriptions to the bare minimum required for correct model invocation.
