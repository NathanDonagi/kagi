#!/usr/bin/env python3
"""
bluetooth_bridge: lets the Android app reach the kagi servers over Bluetooth.

The Android app is the phone version of desktop_app.py: the user types a code,
taps their RFID key, and the app sends the key's answer to the server. The phone
can't reach localhost on the PC, so this script accepts the phone's Bluetooth
(RFCOMM) connection and forwards each request it sends to central_server.py or
challenge_site.py over local HTTP, then sends the answer back. The wire format
is in communication.md.

WSL has no Bluetooth, so under WSL run this with WINDOWS Python (like
serial_bridge.py). The servers keep running in WSL; Windows reaches them on
localhost. On a Linux machine with a Bluetooth adapter it runs there directly.

    py bluetooth_bridge.py                      # Windows Python, Bluetooth on
    py bluetooth_bridge.py --tcp 8766           # no Bluetooth: same protocol over TCP
                                                # (Android emulator: adb reverse tcp:8766 tcp:8766)

It only forwards GET/POST to /api/... paths on the servers it was given, and
never adds credentials: the app can do only what any user's app can (look a
code up, answer it), not what a website can (create codes, read results).
"""

import argparse
import json
import socket
import sys
import threading
import urllib.error
import urllib.request
import uuid

PROTOCOL = "kagi-bt-1"
SERVICE_NAME = "kagi"
SERVICE_UUID = uuid.UUID("083d2893-6eab-4283-b12c-cdf0771acb72")   # the app connects to this
MAX_LINE = 64 * 1024
HTTP_TIMEOUT = 30


# ---------- forwarding ----------

class Bridge:
    def __init__(self, targets: dict):
        self.targets = targets            # name -> base URL

    def hello(self) -> dict:
        return {"type": "hello", "protocol": PROTOCOL, "targets": sorted(self.targets)}

    def handle(self, line: bytes) -> dict:
        """One request line -> one response dict. Never raises."""
        try:
            req = json.loads(line)
        except ValueError:
            return self._reply(None, 400, "request is not valid JSON")
        if not isinstance(req, dict):
            return self._reply(None, 400, "request must be a JSON object")
        rid = req.get("id")
        if not isinstance(rid, (int, str)) or isinstance(rid, bool):
            return self._reply(None, 400, "request needs an id (number or string)")

        target, method, path = req.get("target"), req.get("method"), req.get("path")
        if target == "bridge":
            if method == "GET" and path == "/ping":
                return {"type": "response", "id": rid, "status": 200, "body": {"pong": True}}
            if method == "GET" and path == "/info":
                return {"type": "response", "id": rid, "status": 200, "body": self.hello()}
            return self._reply(rid, 404, "bridge supports GET /ping and GET /info")
        if target not in self.targets:
            return self._reply(rid, 400, f"target must be one of {sorted(self.targets)} or bridge")
        if method not in ("GET", "POST"):
            return self._reply(rid, 400, "method must be GET or POST")
        if (not isinstance(path, str) or not path.startswith("/api/") or ".." in path
                or any(c in path for c in "?#\\ ") or len(path) > 200):
            return self._reply(rid, 400, "path must be an /api/... path")

        headers = {"Content-Type": "application/json"}
        data = json.dumps(req.get("body", {})).encode() if method == "POST" else None
        http = urllib.request.Request(self.targets[target] + path, data=data, method=method,
                                      headers=headers)
        try:
            with urllib.request.urlopen(http, timeout=HTTP_TIMEOUT) as r:
                status, raw = r.status, r.read()
        except urllib.error.HTTPError as e:
            status, raw = e.code, e.read()
        except OSError as e:
            return self._reply(rid, 502, f"can't reach {target} at {self.targets[target]}: {e}")
        try:
            body = json.loads(raw) if raw else {}
        except ValueError:
            body = {"error": f"{target} answered with non-JSON ({status})"}
        return {"type": "response", "id": rid, "status": status, "body": body}

    @staticmethod
    def _reply(rid, status: int, error: str) -> dict:
        return {"type": "response", "id": rid, "status": status, "body": {"error": error}}


def serve_client(bridge: Bridge, conn, who: str):
    """Reads newline-delimited JSON requests and answers each in order."""
    print(f"{who} connected")
    send = lambda obj: conn.sendall(json.dumps(obj, separators=(",", ":")).encode() + b"\n")
    buf = b""
    try:
        send(bridge.hello())
        while True:
            data = conn.recv(4096)
            if not data:
                break
            buf += data
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                line = line.strip()
                if line:
                    send(bridge.handle(line))
            if len(buf) > MAX_LINE:
                send(Bridge._reply(None, 413, f"line longer than {MAX_LINE} bytes"))
                break
    except OSError:
        pass
    finally:
        conn.close()
        print(f"{who} disconnected")


# ---------- Bluetooth service record (so the app can connect by UUID) ----------

