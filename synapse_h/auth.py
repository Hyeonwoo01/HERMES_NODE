"""Accounts, roles and permissions.

Passwords are stored only as PBKDF2-SHA256 hashes (``hash_password``; generate
them with ``python scripts/make_password_hash.py``). Accounts come from the
deployment's secrets, never from the repository. When no accounts are
configured the app stays a public synthetic demo and says so on every screen.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass, field

ITERATIONS = 600_000
MAX_FAILURES = 5
LOCKOUT_S = 300

ROLE_LABELS = {
    "viewer": "조회 전용",
    "coordinator": "전원 담당",
    "supervisor": "감독자",
}
PERMISSIONS: dict[str, frozenset[str]] = {
    "viewer": frozenset({"view"}),
    "coordinator": frozenset({"view", "confirm_case", "decide", "record_outcome"}),
    "supervisor": frozenset({"view", "confirm_case", "decide", "record_outcome",
                             "view_audit", "export_audit", "change_settings", "load_live_data"}),
}
# Public demo: everything works, nothing is real.
DEMO_PERMISSIONS = PERMISSIONS["supervisor"]


def hash_password(password: str, salt: bytes | None = None, iterations: int = ITERATIONS) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    b64 = base64.urlsafe_b64encode
    return f"pbkdf2_sha256${iterations}${b64(salt).decode()}${b64(digest).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters, salt, digest = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        expected = base64.urlsafe_b64decode(digest)
        got = hashlib.pbkdf2_hmac("sha256", password.encode(), base64.urlsafe_b64decode(salt), int(iters))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(got, expected)


@dataclass(frozen=True)
class User:
    username: str
    display_name: str
    role: str

    @property
    def permissions(self) -> frozenset[str]:
        return PERMISSIONS.get(self.role, frozenset())

    def can(self, permission: str) -> bool:
        return permission in self.permissions


@dataclass
class UserStore:
    """Accounts loaded from a secrets mapping: {username: {name, role, password_hash}}."""

    accounts: dict[str, dict] = field(default_factory=dict)
    _failures: dict[str, list[float]] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, mapping) -> "UserStore":
        accounts = {}
        for username, entry in dict(mapping or {}).items():
            entry = dict(entry)
            if entry.get("role") not in PERMISSIONS or not entry.get("password_hash"):
                raise ValueError(f"account {username!r} needs a valid role and password_hash")
            accounts[str(username)] = entry
        return cls(accounts)

    @property
    def enabled(self) -> bool:
        return bool(self.accounts)

    def locked(self, username: str, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        recent = [t for t in self._failures.get(username, []) if now - t < LOCKOUT_S]
        self._failures[username] = recent
        return len(recent) >= MAX_FAILURES

    def authenticate(self, username: str, password: str, now: float | None = None) -> User | None:
        """User on success; None on a wrong name/password or while the account is locked out."""
        now = time.time() if now is None else now
        if self.locked(username, now):
            return None
        entry = self.accounts.get(username)
        # Unknown names are checked against a dummy hash so timing does not reveal which accounts exist.
        ok = verify_password(password, entry["password_hash"] if entry else _dummy_hash())
        if entry and ok:
            self._failures.pop(username, None)
            return User(username, entry.get("name", username), entry["role"])
        self._failures.setdefault(username, []).append(now)
        return None


_DUMMY: list[str] = []


def _dummy_hash() -> str:
    if not _DUMMY:
        _DUMMY.append(hash_password(secrets.token_hex(16)))
    return _DUMMY[0]
