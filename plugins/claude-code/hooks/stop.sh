#!/usr/bin/env bash
# Stop hook: parse transcript, summarize with claude -p, and save to memory.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

# Debug logging — writes to .memsearch/stop-debug.log (stdout must remain clean JSON)
_LOG="$MEMSEARCH_DIR/stop-debug.log"
_dbg() { echo "[$(date '+%H:%M:%S')] $*" >> "$_LOG" 2>/dev/null || true; }
mkdir -p "$MEMSEARCH_DIR" 2>/dev/null || true
_dbg "--- stop.sh fired ---"
_dbg "INPUT=${INPUT:0:200}"

# Prevent infinite loop: if this Stop was triggered by a previous Stop hook, bail out
STOP_HOOK_ACTIVE=$(_json_val "$INPUT" "stop_hook_active" "false")
_dbg "stop_hook_active=$STOP_HOOK_ACTIVE"
if [ "$STOP_HOOK_ACTIVE" = "true" ]; then
  _dbg "EXIT: recursion guard"
  echo '{}'
  exit 0
fi

# Skip summarization when the required API key is missing — embedding/search
# would fail, and the session likely only contains the "key not set" warning.
_required_env_var() {
  case "$1" in
    openai) echo "OPENAI_API_KEY" ;;
    google) echo "GOOGLE_API_KEY" ;;
    voyage) echo "VOYAGE_API_KEY" ;;
    jina) echo "JINA_API_KEY" ;;
    mistral) echo "MISTRAL_API_KEY" ;;
    *) echo "" ;;  # onnx, ollama, local — no API key needed
  esac
}
_PROVIDER=$($MEMSEARCH_CMD config get embedding.provider 2>/dev/null || echo "onnx")
_REQ_KEY=$(_required_env_var "$_PROVIDER")
_dbg "provider=$_PROVIDER req_key=$_REQ_KEY"
if [ -n "$_REQ_KEY" ] && [ -z "${!_REQ_KEY:-}" ]; then
  # Env var not set — check if API key is configured in memsearch config file
  _CONFIG_API_KEY=""
  if [ -n "$MEMSEARCH_CMD" ]; then
    _CONFIG_API_KEY=$($MEMSEARCH_CMD config get embedding.api_key 2>/dev/null || echo "")
  fi
  if [ -z "$_CONFIG_API_KEY" ]; then
    _dbg "EXIT: missing API key for provider=$_PROVIDER"
    echo '{}'
    exit 0
  fi
fi

# Extract transcript path from hook input
TRANSCRIPT_PATH=$(_json_val "$INPUT" "transcript_path" "")
_dbg "transcript_path=$TRANSCRIPT_PATH"

if [ -z "$TRANSCRIPT_PATH" ] || [ ! -f "$TRANSCRIPT_PATH" ]; then
  _dbg "EXIT: transcript missing or not a file"
  echo '{}'
  exit 0
fi

# Check if transcript is empty (< 3 lines = no real content)
LINE_COUNT=$(wc -l < "$TRANSCRIPT_PATH" 2>/dev/null || echo "0")
_dbg "transcript_lines=$LINE_COUNT"
if [ "$LINE_COUNT" -lt 3 ]; then
  _dbg "EXIT: transcript too short ($LINE_COUNT lines)"
  echo '{}'
  exit 0
fi

ensure_memory_dir

# Parse transcript — extract the last turn only (one user question + all responses)
PARSED=$("$SCRIPT_DIR/parse-transcript.sh" "$TRANSCRIPT_PATH" 2>/dev/null || true)
_dbg "parse result (first 100): ${PARSED:0:100}"

if [ -z "$PARSED" ] || [ "$PARSED" = "(empty transcript)" ] || [ "$PARSED" = "(no user message found)" ] || [ "$PARSED" = "(empty turn)" ]; then
  _dbg "EXIT: parse returned empty/sentinel: '$PARSED'"
  echo '{}'
  exit 0
