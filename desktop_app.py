#!/usr/bin/env python3
"""
desktop_app: the user's side of every kagi check (stands in for the phone app).

    python3 desktop_app.py                  # in WSL: also run serial_bridge.py on Windows
    python3 desktop_app.py --port /dev/ttyUSB0      # outside WSL: open the Nano directly
    python3 desktop_app.py --simulate               # rehearse without a Nano

It takes two kinds of code:

8 digits, from challenge_site.py (the Zoom identity check)
1. The app looks the challenge up and shows the name being asked about.
2. Plug in your key (the Nano). The app asks it whether the name matches, with a
   fresh random challenge, and checks its HMAC proof against nano_registry.json.
   The key only ever answers yes or no.
3. The app tells challenge_site.py the outcome, and the host's page shows it.

12 digits, from central_server.py (a website such as blindgram.py)
* unique_signup: plug in the key; it signs the server's nonce for that site and
  the app relays the signature. The site learns only "new" or "existing".
* age_check: type your name (it goes only to the key), plug in the key; it
  answers "over 18?" over the server's nonce and the app relays the proof. The
  site learns only yes or no. The central server checks both proofs itself,
  so the app can't lie to it.

WSL can't open serial ports, so under WSL the app listens on localhost:8765 and
serial_bridge.py (run with Windows Python) connects there when the Nano is
plugged in and forwards its bytes. Elsewhere it opens the port itself.

The UI is Qt: Anaconda's Tk has no font smoothing, so it looked pixelated.
Under WSL the app also reads Windows' display scaling, light/dark setting and
fonts (WSLg passes none of them through), so it matches the site in the browser.
"""

import argparse
import hmac
import json
import os
import platform
import queue
import re
import select
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import serial

from nano_client import BAUD, REGISTRY, Nano, NanoError, find_port

# Same palette as challenge_site.py, plus soft tints for the result.
THEMES = {
    "light": {"bg": "#fafafa", "ink": "#111111", "muted": "#777777", "line": "#e2e2e2",
              "field": "#ffffff", "green": "#16a34a", "green_bg": "#eef8f1",
              "green_flash": "#d3efdd", "red": "#dc2626", "red_bg": "#fdf1f1"},
    "dark": {"bg": "#0e0e0e", "ink": "#f2f2f2", "muted": "#8a8a8a", "line": "#2a2a2a",
             "field": "#161616", "green": "#22c55e", "green_bg": "#0d1a12",
             "green_flash": "#163a23", "red": "#ef4444", "red_bg": "#1c0f0f"},
}
WSL = "microsoft" in platform.uname().release.lower()
DEBUG = False                           # --debug: print the serial conversation
WIN_FONTS = Path("/mnt/c/Windows/Fonts")


def windows_reg_dword(key: str, value: str):
    """Reads a REG_DWORD from the Windows side (WSL only). None if unavailable."""
    try:
        out = subprocess.run(["reg.exe", "query", key, "/v", value], capture_output=True,
                             text=True, timeout=5).stdout
        return int(out.split()[-1], 16)
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return None


def fetch_challenge(server: str, code: str) -> dict:
    try:
        with urllib.request.urlopen(f"{server}/api/challenges/{code}", timeout=10) as r:
            ch = json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise LookupError("That code doesn't exist or has expired.")
        raise LookupError(f"The server said {e.code}.")
    except OSError:
        raise LookupError(f"Can't reach {server}.")
    if ch.get("status") != "waiting":
        raise LookupError("That code has already been used.")
    return {**ch, "code": code}


def fetch_central(server: str, code: str) -> dict:
    try:
        with urllib.request.urlopen(f"{server}/api/challenges/{code}", timeout=10) as r:
            ch = json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise LookupError("That code doesn't exist, has expired or was already used.")
        raise LookupError(f"The server said {e.code}.")
    except OSError:
        raise LookupError(f"Can't reach {server}.")
    if ch.get("type") not in ("unique_signup", "age_check"):
        raise LookupError("This app doesn't know that kind of request.")
    return {**ch, "code": code}


