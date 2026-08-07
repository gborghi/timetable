"""Test concurrent run safety (audit T6)."""
import pytest
import threading
from backend.run_manager import (
    active_run_count,
    is_cancel_requested,
    request_cancel,
    _RUN_SLOTS,
)


def test_semaphore_initialized():
    """The admission-control semaphore is initialized on import."""
    assert _RUN_SLOTS is not None
    assert _RUN_SLOTS._value >= 1


def test_cancel_unknown_run():
    """Cancelling a non-existent run should return False."""
    assert is_cancel_requested(999999) is False
    assert request_cancel(999999) is False


def test_active_run_count_is_int():
    """active_run_count returns a non-negative integer."""
    assert isinstance(active_run_count(), int)
    assert active_run_count() >= 0


def test_concurrent_cancel_requests():
    """Multiple threads cancelling different runs should be safe."""
    results = []

    def _cancel(rid):
        results.append(request_cancel(rid))

    threads = [threading.Thread(target=_cancel, args=(i,)) for i in range(999900, 999910)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    # All should return False (runs don't exist)
    assert results == [False] * 10
