#!/usr/bin/env python3
"""
Holographic memory CLI for Claude Code hooks.

Commands:
  startup  — initialize DB, print memory summary (SessionStart hook)
  inject   — read {prompt} from stdin JSON, print relevant facts (UserPromptSubmit hook)
  collect  — read {transcript_path, session_id} from stdin JSON, extract + store facts (Stop hook)
"""

import json
import os
import re
import sys
from pathlib import Path

SELF_DIR = Path(__file__).parent
sys.path.insert(0, str(SELF_DIR))

DB_PATH = Path.home() / ".claude" / "holographic-memory" / "memory.db"


def _get_store():
    from store import MemoryStore

    return MemoryStore(db_path=DB_PATH)


def _read_hook_input() -> dict:
    """Parse hook stdin JSON. Returns {} on failure."""
    try:
        return json.load(sys.stdin)
    except Exception:
        return {}


def _project_path(data: dict) -> str:
    """Resolve current project path from hook input or env. Returns realpath or ''."""
    cwd = data.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or ""
    if not cwd:
        return ""
    try:
        return os.path.realpath(cwd)
    except Exception:
        return cwd


# ---------------------------------------------------------------------------
# startup — SessionStart hook
# ---------------------------------------------------------------------------


def cmd_startup():
    data = _read_hook_input()
    project = _project_path(data)

    try:
        store = _get_store()
    except Exception as e:
        print(f"Holographic memory: init failed ({e})", file=sys.stderr)
        return

    try:
        count, cats = store.stats()
        if count == 0:
            print(
                "Holographic memory active. "
                "No facts stored yet — memories will be collected automatically."
            )
        else:
            cat_str = ", ".join(f"{cat}:{n}" for cat, n in cats)
            project_suffix = ""
            if project:
                project_count = store.project_count(project)
                if project_count:
                    project_suffix = f", {project_count} in this project"
            print(
                f"Holographic memory: {count} facts ({cat_str}{project_suffix}). "
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

    data = _read_hook_input()
    prompt = (data.get("prompt") or "").strip()
    project = _project_path(data)

    if len(prompt) < 3:
        return

    try:
        from retrieval import FactRetriever

        store = _get_store()
    except Exception:
        return

    try:
        retriever = FactRetriever(store)
        results = retriever.search(
            prompt, min_trust=0.3, limit=6, current_project=project
        )

        n = len(results)
        context_message = ""

        if results:
            lines = ["## Memory"]
            for r in results:
                trust = r.get("trust_score", 0.5)
                content = r.get("content", "")
                cat = r.get("category", "general")
                cat_tag = f"[{cat}] " if cat != "general" else ""
                lines.append(f"- [{trust:.1f}] {cat_tag}{content}")
            context_message = "\n".join(lines)

        output = {
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": context_message,
            },
            "systemMessage": f"🧠 {n} {'memory' if n == 1 else 'memories'} recalled",
        }
        json.dump(output, sys.stdout)
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
- project: tech stack, architecture decisions, project-specific context (durable, not "what happened today")
- general: important facts about the user or their work that don't fit above

DO NOT extract (these are noise, not memory):
- Activity logs / session summaries — "X was extracted", "Y was integrated", "Z was fixed", "we built/updated/refactored W".
  Anything answering "what happened in this session" belongs in git log, not memory.
- Status updates — "X is now complete", "Y now works", "Z has been added".
- Meta-facts about the memory system itself — how the collector works, what hooks do, retention rules.
- Restatements of things already obvious from the codebase or git history.
- One-shot debugging fixes, error resolutions, or temporary workarounds tied to today's work.
- Things the user said in passing that aren't standing preferences (e.g. "do X here" ≠ "always do X").

DO extract:
- Standing user preferences ("always use X", "never do Y", "I prefer Z").
- Durable project facts that won't change next week (long-lived architecture, stack choices, why a decision was made).
- Information about the user (role, expertise, responsibilities) useful across sessions.
- Corrections the user explicitly framed as durable rules.

Other rules:
- Write facts as complete, self-contained sentences. A future Claude reading the fact in isolation must understand it.
- Max 10 facts per session.
- When in doubt, omit. Return [] if nothing is worth persisting.\
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
            ["claude", "--output-format", "text", "--model", "claude-haiku-4-5"],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return []
        text = result.stdout.strip()
        match = re.search(r"\[.*\]", text, re.DOTALL)
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


