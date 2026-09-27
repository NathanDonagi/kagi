# Hardening changelog

## v3 — NTAG213 token transport

- Replaced 725-byte on-tag credential with a 20-byte opaque `bk1:` token.
- Backend resolves token to the unchanged Authority-signed BlindKey credential.
- API bumped to v3 so old/new clients cannot silently mix protocols.
- Registry is validated at startup; every registered credential must authenticate under the configured Authority.
- Unknown token is ERROR, never RED.
- Android NFC parser ignores unrelated URL/Text records and accepts only strict `bk1:` tokens.
- Removed the bad explicit Compose `layout.weight` import found during the first real Android build.
- Preserved request-ID checks, Authority fingerprint pinning, scope checks, bounded HTTP, scan timeout, lifecycle cancellation, and USB transport.
