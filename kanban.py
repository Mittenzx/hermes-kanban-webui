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

def board_conn(slug):
    db_path = get_board_db(slug)
    if not db_path:
        return None, None
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn, db_path

# ── HTML Template ──────────────────────────────────────────────────────────

PAGE_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Kanban Board</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: 'Segoe UI', system-ui, sans-serif; background: #0f172a; color: #e2e8f0; min-height: 100vh; overflow: hidden; }

/* ── Header ─────────────────────────────────────────────────────────────── */
.header { background: #1e293b; border-bottom: 1px solid #334155; padding: 0.6rem 1.2rem; display: flex; align-items: center; justify-content: space-between; height: 48px; }
.header-left { display: flex; align-items: center; gap: 0.75rem; }
.header h1 { font-size: 1rem; color: #22d3ee; }
.header select { background: #0f172a; border: 1px solid #334155; border-radius: 6px; color: #e2e8f0; padding: 0.3rem 0.5rem; font-size: 0.8rem; }
.header-right { display: flex; align-items: center; gap: 0.5rem; }
.header input[type="text"] { background: #0f172a; border: 1px solid #334155; border-radius: 6px; color: #e2e8f0; padding: 0.3rem 0.6rem; font-size: 0.8rem; width: 160px; }
.header input[type="text"]:focus { outline: none; border-color: #22d3ee; }
.btn { padding: 0.35rem 0.8rem; border: none; border-radius: 6px; cursor: pointer; font-size: 0.8rem; font-weight: 500; }
.btn-primary { background: #22d3ee; color: #0f172a; }
.btn-secondary { background: #334155; color: #e2e8f0; }
.btn-danger { background: #7f1d1d; color: #fca5a5; }
.btn:hover { opacity: 0.85; }
.shortcuts { font-size: 0.6rem; color: #475569; margin-left: 0.5rem; }
.shortcuts kbd { background: #1e293b; padding: 0.05rem 0.25rem; border-radius: 3px; border: 1px solid #334155; }

/* ── Board ───────────────────────────────────────────────────────────────── */
.board { display: flex; gap: 0.75rem; padding: 0.75rem; overflow-x: auto; height: calc(100vh - 48px); align-items: flex-start; }

/* ── Columns ─────────────────────────────────────────────────────────────── */
.column { background: #1e293b; border-radius: 8px; min-width: 220px; max-width: 280px; flex: 1; display: flex; flex-direction: column; max-height: 100%; }
.column-header { padding: 0.6rem 0.75rem; font-size: 0.7rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; color: #64748b; border-bottom: 1px solid #334155; display: flex; justify-content: space-between; align-items: center; }
.column-header .count { background: #334155; padding: 0.1rem 0.4rem; border-radius: 999px; font-size: 0.6rem; color: #94a3b8; }
.column-body { padding: 0.4rem; overflow-y: auto; flex: 1; min-height: 50px; transition: background 0.15s; }
.column-body.drag-over { background: rgba(34, 211, 238, 0.06); border: 1px dashed #22d3ee; border-radius: 6px; }

/* ── Task Cards ──────────────────────────────────────────────────────────── */
.task-card { background: #020617; border: 1px solid #1e293b; border-radius: 6px; padding: 0.5rem 0.6rem; margin-bottom: 0.4rem; cursor: grab; transition: border-color 0.15s, box-shadow 0.15s; }
.task-card:hover { border-color: #22d3ee; box-shadow: 0 0 0 1px rgba(34, 211, 238, 0.15); }
.task-card.dragging { opacity: 0.4; cursor: grabbing; }
.task-card .title { font-size: 0.82rem; font-weight: 500; margin-bottom: 0.2rem; line-height: 1.3; }
.task-card .meta { font-size: 0.6rem; color: #475569; display: flex; justify-content: space-between; align-items: center; }
.task-card .assignee { background: #1e3a5f; color: #22d3ee; padding: 0.05rem 0.35rem; border-radius: 4px; font-size: 0.55rem; }
.task-card .comments-badge { background: #334155; color: #94a3b8; padding: 0.05rem 0.3rem; border-radius: 4px; font-size: 0.55rem; }

/* ── Drawer ──────────────────────────────────────────────────────────────── */
.drawer-overlay { display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.5); z-index: 100; }
.drawer-overlay.active { display: block; }
.drawer { position: fixed; top: 0; right: 0; width: 420px; height: 100vh; background: #1e293b; border-left: 1px solid #334155; z-index: 101; transform: translateX(100%); transition: transform 0.2s ease; display: flex; flex-direction: column; }
.drawer.active { transform: translateX(0); }
.drawer-header { padding: 0.75rem 1rem; border-bottom: 1px solid #334155; display: flex; align-items: center; justify-content: space-between; }
.drawer-header h2 { font-size: 0.85rem; color: #22d3ee; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.drawer-header .close-btn { background: none; border: none; color: #64748b; font-size: 1.2rem; cursor: pointer; padding: 0 0.25rem; }
.drawer-body { flex: 1; overflow-y: auto; padding: 0.75rem 1rem; }
.drawer-field { margin-bottom: 0.75rem; }
.drawer-field label { display: block; font-size: 0.65rem; color: #64748b; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 0.25rem; }
.drawer-field input, .drawer-field textarea, .drawer-field select { width: 100%; padding: 0.4rem; background: #020617; border: 1px solid #334155; border-radius: 6px; color: #e2e8f0; font-size: 0.82rem; }
.drawer-field textarea { min-height: 80px; resize: vertical; font-family: inherit; }
.drawer-field input:focus, .drawer-field textarea:focus, .drawer-field select:focus { outline: none; border-color: #22d3ee; }
.drawer-actions { padding: 0.75rem 1rem; border-top: 1px solid #334155; display: flex; gap: 0.4rem; }
.drawer-actions .btn { flex: 1; padding: 0.4rem; border: none; border-radius: 6px; cursor: pointer; font-size: 0.75rem; font-weight: 500; }
.comment-item { background: #020617; border-radius: 6px; padding: 0.4rem 0.5rem; margin-bottom: 0.35rem; }
.comment-item .comment-meta { font-size: 0.6rem; color: #475569; margin-bottom: 0.15rem; }
.comment-item .comment-body { font-size: 0.78rem; line-height: 1.4; }

/* ── Modal ───────────────────────────────────────────────────────────────── */
.modal-overlay { display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.6); z-index: 200; align-items: center; justify-content: center; }
.modal-overlay.active { display: flex; }
.modal { background: #1e293b; border: 1px solid #334155; border-radius: 12px; padding: 1.25rem; width: 440px; max-width: 92vw; }
.modal h3 { font-size: 0.95rem; color: #22d3ee; margin-bottom: 0.75rem; }
.modal .form-group { margin-bottom: 0.6rem; }
.modal .form-group label { display: block; font-size: 0.65rem; color: #64748b; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 0.2rem; }
.modal .form-group input, .form-group textarea, .form-group select { width: 100%; padding: 0.4rem; background: #020617; border: 1px solid #334155; border-radius: 6px; color: #e2e8f0; font-size: 0.82rem; }
.modal .form-group textarea { min-height: 70px; resize: vertical; font-family: inherit; }
.modal .form-group input:focus, .form-group textarea:focus, .form-group select:focus { outline: none; border-color: #22d3ee; }
.modal .form-actions { display: flex; gap: 0.4rem; margin-top: 0.75rem; }
.modal .form-actions .btn { flex: 1; padding: 0.45rem; border: none; border-radius: 6px; cursor: pointer; font-size: 0.8rem; font-weight: 500; }

/* ── Toast ───────────────────────────────────────────────────────────────── */
.toast { position: fixed; bottom: 1rem; right: 1rem; padding: 0.5rem 1rem; border-radius: 8px; font-size: 0.78rem; z-index: 300; transition: opacity 0.3s; }
.toast.success { background: #064e3b; color: #34d399; }
.toast.error { background: #7f1d1d; color: #fca5a5; }

/* ── Scrollbar ───────────────────────────────────────────────────────────── */
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: #334155; border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: #475569; }
</style>
</head>
<body>

<!-- Header -->
<div class="header">
  <div class="header-left">
    <h1>\u26a1 Kanban</h1>
    <select id="board-switcher" onchange="switchBoard(this.value)"></select>
    <button class="btn btn-secondary" onclick="showCreateBoard()" style="padding: 0.25rem 0.5rem; font-size: 0.7rem;">+ Board</button>
  </div>
  <div class="header-right">
    <input type="text" id="search-input" placeholder="Search..." oninput="debouncedSearch()" />
    <select id="filter-assignee" onchange="loadTasks()" style="background: #0f172a; border: 1px solid #334155; border-radius: 6px; color: #e2e8f0; padding: 0.3rem 0.5rem; font-size: 0.8rem;">
      <option value="">All assignees</option>
    </select>
    <button class="btn btn-primary" onclick="showCreateForm()">+ New Task</button>
    <span class="shortcuts"><kbd>N</kbd> new <kbd>Esc</kbd> close</span>
  </div>
</div>

<!-- Board -->
<div class="board" id="board">
  <div style="color: #475569; font-size: 1rem; padding: 2rem;">Loading...</div>
</div>

<!-- Drawer -->
<div class="drawer-overlay" id="drawer-overlay" onclick="closeDrawer()"></div>
<div class="drawer" id="drawer">
  <div class="drawer-header">
    <h2 id="drawer-title">Task</h2>
    <button class="close-btn" onclick="closeDrawer()">&times;</button>
  </div>
  <div class="drawer-body" id="drawer-body"></div>
  <div class="drawer-actions">
    <button class="btn btn-primary" onclick="saveTask()">Save</button>
    <button class="btn btn-secondary" onclick="completeTask()">&#10003; Done</button>
    <button class="btn btn-secondary" onclick="blockTask()">&#10007; Block</button>
    <button class="btn btn-danger" onclick="deleteTask()">Delete</button>
  </div>
</div>

<!-- New Task Modal -->
<div class="modal-overlay" id="modal-overlay" onclick="if(event.target===this)hideCreateForm()">
  <div class="modal">
    <h3>New Task</h3>
    <div class="form-group">
      <label>Title</label>
      <input type="text" id="new-title" placeholder="What needs to be done?" />
    </div>
    <div class="form-group">
      <label>Description</label>
      <textarea id="new-body" placeholder="Add details..."></textarea>
    </div>
    <div class="form-group">
      <label>Assignee</label>
      <select id="new-assignee"></select>
    </div>
    <div class="form-group">
      <label>Status</label>
      <select id="new-status"></select>
    </div>
    <div class="form-actions">
      <button class="btn btn-primary" onclick="submitTask()">Create</button>
      <button class="btn btn-secondary" onclick="hideCreateForm()">Cancel</button>
    </div>
  </div>
</div>

<!-- New Board Modal -->
<div class="modal-overlay" id="board-modal-overlay" onclick="if(event.target===this)hideCreateBoard()">
  <div class="modal">
    <h3>New Board</h3>
    <div class="form-group">
      <label>Slug (lowercase, hyphens)</label>
      <input type="text" id="new-board-slug" placeholder="my-project" />
    </div>
    <div class="form-actions">
      <button class="btn btn-primary" onclick="submitBoard()">Create</button>
      <button class="btn btn-secondary" onclick="hideCreateBoard()">Cancel</button>
    </div>
  </div>
</div>

<!-- Toast -->
<div id="toast" class="toast" style="display:none;"></div>

<script>
// ── State ──────────────────────────────────────────────────────────────────
const STATUSES = [
  { key: 'triage',  label: 'Triage',  color: '#94a3b8' },
  { key: 'todo',    label: 'Todo',    color: '#64748b' },
  { key: 'ready',   label: 'Ready',   color: '#22d3ee' },
  { key: 'running', label: 'Running', color: '#fbbf24' },
  { key: 'blocked', label: 'Blocked', color: '#fb7185' },
  { key: 'done',    label: 'Done',    color: '#34d399' },
];
let currentBoard = 'default';
let tasks = [];
let profiles = [];
let searchTimeout = null;

// ── Helpers ────────────────────────────────────────────────────────────────
function esc(s) { const d = document.createElement('div'); d.textContent = s||''; return d.innerHTML; }
function fmtDate(ts) { if (!ts) return ''; const d = new Date(ts * 1000); return d.toLocaleDateString('en-US',{month:'short',day:'numeric'}); }
function showToast(msg, type) {
  const t = document.getElementById('toast');
  t.textContent = msg; t.className = 'toast ' + type; t.style.display = 'block'; t.style.opacity = '1';
  setTimeout(() => { t.style.opacity = '0'; setTimeout(() => t.style.display = 'none', 300); }, 2500);
}

// ── API ────────────────────────────────────────────────────────────────────
async function api(method, path, data) {
  const opts = { method, headers: {} };
  if (data) { opts.headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(data); }
  const res = await fetch(path, opts);
  return res.json();
}

// ── Load ───────────────────────────────────────────────────────────────────
async function loadBoards() {
  const boards = await api('GET', '/api/boards');
  const sel = document.getElementById('board-switcher');
  sel.innerHTML = boards.map(b => `<option value="${esc(b.slug)}" ${b.slug===currentBoard?'selected':''}>${esc(b.name)}</option>`).join('');
}

async function loadProfiles() {
  profiles = await api('GET', '/api/profiles');
}

async function loadTasks() {
  const search = document.getElementById('search-input').value;
  const assignee = document.getElementById('filter-assignee').value;
  let url = `/api/boards/${currentBoard}/tasks`;
  const p = new URLSearchParams();
  if (search) p.set('search', search);
  if (assignee) p.set('assignee', assignee);
  if (p.toString()) url += '?' + p.toString();
  tasks = await api('GET', url);
  renderBoard();
  updateAssigneeFilter();
}

function updateAssigneeFilter() {
  const sel = document.getElementById('filter-assignee');
  const cur = sel.value;
  const as = [...new Set(tasks.map(t => t.assignee).filter(Boolean))];
  sel.innerHTML = '<option value="">All assignees</option>' + as.map(a => `<option value="${esc(a)}" ${a===cur?'selected':''}>${esc(a)}</option>`).join('');
}

// ── Render ─────────────────────────────────────────────────────────────────
function renderBoard() {
  const board = document.getElementById('board');
  board.innerHTML = STATUSES.map(s => {
    const ct = tasks.filter(t => t.status === s.key);
    return `<div class="column" data-status="${s.key}">
      <div class="column-header" style="border-left:3px solid ${s.color};padding-left:0.55rem;">
        <span>${s.label}</span><span class="count">${ct.length}</span>
      </div>
      <div class="column-body" data-status="${s.key}">
        ${ct.map(c => renderCard(c)).join('')}
      </div>
    </div>`;
  }).join('');
  initDragDrop();
}

function renderCard(t) {
  const cc = (t.comments||[]).length;
  return `<div class="task-card" draggable="true" data-id="${esc(t.id)}" onclick="openTask('${esc(t.id)}')">
    <div class="title">${esc(t.title)}</div>
    <div class="meta">
      <span class="assignee">${esc(t.assignee||'unassigned')}</span>
      <span>${cc>0?`<span class="comments-badge">${cc} \u{1F4AC}</span>`:''} ${fmtDate(t.created_at)}</span>
    </div>
  </div>`;
}

// ── Drag & Drop ────────────────────────────────────────────────────────────
function initDragDrop() {
  let dragged = null;
  document.querySelectorAll('.task-card').forEach(card => {
    card.addEventListener('dragstart', e => { dragged = card; card.classList.add('dragging'); e.dataTransfer.effectAllowed = 'move'; });
    card.addEventListener('dragend', () => { card.classList.remove('dragging'); dragged = null; });
  });
  document.querySelectorAll('.column-body').forEach(col => {
    col.addEventListener('dragover', e => { e.preventDefault(); col.classList.add('drag-over'); });
    col.addEventListener('dragleave', () => col.classList.remove('drag-over'));
    col.addEventListener('drop', async e => {
      e.preventDefault(); col.classList.remove('drag-over');
      if (!dragged) return;
      const newStatus = col.dataset.status;
      const taskId = dragged.dataset.id;
      await api('PUT', `/api/tasks/${taskId}`, { status: newStatus });
      const t = tasks.find(x => x.id === taskId);
      if (t) t.status = newStatus;
      renderBoard();
    });
  });
}

// ── Drawer ─────────────────────────────────────────────────────────────────
let currentTaskId = null;

async function openTask(id) {
  currentTaskId = id;
  const t = await api('GET', `/api/tasks/${id}`);
  if (t.error) { showToast(t.error, 'error'); return; }
  document.getElementById('drawer-title').textContent = t.title;
  const cc = (t.comments||[]).length;
  document.getElementById('drawer-body').innerHTML = `
    <div class="drawer-field"><label>Title</label><input type="text" id="f-title" value="${esc(t.title)}"/></div>
    <div class="drawer-field"><label>Description</label><textarea id="f-body">${esc(t.body||'')}</textarea></div>
    <div class="drawer-field"><label>Assignee</label><select id="f-assignee">${profiles.map(p=>`<option value="${esc(p.name)}" ${t.assignee===p.name?'selected':''}>${esc(p.name)}</option>`).join('')}</select></div>
    <div class="drawer-field"><label>Status</label><select id="f-status">${STATUSES.map(s=>`<option value="${s.key}" ${t.status===s.key?'selected':''}>${s.label}</option>`).join('')}</select></div>
    <div class="drawer-field"><label>Comments (${cc})</label>
      <div id="comments-list">${cc===0?'<div style="color:#475569;font-size:0.75rem;">No comments</div>':''}
        ${(t.comments||[]).map(c=>`<div class="comment-item"><div class="comment-meta">${esc(c.author||'unknown')} &middot; ${fmtDate(c.created_at)}</div><div class="comment-body">${esc(c.body)}</div></div>`).join('')}
      </div>
      <div style="display:flex;gap:0.4rem;margin-top:0.4rem;">
        <input type="text" id="new-comment" placeholder="Add comment..." style="flex:1;padding:0.35rem;background:#020617;border:1px solid #334155;border-radius:6px;color:#e2e8f0;font-size:0.78rem;"/>
        <button class="btn btn-primary" onclick="addComment()" style="padding:0.35rem 0.6rem;">Post</button>
      </div>
    </div>
  `;
  document.getElementById('drawer').classList.add('active');
  document.getElementById('drawer-overlay').classList.add('active');
}

function closeDrawer() {
  document.getElementById('drawer').classList.remove('active');
  document.getElementById('drawer-overlay').classList.remove('active');
  currentTaskId = null;
}

async function saveTask() {
  if (!currentTaskId) return;
  const r = await api('PUT', `/api/tasks/${currentTaskId}`, {
    title: document.getElementById('f-title').value,
    body: document.getElementById('f-body').value,
    assignee: document.getElementById('f-assignee').value,
    status: document.getElementById('f-status').value,
  });
  if (!r.error) { showToast('Saved', 'success'); closeDrawer(); loadTasks(); }
  else showToast(r.error, 'error');
}

async function completeTask() {
  if (!currentTaskId) return;
  await api('PUT', `/api/tasks/${currentTaskId}`, { status: 'done' });
  showToast('Completed', 'success'); closeDrawer(); loadTasks();
}

async function blockTask() {
  if (!currentTaskId) return;
  const reason = prompt('Block reason:');
  if (reason === null) return;
  await api('PUT', `/api/tasks/${currentTaskId}`, { status: 'blocked' });
  await api('POST', `/api/tasks/${currentTaskId}/comments`, { body: '\u274c Blocked: ' + reason, author: 'human' });
  showToast('Blocked', 'success'); closeDrawer(); loadTasks();
}

async function deleteTask() {
  if (!currentTaskId) return;
  if (!confirm('Delete this task?')) return;
  await api('DELETE', `/api/tasks/${currentTaskId}`);
  showToast('Deleted', 'success'); closeDrawer(); loadTasks();
}

async function addComment() {
  if (!currentTaskId) return;
  const input = document.getElementById('new-comment');
  const body = input.value.trim();
  if (!body) return;
  await api('POST', `/api/tasks/${currentTaskId}/comments`, { body, author: 'human' });
  input.value = '';
  openTask(currentTaskId);
}

// ── New Task ───────────────────────────────────────────────────────────────
function showCreateForm() {
  document.getElementById('modal-overlay').classList.add('active');
  document.getElementById('new-assignee').innerHTML = profiles.map(p => `<option value="${esc(p.name)}" ${p.name==='default'?'selected':''}>${esc(p.name)}</option>`).join('');
  document.getElementById('new-status').innerHTML = STATUSES.map(s => `<option value="${s.key}" ${s.key==='todo'?'selected':''}>${s.label}</option>`).join('');
  setTimeout(() => document.getElementById('new-title').focus(), 100);
}

function hideCreateForm() { document.getElementById('modal-overlay').classList.remove('active'); document.getElementById('new-title').value = ''; document.getElementById('new-body').value = ''; }

async function submitTask() {
  const title = document.getElementById('new-title').value.trim();
  if (!title) return;
  await api('POST', `/api/boards/${currentBoard}/tasks`, {
    title, body: document.getElementById('new-body').value,
    assignee: document.getElementById('new-assignee').value,
    status: document.getElementById('new-status').value,
  });
  hideCreateForm(); loadTasks(); showToast('Task created', 'success');
}

// ── New Board ──────────────────────────────────────────────────────────────
function showCreateBoard() { document.getElementById('board-modal-overlay').classList.add('active'); setTimeout(() => document.getElementById('new-board-slug').focus(), 100); }
function hideCreateBoard() { document.getElementById('board-modal-overlay').classList.remove('active'); document.getElementById('new-board-slug').value = ''; }

async function submitBoard() {
  const slug = document.getElementById('new-board-slug').value.trim().toLowerCase();
  if (!slug) return;
  const r = await api('POST', '/api/boards', { slug });
  if (r.error) { showToast(r.error, 'error'); return; }
  hideCreateBoard(); await loadBoards(); currentBoard = slug; switchBoard(slug); showToast('Board created', 'success');
}

function switchBoard(slug) { currentBoard = slug; loadTasks(); }

// ── Search ─────────────────────────────────────────────────────────────────
function debouncedSearch() { clearTimeout(searchTimeout); searchTimeout = setTimeout(loadTasks, 300); }

// ── Keyboard ───────────────────────────────────────────────────────────────
document.addEventListener('keydown', e => {
  if (e.target.matches('input,textarea,select')) return;
  if (e.key === 'n' || e.key === 'N') { e.preventDefault(); showCreateForm(); }
  if (e.key === 'Escape') { closeDrawer(); hideCreateForm(); hideCreateBoard(); }
});

// ── Init ───────────────────────────────────────────────────────────────────
(async () => { await loadBoards(); await loadProfiles(); await loadTasks(); setInterval(loadTasks, 10000); })();
</script>
</body>
</html>"""

# ── Request Handler ─────────────────────────────────────────────────────────

class Handler(http.server.BaseHTTPRequestHandler):

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        if path == "" or path == "/": self._serve_html()
        elif path == "/api/boards": self._handle_get_boards()
        elif path == "/api/profiles": self._handle_get_profiles()
        elif path.startswith("/api/tasks/") and path.endswith("/comments"): self._handle_get_comments(path)
        elif path.startswith("/api/tasks/") and path.endswith("/links"): self._handle_get_links(path)
        elif path.startswith("/api/tasks/"): self._handle_get_task(path)
        elif path.startswith("/api/boards/") and path.endswith("/tasks"): self._handle_get_tasks(parsed)
        else: self.send_response(404); self.end_headers()

    def do_POST(self):
        try:
            parsed = urlparse(self.path); path = parsed.path.rstrip("/")
            if path == "/api/boards": self._handle_create_board()
            elif path.startswith("/api/tasks/") and path.endswith("/comments"): self._handle_create_comment(path)
            elif path.startswith("/api/tasks/") and path.endswith("/links"): self._handle_create_link(path)
            elif path.startswith("/api/boards/") and path.endswith("/tasks"): self._handle_create_task(path)
            else: self.send_response(404); self.end_headers()
        except Exception as e: self._handle_error(e)

    def do_PUT(self):
        try:
            parsed = urlparse(self.path); path = parsed.path.rstrip("/")
            if path.startswith("/api/tasks/"): self._handle_update_task(path)
            else: self.send_response(404); self.end_headers()
        except Exception as e: self._handle_error(e)

    def do_DELETE(self):
        try:
            parsed = urlparse(self.path); path = parsed.path.rstrip("/")
            if path.startswith("/api/tasks/") and "/links/" in path: self._handle_delete_link(path)
            elif path.startswith("/api/tasks/"): self._handle_delete_task(path)
            else: self.send_response(404); self.end_headers()
        except Exception as e: self._handle_error(e)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _serve_html(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(PAGE_HTML.encode())

    def _handle_get_boards(self):
        boards = [{"slug":"default","name":"Default","description":"","icon":"\U0001f4cb"}]
        boards_dir = KANBAN_DB.parent / "kanban" / "boards"
        if boards_dir.exists():
            for d in sorted(boards_dir.iterdir()):
                if d.is_dir() and (d/"kanban.db").exists():
                    boards.append({"slug":d.name,"name":d.name.replace("-"," ").replace("_"," ").title(),"description":"","icon":"\U0001f4cb"})
        self.json_response(boards)

    def _handle_create_board(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        slug = body.get("slug","").strip().lower()
        if not slug: self.json_response({"error":"Slug required"},400); return
        if not re.match(r'^[a-z0-9][a-z0-9_-]{0,63}$', slug): self.json_response({"error":"Invalid slug"},400); return
        if slug == "default": self.json_response({"error":"Cannot create board named 'default'"},400); return
        board_dir = KANBAN_DB.parent / "kanban" / "boards" / slug
        if board_dir.exists(): self.json_response({"error":"Board already exists"},409); return
        board_dir.mkdir(parents=True)
        shutil.copy2(str(KANBAN_DB), str(board_dir/"kanban.db"))
        self.json_response({"slug":slug,"name":slug.replace("-"," ").replace("_"," ").title()},201)

    def _handle_get_profiles(self):
        profiles = [{"name":"default","path":str(KANBAN_DB.parent)}]
        if PROFILES_DIR.exists():
            for d in sorted(PROFILES_DIR.iterdir()):
                if d.is_dir(): profiles.append({"name":d.name,"path":str(d)})
        self.json_response(profiles)

    def _handle_get_tasks(self, parsed):
        slug = parsed.path.split("/")[3]; conn, _ = board_conn(slug)
        if not conn: self.json_response({"error":"Board not found"},404); return
        params = parse_qs(parsed.query); args = []; q = "SELECT * FROM tasks WHERE 1=1"
        for col in ["status","assignee"]:
            v = params.get(col,[None])[0]
            if v: q += f" AND {col} = ?"; args.append(v)
        v = params.get("search",[None])[0]
        if v: q += " AND (title LIKE ? OR body LIKE ?)"; args.extend([f"%{v}%",f"%{v}%"])
        q += " ORDER BY created_at DESC"
        rows = conn.execute(q, args).fetchall(); conn.close()
        self.json_response([dict(r) for r in rows])

    def _handle_get_task(self, path):
        task_id = path.split("/")[3]; conn = get_db()
        row = conn.execute("SELECT * FROM tasks WHERE id = ?",(task_id,)).fetchone()
        if not row: conn.close(); self.json_response({"error":"Task not found"},404); return
        task = dict(row)
        task["comments"] = [dict(c) for c in conn.execute("SELECT * FROM task_comments WHERE task_id = ? ORDER BY created_at ASC",(task_id,)).fetchall()]
        task["parent_ids"] = [r[0] for r in conn.execute("SELECT parent_id FROM task_links WHERE child_id = ?",(task_id,)).fetchall()]
        task["child_ids"] = [r[0] for r in conn.execute("SELECT child_id FROM task_links WHERE parent_id = ?",(task_id,)).fetchall()]
        conn.close(); self.json_response(task)

    def _handle_create_task(self, path):
        slug = path.split("/")[3]; conn, _ = board_conn(slug)
        if not conn: self.json_response({"error":"Board not found"},404); return
        length = int(self.headers.get("Content-Length", 0)); body = json.loads(self.rfile.read(length) or b"{}")
        title = body.get("title","").strip()
        if not title: conn.close(); self.json_response({"error":"Title required"},400); return
        task_id = "t_" + os.urandom(4).hex(); now = int(time.time())
        conn.execute("INSERT INTO tasks (id,title,body,assignee,status,priority,created_by,created_at,started_at,completed_at,workspace_kind,workspace_path,branch_name,claim_lock,claim_expires,tenant,result,idempotency_key,consecutive_failures,worker_pid,last_failure_error,max_runtime_seconds,last_heartbeat_at,current_run_id,workflow_template_id,current_step_key,skills,model_override,max_retries,goal_mode,goal_max_turns,session_id) VALUES (?,?,?,?,?,0,'user',?,NULL,NULL,'scratch',NULL,NULL,NULL,NULL,NULL,NULL,NULL,0,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,0,NULL,NULL)",(task_id,title,body.get("body",""),body.get("assignee","default"),body.get("status","todo"),now))
        conn.commit()
        row = conn.execute("SELECT * FROM tasks WHERE id = ?",(task_id,)).fetchone(); conn.close()
        self.json_response(dict(row),201)

    def _handle_update_task(self, path):
        task_id = path.split("/")[3]; length = int(self.headers.get("Content-Length", 0)); body = json.loads(self.rfile.read(length) or b"{}")
        conn = get_db(); fields = []; args = []
        for f in ["title","body","assignee","status"]:
            if f in body: fields.append(f"{f} = ?"); args.append(body[f])
        if not fields: conn.close(); self.json_response({"error":"No fields to update"},400); return
        args.append(task_id); conn.execute(f"UPDATE tasks SET {','.join(fields)} WHERE id = ?",args); conn.commit()
        row = conn.execute("SELECT * FROM tasks WHERE id = ?",(task_id,)).fetchone(); conn.close()
        self.json_response(dict(row) if row else {"error":"Task not found"}, 200 if row else 404)

    def _handle_delete_task(self, path):
        task_id = path.split("/")[3]; conn = get_db()
        conn.execute("DELETE FROM task_comments WHERE task_id = ?",(task_id,))
        conn.execute("DELETE FROM task_links WHERE parent_id = ? OR child_id = ?",(task_id,task_id))
        conn.execute("DELETE FROM tasks WHERE id = ?",(task_id,)); conn.commit(); conn.close()
        self.json_response({"ok":True})

    def _handle_get_comments(self, path):
        task_id = path.split("/")[3]; conn = get_db()
        rows = conn.execute("SELECT * FROM task_comments WHERE task_id = ? ORDER BY created_at ASC",(task_id,)).fetchall()
        conn.close(); self.json_response([dict(r) for r in rows])

    def _handle_create_comment(self, path):
        task_id = path.split("/")[3]; length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        cb = body.get("body","").strip()
        if not cb: self.json_response({"error":"Comment body required"},400); return
        now = int(time.time()); conn = get_db()
        conn.execute("INSERT INTO task_comments (task_id,author,body,created_at) VALUES (?,?,?,?)",(task_id,body.get("author","human"),cb,now))
        conn.commit(); cid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        row = conn.execute("SELECT * FROM task_comments WHERE id = ?",(cid,)).fetchone(); conn.close()
        self.json_response(dict(row),201)

    def _handle_get_links(self, path):
        task_id = path.split("/")[3]; conn = get_db()
        ps = conn.execute("SELECT parent_id FROM task_links WHERE child_id = ?",(task_id,)).fetchall()
        cs = conn.execute("SELECT child_id FROM task_links WHERE parent_id = ?",(task_id,)).fetchall()
        conn.close(); self.json_response({"parent_ids":[r[0] for r in ps],"child_ids":[r[0] for r in cs]})

    def _handle_create_link(self, path):
        task_id = path.split("/")[3]; length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        pid = body.get("parent_id")
        if not pid: self.json_response({"error":"parent_id required"},400); return
        conn = get_db(); conn.execute("INSERT OR IGNORE INTO task_links (parent_id,child_id) VALUES (?,?)",(pid,task_id))
        conn.commit(); conn.close(); self.json_response({"ok":True})

    def _handle_delete_link(self, path):
        parts = path.split("/"); task_id = parts[3]; parent_id = parts[5]
        conn = get_db(); conn.execute("DELETE FROM task_links WHERE parent_id = ? AND child_id = ?",(parent_id,task_id))
        conn.commit(); conn.close(); self.json_response({"ok":True})

    def json_response(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type","application/json")
        self.send_header("Access-Control-Allow-Origin","*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def _handle_error(self, e):
        import traceback; print(f"ERROR: {e}"); traceback.print_exc()
        try: self.send_response(500); self.send_header("Content-Type","application/json"); self.send_header("Access-Control-Allow-Origin","*"); self.end_headers(); self.wfile.write(json.dumps({"error":str(e)}).encode())
        except: pass

    def log_message(self, fmt, *args): pass

def main():
    port = 7681
    server = http.server.HTTPServer(("127.0.0.1", port), Handler)
    print(f"Kanban WebUI running at http://127.0.0.1:{port}")
    print("Press Ctrl+C to stop.")
    try: server.serve_forever()
    except KeyboardInterrupt: print("\nShutting down."); server.server_close()

if __name__ == "__main__":
    main()
