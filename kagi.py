#!/usr/bin/env python3
"""
kagi: a prototype "attribute-bound key" authentication protocol.

An Authority issues a Key tied to a person's facts, but the Key reveals nothing
about them. A holder can test guesses ("is the first name Nathan?") and get a
yes/no; the only way to learn a fact from the key is to guess it.

Levels (hashes build on each other)
-----------------------------------
Level 1: full_name (first + last hashed TOGETHER), age.
    C1[full_name] = scrypt(["L1", "full_name", name],      salt)
    C1[age]       = scrypt(["L1", "age", name, age],       salt)
    First and last name are one commitment: a query must supply both, and
    neither can be tested alone. Age is chained onto the name, so it can't be
    guessed (only ~100 possibilities!) without first knowing the name.

Level 2: ssn (more can be added to LEVEL2).
    C2[f] = scrypt(["L2", f, full_name, age, pin, value], salt2[f])
    The commitment covers EVERY level-1 value plus a 4-digit PIN, so a query for
    a level-2 field must supply all of them, and brute-forcing one from the key
    means searching first x last x age x PIN x SSN jointly. Cracking the
    level-1 commitments first does not shortcut it: level 2 still needs the PIN
    and SSN, and the cost is multiplied, not added.

Age thresholds ("over 18", "over 21"): a query of first_name + last_name + over=T
    O[T] = scrypt(["OVER", T, full_name], salt)   if age >= T
    O[T] = random bytes (decoy)                   otherwise
    The verifier learns only pass/fail; the key doesn't say whether a threshold
    is met (decoys look identical), and age itself is never revealed or needed.

The Authority signs (id, expiry, all salts and commitments) with Ed25519, so
keys can't be forged; verifiers need only the public key.

Caveats
-------
* Low-entropy facts can still be brute-forced offline; scrypt + stacking only
  make it expensive. Level 2 is the strong part: the attacker needs all of
  level 1 AND the PIN (10^4) AND the SSN (~10^9).
* Holding the key and knowing the answers is enough to authenticate. It proves
  attestation, not identity of the presenter.
* Age changes every year; a key with age (and over-18/21 flags) baked in goes
  stale. Swap in date of birth if that matters.
"""

import argparse
import base64
import hashlib
import hmac
import json
import os
import secrets
import sys
import time
import unicodedata

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

# ---- schema ----
LEVEL1 = ["full_name", "age"]                # order matters: it's hashed into level 2
NAME_PARTS = ["first_name", "last_name"]     # combined into full_name; never queried alone
OVER_THRESHOLDS = [18, 21]
LEVEL2 = ["ssn"]
PIN_FIELD = "pin"

# scrypt cost: ~64 MiB, ~100ms per guess. Raise N for more brute-force resistance.
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2**16, 8, 1
SCRYPT_MAXMEM = 128 * 1024 * 1024


# ---------- helpers ----------

def b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def normalize(field: str, value: str) -> str:
    """Canonical form so 'Nathan ', 'nathan' and '  NATHAN' all match."""
    value = unicodedata.normalize("NFKC", str(value)).casefold()
    value = " ".join(value.split())
    if field == "ssn":
        value = value.replace("-", "").replace(" ", "")
        if not (value.isdigit() and len(value) == 9):
            raise ValueError("ssn must be 9 digits")
    elif field == "age":
        if not value.isdigit():
            raise ValueError("age must be a whole number")
        value = str(int(value))
    elif field == PIN_FIELD:
        if not (value.isdigit() and len(value) == 4):
            raise ValueError("pin must be exactly 4 digits")
    elif not value:
        raise ValueError(f"{field} must not be empty")
    return value


def scrypt_hash(parts: list, salt: bytes) -> bytes:
    # JSON encoding is unambiguous: ["a","bc"] can never equal ["ab","c"].
    return hashlib.scrypt(
        json.dumps(parts, separators=(",", ":")).encode(), salt=salt,
        n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, maxmem=SCRYPT_MAXMEM, dklen=32,
    )


def commit1(field: str, level1: dict, salt: bytes) -> bytes:
    # Chained: each level-1 commitment also covers every field before it, so
    # age can never be tested (or brute-forced) without the full name.
    chain = LEVEL1[:LEVEL1.index(field) + 1]
    return scrypt_hash(["L1", field] + [level1[f] for f in chain], salt)