fi

# Determine today's date and current time
TODAY=$(date +%Y-%m-%d)
NOW=$(date +%H:%M)
MEMORY_FILE="$MEMORY_DIR/$TODAY.md"

# Extract session ID and last user turn UUID for progressive disclosure anchors
SESSION_ID=$(basename "$TRANSCRIPT_PATH" .jsonl)
_PYTHON=$(command -v py 2>/dev/null || command -v python3 2>/dev/null || command -v python 2>/dev/null || echo "")
LAST_USER_TURN_UUID=""
if [ -n "$_PYTHON" ]; then
  LAST_USER_TURN_UUID=$("$_PYTHON" -c "
import json, sys
uuid = ''
with open(sys.argv[1]) as f:
    for line in f:
        try:
            obj = json.loads(line)
            if obj.get('type') == 'user' and isinstance(obj.get('message', {}).get('content'), str):
                uuid = obj.get('uuid', '')
        except: pass
print(uuid)
" "$TRANSCRIPT_PATH" 2>/dev/null || true)
fi

# Load summarization prompt: user custom (via config) > plugin built-in template
AGENT_NAME="Claude Code"
PROMPT_FILE=""
if [ -n "$MEMSEARCH_CMD" ]; then
  PROMPT_FILE=$($MEMSEARCH_CMD config get prompts.summarize 2>/dev/null || true)
fi
if [ -n "$PROMPT_FILE" ] && [ -f "$PROMPT_FILE" ]; then
  SYSTEM_PROMPT=$(sed "s/{{AGENT_NAME}}/$AGENT_NAME/g" "$PROMPT_FILE")
elif [ -f "${CLAUDE_PLUGIN_ROOT}/prompts/summarize.txt" ]; then
  SYSTEM_PROMPT=$(sed "s/{{AGENT_NAME}}/$AGENT_NAME/g" "${CLAUDE_PLUGIN_ROOT}/prompts/summarize.txt")
else
  SYSTEM_PROMPT="You are a third-person note-taker. Summarize the transcript as 2-6 bullet points. Write in third person. Output ONLY bullet points."
fi

# Summarize the last turn into structured bullet points.
# Default: use claude -p (plugin's own agent). If [llm] is configured, still
# use claude -p since it's the most reliable path for Claude Code plugin.
SUMMARY=""
_dbg "claude available: $(command -v claude 2>/dev/null || echo 'NOT FOUND')"
if command -v claude &>/dev/null; then
  SUMMARY=$(printf '%s' "$PARSED" | MEMSEARCH_NO_WATCH=1 CLAUDECODE= claude -p \
    --model haiku \
    --no-session-persistence \
    --no-chrome \
    --system-prompt "$SYSTEM_PROMPT" \
    2>/dev/null || true)
  _dbg "claude summary (first 100): ${SUMMARY:0:100}"
fi

# If claude is not available or returned empty, fall back to raw parsed output
if [ -z "$SUMMARY" ]; then
  _dbg "summary empty — using raw parsed output"
  SUMMARY="$PARSED"
fi

# Append as a sub-heading under the session heading written by SessionStart
# Include HTML comment anchor for progressive disclosure (L3 transcript lookup)
{
  echo "### $NOW"
  if [ -n "$SESSION_ID" ]; then
    echo "<!-- session:${SESSION_ID} turn:${LAST_USER_TURN_UUID} transcript:${TRANSCRIPT_PATH} -->"
  fi
  echo "$SUMMARY"
  echo ""
} >> "$MEMORY_FILE"
_dbg "appended to $MEMORY_FILE"

# Kill any previous background index before re-indexing to avoid process accumulation
kill_orphaned_index

# Index immediately — don't rely on watch (which may be killed by SessionEnd before debounce fires)
_dbg "running memsearch index"
run_memsearch index "$MEMORY_DIR"
_dbg "done"

echo '{}'