# Regex fallback — used when claude CLI is unavailable
_REGEX_RULES: dict[str, list[tuple[re.Pattern, str]]] = {
    "user": [
        (re.compile(r"\bremember\s+(?:that\s+)?.{10,200}", re.I), "general"),
        (re.compile(r"\bnote\s+(?:that\s+)?.{10,200}", re.I), "general"),
        (re.compile(r"\bI(?:\'m| am)\s+(?:a|an)\s+\w.{5,80}", re.I), "user_pref"),
        (re.compile(r"\bmy name is\s+\w.{2,40}", re.I), "user_pref"),
        (re.compile(r"\bI work (?:at|for|with|on)\s+\w.{3,80}", re.I), "user_pref"),
        (
            re.compile(
                r"\bI\s+(?:prefer|like|love|use|hate|always use|never use)\s+\w.{5,120}",
                re.I,
            ),
            "user_pref",
        ),
        (
            re.compile(r"\bI\s+(?:always|never|usually|typically)\s+\w.{5,100}", re.I),
            "user_pref",
        ),
        (
            re.compile(r"\bplease\s+(?:always|never|don\'t|do)\s+\w.{5,100}", re.I),
            "user_pref",
        ),
        (
            re.compile(
                r"\bwe\s+(?:decided|agreed|chose|are using|switched to|will use)\s+\w.{5,100}",
                re.I,
            ),
            "project",
        ),
        (
            re.compile(
                r"\bwe\'re\s+(?:using|building|working on|migrating to)\s+\w.{5,100}",
                re.I,
            ),
            "project",
        ),
        (
            re.compile(
                r"\bthis\s+(?:project|repo|app|service|codebase)\s+(?:uses?|needs?|is built with)\s+\w.{5,80}",
                re.I,
            ),
            "project",
        ),
        (
            re.compile(
                r"\bour\s+(?:stack|setup|architecture|framework)\s+(?:is|uses?)\s+\w.{5,80}",
                re.I,
            ),
            "project",
        ),
        (
            re.compile(r"\bdon\'t use\s+\w.{3,60}[,;]\s+(?:use|try)\s+\w.{3,60}", re.I),
            "user_pref",
        ),
    ],
    "assistant": [
        (
            re.compile(
                r"\bI\'ll (?:remember|note|keep in mind)\s+(?:that\s+)?\w.{10,200}",
                re.I,
            ),
            "general",
        ),
    ],
}


def _extract_with_regex(messages: list[dict]) -> list[tuple[str, str]]:
    results: list[tuple[str, str]] = []
    seen: set[str] = set()

    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if not content or len(content) < _MIN_FACT_LENGTH:
            continue
        for pattern, category in _REGEX_RULES.get(role, []):
            if pattern.search(content):
                text = content.strip()
                key = text.lower()[:100]
                if key not in seen:
                    seen.add(key)
                    results.append((text[:_MAX_FACT_LENGTH], category))
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
                                c.get("text", "")
                                for c in content
                                if isinstance(c, dict) and c.get("type") == "text"
                            )
                        if isinstance(content, str) and content.strip():
                            messages.append(
                                {"role": "user", "content": content.strip()}
                            )

                    elif role == "assistant":
                        content_parts = msg.get("content", [])
                        if isinstance(content_parts, list):
                            text = " ".join(
                                p.get("text", "")
                                for p in content_parts
                                if isinstance(p, dict) and p.get("type") == "text"
                            )
                        elif isinstance(content_parts, str):
                            text = content_parts
                        else:
                            text = ""
                        if text.strip():
                            messages.append(
                                {"role": "assistant", "content": text.strip()}
                            )

                except (json.JSONDecodeError, KeyError, TypeError):
                    continue
    except Exception:
        pass

    return messages, total_lines


def cmd_collect():
    """SessionEnd / PreCompact hook: read stdin, hand off to a detached worker,
    return immediately.

    The worker runs the (potentially slow) claude CLI extraction in a new
    session so it survives this process exiting. Hook latency drops from
    seconds to milliseconds. Falls back to inline execution if spawn fails.
    """
    import subprocess

    try:
        raw = sys.stdin.buffer.read()
    except Exception:
        raw = b""
    if not raw:
        return

    try:
        json.loads(raw)
    except Exception:
        return

    try:
        proc = subprocess.Popen(
            [sys.executable, __file__, "_collect_worker"],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )
        assert proc.stdin is not None
        proc.stdin.write(raw)
        proc.stdin.close()
        return
    except Exception:
        pass

    try:
        _do_collect(json.loads(raw))
    except Exception:
        pass


def _do_collect(data: dict):
    """Extract facts from the full transcript. Fires on SessionEnd and PreCompact
    so the LLM sees complete context (not a per-turn delta). Dedup via HRR
    similarity in store.add_fact handles overlap between the two events."""
    transcript_path = (data.get("transcript_path") or "").strip()
    project = _project_path(data)

    if not transcript_path or not Path(transcript_path).exists():
        return

    messages, _ = _parse_transcript(transcript_path, start_line=0)
    if not messages:
        return

    facts_to_store = _extract_with_claude(messages) or _extract_with_regex(messages)

    saved = 0
    if facts_to_store:
        store = None
        try:
            store = _get_store()
            for content, category in facts_to_store:
                try:
                    store.add_fact(content, category=category, project_path=project)
                    saved += 1
                except Exception:
                    pass
        except Exception:
            pass
        finally:
            if store is not None:
                store.close()

    if saved:
        print(
            f"💾 {saved} new {'fact' if saved == 1 else 'facts'} saved", file=sys.stderr
        )


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
    elif cmd == "_collect_worker":
        try:
            _do_collect(_read_hook_input())
        except Exception:
            pass
    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        sys.exit(1)
