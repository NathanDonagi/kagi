# kagi

Privacy-preserving identity for the web, built at HackGT 26.

A central authority issues each person a **key** that is cryptographically tied to
facts about them (name, date of birth, SSN), but the key reveals **nothing** about
those facts. The only way to get a fact out of it is to guess, and the key only
ever answers yes or no. On top of the key we build **one account per person per
website**: a site can be sure each real person signs up at most once, without
ever learning who they are. The same key can also prove "I'm over 18" to a site,
or "my name really is Nathan Donagi" to someone on a video call.

The project has four layers:

| Layer | What it is | Files |
|---|---|---|
| **1. The key** | Signed, salted commitments you can query but not read | `kagi.py` |
| **2. The key in hardware** | The same key living on an Arduino Nano; the PC asks it questions over USB serial | `kagi_nano/kagi_nano.ino`, `nano_provision.py`, `nano_client.py` |
| **3. One account per person** | Two designs: an unlinkable blind-signature protocol, and a tap-your-key sign-up flow with a central server, demo websites (including an Instagram-style one with 18+ Reels) and a user app | `unique_account.py`; `central_server.py`, `website.py`, `blindgram.py`, `phone_app.py`, `desktop_app.py` |
| **4. Who am I talking to?** | A Zoom-style name check: the host sends a code, the other person's key says whether the name matches | `challenge_site.py`, `desktop_app.py` |

