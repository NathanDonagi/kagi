#!/usr/bin/env python3
"""
central_server: the unique sign-up service for kagi Nano keys.

Flow
----
1. Website -> server   POST /api/challenges            (site API key)
                       <- 12-digit code, shown to the user on the website
2. Phone   -> server   GET  /api/challenges/<code>
                       <- {type: "unique_signup", site, nonce}
3. Phone   -> key      SIGN <nonce> <site_id>          (the user taps the key)
                       <- HMAC(device_secret, "kagi-nano-sign-v1|key id|site|nonce")
4. Phone   -> server   POST /api/challenges/<code>/response  {key_id, proof}
                       server checks the proof, maps key -> person -> per-site mark,
                       and records "new" (mark added) or "existing" (mark was there)
5. Website -> server   GET  /api/challenges/<code>/result   (site API key)
                       <- {status: "complete", result: "new" | "existing"}
                       the challenge is then deleted

Age checks use the same five steps with {"type": "age_check", "over": 18} in
step 1. At step 3 the app asks the key AUTH <nonce> over=18 (no name needed),
and at step 4 it relays the key's proof, HMAC(device_secret, "kagi-nano-v1|key id|OVER18|nonce"),
or {"declined": true} if the key said no. The website gets "verified" or "failed".

What each party learns
----------------------
* Website: only "new" or "existing". No name, no key id, nothing reusable.
* Phone: the site name and nonce. It never holds the device secret.
* Server: that some registered person signed up at this site. It stores only
  opaque per-site marks, scrypt(HMAC(pepper, "mark|site|person")), and deletes
  the challenge (the only thing tying a sign-up session to a person) as soon as
  the website collects the result. Unlike unique_account.py's blind-signature
  protocol this is NOT unlinkable against a server that is compromised while
  running: it sees the (person, site, session) link at step 4, and would learn
  which account is whose if it logged that and the website logged codes.

Usage
-----
    python3 central_server.py add-site shop.example "Example Shop"
        -> registers the site and writes website_credentials.json (its API key)
    python3 central_server.py serve                 # http://localhost:8000
    python3 central_server.py forget-site shop.example
        -> deletes every registered person's mark for that site, so the demo can
           sign up again (works while the server is running)
"""

import argparse
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import threading
import time
from pathlib import Path

from flask import Flask, jsonify, request

HERE = Path(__file__).resolve().parent
DATA = HERE / "central_data"
REGISTRY = HERE / "nano_registry.json"

CODE_TTL = 300            # seconds a code stays valid
MAX_BAD_PROOFS = 3        # wrong answers before a challenge is burnt
MARK_SCRYPT_N = 2**17     # ~128 MiB, ~0.25 s per guess
AGE_THRESHOLDS = (18, 21) # what the key can answer
SITE_ID = re.compile(r"[a-z0-9.-]{1,64}")
FIXED_CODES = {"blindgram": "744915652364"}  # testing: the site always gets this code,
                                             # and a new challenge replaces the old one


# ---------- persistent state ----------

def _read_json(path: Path, default):
    return json.loads(path.read_text()) if path.exists() else default


def _write_private(path: Path, data: bytes):
    tmp = path.with_suffix(".tmp")
    with open(tmp, "wb") as f:
        os.fchmod(f.fileno(), 0o600)
        f.write(data)
    tmp.replace(path)


def load_pepper() -> bytes:
    """Long-term secret for the marks. Losing it silently resets the one-account rule;
    in production keep it in an HSM/KMS, away from marks.json."""
    DATA.mkdir(exist_ok=True)
    path = DATA / "pepper.key"
    if not path.exists():
        _write_private(path, secrets.token_bytes(32))
    return path.read_bytes()


def api_key_hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def compute_mark(pepper: bytes, person: str, site_id: str) -> str:
    inner = hmac.new(pepper, f"mark|{site_id}|{person}".encode(), "sha256").digest()
    return hashlib.scrypt(inner, salt=b"kagi-central-mark-v1", n=MARK_SCRYPT_N, r=8, p=1,
                          maxmem=256 * 1024 * 1024, dklen=32).hex()


# ---------- server ----------

