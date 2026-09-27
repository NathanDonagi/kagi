# Security boundaries — HackGT token-tag prototype

What this prototype establishes:

- The NFC tag reveals only an opaque `bk1:...` handle, not plaintext identity attributes or the full signed credential.
- The backend resolves that handle to the Authority-signed BlindKey credential and runs Nathan's existing verifier.
- GREEN means the authentic resolved credential proved exactly the requested scope.
- RED means the authentic resolved credential did not satisfy the requested claim.
- Unknown tokens, invalid credentials, protocol mismatches, and transport failures are ERROR, not RED.
- Test Connection pins the expected backend Authority fingerprint for the demo.

What it does **not** establish:

- A normal NTAG213 is not an unclonable hardware root of trust. Its static token can be copied to another tag.
- Possession of the tag alone does not prove that the presenter is the originally enrolled human.
- The static token is a bearer handle; production would need revocation/rotation and stronger possession binding.
- HTTP (even through USB `adb reverse`) is demo transport, not production authentication.
- Nathan's own commitment caveats still apply.

Production direction: secure element/non-exportable key + challenge-response,
TLS/service authentication, revocation/rotation, replay/abuse controls, and a
carefully designed issuance/recovery flow.