def send_central(server: str, code: str, body: dict) -> str:
    """Relays the key's answer. Returns the server's result; raises LookupError."""
    req = urllib.request.Request(f"{server}/api/challenges/{code}/response", method="POST",
                                 data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)["result"]
    except urllib.error.HTTPError as e:
        try:
            msg = json.load(e).get("error", e.reason)
        except ValueError:
            msg = e.reason
        raise LookupError(f"The server said: {msg}.")
    except OSError:
        raise LookupError(f"Can't reach {server}.")


def report_result(server: str, code: str, verified: bool):
    req = urllib.request.Request(f"{server}/api/challenges/{code}/result", method="POST",
                                 data=json.dumps({"verified": verified}).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=10).close()
    except OSError as e:                # the app's own result still shows; just log it
        print(f"couldn't report the result to {server}: {e}", file=sys.stderr)


class BridgeClosed(NanoError):
    pass


class BridgedSerial:
    """The Nano's serial line as forwarded by serial_bridge.py over a local socket.
    Has just the bits of pyserial's interface that nano_client.Nano uses."""

    def __init__(self, sock: socket.socket):
        self.sock, self.buf = sock, b""

    def _fill(self, timeout: float):
        self.sock.settimeout(timeout)
        try:
            data = self.sock.recv(4096)
        except socket.timeout:
            return
        except OSError:
            data = b""
        if not data:
            raise BridgeClosed("The key was unplugged.")
        if DEBUG:
            print(f"key -> app  {data!r}", file=sys.stderr)
        self.buf += data

    def readline(self) -> bytes:
        if b"\n" not in self.buf:
            self._fill(0.1)
        i = self.buf.find(b"\n") + 1 or len(self.buf)
        line, self.buf = self.buf[:i], self.buf[i:]
        return line

    def reset_input_buffer(self):
        self.buf = b""
        self.sock.setblocking(False)
        try:
            while self.sock.recv(4096):
                pass
        except OSError:                 # BlockingIOError: nothing left to drain
            pass
        self.sock.setblocking(True)

    def write(self, data: bytes):
        if DEBUG:
            print(f"app -> key  {data!r}", file=sys.stderr)
        self.sock.sendall(data)

    def close(self):
        self.sock.close()

    def alive(self) -> bool:
        """False once serial_bridge.py has closed the connection (key unplugged)."""
        try:
            readable, _, _ = select.select([self.sock], [], [], 0)
            return not readable or bool(self.sock.recv(1, socket.MSG_PEEK))
        except OSError:
            return False


class DirectLink:
    """The Nano's serial port on this machine."""

    def __init__(self, port: str = None):
        self.port = port

    def open(self):
        try:
            ser = serial.Serial()
            ser.port, ser.baudrate, ser.timeout = self.port or find_port(), BAUD, 0.1
            ser.dtr = ser.rts = False       # try not to reset it; see serial_bridge.py
            ser.open()
            return ser
        except (NanoError, serial.SerialException):
            time.sleep(0.1)
            return None

    @staticmethod
    def alive(ser) -> bool:
        try:
            ser.in_waiting
            return True
        except (OSError, serial.SerialException):
            return False


class BridgeLink:
    """Connections from serial_bridge.py (Windows side), one per plug-in."""

    def __init__(self, listen_port: int):
        self.server = socket.socket()
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server.bind(("127.0.0.1", listen_port))
        self.server.listen()
        self.server.settimeout(0.2)

    def open(self):
        try:
            conn, _ = self.server.accept()
        except socket.timeout:
            return None
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        return BridgedSerial(conn)

    @staticmethod
    def alive(ser) -> bool:
        return ser.alive()


class KeyGone(Exception):
    pass


