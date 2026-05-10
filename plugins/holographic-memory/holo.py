#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy"]
# ///
"""
Holographic memory CLI for Claude Code hooks.

Commands:
  startup  — initialize DB, print memory summary (SessionStart hook)
  inject   — read {prompt} from stdin JSON, print relevant facts (UserPromptSubmit hook)
  collect  — read {transcript_path, session_id} from stdin JSON, extract + store facts (Stop hook)
"""

import json
import re
import sys
from pathlib import Path

SELF_DIR = Path(__file__).parent
sys.path.insert(0, str(SELF_DIR))

DB_PATH = Path.home() / ".claude" / "holographic-memory" / "memory.db"
WATERMARK_DIR = Path.home() / ".claude" / "holographic-memory" / "watermarks"


def _get_store():
    from store import MemoryStore
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return MemoryStore(db_path=DB_PATH)


# ---------------------------------------------------------------------------
# startup — SessionStart hook
# ---------------------------------------------------------------------------

def cmd_startup():
    try:
        store = _get_store()
    except Exception as e:
        print(f"Holographic memory: init failed ({e})", file=sys.stderr)
        return

    try:
        count = store._conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
        import holographic as hrr
        hrr_status = "HRR+FTS5" if hrr._HAS_NUMPY else "FTS5 only (install numpy for HRR)"

        if count == 0:
            print(
                f"Holographic memory active ({hrr_status}). "
                "No facts stored yet — memories will be collected automatically."
            )
        else:
            cats = store._conn.execute(
                "SELECT category, COUNT(*) as n FROM facts GROUP BY category ORDER BY n DESC LIMIT 5"
            ).fetchall()
            cat_str = ", ".join(f"{r[0]}:{r[1]}" for r in cats)
            print(
                f"Holographic memory: {count} facts ({cat_str}) | {hrr_status}. "
                "Relevant facts injected with each message."
            )
    finally:
        store.close()


# ---------------------------------------------------------------------------
# inject — UserPromptSubmit hook
# ---------------------------------------------------------------------------

def cmd_inject():
    if not DB_PATH.exists():
        return

    try:
        data = json.load(sys.stdin)
        prompt = (data.get("prompt") or "").strip()
    except Exception:
        return

    if not prompt or len(prompt) < 3:
        return

    try:
        from store import MemoryStore
        from retrieval import FactRetriever
        store = MemoryStore(db_path=DB_PATH)
    except Exception:
        return

    try:
        retriever = FactRetriever(store)
        results = retriever.search(prompt, min_trust=0.3, limit=6)

        if not results:
            return

        lines = ["## Memory"]
        for r in results:
            trust = r.get("trust_score", 0.5)
            content = r.get("content", "")
            cat = r.get("category", "general")
            cat_tag = f"[{cat}] " if cat != "general" else ""
            lines.append(f"- [{trust:.1f}] {cat_tag}{content}")

        n = len(results)
        print(f"🧠 {n} {'memory' if n == 1 else 'memories'} retrieved", file=sys.stderr)
        print("\n".join(lines))
    finally:
        store.close()


# ---------------------------------------------------------------------------
# collect — Stop hook
# ---------------------------------------------------------------------------

_MIN_FACT_LENGTH = 20
_MAX_FACT_LENGTH = 400

_EXTRACT_SYSTEM = """\
You extract durable facts from Claude Code sessions that are worth remembering in future sessions.

Return a JSON array (only the array, no other text):
[{"content": "...", "category": "user_pref|project|general"}]

Categories:
- user_pref: preferences, tools, languages, style, corrections to Claude's behavior
- project: tech stack, architecture decisions, project-specific context
- general: important facts about the user or their work that don't fit above

Rules:
- Only include facts a future Claude session should know
- Write facts as complete, self-contained sentences
- Skip conversational filler, greetings, questions with obvious answers
- Skip facts derivable just by reading the codebase
- Max 10 facts per session
- Return [] if nothing is worth persisting\
"""


def _extract_with_claude(messages: list[dict]) -> list[tuple[str, str]]:
    """Call the `claude` CLI to extract memorable facts. Returns [(content, category)].

    Uses stdin piping so no API key configuration is needed — claude's own
    auth (already set up for Claude Code) handles it.
    """
    import shutil
    import subprocess

    if not shutil.which("claude"):
        return []

    lines = []
    for msg in messages[-30:]:
        role = msg["role"].upper()
        content = msg["content"][:600].replace("\n", " ")
        lines.append(f"{role}: {content}")
    conversation = "\n".join(lines)

    prompt = _EXTRACT_SYSTEM + "\n\nConversation to analyze:\n" + conversation

    try:
        result = subprocess.run(
            ["claude", "--output-format", "text", "--model", "claude-haiku-4-5-20251001"],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return []
        text = result.stdout.strip()
        match = re.search(r'\[.*\]', text, re.DOTALL)
        if not match:
            return []
        facts = json.loads(match.group())
        return [
            (f["content"].strip()[:_MAX_FACT_LENGTH], f.get("category", "general"))
            for f in facts
            if isinstance(f, dict) and f.get("content", "").strip()
        ]
    except Exception:
        return []


# Regex fallback — used when ANTHROPIC_API_KEY is absent or API call fails
_REGEX_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r'\bremember\s+(?:that\s+)?.{10,200}', re.I), "general"),
    (re.compile(r'\bnote\s+(?:that\s+)?.{10,200}', re.I), "general"),
    (re.compile(r'\bI(?:\'m| am)\s+(?:a|an)\s+\w.{5,80}', re.I), "user_pref"),
    (re.compile(r'\bmy name is\s+\w.{2,40}', re.I), "user_pref"),
    (re.compile(r'\bI work (?:at|for|with|on)\s+\w.{3,80}', re.I), "user_pref"),
    (re.compile(r'\bI\s+(?:prefer|like|love|use|hate|always use|never use)\s+\w.{5,120}', re.I), "user_pref"),
    (re.compile(r'\bI\s+(?:always|never|usually|typically)\s+\w.{5,100}', re.I), "user_pref"),
    (re.compile(r'\bplease\s+(?:always|never|don\'t|do)\s+\w.{5,100}', re.I), "user_pref"),
    (re.compile(r'\bwe\s+(?:decided|agreed|chose|are using|switched to|will use)\s+\w.{5,100}', re.I), "project"),
    (re.compile(r'\bwe\'re\s+(?:using|building|working on|migrating to)\s+\w.{5,100}', re.I), "project"),
    (re.compile(r'\bthis\s+(?:project|repo|app|service|codebase)\s+(?:uses?|needs?|is built with)\s+\w.{5,80}', re.I), "project"),
    (re.compile(r'\bour\s+(?:stack|setup|architecture|framework)\s+(?:is|uses?)\s+\w.{5,80}', re.I), "project"),
    (re.compile(r'\bdon\'t use\s+\w.{3,60}[,;]\s+(?:use|try)\s+\w.{3,60}', re.I), "user_pref"),
]

