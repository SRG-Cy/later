"""No accounts: each visitor is an anonymous random cookie. Push buttons carry a signed per-item token,
and each visitor gets their own unguessable ntfy topic (ntfy.sh topics are public by name)."""

import hashlib
import hmac
import os


def _secret() -> bytes:
    secret = os.environ.get("LATER_SECRET")
    if not secret:
        raise RuntimeError("LATER_SECRET is not set")
    return secret.encode()


def _sign(message: str) -> str:
    return hmac.new(_secret(), message.encode(), hashlib.sha256).hexdigest()


def item_token(item_id: str) -> str:
    return _sign(f"item:{item_id}")[:24]


def check_token(item_id: str, token: str | None) -> bool:
    return bool(token) and hmac.compare_digest(item_token(item_id), token)


def topic_for(owner: str) -> str:
    return f"later-{_sign(f'topic:{owner}')[:20]}"
