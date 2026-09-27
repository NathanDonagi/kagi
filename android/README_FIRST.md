# BlindKey Android — HackGT 13 — token-tag revision

This revision is designed for small commodity NFC tags such as the user's
**NTAG213 (142 usable NDEF bytes)**.

## Architecture

```text
NFC tag: tiny opaque bk1:... token
        ↓
Android app: reads token + exact query
        ↓
BlindKey backend: resolves token to Authority-signed credential
        ↓
Nathan's blindkey.py: verifies signature/commitments and evaluates query
        ↓
GREEN / RED / ERROR
```

The tag contains **no name, age, SSN, or 725-byte credential JSON**. Nathan's
signed credential and cryptographic verification remain unchanged on the backend.

## Demo tokens

- `BlindKeyBackend/demo/nathan22.token.txt` — PASS for Over 21
- `BlindKeyBackend/demo/nathan19.token.txt` — FAIL for Over 21

Each token is only 20 ASCII bytes before NDEF framing, so it fits comfortably on
an NTAG213.

## Semantics

- **GREEN** = registered token resolved to an authentic signed credential and the exact requested claim was proved.
- **RED** = registered token resolved to an authentic credential, but the requested claim was false.
- **ERROR** = unknown token, malformed tag, invalid/expired credential, NFC/network/protocol failure.

Read `ANDROID_RUNBOOK.md` next.
