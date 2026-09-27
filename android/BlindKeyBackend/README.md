# BlindKey verifier API

This wraps Nathan's `blindkey.py` protocol in a small FastAPI service used by the
Android demo app.

## Preferred Android demo: USB tunnel

From the repository root, use:

```bash
./scripts/start_usb_demo.sh
```

That creates `adb reverse tcp:8000 tcp:8000` and starts this server on Mac
localhost only. The phone then uses:

```text
http://127.0.0.1:8000
```

## Manual start

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
python3 server.py --host 127.0.0.1 --port 8000
```

For a LAN-only fallback, explicitly bind all interfaces:

```bash
python3 server.py --host 0.0.0.0 --port 8000
```

and configure the phone with the Mac's LAN address.

## Endpoints

- `GET /health` — API version + short Authority public-key fingerprint
- `POST /verify` — verifies a signed BlindKey credential against one strict query

Responses are non-cacheable and include protocol headers for API version,
Authority fingerprint, and request correlation.

## Security boundary

This is a HackGT prototype service. USB forwarding is preferred because it keeps
the backend off the venue LAN, but HTTP is still not a substitute for production
TLS/service authentication. See the repository `SECURITY_NOTES.md`.
