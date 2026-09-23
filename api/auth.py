"""Bearer-token authentication (spec 007).

A single shared secret, not per-caller identity -- v1's access-control
model answers "is this caller allowed to use the API at all," nothing
finer-grained. See spec 007's Open questions for the known limits of that.
"""

import os
import secrets

from fastapi import Header, HTTPException, status

TOKEN_ENV_VAR = "INCIDENT_AGENT_API_TOKEN"


def get_expected_token() -> str:
    """Reads the configured token from the environment. Raises if it isn't
    set -- called once at API startup (`api/app.py`) so the process
    refuses to start without it configured, and again per-request inside
    `require_bearer_token` so a token change takes effect without a
    restart."""
    token = os.environ.get(TOKEN_ENV_VAR)
    if not token:
        raise RuntimeError(f"{TOKEN_ENV_VAR} must be set")
    return token


def require_bearer_token(authorization: str | None = Header(default=None)) -> None:
    """FastAPI dependency: 401s the request unless `Authorization: Bearer
    <token>` matches the configured token. Uses a constant-time comparison
    to avoid a timing side-channel on the token value."""
    expected = get_expected_token()
    if authorization is None or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="missing bearer token"
        )
    provided = authorization.removeprefix("Bearer ")
    if not secrets.compare_digest(provided, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid bearer token"
        )