class KeyManager:
    """Owns the connection to the key on a background thread, so the app always
    knows whether it's plugged in, and runs queries on it. on_change(state) is
    called from that thread with "connected", "unregistered" or "absent"."""

    def __init__(self, link, registry: dict, on_change):
        self.link, self.registry, self.on_change = link, registry, on_change
        self.lock = threading.Lock()        # held while talking to the key
        self.nano = None
        self.state = "absent"
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        while True:
            ser = self.link.open()
            if ser is None:
                continue
            try:
                nano, state = Nano(ser, self.registry), "connected"
            except NanoError as e:
                nano = None
                state = "unregistered" if "isn't in nano_registry" in str(e) else None
            except (OSError, serial.SerialException):
                nano, state = None, None
            if state is None:               # pulled out mid-hello, or not a kagi
                ser.close()
                continue
            with self.lock:
                self.nano = nano
            self.state = state
            self.on_change(state)
            while True:
                time.sleep(0.1)
                with self.lock:
                    if not self.link.alive(ser):
                        self.nano = None
                        break
            ser.close()
            self.state = "absent"
            self.on_change("absent")

    def run(self, op):
        """op(nano)'s result; KeyGone if the key isn't there or is pulled out."""
        with self.lock:
            if self.nano is None:
                raise KeyGone()
            try:
                return op(self.nano)
            except (BridgeClosed, OSError, serial.SerialException):
                raise KeyGone()


class SimulatedNano:
    """Answers like a Nano holding the first key in nano_registry.json, and says
    yes to everything. Its proofs are real (it has the device secret), so the
    central server accepts them: for rehearsing without the hardware."""

    has_button = False

    def __init__(self, rec: dict = None):
        self.rec = rec
        self.key_id = rec and rec["key_id"]

    def _mac(self, msg: str) -> str:
        if not self.rec:
            raise NanoError("Simulating needs nano_registry.json for this.")
        return hmac.new(bytes.fromhex(self.rec["device_secret"]), msg.encode(), "sha256").hexdigest()

    def query(self, fields):
        return "AUTHENTICATED", "L1"

    def auth(self, fields, challenge):
        scope = f"OVER{fields['over']}"
        return "AUTHENTICATED", scope, self._mac(f"kagi-nano-v1|{self.key_id}|{scope}|{challenge}")

    def sign(self, nonce, site_id, on_tap=None):
        return self._mac(f"kagi-nano-sign-v1|{self.key_id}|{site_id}|{nonce}")


class SimulatedKeys:
    """Stands in for KeyManager: the key is 'plugged in' 3 s into each check."""

    def __init__(self, registry: dict):
        self.nano = SimulatedNano(next(iter(registry.values()), None))
        self.plugged_at = None

    @property
    def state(self):
        if self.plugged_at is None:
            self.plugged_at = time.time() + 3
        return "connected" if time.time() >= self.plugged_at else "absent"

    def run(self, op):
        time.sleep(2)
        self.plugged_at = None
        return op(self.nano)


def with_key(keys, op, alive, say):
    """Runs on a worker thread: waits for the key, then returns op(nano). Waits
    again if the key is pulled out mid-way. None if cancelled; NanoError on failure."""
    while alive():
        if keys.state == "absent":
            time.sleep(0.05)
            continue
        if keys.state == "unregistered":
            raise NanoError("This key isn't registered.")
        say("checking")
        try:
            return keys.run(op)
        except KeyGone:
            say("unplugged")
    return None


# Each flow runs on a worker thread and returns (ok, headline, message), or
# None if the user cancelled.

def name_check_flow(ch, keys, server, alive, say):
    fields = {"first_name": ch["first_name"], "last_name": ch["last_name"]}
    try:
        answer = with_key(keys, lambda nano: nano.query(fields), alive, say)
    except NanoError as e:
        answer = "ERROR", str(e)
    if answer is None:
        return None
    status, detail = answer
    ok = status == "AUTHENTICATED"
    if ok:
        message = "Your key confirmed this name."
    elif status == "DENIED" and not detail:
        message = "This key doesn't belong to that person."
    else:
        message = detail or status.title()
    report_result(server, ch["code"], ok)
    return ok, "Verified" if ok else "Not verified", message


