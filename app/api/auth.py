"""API-key authentication with tenant identity derived from the credential."""

from __future__ import annotations

import hashlib
import hmac
import os
from dataclasses import dataclass

from fastapi import Header, HTTPException

ANONYMOUS_TENANT = os.environ.get("ANONYMOUS_TENANT", "stu_maya_chen")
ANONYMOUS_KEY_ID = "openmode"


@dataclass(frozen=True)
class Principal:
    tenant_id: str
    admin: bool
    key_id: str


def parse_keys(raw: str) -> dict[str, Principal]:
    principals: dict[str, Principal] = {}
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        try:
            token, tenant = entry.split(":", 1)
        except ValueError as exc:
            raise ValueError("API_KEYS entries must have the form token:tenant") from exc
        token, tenant = token.strip(), tenant.strip()
        if not token or not tenant:
            raise ValueError("API_KEYS tokens and tenants must not be empty")
        digest = hashlib.sha256(token.encode()).hexdigest()
        principals[digest] = Principal(tenant, tenant == "*", digest[:8])
    return principals


def principal_for_key(x_api_key: str | None) -> Principal:
    raw = os.environ.get("API_KEYS", "").strip()
    if not raw:
        return Principal(ANONYMOUS_TENANT, True, ANONYMOUS_KEY_ID)
    if not x_api_key:
        raise HTTPException(status_code=401, detail="missing API key")
    candidate = hashlib.sha256(x_api_key.encode()).hexdigest()
    for digest, principal in parse_keys(raw).items():
        if hmac.compare_digest(candidate, digest):
            return principal
    raise HTTPException(status_code=401, detail="unknown API key")


def resolve(x_api_key: str | None = Header(default=None)) -> Principal:
    return principal_for_key(x_api_key)
