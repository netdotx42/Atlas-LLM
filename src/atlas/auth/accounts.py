"""Email login, a 14-day trial, and one-time 30/90/365 day passes."""

import hashlib
import hmac
import re
import secrets
from datetime import UTC, datetime, timedelta

PASSES: dict[str, tuple[int, int]] = {
    "30": (30, 2900),
    "90": (90, 6900),
    "365": (365, 17900),
}
TRIAL_DAYS = 14
LOCK_AFTER = 5
LOCK_MINUTES = 15
PBKDF2_ROUNDS = 200_000
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_DUMMY = hashlib.pbkdf2_hmac("sha256", b"atlas-dummy", b"atlas-dummy-salt", PBKDF2_ROUNDS)


def normalize_email(value: str) -> str:
    email = value.strip().lower()
    if not _EMAIL.fullmatch(email) or len(email) > 200:
        raise ValueError("Use a valid email")
    return email


def hash_password(password: str) -> str:
    if len(password) < 10:
        raise ValueError("Use at least 10 characters")
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), PBKDF2_ROUNDS)
    return f"pbkdf2${PBKDF2_ROUNDS}${salt}${digest.hex()}"


def password_ok(password: str, stored: str) -> bool:
    try:
        _, rounds, salt, digest = stored.split("$", 3)
        check = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(rounds))
        return hmac.compare_digest(check.hex(), digest)
    except (ValueError, TypeError):
        hmac.compare_digest(_DUMMY, _DUMMY)
        return False


def new_token() -> str:
    return secrets.token_urlsafe(32)


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value)


def stamp(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="microseconds")


def trial_end(now: datetime | None = None) -> datetime:
    return (now or datetime.now(UTC)) + timedelta(days=TRIAL_DAYS)


def extend_until(current: str, days: int, now: datetime | None = None) -> str:
    moment = now or datetime.now(UTC)
    base = max(parse_time(current), moment)
    return stamp(base + timedelta(days=days))


def is_open(access_until: str, now: datetime | None = None) -> bool:
    return parse_time(access_until) > (now or datetime.now(UTC))


def days_left(access_until: str, now: datetime | None = None) -> int:
    moment = now or datetime.now(UTC)
    remaining = parse_time(access_until) - moment
    if remaining.total_seconds() <= 0:
        return 0
    return remaining.days + (1 if remaining.seconds or remaining.microseconds else 0)


def pass_catalog() -> list[dict[str, int | str]]:
    return [
        {"id": key, "days": days, "cents": cents, "label": f"{days} days"}
        for key, (days, cents) in PASSES.items()
    ]
