from __future__ import annotations

import asyncio
import logging
import os
import sys
from typing import Any

if __name__ == "__main__" and __package__ is None:
    # Executed directly (e.g. "Run" in the IDE) rather than as a package module.
    # Add the project root to sys.path and set __package__ so relative imports work.
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    __package__ = "gateflow"

from .store import log_audit_event

logger = logging.getLogger("gateflow.audit")

_background_tasks: set[asyncio.Task] = set()


def log_admin_async(action: str, resource: str, x_admin_api_key: str, details: dict[str, Any] | None = None) -> None:
    """Fire an async audit event for an admin action.

    The admin key is one-way hashed so the audit log does not contain
    reusable credentials. The event is written durably to the database and
    also published to the Redis audit stream for real-time consumers.
    """

    async def _push() -> None:
        try:
            await log_audit_event(action, resource, x_admin_api_key, details)
        except Exception as exc:
            logger.warning("audit_push_failed", extra={"error": str(exc)})

    task = asyncio.create_task(_push())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


async def flush_audit() -> None:
    """Wait for any in-flight audit tasks to finish before shutdown."""
    if _background_tasks:
        await asyncio.gather(*_background_tasks, return_exceptions=True)
