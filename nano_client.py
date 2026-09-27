#!/usr/bin/env python3
"""
nano_client: the PC-side verifier for a kagi Arduino Nano.

Sends queries to the Nano over USB serial and checks its answers. The key
never leaves the Nano; this script only ever sees yes/no plus a proof.

Each query carries a fresh random challenge. On success the Nano returns
    AUTHENTICATED <scope> HMAC(device_secret, "kagi-nano-v1|<id>|<scope>|<challenge>")
which this script checks with the device secret from nano_registry.json
(written by nano_provision.py). A forged or replayed answer fails the check.

    pip install pyserial
    python3 nano_client.py info
    python3 nano_client.py verify first_name=Nathan last_name=Donagi over=21
    python3 nano_client.py verify first_name=Nathan last_name=Donagi dob=2005-09-21 \
                                  ssn=123-45-6789 pin=4821
    python3 nano_client.py demo       # runs the full test list against the Nano
    python3 nano_client.py shell      # type queries interactively

Use --port to pick the serial port (e.g. /dev/ttyUSB0, /dev/ttyACM0, COM5);
otherwise the first Arduino-looking port is used.
"""

import argparse
import datetime
import hashlib
import hmac
import json
import secrets
import shlex
import sys
import time
from pathlib import Path

try:
    import serial
    import serial.tools.list_ports
except ImportError:
    sys.exit("pyserial is required: pip install pyserial")

REGISTRY = Path(__file__).resolve().parent / "nano_registry.json"
BAUD = 115200
FIELDS = {"first_name", "last_name", "dob", "ssn", "pin", "over"}


class NanoError(Exception):
    pass


def find_port() -> str:
    ports = list(serial.tools.list_ports.comports())
    hints = ("arduino", "ch340", "ch341", "ftdi", "usb serial", "usb-serial", "cp210")
    for p in ports:
        text = f"{p.description} {p.manufacturer or ''}".lower()
        if any(h in text for h in hints) or "ttyUSB" in p.device or "ttyACM" in p.device:
            return p.device
    listing = ", ".join(p.device for p in ports) or "none"
    raise NanoError(f"no Arduino found (ports: {listing}); pass --port")


