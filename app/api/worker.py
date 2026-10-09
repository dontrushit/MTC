"""Single background worker: Whisper and the LLM must not run in parallel."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import select

from app.db.models import Call, CallStatus
from app.db.session import get_session

logger = logging.getLogger(__name__)

# One worker: whisper and the LLM share 32 GB and must not overlap.
_executor: ThreadPoolExecutor | None = None


def _pool() -> ThreadPoolExecutor:
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mtc-call")
    return _executor


def _run(call_id: int) -> None:
    from app.pipeline import process_call

    try:
        process_call(call_id)
    except Exception:
        logger.exception("process_call failed for call %s", call_id)


def submit_call(call_id: int) -> None:
    """Queue a call. Jobs run strictly one after another."""
    _pool().submit(_run, call_id)


def requeue_stuck() -> None:
    """Re-queue calls left in processing after a restart."""
    with get_session() as session:
        ids = list(
            session.scalars(
                select(Call.id)
                .where(Call.status == CallStatus.PROCESSING)
                .order_by(Call.id)
            ).all()
        )
    for call_id in ids:
        submit_call(call_id)


def shutdown_executor() -> None:
    global _executor
    executor = _executor
    _executor = None
    if executor is not None:
        executor.shutdown(wait=False, cancel_futures=True)