class CentralServer:
    def __init__(self, registry_path: Path = REGISTRY):
        self.registry_path = registry_path
        self.pepper = load_pepper()
        self.sites = _read_json(DATA / "sites.json", {})
        self.marks = set(_read_json(DATA / "marks.json", []))
        self.challenges = {}          # code -> dict; in memory only, deleted when done
        self.lock = threading.Lock()

    def _save_marks(self):
        _write_private(DATA / "marks.json", json.dumps(sorted(self.marks)).encode())

    def _mark(self, person: str, site_id: str) -> str:
        return compute_mark(self.pepper, person, site_id)

    def _expire(self):
        now = time.time()
        for code in [c for c, ch in self.challenges.items() if ch["expires"] < now]:
            del self.challenges[code]

    def site_for(self, auth_header: str):
        """Returns the site id whose API key is in `Authorization: Bearer <key>`."""
        if not auth_header or not auth_header.startswith("Bearer "):
            return None
        h = api_key_hash(auth_header[7:].strip())
        for site_id, site in self.sites.items():
            if hmac.compare_digest(site["api_key_sha256"], h):
                return site_id
        return None

    def new_challenge(self, site_id: str, kind: str = "unique_signup", over: int = None) -> str:
        with self.lock:
            self._expire()
            code = FIXED_CODES.get(site_id)
            while code is None:
                code = f"{secrets.randbelow(10**12):012d}"
                if code in self.challenges or code in FIXED_CODES.values():
                    code = None
            self.challenges[code] = {
                "type": kind, "over": over, "site_id": site_id, "nonce": secrets.token_hex(16),
                "expires": time.time() + CODE_TTL, "state": "waiting", "result": None,
                "bad_proofs": 0,
            }
        return code

    def get_challenge(self, code: str):
        with self.lock:
            self._expire()
            ch = self.challenges.get(code)
            return dict(ch) if ch else None

    def respond(self, code: str, body: dict) -> str:
        """Checks the key's answer. Returns "new" or "existing" for a sign-up,
        "verified" or "declined" for an age check; raises ValueError."""
        with self.lock:
            self._expire()
            ch = self.challenges.get(code)
            if not ch:
                raise ValueError("unknown or expired code")
            if ch["state"] != "waiting":
                raise ValueError("this code has already been used")
            site_id, nonce = ch["site_id"], ch["nonce"]
            if ch["type"] == "age_check" and body.get("declined") is True:
                ch["state"] = "failed"                  # the key said no (or the name was wrong)
                return "declined"

        key_id = body.get("key_id")
        if ch["type"] == "age_check":
            msg = f"kagi-nano-v1|{key_id}|OVER{ch['over']}|{nonce}"
        else:
            msg = f"kagi-nano-sign-v1|{key_id}|{site_id}|{nonce}"
        rec = self._check_proof(key_id, msg, body.get("proof"))
        if not rec:
            with self.lock:
                ch["bad_proofs"] += 1
                if ch["bad_proofs"] >= MAX_BAD_PROOFS:
                    ch["state"] = "failed"
            raise ValueError("the key's answer didn't verify (unknown, expired or wrong key)")

        if ch["type"] == "age_check":
            with self.lock:
                if ch["state"] != "waiting":
                    raise ValueError("this code has already been used")
                ch["state"], ch["result"] = "complete", "verified"
            return "verified"

        mark = self._mark(rec["person"], site_id)       # slow (scrypt): outside the lock
        with self.lock:
            if ch["state"] != "waiting":                # someone else answered meanwhile
                raise ValueError("this code has already been used")
            # re-read so `forget-site` takes effect without a restart
            self.marks = set(_read_json(DATA / "marks.json", []))
            result = "existing" if mark in self.marks else "new"
            if result == "new":
                self.marks.add(mark)
                self._save_marks()
            ch["state"], ch["result"] = "complete", result
        return result

    def _check_proof(self, key_id, msg: str, proof_hex):
        """The key's registry record if proof is its HMAC over msg and it hasn't expired."""
        registry = _read_json(self.registry_path, {})   # re-read: new keys work without restart
        rec = registry.get(key_id) if isinstance(key_id, str) else None
        if not rec or time.strftime("%Y-%m-%d") > rec["expires"]:
            return None
        want = hmac.new(bytes.fromhex(rec["device_secret"]), msg.encode(), "sha256").digest()
        try:
            return rec if hmac.compare_digest(want, bytes.fromhex(proof_hex)) else None
        except (TypeError, ValueError):
            return None

    def result(self, code: str, site_id: str) -> dict:
        with self.lock:
            self._expire()
            ch = self.challenges.get(code)
            if not ch or ch["site_id"] != site_id:
                return {"status": "expired"}
            if ch["state"] == "waiting":
                return {"status": "waiting", "expires_in": int(ch["expires"] - time.time())}
            del self.challenges[code]                   # nothing left that ties session to person
            if ch["state"] == "failed":
                return {"status": "failed"}
            return {"status": "complete", "result": ch["result"]}


def normalize_code(code: str) -> str:
    return re.sub(r"[\s-]", "", code or "")


