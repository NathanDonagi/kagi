#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${BLINDKEY_PORT:-8000}"

find_adb() {
  if command -v adb >/dev/null 2>&1; then
    command -v adb
    return
  fi
  for candidate in \
    "${ANDROID_HOME:-}/platform-tools/adb" \
    "${ANDROID_SDK_ROOT:-}/platform-tools/adb" \
    "$HOME/Library/Android/sdk/platform-tools/adb"; do
    if [ -n "$candidate" ] && [ -x "$candidate" ]; then
      echo "$candidate"
      return
    fi
  done
  return 1
}

ADB="$(find_adb || true)"
if [ -z "$ADB" ]; then
  echo "adb not found. Open Android Studio once / install Android SDK Platform Tools." >&2
  exit 1
fi

DEVICE_COUNT="$($ADB devices | awk 'NR>1 && $2=="device" {count++} END {print count+0}')"
if [ "$DEVICE_COUNT" -ne 1 ]; then
  echo "Expected exactly one authorized Android device; found $DEVICE_COUNT." >&2
  echo "Connect the demo phone by USB and approve the USB debugging prompt." >&2
  "$ADB" devices
  exit 1
fi

"$ADB" reverse "tcp:$PORT" "tcp:$PORT"
echo "USB tunnel ready: phone http://127.0.0.1:$PORT -> Mac 127.0.0.1:$PORT"

echo "Starting BlindKey verifier on Mac localhost only..."
cd "$ROOT/BlindKeyBackend"
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
source .venv/bin/activate
python3 -m pip install -q -r requirements.txt
exec python3 server.py --host 127.0.0.1 --port "$PORT"
