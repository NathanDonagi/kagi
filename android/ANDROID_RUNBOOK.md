# BlindKey Android — exact NTAG213 runbook

## 1. Build/install

Open this folder in Android Studio, let Gradle Sync finish, select the physical
Android phone, and press Run. The known Compose `weight` import issue from v2 is
fixed in this revision.

## 2. Start the backend over USB

Keep the phone plugged in with USB debugging authorized. From the project root:

```bash
./scripts/start_usb_demo.sh
```

On the phone, BlindKey → Settings:

```text
Backend URL: http://127.0.0.1:8000
```

Tap **Test Connection**. Expected:

```text
Connected ✓  API v3  Authority <fingerprint>
```

## 3. Reprogram the NTAG213

Your NTAG213 has about 142 bytes usable NDEF capacity. Do **not** write the old
725-byte credential JSON.

For the PASS tag, open:

```text
BlindKeyBackend/demo/nathan22.token.txt
```

It contains exactly:

```text
bk1:UtVTrXmW8_2nNB-H
```

In NFC Tools:

1. **Write**
2. **Add a record**
3. **Text**
4. Paste only that one token (no quotes, no explanation)
5. Save/add the record
6. Tap **Write** and touch the NTAG213
7. Read it back and confirm the Text record is exactly the token

For a second FAIL tag, write:

```text
bk1:fdEtt5zNKYpGc4qz
```

from `BlindKeyBackend/demo/nathan19.token.txt`.

The token is only 20 ASCII bytes, so it fits comfortably on an NTAG213.

## 4. End-to-end PASS test

1. Keep `./scripts/start_usb_demo.sh` running.
2. BlindKey → Settings → Test Connection.
3. Select **Over 21**.
4. Tap **Scan Credential**.
5. Touch the `nathan22` token tag.
6. Expected: YELLOW → VERIFYING → **GREEN / VERIFIED**.

## 5. End-to-end RED test

1. Tap **Scan Another Credential**.
2. Touch the `nathan19` token tag.
3. Expected: **RED / DENIED**.

## 6. What is actually happening

The NFC tag contains no age/name/SSN and no full credential. It holds only an
opaque lookup handle. The backend resolves that handle to the original
Authority-signed BlindKey credential and then runs Nathan's normal signature +
commitment verification against the exact query.

## 7. Expected semantics

```text
GREEN = known token → authentic signed credential → requested claim true
RED   = known token → authentic signed credential → requested claim false
ERROR = unknown token / NFC / network / backend / credential integrity problem
```

## 8. Important security wording

Say **privacy-preserving selective verification prototype**.
Do not claim the NTAG213 is unclonable. A static token on a commodity NDEF tag
can be copied; production possession proof needs challenge-response with a
non-exportable private key / secure element.
