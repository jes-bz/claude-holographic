# Holographic Memory for Claude Code

Persistent cross-session memory using [Holographic Reduced Representations](https://en.wikipedia.org/wiki/Holographic_reduced_representation) (HRR) and SQLite. Facts are extracted from each session and injected as context in future ones.

## How it works

Three Claude Code hooks:

| Hook | When | What |
|------|------|------|
| `SessionStart` | Session opens | Initialize DB, print fact count |
| `UserPromptSubmit` | Every message | Search memory, inject relevant facts as context |
| `Stop` | After each response | Call `claude` CLI to extract memorable facts from the transcript |

Facts are stored in SQLite with FTS5 full-text search and optional HRR vector embeddings (when numpy is available) for semantic retrieval. The `claude` CLI handles extraction — no API key configuration needed.

## Install

### Via Claude Code plugin marketplace (recommended)

Add to `~/.claude/settings.json`:

```json
{
  "extraKnownMarketplaces": {
    "holographic-memory": {
      "source": {
        "source": "git",
        "url": "https://github.com/jes-bz/claude-holographic.git"
      }
    }
  }
}
```

Then install in Claude Code:
```
/install holographic-memory@holographic-memory
```

### Manual install

Requires [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/jes-bz/claude-holographic.git
cd claude-holographic
bash install.sh
```

## Storage

- **DB**: `~/.claude/holographic-memory/memory.db` (SQLite, WAL mode)
- **Watermarks**: `~/.claude/holographic-memory/watermarks/` (tracks processed transcript lines per session)
- **Plugin cache** (marketplace install): `~/.claude/plugins/cache/holographic-memory/`

## Retrieval

Search uses a hybrid pipeline:
1. **FTS5** — SQLite full-text search, fast keyword matching
2. **Jaccard similarity** — token overlap reranking  
3. **HRR vectors** — phase-encoded semantic similarity (requires numpy, auto-installed by uv)

Facts have trust scores (0–1) that adjust with use. Higher-trust facts rank higher in retrieval.

## Requirements

- [uv](https://docs.astral.sh/uv/) — for Python 3.11+ and numpy auto-install
- `claude` CLI — for smart fact extraction (comes with Claude Code)

## Architecture

Ported from [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent/tree/main/plugins/memory/holographic) with Claude Code hook integration replacing the Hermes plugin system.
