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

def row_to_dict(row):
    return dict(row) if row else None

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
            self.wfile.write(b"<h1>Hello Kanban</h1>")

        # GET /api/boards — list boards
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

        # GET /api/boards/{slug}/tasks — list tasks
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

        # GET /api/tasks/{id} — task detail
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

        # GET /api/tasks/{id}/comments
        elif path.startswith("/api/tasks/") and path.endswith("/comments"):
            task_id = path.split("/")[3]
            conn = get_db()
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM task_comments WHERE task_id = ? ORDER BY created_at ASC", (task_id,)).fetchall()
            conn.close()
            self.json_response([dict(r) for r in rows])

        # GET /api/profiles
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

        # POST /api/boards/{slug}/tasks — create task
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

        # POST /api/tasks/{id}/comments
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
