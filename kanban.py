#!/usr/bin/env python3
"""Kanban WebUI — local kanban board for Hermes Agent."""

import http.server
import json
import os
import re
import shutil
import sqlite3
import time
from pathlib import Path
from urllib.parse import urlparse, parse_qs

# ── Paths ──────────────────────────────────────────────────────────────────
KANBAN_DB = Path(os.environ.get("USERPROFILE", "")) / "AppData" / "Local" / "hermes" / "kanban.db"
PROFILES_DIR = KANBAN_DB.parent / "profiles"

# ── Helpers ────────────────────────────────────────────────────────────────

def get_db():
    """Return a SQLite connection to the default kanban DB."""
    conn = sqlite3.connect(str(KANBAN_DB))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def get_board_db(slug):
    """Return the DB path for a board slug."""
    if slug == "default":
        return KANBAN_DB
    board_db = KANBAN_DB.parent / "kanban" / "boards" / slug / "kanban.db"
    if board_db.exists():
        return board_db
    return None


def board_conn(slug):
    """Return a (connection, db_path) tuple for a board."""
    db_path = get_board_db(slug)
    if not db_path:
        return None, None
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn, db_path

# ── Request Handler ─────────────────────────────────────────────────────────

class Handler(http.server.BaseHTTPRequestHandler):

    # ── Routing ────────────────────────────────────────────────────────────

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        if path == "" or path == "/":
            self._serve_html()

        elif path == "/api/boards":
            self._handle_get_boards()

        elif path == "/api/profiles":
            self._handle_get_profiles()

        elif path.startswith("/api/tasks/") and path.endswith("/comments"):
            self._handle_get_comments(path)

        elif path.startswith("/api/tasks/") and path.endswith("/links"):
            self._handle_get_links(path)

        elif path.startswith("/api/tasks/"):
            self._handle_get_task(path)

        elif path.startswith("/api/boards/") and path.endswith("/tasks"):
            self._handle_get_tasks(parsed)

        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        try:
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/")

            if path == "/api/boards":
                self._handle_create_board()

            elif path.startswith("/api/tasks/") and path.endswith("/comments"):
                self._handle_create_comment(path)

            elif path.startswith("/api/tasks/") and path.endswith("/links"):
                self._handle_create_link(path)

            elif path.startswith("/api/boards/") and path.endswith("/tasks"):
                self._handle_create_task(path)

            else:
                self.send_response(404)
                self.end_headers()
        except Exception as e:
            self._handle_error(e)

    def do_PUT(self):
        try:
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/")

            if path.startswith("/api/tasks/"):
                self._handle_update_task(path)

            else:
                self.send_response(404)
                self.end_headers()
        except Exception as e:
            self._handle_error(e)

    def do_DELETE(self):
        try:
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/")

            if path.startswith("/api/tasks/") and "/links/" in path:
                self._handle_delete_link(path)

            elif path.startswith("/api/tasks/"):
                self._handle_delete_task(path)

            else:
                self.send_response(404)
                self.end_headers()
        except Exception as e:
            self._handle_error(e)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    # ── HTML ────────────────────────────────────────────────────────────────

    def _serve_html(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"<h1>Hello Kanban</h1>")

    # ── Boards ─────────────────────────────────────────────────────────────

    def _handle_get_boards(self):
        boards = [{"slug": "default", "name": "Default", "description": "", "icon": "\U0001f4cb"}]
        boards_dir = KANBAN_DB.parent / "kanban" / "boards"
        if boards_dir.exists():
            for d in sorted(boards_dir.iterdir()):
                if d.is_dir() and (d / "kanban.db").exists():
                    boards.append({
                        "slug": d.name,
                        "name": d.name.replace("-", " ").replace("_", " ").title(),
                        "description": "",
                        "icon": "\U0001f4cb",
                    })
        self.json_response(boards)

    def _handle_create_board(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        slug = body.get("slug", "").strip().lower()
        if not slug:
            self.json_response({"error": "Slug required"}, 400)
            return
        if not re.match(r'^[a-z0-9][a-z0-9_-]{0,63}$', slug):
            self.json_response({"error": "Invalid slug"}, 400)
            return
        if slug == "default":
            self.json_response({"error": "Cannot create board named 'default'"}, 400)
            return
        board_dir = KANBAN_DB.parent / "kanban" / "boards" / slug
        if board_dir.exists():
            self.json_response({"error": "Board already exists"}, 409)
            return
        board_dir.mkdir(parents=True)
        shutil.copy2(str(KANBAN_DB), str(board_dir / "kanban.db"))
        self.json_response({"slug": slug, "name": slug.replace("-", " ").replace("_", " ").title()}, 201)

    # ── Profiles ───────────────────────────────────────────────────────────

    def _handle_get_profiles(self):
        profiles = [{"name": "default", "path": str(KANBAN_DB.parent)}]
        if PROFILES_DIR.exists():
            for d in sorted(PROFILES_DIR.iterdir()):
                if d.is_dir():
                    profiles.append({"name": d.name, "path": str(d)})
        self.json_response(profiles)

    # ── Tasks ──────────────────────────────────────────────────────────────

    def _handle_get_tasks(self, parsed):
        slug = parsed.path.split("/")[3]
        conn, _ = board_conn(slug)
        if not conn:
            self.json_response({"error": "Board not found"}, 404)
            return

        params = parse_qs(parsed.query)
        status_filter = params.get("status", [None])[0]
        assignee_filter = params.get("assignee", [None])[0]
        search = params.get("search", [None])[0]

        query = "SELECT * FROM tasks WHERE 1=1"
        args = []
        if status_filter:
            query += " AND status = ?"
            args.append(status_filter)
        if assignee_filter:
            query += " AND assignee = ?"
            args.append(assignee_filter)
        if search:
            query += " AND (title LIKE ? OR body LIKE ?)"
            args.extend([f"%{search}%", f"%{search}%"])
        query += " ORDER BY created_at DESC"

        rows = conn.execute(query, args).fetchall()
        tasks = [dict(r) for r in rows]
        conn.close()
        self.json_response(tasks)

    def _handle_get_task(self, path):
        task_id = path.split("/")[3]
        conn = get_db()
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not row:
            conn.close()
            self.json_response({"error": "Task not found"}, 404)
            return
        task = dict(row)

        comments = conn.execute(
            "SELECT * FROM task_comments WHERE task_id = ? ORDER BY created_at ASC",
            (task_id,),
        ).fetchall()
        task["comments"] = [dict(c) for c in comments]

        parents = conn.execute(
            "SELECT parent_id FROM task_links WHERE child_id = ?", (task_id,)
        ).fetchall()
        children = conn.execute(
            "SELECT child_id FROM task_links WHERE parent_id = ?", (task_id,)
        ).fetchall()
        task["parent_ids"] = [r[0] for r in parents]
        task["child_ids"] = [r[0] for r in children]

        conn.close()
        self.json_response(task)

    def _handle_create_task(self, path):
        slug = path.split("/")[3]
        conn, _ = board_conn(slug)
        if not conn:
            self.json_response({"error": "Board not found"}, 404)
            return

        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        title = body.get("title", "").strip()
        if not title:
            conn.close()
            self.json_response({"error": "Title required"}, 400)
            return

        task_id = "t_" + os.urandom(4).hex()
        task_body = body.get("body", "")
        assignee = body.get("assignee", "default")
        status = body.get("status", "todo")

        now = int(time.time())
        conn.execute(
            """INSERT INTO tasks
            (id, title, body, assignee, status, priority, created_by, created_at, started_at,
             completed_at, workspace_kind, workspace_path, branch_name, claim_lock, claim_expires,
             tenant, result, idempotency_key, consecutive_failures, worker_pid, last_failure_error,
             max_runtime_seconds, last_heartbeat_at, current_run_id, workflow_template_id,
             current_step_key, skills, model_override, max_retries, goal_mode, goal_max_turns, session_id)
            VALUES (?, ?, ?, ?, ?, 0, 'user', ?, NULL, NULL, 'scratch', NULL, NULL, NULL, NULL,
                    NULL, NULL, NULL, 0, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 0, NULL, NULL)""",
            (task_id, title, task_body, assignee, status, now),
        )
        conn.commit()

        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        conn.close()
        self.json_response(dict(row), 201)

    def _handle_update_task(self, path):
        task_id = path.split("/")[3]
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")

        conn = get_db()
        fields = []
        args = []
        for field in ["title", "body", "assignee", "status"]:
            if field in body:
                fields.append(f"{field} = ?")
                args.append(body[field])

        if not fields:
            conn.close()
            self.json_response({"error": "No fields to update"}, 400)
            return

        args.append(task_id)
        conn.execute(f"UPDATE tasks SET {', '.join(fields)} WHERE id = ?", args)
        conn.commit()

        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        conn.close()

        if row:
            self.json_response(dict(row))
        else:
            self.json_response({"error": "Task not found"}, 404)

    def _handle_delete_task(self, path):
        task_id = path.split("/")[3]
        conn = get_db()
        conn.execute("DELETE FROM task_comments WHERE task_id = ?", (task_id,))
        conn.execute("DELETE FROM task_links WHERE parent_id = ? OR child_id = ?", (task_id, task_id))
        conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        conn.commit()
        conn.close()
        self.json_response({"ok": True})

    # ── Comments ───────────────────────────────────────────────────────────

    def _handle_get_comments(self, path):
        task_id = path.split("/")[3]
        conn = get_db()
        rows = conn.execute(
            "SELECT * FROM task_comments WHERE task_id = ? ORDER BY created_at ASC",
            (task_id,),
        ).fetchall()
        conn.close()
        self.json_response([dict(r) for r in rows])

    def _handle_create_comment(self, path):
        task_id = path.split("/")[3]
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        comment_body = body.get("body", "").strip()
        if not comment_body:
            self.json_response({"error": "Comment body required"}, 400)
            return

        author = body.get("author", "human")
        now = int(time.time())
        conn = get_db()
        conn.execute(
            "INSERT INTO task_comments (task_id, author, body, created_at) VALUES (?, ?, ?, ?)",
            (task_id, author, comment_body, now),
        )
        conn.commit()
        comment_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        row = conn.execute("SELECT * FROM task_comments WHERE id = ?", (comment_id,)).fetchone()
        conn.close()
        self.json_response(dict(row), 201)

    # ── Links ──────────────────────────────────────────────────────────────

    def _handle_get_links(self, path):
        task_id = path.split("/")[3]
        conn = get_db()
        parents = conn.execute("SELECT parent_id FROM task_links WHERE child_id = ?", (task_id,)).fetchall()
        children = conn.execute("SELECT child_id FROM task_links WHERE parent_id = ?", (task_id,)).fetchall()
        conn.close()
        self.json_response({
            "parent_ids": [r[0] for r in parents],
            "child_ids": [r[0] for r in children],
        })

    def _handle_create_link(self, path):
        task_id = path.split("/")[3]
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        parent_id = body.get("parent_id")
        if not parent_id:
            self.json_response({"error": "parent_id required"}, 400)
            return
        conn = get_db()
        conn.execute(
            "INSERT OR IGNORE INTO task_links (parent_id, child_id) VALUES (?, ?)",
            (parent_id, task_id),
        )
        conn.commit()
        conn.close()
        self.json_response({"ok": True})

    def _handle_delete_link(self, path):
        parts = path.split("/")
        task_id = parts[3]
        parent_id = parts[5]
        conn = get_db()
        conn.execute("DELETE FROM task_links WHERE parent_id = ? AND child_id = ?", (parent_id, task_id))
        conn.commit()
        conn.close()
        self.json_response({"ok": True})

    # ── Helpers ────────────────────────────────────────────────────────────

    def json_response(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def _handle_error(self, e):
        import traceback
        print(f"ERROR: {e}")
        traceback.print_exc()
        try:
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode())
        except Exception:
            pass

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
