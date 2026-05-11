#!/usr/bin/env python3
"""Single-file SPA to manage holographic-memory facts.

Run:  python webui.py [--port 8765] [--host 127.0.0.1]
Then open http://127.0.0.1:8765
"""

from __future__ import annotations

import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

SELF_DIR = Path(__file__).parent
sys.path.insert(0, str(SELF_DIR))

from store import MemoryStore  # noqa: E402

DB_PATH = Path.home() / ".claude" / "holographic-memory" / "memory.db"

INDEX_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Holographic Memory</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;700&family=Space+Grotesk:wght@300;500;700&display=swap" rel="stylesheet">
<style>
  /* catthode — CRT/OLED warm retro-futuristic theme */
  :root {
    --bg:      #000000;  /* base */
    --panel:   #141414;  /* sidebar */
    --panel2:  #2d2d2d;  /* selection */
    --border:  #636363;
    --text:    #ffffff;  /* phosphor */
    --text2:   #e8e8e8;  /* variable */
    --muted:   #b3b3b3;  /* comment */
    --dim:     #757575;  /* ignored */
    --wheat:   #fae2c8;
    --tan:     #d9b98c;
    --gold:    #ffb86c;
    --amber:   #ff9e3b;  /* primary action */
    --clay:    #f08d49;
    --red:     #ff6b6b;
    --green:   #b9d665;
    --cyan:    #aee6d6;
    --blue:    #9cd9e6;
    --purple:  #eba4be;
    --mono:    "JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, monospace;
    --sans:    "Space Grotesk", -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
  }
  * { box-sizing: border-box; }
  html, body { margin: 0; height: 100%; background: var(--bg); color: var(--text);
    font-family: var(--sans); font-weight: 300; }
  header { padding: 14px 20px; border-bottom: 1px solid var(--border);
    display: flex; align-items: center; gap: 16px; background: var(--panel); }
  header h1 { font-size: 16px; font-weight: 700; margin: 0; letter-spacing: 0.02em;
    color: var(--amber); text-shadow: 0 0 8px rgba(255,158,59,0.4); }
  header .stats { color: var(--muted); font-size: 13px; font-family: var(--mono); }
  main { display: grid; grid-template-columns: 320px 1fr; height: calc(100vh - 51px); }
  aside { border-right: 1px solid var(--border); padding: 16px; background: var(--panel);
    overflow-y: auto; display: flex; flex-direction: column; gap: 14px; }
  section.list { overflow-y: auto; padding: 8px 16px 60px; }
  label { font-size: 11px; color: var(--muted); display: block; margin-bottom: 4px;
    text-transform: uppercase; letter-spacing: 0.08em; }
  input, select, textarea, button {
    font: inherit; color: var(--text);
    background: var(--bg); border: 1px solid var(--border);
    border-radius: 4px; padding: 8px 10px; width: 100%;
  }
  input, select, textarea { font-family: var(--mono); font-size: 13px; }
  input:focus, select:focus, textarea:focus {
    outline: none; border-color: var(--amber);
    box-shadow: 0 0 0 1px var(--amber), 0 0 12px rgba(255,158,59,0.25);
  }
  textarea { resize: vertical; min-height: 70px; }
  button { cursor: pointer; width: auto; background: var(--amber); color: #1a0d00;
    border: 1px solid var(--amber); font-weight: 700; font-family: var(--sans);
    letter-spacing: 0.02em; text-transform: uppercase; font-size: 12px;
    box-shadow: 0 0 12px rgba(255,158,59,0.25); transition: 0.15s; }
  button:hover { background: var(--gold); border-color: var(--gold);
    box-shadow: 0 0 18px rgba(255,184,108,0.5); }
  button.ghost { background: transparent; color: var(--text2); border: 1px solid var(--border);
    box-shadow: none; }
  button.ghost:hover { background: var(--panel2); border-color: var(--tan); color: var(--wheat);
    box-shadow: 0 0 8px rgba(217,185,140,0.2); }
  button.danger { background: var(--red); color: #1a0404; border-color: var(--red);
    box-shadow: 0 0 12px rgba(255,107,107,0.3); }
  button.danger:hover { background: #ff8585; border-color: #ff8585; }
  .row { display: flex; gap: 8px; }
  .row > * { flex: 1; }
  .fact { background: var(--panel); border: 1px solid var(--border);
    border-radius: 4px; padding: 12px 14px; margin-bottom: 10px;
    transition: border-color 0.15s, box-shadow 0.15s; }
  .fact:hover { border-color: var(--tan); box-shadow: 0 0 14px rgba(217,185,140,0.12); }
  .fact header { padding: 0; border: 0; background: transparent; gap: 8px;
    display: flex; flex-wrap: wrap; align-items: center; margin-bottom: 6px; }
  .fact .content { font-size: 14px; line-height: 1.5; white-space: pre-wrap;
    word-break: break-word; color: var(--text2); }
  .fact .tags { color: var(--muted); font-size: 12px; margin-top: 6px; font-family: var(--mono); }
  .pill { font-size: 10px; padding: 2px 8px; border-radius: 999px;
    background: var(--bg); border: 1px solid var(--border); color: var(--muted);
    font-family: var(--mono); text-transform: uppercase; letter-spacing: 0.06em; }
  .pill.cat { background: rgba(255,158,59,0.10); color: var(--amber);
    border-color: rgba(255,158,59,0.45); text-shadow: 0 0 6px rgba(255,158,59,0.3); }
  .pill.trust-hi { background: rgba(185,214,101,0.10); color: var(--green);
    border-color: rgba(185,214,101,0.4); }
  .pill.trust-md { background: rgba(255,184,108,0.10); color: var(--gold);
    border-color: rgba(255,184,108,0.4); }
  .pill.trust-lo { background: rgba(255,107,107,0.10); color: var(--red);
    border-color: rgba(255,107,107,0.4); }
  .actions { display: flex; gap: 6px; margin-top: 10px; flex-wrap: wrap; }
  .actions button { padding: 4px 10px; font-size: 11px; font-weight: 500; }
  .empty { color: var(--dim); text-align: center; padding: 40px 20px;
    font-family: var(--mono); }
  .edit-form { display: none; flex-direction: column; gap: 8px; margin-top: 10px;
    padding-top: 10px; border-top: 1px solid var(--border); }
  .edit-form.open { display: flex; }
  .id { color: var(--dim); font-size: 11px; font-family: var(--mono); margin-left: auto; }
  .toast { position: fixed; bottom: 20px; right: 20px; background: var(--panel);
    border: 1px solid var(--amber); padding: 10px 14px; border-radius: 4px;
    font-size: 13px; font-family: var(--mono); color: var(--gold);
    box-shadow: 0 0 18px rgba(255,158,59,0.35); opacity: 0;
    transform: translateY(10px); transition: 0.2s; pointer-events: none; z-index: 200; }
  .toast.show { opacity: 1; transform: translateY(0); }
  .toast.err { border-color: var(--red); color: var(--red);
    box-shadow: 0 0 18px rgba(255,107,107,0.35); }
  h2 { font-size: 11px; font-weight: 700; text-transform: uppercase;
    letter-spacing: 0.12em; color: var(--tan); margin: 0 0 8px;
    font-family: var(--sans); }
  hr { border: none; border-top: 1px solid var(--border); }
  .meta { color: var(--dim); font-size: 11px; margin-top: 4px; font-family: var(--mono); }
  /* selection */
  ::selection { background: var(--amber); color: #1a0d00; }
  /* scrollbar */
  ::-webkit-scrollbar { width: 10px; height: 10px; }
  ::-webkit-scrollbar-track { background: var(--bg); }
  ::-webkit-scrollbar-thumb { background: var(--panel2); border-radius: 4px;
    border: 2px solid var(--bg); }
  ::-webkit-scrollbar-thumb:hover { background: var(--tan); }
</style>
</head>
<body>
<header>
  <h1>🧠 Holographic Memory</h1>
  <span class="stats" id="stats">loading…</span>
</header>
<main>
  <aside>
    <div>
      <h2>Search / Filter</h2>
      <input id="q" placeholder="search facts (FTS5)" autofocus>
    </div>
    <div class="row">
      <div>
        <label>Category</label>
        <select id="filterCat">
          <option value="">all</option>
          <option value="user_pref">user_pref</option>
          <option value="project">project</option>
          <option value="general">general</option>
        </select>
      </div>
      <div>
        <label>Min trust</label>
        <input id="minTrust" type="number" min="0" max="1" step="0.1" value="0">
      </div>
    </div>
    <div>
      <label>Limit</label>
      <input id="limit" type="number" min="1" max="500" value="100">
    </div>
    <button id="refresh">Refresh</button>

    <hr style="border-color:var(--border); width:100%;">

    <div>
      <h2>Add new fact</h2>
      <textarea id="newContent" placeholder="durable fact about user, project, etc."></textarea>
      <div class="row" style="margin-top:6px">
        <select id="newCat">
          <option value="general">general</option>
          <option value="user_pref">user_pref</option>
          <option value="project">project</option>
        </select>
        <input id="newTags" placeholder="tags (comma-sep)">
      </div>
      <button id="addBtn" style="margin-top:8px; width:100%;">Add fact</button>
    </div>
  </aside>

  <section class="list" id="list">
    <div class="empty">loading…</div>
  </section>
</main>
<div id="toast" class="toast"></div>

<script>
const $ = (id) => document.getElementById(id);
const list = $('list');
const stats = $('stats');
const toast = $('toast');

let timer = null;
const debounce = (fn, ms=250) => () => { clearTimeout(timer); timer = setTimeout(fn, ms); };

function showToast(msg, isErr=false) {
  toast.textContent = msg;
  toast.className = 'toast show' + (isErr ? ' err' : '');
  setTimeout(() => toast.className = 'toast', 1800);
}

function trustClass(t) {
  if (t >= 0.7) return 'trust-hi';
  if (t >= 0.4) return 'trust-md';
  return 'trust-lo';
}

function escapeHTML(s) {
  return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

function factHTML(f) {
  const t = f.trust_score ?? 0.5;
  return `
    <div class="fact" data-id="${f.fact_id}">
      <header>
        <span class="pill cat">${escapeHTML(f.category)}</span>
        <span class="pill ${trustClass(t)}">trust ${t.toFixed(2)}</span>
        <span class="pill">recalls ${f.retrieval_count ?? 0}</span>
        <span class="pill">helpful ${f.helpful_count ?? 0}</span>
        <span class="id">#${f.fact_id}</span>
      </header>
      <div class="content">${escapeHTML(f.content)}</div>
      ${f.tags ? `<div class="tags">tags: ${escapeHTML(f.tags)}</div>` : ''}
      <div class="meta">created ${f.created_at ?? '?'} · updated ${f.updated_at ?? '?'}</div>
      <div class="actions">
        <button class="ghost" data-act="edit">Edit</button>
        <button class="ghost" data-act="up">👍 helpful</button>
        <button class="ghost" data-act="down">👎 not</button>
        <button class="danger" data-act="del">Delete</button>
      </div>
      <div class="edit-form">
        <textarea data-f="content">${escapeHTML(f.content)}</textarea>
        <div class="row">
          <select data-f="category">
            <option ${f.category==='general'?'selected':''}>general</option>
            <option ${f.category==='user_pref'?'selected':''}>user_pref</option>
            <option ${f.category==='project'?'selected':''}>project</option>
          </select>
          <input data-f="tags" value="${escapeHTML(f.tags || '')}" placeholder="tags">
        </div>
        <div class="row">
          <button data-act="save">Save</button>
          <button class="ghost" data-act="cancel">Cancel</button>
        </div>
      </div>
    </div>
  `;
}

async function api(path, opts={}) {
  const r = await fetch(path, { headers: {'Content-Type':'application/json'}, ...opts });
  const data = await r.json().catch(()=>({}));
  if (!r.ok) throw new Error(data.error || r.statusText);
  return data;
}

async function loadStats() {
  try {
    const s = await api('/api/stats');
    const cats = (s.categories || []).map(([c,n]) => `${c}:${n}`).join(', ');
    stats.textContent = `${s.total} facts ${cats ? '('+cats+')' : ''}`;
  } catch (e) { stats.textContent = 'stats error'; }
}

async function loadList() {
  const q = $('q').value.trim();
  const cat = $('filterCat').value;
  const minTrust = $('minTrust').value || 0;
  const limit = $('limit').value || 100;

  let url;
  if (q) {
    const p = new URLSearchParams({ q, min_trust: minTrust, limit });
    if (cat) p.set('category', cat);
    url = '/api/search?' + p;
  } else {
    const p = new URLSearchParams({ min_trust: minTrust, limit });
    if (cat) p.set('category', cat);
    url = '/api/facts?' + p;
  }

  try {
    const { facts } = await api(url);
    if (!facts.length) {
      list.innerHTML = '<div class="empty">no facts found</div>';
    } else {
      list.innerHTML = facts.map(factHTML).join('');
    }
  } catch (e) {
    list.innerHTML = `<div class="empty">error: ${escapeHTML(e.message)}</div>`;
  }
}

list.addEventListener('click', async (e) => {
  const btn = e.target.closest('button[data-act]');
  if (!btn) return;
  const card = btn.closest('.fact');
  const id = card.dataset.id;
  const act = btn.dataset.act;

  try {
    if (act === 'edit') {
      card.querySelector('.edit-form').classList.add('open');
    } else if (act === 'cancel') {
      card.querySelector('.edit-form').classList.remove('open');
    } else if (act === 'save') {
      const form = card.querySelector('.edit-form');
      const body = {
        content: form.querySelector('[data-f=content]').value,
        category: form.querySelector('[data-f=category]').value,
        tags: form.querySelector('[data-f=tags]').value,
      };
      await api('/api/facts/' + id, { method: 'PUT', body: JSON.stringify(body) });
      showToast('saved');
      loadList();
    } else if (act === 'del') {
      if (!confirm('Delete fact #' + id + '?')) return;
      await api('/api/facts/' + id, { method: 'DELETE' });
      showToast('deleted');
      card.remove();
      loadStats();
    } else if (act === 'up' || act === 'down') {
      await api('/api/facts/' + id + '/feedback',
        { method: 'POST', body: JSON.stringify({ helpful: act === 'up' }) });
      showToast(act === 'up' ? 'marked helpful' : 'marked unhelpful');
      loadList();
    }
  } catch (err) { showToast(err.message, true); }
});

$('addBtn').addEventListener('click', async () => {
  const content = $('newContent').value.trim();
  if (!content) return showToast('content required', true);
  try {
    await api('/api/facts', {
      method: 'POST',
      body: JSON.stringify({
        content,
        category: $('newCat').value,
        tags: $('newTags').value,
      }),
    });
    $('newContent').value = '';
    $('newTags').value = '';
    showToast('added');
    loadList(); loadStats();
  } catch (e) { showToast(e.message, true); }
});

$('refresh').addEventListener('click', () => { loadList(); loadStats(); });
$('q').addEventListener('input', debounce(loadList, 200));
$('filterCat').addEventListener('change', loadList);
$('minTrust').addEventListener('change', loadList);
$('limit').addEventListener('change', loadList);

loadStats();
loadList();
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    store: MemoryStore = None  # type: ignore[assignment]

    def log_message(self, fmt, *args):  # silence access log
        pass

    def _send_json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, code: int, html: str) -> None:
        body = html.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw)
        except Exception:
            return {}

    def _query(self) -> dict:
        qs = parse_qs(urlsplit(self.path).query)
        return {k: v[0] for k, v in qs.items()}

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        try:
            if path == "/" or path == "/index.html":
                self._send_html(200, INDEX_HTML)
                return
            if path == "/api/stats":
                total, cats = self.store.stats()
                self._send_json(200, {"total": total, "categories": cats})
                return
            if path == "/api/facts":
                q = self._query()
                cat = q.get("category") or None
                min_trust = float(q.get("min_trust", 0) or 0)
                limit = int(q.get("limit", 100) or 100)
                facts = self.store.list_facts(category=cat, min_trust=min_trust, limit=limit)
                self._send_json(200, {"facts": facts})
                return
            if path == "/api/search":
                q = self._query()
                query = q.get("q", "")
                cat = q.get("category") or None
                min_trust = float(q.get("min_trust", 0) or 0)
                limit = int(q.get("limit", 100) or 100)
                facts = self.store.search_facts(query, category=cat, min_trust=min_trust, limit=limit)
                self._send_json(200, {"facts": facts})
                return
            self._send_json(404, {"error": "not found"})
        except Exception as e:
            self._send_json(500, {"error": str(e)})

    def do_POST(self) -> None:
        path = urlsplit(self.path).path
        try:
            if path == "/api/facts":
                body = self._read_json()
                content = (body.get("content") or "").strip()
                if not content:
                    self._send_json(400, {"error": "content required"})
                    return
                fact_id = self.store.add_fact(
                    content,
                    category=body.get("category") or "general",
                    tags=body.get("tags") or "",
                    project_path=body.get("project_path") or "",
                )
                self._send_json(200, {"fact_id": fact_id})
                return
            if path.startswith("/api/facts/") and path.endswith("/feedback"):
                fact_id = int(path.split("/")[3])
                body = self._read_json()
                result = self.store.record_feedback(fact_id, bool(body.get("helpful")))
                self._send_json(200, result)
                return
            self._send_json(404, {"error": "not found"})
        except KeyError as e:
            self._send_json(404, {"error": str(e)})
        except Exception as e:
            self._send_json(500, {"error": str(e)})

    def do_PUT(self) -> None:
        path = urlsplit(self.path).path
        try:
            if path.startswith("/api/facts/"):
                fact_id = int(path.rsplit("/", 1)[-1])
                body = self._read_json()
                ok = self.store.update_fact(
                    fact_id,
                    content=body.get("content"),
                    tags=body.get("tags"),
                    category=body.get("category"),
                    trust_delta=body.get("trust_delta"),
                )
                if not ok:
                    self._send_json(404, {"error": "fact not found"})
                    return
                self._send_json(200, {"ok": True})
                return
            self._send_json(404, {"error": "not found"})
        except Exception as e:
            self._send_json(500, {"error": str(e)})

    def do_DELETE(self) -> None:
        path = urlsplit(self.path).path
        try:
            if path.startswith("/api/facts/"):
                fact_id = int(path.rsplit("/", 1)[-1])
                ok = self.store.remove_fact(fact_id)
                self._send_json(200 if ok else 404, {"ok": ok})
                return
            self._send_json(404, {"error": "not found"})
        except Exception as e:
            self._send_json(500, {"error": str(e)})


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--db", default=str(DB_PATH))
    args = parser.parse_args()

    Handler.store = MemoryStore(db_path=args.db)

    server = HTTPServer((args.host, args.port), Handler)
    print(f"Holographic Memory UI → http://{args.host}:{args.port}  (db: {args.db})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")
    finally:
        Handler.store.close()


if __name__ == "__main__":
    main()
