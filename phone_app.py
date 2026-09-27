#!/usr/bin/env python3
"""
phone_app: the user's side of unique sign-up.

    python3 phone_app.py                     # asks for the code shown on the website
    python3 phone_app.py 1234-5678-9012 --port /dev/ttyUSB0

1. You type the 12-digit code from the website.
2. The app asks the central server what the code is for and shows you.
3. You tap your key (the Nano). It answers the server's challenge.
4. The app sends that answer to the central server, which tells the website
   whether you're new or already have an account.

The app never sees your personal details or the key's secret; it only relays.
"""

import argparse
import json
import re
import sys
import urllib.error
import urllib.request

from nano_client import Nano, NanoError, find_port


def call(server: str, method: str, path: str, body: dict = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(server + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise SystemExit(f"server: {json.load(e).get('error', e.reason)}")
    except OSError as e:
        raise SystemExit(f"can't reach the central server at {server}: {e}")


def main():
    p = argparse.ArgumentParser(description="kagi phone app (unique sign-up)")
    p.add_argument("code", nargs="?", help="the 12-digit code shown on the website")
    p.add_argument("--server", default="http://localhost:8000")
    p.add_argument("--port", help="the key's serial port (default: auto-detect)")
    a = p.parse_args()

    code = a.code or input("Enter the code shown on the website: ")
    code = re.sub(r"[\s-]", "", code)
    if not re.fullmatch(r"\d{12}", code):
        sys.exit("the code is 12 digits")

    ch = call(a.server, "GET", f"/api/challenges/{code}")
    if ch.get("type") != "unique_signup":
        sys.exit(f"this app doesn't handle {ch.get('type')!r} challenges")
    print(f"\n  {ch['site_name']} ({ch['site_id']}) is asking you to prove you're a unique person.")
    print("  It will learn only whether you already have an account there, nothing about you.\n")
    if input("Continue? [Y/n] ").strip().lower() not in ("", "y", "yes"):
        sys.exit("cancelled")

    try:
        nano = Nano(a.port or find_port())
        if nano.has_button:
            print("Tap the button on your key...")
        else:
            input("Press Enter to tap your key (no button wired on this Nano)... ")
        proof = nano.sign(ch["nonce"], ch["site_id"])
    except NanoError as e:
        sys.exit(f"key: {e}")

    print("Checking with the central server...")
    r = call(a.server, "POST", f"/api/challenges/{code}/response",
             {"key_id": nano.key_id, "proof": proof})
    if r["result"] == "new":
        print(f"Done. {ch['site_name']} will create your account. Go back to the website.")
    else:
        print(f"You already have an account on {ch['site_name']}. It has been told, "
              "and won't create another.")


if __name__ == "__main__":
    main()
