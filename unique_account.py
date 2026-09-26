#!/usr/bin/env python3
"""
unique_account: one account per person per website, with no way to link the
account back to the person, and no personal data ever shown to the website.

Protocol (Chaum RSA blind signatures, built on blindkey.py)
-----------------------------------------------------------
Setup   The central server registers each website and gives it a dedicated RSA
        key pair. The website gets the public half.

Code    1. The user picks a random nonce and computes h = FDH(site_id || nonce).
        2. The user BLINDS it: b = h * r^e mod n, with a secret random r.
        3. The user authenticates to the server with their blindkey key at
           level 2 (name, age, SSN, PIN) and sends b for a given website.
        4. The server checks that this person has no code for that site yet,
           MARKS them as having one, and returns s' = b^d mod n.
        5. The user unblinds: s = s' * r^-1 mod n. The code is (nonce, s).

Signup  The user gives the code to the website. The website checks
        s^e == FDH(site_id || nonce) mod n using its public key, checks the
        nonce is new, and creates the account. It never contacts the server
        and learns nothing about the user.

Why it works
------------
* One per person: the server refuses a second issuance for (person, site), and
  a code only verifies under its own site's key.
* Unlinkable, unconditionally: the server only ever sees b, which is uniformly
  random because of r, and s'. Given ANY valid code (nonce, s) there is an r'
  that makes the server's transcript consistent with it (demonstrated below).
  So the server, the website, or anyone who knows everything, including the
  server's secret key and logs, cannot tell which issuance produced which
  code. There is no stored mapping to destroy.
* Sites can't collude: each site has its own key and each code its own nonce,
  so accounts on different sites can't be linked either.

Caveats
-------
* Metadata: the server knows THAT a person requested a code for a site, and
  when. If issuance and signup happen close together from the same IP, timing
  and network address can correlate them. Use delays or an anonymizing network.
* A code is a bearer token: it can be handed or sold to someone else. It caps
  one account per real person, not per person-who-cooperates.
* If a user loses their code before using it, the server can't safely reissue
  it without weakening the one-per-person rule; that policy is up to you.
* Hand-rolled RSA-FDH blinding for a prototype. For production use RFC 9474
  (RSABSSA) from a vetted library.
"""

import hashlib
import hmac
import math
import secrets
import threading
import time

from cryptography.hazmat.primitives.asymmetric import rsa

from blindkey import Verifier, b64, normalize, unb64

RSA_BITS = 2048
MARK_SCRYPT_N = 2**17                       # ~128 MiB, ~0.25s per guess
MAX_FAILURES, FAILURE_WINDOW = 10, 3600     # failed logins per key per hour
L2_FIELDS = {"first_name", "last_name", "age", "ssn", "pin"}


