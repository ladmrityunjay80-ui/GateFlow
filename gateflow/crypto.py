from __future__ import annotations

import hashlib
import hmac
import logging
import os
import sys

if __name__ == "__main__" and __package__ is None:
    # Executed directly (e.g. "Run" in the IDE) rather than as a package module.
    # Add the project root to sys.path and set __package__ so relative imports work.
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    __package__ = "gateflow"

from .config import Settings, get_settings

logger = logging.getLogger("gateflow.crypto")


def _primary_key_secret() -> str:
    settings = get_settings()
    if settings.key_secret == Settings.model_fields["key_secret"].default:
        logger.warning("using_default_key_secret")
    return settings.key_secret


def _key_secrets() -> list[str]:
    """Return the primary secret followed by any historical versions."""
    settings = get_settings()
    versions = [s.strip() for s in settings.key_secret_versions.split(",") if s.strip()]
    return [_primary_key_secret(), *versions]


def hash_api_key(api_key: str, secret: str | None = None) -> str:
    """Deterministic, one-way identifier for an API key.

    Uses HMAC-SHA256 with a server-side secret. The original API key is
    never persisted, so a database compromise does not expose reusable
    credentials.
    """
    secret = secret or _primary_key_secret()
    return hmac.new(secret.encode(), api_key.encode(), hashlib.sha256).hexdigest()


def constant_time_compare(a: str, b: str) -> bool:
    return hmac.compare_digest(a, b)