def commit2(field: str, level1: dict, pin: str, value: str, salt: bytes) -> bytes:
    return scrypt_hash(["L2", field] + [level1[f] for f in LEVEL1] + [pin, value], salt)


def commit_over(threshold: int, full_name: list, salt: bytes) -> bytes:
    return scrypt_hash(["OVER", threshold, full_name], salt)


def signing_payload(key: dict) -> bytes:
    body = {k: key[k] for k in ("v", "id", "exp", "l1", "l2", "over")}
    return json.dumps(body, sort_keys=True, separators=(",", ":")).encode()


def level1_values(raw: dict) -> dict:
    """Normalized level-1 values present in `raw`. first_name and last_name are
    only accepted together and become the single value full_name = [first, last]."""
    out = {}
    parts = [p for p in NAME_PARTS if p in raw]
    if parts:
        if len(parts) != len(NAME_PARTS):
            raise ValueError("first_name and last_name must be given together")
        out["full_name"] = [normalize(p, raw[p]) for p in NAME_PARTS]
    if "age" in raw:
        out["age"] = normalize("age", raw["age"])
    return out


# ---------- Authority ----------

class Authority:
    """Holds the private signing key; issues keys bound to facts."""

    def __init__(self, private_key: Ed25519PrivateKey):
        self._sk = private_key

    @classmethod
    def generate(cls):
        return cls(Ed25519PrivateKey.generate())

    @classmethod
    def from_private_bytes(cls, raw: bytes):
        return cls(Ed25519PrivateKey.from_private_bytes(raw))

    def public_key_bytes(self) -> bytes:
        return self._sk.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw)

    def private_key_bytes(self) -> bytes:
        return self._sk.private_bytes(
            serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
            serialization.NoEncryption())

    def issue(self, facts: dict, pin: str, ttl_seconds: int = 365 * 86400) -> dict:
        """facts: first_name, last_name, age, ssn."""
        missing = [f for f in NAME_PARTS + ["age"] + LEVEL2 if f not in facts]
        if missing:
            raise ValueError(f"missing fields: {missing}")
        l1v = level1_values(facts)
        l2v = {f: normalize(f, facts[f]) for f in LEVEL2}
        pin = normalize(PIN_FIELD, pin)
        age = int(l1v["age"])

        l1, l2, over = {}, {}, {}
        for f in LEVEL1:
            salt = secrets.token_bytes(32)
            l1[f] = {"salt": b64(salt), "c": b64(commit1(f, l1v, salt))}
        for f in LEVEL2:
            salt = secrets.token_bytes(32)
            l2[f] = {"salt": b64(salt), "c": b64(commit2(f, l1v, pin, l2v[f], salt))}
        for t in OVER_THRESHOLDS:
            salt = secrets.token_bytes(32)
            # Unmet thresholds get random bytes: indistinguishable from real ones.
            c = commit_over(t, l1v["full_name"], salt) if age >= t else secrets.token_bytes(32)
            over[str(t)] = {"salt": b64(salt), "c": b64(c)}

        key = {"v": 3, "id": b64(secrets.token_bytes(12)),
               "exp": int(time.time()) + ttl_seconds, "l1": l1, "l2": l2, "over": over}
        key["sig"] = b64(self._sk.sign(signing_payload(key)))
        return key


# ---------- Verifier ----------

