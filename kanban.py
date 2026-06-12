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
INDEX_HTML = Path(__file__).parent / "index.html"

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

def read_index():
    if INDEX_HTML.exists():
        return INDEX_HTML.read_text(encoding="utf-8")
    return "<h1>index.html not found</h1>"

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
            self.wfile.write(read_index().encode())

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
            result = []
            # Default profile
            default_path = KANBAN_DB.parent
            soul_path = default_path / "SOUL.md"
            personality = ""
            if soul_path.exists():
                try:
                    personality = soul_path.read_text(encoding="utf-8", errors="replace")[:200]
                except: pass
            skills_count = 0
            skills_dir = default_path / "skills"
            if skills_dir.exists():
                skills_count = sum(1 for _ in skills_dir.rglob("SKILL.md"))
            config_path = default_path / "config.yaml"
            model = ""
            if config_path.exists():
                try:
                    for line in config_path.read_text(encoding="utf-8", errors="replace").split("\n"):
                        if line.strip().startswith("default:"):
                            model = line.split(":", 1)[1].strip().strip('"').strip("'")
                            break
                except: pass
            result.append({"name": "default", "path": str(default_path), "is_default": True, "personality": personality, "skills_count": skills_count, "model": model})
            # Named profiles
            if profiles_dir.exists():
                for d in sorted(profiles_dir.iterdir()):
                    if d.is_dir():
                        p_soul = d / "SOUL.md"
                        p_personality = ""
                        if p_soul.exists():
                            try:
                                p_personality = p_soul.read_text(encoding="utf-8", errors="replace")[:200]
                            except: pass
                        p_skills = 0
                        p_skills_dir = d / "skills"
                        if p_skills_dir.exists():
                            p_skills = sum(1 for _ in p_skills_dir.rglob("SKILL.md"))
                        result.append({"name": d.name, "path": str(d), "is_default": False, "personality": p_personality, "skills_count": p_skills, "model": ""})
            self.json_response(result)

        # GET /api/profiles/{name}/files — list files in profile directory
        elif path.startswith("/api/profiles/") and path.endswith("/files"):
            name = path.split("/")[3]
            if name == "default":
                profile_path = KANBAN_DB.parent
            else:
                profile_path = KANBAN_DB.parent / "profiles" / name
            if not profile_path.exists():
                self.json_response({"error": "Profile not found"}, 404)
                return
            skip = {".git", "__pycache__", "node_modules", ".venv", "venv", "__pycache__"}
            files = []
            for f in sorted(profile_path.rglob("*")):
                if any(part in skip for part in f.parts):
                    continue
                if f.is_file():
                    rel = f.relative_to(profile_path)
                    files.append({"path": str(rel), "size": f.stat().st_size, "is_dir": False})
                elif f.is_dir():
                    rel = f.relative_to(profile_path)
                    files.append({"path": str(rel) + "/", "size": 0, "is_dir": True})
            self.json_response(files)

        # GET /api/profiles/{name}/file?path=... — read a file
        elif path.startswith("/api/profiles/") and "/file" in path and "path=" in parsed.query:
            name = path.split("/")[3]
            if name == "default":
                profile_path = KANBAN_DB.parent
            else:
                profile_path = KANBAN_DB.parent / "profiles" / name
            file_path = params.get("path", [None])[0]
            if not file_path:
                self.json_response({"error": "Path required"}, 400)
                return
            full_path = profile_path / file_path
            try:
                full_path.relative_to(profile_path)
            except ValueError:
                self.json_response({"error": "Invalid path"}, 403)
                return
            if not full_path.exists():
                self.json_response({"error": "File not found"}, 404)
                return
            if full_path.stat().st_size > 100_000:
                self.json_response({"error": "File too large (>100KB)"}, 400)
                return
            content = full_path.read_text(encoding="utf-8", errors="replace")
            self.json_response({"content": content, "path": file_path})

        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")

        # POST /api/boards — create a new board
        if path == "/api/boards":
            slug = body.get("slug", "").strip().lower()
            if not slug:
                self.json_response({"error": "Slug required"}, 400)
                return
            import re as _re
            if not _re.match(r'^[a-z0-9][a-z0-9_-]{0,63}$', slug):
                self.json_response({"error": "Invalid slug: lowercase alphanumerics, hyphens, underscores"}, 400)
                return
            if slug == "default":
                self.json_response({"error": "Cannot create board named 'default'"}, 400)
                return
            board_dir = KANBAN_DB.parent / "kanban" / "boards" / slug
            if board_dir.exists():
                self.json_response({"error": "Board already exists"}, 409)
                return
            board_dir.mkdir(parents=True)
            board_db = board_dir / "kanban.db"
            import shutil
            shutil.copy2(str(KANBAN_DB), str(board_db))
            self.json_response({"slug": slug, "name": slug.replace("-", " ").replace("_", " ").title()}, 201)

        elif path.startswith("/api/boards/") and path.endswith("/tasks"):
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

        # POST /api/tasks/{id}/links — add parent link
        elif path.startswith("/api/tasks/") and path.endswith("/links"):
            task_id = path.split("/")[3]
            parent_id = body.get("parent_id")
            if not parent_id:
                self.json_response({"error": "parent_id required"}, 400)
                return
            conn = get_db()
            conn.execute("INSERT OR IGNORE INTO task_links (parent_id, child_id) VALUES (?, ?)", (parent_id, task_id))
            conn.commit()
            conn.close()
            self.json_response({"ok": True})

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

        # DELETE /api/tasks/{id}/links/{parent_id} — remove link
        if path.startswith("/api/tasks/") and "/links/" in path:
            parts = path.split("/")
            task_id = parts[3]
            parent_id = parts[5]
            conn = get_db()
            conn.execute("DELETE FROM task_links WHERE parent_id = ? AND child_id = ?", (parent_id, task_id))
            conn.commit()
            conn.close()
            self.json_response({"ok": True})

        elif path.startswith("/api/tasks/"):
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
