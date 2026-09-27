# Validation report — token-tag revision

Validated in this build environment:

- Backend Python compilation passes.
- `python3 test_api.py` passes for API v3 token lookup, PASS/RED behavior, unknown-token errors, query validation, request-size limits, request-ID echo, and Authority headers.
- Demo token strings are 20 ASCII bytes each (21-byte files including newline), far below NTAG213 capacity.
- Token registry credentials are authenticated against the configured Authority at server startup.
- Android reader accepts only `bk1:` token records and ignores unrelated NDEF text/URLs.
- The known erroneous explicit Compose `layout.weight` import from v2 is removed.
- Existing backend URL validation, request correlation, Authority pinning, response size bounds, NFC timeout, lifecycle cancellation, and USB `adb reverse` demo transport are preserved.

Final hardware validation still happens in Android Studio + on the physical phone/tag.
