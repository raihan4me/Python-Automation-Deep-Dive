"""Flaky inventory API: local stand-in for a real CMDB/inventory service."""
import os
import threading

from flask import Flask, jsonify, request

app = Flask(__name__)
TOKEN = os.environ.get("API_TOKEN", "opskit-token")
FLAKY_EVERY = int(os.environ.get("FLAKY_EVERY", "3"))
PER_PAGE = 5
_lock = threading.Lock()
_counter = {"n": 0}

HOSTS = []
for role, count in (("web", 4), ("app", 4), ("db", 2), ("cache", 2)):
    for i in range(1, count + 1):
        HOSTS.append({
            "name": f"{role}{i:02d}",
            "role": role,
            "env": "prod" if i <= count // 2 else "staging",
            "ip": f"10.20.0.{len(HOSTS) + 10}",
            "maintenance": False,
        })


@app.before_request
def auth_and_chaos():
    if not request.path.startswith("/api/"):
        return None
    if request.headers.get("Authorization") != f"Bearer {TOKEN}":
        return jsonify(error="unauthorized"), 401
    if FLAKY_EVERY > 0 and request.method == "GET":
        with _lock:
            _counter["n"] += 1
            n = _counter["n"]
        if n % FLAKY_EVERY == 0:
            return jsonify(error="temporarily unavailable"), 503
    return None


@app.get("/health")
def health():
    return jsonify(status="ok", flaky_every=FLAKY_EVERY)


@app.get("/api/hosts")
def list_hosts():
    try:
        page = int(request.args.get("page", "1"))
    except ValueError:
        return jsonify(error="page must be an integer"), 400
    pages = (len(HOSTS) + PER_PAGE - 1) // PER_PAGE
    if page < 1 or page > pages:
        return jsonify(error="page out of range"), 404
    start = (page - 1) * PER_PAGE
    return jsonify(page=page, pages=pages, total=len(HOSTS), items=HOSTS[start:start + PER_PAGE])


@app.post("/api/hosts/<name>/maintenance")
def set_maintenance(name):
    body = request.get_json(silent=True) or {}
    for host in HOSTS:
        if host["name"] == name:
            host["maintenance"] = bool(body.get("enabled", True))
            return jsonify(host)
    return jsonify(error="not found"), 404


if __name__ == "__main__":
    app.run(host=os.environ.get("BIND", "127.0.0.1"), port=int(os.environ.get("PORT", "5000")))
