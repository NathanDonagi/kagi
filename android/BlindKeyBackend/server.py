"""BlindKey verification API for the HackGT mobile demo.

The NFC tag carries only a small opaque `bk1:...` token. The backend resolves
that token to an Authority-signed BlindKey credential, runs Nathan's existing
commitment verifier, and returns only the requested verification result + scope.

Demo transport note: run this through the included USB `adb reverse` setup or on
a trusted local network. Production needs HTTPS, service authentication, abuse
controls, token rotation/revocation, and stronger possession binding.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from blindkey import Verifier

MAX_REQUEST_BYTES = 16 * 1024
API_VERSION = 3
_NAME_MAX = 128
_TOKEN_RE = re.compile(r"^bk1:[A-Za-z0-9_-]{8,64}$")


class QueryModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    first_name: Optional[str] = Field(default=None, max_length=_NAME_MAX)
    last_name: Optional[str] = Field(default=None, max_length=_NAME_MAX)
    age: Optional[int] = Field(default=None, ge=0, le=150)
    over: Optional[int] = None
    ssn: Optional[str] = Field(default=None, max_length=16)
    pin: Optional[str] = Field(default=None, max_length=4)

    @model_validator(mode="after")
    def validate_shape(self):
        present = self.model_fields_set

        if "over" in present:
            if present != {"first_name", "last_name", "over"}:
                raise ValueError("age-threshold queries require exactly first_name, last_name, and over")
            if self.over not in (18, 21):
                raise ValueError("over must be 18 or 21")
            self._validate_name()
            return self

        if "ssn" in present or "pin" in present:
            expected = {"first_name", "last_name", "age", "ssn", "pin"}
            if present != expected:
                raise ValueError("level-2 queries require first_name, last_name, age, ssn, and pin")
            self._validate_name()
            if self.ssn is None or not re.fullmatch(r"(?:\d{9}|\d{3}-\d{2}-\d{4})", self.ssn):
                raise ValueError("ssn must contain 9 digits")
            if self.pin is None or not re.fullmatch(r"\d{4}", self.pin):
                raise ValueError("pin must be exactly 4 digits")
            return self

        if present not in ({"first_name", "last_name"}, {"first_name", "last_name", "age"}):
            raise ValueError("level-1 queries require first_name + last_name, optionally age")
        self._validate_name()
        return self

    def _validate_name(self) -> None:
        if not self.first_name or not self.first_name.strip():
            raise ValueError("first_name must not be empty")
        if not self.last_name or not self.last_name.strip():
            raise ValueError("last_name must not be empty")

    def as_blindkey_query(self) -> Dict[str, Any]:
        return self.model_dump(exclude_none=True)


class VerifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=12, max_length=68)
    query: QueryModel

    @model_validator(mode="after")
    def validate_token(self):
        if not _TOKEN_RE.fullmatch(self.token):
            raise ValueError("invalid BlindKey token")
        return self


class VerifyResponse(BaseModel):
    verified: bool
    scope: Optional[str] = None
    error: Optional[str] = None


def _load_registry(registry_path: Path, verifier: Verifier) -> Dict[str, Dict[str, Any]]:
    if not registry_path.exists():
        raise FileNotFoundError(
            f"BlindKey token registry not found: {registry_path}. Run `python3 setup_demo.py` first."
        )

    raw = json.loads(registry_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not raw:
        raise ValueError("BlindKey token registry must be a non-empty JSON object.")

    resolved: Dict[str, Dict[str, Any]] = {}
    root = registry_path.parent.resolve()
    for token, filename in raw.items():
        if not isinstance(token, str) or not _TOKEN_RE.fullmatch(token):
            raise ValueError(f"Invalid token in registry: {token!r}")
        if not isinstance(filename, str) or Path(filename).name != filename:
            raise ValueError(f"Unsafe credential filename for token {token!r}")
        credential_path = (root / filename).resolve()
        if credential_path.parent != root:
            raise ValueError("Credential must remain inside the demo registry directory.")
        credential = json.loads(credential_path.read_text(encoding="utf-8"))
        if not verifier.key_is_authentic(credential):
            raise ValueError(f"Registry credential {filename} is not authentic for this Authority.")
        resolved[token] = credential
    return resolved


def create_app(
    authority_pub_path: str | os.PathLike[str],
    registry_path: str | os.PathLike[str] | None = None,
) -> FastAPI:
    pub_path = Path(authority_pub_path)
    if not pub_path.exists():
        raise FileNotFoundError(
            f"Authority public key not found: {pub_path}. "
            "Run `python3 setup_demo.py` first or set BLINDKEY_AUTHORITY_PUB."
        )

    authority_public = pub_path.read_bytes()
    if len(authority_public) != 32:
        raise ValueError("Authority public key must be exactly 32 raw Ed25519 bytes.")

    authority_fingerprint = hashlib.sha256(authority_public).hexdigest()[:12]
    verifier = Verifier(authority_public)
    registry = Path(registry_path) if registry_path else pub_path.parent / "tag_registry.json"
    token_registry = _load_registry(registry, verifier)

    app = FastAPI(title="BlindKey Verifier", version="3.0")

    def apply_protocol_headers(request: Request, response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-BlindKey-API-Version"] = str(API_VERSION)
        response.headers["X-BlindKey-Authority-Fingerprint"] = authority_fingerprint
        request_id = request.headers.get("x-request-id")
        if request_id and len(request_id) <= 128:
            response.headers["X-Request-ID"] = request_id
        return response

    @app.middleware("http")
    async def demo_safety_headers(request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > MAX_REQUEST_BYTES:
                    return apply_protocol_headers(
                        request,
                        JSONResponse(status_code=413, content={"detail": "request_too_large"}),
                    )
            except ValueError:
                return apply_protocol_headers(
                    request,
                    JSONResponse(status_code=400, content={"detail": "invalid_content_length"}),
                )

        response = await call_next(request)
        return apply_protocol_headers(request, response)

    @app.get("/health")
    def health() -> Dict[str, Any]:
        return {
            "ok": True,
            "service": "blindkey-verifier",
            "api_version": API_VERSION,
            "authority_fingerprint": authority_fingerprint,
            "registered_tokens": len(token_registry),
        }

    @app.post("/verify", response_model=VerifyResponse)
    def verify(request: VerifyRequest) -> VerifyResponse:
        credential = token_registry.get(request.token)
        if credential is None:
            return VerifyResponse(verified=False, error="unknown_token")

        # Defense in depth: registry is validated at startup, but never turn an
        # integrity problem into an ordinary RED query denial.
        if not verifier.key_is_authentic(credential):
            return VerifyResponse(verified=False, error="invalid_credential")

        query = request.query.as_blindkey_query()
        code = verifier.authenticate(credential, query)
        if not code:
            return VerifyResponse(verified=False)

        scope = verifier.check_code(code)
        if scope is None:
            raise HTTPException(status_code=500, detail="session_code_validation_failed")
        return VerifyResponse(verified=True, scope=scope)

    return app


DEFAULT_PUB = os.environ.get(
    "BLINDKEY_AUTHORITY_PUB",
    str(Path(__file__).resolve().parent / "demo" / "authority.pub"),
)
DEFAULT_REGISTRY = os.environ.get(
    "BLINDKEY_TOKEN_REGISTRY",
    str(Path(__file__).resolve().parent / "demo" / "tag_registry.json"),
)

app = create_app(DEFAULT_PUB, DEFAULT_REGISTRY)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8000, type=int)
    parser.add_argument("--authority-pub", default=DEFAULT_PUB)
    parser.add_argument("--token-registry", default=DEFAULT_REGISTRY)
    args = parser.parse_args()

    import uvicorn

    uvicorn.run(
        create_app(args.authority_pub, args.token_registry),
        host=args.host,
        port=args.port,
    )
