# blindkey

Two prototype privacy protocols, implemented as single-file Python scripts:

1. **`blindkey.py`** — *attribute-bound keys.* A central authority issues a key
   that is cryptographically tied to facts about a person (name, age, SSN, ...).
   The key can't be forged and reveals **nothing** about those facts. The only
   way to get a fact out of it is to guess it, and the key will say yes or no.
2. **`unique_account.py`** — *one account per person per website, unlinkably.*
   A website can guarantee that each real person creates at most one account,
   without ever learning who they are, and without the central server (or a
   hacker, or a subpoena) being able to connect an account back to a person.

> **Status: research prototype.** Written for a hackathon (HackGT 26). The design
> has been through one round of security review (see [Security review](#security-review))
> but the code has **not** been independently audited. Do not protect real
> people's data with it as-is. See [Before you use this for real](#before-you-use-this-for-real).

---

## Contents

- [Quick start](#quick-start)
- [Part 1: blindkey (attribute-bound keys)](#part-1-blindkey-attribute-bound-keys)
- [Part 2: unique_account (one account per person)](#part-2-unique_account-one-account-per-person)
- [Security review](#security-review)
- [Threat model: database breach and subpoena](#threat-model-database-breach-and-subpoena)
- [Known limitations](#known-limitations)
- [Before you use this for real](#before-you-use-this-for-real)
- [Design history](#design-history)

---

## Quick start

Requires Python 3.9+ and the `cryptography` package.

```bash
pip install -r requirements.txt

python3 blindkey.py demo          # self-test for the key format (fast)
python3 unique_account.py         # self-test for the one-account protocol (~15 s,
                                  # most of it is generating RSA keys and scrypt)
```

Both demos are self-checking: they `assert` every claim they print and end with
`all checks passed`.

### Command-line use of `blindkey.py`

```bash
# 1. The authority creates its signing key pair (do this once).
python3 blindkey.py init
#    -> authority.key  (PRIVATE, mode 600: never share)
#    -> authority.pub  (public: give to every verifier)

# 2. The authority issues a key bound to one person's facts.
python3 blindkey.py issue --first-name Nathan --last-name Donagi \
        --age 21 --ssn 123-45-6789 --pin 4821
#    -> user.key.json   (this is what the person holds)

# 3. Anyone with authority.pub can check queries against the key.
python3 blindkey.py verify first_name=Nathan last_name=Donagi                 # level 1
python3 blindkey.py verify first_name=Nathan last_name=Donagi over=21         # age threshold
python3 blindkey.py verify first_name=Nathan last_name=Donagi age=21 \
                           ssn=123-45-6789 pin=4821                           # level 2
```

On success it prints `AUTHENTICATED <code>`; otherwise `DENIED` and exit code 1.
(Each CLI run creates a fresh session secret, so the printed code can only be
checked by the same process. Use the `Verifier` class from Python if you need
`check_code()` across requests.)

`authority.key` and `user.key.json` are in `.gitignore`. Never commit them.

---

## Part 1: blindkey (attribute-bound keys)

### The problem

We want a central authority to issue keys tied to specific information such that:

- **Unforgeable** — nobody else can mint a key that claims "this is Nathan Donagi".
- **Hiding** — holding a key leaks *no* information about what it contains. If
  you don't already know the answer to a query, the only way to extract it is to
  try every possibility (brute force).
- **Queryable** — given a key and a query such as `name=Nathan Donagi`, a
  verifier can tell whether the query is correct, and on success hand out a code.

### How it works

**Commitments.** For each fact the authority picks a fresh random 32-byte salt
and stores a *commitment*: the scrypt hash of the fact with that salt. scrypt is
memory-hard (~64 MiB, ~100 ms per attempt), so each brute-force guess is
expensive. The key contains only salts and hashes, never the facts.

**Signature.** The authority signs the whole bundle (key id, expiry, every salt
and commitment) with an Ed25519 private key. Verifiers need only the *public*
key. Since only the authority can sign, nobody can add, swap or edit a
commitment without the signature failing.

**Verification.** A verifier checks the signature, hashes the query with the
stored salt, and compares in constant time. It never sees the facts unless the
person supplies them in the query.

### The hash levels (hashes build on each other)

To make brute force much harder, later commitments *include* earlier facts:

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

To brute-force an SSN from a stolen key an attacker must therefore search
*name × age × PIN × SSN* jointly (the PIN alone is a 10⁴ factor and the SSN about
10⁹), and each candidate costs one scrypt evaluation. Cracking the level-1
commitments first doesn't shortcut it, because level 2 still needs the PIN and
SSN, and the costs multiply rather than add.

Design decisions worth knowing:

- **First and last name are one field.** You cannot query either alone. This
  was added so an attacker can't attack the two halves independently.
- **Age is chained onto the name.** Originally age had its own standalone
  commitment; a key holder could recover it in ~120 guesses. Now age can't be
  tested without the name.
- **Field names are inside the hash.** The key doesn't say what *kind* of fact a
  commitment holds.

### Age-threshold queries ("over 18", "over 21")

You can prove someone is at least 18 or 21 without revealing their age:

```
first_name=Nathan  last_name=Donagi  over=21
```

The key stores, for each threshold `T` in `{18, 21}`:

- if age ≥ T: `scrypt(["OVER", T, full_name], salt)`
- otherwise: **32 random bytes (a decoy)**

Decoys are indistinguishable from real commitments, so the key doesn't reveal
*whether* a threshold is met, only someone who knows the name and runs the
query learns the yes/no. The verifier never sees the age. The signature covers
the thresholds, so nobody can add their own "over 21" commitment.
Threshold queries can't be mixed with other fields.

### Queries and session codes

| Query kind | Fields | Result scope |
|---|---|---|
| Level 1 | `first_name`+`last_name` (together), optionally `age` | `L1` |
| Age threshold | `first_name`, `last_name`, `over` (18 or 21) | `OVER18` / `OVER21` |
| Level 2 | `first_name`, `last_name`, `age`, `ssn`, `pin` (all required) | `L2` |

A successful query returns a short-lived (5 min) HMAC-signed session code of the
form `keyid.scope.expiry.nonce.mac`. `Verifier.check_code(code)` returns the
proven scope, so a service can demand `L2` for sensitive actions.
A failed query never says which part was wrong.

Queries are normalized (Unicode NFKC, case-folded, whitespace collapsed; SSNs
accept dashes or none), so `NAME = nathan   donagi` matches `Nathan Donagi`.

### Using it from Python

```python
from blindkey import Authority, Verifier

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

- Low-entropy facts can still be brute-forced offline by anyone holding the key.
  scrypt and chaining only make it expensive. The strong protection is level 2.
- Holding the key *and* knowing the answers is enough to authenticate. The key
  proves "the authority attested this", not "you are that person".
- Age (and the over-18/21 flags) is fixed at issuance, so a key goes stale. Use
  date of birth plus re-issuance if that matters.
- The key's `exp` field reveals roughly when it was issued.

---

## Part 2: unique_account (one account per person)

### The problem

A website wants **one account per real person**, but:

- the person must not hand the website any personal data;
- once the account exists, **nobody** — not the website, not the central server,
  not a hacker, not a court order — should be able to tie the account back to
  the person, even knowing everything the system knows.

### Why not "convert the code to a user, then delete the mapping"?

The obvious design is: the user gets a code, the site forwards it to the central
server, the server looks up which user it belongs to, marks them as "has
account", then destroys the code-to-user mapping. That is only as strong as the
server's promise to delete, and the requirement is that it holds even if the
server is hacked or subpoenaed later.

Instead we use **blind signatures** (Chaum RSA blinding): the server marks the
person *at issuance* but never sees the code's actual value. There is nothing
to delete and nothing to recover, so the unlinkability is mathematical, not
procedural.

### The protocol

```
                      Central server                          Website
                     (Issuer, knows people)             (knows nothing about people)
  Setup:         gives each site its own RSA key pair ─────────► public key (n, e)

  User                                   Server
  ────                                   ──────
  nonce  = random 32 bytes
  h      = FDH(site_id || nonce)
  b      = h · r^e mod n      (r = secret random blinding factor)
  ── key + level-2 credentials + site_id + b ──►
                                         verify key + credentials (blindkey L2)
                                         has this person a mark for this site? → refuse
                                         store opaque mark for (person, site)
                                         s' = b^d mod n
  ◄────────────────── s' ────────────────
  s = s' · r⁻¹ mod n
  code = (nonce, s)

  User ── code ──────────────────────────────────────────────────►  Website
                                                            check s^e == FDH(site_id||nonce)
                                                            check nonce unused → create account
```

### Why each property holds

- **One account per person per site.** The server refuses a second issuance for
  the same `(person, site)`. A code only verifies under *its own site's* key, so
  it can't be spent elsewhere. Each site remembers used nonces, so a code can't
  be replayed. The person is identified by their SSN (not their key id), so
  being issued a fresh key doesn't reset the quota.
- **Website learns nothing.** It sees a random nonce and a signature.
- **Unlinkable, unconditionally.** The server only ever sees `b` (uniformly
  random because of `r`) and its own signature `s'`. For *any* valid code there
  exists a blinding factor that makes the server's transcript consistent with
  it, so the transcript proves nothing about which code it produced. The demo
  checks this explicitly: for two users and two codes, every pairing is
  consistent. This holds even if the server's private keys and logs leak.
- **Sites can't collude.** Each site has its own key and each code its own
  nonce, so accounts on different sites can't be linked.
- **No covert channel.** RSA-FDH signatures are deterministic: for a given
  blinded value there is exactly one valid response, so a compelled server can't
  embed a tag in it.

### What the server stores

Exactly one thing per person per site: an opaque **mark**.

```
mark = scrypt( HMAC(pepper, "mark|" + site_id + "|" + ssn) )
```

- **Keyed with a `pepper`** stored *outside* the database (ideally an HSM). A
  database dump alone can't be tested against guessed SSNs at all.
- **Per-site**, so one person's marks on different sites are unrelated. A dump
  can't be joined into "which sites does this person use".
- **scrypt on top** (~128 MiB per guess), so even if the pepper leaks as well,
  brute-forcing the ~10⁹ SSN space stays expensive.

It does **not** store: codes, blinded values, nonces, signatures, SSNs, names,
site names, or timestamps.

### Using it from Python

```python
import secrets
from blindkey import Authority
from unique_account import Issuer, Website, request_code

authority = Authority.generate()
issuer    = Issuer(authority.public_key_bytes(), pepper=secrets.token_bytes(32))  # persist the pepper!

site_pub  = issuer.register_site("shop.example")      # site gets (n, e)
site      = Website("shop.example", site_pub)

facts = {"first_name": "Alice", "last_name": "Nguyen", "age": 25, "ssn": "111-22-3333"}
key   = authority.issue(facts, pin="1234")
query = {**facts, "age": "25", "pin": "1234"}

code = request_code(issuer, key, query, "shop.example", site_pub)   # user side
account_id = site.create_account(code)                              # website side
```

A second `request_code` for the same person and site raises `RefusedError`, as
does `create_account` on a reused, forged, or wrong-site code.

---

## Security review

After the first version we reviewed both files assuming an attacker can read the
database, or that the operator is served a subpoena. Findings and fixes:

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

## Threat model: database breach and subpoena

**Hacker reads the issuer database:** sees opaque marks only. No codes, no
blinded values, no SSNs, no site names. Without the pepper they cannot even test
a guessed SSN; with it, each guess is a 128 MiB scrypt.

**Hacker reads the website database:** sees random nonces and account ids.
Nothing about any person.

**Both databases together:** still nothing, because the blind signature means
the issuer's records and the site's records can't be joined.

**Issuer's site signing keys stolen:** the attacker can forge codes for those
sites and create unlimited fake accounts. That's a Sybil attack, not a
deanonymization; keep these keys in an HSM.

**Subpoena to the issuer:** it can produce the marks, and, given an SSN and a
site, answer "does this person have a code for this site?". That fact is
unavoidable if you enforce one account per person. It **cannot** say which
account on the site is theirs.

**Subpoena to the website:** nothing about any person.

## Known limitations

These are open; the first is the most important.

1. **Logs and timing.** If issuance and signup happen close together, or from
   the same IP, then an order to log a target's issuance requests plus one to
   the site for its signup logs lets someone match them. The code logs nothing,
   but deployments must keep it that way. Mitigations: the client waits a random
   delay before signing up; the server signs in fixed batches in shuffled order;
   users connect through an anonymizing network.
2. **Stolen key + leaked personal data.** The PIN is 4 digits. Someone with the
   key file and the person's leaked name, age, and SSN can brute-force the PIN
   offline. Encrypt keys at rest or bind them to a device.
3. **The authority's own records.** If the authority keeps the names and SSNs it
   used to issue keys, a breach there exposes everything. It should keep only its
   signing key and delete the data after issuing (it isn't needed to verify).
4. **Where the client gets each site's public key.** It should come from the
   website itself, not from the issuer; otherwise a malicious issuer could hand
   each user a different key and tell them apart.
5. **Transport.** The level-2 query sends name, age, and SSN to the issuer, so
   TLS is mandatory.
6. **Codes are bearer tokens.** They can be handed or sold. This limits each real
   person to one account per site, not someone who cooperates to hand theirs on.
7. **Lost codes.** If a user loses a code before using it, the server can't
   safely reissue it without weakening the one-per-person rule. Policy is yours.
8. **State is in memory only.** The issuer's marks, site keys, and failure table
   need real persistent storage.

## Before you use this for real

- Get an independent cryptographic review.
- Replace the hand-rolled RSA blinding with RFC 9474 (RSABSSA) from a vetted library.
- Keep the pepper and per-site private keys in an HSM/KMS; store marks with a
  unique constraint.
- Add TLS, rate limiting at the network layer, and audited logging rules that
  explicitly exclude request bodies, IPs and timestamps for the issuance endpoint.
- Decide the recovery policy for lost codes and stale keys (date of birth vs. age).
- Consider an **anonymous-credential / nullifier** design (ZK proofs) if you
  need to avoid storing even the per-site marks.

## Design history

How the design evolved, and why:

1. **Plain hashed queries.** Store salted hashes; hash a query and compare.
   Problem: nothing stops someone from creating fake keys.
2. **Signed commitments.** The authority signs a bundle of salted scrypt
   commitments (Ed25519). Unforgeable, and reveals nothing except by guessing.
3. **Hash levels.** Split into level-1 (name, age) and level-2 (SSN) where the
   level-2 hash covers every level-1 value plus a 4-digit PIN, so brute-forcing
   the SSN means guessing everything at once.
4. **Combined name and age thresholds.** First and last name merged into one
   commitment; added "over 18"/"over 21" queries using real-or-decoy commitments.
5. **One account per person.** First considered "server decodes the code, then
   destroys the mapping" but replaced it with blind signatures so
   unlinkability is unconditional rather than a promise.
6. **Security review** against database compromise and subpoena; fixes listed
   [above](#security-review).
