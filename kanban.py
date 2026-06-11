#!/usr/bin/env python3
"""Kanban WebUI — local kanban board for Hermes Agent."""

import http.server
import json
import os
import sqlite3
from pathlib import Path
from urllib.parse import urlparse, parse_qs

# ── Paths ──────────────────────────────────────────────────────────────────
KANBAN_DB = Path(os.environ.get("USERPROFILE", "")) / "AppData" / "Local" / "hermes" / "kanban.db"

# ── Helpers ────────────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(str(KANBAN_DB))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def get_board_db(slug):
    if slug == "default":
        return KANBAN_DB
    board_db = KANBAN_DB.parent / "kanban" / "boards" / slug / "kanban.db"
    if board_db.exists():
        return board_db
    return None

# ── HTML Template ──────────────────────────────────────────────────────────

PAGE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Kanban Board</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: 'Segoe UI', system-ui, sans-serif; background: #0f172a; color: #e2e8f0; min-height: 100vh; }
  .header { background: #1e293b; border-bottom: 1px solid #334155; padding: 0.75rem 1.5rem; display: flex; align-items: center; justify-content: space-between; }
  .header h1 { font-size: 1.1rem; color: #22d3ee; }
  .header .btn { padding: 0.4rem 1rem; background: #22d3ee; color: #0f172a; border: none; border-radius: 6px; cursor: pointer; font-size: 0.8rem; font-weight: 600; }
  .header .btn:hover { opacity: 0.85; }
  .board { display: flex; gap: 1rem; padding: 1rem; overflow-x: auto; height: calc(100vh - 52px); align-items: flex-start; }
  .column { background: #1e293b; border-radius: 8px; min-width: 220px; max-width: 280px; flex: 1; display: flex; flex-direction: column; max-height: 100%; }
  .column-header { padding: 0.75rem; font-size: 0.75rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; color: #64748b; border-bottom: 1px solid #334155; display: flex; justify-content: space-between; }
  .column-header .count { background: #334155; padding: 0.1rem 0.5rem; border-radius: 999px; font-size: 0.65rem; }
  .column-body { padding: 0.5rem; overflow-y: auto; flex: 1; min-height: 60px; }
  .task-card { background: #0f172a; border: 1px solid #334155; border-radius: 6px; padding: 0.6rem; margin-bottom: 0.5rem; cursor: grab; transition: border-color 0.15s, box-shadow 0.15s; }
  .task-card:hover { border-color: #22d3ee; box-shadow: 0 0 0 1px rgba(34, 211, 238, 0.2); }
  .task-card.dragging { opacity: 0.5; cursor: grabbing; }
  .task-card .title { font-size: 0.85rem; font-weight: 500; margin-bottom: 0.25rem; }
  .task-card .meta { font-size: 0.65rem; color: #64748b; display: flex; justify-content: space-between; }
  .task-card .assignee { background: #1e3a5f; color: #22d3ee; padding: 0.1rem 0.4rem; border-radius: 4px; }
  .column-body.drag-over { background: rgba(34, 211, 238, 0.05); border: 1px dashed #22d3ee; border-radius: 6px; }
</style>
</head>
<body>
<div class="header">
  <h1>⚡ Kanban Board</h1>
  <button class="btn" onclick="showCreateForm()">+ New Task</button>
</div>
<div class="board" id="board"><div style="color:#475569;padding:2rem;">Loading...</div></div>
<script>
const STATUSES = [
  { key: 'triage', label: 'Triage', color: '#94a3b8' },
  { key: 'todo', label: 'Todo', color: '#64748b' },
  { key: 'ready', label: 'Ready', color: '#22d3ee' },
  { key: 'running', label: 'Running', color: '#fbbf24' },
  { key: 'blocked', label: 'Blocked', color: '#fb7185' },
  { key: 'done', label: 'Done', color: '#34d399' },
];
let tasks = [];
let draggedCard = null;

async function loadTasks() {
  const res = await fetch('/api/boards/default/tasks');
  tasks = await res.json();
  renderBoard();
}

function renderBoard() {
  const board = document.getElementById('board');
  board.innerHTML = STATUSES.map(status => {
    const statusTasks = tasks.filter(t => t.status === status.key);
    return '<div class="column" data-status="' + status.key + '">' +
      '<div class="column-header" style="border-left:3px solid ' + status.color + ';padding-left:0.6rem;">' +
        '<span>' + status.label + '</span>' +
        '<span class="count">' + statusTasks.length + '</span>' +
      '</div>' +
      '<div class="column-body" data-status="' + status.key + '">' +
        statusTasks.map(task => renderCard(task)).join('') +
      '</div>' +
    '</div>';
  }).join('');
}

function renderCard(task) {
  return '<div class="task-card" draggable="true" data-id="' + esc(task.id) + '" onclick="openTask(\'' + esc(task.id) + '\')">' +
    '<div class="title">' + esc(task.title) + '</div>' +
    '<div class="meta">' +
      '<span class="assignee">' + esc(task.assignee || 'unassigned') + '</span>' +
      '<span>' + fmtDate(task.created_at) + '</span>' +
    '</div>' +
  '</div>';
}

function esc(s) { var d=document.createElement('div'); d.textContent=s||''; return d.innerHTML; }
function fmtDate(s) { if(!s) return ''; var d=new Date(s); return d.toLocaleDateString('en-US',{month:'short',day:'numeric'}); }

document.addEventListener('dragstart', function(e) {
  if(e.target.classList.contains('task-card')) { draggedCard=e.target; e.target.classList.add('dragging'); e.dataTransfer.effectAllowed='move'; }
});
document.addEventListener('dragend', function(e) {
  if(e.target.classList.contains('task-card')) { e.target.classList.remove('dragging'); draggedCard=null; }
});
document.addEventListener('dragover', function(e) {
  var cb=e.target.closest('.column-body');
  if(cb) { e.preventDefault(); e.dataTransfer.dropEffect='move'; cb.classList.add('drag-over'); }
});
document.addEventListener('dragleave', function(e) {
  var cb=e.target.closest('.column-body');
  if(cb && !cb.contains(e.relatedTarget)) cb.classList.remove('drag-over');
});
document.addEventListener('drop', async function(e) {
  e.preventDefault();
  var cb=e.target.closest('.column-body');
  if(!cb||!draggedCard) return;
  cb.classList.remove('drag-over');
  var newStatus=cb.dataset.status;
  var taskId=draggedCard.dataset.id;
  var res=await fetch('/api/tasks/'+taskId, {method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({status:newStatus})});
  if(res.ok) { var t=tasks.find(function(x){return x.id===taskId;}); if(t) t.status=newStatus; renderBoard(); }
});

function openTask(id) { console.log('open',id); }
function showCreateForm() { alert('Coming soon!'); }

loadTasks();
</script>
</body>
</html>"""

# ── Request Handler ─────────────────────────────────────────────────────────

class Handler(http.server.BaseHTTPRequestHandler):

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        params = parse_qs(parsed.query)

        if path == "" or path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(PAGE_HTML.encode())

        elif path == "/api/boards":
            boards = [{"slug": "default", "name": "Default", "description": "", "icon": "📋"}]
            boards_dir = KANBAN_DB.parent / "kanban" / "boards"
            if boards_dir.exists():
                for d in sorted(boards_dir.iterdir()):
                    if d.is_dir() and (d / "kanban.db").exists():
                        boards.append({
                            "slug": d.name,
                            "name": d.name.replace("-", " ").replace("_", " ").title(),
                            "description": "",
                            "icon": "📋",
                        })
            self.json_response(boards)

        elif path.startswith("/api/boards/") and path.endswith("/tasks"):
            slug = path.split("/")[3]
            board_db = get_board_db(slug)
            if not board_db:
                self.json_response({"error": "Board not found"}, 404)
                return
            conn = sqlite3.connect(str(board_db))
            conn.row_factory = sqlite3.Row
            query = "SELECT * FROM tasks WHERE 1=1"
            args = []
            if params.get("status", [None])[0]:
                query += " AND status = ?"
                args.append(params["status"][0])
            if params.get("assignee", [None])[0]:
                query += " AND assignee = ?"
                args.append(params["assignee"][0])
            if params.get("search", [None])[0]:
                query += " AND (title LIKE ? OR body LIKE ?)"
                args.extend(["%" + params["search"][0] + "%"] * 2)
            query += " ORDER BY created_at DESC"
            rows = conn.execute(query, args).fetchall()
            conn.close()
            self.json_response([dict(r) for r in rows])

        elif path.startswith("/api/tasks/") and "/comments" not in path and "/links" not in path:
            task_id = path.split("/")[3]
            conn = get_db()
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if not row:
                conn.close()
                self.json_response({"error": "Task not found"}, 404)
                return
            task = dict(row)
            comments = conn.execute("SELECT * FROM task_comments WHERE task_id = ? ORDER BY created_at ASC", (task_id,)).fetchall()
            task["comments"] = [dict(c) for c in comments]
            parents = conn.execute("SELECT parent_id FROM task_links WHERE child_id = ?", (task_id,)).fetchall()
            children = conn.execute("SELECT child_id FROM task_links WHERE parent_id = ?", (task_id,)).fetchall()
            task["parent_ids"] = [r[0] for r in parents]
            task["child_ids"] = [r[0] for r in children]
            conn.close()
            self.json_response(task)

        elif path.startswith("/api/tasks/") and path.endswith("/comments"):
            task_id = path.split("/")[3]
            conn = get_db()
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM task_comments WHERE task_id = ? ORDER BY created_at ASC", (task_id,)).fetchall()
            conn.close()
            self.json_response([dict(r) for r in rows])

        elif path == "/api/profiles":
            profiles_dir = KANBAN_DB.parent / "profiles"
            profiles = [{"name": "default", "path": str(KANBAN_DB.parent)}]
            if profiles_dir.exists():
                for d in sorted(profiles_dir.iterdir()):
                    if d.is_dir():
                        profiles.append({"name": d.name, "path": str(d)})
            self.json_response(profiles)

        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")

        if path.startswith("/api/boards/") and path.endswith("/tasks"):
            slug = path.split("/")[3]
            board_db = get_board_db(slug)
            if not board_db:
                self.json_response({"error": "Board not found"}, 404)
                return
            title = body.get("title", "").strip()
            if not title:
                self.json_response({"error": "Title required"}, 400)
                return
            task_id = "t_" + os.urandom(4).hex()
            task_body = body.get("body", "")
            assignee = body.get("assignee", "default")
            status = body.get("status", "todo")
            conn = sqlite3.connect(str(board_db))
            conn.execute(
                "INSERT INTO tasks (id, title, body, assignee, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, datetime('now'), datetime('now'))",
                (task_id, title, task_body, assignee, status),
            )
            conn.commit()
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            conn.close()
            self.json_response(dict(row), 201)

        elif path.startswith("/api/tasks/") and path.endswith("/comments"):
            task_id = path.split("/")[3]
            comment_body = body.get("body", "").strip()
            if not comment_body:
                self.json_response({"error": "Comment body required"}, 400)
                return
            author = body.get("author", "human")
            comment_id = "c_" + os.urandom(4).hex()
            conn = get_db()
            conn.execute(
                "INSERT INTO task_comments (id, task_id, body, author, created_at) VALUES (?, ?, ?, ?, datetime('now'))",
                (comment_id, task_id, comment_body, author),
            )
            conn.commit()
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM task_comments WHERE id = ?", (comment_id,)).fetchone()
            conn.close()
            self.json_response(dict(row), 201)

        else:
            self.send_response(404)
            self.end_headers()

    def do_PUT(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")

        if path.startswith("/api/tasks/"):
            task_id = path.split("/")[3]
            conn = get_db()
            conn.row_factory = sqlite3.Row
            fields = []
            args = []
            for field in ["title", "body", "assignee", "status"]:
                if field in body:
                    fields.append(field + " = ?")
                    args.append(body[field])
            if not fields:
                conn.close()
                self.json_response({"error": "No fields to update"}, 400)
                return
            fields.append("updated_at = datetime('now')")
            args.append(task_id)
            conn.execute("UPDATE tasks SET " + ", ".join(fields) + " WHERE id = ?", args)
            conn.commit()
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            conn.close()
            if row:
                self.json_response(dict(row))
            else:
                self.json_response({"error": "Task not found"}, 404)
        else:
            self.send_response(404)
            self.end_headers()

    def do_DELETE(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        if path.startswith("/api/tasks/"):
            task_id = path.split("/")[3]
            conn = get_db()
            conn.execute("DELETE FROM task_comments WHERE task_id = ?", (task_id,))
            conn.execute("DELETE FROM task_links WHERE parent_id = ? OR child_id = ?", (task_id, task_id))
            conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
            conn.commit()
            conn.close()
            self.json_response({"ok": True})
        else:
            self.send_response(404)
            self.end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def json_response(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def log_message(self, fmt, *args):
        pass

# ── Main ────────────────────────────────────────────────────────────────────

def main():
    port = 7681
    server = http.server.HTTPServer(("127.0.0.1", port), Handler)
    print(f"Kanban WebUI running at http://127.0.0.1:{port}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.server_close()

if __name__ == "__main__":
    main()