class Nano:
    """Serial connection to the key. `registry` (key_id -> record) is only
    needed for query(); the phone app just relays SIGN answers and has none."""

    def __init__(self, port: str, registry: dict = None):
        # `port` is a device name, or an already-open serial-like object (see desktop_app.py)
        self.ser = port if hasattr(port, "readline") else serial.Serial(port, BAUD, timeout=0.1)
        self._partial = b""     # start of a line that hasn't finished arriving
        self._wait_ready()
        info = self.info()
        self.key_id = info.get("id")
        self.has_button = info.get("tap") == "1"
        if registry is not None:
            if self.key_id not in registry:
                raise NanoError(f"Nano holds key {self.key_id}, which isn't in nano_registry.json. "
                                "Re-run nano_provision.py and re-upload.")
            self.v = registry[self.key_id]
            self.secret = bytes.fromhex(self.v["device_secret"])

    def _wait_ready(self):
        """Opening the port may reset the Nano (it then prints READY once booted) or
        not (it's already running, and says PONG). Ping every half second meanwhile;
        a ping that lands in the bootloader just makes it start the sketch sooner."""
        deadline, next_ping = time.time() + 8, 0
        while time.time() < deadline:
            if time.time() >= next_ping:
                self.ser.write(b"PING\n")
                next_ping = time.time() + 0.5
            line = self._readline(0.1)
            if line.startswith(("READY", "PONG")):
                return
        raise NanoError("the Nano didn't answer; is kagi_nano.ino uploaded?")

    def _send(self, line: str):
        self.ser.reset_input_buffer()
        self._partial = b""
        self.ser.write(line.encode() + b"\n")

    def _readline(self, timeout: float = 0.5) -> str:
        """The next complete line, or "" if none finished arriving in time. A line cut
        off by the timeout is kept for the next call rather than returned in pieces."""
        deadline = time.time() + timeout
        while b"\n" not in self._partial and time.time() < deadline:
            self._partial += self.ser.readline()
        if b"\n" not in self._partial:
            return ""
        line, self._partial = self._partial.split(b"\n", 1)
        return line.decode(errors="replace").strip()

    def info(self) -> dict:
        self._send("INFO")
        deadline = time.time() + 3
        while time.time() < deadline:   # skip leftovers, e.g. a second PONG from _wait_ready
            line = self._readline(0.5)
            if line.startswith("INFO "):
                return dict(kv.split("=", 1) for kv in line.split()[1:])
        raise NanoError("the Nano didn't answer INFO")

    def sign(self, nonce: str, site_id: str, on_tap=None) -> str:
        """Answer a unique sign-up challenge. Returns the proof hex. If the Nano
        has a tap button it replies TAP first; on_tap() is called then."""
        self._send(f"SIGN {nonce} {site_id}")
        deadline = time.time() + 40
        while time.time() < deadline:
            line = self._readline(1)
            if line == "TAP":
                if on_tap:
                    on_tap()
            elif line.startswith("SIGNED "):
                return line.split()[1]
            elif line == "TIMEOUT":
                raise NanoError("the key wasn't tapped in time")
            elif line.startswith("ERR"):
                raise NanoError(line)
        raise NanoError("timed out waiting for the Nano")

    def expected_proof(self, scope: str, challenge: str) -> bytes:
        msg = f"kagi-nano-v1|{self.v['key_id']}|{scope}|{challenge}".encode()
        return hmac.new(self.secret, msg, hashlib.sha256).digest()

    def auth(self, fields: dict, challenge: str):
        """Sends AUTH and returns the Nano's answer unchecked: ("AUTHENTICATED", scope,
        proof_hex), ("DENIED", "", None) or ("LOCKED", seconds, None). query() checks
        the proof itself; the desktop app relays it to the central server instead."""
        bad = set(fields) - FIELDS
        if bad:
            raise NanoError(f"unknown fields: {sorted(bad)} (allowed: {sorted(FIELDS)})")
        if any(c in str(v) for v in fields.values() for c in ";\r\n"):
            raise NanoError("values can't contain ';' or newlines")
        body = ";".join(f"{k}={v}" for k, v in fields.items())
        self._send(f"AUTH {challenge} {body}")

        deadline = time.time() + 60   # a check takes ~1-2 s; generous for slow clones
        while time.time() < deadline:
            line = self._readline(1)
            if not line or line == "WORKING":
                continue
            parts = line.split()
            if parts[0] == "AUTHENTICATED" and len(parts) == 3:
                return "AUTHENTICATED", parts[1], parts[2]
            if parts[0] == "DENIED":
                return "DENIED", "", None
            if parts[0] == "LOCKED":
                return "LOCKED", parts[1], None
            if parts[0] == "ERR":
                raise NanoError(line)
        raise NanoError("timed out waiting for the Nano")

    def query(self, fields: dict):
        """Returns (status, detail). status is AUTHENTICATED, DENIED, LOCKED or FORGED."""
        challenge = secrets.token_hex(16)
        status, detail, proof = self.auth(fields, challenge)
        if status == "AUTHENTICATED":
            if not hmac.compare_digest(bytes.fromhex(proof), self.expected_proof(detail, challenge)):
                return "FORGED", "proof did not verify: not this Nano, or a replay"
            if datetime.date.today().isoformat() > self.v["expires"]:
                return "DENIED", f"key expired on {self.v['expires']}"
        if status == "LOCKED":
            return "LOCKED", f"too many wrong guesses, wait {detail} s"
        return status, detail


def parse_fields(items) -> dict:
    fields = {}
    for item in items:
        if "=" not in item:
            raise NanoError(f"expected field=value, got {item!r}")
        k, v = item.split("=", 1)
        fields[k.strip()] = v
    return fields


def show(status, detail, elapsed):
    note = f" {detail}" if detail else ""
    print(f"{status}{note}  ({elapsed:.1f} s)")


def run_verify(nano, items) -> bool:
    t = time.time()
    status, detail = nano.query(parse_fields(items))
    show(status, detail, time.time() - t)
    return status == "AUTHENTICATED"


# Facts provisioned for the demo. Only this script's test list knows them;
# the Nano stores commitments only.
DEMO = {"first_name": "Nathan", "last_name": "Donagi", "dob": "2005-09-21",
        "ssn": "123456789", "pin": "4821"}


