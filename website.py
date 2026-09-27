#!/usr/bin/env python3
"""
website: a demo site that uses the central server for one-account-per-person sign-up.

    python3 central_server.py add-site shop.example "Example Shop"   # once
    python3 website.py                       # http://localhost:8001

The browser never talks to the central server, and the site never learns who
the user is: it gets back only "new" or "existing". It doesn't store the code.
"""

import argparse
import json
import secrets
import threading
import urllib.error
import urllib.request

from flask import Flask, jsonify

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{name}</title>
<style>
  :root {{ --bg:#f6f7f9; --card:#fff; --ink:#1b1f24; --muted:#5b6470; --accent:#2f6fed;
          --good:#1a7f37; --warn:#b35900; --line:#dde1e6; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg:#111418; --card:#1b2027; --ink:#e8ebef; --muted:#9aa4b1; --accent:#6b9bff;
            --good:#4cc26a; --warn:#f0a44b; --line:#2c333d; }} }}
  body {{ margin:0; font:16px/1.5 system-ui, sans-serif; background:var(--bg); color:var(--ink);
         display:grid; place-items:center; min-height:100vh; padding:16px; box-sizing:border-box; }}
  .card {{ background:var(--card); border:1px solid var(--line); border-radius:14px;
          padding:32px; max-width:440px; width:100%; text-align:center; }}
  h1 {{ margin:0 0 8px; font-size:24px; }}
  p {{ color:var(--muted); margin:8px 0; }}
  button {{ font:inherit; font-weight:600; padding:12px 22px; border:0; border-radius:10px;
           background:var(--accent); color:#fff; cursor:pointer; margin-top:12px; }}
  .code {{ font:600 34px/1.2 ui-monospace, monospace; letter-spacing:2px; margin:18px 0 6px; }}
  .good {{ color:var(--good); font-weight:600; }} .warn {{ color:var(--warn); font-weight:600; }}
  .hidden {{ display:none; }}
</style></head><body>
<div class="card">
  <h1>{name}</h1>
  <div id="start"><p>Create your account. We only allow one per person, and we never see who you are.</p>
    <button onclick="start()">Sign up</button></div>
  <div id="wait" class="hidden">
    <p>Open the kagi app on your phone and enter:</p>
    <div class="code" id="code"></div>
    <p id="left"></p></div>
  <div id="done" class="hidden"><p id="msg"></p>
    <button onclick="location.reload()">Start over</button></div>
</div>
<script>
let token = null;
const show = id => ['start','wait','done'].forEach(x =>
  document.getElementById(x).classList.toggle('hidden', x !== id));
function finish(cls, text) {{
  const m = document.getElementById('msg'); m.className = cls; m.textContent = text; show('done');
}}
async function start() {{
  const r = await fetch('/signup/start', {{method: 'POST'}});
  const j = await r.json();
  if (!r.ok) return finish('warn', j.error || 'Could not reach the sign-up service.');
  token = j.token;
  document.getElementById('code').textContent = j.code.replace(/(\\d{{4}})(?=\\d)/g, '$1 ');
  show('wait'); poll();
}}
async function poll() {{
  const r = await fetch('/signup/status/' + token);
  const j = await r.json();
  if (j.status === 'waiting') {{
    document.getElementById('left').textContent = 'Code expires in ' + j.expires_in + ' s';
    return setTimeout(poll, 1000);
  }}
  if (j.status === 'created') finish('good', 'Welcome! Your account ' + j.account + ' is ready.');
  else if (j.status === 'existing') finish('warn', 'You already have an account here. One per person.');
  else finish('warn', 'That code expired or failed. Please try again.');
}}
</script></body></html>"""


class Site:
    def __init__(self, creds: dict):
        self.creds = creds
        self.pending = {}       # browser token -> code; removed once resolved
        self.accounts = []      # random ids; nothing about the person
        self.lock = threading.Lock()

    def call(self, method: str, path: str) -> dict:
        req = urllib.request.Request(
            self.creds["server"] + path, method=method,
            headers={"Authorization": "Bearer " + self.creds["api_key"]})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            return json.load(e)


def create_app(site: Site) -> Flask:
    app = Flask(__name__)

    @app.get("/")
    def index():
        return PAGE.format(name=site.creds["name"])

    @app.post("/signup/start")
    def start():
        try:
            j = site.call("POST", "/api/challenges")
        except OSError:
            return jsonify({"error": "sign-up service unreachable"}), 502
        if "code" not in j:
            return jsonify({"error": j.get("error", "sign-up service error")}), 502
        token = secrets.token_urlsafe(16)
        with site.lock:
            site.pending[token] = j["code"]
        return jsonify({"token": token, "code": j["code"]})

    @app.get("/signup/status/<token>")
    def status(token):
        with site.lock:
            code = site.pending.get(token)
        if not code:
            return jsonify({"status": "expired"})
        try:
            j = site.call("GET", f"/api/challenges/{code}/result")
        except OSError:
            return jsonify({"status": "waiting", "expires_in": "?"})
        if j.get("status") == "waiting":
            return jsonify(j)
        with site.lock:
            site.pending.pop(token, None)
        if j.get("status") != "complete":
            return jsonify({"status": "expired"})
        if j["result"] == "existing":
            return jsonify({"status": "existing"})
        account = secrets.token_hex(4)
        with site.lock:
            site.accounts.append(account)
        print(f"created account {account} ({len(site.accounts)} total)")
        return jsonify({"status": "created", "account": account})

    return app


def main():
    p = argparse.ArgumentParser(description="demo website using kagi unique sign-up")
    p.add_argument("--creds", default="website_credentials.json")
    p.add_argument("--port", type=int, default=8001)
    a = p.parse_args()
    try:
        creds = json.load(open(a.creds))
    except FileNotFoundError:
        raise SystemExit(f"{a.creds} not found: run  central_server.py add-site <id> <name>  first")
    create_app(Site(creds)).run(port=a.port, threaded=True)


if __name__ == "__main__":
    main()
