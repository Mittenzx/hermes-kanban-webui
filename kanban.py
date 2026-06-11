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

# ── DB Helper ──────────────────────────────────────────────────────────────

def get_db():
    """Return a SQLite connection to the kanban DB."""
    conn = sqlite3.connect(str(KANBAN_DB))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

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
        else:
            self.send_response(404)
            self.end_headers()

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
