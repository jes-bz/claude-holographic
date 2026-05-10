#!/usr/bin/env bash
# Stop — extract memorable facts from the completed session turn
# Reads {transcript_path, session_id} JSON from stdin; side-effects only
exec python3 "${CLAUDE_PLUGIN_ROOT}/holo.py" collect 2>/dev/null