def run_demo(nano, verifier):
    name = {k: DEMO[k] for k in ("first_name", "last_name")}
    full = dict(DEMO)
    issued = datetime.date.fromisoformat(verifier["issued"])
    dob = datetime.date.fromisoformat(DEMO["dob"])
    age = issued.year - dob.year - ((issued.month, issued.day) < (dob.month, dob.day))
    drop = lambda k: {f: v for f, v in full.items() if f != k}

    # Ordered so wrong guesses never reach the lockout threshold: a correct
    # level-2 query resets the Nano's failure counter.
    cases = [
        ("L1: full name", name, "L1"),
        ("L1: name, different case/spacing", {"first_name": "NATHAN", "last_name": "  donagi "}, "L1"),
        ("L1: name + dob", {**name, "dob": DEMO["dob"]}, "L1"),
        ("L1: name + dob as MM/DD/YYYY", {**name, "dob": "09/21/2005"}, "L1"),
        ("L1: dob alone", {"dob": DEMO["dob"]}, None),
        ("L1: first name alone", {"first_name": "Nathan"}, None),
        ("L1: wrong last name", {"first_name": "Nathan", "last_name": "Smith"}, None),
        ("L1: wrong dob", {**name, "dob": "2005-09-22"}, None),
        ("L2: everything correct", full, "L2"),
        ("L2: ssn with dashes", {**full, "ssn": "123-45-6789"}, "L2"),
        ("L2: ssn only", {"ssn": DEMO["ssn"]}, None),
        ("L2: ssn + pin, no level-1", {"ssn": DEMO["ssn"], "pin": DEMO["pin"]}, None),
        ("L2: missing dob", drop("dob"), None),
        ("L2: wrong pin", {**full, "pin": "0000"}, None),
        ("L2: wrong ssn", {**full, "ssn": "999999999"}, None),
        ("L2: wrong first name", {**full, "first_name": "Nate"}, None),
        ("pin with no ssn", {**name, "pin": DEMO["pin"]}, None),
        (f"over 18 (age {age})", {**name, "over": 18}, "OVER18" if age >= 18 else None),
        (f"over 21 (age {age})", {**name, "over": 21}, "OVER21" if age >= 21 else None),
        ("over 18, wrong name", {"first_name": "Nathan", "last_name": "Smith", "over": 18}, None),
        ("over 18 + extra field", {**name, "over": 18, "dob": DEMO["dob"]}, None),
        ("over 25 (unsupported)", {**name, "over": 25}, None),
        ("L2: everything correct (resets failure counter)", full, "L2"),
    ]
    failed = 0
    for label, q, expect in cases:
        t = time.time()
        status, detail = nano.query(q)
        got = detail if status == "AUTHENTICATED" else None
        ok = got == expect
        failed += not ok
        mark = "OK " if got else "NO "
        warn = "" if ok else f"   <-- UNEXPECTED (wanted {expect or 'DENIED'}, got {status} {detail})"
        print(f"{mark} {label:<50} {time.time() - t:4.1f} s{warn}")

    # A recorded answer is useless for a different challenge.
    proof = nano.expected_proof("L2", "aa" * 16)
    assert not hmac.compare_digest(proof, nano.expected_proof("L2", "bb" * 16))
    print("OK  a proof for one challenge doesn't verify for another (no replays)")
    print("all checks passed" if not failed else f"{failed} UNEXPECTED RESULT(S)")
    return failed == 0


def run_shell(nano):
    print("Type queries like:  first_name=Nathan last_name=Donagi over=21")
    print("Quote values with spaces:  first_name=\"Mary Ann\" ...   (blank line or Ctrl-D quits)")
    while True:
        try:
            line = input("query> ").strip()
        except EOFError:
            break
        if not line:
            break
        try:
            run_verify(nano, shlex.split(line))
        except (NanoError, ValueError) as e:
            print("error:", e)


def main():
    p = argparse.ArgumentParser(description="Query a kagi Arduino Nano over serial.")
    p.add_argument("--port", help="serial port (default: auto-detect)")
    p.add_argument("--registry", type=Path, default=REGISTRY)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("info", help="show the Nano's key id and failure counter")
    s = sub.add_parser("verify", help="send one query, e.g. first_name=Nathan last_name=Donagi")
    s.add_argument("fields", nargs="+")
    sub.add_parser("demo", help="run the full test list")
    sub.add_parser("shell", help="interactive queries")
    a = p.parse_args()

    try:
        registry = json.loads(a.registry.read_text())
    except FileNotFoundError:
        sys.exit(f"{a.registry} not found: run nano_provision.py first")

    try:
        nano = Nano(a.port or find_port(), registry)
        verifier = nano.v
        if a.cmd == "info":
            info = nano.info()
            print(f"key id    {info['id']}  (found in nano_registry.json)")
            print(f"kdf iters {info['iters']}")
            print(f"failures  {info['fails']}  (lockout starts at 5)")
            print(f"expires   {verifier['expires']}")
            ok = True
        elif a.cmd == "verify":
            ok = run_verify(nano, a.fields)
        elif a.cmd == "demo":
            ok = run_demo(nano, verifier)
        else:
            run_shell(nano)
            ok = True
    except (NanoError, serial.SerialException) as e:
        sys.exit(f"error: {e}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
