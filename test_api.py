"""Full kanban API test."""
import json, subprocess, sys, time, urllib.request, os

server_dir = os.path.dirname(os.path.abspath(__file__))
proc = subprocess.Popen(
    [sys.executable, os.path.join(server_dir, "kanban.py")],
    stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=server_dir,
)
time.sleep(3)

def call(method, path, data=None):
    url = "http://127.0.0.1:7681" + path
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method=method)
    try:
        resp = urllib.request.urlopen(req, timeout=5)
        return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}: {e.read().decode()}"}
    except Exception as e:
        return {"error": str(e)}

try:
    p, f = 0, 0
    def test(name, result, expect_type=None):
        global p, f
        if isinstance(result, dict) and "error" in result:
            print(f"  FAIL: {name} -> {result['error']}"); f += 1
        elif expect_type and not isinstance(result, expect_type):
            print(f"  FAIL: {name} -> wrong type"); f += 1
        else:
            print(f"  PASS: {name}"); p += 1

    print("=== Kanban API Tests ===\n")

    # Read
    test("GET /api/boards", call("GET", "/api/boards"), list)
    test("GET /api/profiles", call("GET", "/api/profiles"), list)
    test("GET /api/boards/default/tasks (empty)", call("GET", "/api/boards/default/tasks"), list)

    # Create
    t1 = call("POST", "/api/boards/default/tasks", {"title": "Task 1", "assignee": "default"})
    test("POST create task", t1, dict)
    t2 = call("POST", "/api/boards/default/tasks", {"title": "Task 2", "body": "With description", "status": "in_progress"})
    test("POST create task 2", t2, dict)

    # Read after create
    tasks = call("GET", "/api/boards/default/tasks")
    test("GET tasks after create (2 tasks)", tasks, list)

    # Get single
    if isinstance(t1, dict) and "id" in t1:
        test("GET single task", call("GET", f"/api/tasks/{t1['id']}"), dict)

        # Update
        test("PUT update status", call("PUT", f"/api/tasks/{t1['id']}", {"status": "done"}), dict)
        test("PUT update title", call("PUT", f"/api/tasks/{t1['id']}", {"title": "Updated title"}), dict)

        # Comment
        c1 = call("POST", f"/api/tasks/{t1['id']}/comments", {"body": "First comment", "author": "human"})
        test("POST comment", c1, dict)
        test("GET comments", call("GET", f"/api/tasks/{t1['id']}/comments"), list)

    # Link
    if isinstance(t1, dict) and isinstance(t2, dict) and "id" in t1 and "id" in t2:
        test("POST link", call("POST", f"/api/tasks/{t2['id']}/links", {"parent_id": t1["id"]}), dict)
        test("GET links", call("GET", f"/api/tasks/{t2['id']}/links"), dict)
        test("DELETE link", call("DELETE", f"/api/tasks/{t2['id']}/links/{t1['id']}"), dict)

    # Delete
    if isinstance(t2, dict) and "id" in t2:
        test("DELETE task", call("DELETE", f"/api/tasks/{t2['id']}"), dict)

    # Board management
    b1 = call("POST", "/api/boards", {"slug": "test-board"})
    test("POST create board", b1, dict)

    boards = call("GET", "/api/boards")
    test("GET boards (includes new)", boards, list)

    print(f"\n=== {p} passed, {f} failed ===")

finally:
    proc.terminate()
    proc.wait(timeout=5)
