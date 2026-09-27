#!/usr/bin/env python3
"""
challenge_site: the user-facing site for the Zoom identity-check demo.

    python3 challenge_site.py                    # http://localhost:8002

1. The host presses "Create challenge" and types the name the other person
   claims to have.
2. The site makes a one-time 8-digit code, which the host pastes into the Zoom chat.
3. The other person types the code into desktop_app.py, which looks the
   challenge up here (GET /api/challenges/<code>) and checks it against their key.
4. The app reports the outcome (POST /api/challenges/<code>/result), and the
   host's page, which has been polling, shows Verified or Not verified.

Demo only: the result endpoint takes the app's word for it, with no proof.
"""

import argparse
import re
import secrets
import threading
import time

from flask import Flask, abort, jsonify, request

CHALLENGE_TTL = 15 * 60       # seconds a code stays valid
MAX_NAME = 64

STYLE = """
  :root { --bg:#fafafa; --ink:#111; --muted:#777; --line:#e2e2e2; --field:#fff;
          --btn:#111; --btn-ink:#fafafa; --shade:rgba(0,0,0,.25); }
  @media (prefers-color-scheme: dark) {
    :root { --bg:#0e0e0e; --ink:#f2f2f2; --muted:#8a8a8a; --line:#2a2a2a; --field:#161616;
            --btn:#f2f2f2; --btn-ink:#0e0e0e; --shade:rgba(0,0,0,.6); } }
  * { box-sizing:border-box; }
  body { margin:0; min-height:100vh; display:grid; place-items:center; padding:16px;
         background:var(--bg); color:var(--ink); font:16px/1.5 system-ui, -apple-system, sans-serif; }
  main { width:100%; max-width:360px; text-align:center; }
  .brand { font-size:13px; letter-spacing:.2em; text-transform:uppercase; color:var(--muted);
           margin-bottom:40px; }
  button { font:inherit; font-weight:600; border:0; border-radius:999px; cursor:pointer;
           background:var(--btn); color:var(--btn-ink); padding:14px 28px; }
  button:disabled { opacity:.4; cursor:default; }
  .big { font-size:20px; padding:22px 44px; }
  input { font:inherit; width:100%; padding:14px 16px; margin-bottom:12px; border-radius:12px;
          border:1px solid var(--line); background:var(--field); color:var(--ink); outline:none; }
  input:focus { border-color:var(--ink); }
  form button { width:100%; margin-top:8px; }
  .hidden { display:none !important; }
  .muted { color:var(--muted); }
  .error { color:#d33; font-size:14px; min-height:1.5em; margin:8px 0 0; }
"""

