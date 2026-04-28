import os

from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader


API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)


class APIKeyAuth:
    def __init__(self, required_scopes: list[str] | None = None) -> None:
        self.required_scopes = required_scopes or ["read-write"]

    async def __call__(self, api_key: str | None = Security(API_KEY_HEADER)) -> str:
        if not api_key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing X-API-Key header",
                headers={"WWW-Authenticate": "ApiKey"},
            )

        key_scopes = _load_keys().get(api_key)
        if key_scopes is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")

        if not _has_required_scope(key_scopes, self.required_scopes):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient API key scope")

        return api_key


def _load_keys() -> dict[str, set[str]]:
    keys_str = os.environ.get("API_KEYS", "")
    keys: dict[str, set[str]] = {}
    for raw_entry in keys_str.split(","):
        entry = raw_entry.strip()
        if not entry:
            continue
        key, scopes = _parse_key_entry(entry)
        keys[key] = scopes
    return keys


def _parse_key_entry(entry: str) -> tuple[str, set[str]]:
    if ":" in entry:
        key, raw_scopes = entry.split(":", 1)
        scopes = {scope.strip() for scope in raw_scopes.split("+") if scope.strip()}
    elif entry.endswith("read-only"):
        key = entry
        scopes = {"read"}
    else:
        key = entry
        scopes = {"read", "write", "read-write"}
    if "read-write" in scopes:
        scopes.update({"read", "write"})
    return key.strip(), scopes


def _has_required_scope(key_scopes: set[str], required_scopes: list[str]) -> bool:
    return all(scope in key_scopes for scope in required_scopes)


require_auth = APIKeyAuth(["write"])
require_read = APIKeyAuth(["read"])
