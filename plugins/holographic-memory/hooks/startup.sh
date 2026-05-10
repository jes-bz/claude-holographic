#!/usr/bin/env bash
# SessionStart — initialize DB, print memory summary
exec uv run "${CLAUDE_PLUGIN_ROOT}/holo.py" startup 2>/dev/null
