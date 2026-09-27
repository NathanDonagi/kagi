# Android token-tag port notes

The Android transport intentionally differs from the original full-credential NFC
transport because the available physical tags are NTAG213 (about 142 usable NDEF
bytes). The NFC layer now carries a tiny opaque `bk1:...` handle; Nathan's full
signed credential remains on the backend and is still verified by `blindkey.py`.

The privacy goal is preserved for the tag itself: it contains no plaintext name,
age, SSN, or full credential. The security tradeoff is explicit: a static token
on a commodity tag is copyable and is not proof of physical possession by the
enrolled person.
