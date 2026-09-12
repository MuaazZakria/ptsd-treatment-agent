"""
Single-admin login gate.

Not real IAM: one shared password (`IASO_ADMIN_PASSWORD`), no user identity
beyond "the admin", no lockout/rate-limiting. It exists so this app isn't
wide open to anyone who can reach the port - nothing more. Stdlib only, to
keep with the "self-contained, minimal deps" constraint already governing
this app (see HANDOVER.md).

Session token: `hmac_sha256(secret, "admin:<expiry>")`, base64-encoded
alongside the expiry, verified with a constant-time compare. A process
restart with no IASO_SESSION_SECRET set rotates the secret and invalidates
every outstanding session - acceptable for a single-admin tool.
"""

from __future__ import annotations

import base64
import hmac
import time
from hashlib import sha256

from .config import Settings

COOKIE_NAME = "iaso_session"
SESSION_TTL_S = 60 * 60 * 12  # 12h


def _sign(secret: str, expiry: int) -> str:
    msg = f"admin:{expiry}".encode("ascii")
    return hmac.new(secret.encode("utf-8"), msg, sha256).hexdigest()


def check_password(password: str, cfg: Settings) -> bool:
    if not cfg.admin_password:
        return False
    return hmac.compare_digest(password.strip(), cfg.admin_password)


def issue_token(cfg: Settings, *, ttl_s: int = SESSION_TTL_S) -> str:
    expiry = int(time.time()) + ttl_s
    sig = _sign(cfg.session_secret, expiry)
    raw = f"{expiry}.{sig}".encode("ascii")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def verify_token(token: str | None, cfg: Settings) -> bool:
    if not token:
        return False
    try:
        raw = base64.urlsafe_b64decode(token.encode("ascii")).decode("ascii")
        expiry_s, sig = raw.split(".", 1)
        expiry = int(expiry_s)
    except (ValueError, UnicodeDecodeError):
        return False
    if expiry < int(time.time()):
        return False
    return hmac.compare_digest(sig, _sign(cfg.session_secret, expiry))