INDEX = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>kagi</title>
<style>""" + STYLE + """
  .overlay { position:fixed; inset:0; background:var(--shade); display:grid; place-items:center;
             padding:16px; }
  .modal { background:var(--bg); border:1px solid var(--line); border-radius:20px; padding:32px;
           width:100%; max-width:420px; text-align:center; }
  .modal h2 { margin:0 0 6px; font-size:20px; }
  .modal p { margin:0 0 20px; }
  .code { font:600 40px/1.2 ui-monospace, monospace; letter-spacing:.08em; margin:4px 0 24px; }
  .status { display:flex; align-items:center; justify-content:center; gap:10px; min-height:28px;
            margin-bottom:20px; color:var(--muted); }
  .dot { width:10px; height:10px; border-radius:50%; background:var(--muted);
         animation:pulse 1.2s ease-in-out infinite; }
  @keyframes pulse { 50% { opacity:.2; } }
  .modal.verified { background:#16a34a; border-color:#16a34a; color:#fff; }
  .modal.failed { background:#dc2626; border-color:#dc2626; color:#fff; }
  .modal.verified .muted, .modal.failed .muted, .modal.verified .status,
  .modal.failed .status, .modal.verified .close, .modal.failed .close { color:#fff; }
  .modal.verified #copy, .modal.failed #copy { display:none; }
  .flash { animation:flash .9s ease-out; }
  @keyframes flash { from { filter:brightness(1.25); } }
  .result { font-size:40px; font-weight:700; line-height:1.1; margin:4px 0 8px; }
  .close { background:none; color:var(--muted); font-weight:400; margin-top:16px; padding:8px; }
</style></head><body>
<main>
  <div class="brand">kagi</div>
  <button id="begin" class="big">Create challenge</button>
  <form id="form" class="hidden" autocomplete="off">
    <input id="first" placeholder="First name" maxlength="64" required>
    <input id="last" placeholder="Last name" maxlength="64" required>
    <button id="create" type="submit">Create challenge</button>
    <p id="err" class="error"></p>
  </form>
</main>
<div id="overlay" class="overlay hidden">
  <div class="modal" role="dialog" aria-modal="true" aria-labelledby="mtitle">
    <h2 id="mtitle">Challenge created</h2>
    <p id="hint" class="muted">Send this code in the Zoom chat.</p>
    <div id="code" class="code"></div>
    <div id="status" class="status"><span class="dot"></span><span id="stext">Waiting for their key</span></div>
    <button id="copy">Copy</button><br>
    <button id="close" class="close">Done</button>
  </div>
</div>
<script>
const $ = id => document.getElementById(id);
let watching = null;      // code being polled; cleared when the popup closes
async function watch(code) {
  if (watching !== code) return;
  let j = null;
  try {
    const r = await fetch('/api/challenges/' + code);
    j = r.ok ? await r.json() : {status: 'expired'};
  } catch { return setTimeout(watch, 1000, code); }
  if (watching !== code) return;
  if (j.status === 'waiting') return setTimeout(watch, 1000, code);
  const ok = j.status === 'verified', modal = document.querySelector('.modal');
  modal.classList.add(ok ? 'verified' : 'failed', 'flash');
  $('mtitle').className = 'result';
  $('mtitle').textContent = ok ? 'Verified' : j.status === 'failed' ? 'Not verified' : 'Code expired';
  $('hint').textContent = j.first_name ? j.first_name + ' ' + j.last_name : '';
  $('status').classList.add('hidden');
  $('code').classList.add('hidden');
}
$('begin').onclick = () => {
  $('begin').classList.add('hidden');
  $('form').classList.remove('hidden');
  $('first').focus();
};
$('form').onsubmit = async e => {
  e.preventDefault();
  $('err').textContent = '';
  $('create').disabled = true;
  try {
    const r = await fetch('/api/challenges', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({first_name: $('first').value, last_name: $('last').value})});
    const j = await r.json();
    if (!r.ok) throw new Error(j.error || 'Something went wrong.');
    $('code').textContent = j.code.replace(/(\\d{4})(\\d{4})/, '$1 $2');
    $('copy').textContent = 'Copy';
    $('mtitle').className = ''; $('mtitle').textContent = 'Challenge created';
    $('hint').textContent = 'Send this code in the Zoom chat.';
    document.querySelector('.modal').className = 'modal';
    ['status', 'code'].forEach(id => $(id).classList.remove('hidden'));
    $('overlay').classList.remove('hidden');
    watching = j.code; watch(j.code);
  } catch (err) {
    $('err').textContent = err.message || 'Could not reach the server.';
  } finally {
    $('create').disabled = false;
  }
};
$('copy').onclick = async () => {
  const text = $('code').textContent;
  try { await navigator.clipboard.writeText(text); }
  catch {                                  // no clipboard API on plain http off localhost
    const t = document.createElement('textarea');
    t.value = text; document.body.appendChild(t); t.select();
    document.execCommand('copy'); t.remove();
  }
  $('copy').textContent = 'Copied';
};
$('close').onclick = () => {
  watching = null;
  $('overlay').classList.add('hidden');
  $('form').reset();
  $('first').focus();
};
document.addEventListener('keydown', e => {
  if (e.key === 'Escape' && !$('overlay').classList.contains('hidden')) $('close').click();
});
</script></body></html>"""

class Challenges:
    def __init__(self):
        self.items = {}           # 8-digit code -> {first_name, last_name, expires}
        self.lock = threading.Lock()

    def _expire(self):
        now = time.time()
        for cid in [c for c, ch in self.items.items() if ch["expires"] < now]:
            del self.items[cid]

    def create(self, first: str, last: str) -> str:
        with self.lock:
            self._expire()
            while True:
                cid = f"{secrets.randbelow(10**8):08d}"
                if cid not in self.items:
                    break
            self.items[cid] = {"first_name": first, "last_name": last, "status": "waiting",
                               "expires": time.time() + CHALLENGE_TTL}
            return cid

    def get(self, cid: str):
        with self.lock:
            self._expire()
            ch = self.items.get(cid)
            return dict(ch) if ch else None

    def finish(self, cid: str, verified: bool) -> bool:
        """Records the outcome once. False if the code is unknown or already finished."""
        with self.lock:
            self._expire()
            ch = self.items.get(cid)
            if not ch or ch["status"] != "waiting":
                return False
            ch["status"] = "verified" if verified else "failed"
            return True


def clean_name(value) -> str:
    return " ".join(value.split())[:MAX_NAME] if isinstance(value, str) else ""


def normalize_code(code: str) -> str:
    return re.sub(r"[\s-]", "", code)


def create_app(challenges: Challenges) -> Flask:
    app = Flask(__name__)

    @app.get("/")
    def index():
        return INDEX

    @app.post("/api/challenges")
    def new_challenge():
        body = request.get_json(silent=True) or {}
        first, last = clean_name(body.get("first_name")), clean_name(body.get("last_name"))
        if not first or not last:
            return jsonify({"error": "Enter a first and last name."}), 400
        code = challenges.create(first, last)
        return jsonify({"code": code, "expires_in": CHALLENGE_TTL})

    @app.get("/api/challenges/<code>")
    def get_challenge(code):
        ch = challenges.get(normalize_code(code))
        if not ch:
            abort(404)
        return jsonify({"first_name": ch["first_name"], "last_name": ch["last_name"],
                        "status": ch["status"], "expires_in": int(ch["expires"] - time.time())})

    @app.post("/api/challenges/<code>/result")
    def set_result(code):
        body = request.get_json(silent=True) or {}
        if not isinstance(body.get("verified"), bool):
            return jsonify({"error": "send {\"verified\": true|false}"}), 400
        if not challenges.finish(normalize_code(code), body["verified"]):
            return jsonify({"error": "unknown, expired or already used code"}), 409
        return jsonify({"ok": True})

    return app


def main():
    p = argparse.ArgumentParser(description="kagi Zoom challenge site")
    p.add_argument("--port", type=int, default=8002)
    a = p.parse_args()
    create_app(Challenges()).run(host="127.0.0.1", port=a.port, threaded=True)


if __name__ == "__main__":
    main()