def signup_flow(ch, keys, central, alive, say):
    site = ch["site_name"]
    try:
        answer = with_key(keys, lambda nano: (
            nano.key_id, nano.sign(ch["nonce"], ch["site_id"], on_tap=lambda: say("tap"))),
            alive, say)
        if answer is None:
            return None
        key_id, proof = answer
        say("sending")
        result = send_central(central, ch["code"], {"key_id": key_id, "proof": proof})
    except (NanoError, LookupError) as e:
        return False, "Not verified", str(e)
    if result == "new":
        return True, "You're in", f"Go back to {site} to finish signing up."
    return False, "Already signed up", (f"You already have a {site} account. "
                                        "It allows one per person.")


def age_flow(ch, fields, keys, central, alive, say):
    site, over = ch["site_name"], ch["over"]
    query = {**fields, "over": over}
    try:
        answer = with_key(keys, lambda nano: (nano.key_id, *nano.auth(query, ch["nonce"])),
                          alive, say)
        if answer is None:
            return None
        key_id, status, scope, proof = answer
        if status == "LOCKED":
            return False, "Key locked", f"Too many wrong guesses. Try again in {scope} s."
        say("sending")
        if status == "AUTHENTICATED" and scope == f"OVER{over}":
            send_central(central, ch["code"], {"key_id": key_id, "proof": proof})
            return True, f"Verified {over}+", f"{site} now knows you're {over} or over. Nothing else."
        send_central(central, ch["code"], {"declined": True})
    except (NanoError, LookupError) as e:
        return False, "Not verified", str(e)
    return False, "Not verified", (f"Your key couldn't confirm you're {over} or over. "
                                   "Check how you spelled your name.")


# ---------- UI ----------
# Qt is imported here, after main() has set QT_SCALE_FACTOR.

