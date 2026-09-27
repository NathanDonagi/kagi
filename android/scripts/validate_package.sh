#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "== BlindKey token-tag package validation =="

cd "$ROOT/BlindKeyBackend"
python3 -m py_compile ./*.py
python3 test_api.py

for payload in demo/nathan19.token.txt demo/nathan22.token.txt; do
  bytes="$(wc -c < "$payload" | tr -d ' ')"
  echo "  $payload: $bytes bytes including newline"
  if [ "$bytes" -gt 96 ]; then
    echo "Token unexpectedly exceeds app safety limit." >&2
    exit 1
  fi
done

bash -n "$ROOT/gradlew"
bash -n "$ROOT/scripts/start_usb_demo.sh"
bash -n "$ROOT/scripts/validate_package.sh"

if [ -d "${ANDROID_HOME:-$HOME/Library/Android/sdk}" ] || [ -d "${ANDROID_SDK_ROOT:-}" ]; then
  cd "$ROOT"
  ./gradlew testDebugUnitTest --stacktrace
else
  echo "Android SDK not detected here; use Android Studio on the Mac for the final app build."
fi

echo "Validation complete."