def fdh(msg: bytes, n: int) -> int:
    """Full-domain hash of msg into Z_n."""
    k = (n.bit_length() + 7) // 8 + 16
    out = b"".join(
        hashlib.sha256(b"unique-account-v1" + i.to_bytes(4, "big") + msg).digest()
        for i in range((k + 31) // 32))
    return int.from_bytes(out[:k], "big") % n


def token_message(site_id: str, nonce: bytes) -> bytes:
    return site_id.encode() + b"\x00" + nonce


class RefusedError(Exception):
    pass


# ---------- Central server ----------

class Issuer:
    """Knows people (via their blindkey keys); signs blinded values, once per (person, site).

    `pepper` is a long-term secret. It MUST be stored somewhere other than the
    database holding `_issued` (an HSM/KMS, ideally used as an HMAC oracle) and
    it MUST persist across restarts, otherwise old marks stop matching and the
    one-per-person rule silently resets.
    """

    def __init__(self, authority_public: bytes, pepper: bytes):
        if len(pepper) < 32:
            raise ValueError("pepper must be at least 32 random bytes")
        self._verifier = Verifier(authority_public)
        self._pepper = pepper
        self._lock = threading.Lock()
        self._site_keys = {}       # site_id -> (n, e, d)
        self._issued = set()       # opaque per-(person, site) marks: the ONLY per-person state
        self._failures = {}        # HMAC(key id) -> times of recent failed logins

    def register_site(self, site_id: str):
        """Returns the site's public key (n, e)."""
        sk = rsa.generate_private_key(public_exponent=65537, key_size=RSA_BITS)
        pn = sk.private_numbers()
        n, e = pn.public_numbers.n, pn.public_numbers.e
        self._site_keys[site_id] = (n, e, pn.d)
        return n, e

    def _mark(self, ssn: str, site_id: str) -> bytes:
        """Deterministic opaque marker for (person, site).

        * Keyed with the pepper: a database dump alone can't be tested against
          guessed SSNs at all.
        * Per-site: the same person has unrelated marks on different sites, so
          a dump can't be joined into "which sites does this person use".
        * scrypt on top: even if the pepper leaks too, each SSN guess costs a
          128 MiB memory-hard hash instead of a microsecond HMAC.
        """
        inner = hmac.new(self._pepper,
                         b"mark|" + site_id.encode() + b"|" + normalize("ssn", ssn).encode(),
                         "sha256").digest()
        return hashlib.scrypt(inner, salt=b"unique-account-mark-v1", n=MARK_SCRYPT_N, r=8,
                              p=1, maxmem=256 * 1024 * 1024, dklen=32)

    def _throttle_id(self, key: dict) -> bytes:
        # Hashed so the failure table isn't a list of key ids.
        return hmac.new(self._pepper, b"throttle|" + str(key["id"]).encode(), "sha256").digest()

    @staticmethod
    def _blind_sign(x: int, n: int, e: int, d: int) -> int:
        """x^d mod n with server-side blinding, so the time taken by the private
        exponentiation is independent of the client-chosen input (remote timing
        attacks on RSA need attacker-controlled inputs)."""
        while True:
            s = secrets.randbelow(n - 2) + 2
            if math.gcd(s, n) == 1:
                break
        return pow(x * pow(s, e, n) % n, d, n) * pow(s, -1, n) % n

    def issue(self, key: dict, query: dict, site_id: str, blinded: int) -> int:
        if site_id not in self._site_keys:
            raise RefusedError("unknown site")
        # Cheap signature check first: junk keys never touch scrypt or the failure table.
        if not isinstance(key, dict) or not self._verifier.key_is_authentic(key):
            raise RefusedError("authentication failed")
        if set(query) != L2_FIELDS:
            raise RefusedError("level-2 credentials required")

        tid, now = self._throttle_id(key), time.time()
        with self._lock:
            recent = [t for t in self._failures.get(tid, []) if now - t < FAILURE_WINDOW]
            self._failures[tid] = recent
            if len(recent) >= MAX_FAILURES:
                raise RefusedError("too many failed attempts, try again later")

        session = self._verifier.authenticate(key, query)
        if not session or self._verifier.check_code(session) != "L2":
            with self._lock:
                self._failures[tid].append(time.time())
            raise RefusedError("authentication failed")   # does not use up the quota

        n, e, d = self._site_keys[site_id]
        if not 1 < blinded < n:
            raise RefusedError("bad blinded value")
        mark = self._mark(query["ssn"], site_id)
        with self._lock:                       # atomic check-and-set: no double issuance
            if mark in self._issued:
                raise RefusedError("this person already has an account code for this site")
            self._issued.add(mark)
        return self._blind_sign(blinded, n, e, d)


# ---------- User side ----------

def request_code(issuer: Issuer, key: dict, query: dict, site_id: str, site_pub,
                 transcript: list = None) -> str:
    """Runs the blind-issuance protocol; returns the code to give to the website.
    `transcript`, if given, receives everything the server saw (for the demo)."""
    n, e = site_pub
    nonce = secrets.token_bytes(32)
    h = fdh(token_message(site_id, nonce), n)
    while True:
        r = secrets.randbelow(n - 2) + 2
        if math.gcd(r, n) == 1:
            break
    blinded = h * pow(r, e, n) % n
    blind_sig = issuer.issue(key, query, site_id, blinded)
    if transcript is not None:
        transcript.append((blinded, blind_sig))
    sig = blind_sig * pow(r, -1, n) % n
    if pow(sig, e, n) != h:
        raise RefusedError("issuer returned a bad signature")
    return f"{b64(nonce)}.{b64(sig.to_bytes((n.bit_length() + 7) // 8, 'big'))}"


# ---------- Website ----------

class Website:
    """Sees only the code. Never contacts the server, never learns who the user is."""

    def __init__(self, site_id: str, public_key):
        self.site_id = site_id
        self._n, self._e = public_key
        self._used = set()
        self.accounts = []

    def create_account(self, code: str) -> str:
        try:
            nonce_s, sig_s = code.split(".")
            nonce, sig = unb64(nonce_s), int.from_bytes(unb64(sig_s), "big")
        except ValueError:
            raise RefusedError("malformed code")
        if not 0 < sig < self._n or pow(sig, self._e, self._n) != fdh(
                token_message(self.site_id, nonce), self._n):
            raise RefusedError("invalid code")
        if nonce in self._used:
            raise RefusedError("code already used")
        self._used.add(nonce)
        account_id = hashlib.sha256(nonce).hexdigest()[:16]
        self.accounts.append(account_id)
        return account_id


# ---------- demo ----------

def consistent(pub, site_id, transcript_entry, code) -> bool:
    """Could `code` have come from this server transcript (blinded, blind_sig)?
    Solves for the blinding factor r' that would link them. For every valid
    code such an r' exists, so the transcript proves nothing about which code
    it produced."""
    n, e = pub
    blinded, blind_sig = transcript_entry
    nonce_s, sig_s = code.split(".")
    h = fdh(token_message(site_id, unb64(nonce_s)), n)
    sig = int.from_bytes(unb64(sig_s), "big")
    r2 = blind_sig * pow(sig, -1, n) % n
    return h * pow(r2, e, n) % n == blinded


def demo():
    from blindkey import Authority
    print("== demo ==")
    authority = Authority.generate()
    pepper = secrets.token_bytes(32)
    issuer = Issuer(authority.public_key_bytes(), pepper)
    pub_a, pub_b = issuer.register_site("shop.example"), issuer.register_site("forum.example")
    site_a, site_b = Website("shop.example", pub_a), Website("forum.example", pub_b)

    alice_facts = {"first_name": "Alice", "last_name": "Nguyen", "age": 25, "ssn": "111-22-3333"}
    bob_facts = {"first_name": "Bob", "last_name": "Ortiz", "age": 40, "ssn": "444-55-6666"}
    alice_key, bob_key = authority.issue(alice_facts, "1234"), authority.issue(bob_facts, "9876")
    alice_q = {**alice_facts, "age": "25", "pin": "1234"}
    bob_q = {**bob_facts, "age": "40", "pin": "9876"}

    def expect_refused(label, fn):
        try:
            fn()
        except RefusedError as ex:
            print(f"NO  {label}: {ex}")
        else:
            raise AssertionError(f"{label} should have been refused")

    seen = []
    a_code = request_code(issuer, alice_key, alice_q, "shop.example", pub_a, seen)
    b_code = request_code(issuer, bob_key, bob_q, "shop.example", pub_a, seen)
    print("OK  alice's account:", site_a.create_account(a_code))
    print("OK  bob's account:  ", site_a.create_account(b_code))

    expect_refused("alice replays her code", lambda: site_a.create_account(a_code))
    expect_refused("alice asks for a second code", lambda: request_code(
        issuer, alice_key, alice_q, "shop.example", pub_a))
    # Even with a re-issued key (new id), she's the same person.
    alice_key2 = authority.issue(alice_facts, "1234")
    expect_refused("alice tries again with a fresh key", lambda: request_code(
        issuer, alice_key2, alice_q, "shop.example", pub_a))
    expect_refused("wrong pin", lambda: request_code(
        issuer, bob_key, {**bob_q, "pin": "0000"}, "forum.example", pub_b))
    # A failed authentication didn't burn Bob's quota for the other site:
    print("OK  bob's forum account:", site_b.create_account(
        request_code(issuer, bob_key, bob_q, "forum.example", pub_b)))
    expect_refused("shop code used on forum", lambda: site_b.create_account(a_code))
    expect_refused("forged code", lambda: site_a.create_account(
        b64(secrets.token_bytes(32)) + "." + b64(secrets.token_bytes(256))))

    # Unlinkability: the server's records are consistent with EITHER code.
    (alice_t, bob_t) = seen
    for t in (alice_t, bob_t):
        for c in (a_code, b_code):
            assert consistent(pub_a, "shop.example", t, c)
    print("OK  server transcripts are consistent with every code (2x2 checked): "
          "no way to tell whose is whose")
    print("    server keeps only:", len(issuer._issued), "opaque marks; "
          "no codes, no blinded values, no SSNs, no site names")

    # Marks: per-site, keyed by the pepper.
    m_a, m_b = issuer._mark("444-55-6666", "shop.example"), issuer._mark("444556666", "forum.example")
    assert m_a in issuer._issued and m_b in issuer._issued and m_a != m_b   # bob, both sites
    assert Issuer(authority.public_key_bytes(), secrets.token_bytes(32))._mark(
        "444556666", "shop.example") != m_a
    print("OK  same person has unrelated marks per site; marks depend on the pepper")

    # Online guessing is throttled per key.
    carol_facts = {"first_name": "Carol", "last_name": "Diaz", "age": 30, "ssn": "777-88-9999"}
    carol_key = authority.issue(carol_facts, "5555")
    carol_q = {**carol_facts, "age": "30", "pin": "5555"}
    for pin in range(MAX_FAILURES):
        try:
            request_code(issuer, carol_key, {**carol_q, "pin": f"{pin:04d}"}, "shop.example", pub_a)
        except RefusedError:
            pass
    try:
        request_code(issuer, carol_key, carol_q, "shop.example", pub_a)
        raise AssertionError("throttle failed")
    except RefusedError as ex:
        print(f"NO  carol, correct pin after {MAX_FAILURES} failures: {ex}")
    print("all checks passed")


if __name__ == "__main__":
    demo()
