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
    """Return a SQLite connection to the kanban DB."""
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

# ── Request Handler ─────────────────────────────────────────────────────────

class Handler(http.server.BaseHTTPRequestHandler):

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        if path == "" or path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"<h1>Hello Kanban</h1>")

        elif path == "/api/boards":
            self._handle_get_boards()

        elif path.startswith("/api/boards/") and path.endswith("/tasks"):
            self._handle_get_tasks(parsed)

        else:
            self.send_response(404)
            self.end_headers()

    # ── Boards ─────────────────────────────────────────────────────────────

    def _handle_get_boards(self):
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

    # ── Tasks ──────────────────────────────────────────────────────────────

    def _handle_get_tasks(self, parsed):
        slug = parsed.path.split("/")[3]
        board_db = get_board_db(slug)
        if not board_db:
            self.json_response({"error": "Board not found"}, 404)
            return

        conn = sqlite3.connect(str(board_db))
        conn.row_factory = sqlite3.Row

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

    # ── Helpers ────────────────────────────────────────────────────────────

    def json_response(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def log_message(self, fmt, *args):
        pass  # suppress request logging

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