def run_ui(server: str, central: str, registry: dict, link, simulate: bool, theme: dict):
    from PyQt5.QtCore import QRectF, Qt, QTimer, QVariantAnimation, QEasingCurve
    from PyQt5.QtGui import QColor, QFont, QFontDatabase, QPainter, QPainterPath, QPen
    from PyQt5.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLabel, QLineEdit,
                                 QPushButton, QVBoxLayout, QWidget)

    app = QApplication(sys.argv)
    app.setApplicationName("kagi")
    t = theme

    def load_font(files, fallback):
        for f in files:
            path = WIN_FONTS / f
            if path.exists():
                QFontDatabase.addApplicationFont(str(path))
        fams = QFontDatabase().families()
        return next((f for f in fallback if f in fams), fallback[-1])

    sans = load_font(["segoeui.ttf", "seguisb.ttf", "segoeuib.ttf"],
                     ["Segoe UI", "Inter", "Noto Sans", "DejaVu Sans", "Sans Serif"])
    mono = load_font(["consola.ttf", "consolab.ttf"],
                     ["Consolas", "DejaVu Sans Mono", "Monospace"])
    app.setFont(QFont(sans, 11))
    app.setStyleSheet(f"""
        QWidget {{ color:{t['ink']}; font-family:"{sans}"; font-size:16px; }}
        QLabel#brand {{ color:{t['muted']}; font-size:13px; }}
        QLabel#title {{ font-size:28px; font-weight:600; }}
        QLabel#muted, QLabel#key {{ color:{t['muted']}; }}
        QLabel#value {{ font-size:18px; font-weight:600; }}
        QLabel#status {{ color:{t['muted']}; font-size:13px; }}
        QLabel#error {{ color:{t['red']}; font-size:14px; }}
        QLineEdit {{ background:{t['field']}; border:1px solid {t['line']}; border-radius:12px;
                     padding:12px 16px; font-family:"{mono}"; font-size:30px; font-weight:600;
                     selection-background-color:{t['ink']}; selection-color:{t['bg']}; }}
        QLineEdit:focus {{ border-color:{t['ink']}; }}
        QLineEdit#name {{ font-family:"{sans}"; font-size:16px; font-weight:400; }}
        QLabel#note {{ color:{t['muted']}; font-size:14px; }}
        QPushButton#primary {{ background:{t['ink']}; color:{t['bg']}; border:none;
                               border-radius:24px; padding:14px 28px; font-weight:600; }}
        QPushButton#primary:disabled {{ background:{t['muted']}; }}
        QPushButton#text {{ background:transparent; color:{t['muted']}; border:none; padding:8px; }}
        QPushButton#text:hover {{ color:{t['ink']}; }}
        QFrame#card {{ background:{t['field']}; border:1px solid {t['line']}; border-radius:16px; }}
        QFrame#sep {{ background:{t['line']}; border:none; }}
    """)

    class Root(QWidget):
        """Paints its own background so the result tint can be animated."""

        def __init__(self):
            super().__init__()
            self.bg = QColor(t["bg"])

        def set_bg(self, color):
            self.bg = QColor(color)
            self.update()

        def paintEvent(self, e):
            QPainter(self).fillRect(self.rect(), self.bg)

    class StatusIcon(QWidget):
        """Anti-aliased spinner, tick or cross."""

        def __init__(self):
            super().__init__()
            self.setFixedSize(88, 88)
            self.mode, self.angle = "spin", 0
            self.timer = QTimer(self, timeout=self._tick)
            self.timer.start(16)

        def _tick(self):
            self.angle = (self.angle - 6) % 360
            self.update()

        def set_mode(self, mode):
            self.mode = mode
            if mode != "spin":
                self.timer.stop()
            self.update()

        def paintEvent(self, e):
            p = QPainter(self)
            p.setRenderHint(QPainter.Antialiasing)
            r = QRectF(5, 5, 78, 78)
            if self.mode == "spin":
                p.setPen(QPen(QColor(t["line"]), 5))
                p.drawEllipse(r)
                pen = QPen(QColor(t["ink"]), 5)
                pen.setCapStyle(Qt.RoundCap)
                p.setPen(pen)
                p.drawArc(r, self.angle * 16, 80 * 16)
                return
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(t["green"] if self.mode == "ok" else t["red"]))
            p.drawEllipse(QRectF(2, 2, 84, 84))
            pen = QPen(QColor("#ffffff"), 6.5)
            pen.setCapStyle(Qt.RoundCap)
            pen.setJoinStyle(Qt.RoundJoin)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            path = QPainterPath()
            if self.mode == "ok":
                path.moveTo(27, 45)
                path.lineTo(39, 57)
                path.lineTo(62, 32)
            else:
                path.moveTo(32, 32)
                path.lineTo(56, 56)
                path.moveTo(56, 32)
                path.lineTo(32, 56)
            p.drawPath(path)

    def label(text, name=None, align=Qt.AlignCenter):
        lbl = QLabel(text)
        if name:
            lbl.setObjectName(name)
        lbl.setAlignment(align)
        return lbl

    def button(text, name, on_click):
        b = QPushButton(text)
        b.setObjectName(name)
        b.setCursor(Qt.PointingHandCursor)
        b.clicked.connect(on_click)
        return b

    class Window(Root):
        def __init__(self):
            super().__init__()
            self.setWindowTitle("kagi")
            self.resize(480, 620)
            self.events = queue.Queue()     # (generation, kind, value) from worker threads
            self.gen = 0                    # bumps on every new screen; stale events are dropped
            self.page = None
            outer = QVBoxLayout(self)
            outer.setContentsMargins(24, 24, 24, 24)
            self.holder = QHBoxLayout()
            outer.addStretch(1)
            outer.addLayout(self.holder)
            outer.addStretch(1)
            self.key_status = label("", "status")
            outer.addWidget(self.key_status)
            self.show_key("simulated" if simulate else "absent")
            drain = QTimer(self, timeout=self._drain)
            drain.start(50)
            self.show_code_screen()

        def _page(self):
            """A fresh centred column, 360 wide like the site, headed by the brand."""
            self.gen += 1
            if self.anim:
                self.anim.stop()
            self.set_bg(t["bg"])
            if self.page:
                self.page.hide()
                self.page.deleteLater()
            self.page = QWidget()
            self.page.setFixedWidth(360)
            col = QVBoxLayout(self.page)
            col.setContentsMargins(0, 0, 0, 0)
            col.setSpacing(0)
            brand = label("KAGI", "brand")
            f = brand.font()
            f.setLetterSpacing(QFont.PercentageSpacing, 125)
            brand.setFont(f)
            col.addWidget(brand)
            col.addSpacing(40)
            self.holder.addStretch(1)
            self.holder.addWidget(self.page)
            self.holder.addStretch(1)
            while self.holder.count() > 3:  # drop the previous page's stretches
                self.holder.takeAt(0)
            return col

        anim = None

        def show_key(self, state):
            colour, text = {"connected": (t["green"], "Key connected"),
                            "absent": (t["line"], "No key"),
                            "unregistered": (t["red"], "Unregistered key"),
                            "simulated": (t["muted"], "Simulated key")}[state]
            self.key_status.setText(f'<span style="color:{colour}">&#9679;</span>&nbsp; {text}')

        # ---- screen 1: enter code ----

        def show_code_screen(self):
            col = self._page()
            col.addWidget(label("Enter code", "title"))
            col.addSpacing(24)
            self.entry = QLineEdit()
            self.entry.setAlignment(Qt.AlignCenter)
            self.entry.setPlaceholderText("0000 0000")
            self.entry.setMaxLength(14)
            self.entry.textEdited.connect(self._format_code)
            self.entry.returnPressed.connect(self.submit_code)
            col.addWidget(self.entry)
            col.addSpacing(8)
            self.error = label("", "error")
            self.error.setMinimumHeight(28)
            col.addWidget(self.error)
            col.addSpacing(8)
            self.go = button("Continue", "primary", self.submit_code)
            col.addWidget(self.go)
            self.entry.setFocus()

        def _format_code(self, text):
            digits = re.sub(r"\D", "", text)[:12]
            pretty = " ".join(digits[i:i + 4] for i in range(0, len(digits), 4))
            if pretty != text:
                self.entry.setText(pretty)

        def submit_code(self):
            code = re.sub(r"\D", "", self.entry.text())
            if len(code) not in (8, 12):
                self.error.setText("The code is 8 or 12 digits.")
                return
            self.error.setText("")
            self.go.setEnabled(False)
            self.go.setText("Looking up...")
            gen = self.gen

            def work():
                try:
                    if len(code) == 12:
                        ch = fetch_central(central, code)
                    else:
                        ch = {**fetch_challenge(server, code), "type": "name_check"}
                    self.events.put((gen, "challenge", ch))
                except LookupError as e:
                    self.events.put((gen, "lookup_failed", str(e)))
            threading.Thread(target=work, daemon=True).start()

        # ---- screen 2: show the request, then authenticate ----

        def _card(self, col, rows):
            card = QFrame()
            card.setObjectName("card")
            lines = QVBoxLayout(card)
            lines.setContentsMargins(24, 8, 24, 8)
            lines.setSpacing(0)
            for i, (k, v) in enumerate(rows):
                if i:
                    sep = QFrame()
                    sep.setObjectName("sep")
                    sep.setFixedHeight(1)
                    lines.addWidget(sep)
                row = QHBoxLayout()
                row.setContentsMargins(0, 12, 0, 12)
                row.addWidget(label(k, "key", Qt.AlignLeft | Qt.AlignVCenter))
                val = label(v, "value", Qt.AlignRight | Qt.AlignVCenter)
                val.setWordWrap(True)
                row.addWidget(val, 1)
                lines.addLayout(row)
            col.addWidget(card)

        def show_challenge(self, ch: dict):
            if ch["type"] == "age_check":
                return self.show_age_form(ch)
            col = self._page()
            if ch["type"] == "name_check":
                col.addWidget(label("Someone is asking you to confirm", "muted"))
                col.addSpacing(16)
                self._card(col, (("First name", ch["first_name"]), ("Last name", ch["last_name"])))
                flow = lambda alive, say: name_check_flow(ch, keys, server, alive, say)
            else:
                col.addWidget(label(f"{ch['site_name']} wants to check you're a unique person",
                                    "muted"))
                col.addSpacing(16)
                self._card(col, (("Site", ch["site_name"]), ("They learn", "New or existing")))
                flow = lambda alive, say: signup_flow(ch, keys, central, alive, say)
            self._authenticate(col, flow)

        def show_age_form(self, ch: dict):
            col = self._page()
            col.addWidget(label(f"{ch['site_name']} wants to check your age", "muted"))
            col.addSpacing(16)
            self._card(col, (("Question", f"{ch['over']} or over?"), ("They learn", "Yes or no")))
            col.addSpacing(24)
            first, last = QLineEdit(), QLineEdit()
            for field, hint, value in ((first, "First name", self.remembered[0]),
                                       (last, "Last name", self.remembered[1])):
                field.setObjectName("name")
                field.setPlaceholderText(hint)
                field.setText(value)
                field.setMaxLength(32)
                col.addWidget(field)
                col.addSpacing(8)
            note = label("Your key needs your name to answer.\nIt goes to your key and nowhere else.",
                         "note")
            note.setWordWrap(True)
            col.addWidget(note)
            col.addSpacing(8)
            self.error = label("", "error")
            self.error.setMinimumHeight(28)
            col.addWidget(self.error)
            col.addSpacing(8)

            def go():
                fields = {"first_name": " ".join(first.text().split()),
                          "last_name": " ".join(last.text().split())}
                if not all(fields.values()):
                    self.error.setText("Enter your first and last name.")
                    return
                self.remembered = (fields["first_name"], fields["last_name"])
                self.show_age_check(ch, fields)
            last.returnPressed.connect(go)
            first.returnPressed.connect(last.setFocus)
            col.addWidget(button("Continue", "primary", go))
            col.addSpacing(4)
            col.addWidget(button("Cancel", "text", self.show_code_screen), 0, Qt.AlignHCenter)
            (last if self.remembered[0] else first).setFocus()

        remembered = ("", "")       # the name from the last age check, only in memory

        def show_age_check(self, ch: dict, fields: dict):
            col = self._page()
            col.addWidget(label(f"{ch['site_name']} wants to check your age", "muted"))
            col.addSpacing(16)
            self._card(col, (("Question", f"{ch['over']} or over?"), ("They learn", "Yes or no")))
            self._authenticate(col, lambda alive, say: age_flow(ch, fields, keys, central, alive, say))

        def _authenticate(self, col, flow):
            """Spinner, headline and Cancel under the request; runs flow on a worker."""
            col.addSpacing(40)
            self.icon = StatusIcon()
            col.addWidget(self.icon, 0, Qt.AlignHCenter)
            col.addSpacing(20)
            self.headline = label("Please authenticate now", "title")
            self.headline.setWordWrap(True)
            col.addWidget(self.headline)
            col.addSpacing(6)
            self.sub = label("Plug in your key.", "muted")
            self.sub.setWordWrap(True)
            self.sub.setMinimumHeight(48)
            self.sub.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
            col.addWidget(self.sub)
            col.addSpacing(12)
            self.back = button("Cancel", "text", self.show_code_screen)
            col.addWidget(self.back, 0, Qt.AlignHCenter)

            gen = self.gen
            say = lambda kind, value="": self.events.put((gen, kind, value))

            def work():
                result = flow(lambda: gen == self.gen, say)
                if result is None:          # the user went back to the code screen
                    return
                if not result[0]:
                    print(f"not verified: {result[2]}", file=sys.stderr)
                say("done", result)
            threading.Thread(target=work, daemon=True).start()

        def finish(self, ok: bool, headline: str, message: str):
            colour = t["green"] if ok else t["red"]
            self.icon.set_mode("ok" if ok else "fail")
            self.headline.setText(headline)
            self.headline.setStyleSheet(f"color:{colour};")
            self.sub.setText(message)
            self.back.setText("Done")
            if ok:
                # One gentle pulse of green that settles into a soft tint.
                self.anim = QVariantAnimation(self, startValue=QColor(t["green_flash"]),
                                              endValue=QColor(t["green_bg"]), duration=900,
                                              easingCurve=QEasingCurve.OutCubic)
                self.anim.valueChanged.connect(self.set_bg)
                self.anim.start()
            else:
                self.set_bg(t["red_bg"])

        # ---- events from worker threads ----

        def _drain(self):
            try:
                while True:
                    gen, kind, value = self.events.get_nowait()
                    if kind == "key":           # not tied to a screen
                        self.show_key(value)
                        continue
                    if gen != self.gen:
                        continue
                    if kind == "challenge":
                        self.show_challenge(value)
                    elif kind == "lookup_failed":
                        self.error.setText(value)
                        self.go.setEnabled(True)
                        self.go.setText("Continue")
                    elif kind == "checking":
                        self.headline.setText("Checking your key...")
                        self.sub.setText("Keep it plugged in.")
                    elif kind == "tap":
                        self.headline.setText("Tap your key")
                        self.sub.setText("Press the button on your key.")
                    elif kind == "sending":
                        self.headline.setText("Almost done...")
                        self.sub.setText("Sending your key's answer.")
                    elif kind == "unplugged":
                        self.headline.setText("Please authenticate now")
                        self.sub.setText("Your key was pulled out. Plug it back in.")
                    elif kind == "done":
                        self.finish(*value)
            except queue.Empty:
                pass

    win = Window()
    if simulate:
        keys = SimulatedKeys(registry)
    else:
        keys = KeyManager(link, registry, lambda st: win.events.put((None, "key", st)))
    win.show()
    return app, win


