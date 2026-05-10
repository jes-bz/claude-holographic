#!/usr/bin/env bash
# SessionStart — initialize DB, print memory summary
exec python3 "${CLAUDE_PLUGIN_ROOT}/holo.py" startup 2>/dev/null
