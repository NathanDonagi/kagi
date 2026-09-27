"""Create HackGT demo credentials and compact NFC payloads.

DEMO ONLY. The generated private authority key is intentionally local test data;
do not use these credentials for real identity data.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from blindkey import Authority


def write_private(path: Path, data: bytes) -> None:
    with path.open("wb") as handle:
        try:
            os.fchmod(handle.fileno(), 0o600)
        except OSError:
            pass
        handle.write(data)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent
    demo = root / "demo"
    demo.mkdir(exist_ok=True)

    authority_key = demo / "authority.key"
    authority_pub = demo / "authority.pub"
    existing_assets = [
        authority_pub,
        demo / "nathan22.key.json",
        demo / "nathan22.ndef.txt",
        demo / "nathan19.key.json",
        demo / "nathan19.ndef.txt",
        demo / "tag_registry.json",
        demo / "nathan22.token.txt",
        demo / "nathan19.token.txt",
    ]

    # The handoff ships a matched public key + demo credentials but intentionally
    # omits the private Authority key. Do not silently rotate those demo assets
    # when setup_demo.py is run without --force; that would invalidate any NFC
    # card already written from the included payloads.
    if not args.force and all(path.exists() for path in existing_assets) and not authority_key.exists():
        print("Demo assets already exist and match demo/authority.pub.")
        print("Use --force only if you intentionally want to regenerate them.")
        return

    if authority_key.exists() and not args.force:
        authority = Authority.from_private_bytes(authority_key.read_bytes())
    else:
        authority = Authority.generate()
        write_private(authority_key, authority.private_key_bytes())
        authority_pub.write_bytes(authority.public_key_bytes())

    if not authority_pub.exists():
        authority_pub.write_bytes(authority.public_key_bytes())

    credentials = {
        "nathan22": authority.issue(
            {"first_name": "Nathan", "last_name": "Donagi", "age": 22,
             "ssn": "123-45-6789"},
            pin="4821",
        ),
        "nathan19": authority.issue(
            {"first_name": "Nathan", "last_name": "Donagi", "age": 19,
             "ssn": "123-45-6789"},
            pin="4821",
        ),
    }


    # Tiny opaque NFC handles. These values deliberately encode no age/name/PII.
    tokens = {
        "nathan22": "bk1:UtVTrXmW8_2nNB-H",
        "nathan19": "bk1:fdEtt5zNKYpGc4qz",
    }

    registry = {}
    for name, credential in credentials.items():
        pretty = demo / f"{name}.key.json"
        ndef = demo / f"{name}.ndef.txt"
        pretty.write_text(json.dumps(credential, indent=2), encoding="utf-8")
        compact = json.dumps(credential, separators=(",", ":"))
        ndef.write_text(compact, encoding="utf-8")
        print(f"{ndef.name}: {len(compact.encode('utf-8'))} bytes")
        token = tokens[name]
        (demo / f"{name}.token.txt").write_text(token + "\n", encoding="ascii")
        registry[token] = pretty.name
        print(f"{name}.token.txt: {len(token)} ASCII bytes")

    (demo / "tag_registry.json").write_text(
        json.dumps(registry, indent=2) + "\n", encoding="utf-8"
    )

    print(f"authority.pub: {authority_pub}")
    print("Demo facts: Nathan Donagi, SSN 123-45-6789, PIN 4821")
    print("nathan22 passes OVER18 and OVER21; nathan19 passes OVER18 but fails OVER21.")


if __name__ == "__main__":
    main()