_ASSISTANT_REGEX_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r'\bI\'ll (?:remember|note|keep in mind)\s+(?:that\s+)?\w.{10,200}', re.I), "general"),
]


def _extract_with_regex(messages: list[dict]) -> list[tuple[str, str]]:
    results: list[tuple[str, str]] = []
    seen: set[str] = set()

    def _add(text: str, category: str) -> None:
        text = text.strip()
        if len(text) < _MIN_FACT_LENGTH:
            return
        key = text.lower()[:100]
        if key not in seen:
            seen.add(key)
            results.append((text[:_MAX_FACT_LENGTH], category))

    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if not content or len(content) < _MIN_FACT_LENGTH:
            continue
        rules = _REGEX_RULES if role == "user" else _ASSISTANT_REGEX_RULES
        for pattern, category in rules:
            if pattern.search(content):
                _add(content, category)
                break

    return results


def _parse_transcript(path: str, start_line: int = 0) -> tuple[list[dict], int]:
    """Parse JSONL transcript from start_line. Returns (messages, total_line_count)."""
    messages: list[dict] = []
    total_lines = 0

    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for i, line in enumerate(f):
                total_lines = i + 1
                if i < start_line:
                    continue
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    # Claude Code transcript format: each line is a message or wrapped message
                    msg = entry.get("message", entry)
                    role = msg.get("role") or entry.get("role", "")

                    if role == "user":
                        content = msg.get("content", "")
                        if isinstance(content, list):
                            content = " ".join(
                                c.get("text", "") for c in content
                                if isinstance(c, dict) and c.get("type") == "text"
                            )
                        if isinstance(content, str) and content.strip():
                            messages.append({"role": "user", "content": content.strip()})

                    elif role == "assistant":
                        content_parts = msg.get("content", [])
                        if isinstance(content_parts, list):
                            text = " ".join(
                                p.get("text", "") for p in content_parts
                                if isinstance(p, dict) and p.get("type") == "text"
                            )
                        elif isinstance(content_parts, str):
                            text = content_parts
                        else:
                            text = ""
                        if text.strip():
                            messages.append({"role": "assistant", "content": text.strip()})

                except (json.JSONDecodeError, KeyError, TypeError):
                    continue
    except Exception:
        pass

    return messages, total_lines


def cmd_collect():
    try:
        data = json.load(sys.stdin)
        transcript_path = (data.get("transcript_path") or "").strip()
        session_id = (data.get("session_id") or "unknown").strip()
    except Exception:
        return

    if not transcript_path or not Path(transcript_path).exists():
        return

    # Load watermark — only process new lines since last run
    WATERMARK_DIR.mkdir(parents=True, exist_ok=True)
    safe_id = re.sub(r'[^a-zA-Z0-9_-]', '_', session_id)[:64]
    watermark_file = WATERMARK_DIR / f"{safe_id}.json"

    start_line = 0
    if watermark_file.exists():
        try:
            wm = json.loads(watermark_file.read_text())
            start_line = int(wm.get("last_line", 0))
        except Exception:
            start_line = 0

    messages, total_lines = _parse_transcript(transcript_path, start_line=start_line)

    if not messages:
        # Update watermark even if no messages (so we don't re-scan)
        watermark_file.write_text(json.dumps({"last_line": total_lines}))
        return

    facts_to_store = _extract_with_claude(messages) or _extract_with_regex(messages)

    saved = 0
    if facts_to_store:
        try:
            store = _get_store()
            try:
                for content, category in facts_to_store:
                    try:
                        store.add_fact(content, category=category)
                        saved += 1
                    except Exception:
                        pass
            finally:
                store.close()
        except Exception:
            pass

    if saved:
        print(f"💾 {saved} new {'fact' if saved == 1 else 'facts'} saved", file=sys.stderr)

    # Update watermark
    try:
        watermark_file.write_text(json.dumps({"last_line": total_lines}))
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "startup"

    if cmd == "startup":
        cmd_startup()
    elif cmd == "inject":
        cmd_inject()
    elif cmd == "collect":
        cmd_collect()
    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        sys.exit(1)
