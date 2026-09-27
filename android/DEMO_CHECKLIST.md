# BlindKey Android — 5-minute demo checklist

- [ ] Android phone NFC is ON.
- [ ] USB debugging is authorized.
- [ ] `./scripts/start_usb_demo.sh` is running.
- [ ] App backend URL is `http://127.0.0.1:8000`.
- [ ] Settings → Test Connection says `Connected ✓ API v3` and shows the Authority fingerprint.
- [ ] PASS tag contains exactly the Text record from `demo/nathan22.token.txt`.
- [ ] FAIL tag contains exactly the Text record from `demo/nathan19.token.txt`.
- [ ] Debug controls are OFF.
- [ ] One complete PASS/FAIL sequence was tested immediately before judging.

Demo:

1. Over 21 → YELLOW.
2. Tap age-22 token tag → GREEN / VERIFIED.
3. Scan Another Credential.
4. Tap age-19 token tag → RED / DENIED.
