#!/usr/bin/env bash
# UserPromptSubmit hook: lightweight hint reminding Claude about the memory-recall skill.
# The actual search + expand is handled by the memory-recall skill (pull-based, context: fork).

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

# Date-rollover guard: create today's memory file + heading if it doesn't exist yet.
# Catches resumed sessions and sessions that span midnight — SessionStart only fires
# once per new session, so this is the only reliable per-turn fallback.
ensure_memory_dir
TODAY=$(date +%Y-%m-%d)
NOW=$(date +%H:%M)
MEMORY_FILE="$MEMORY_DIR/$TODAY.md"
if [ ! -f "$MEMORY_FILE" ] || ! grep -qF "## Session" "$MEMORY_FILE"; then
  echo -e "\n## Session $NOW (resumed)\n" >> "$MEMORY_FILE"
fi

# Skip short prompts (greetings, single words, etc.)
PROMPT=$(_json_val "$INPUT" "prompt" "")
if [ -z "$PROMPT" ] || [ "${#PROMPT}" -lt 10 ]; then
  echo '{}'
  exit 0
fi

# Need memsearch available
if [ -z "$MEMSEARCH_CMD" ]; then
  echo '{}'
  exit 0
fi

echo '{"systemMessage": "[memsearch] Memory available"}'
