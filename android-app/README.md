# kagi Android app

The phone version of `desktop_app.py`. Type the 8- or 12-digit code, tap an NFC
tag, and the app answers the check. The phone plays the part of the Arduino Nano:
it holds the key (salted commitments plus the device secret) and produces the
same HMAC proofs, so the servers can't tell it from the Nano. It reaches the
servers over Bluetooth through `bluetooth_bridge.py` (protocol: `communication.md`).

Two NFC tags drive the demo:

| Tag  | Key | Result |
|------|-----|--------|
| Pass | Nathan Donagi, the same key as the Arduino (from `nano_registry.json`) | Passes every check |
| Fail | Someone else, under 18, not registered anywhere | The key says no to age and name checks; the server rejects its sign-up proof |

## Build

`DemoKeys.kt` holds the pass key's device secret, so it isn't committed.
Generate it from the registry first:

```bash
python3 android-app/tools/make_keys.py --registry nano_registry.json
```

Then open `android-app/` in Android Studio, or run `./gradlew assembleDebug`
(`./gradlew testDebugUnitTest` checks the proofs match the servers').

## Run the demo

```bash
# WSL
python3 central_server.py serve
python3 blindgram.py
python3 challenge_site.py
python3 central_server.py forget-site blindgram   # before each sign-up demo

# Windows (Bluetooth on)
py bluetooth_bridge.py
```

1. Pair the phone with the PC in Android's Bluetooth settings.
2. In the app, open Settings: pick the PC and register the pass and fail tags.
3. If it won't connect, enter the RFCOMM channel the bridge printed.

Settings → Debug has:

- **TCP 127.0.0.1:8766**: use `py bluetooth_bridge.py --tcp 8766` plus `adb reverse tcp:8766 tcp:8766` instead of Bluetooth.
- **Simulated tap buttons**: on-screen stand-ins for the tags.
- **Recording mode**: answers with the pass key after 3 s. A real tag tapped within that time wins.