def main():
    p = argparse.ArgumentParser(description="kagi desktop app (identity, sign-up and age checks)")
    p.add_argument("--server", default="http://localhost:8002",
                   help="where challenge_site.py is running (8-digit codes)")
    p.add_argument("--central", default="http://localhost:8000",
                   help="where central_server.py is running (12-digit codes)")
    p.add_argument("--port", help="open this serial port directly instead of using the bridge")
    p.add_argument("--bridge-port", type=int, default=8765,
                   help="where to listen for serial_bridge.py (under WSL)")
    p.add_argument("--registry", type=Path, default=REGISTRY)
    p.add_argument("--simulate", action="store_true",
                   help="pretend a key was plugged in and said yes (for rehearsing); "
                        "uses nano_registry.json's first key if present")
    p.add_argument("--theme", choices=["auto", "light", "dark"], default="auto",
                   help="auto follows Windows' app setting under WSL, else light")
    p.add_argument("--scale", type=float, help="UI scale (default: Windows' scaling under WSL)")
    p.add_argument("--debug", action="store_true", help="print what goes to and from the key")
    a = p.parse_args()
    global DEBUG
    DEBUG = a.debug

    try:
        registry = json.loads(a.registry.read_text())
    except FileNotFoundError:
        if not a.simulate:
            sys.exit(f"{a.registry} not found: run nano_provision.py first")
        registry = {}
    link = None
    if a.simulate:
        pass
    elif a.port or not WSL:
        link = DirectLink(a.port)
    else:
        try:
            link = BridgeLink(a.bridge_port)
        except OSError as e:
            sys.exit(f"can't listen on localhost:{a.bridge_port}: {e}")
        print(f"WSL: waiting for serial_bridge.py on localhost:{a.bridge_port} "
              "(run it with Windows Python)")

    theme = a.theme
    if theme == "auto":
        light = windows_reg_dword(r"HKCU\Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
                                  "AppsUseLightTheme") if WSL else None
        theme = "dark" if light == 0 else "light"
    scale = a.scale
    if scale is None and WSL:
        dpi = windows_reg_dword(r"HKCU\Control Panel\Desktop\WindowMetrics", "AppliedDPI")
        scale = dpi / 96 if dpi else None
    if scale:
        os.environ["QT_SCALE_FACTOR"] = f"{scale:g}"

    app, _win = run_ui(a.server.rstrip("/"), a.central.rstrip("/"), registry, link, a.simulate,
                       THEMES[theme])
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