> **Status: research prototype.** The Python design has been through one round
> of security review (see [Security review](#security-review)); nothing has been
> independently audited. The Nano sketch has been tested in a PC simulator
> (see [How the Nano code was tested](#how-the-nano-code-was-tested)) but not yet
> on physical hardware. Do not protect real people's data with it as-is.

---

## Contents

- [Repository layout](#repository-layout)
- [Quick start](#quick-start)
- [Part 1: The key (attribute-bound keys)](#part-1-the-key-attribute-bound-keys)
- [Part 2: The key on an Arduino Nano](#part-2-the-key-on-an-arduino-nano)
- [Part 3: One account per person](#part-3-one-account-per-person)
  - [3a. Blind signatures (`unique_account.py`)](#3a-blind-signatures-unique_accountpy)
  - [3b. Tap-your-key sign-up (central server, website, phone app)](#3b-tap-your-key-sign-up)
  - [3c. Blindgram: sign-up and age checks on a social site](#3c-blindgram-sign-up-and-age-checks-on-a-social-site)
  - [Comparing the two](#comparing-the-two)
- [Part 4: Name checks on a video call](#part-4-name-checks-on-a-video-call)
- [The desktop app](#the-desktop-app)
- [Security review](#security-review)
- [Threat model](#threat-model)
- [Known limitations](#known-limitations)
- [Before you use this for real](#before-you-use-this-for-real)
- [Design history](#design-history)

---

## Repository layout

| File | Role |
|---|---|
| `kagi.py` | The key format: authority, issuing, verifying, CLI and self-test |
| `unique_account.py` | Blind-signature one-account-per-person protocol and self-test |
| `kagi_nano/kagi_nano.ino` | The whole Nano firmware in one file, no libraries (copy-paste into the Arduino IDE) |
| `nano_provision.py` | The authority for Nano keys: computes commitments and writes them into the sketch |
| `nano_client.py` | PC-side verifier: sends queries to the Nano and checks its proofs |
| `central_server.py` | Unique sign-up server (Flask): challenges, proof checking, per-site marks |
| `website.py` | Demo website (Flask) that uses the central server for sign-up |
| `phone_app.py` | The user's app: enter the code, tap the key, relay the answer |
| `desktop_app.py` | The user's app with a Qt UI: Zoom name checks (8-digit codes) and website sign-up / age checks (12-digit codes) |
| `serial_bridge.py` | Run with Windows Python under WSL: forwards the Nano's COM port to `desktop_app.py` over localhost |
| `challenge_site.py` | Zoom name-check site (Flask): the host creates a challenge and watches for the result |
| `blindgram.py` | Instagram-style demo site: one account per person at sign-up, Reels gated behind an 18+ check |

Generated secrets, all in `.gitignore` (never commit them):

| File | Made by | Contains |
|---|---|---|
| `authority.key`, `authority.pub`, `user.key.json` | `kagi.py` | Ed25519 authority key pair, an issued key |
| `authority_person.key` | `nano_provision.py` | Secret used to derive opaque person ids. **Keep it**: losing it gives everyone new person ids. |
| `nano_registry.json` | `nano_provision.py` | Per key: device secret, opaque person id, expiry |
| `central_data/` | `central_server.py` | Pepper, registered sites (hashed API keys), marks |
| `website_credentials.json`, `blindgram_credentials.json` | `central_server.py add-site` | A site's API key |
| `blindgram_data/` | `blindgram.py` | Accounts (username, password hash, 18+ flag), posts, uploads, session key |
| `blindgram_media/` | you (optional) | `.mp4` files for Reels |

Note that the KEY DATA block inside `kagi_nano.ino` also holds that key's
device secret. Treat a provisioned sketch as secret too.

---

## Quick start

```bash
pip install -r requirements.txt       # cryptography, pyserial, flask, PyQt5
```

Default ports: central server **8000**, `website.py` **8001**,
`challenge_site.py` **8002**, `blindgram.py` **8003**, and `desktop_app.py`
listens on **8765** for `serial_bridge.py` under WSL. Every server takes `--port`.

### Python only (no hardware)

```bash
python3 kagi.py demo          # self-test for the key format (fast)
python3 unique_account.py         # self-test for the blind-signature protocol (~15 s)
```

Both demos `assert` every claim they print and end with `all checks passed`.

### The key on a Nano

```bash
# 1. Provision (the authority's job). Writes the commitments into the sketch.
python3 nano_provision.py --first-name Nathan --last-name Donagi \
        --dob 2005-09-21 --ssn 123-45-6789 --pin 4821

# 2. Open kagi_nano/kagi_nano.ino in the Arduino IDE, board "Arduino Nano", upload.

# 3. Ask it questions from the PC.
python3 nano_client.py info
python3 nano_client.py demo                                       # 23 test queries
python3 nano_client.py verify first_name=Nathan last_name=Donagi over=21
python3 nano_client.py shell                                      # interactive
```

`--port` picks the serial port (`/dev/ttyUSB0`, `/dev/ttyACM0`, `COM5`, ...);
otherwise the first Arduino-looking port is used. On WSL, either run the Python
side with Windows Python, or attach the board to WSL with `usbipd`. For
`desktop_app.py` there is a third option, `serial_bridge.py` (see
[The desktop app](#the-desktop-app)).

### Tap-your-key sign-up (three terminals, Nano plugged in)

```bash
python3 central_server.py add-site shop.example "Example Shop"   # once
python3 central_server.py serve                                  # http://localhost:8000
python3 website.py                                               # http://localhost:8001 → Sign up
python3 phone_app.py                                             # type the code, tap the key
```

Sign up once and the site says *Welcome*. Try again with the same key (or a
re-issued key for the same person) and it says *You already have an account here*.
`desktop_app.py` can be used in place of `phone_app.py`.

### Blindgram (sign-up and 18+ Reels)

```bash
python3 central_server.py add-site blindgram Blindgram --out blindgram_credentials.json   # once
python3 central_server.py serve        # http://localhost:8000
python3 blindgram.py                   # http://localhost:8003
python3 desktop_app.py                 # add --simulate to rehearse without the Nano
```

### Zoom name check

```bash
python3 challenge_site.py              # http://localhost:8002 → Create challenge
python3 desktop_app.py                 # the other person types the 8-digit code
```

Under WSL, also run `py serial_bridge.py` with **Windows** Python so the desktop
app can reach the Nano.

---

## Part 1: The key (attribute-bound keys)

### The problem

We want a central authority to issue keys tied to specific information such that:

- **Unforgeable**: nobody else can mint a key that claims "this is Nathan Donagi".
- **Hiding**: holding a key leaks *no* information about what it contains. If
  you don't already know the answer to a query, the only way to extract it is to
  try every possibility.
- **Queryable**: given a key and a query such as `name=Nathan Donagi`, a
  verifier can tell whether the query is correct, and on success hand out a code.

### How it works

**Commitments.** For each fact the authority picks a fresh random 32-byte salt
and stores a *commitment*: the scrypt hash of the fact with that salt. scrypt is
memory-hard (~64 MiB, ~100 ms per attempt), so each brute-force guess is
expensive. The key contains only salts and hashes, never the facts.

**Signature.** The authority signs the whole bundle (key id, expiry, every salt
and commitment) with an Ed25519 private key. Verifiers need only the *public*
key. Nobody can add, swap or edit a commitment without the signature failing.

**Verification.** A verifier checks the signature, hashes the query with the
stored salt, and compares in constant time. It never sees the facts unless the
person supplies them in the query.

### The hash levels

Later commitments *include* earlier facts, so brute force gets much harder:

```
Level 1   full_name = first + last, hashed TOGETHER   (never queryable separately)
          age                                          (chained onto the name)

Level 2   ssn                                          (covers ALL of level 1 + a 4-digit PIN)
```

| Field | What the commitment covers | What a query must supply |
|---|---|---|
| `full_name` | `["L1","full_name", [first, last]]` | `first_name` **and** `last_name` |
| `age` | `["L1","age", name, age]` | name **and** age |
| `ssn` | `["L2","ssn", name, age, pin, ssn]` | first, last, age, **PIN**, ssn (all of them) |

To brute-force an SSN from a stolen key an attacker must search
*name × age × PIN × SSN* jointly (the PIN alone is a 10⁴ factor and the SSN about
10⁹), each candidate costing one scrypt. Cracking level 1 first doesn't help:
level 2 still needs the PIN and SSN, and the costs multiply.

Design decisions worth knowing:

- **First and last name are one field**, so the two halves can't be attacked separately.
- **Age is chained onto the name.** A standalone age commitment could be
  recovered in ~120 guesses; now age can't be tested without the name.
- **Field names are inside the hash**, so the key doesn't say what *kind* of
  fact a commitment holds.

### Age thresholds ("over 18", "over 21")

Prove someone is at least 18 or 21 without revealing their age:
`first_name=Nathan last_name=Donagi over=21`.

For each threshold `T` in `{18, 21}` the key stores either
`scrypt(["OVER", T, full_name], salt)` if age ≥ T, or **32 random bytes (a
decoy)** otherwise. Decoys look identical to real commitments, so the key
doesn't reveal *whether* a threshold is met. The signature covers the
thresholds, so nobody can add their own "over 21". Threshold queries can't be
mixed with other fields.

### Queries and session codes

| Query kind | Fields | Result scope |
|---|---|---|
| Level 1 | `first_name` + `last_name` (together), optionally `age` | `L1` |
| Age threshold | `first_name`, `last_name`, `over` (18 or 21) | `OVER18` / `OVER21` |
| Level 2 | `first_name`, `last_name`, `age`, `ssn`, `pin` (all required) | `L2` |

A success returns a short-lived (5 min) HMAC-signed session code,
`keyid.scope.expiry.nonce.mac`; `Verifier.check_code(code)` returns the proven
scope, so a service can demand `L2` for sensitive actions. A failure never says
which part was wrong. Queries are normalized (Unicode NFKC, case-folded,
whitespace collapsed; SSNs with or without dashes).

### Command line

```bash
python3 kagi.py init                                  # authority.key (PRIVATE) + authority.pub
python3 kagi.py issue --first-name Nathan --last-name Donagi \
        --age 21 --ssn 123-45-6789 --pin 4821             # -> user.key.json
python3 kagi.py verify first_name=Nathan last_name=Donagi                 # level 1
python3 kagi.py verify first_name=Nathan last_name=Donagi over=21         # threshold
python3 kagi.py verify first_name=Nathan last_name=Donagi age=21 \
                           ssn=123-45-6789 pin=4821                           # level 2
```

Prints `AUTHENTICATED <code>` or `DENIED` (exit code 1). Each CLI run has a
fresh session secret, so use the `Verifier` class if you need `check_code()`
across requests.

### From Python

```python
from kagi import Authority, Verifier

authority = Authority.generate()
key = authority.issue(
    {"first_name": "Nathan", "last_name": "Donagi", "age": 21, "ssn": "123-45-6789"},
    pin="4821",
)
verifier = Verifier(authority.public_key_bytes())     # verifiers only need the PUBLIC key
code = verifier.authenticate(key, {"first_name": "Nathan", "last_name": "Donagi", "over": 21})
assert verifier.check_code(code) == "OVER21"
```

### Guarantees and caveats

- Anyone holding the key file can brute-force low-entropy facts offline;
  scrypt and chaining only make it expensive. Level 2 is the strong part.
  (Part 2 fixes this by never letting the key file out of the hardware.)
- Holding the key *and* knowing the answers is enough to authenticate. The key
  proves "the authority attested this", not "you are that person".
- Age and the over-18/21 flags are fixed at issuance, so the key goes stale.
  (The Nano version uses date of birth.)
- The key's `exp` field reveals roughly when it was issued.

---

## Part 2: The key on an Arduino Nano

### Why

With the Python version, the key, the verifier and the person asking all live on
one laptop, so a demo shows nothing: whoever has the file has everything. On the
Nano the key is a **separate physical device**. The PC can only ask it
questions over USB serial and get yes/no back. There is no command that reads
the commitments out, so the offline brute-force weakness from Part 1 turns
into online guessing through a rate-limited serial port.

### What is on the chip

`nano_provision.py` plays the authority. It normalizes the facts, computes the
commitments, and writes them into the `KEY DATA` block of
`kagi_nano/kagi_nano.ino`:

| Stored in flash | Purpose |
|---|---|
| Key id (12 bytes) | Identifies the key to verifiers and the central server |
| Device secret (32 bytes) | Signs the Nano's answers (HMAC) |
| 5 commitments, each 32-byte salt + 32-byte hash | `full_name`, `dob`, `ssn`, `over18`, `over21` |

It also adds the key to `nano_registry.json` (device secret, expiry, and an
opaque person id, used in Part 3b). The facts themselves are written nowhere.

Commitments use the same JSON layouts as Part 1, with date of birth in place of age:

```
C = PBKDF2-HMAC-SHA256( SHA256(json(parts)), salt, 200 iterations )

full_name  ["L1","full_name",[first,last]]
dob        ["L1","dob",[first,last],"YYYY-MM-DD"]             chained on the name
ssn        ["L2","ssn",[first,last],dob,pin,ssn]               covers everything
over T     ["OVER",T,[first,last]]   or 64 random bytes if under T (decoy)
```

Each query is checked against its single most specific commitment (for
example, a level-2 query checks only `ssn`, which already covers every level-1
value). This gives the same answer as checking each level, for a third of the work.

### Serial protocol (115200 baud, one command per line)

| Command | Reply |
|---|---|
| `PING` | `PONG kagi-nano v1` |
| `INFO` | `INFO id=<hex> iters=<n> fails=<n> tap=<0\|1>` |
| `AUTH <challenge> k=v;k=v;...` | `WORKING`, then `AUTHENTICATED <scope> <proof>`, `DENIED`, or `LOCKED <seconds>` |
| `SIGN <nonce> <site_id>` | (`TAP` while waiting for the button) then `SIGNED <proof>` or `TIMEOUT` |
| anything malformed | `ERR <reason>` |

- Query keys: `first_name`, `last_name`, `dob` (`YYYY-MM-DD` or `MM/DD/YYYY`),
  `ssn`, `pin`, `over`. The query kinds and rules are the same as in Part 1.
- `AUTH` proof = `HMAC(device_secret, "kagi-nano-v1|<key id>|<scope>|<challenge>")`.
  The PC sends a fresh random challenge each time, so a recorded answer can't be
  replayed and nothing without the device secret can fake one.
- `SIGN` proof = `HMAC(device_secret, "kagi-nano-sign-v1|<key id>|<site_id>|<nonce>")`
  (used by Part 3b).
- It also works by hand from the Arduino Serial Monitor (Newline line ending):
  `AUTH - first_name=Nathan;last_name=Donagi;over=21` (`-` means no challenge).

`nano_client.py` wraps this: it generates the challenge, checks the proof against
`nano_registry.json`, and checks the key's expiry (the Nano has no clock).

### Lockout

Failed guesses are counted in EEPROM, so unplugging the board doesn't reset
the counter. The first 5 are instant; after that each attempt must wait 15 s,
30 s, 60 s, ... (up to ~64 min) since the previous one or since power-up. The
attempt is counted *before* the check runs, so cutting power mid-check doesn't
dodge it. A correct level-2 query (which needs the PIN) resets the counter;
other correct answers don't count as failures. Malformed queries (first name
alone, unknown fields) are refused without testing anything, so they don't count.
Provisioning a new key resets the counter.

### Tap button (optional)

Wire a push button between **D2** and **GND** and set `#define USE_TAP_BUTTON 1`
at the top of the sketch. `SIGN` then blinks the built-in LED and waits up to
30 s for a press. With `0` (the default) `SIGN` answers immediately, and the
phone app asks you to press Enter instead.

### Differences from `kagi.py`

- **PBKDF2 (200 iterations) instead of scrypt.** scrypt needs 64 MiB of RAM; the
  Nano has 2 KiB. This is cheap to brute-force *if* someone gets the
  commitments, which is why the Nano has no way to read them out and has the
  lockout. Each query should take about 1–2 s on a 16 MHz Nano (estimated,
  not measured).
- **No Ed25519 signature.** Trust comes from the device secret, which the
  authority shares with verifiers through `nano_registry.json`. This is
  symmetric: anyone holding the registry could also impersonate the key.
- **Date of birth instead of age.** Over-18/21 flags are still fixed at issuance.
- **Names are ASCII only** (no `"` or `\`), so the on-chip JSON needs no escaping.

### How the Nano code was tested

There was no AVR toolchain, so the exact `.ino` file was compiled on a PC with
small stand-ins for the Arduino APIs (`Serial` on stdin/stdout, EEPROM in a
file, `millis`), connected to a virtual serial port, and driven by the real
`nano_client.py` and `phone_app.py`. Verified this way:

- all 23 `nano_client.py demo` queries give the expected answer, which also
  confirms the on-chip SHA-256/PBKDF2 matches Python's `hashlib` byte for byte;
- the lockout starts after 5 failures and survives a "reboot";
- a proof checked with the wrong device secret is rejected;
- the tap-button path (`TAP` → `SIGNED`) and input validation.

Not yet verified on the board: real timing, RAM headroom (estimated at under
1.5 KB of the 2 KB), and the button wiring.

---

## Part 3: One account per person

A website wants **one account per real person**, but the person must not hand the
website any personal data. There are two implementations, with different
trade-offs.

### 3a. Blind signatures (`unique_account.py`)

The strongest version: once the account exists, **nobody** (not the website,
not the central server, not a hacker, not a court order) can tie it back to the
person, even knowing everything the system knows.

**Why not "convert the code to a user, then delete the mapping"?** That is only
as strong as the server's promise to delete. Instead we use **Chaum RSA blind
signatures**: the server marks the person *at issuance* but never sees the
code's actual value. There is nothing to delete and nothing to recover.

```
                      Central server                          Website
  Setup:         gives each site its own RSA key pair ─────────► public key (n, e)

  User                                   Server
  nonce  = random 32 bytes
  h      = FDH(site_id || nonce)
  b      = h · r^e mod n      (r = secret random blinding factor)
  ── key + level-2 credentials + site_id + b ──►
                                         verify key + credentials (kagi L2)
                                         person already has a mark for this site? → refuse
                                         store opaque mark for (person, site)
                                         s' = b^d mod n
  ◄────────────────── s' ────────────────
  s = s' · r⁻¹ mod n ;  code = (nonce, s)

  User ── code ──────────────────────────────────────────────────►  Website
                                                  check s^e == FDH(site_id||nonce), nonce unused
```

Why each property holds:

- **One account per person per site.** The server refuses a second issuance for
  the same `(person, site)`. A code verifies only under its own site's key, and
  each site remembers used nonces. The person is identified by SSN, not key id,
  so a fresh key doesn't reset the quota.
- **The website learns nothing.** It sees a random nonce and a signature.
- **Unlinkable, unconditionally.** The server only ever sees `b` (uniformly
  random because of `r`) and `s'`. For *any* valid code there is a blinding
  factor consistent with the server's transcript; the demo checks all 2×2
  pairings. This holds even if the server's keys and logs leak.
- **Sites can't collude.** Separate keys and nonces per site.
- **No covert channel.** RSA-FDH is deterministic, so a compelled server can't
  tag its responses.

The server stores exactly one thing per person per site:
`mark = scrypt(HMAC(pepper, "mark|" + site_id + "|" + ssn))`. The pepper lives
outside the database, marks are per-site, and scrypt (~128 MiB per guess) keeps
brute force expensive even if the pepper leaks. No codes, blinded values, SSNs,
names, site names, or timestamps are stored.

```python
import secrets
from kagi import Authority
from unique_account import Issuer, Website, request_code

authority = Authority.generate()
issuer    = Issuer(authority.public_key_bytes(), pepper=secrets.token_bytes(32))  # persist the pepper!
site_pub  = issuer.register_site("shop.example")
site      = Website("shop.example", site_pub)

facts = {"first_name": "Alice", "last_name": "Nguyen", "age": 25, "ssn": "111-22-3333"}
key   = authority.issue(facts, pin="1234")
code  = request_code(issuer, key, {**facts, "age": "25", "pin": "1234"}, "shop.example", site_pub)
account_id = site.create_account(code)
```

A second `request_code` for the same person and site raises `RefusedError`, as
does `create_account` on a reused, forged, or wrong-site code.

### 3b. Tap-your-key sign-up

A complete, clickable flow using the Nano as a hardware key: a website with a
**Sign up** button, a central server, and a phone app. The user never types any
personal information; they type a code and tap their key.

```
 Website ──POST /api/challenges──────────────────────► Central server   (site API key)
         ◄──────────────── 12-digit code ────────────
 shows "1234 5678 9012" to the user

 Phone   ──GET /api/challenges/<code>────────────────►                  (user typed the code)
         ◄──── type: unique_signup, site, nonce ─────
 shows "Example Shop wants to check you're a unique person"

 Phone   ──SIGN <nonce> <site_id>──► Nano key                           (user taps the key)
         ◄──── HMAC(device_secret, "kagi-nano-sign-v1|key id|site|nonce")

 Phone   ──POST /api/challenges/<code>/response {key_id, proof}──►
                                   look up key id in the registry, check the proof and expiry
                                   key id → opaque person id → per-site mark
                                   mark already stored? "existing" : store it, "new"

 Website ──GET /api/challenges/<code>/result─────────► "new" or "existing"
                                   challenge deleted; website creates the account (or doesn't)
```

**Person ids.** Uniqueness must be per *person*, not per key, or someone could
just get a second key. When provisioning, the authority computes
`person = HMAC(authority_person.key, "person|" + ssn)` and stores it in the
registry next to the key. A re-issued key for the same SSN gets the same person
id, while the central server never sees the SSN. The server's mark is then
`scrypt(HMAC(pepper, "mark|" + site_id + "|" + person))`, per site as in 3a.

**Central server HTTP API** (`central_server.py serve`):

| Endpoint | Caller | Auth | Returns |
|---|---|---|---|
| `POST /api/challenges` | website | `Authorization: Bearer <site API key>` | `{code, expires_in}` |
| `GET /api/challenges/<code>` | phone | none | `{type, site_id, site_name, nonce, expires_in}` (+ `over` for age checks) |
| `POST /api/challenges/<code>/response` | phone | the key's proof: `{key_id, proof}`, or `{declined: true}` for an age check the key said no to | `{status: "complete", result}` or `{error}` |
| `GET /api/challenges/<code>/result` | website | site API key | `waiting`, `complete` + `new`/`existing` (sign-up) or `verified` (age check), `failed`, or `expired` |

The `POST /api/challenges` body is optional: `{}` or `{"type": "unique_signup"}`
for a sign-up, `{"type": "age_check", "over": 18}` (or 21) for an age check
(see [3c](#3c-blindgram-sign-up-and-age-checks-on-a-social-site)).

Rules: codes are 12 random digits (spaces/dashes accepted) and expire after
5 minutes; each can be answered once; 3 bad proofs burn it; a site can only
read results for its own codes; the challenge is deleted as soon as the website
collects the result. The server keeps no request log. Codes, times and IPs are
exactly what would let someone line up a session with a person later. Keys
added to `nano_registry.json` work without restarting the server.

**The website** (`website.py`) never talks to the key or learns anything about
the user. The browser gets a random token for its session. The site maps it to
the code only until the result arrives, then creates an account with a random
id or shows "You already have an account here".

**The phone app** (`phone_app.py`) runs on the computer the Nano is plugged into
(a phone browser can't reach a USB serial device). It shows which site is
asking, waits for the tap, and relays the proof. It never has the device secret
or any personal data. It is a small command-line tool for sign-ups only;
[`desktop_app.py`](#the-desktop-app) does the same with a UI, and also handles
age checks and Zoom name checks.

**What each party learns:**

| Party | Learns |
|---|---|
| Website | `new` or `existing`. Nothing else: no name, no key id |
| Phone app | Which site is asking, and a nonce |
| Central server | That a registered person answered a code for a site. Stores only the per-site mark afterwards |
| Nano | The site id and nonce it signs |

**Tested end to end** (with simulated keys): first sign-up → `new` and account
created; the same person with a re-issued key → `existing`; a different person
→ `new`; the same person on a second site → `new`; a forged proof, a bad site API
key, and a reused or unknown code are all rejected.

### 3c. Blindgram: sign-up and age checks on a social site

`blindgram.py` is a photo-sharing site in the style of Instagram (feed, likes,
comments, posting, profiles, Reels) that uses the central server twice:

- **Sign-up** is 3b's unique sign-up. The user picks a username and password,
  the site shows a 12-digit code, and the user types it into `desktop_app.py`
  and plugs in the key. Blindgram gets `new` (account created) or `existing`
  ("You already have an account"). Later log-ins are a plain username and password.
- **Reels are 18+.** The site asks the central server for an `age_check`
  challenge (`{"type": "age_check", "over": 18}`). The desktop app asks the user
  for their name, which goes only to the key, and sends
  `AUTH <server nonce> first_name=..;last_name=..;over=18`. It relays the key's
  proof, `HMAC(device_secret, "kagi-nano-v1|key id|OVER18|nonce")`, and
  the **central server checks it**, so a modified app can't claim a yes it
  didn't get. Blindgram gets `verified` or `failed` and stores a single
  "18+ verified" flag on the account.

```bash
python3 central_server.py add-site blindgram Blindgram --out blindgram_credentials.json   # once
python3 central_server.py serve        # http://localhost:8000
python3 blindgram.py                   # http://localhost:8003
python3 desktop_app.py                 # (+ serial_bridge.py on Windows under WSL)
python3 desktop_app.py --simulate      # rehearse without the Nano: a virtual key with real proofs
```

Resetting between demos: `python3 blindgram.py reset` and
`python3 central_server.py forget-site blindgram`. The second works while the
server is running, and lets the same key sign up again. Put `.mp4` files in
`blindgram_media/reels/` to show real videos as Reels; otherwise they are
animated placeholders.

What Blindgram learns: that the account belongs to a person with no other
account, and (if they checked) that they're 18 or over. No name, birthday or key id.

**Limitation:** the age check proves that *someone's* key says 18+, not that it
is the same key that created the account. An older friend could answer the
check for you. Binding the two would need a per-site pseudonym for the key,
which the central server would then have to remember.

**Tested end to end** (simulated keys, real HMAC proofs): sign-up → created;
the same person with a re-issued key → existing; username clashes refused;
Reels gated until the check passes; a key that says no, a forged proof, and a
sign-up proof replayed as an age proof are all rejected; `forget-site` lets
the person sign up again without restarting the server.

### Comparing the two

| | 3a: blind signatures | 3b: tap-your-key |
|---|---|---|
| User enters | name, age, SSN, PIN (to the issuer) | a 12-digit code, then taps the key |
| Personal data sent anywhere | yes, to the issuer (TLS required) | no; the key answers with a MAC |
| Website learns | nothing (a random nonce and signature) | `new` / `existing` |
| Server can link account ↔ person | **never**, even if fully compromised | only while answering, if it were compromised then and logged it, *and* the website logged codes |
| Code can be stolen | code is a bearer token (can be handed on) | someone who sees the code on screen could answer it first with their own key |
| Hardware | none | Nano key |

3b trades 3a's mathematical unlinkability for a much simpler user experience and
no personal data in transit. Combining the two, with the Nano authorizing a
blind-signature issuance, would give both; see [Before you use this for real](#before-you-use-this-for-real).

---

## Part 4: Name checks on a video call

On a Zoom call you can't tell whether "Nathan Donagi" is really Nathan Donagi.
`challenge_site.py` lets the host ask the other person's key.

```
 Host      ──POST /api/challenges {first_name, last_name}──► challenge_site.py
           ◄──────────── 8-digit code ────────────────────
 pastes "1234 5678" into the Zoom chat

 Other person types the code into desktop_app.py
 App       ──GET /api/challenges/<code>──────────────────►  {first_name, last_name, status}
 App       ──AUTH <fresh random challenge> first_name=..;last_name=..──► Nano key
           ◄──── AUTHENTICATED L1 <proof> / DENIED / LOCKED
           checks the proof against nano_registry.json and the key's expiry
 App       ──POST /api/challenges/<code>/result {verified: true|false}──►

 Host's page (polling every second) turns green "Verified" or red "Not verified"
```

Codes are 8 random digits, valid for 15 minutes, and can be answered once. The
site keeps challenges in memory only. The name is typed by the host, not the
person being checked, and only ever reaches their key as a yes/no question.

**Limitation: this is a demo.** Unlike the central server, `challenge_site.py`
takes the app's word for the result; nothing checks the key's proof on the
server side, so a modified app could report `verified`. Fixing it means doing
what the age check already does: the site issues the nonce, and it (or the
central server) verifies the key's `AUTH` proof against the registry. Also,
nothing ties the answering key to the person on camera; someone could hand
their key and name to a friend.

---

## The desktop app

`desktop_app.py` is the user's side of every check, with a Qt window (it
stands in for a phone app). You type a code, plug in the key, and see the result:

| Code | From | What the app does |
|---|---|---|
| 8 digits | `challenge_site.py` | Asks the key whether the host's name matches (Part 4) |
| 12 digits, `unique_signup` | `central_server.py` | Has the key `SIGN` the server's nonce and relays it (3b) |
| 12 digits, `age_check` | `central_server.py` | Asks for your name (sent only to the key), relays the key's `OVER18` proof (3c) |

The app waits for the key to be plugged in, and waits again if it is pulled out
mid-check.

| Flag | Default | Purpose |
|---|---|---|
| `--server` | `http://localhost:8002` | `challenge_site.py` (8-digit codes) |
| `--central` | `http://localhost:8000` | `central_server.py` (12-digit codes) |
| `--port` | auto-detect | Open this serial port directly instead of using the bridge |
| `--bridge-port` | `8765` | Where to listen for `serial_bridge.py` under WSL |
| `--registry` | `nano_registry.json` | Key registry |
| `--simulate` | off | No Nano: a virtual key that says **yes to everything**, using the first registry key's device secret so its proofs are real |
| `--theme` | `auto` | `light` / `dark`; `auto` follows Windows' app setting under WSL |
| `--scale` | Windows' scaling under WSL | UI scale |
| `--debug` | off | Print the serial conversation |

**WSL.** WSL can't open Windows COM ports. Under WSL (and without `--port`) the
app listens on `localhost:8765`, and `serial_bridge.py`, run with Windows
Python, waits for the Nano to be plugged in, connects to the app and copies
bytes both ways. Unplugging the Nano closes the connection, which is how the app
notices. The bridge understands nothing: the app still sends the challenge and
checks the proof.

```powershell
py -m pip install pyserial
py serial_bridge.py                 # the key on COM7 (the default)
py serial_bridge.py --port auto     # find it by USB description instead
```

The bridge opens the port without asserting DTR, so the Nano isn't reset
(and doesn't spend another 1–2 s in its bootloader). Under WSL the app also reads
Windows' display scaling, light/dark setting and fonts, since WSLg passes none
of them through.

---

## Security review

After the first version we reviewed `kagi.py` and `unique_account.py`
assuming an attacker can read the database, or that the operator is served a
subpoena. Findings and fixes:

| # | Problem | Impact | Fix |
|---|---|---|---|
| 1 | Person ID was `HMAC(secret, ssn)` with the secret next to the database | A dump plus the secret recovers every SSN in minutes (~10⁹ SSNs, HMAC is fast) | Mark is now `scrypt(HMAC(pepper, site‖ssn))`, pepper stored separately |
| 2 | Same person ID appeared on every site | A dump reveals which sites each person uses | Marks are per-site |
| 3 | `age` committed standalone | ~120 guesses recovers age from a key | Age chained onto the name |
| 4 | Issuer secret random per process, defaulted silently | A restart would reset the one-per-person rule | Pepper is now a required, persistent argument |
| 5 | No limit on failed logins | Stolen key + leaked name/SSN → online PIN guessing | 10 failures per key per hour, tracked under a hash of the key id; junk keys rejected before any scrypt work |
| 6 | Check-then-mark not atomic | Concurrent requests could both get a code | Single lock (use a unique-constraint insert in a real DB) |
| 7 | RSA private op ran on client-chosen input | Remote timing attack surface | Server-side blinding of the signing step |
| 8 | Client verified with `assert` | `python -O` strips it | Explicit exception |

The Nano, sign-up and age-check flows were built with those lessons applied
(per-site peppered scrypt marks, persistent pepper, atomic check-and-set,
online-guess limits, no request logs) but have not had their own review round.
The Zoom name check (Part 4) and the desktop app have not been reviewed either.

---

## Threat model

**Someone reads the central server's database** (3a or 3b): opaque per-site
marks only. No SSNs, names, codes, or key ids. Without the pepper they can't even
test a guess; with it, each guess costs a 128 MiB scrypt. In 3b they'd also need
`authority_person.key` to connect a guessed SSN to a person id.

**Someone reads the website's database:** random account ids (and in 3a, used
nonces). Nothing about any person.

**Both databases together:** in 3a, still nothing: the blind signature makes
them unjoinable. In 3b, also nothing, provided neither side logged the code;
the challenge record that tied them was deleted.

**The central server is compromised while running** (3b only): it could record
which person answered which code, and so, with the website's cooperation, which
account belongs to whom. 3a is immune to this.

**Someone steals `nano_registry.json`:** they have the device secrets, so they
can impersonate those keys to verifiers and to the sign-up server. Keep it in
the same trust zone as the server.

**Someone steals a Nano:** without the person's facts they can only guess
through the lockout. `SIGN` needs no facts, so they *can* use it for sign-ups
as that person (see limitations). If they dump the flash with a programmer
(possible unless the chip's lock bits are set), they get the device secret and
the commitments and can guess offline at PBKDF2 speed.

**The issuer's site signing keys are stolen** (3a): unlimited fake accounts on
those sites (a Sybil attack), but no deanonymization. Keep them in an HSM.

**Subpoena to the central server:** it can produce the marks and, given a
person and a site, answer "does this person have an account here?". That is
unavoidable if you enforce one account per person. It **cannot** say which
account is theirs (in 3b, as long as it wasn't logging at the time).

**Subpoena to the website:** nothing about any person.

---

## Known limitations

1. **Logs and timing.** If issuance/answering and sign-up happen close together
   or from the same IP, logs on both sides can be matched up. The code logs
   nothing, but deployments must keep it that way. Mitigations: random client
   delays, batched and shuffled signing, anonymizing networks.
2. **3b is not unlinkable against a live compromised server** (see threat model).
3. **`SIGN` has no PIN.** A tap alone authorizes a sign-up, so a stolen key can
   create accounts as its owner. Adding a PIN check before `SIGN` is a small change.
4. **Code interception in 3b.** Someone who sees the code on screen could answer
   it first with their own key; the site would then count them instead of you.
5. **Stolen key file + leaked personal data (Part 1).** The PIN is 4 digits;
   someone with the key file and the person's name, age and SSN can brute-force
   it offline. The Nano version addresses this by never releasing the key.
6. **The authority's own records.** If the authority keeps the names and SSNs it
   used to issue keys, a breach there exposes everything. It should keep only
   its secrets and delete the facts after issuing.
7. **Where the client gets each site's public key (3a).** It should come from
   the website, not the issuer; otherwise a malicious issuer could hand each
   user a different key and tell them apart.
8. **Transport.** 3a sends name, age and SSN to the issuer, and the 3b, 3c and
   Part 4 demos run over plain HTTP. TLS is mandatory for anything real.
9. **Codes are bearer tokens (3a).** They can be handed or sold. The system limits
   each real person to one account per site, not a person who cooperates in handing theirs on.
10. **Lost codes and failed sign-ups.** In 3a a lost code can't be safely
    reissued; in 3b a site that fails after being told `new` leaves a mark with
    no account. Recovery policy is up to the deployment.
11. **State.** Marks, sites and the pepper are persisted in `central_data/`, but
    in-flight challenges are in memory (in `challenge_site.py` too).
    `unique_account.py` keeps everything in memory.
12. **Stale facts.** Over-18/21 flags are fixed at issuance; keys expire after a
    year by default and must be re-issued.
13. **The Zoom name check trusts the app.** `challenge_site.py` accepts the
    app's `verified: true|false` without a proof (see [Part 4](#part-4-name-checks-on-a-video-call)).
14. **Age checks aren't bound to the account.** Any key that says 18+ can
    unlock Reels on any Blindgram account (see [3c](#3c-blindgram-sign-up-and-age-checks-on-a-social-site)).

---

## Before you use this for real

- Get an independent cryptographic review.
- Replace the hand-rolled RSA blinding with RFC 9474 (RSABSSA) from a vetted library.
- Keep the pepper, `authority_person.key`, device secrets and per-site private
  keys in an HSM/KMS; store marks with a unique constraint.
- Use a secure element for the key (e.g. ATECC608) instead of plain flash, or at
  least set the Nano's lock bits so the flash can't be read out.
- Replace the shared device secret with a per-device signing key (e.g. Ed25519 in
  a secure element) so verifiers don't hold secrets that could impersonate keys.
- Add a PIN to `SIGN`, and combine 3b with 3a (the key authorizes a blind-signature
  issuance) to get tap-to-sign-up *and* unconditional unlinkability.
- Add TLS, network rate limiting, and logging rules that exclude request bodies,
  IPs and timestamps for the challenge endpoints.
- Decide recovery policy for lost codes, lost keys and stale facts.
- Consider an anonymous-credential / nullifier design (ZK proofs) to avoid
  storing even per-site marks.

---

## Design history

1. **Plain hashed queries.** Store salted hashes; hash a query and compare.
   Problem: nothing stops someone from creating fake keys.
2. **Signed commitments.** The authority signs a bundle of salted scrypt
   commitments (Ed25519). Unforgeable, and reveals nothing except by guessing.
3. **Hash levels.** Level 2 (SSN) covers every level-1 value plus a 4-digit PIN,
   so brute-forcing the SSN means guessing everything at once.
4. **Combined name and age thresholds.** First and last name merged into one
   commitment; "over 18"/"over 21" via real-or-decoy commitments.
5. **One account per person, unlinkably.** "Decode the code, then destroy the
   mapping" was replaced by blind signatures so unlinkability is mathematical.
6. **Security review** against database compromise and subpoena; fixes
   [above](#security-review).
7. **The key in hardware.** Demoing on one laptop showed nothing, so the key
   moved to an Arduino Nano: a single library-free sketch, PBKDF2 instead of
   scrypt to fit 2 KiB of RAM, date of birth instead of age, HMAC proofs over PC
   challenges, and an EEPROM-backed lockout. The commitments never leave the chip.
8. **Tap-your-key sign-up.** A realistic end-to-end flow: the website shows a
   12-digit code, the user enters it in the phone app and taps the key, and the
   central server tells the website `new` or `existing`. Uniqueness is per
   person via authority-derived opaque person ids, so re-issued keys don't reset
   it. This is simpler to use than 3a, and deliberately documented as weaker on
   unlinkability.
9. **Age checks and Blindgram.** The central server gained `age_check`
   challenges whose `AUTH` proofs it verifies itself, and Blindgram, an
   Instagram-style site, uses both sign-up and 18+ checks.
10. **Desktop app and Zoom name checks.** `desktop_app.py` replaced the
    command-line phone app as the demo client, with a UI, a `--simulate` mode
    for rehearsing, and `serial_bridge.py` so it works under WSL.
    `challenge_site.py` added a name check for video calls.