class Verifier:
    """Needs only the Authority's public key plus its own secret for session codes."""

    def __init__(self, authority_public: bytes, session_secret: bytes = None,
                 session_ttl: int = 300):
        self._pk = Ed25519PublicKey.from_public_bytes(authority_public)
        self._secret = session_secret or secrets.token_bytes(32)
        self._ttl = session_ttl

    def key_is_authentic(self, key: dict) -> bool:
        try:
            if key["v"] != 3 or key["exp"] < time.time():
                return False
            if (set(key["l1"]) != set(LEVEL1) or set(key["l2"]) != set(LEVEL2)
                    or set(key["over"]) != {str(t) for t in OVER_THRESHOLDS}):
                return False
            self._pk.verify(unb64(key["sig"]), signing_payload(key))
            return True
        except (InvalidSignature, KeyError, TypeError, ValueError):
            return False

    def authenticate(self, key: dict, query: dict):
        """
        Three kinds of query (mixing kinds is rejected):

        * Age threshold: {first_name, last_name, over: 18|21}
        * Level 1:       {first_name + last_name (together), optionally with age}
        * Level 2:       {ssn, first_name, last_name, age, pin}  (all required)

        Returns a session code on success, else None. A failure gives no hint
        about which part was wrong.
        """
        try:
            if not query or not self.key_is_authentic(key):
                return None
            if set(query) - set(NAME_PARTS) - {"age", "over", PIN_FIELD} - set(LEVEL2):
                return None

            if "over" in query:
                return self._auth_over(key, query)

            l1v = level1_values(query)
            asked_l2 = [f for f in LEVEL2 if f in query]
            if asked_l2:
                if set(l1v) != set(LEVEL1) or PIN_FIELD not in query:
                    return None
            elif PIN_FIELD in query or "full_name" not in l1v:
                return None        # level 1 always needs the name; a pin alone is meaningless

            ok = True
            for f in l1v:
                c = key["l1"][f]
                ok &= hmac.compare_digest(commit1(f, l1v, unb64(c["salt"])), unb64(c["c"]))
            if asked_l2:
                pin = normalize(PIN_FIELD, query[PIN_FIELD])
                for f in asked_l2:
                    c = key["l2"][f]
                    guess = commit2(f, l1v, pin, normalize(f, query[f]), unb64(c["salt"]))
                    ok &= hmac.compare_digest(guess, unb64(c["c"]))
        except (ValueError, KeyError, TypeError):
            return None
        return self._mint_code(key["id"], "L2" if asked_l2 else "L1") if ok else None

    def _auth_over(self, key: dict, query: dict):
        if set(query) != set(NAME_PARTS) | {"over"}:
            return None
        t = int(query["over"])
        if t not in OVER_THRESHOLDS:
            return None
        name = level1_values(query)["full_name"]
        c = key["over"][str(t)]
        if hmac.compare_digest(commit_over(t, name, unb64(c["salt"])), unb64(c["c"])):
            return self._mint_code(key["id"], f"OVER{t}")
        return None

    # session code = id.scope.expiry.nonce.mac
    def _mint_code(self, key_id: str, scope: str) -> str:
        body = f"{key_id}.{scope}.{int(time.time()) + self._ttl}.{b64(secrets.token_bytes(8))}"
        mac = hmac.new(self._secret, body.encode(), hashlib.sha256).digest()
        return f"{body}.{b64(mac)}"

    def check_code(self, code: str):
        """Returns the proven scope ("L1", "L2", "OVER18", "OVER21") or None."""
        try:
            body, mac = code.rsplit(".", 1)
            _, scope, expiry, _ = body.split(".")
            good = hmac.new(self._secret, body.encode(), hashlib.sha256).digest()
            if hmac.compare_digest(good, unb64(mac)) and int(expiry) >= time.time():
                return scope
        except ValueError:
            pass
        return None


# ---------- CLI ----------

def cmd_init(a):
    auth = Authority.generate()
    with open(a.dir + "/authority.key", "wb") as f:
        os.fchmod(f.fileno(), 0o600)
        f.write(auth.private_key_bytes())
    with open(a.dir + "/authority.pub", "wb") as f:
        f.write(auth.public_key_bytes())
    print(f"wrote {a.dir}/authority.key (KEEP SECRET) and {a.dir}/authority.pub")


def cmd_issue(a):
    auth = Authority.from_private_bytes(open(a.authority_key, "rb").read())
    facts = {"first_name": a.first_name, "last_name": a.last_name,
             "age": a.age, "ssn": a.ssn}
    key = auth.issue(facts, a.pin)
    json.dump(key, open(a.out, "w"), indent=2)
    print(f"issued {a.out}")


def cmd_verify(a):
    ver = Verifier(open(a.authority_pub, "rb").read())
    key = json.load(open(a.key))
    query = dict(q.split("=", 1) for q in a.query)
    code = ver.authenticate(key, query)
    if code:
        print("AUTHENTICATED", code)
    else:
        print("DENIED")
        sys.exit(1)


