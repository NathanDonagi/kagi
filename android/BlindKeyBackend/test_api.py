"""Fast checks for BlindKey token transport + protocol semantics."""

from pathlib import Path
import json

from fastapi.testclient import TestClient

from blindkey import Verifier
from server import API_VERSION, create_app

ROOT = Path(__file__).resolve().parent
DEMO = ROOT / "demo"

pub = (DEMO / "authority.pub").read_bytes()
verifier = Verifier(pub)
key22 = json.loads((DEMO / "nathan22.key.json").read_text())
key19 = json.loads((DEMO / "nathan19.key.json").read_text())
registry = json.loads((DEMO / "tag_registry.json").read_text())
token22 = next(token for token, filename in registry.items() if filename == "nathan22.key.json")
token19 = next(token for token, filename in registry.items() if filename == "nathan19.key.json")
name = {"first_name": "Nathan", "last_name": "Donagi"}

# Nathan's underlying signed-credential protocol is unchanged.
assert verifier.authenticate(key22, {**name, "over": 21})
assert verifier.authenticate(key19, {**name, "over": 18})
assert not verifier.authenticate(key19, {**name, "over": 21})

app = create_app(DEMO / "authority.pub", DEMO / "tag_registry.json")
client = TestClient(app)

health = client.get("/health")
assert health.status_code == 200
h = health.json()
assert h["ok"] is True
assert h["service"] == "blindkey-verifier"
assert h["api_version"] == API_VERSION == 3
assert h["registered_tokens"] == 2
assert len(h["authority_fingerprint"]) == 12
assert health.headers["cache-control"] == "no-store"
assert health.headers["x-blindkey-api-version"] == str(API_VERSION)

# Token 22 resolves to the authentic age-22 credential and passes OVER21.
r = client.post(
    "/verify",
    json={"token": token22, "query": {**name, "over": 21}},
    headers={"X-Request-ID": "verify-123"},
)
assert r.status_code == 200 and r.json() == {"verified": True, "scope": "OVER21", "error": None}
assert r.headers["x-request-id"] == "verify-123"
assert r.headers["x-blindkey-authority-fingerprint"] == h["authority_fingerprint"]

# Token 19 resolves to an authentic credential, but OVER21 is false => RED.
r = client.post("/verify", json={"token": token19, "query": {**name, "over": 21}})
assert r.status_code == 200 and r.json() == {"verified": False, "scope": None, "error": None}

# Unknown/malformed handles are errors, never normal RED denials.
r = client.post("/verify", json={"token": "bk1:AAAAAAAAAAAAAAAA", "query": {**name, "over": 21}})
assert r.status_code == 200 and r.json()["error"] == "unknown_token"
r = client.post("/verify", json={"token": "not-a-token", "query": {**name, "over": 21}})
assert r.status_code == 422

# Query surface remains deliberately narrow.
invalid_queries = [
    {"over": 21},
    {**name, "over": 25},
    {**name, "over": 21, "age": 22},
    {"first_name": "Nathan"},
    {**name, "pin": "4821"},
    {**name, "age": 22, "ssn": "123-45-6789", "pin": "12"},
]
for query in invalid_queries:
    r = client.post("/verify", json={"token": token22, "query": query})
    assert r.status_code == 422, (query, r.text)

r = client.get("/health", headers={"X-Request-ID": "demo-123"})
assert r.headers.get("x-request-id") == "demo-123"

r = client.post(
    "/verify",
    content=b"x",
    headers={"Content-Length": str(17 * 1024), "X-Request-ID": "too-big"},
)
assert r.status_code == 413
assert r.headers["x-request-id"] == "too-big"
assert r.headers["x-blindkey-api-version"] == str(API_VERSION)

print("BlindKey token backend + API checks passed")
