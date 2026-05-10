#!/usr/bin/env bash
# UserPromptSubmit — search memory, inject relevant facts into context
# Reads {prompt, session_id} JSON from stdin; prints facts to stdout
exec python3 "${CLAUDE_PLUGIN_ROOT}/holo.py" inject 2>/dev/null
