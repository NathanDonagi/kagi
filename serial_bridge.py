#!/usr/bin/env python3
"""
serial_bridge: run this with WINDOWS Python so the WSL desktop app can reach the Nano.

WSL can't open Windows COM ports, but it can listen on localhost, and Windows
can connect to that. So this script waits for the Nano to be plugged in, then
connects to desktop_app.py on localhost:8765 and passes bytes both ways for as
long as it stays plugged in; unplugging it closes the connection, which is how
the app notices. It understands nothing: the app still sends the challenge and
checks the proof.

    py -m pip install pyserial
    py serial_bridge.py                 # the key on COM7
    py serial_bridge.py --port auto     # find it by USB description instead
"""

import argparse
import socket
import threading
import time

import serial
import serial.tools.list_ports

HINTS = ("arduino", "ch340", "ch341", "ftdi", "usb serial", "usb-serial", "cp210")


def find_port():
    for p in serial.tools.list_ports.comports():
        if any(h in f"{p.description} {p.manufacturer or ''}".lower() for h in HINTS):
            return p.device
    return None


def open_port(port):
    """Opens the port without asserting DTR, so the Nano isn't reset: it booted when
    it was plugged in, and a reset would cost another 1-2 s in its bootloader."""
    ser = serial.Serial()
    ser.port, ser.baudrate, ser.timeout = port, 115200, 0.1
    ser.dtr = ser.rts = False
    ser.open()
    return ser


def pipe(ser, sock):
    """Copies bytes both ways until either end goes away."""
    done = threading.Event()

    def serial_to_socket():
        try:
            while not done.is_set():
                data = ser.read(ser.in_waiting or 1)
                if data:
                    sock.sendall(data)
        except (OSError, serial.SerialException):
            pass
        done.set()

    reader = threading.Thread(target=serial_to_socket, daemon=True)
    reader.start()
    sock.settimeout(0.2)
    try:
        while not done.is_set():
            try:
                data = sock.recv(4096)
            except socket.timeout:
                continue
            if not data:
                break
            ser.write(data)
    except (OSError, serial.SerialException):
        pass
    done.set()
    reader.join()                       # before the caller closes the port under it


def main():
    p = argparse.ArgumentParser(description="forward the Nano's COM port to the WSL desktop app")
    p.add_argument("--port", default="COM7", help="COM port, or 'auto' (default: COM7)")
    p.add_argument("--app", default="localhost:8765", help="where desktop_app.py listens")
    a = p.parse_args()
    host, app_port = a.app.rsplit(":", 1)

    print("Waiting for the key to be plugged in...")
    while True:
        port = find_port() if a.port == "auto" else a.port
        try:
            ser = open_port(port) if port else None
        except serial.SerialException:     # not plugged in (yet), or still enumerating
            ser = None
        if not ser:
            time.sleep(0.1)
            continue
        try:
            sock = socket.create_connection((host, int(app_port)), timeout=2)
        except OSError:
            ser.close()
            print(f"Key on {port}, but desktop_app.py isn't listening on {a.app}; retrying...")
            time.sleep(1)
            continue
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        print(f"Key on {port} connected to the app.")
        pipe(ser, sock)
        ser.close()
        sock.close()
        print("Key disconnected. Waiting for the key...")


if __name__ == "__main__":
    main()