def demo():
    print("== demo ==")
    authority = Authority.generate()
    facts = {"first_name": "Nathan", "last_name": "Donagi", "age": 19,
             "ssn": "123-45-6789"}
    key = authority.issue(facts, pin="4821")
    print("key (opaque):", json.dumps(key)[:150], "...")
    ver = Verifier(authority.public_key_bytes())

    name = {"first_name": "Nathan", "last_name": "Donagi"}
    full = {**name, "age": "19", "ssn": "123456789", "pin": "4821"}
    cases = [
        ("L1: full name", name, True),
        ("L1: name, different case", {"first_name": "NATHAN", "last_name": " donagi"}, True),
        ("L1: name + age", {**name, "age": "19"}, True),
        ("L1: age alone", {"age": "19"}, False),
        ("L1: first name alone", {"first_name": "Nathan"}, False),
        ("L1: last name alone", {"last_name": "Donagi"}, False),
        ("L1: wrong last name", {"first_name": "Nathan", "last_name": "Smith"}, False),
        ("L2: everything correct", full, True),
        ("L2: ssn with dashes", {**full, "ssn": "123-45-6789"}, True),
        ("L2: ssn only", {"ssn": "123456789"}, False),
        ("L2: ssn + pin, no level-1", {"ssn": "123456789", "pin": "4821"}, False),
        ("L2: missing age", {k: v for k, v in full.items() if k != "age"}, False),
        ("L2: first name only", {**{k: v for k, v in full.items() if k != "last_name"}}, False),
        ("L2: wrong pin", {**full, "pin": "0000"}, False),
        ("L2: wrong ssn", {**full, "ssn": "999999999"}, False),
        ("L2: wrong first name", {**full, "first_name": "Nate"}, False),
        ("pin with no ssn", {**name, "pin": "4821"}, False),
        ("over 18 (age 19)", {**name, "over": 18}, True),
        ("over 21 (age 19)", {**name, "over": 21}, False),
        ("over 18, wrong name", {"first_name": "Nathan", "last_name": "Smith", "over": 18}, False),
        ("over 18, first name only", {"first_name": "Nathan", "over": 18}, False),
        ("over 18 + extra fields", {**name, "over": 18, "age": "19"}, False),
        ("over 25 (unsupported)", {**name, "over": 25}, False),
    ]
    for label, q, expect in cases:
        code = ver.authenticate(key, q)
        assert bool(code) == expect, label
        print(f"{'OK ' if code else 'NO '} {label}")
    assert ver.check_code(ver.authenticate(key, full)) == "L2"
    assert ver.check_code(ver.authenticate(key, name)) == "L1"
    assert ver.check_code(ver.authenticate(key, {**name, "over": 18})) == "OVER18"

    # Someone 21+ passes both; under-18 passes neither, and their key has
    # the same shape (decoys), so it doesn't reveal that.
    adult = authority.issue({**facts, "age": 30}, pin="4821")
    assert ver.authenticate(adult, {**name, "over": 21})
    kid = authority.issue({**facts, "age": 15}, pin="4821")
    assert not ver.authenticate(kid, {**name, "over": 18})
    assert kid["over"].keys() == adult["over"].keys()
    assert all(len(unb64(v["c"])) == 32 for v in kid["over"].values())
    print("thresholds behave; decoys same shape")

    # Forgery: attacker swaps in their own over-21 commitment.
    forged = json.loads(json.dumps(kid))
    salt = secrets.token_bytes(32)
    forged["over"]["21"] = {"salt": b64(salt), "c": b64(commit_over(21, ["nathan", "donagi"], salt))}
    assert ver.authenticate(forged, {**name, "over": 21}) is None
    print("forged over-21 rejected")

    rogue = Authority.generate().issue(facts, pin="4821")
    assert ver.authenticate(rogue, full) is None
    print("rogue-authority key rejected")
    print("all checks passed")


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    sub = p.add_subparsers(dest="cmd")
    s = sub.add_parser("init", help="generate authority keypair")
    s.add_argument("--dir", default=".")
    s.set_defaults(fn=cmd_init)
    s = sub.add_parser("issue", help="issue a key bound to a person's facts")
    s.add_argument("--authority-key", default="authority.key")
    s.add_argument("--out", default="user.key.json")
    for f in ("first-name", "last-name", "age", "ssn", "pin"):
        s.add_argument(f"--{f}", required=True)
    s.set_defaults(fn=cmd_issue)
    s = sub.add_parser("verify", help='check queries, e.g. first_name=Nathan last_name=Donagi over=21')
    s.add_argument("--authority-pub", default="authority.pub")
    s.add_argument("--key", default="user.key.json")
    s.add_argument("query", nargs="+")
    s.set_defaults(fn=cmd_verify)
    sub.add_parser("demo", help="run self-test").set_defaults(fn=lambda a: demo())
    a = p.parse_args()
    (a.fn if a.cmd else lambda _: demo())(a)


if __name__ == "__main__":
    main()