def register_service_windows(sock):
    """Publishes an SDP record for SERVICE_UUID pointing at sock's RFCOMM channel,
    the ctypes equivalent of WSASetService(RNRSERVICE_REGISTER). Returns an object
    whose .delete() withdraws it."""
    import ctypes
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [("Data1", ctypes.c_uint32), ("Data2", ctypes.c_uint16),
                    ("Data3", ctypes.c_uint16), ("Data4", ctypes.c_ubyte * 8)]

    class SOCKET_ADDRESS(ctypes.Structure):
        _fields_ = [("lpSockaddr", ctypes.c_void_p), ("iSockaddrLength", ctypes.c_int)]

    class CSADDR_INFO(ctypes.Structure):
        _fields_ = [("LocalAddr", SOCKET_ADDRESS), ("RemoteAddr", SOCKET_ADDRESS),
                    ("iSocketType", ctypes.c_int), ("iProtocol", ctypes.c_int)]

    class WSAQUERYSETW(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("lpszServiceInstanceName", wintypes.LPWSTR),
                    ("lpServiceClassId", ctypes.POINTER(GUID)), ("lpVersion", ctypes.c_void_p),
                    ("lpszComment", wintypes.LPWSTR), ("dwNameSpace", wintypes.DWORD),
                    ("lpNSProviderId", ctypes.c_void_p), ("lpszContext", wintypes.LPWSTR),
                    ("dwNumberOfProtocols", wintypes.DWORD), ("lpafpProtocols", ctypes.c_void_p),
                    ("lpszQueryString", wintypes.LPWSTR), ("dwNumberOfCsAddrs", wintypes.DWORD),
                    ("lpcsaBuffer", ctypes.POINTER(CSADDR_INFO)), ("dwOutputFlags", wintypes.DWORD),
                    ("lpBlob", ctypes.c_void_p)]

    ws2 = ctypes.windll.ws2_32
    ws2.getsockname.argtypes = [ctypes.c_size_t, ctypes.c_void_p, ctypes.POINTER(ctypes.c_int)]
    ws2.WSASetServiceW.argtypes = [ctypes.POINTER(WSAQUERYSETW), ctypes.c_int, wintypes.DWORD]

    addr = ctypes.create_string_buffer(64)          # the bound SOCKADDR_BTH, as Windows sees it
    alen = ctypes.c_int(len(addr))
    if ws2.getsockname(sock.fileno(), addr, ctypes.byref(alen)) != 0:
        raise OSError(f"getsockname failed ({ws2.WSAGetLastError()})")

    u = SERVICE_UUID
    guid = GUID(u.fields[0], u.fields[1], u.fields[2], (ctypes.c_ubyte * 8)(*u.bytes[8:]))
    csa = CSADDR_INFO(SOCKET_ADDRESS(ctypes.addressof(addr), alen.value), SOCKET_ADDRESS(None, 0),
                      socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
    qs = WSAQUERYSETW(dwSize=ctypes.sizeof(WSAQUERYSETW), lpszServiceInstanceName=SERVICE_NAME,
                      lpServiceClassId=ctypes.pointer(guid), dwNameSpace=16,   # NS_BTH
                      dwNumberOfCsAddrs=1, lpcsaBuffer=ctypes.pointer(csa))
    if ws2.WSASetServiceW(ctypes.byref(qs), 0, 0) != 0:          # RNRSERVICE_REGISTER
        raise OSError(f"WSASetService failed ({ws2.WSAGetLastError()})")

    class Record:
        keep = (addr, guid, csa, qs)                # must outlive the registration

        @staticmethod
        def delete():
            ws2.WSASetServiceW(ctypes.byref(qs), 2, 0)             # RNRSERVICE_DELETE
    return Record


def open_bluetooth(channel):
    if not hasattr(socket, "AF_BLUETOOTH"):
        hint = " (WSL has no Bluetooth: run this with Windows Python)" if "microsoft" in \
            " ".join(__import__("platform").uname()).lower() else ""
        raise SystemExit(f"this Python has no Bluetooth sockets{hint}")
    sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
    windows = sys.platform == "win32"
    try:
        if channel:
            sock.bind((socket.BDADDR_ANY, channel))
        elif windows:
            sock.bind((socket.BDADDR_ANY, -1))       # BT_PORT_ANY: Windows picks a channel
        else:
            for ch in range(1, 31):
                try:
                    sock.bind((socket.BDADDR_ANY, ch))
                    break
                except OSError:
                    continue
            else:
                raise OSError("no free RFCOMM channel")
    except OSError as e:
        if windows and getattr(e, "winerror", None) == 10050:
            raise SystemExit("Bluetooth is off: turn it on in Windows Settings > Bluetooth & devices")
        raise SystemExit(f"can't open a Bluetooth socket: {e}")
    sock.listen(2)
    channel = sock.getsockname()[1]
    record = None
    if windows:
        try:
            record = register_service_windows(sock)
        except OSError as e:
            print(f"warning: couldn't publish the service record ({e}); "
                  f"the app must connect to channel {channel} directly")
    else:
        print("note: no service record on Linux; the app must connect to the channel directly "
              "(see communication.md)")
    print(f"Bluetooth: listening on RFCOMM channel {channel}, service {SERVICE_NAME} {SERVICE_UUID}")
    return sock, record


def main():
    p = argparse.ArgumentParser(description="forward the Android app's Bluetooth requests "
                                            "to the kagi servers")
    p.add_argument("--central", default="http://localhost:8000", help="central_server.py")
    p.add_argument("--challenge-site", default="http://localhost:8002", help="challenge_site.py")
    p.add_argument("--channel", type=int, help="RFCOMM channel (default: any free one)")
    p.add_argument("--tcp", type=int, metavar="PORT",
                   help="listen on 127.0.0.1:PORT (TCP) instead of Bluetooth, for the emulator")
    a = p.parse_args()

    bridge = Bridge({"central": a.central.rstrip("/"), "challenge": a.challenge_site.rstrip("/")})

    record = None
    if a.tcp:
        server = socket.create_server(("127.0.0.1", a.tcp))
        print(f"TCP: listening on 127.0.0.1:{a.tcp}")
    else:
        server, record = open_bluetooth(a.channel)
    try:
        while True:
            conn, addr = server.accept()
            who = addr[0] if isinstance(addr, tuple) else str(addr)
            threading.Thread(target=serve_client, args=(bridge, conn, who), daemon=True).start()
    except KeyboardInterrupt:
        pass
    finally:
        if record:
            record.delete()
        server.close()


if __name__ == "__main__":
    main()
