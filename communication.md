# kagi Android app ↔ PC: communication spec

The Android app is the phone version of `desktop_app.py`: the user types a
code, taps their **RFID key**, and the app sends the key's answer to the kagi
servers on the demo PC. The phone can't reach the PC's `localhost`, so it talks
to the PC over **Bluetooth Classic (RFCOMM)**. On the PC,
`bluetooth_bridge.py` accepts the connection and forwards each request to the
real servers.

This file defines what goes over Bluetooth. Reading the RFID key is the app's
business; this spec only says what the key's answer must look like when it is
sent (§4).

Protocol id: **`kagi-bt-1`**

```
 website (e.g. Blindgram) shows a 12-digit code        host's Zoom page shows an 8-digit code
                     │                                                │
                     ▼                                                ▼
 Android app ──Bluetooth RFCOMM──► bluetooth_bridge.py ──HTTP──► central_server.py  (target "central")
   + RFID key     JSON lines        (Windows Python, PC)        ► challenge_site.py   (target "challenge")
```

---

## 1. Transport

| | |
|---|---|
| Technology | Bluetooth Classic, RFCOMM (serial-port-style stream socket). **Not BLE.** |
| Service UUID | **`083d2893-6eab-4283-b12c-cdf0771acb72`** |
| Service name | `kagi` |
| Pairing | The phone must be **paired** with the demo PC first (Android Settings → Bluetooth; keep Windows' Bluetooth settings page open so the PC is discoverable). The app doesn't scan or pair; it picks from already-paired devices. |
| Encoding | UTF-8 |
| Framing | One JSON object per line, terminated by `\n`. No line may exceed 64 KiB. |

### Android permissions

```xml
<uses-permission android:name="android.permission.BLUETOOTH" android:maxSdkVersion="30" />
<uses-permission android:name="android.permission.BLUETOOTH_ADMIN" android:maxSdkVersion="30" />
<uses-permission android:name="android.permission.BLUETOOTH_CONNECT" />
```

On API 31+ request `BLUETOOTH_CONNECT` at runtime before touching
`bondedDevices` or connecting. No scan or location permission is needed.

### Connecting

```kotlin
val KAGI_UUID: UUID = UUID.fromString("083d2893-6eab-4283-b12c-cdf0771acb72")

// Off the main thread (Dispatchers.IO): connect() blocks.
val adapter = context.getSystemService(BluetoothManager::class.java).adapter
val pc = adapter.bondedDevices.first { it.address == savedPcAddress }   // user picks once; remember the MAC
adapter.cancelDiscovery()
val socket = pc.createRfcommSocketToServiceRecord(KAGI_UUID)
socket.connect()
val reader = socket.inputStream.bufferedReader(Charsets.UTF_8)
val writer = socket.outputStream.bufferedWriter(Charsets.UTF_8)
val hello = JSONObject(reader.readLine())      // §2.1; check hello.protocol == "kagi-bt-1"
```

**If `connect()` fails** (e.g. `read failed, socket might closed`), try
`createInsecureRfcommSocketToServiceRecord(KAGI_UUID)`. If that also fails,
connect to the RFCOMM channel directly. The bridge prints it on startup
(`Bluetooth: listening on RFCOMM channel N ...`); let the user enter N in a
debug setting:

```kotlin
val socket = pc.javaClass.getMethod("createRfcommSocket", Int::class.javaPrimitiveType)
    .invoke(pc, channel) as BluetoothSocket
socket.connect()
```

### Development without Bluetooth (emulator / USB)

The bridge speaks the **identical protocol over TCP**:

```
PC:      py bluetooth_bridge.py --tcp 8766
PC:      adb reverse tcp:8766 tcp:8766
Android: Socket("127.0.0.1", 8766)       // then the same reader/writer code
```

Put the transport (Bluetooth socket or TCP socket) behind one interface that
yields an `InputStream`/`OutputStream`; everything above it is shared.

---

## 2. Messages

### 2.1 Hello (bridge → app, once, right after connecting)

```json
{"type":"hello","protocol":"kagi-bt-1","targets":["central","challenge"]}
```

### 2.2 Request (app → bridge)

```json
{"id":7,"target":"central","method":"POST","path":"/api/challenges/123456789012/response","body":{"key_id":"…","proof":"…"}}
```

| Field | Required | Meaning |
|---|---|---|
| `id` | yes | Number or string chosen by the app, echoed in the response. Use an incrementing integer. |
| `target` | yes | `"central"` (12-digit codes), `"challenge"` (8-digit codes) or `"bridge"` |
| `method` | yes | `"GET"` or `"POST"` |
| `path` | yes | Must start with `/api/`. No `..`, `?`, `#`, spaces or backslashes. |
| `body` | POST only | JSON; sent as the HTTP body. Omitted → `{}`. |

### 2.3 Response (bridge → app, one per request)

```json
{"type":"response","id":7,"status":200,"body":{"status":"complete","result":"new"}}
```

- `status` is the HTTP status from the server, or the bridge's own error status.
- `body` is the server's JSON. On errors it is `{"error": "<human-readable message>"}`,
  which is fine to show the user.
- Responses come back **in request order** (a connection is handled
  sequentially), but always match on `id`.
- If the bridge couldn't parse a request, the response `id` is `null`.

Bridge-generated errors:

| status | cause |
|---|---|
| 400 | bad JSON, missing `id`, unknown `target`, method not GET/POST, path not `/api/...` |
| 404 | unknown `bridge` path; also a `challenge` code that doesn't exist (body then says "non-JSON (404)") |
| 413 | line longer than 64 KiB (the bridge then closes the connection) |
| 502 | the bridge couldn't reach the server (server not running) |

### 2.4 Bridge's own endpoints

| Request | Response body |
|---|---|
| `{"id":1,"target":"bridge","method":"GET","path":"/ping"}` | `{"pong":true}` |
| `{"id":2,"target":"bridge","method":"GET","path":"/info"}` | same object as the hello |

Use `/ping` as a keep-alive / "is the PC still there" check (e.g. every 15 s
while idle).

---

## 3. Flows

The user types a code. Strip spaces and dashes, then route on its length:

| Digits | Target | Flow |
|---|---|---|
| 12 | `central` | 3.1 look up, then 3.2 (sign-up) or 3.3 (age check) by `type` |
| 8 | `challenge` | 3.4 Zoom name check |
| other | | "That isn't a kagi code." |

### 3.1 Look up a 12-digit code

`GET /api/challenges/<code>` on `central`:

```json
// 200, sign-up
{"type":"unique_signup","site_id":"blindgram","site_name":"Blindgram","nonce":"93fdbf3028807a765e17a3b4254d5b31","expires_in":299}
// 200, age check
{"type":"age_check","over":18,"site_id":"blindgram","site_name":"Blindgram","nonce":"2f42f15db557d7b05a7847e18980bf07","expires_in":299}
// 404
{"error":"unknown, expired or already used code"}
```

Keep `site_id`, `nonce` and `over` for the answer. Show `site_name` and
count down `expires_in` (codes last 5 minutes).

### 3.2 Unique sign-up (`type: "unique_signup"`)

Show: **"<site_name> wants to check you're a unique person. Tap your key."**
No name is needed. After the tap:

`POST /api/challenges/<code>/response` on `central`, body:

```json
{"key_id":"1b120e0f3e770faccbf4a262","proof":"<SIGN proof, §4>"}
```

| Response | Show |
|---|---|
| `200 {"status":"complete","result":"new"}` | ✓ **You're in.** "Go back to <site_name> to finish signing up." |
| `200 {"status":"complete","result":"existing"}` | ✗ **Already signed up.** "You already have a <site_name> account. It allows one per person." |
| `400 {"error": …}` | ✗ **Not verified** + the error. A wrong proof can be retried; after 3 wrong proofs the code is burnt. |

### 3.3 Age check (`type: "age_check"`)

Show: **"<site_name> wants to check you're <over> or over."** Ask for the
user's **first and last name**. The name goes only to the key, and is never
sent over Bluetooth. The key checks name + "over <over>".

- **Key says yes:** `POST /api/challenges/<code>/response`, body
  `{"key_id":"…","proof":"<AUTH proof for scope OVER18 or OVER21, §4>"}` → `200 {"status":"complete","result":"verified"}`.
  Show ✓ **Verified <over>+**: "<site_name> now knows you're <over> or over. Nothing else."
- **Key says no** (wrong name, or under age): `POST …/response`, body
  `{"declined":true}` → `200 {"status":"complete","result":"declined"}`.
  Show ✗ **Not verified**: "Your key couldn't confirm you're <over> or over. Check how you spelled your name."
- `400 {"error": …}`: as in 3.2.

The central server checks the proof itself, so the site's "verified" can be
trusted. Don't send a proof the key didn't produce.

### 3.4 Zoom name check (8-digit code, target `challenge`)

`GET /api/challenges/<code>` on `challenge`:

```json
// 200
{"first_name":"Nathan","last_name":"Donagi","nonce":"db37510e73c63af205bba8984f16dd1c","status":"waiting","expires_in":899}
// 404 → "That code doesn't exist or has expired."
```

If `status` isn't `"waiting"`, the code was already answered: show that and stop.

Show: **"Someone wants to check you're <first_name> <last_name>. Tap your key."**
The key checks that name (no user input needed; the host typed it). Then
`POST /api/challenges/<code>/result` on `challenge`:

- **Key says the name matches:** body `{"key_id":"…","proof":"<AUTH proof for scope L1, §4>"}`
  → `200 {"ok":true,"status":"verified"}`. Show ✓ **Verified**: "Your key confirmed this name."
- **Key says no:** body `{"declined":true}` → `200 {"ok":true,"status":"failed"}`.
  Show ✗ **Not verified**: "This key doesn't belong to that person."
- `400 {"error":…}` → the proof didn't verify (3 of these fail the code);
  `409` → already answered or expired.

The host's page turns green or red as soon as this is posted.

---

## 4. The key's answer

Everything the servers check is an **HMAC-SHA256 keyed with the key's 32-byte
`device_secret`**, over an ASCII message built from `|`-separated fields.
These are exactly what the Nano version of the key produces, so the servers
treat an RFID key the same way.

| Used in | Message (UTF-8/ASCII, no trailing newline) |
|---|---|
| 3.2 sign-up (`SIGN`) | `kagi-nano-sign-v1|<key_id>|<site_id>|<nonce>` |
| 3.3 age check (`AUTH`) | `kagi-nano-v1|<key_id>|OVER<over>|<nonce>` e.g. `…|OVER18|…` |
| 3.4 name check (`AUTH`) | `kagi-nano-v1|<key_id>|L1|<nonce>` |

- `key_id`: the key's 12-byte id as **24 lowercase hex chars**.
- `site_id`, `nonce`, `over`: exactly as received in §3 (`nonce` is used as the
  hex **string**, not decoded).
- `proof` sent in JSON: the 32-byte HMAC as **64 lowercase hex chars**.
- Only send an `AUTH` proof when the key actually confirmed the facts (name,
  and age for OVER); otherwise send `{"declined": true}`.

Example (Kotlin):

```kotlin
fun proof(deviceSecret: ByteArray, message: String): String {
    val mac = Mac.getInstance("HmacSHA256")
    mac.init(SecretKeySpec(deviceSecret, "HmacSHA256"))
    return mac.doFinal(message.toByteArray(Charsets.US_ASCII)).joinToString("") { "%02x".format(it) }
}
// sign-up: proof(secret, "kagi-nano-sign-v1|$keyId|$siteId|$nonce")
```

(Whether the HMAC is computed on the card or in the app is up to the app;
the servers only see `key_id` + `proof`.)

### The key must be registered on the PC

The servers look the `key_id` up in `nano_registry.json` on the PC to get its
`device_secret`, owner and expiry. A key that isn't there (or has expired) gets
"the key's answer didn't verify". An entry looks like:

```json
"1b120e0f3e770faccbf4a262": {
  "key_id": "1b120e0f3e770faccbf4a262",
  "person": "<64 hex: HMAC-SHA256(authority_person.key, \"person|\" + 9-digit SSN)>",
  "device_secret": "<64 hex>",
  "iters": 200,
  "issued": "2026-09-26",
  "expires": "2027-09-26"
}
```

`person` is what makes sign-ups one-per-*person*: two keys for the same SSN get
the same `person` and count as one. `nano_provision.py` writes these entries.
For an RFID key, the RFID key's `key_id` and `device_secret` must match an entry
here. Tell the PC side what they are, or have it generate them for the card.

---

## 5. Implementation requirements

1. **All socket I/O off the main thread.** One reader loop that parses lines
   and completes pending requests by `id` (e.g. a map of `id` → `CompletableDeferred`).
2. **Timeouts.** Treat a request with no response after 35 s as failed (the
   bridge's own HTTP timeout is 30 s).
3. **Reconnect.** If the socket closes or a write throws, fail all pending
   requests, show "Reconnecting to PC…", and reconnect with backoff (1 s, 2 s,
   4 s, max 10 s). A looked-up code stays valid on the server until it expires,
   so the user can tap again after reconnecting.
4. **One answer per code.** Don't POST a second answer after a `200`; the
   server rejects it.
5. **Connection status** visible in the UI (connected to <PC name> / reconnecting).
6. **PC selection:** list `bondedDevices` by name, remember the chosen MAC.
   Settings: change PC, optional manual RFCOMM channel (§1 fallback), and a
   debug toggle for TCP `127.0.0.1:8766`.
7. **Privacy:** the user's name (age check) goes only to the key, never over
   Bluetooth. Never log or store codes, nonces, proofs or `device_secret`.
8. **Strict parsing:** ignore unknown fields; treat a missing/unknown `status`
   or `type` as an error.

---

## 6. Running the PC side (for reference)

```bash
python3 central_server.py serve          # :8000 (WSL), 12-digit codes
python3 blindgram.py                     # :8003, a website that shows 12-digit codes
python3 challenge_site.py                # :8002, host page that shows 8-digit codes
py bluetooth_bridge.py                   # WINDOWS Python, Bluetooth on
#   prints: Bluetooth: listening on RFCOMM channel N, service kagi 083d2893-...
```

Reset between demos: `python3 central_server.py forget-site blindgram` (lets
the same person sign up again).

## 7. Example session

```
← {"type":"hello","protocol":"kagi-bt-1","targets":["central","challenge"]}
   user types 8741 5768 5589
→ {"id":1,"target":"central","method":"GET","path":"/api/challenges/874157685589"}
← {"type":"response","id":1,"status":200,"body":{"expires_in":299,"nonce":"93fdbf3028807a765e17a3b4254d5b31","site_id":"blindgram","site_name":"Blindgram","type":"unique_signup"}}
   user taps the key
→ {"id":2,"target":"central","method":"POST","path":"/api/challenges/874157685589/response","body":{"key_id":"1b120e0f3e770faccbf4a262","proof":"4be1…(64 hex)"}}
← {"type":"response","id":2,"status":200,"body":{"result":"new","status":"complete"}}
   user types 4948 3572
→ {"id":3,"target":"challenge","method":"GET","path":"/api/challenges/49483572"}
← {"type":"response","id":3,"status":200,"body":{"expires_in":899,"first_name":"Nathan","last_name":"Donagi","nonce":"db37510e73c63af205bba8984f16dd1c","status":"waiting"}}
   user taps the key; it confirms the name
→ {"id":4,"target":"challenge","method":"POST","path":"/api/challenges/49483572/result","body":{"key_id":"1b120e0f3e770faccbf4a262","proof":"9a07…(64 hex)"}}
← {"type":"response","id":4,"status":200,"body":{"ok":true,"status":"verified"}}
→ {"id":5,"target":"bridge","method":"GET","path":"/ping"}
← {"type":"response","id":5,"status":200,"body":{"pong":true}}
```