def create_app(server: CentralServer) -> Flask:
    app = Flask(__name__)

    def err(msg, status):
        return jsonify({"error": msg}), status

    @app.post("/api/challenges")
    def api_new_challenge():
        site_id = server.site_for(request.headers.get("Authorization"))
        if not site_id:
            return err("bad or missing site API key", 401)
        body = request.get_json(silent=True) or {}
        kind, over = body.get("type", "unique_signup"), None
        if kind == "age_check":
            over = body.get("over", 18)
            if over not in AGE_THRESHOLDS:
                return err(f"over must be one of {AGE_THRESHOLDS}", 400)
        elif kind != "unique_signup":
            return err("type must be unique_signup or age_check", 400)
        return jsonify({"code": server.new_challenge(site_id, kind, over), "expires_in": CODE_TTL})

    @app.get("/api/challenges/<code>")
    def api_get_challenge(code):
        ch = server.get_challenge(normalize_code(code))
        if not ch or ch["state"] != "waiting":
            return err("unknown, expired or already used code", 404)
        return jsonify({
            "type": ch["type"], "site_id": ch["site_id"],
            "site_name": server.sites[ch["site_id"]]["name"], "nonce": ch["nonce"],
            "expires_in": int(ch["expires"] - time.time()),
            **({"over": ch["over"]} if ch["type"] == "age_check" else {}),
        })

    @app.post("/api/challenges/<code>/response")
    def api_respond(code):
        body = request.get_json(silent=True) or {}
        try:
            result = server.respond(normalize_code(code), body)
        except ValueError as e:
            return err(str(e), 400)
        return jsonify({"status": "complete", "result": result})

    @app.get("/api/challenges/<code>/result")
    def api_result(code):
        site_id = server.site_for(request.headers.get("Authorization"))
        if not site_id:
            return err("bad or missing site API key", 401)
        return jsonify(server.result(normalize_code(code), site_id))

    return app


# ---------- CLI ----------

def cmd_add_site(a):
    if not SITE_ID.fullmatch(a.site_id):
        raise SystemExit("site id must be lowercase letters, digits, '.' and '-'")
    DATA.mkdir(exist_ok=True)
    sites = _read_json(DATA / "sites.json", {})
    api_key = secrets.token_urlsafe(32)
    sites[a.site_id] = {"name": a.name, "api_key_sha256": api_key_hash(api_key)}
    _write_private(DATA / "sites.json", json.dumps(sites, indent=2).encode())
    creds = {"server": a.server, "site_id": a.site_id, "name": a.name, "api_key": api_key}
    _write_private(Path(a.out), json.dumps(creds, indent=2).encode())
    print(f"registered {a.site_id} ({a.name}); API key written to {a.out}")


def cmd_forget_site(a):
    registry = _read_json(Path(a.registry), {})
    pepper = load_pepper()
    persons = {rec["person"] for rec in registry.values()}
    doomed = {compute_mark(pepper, person, a.site_id) for person in persons}
    marks = set(_read_json(DATA / "marks.json", []))
    _write_private(DATA / "marks.json", json.dumps(sorted(marks - doomed)).encode())
    print(f"forgot {len(marks & doomed)} mark(s) for {a.site_id} "
          f"({len(persons)} registered person(s) checked)")


def cmd_serve(a):
    server = CentralServer(Path(a.registry))
    print(f"{len(server.sites)} site(s), {len(server.marks)} mark(s) stored")
    # No request log: codes, timestamps and IPs are exactly what would let
    # someone line up a sign-up session with a person afterwards.
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    create_app(server).run(host=a.host, port=a.port, threaded=True)


def main():
    p = argparse.ArgumentParser(description="kagi central unique sign-up server")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("add-site", help="register a website and create its API key")
    s.add_argument("site_id")
    s.add_argument("name")
    s.add_argument("--out", default="website_credentials.json")
    s.add_argument("--server", default="http://localhost:8000",
                   help="URL the website should use to reach this server")
    s.set_defaults(fn=cmd_add_site)
    s = sub.add_parser("serve", help="run the HTTP API")
    s.add_argument("--host", default="127.0.0.1",
                   help="use 0.0.0.0 to let a real phone on your network reach it")
    s.add_argument("--port", type=int, default=8000)
    s.add_argument("--registry", default=str(REGISTRY))
    s.set_defaults(fn=cmd_serve)
    s = sub.add_parser("forget-site", help="delete every registered person's mark for a site "
                                           "(demo reset)")
    s.add_argument("site_id")
    s.add_argument("--registry", default=str(REGISTRY))
    s.set_defaults(fn=cmd_forget_site)
    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
