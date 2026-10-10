"""Propagate one existing solve budget to HTTP and owned tool operations."""
import math
import time
import hashlib
import signal
import sys
import threading
import os
from contextlib import contextmanager
from pathlib import Path


class BudgetExpired(RuntimeError):
    pass


PARENT_STARTED_ENV = 'RTL_SOLVE_PARENT_STARTED_MONOTONIC'


def parent_started_from_environment():
    """A production worker must inherit the queue's monotonic solve start."""
    raw = os.environ.get(PARENT_STARTED_ENV)
    if raw is None:
        raise ValueError('Missing parent solve-start binding')
    try:
        started = float(raw)
    except (ValueError, TypeError) as error:
        raise ValueError('Invalid parent solve-start binding') from error
    if not math.isfinite(started) or started < 0:
        raise ValueError('Invalid parent solve-start binding')
    return started


class SolveBudget:
    def __init__(self, seconds=300, clock=None, parent_started=None):
        if type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds <= 0:
            raise ValueError('Invalid shared solve budget')
        self.clock = clock or time.monotonic
        now = self.clock()
        if parent_started is not None and (
                type(parent_started) not in (int, float) or
                not math.isfinite(parent_started) or not 0 <= parent_started <= now):
            raise ValueError('Invalid or future parent solve start')
        self.started = now if parent_started is None else parent_started
        self.seconds = seconds
        self.end = self.started + seconds

    def remaining(self, cap=None):
        remaining = self.end - self.clock()
        if remaining <= 0:
            raise BudgetExpired('Shared solve budget exhausted; no further dispatch')
        if cap is not None:
            if type(cap) not in (int, float) or not math.isfinite(cap) or cap <= 0:
                raise ValueError('Invalid operation cap')
            remaining = min(remaining, cap)
        return remaining

    def expired(self):
        return self.clock() >= self.end

    def exit_receipt(self, requests_path, worker_source):
        assert self.seconds == 300 and self.expired()
        observed = self.clock()
        elapsed = observed - self.started
        assert math.isfinite(elapsed) and elapsed >= 300
        digest = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
        return dict(schema='shared_worker_budget_expired_v2', budget_s=300, elapsed_s=elapsed,
                    started_monotonic=self.started, observed_monotonic=observed,
                    requests_sha256=digest(requests_path), worker_source_sha256=digest(worker_source),
                    budget_source_sha256=digest(__file__), complete=False, grade=None,
                    actual_calls=None, unconfirmed_calls=None, score_eligible=False)

    def http_timeout(self, positional, kwargs):
        # The frozen runtime supplies request and keyword timeout only.
        if positional:
            raise ValueError('Unreviewed positional HTTP timeout contract')
        result = dict(kwargs)
        result['timeout'] = self.remaining(result.get('timeout', 300))
        return result

    @contextmanager
    def http_deadline(self):
        """Bound opening and reading HTTP even while the peer keeps sending bytes.

        This is only used in the owned Linux worker's main thread. Do not arm
        asynchronous exceptions around the native process supervisor or cleanup.
        Refuse another timer/handler instead of replacing its ownership.
        """
        if sys.platform != 'linux' or threading.current_thread() is not threading.main_thread():
            raise RuntimeError('HTTP deadline requires the owned Linux main thread')
        previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGALRM})
        previous_handler = signal.getsignal(signal.SIGALRM)
        armed = False
        try:
            if signal.SIGALRM in previous_mask:
                raise RuntimeError('HTTP deadline signal already blocked')
            if signal.getitimer(signal.ITIMER_REAL) != (0.0, 0.0):
                raise RuntimeError('HTTP deadline timer already owned')
            if previous_handler not in (signal.SIG_DFL, signal.SIG_IGN):
                raise RuntimeError('HTTP deadline handler already owned')
            if signal.SIGALRM in signal.sigpending():
                raise RuntimeError('HTTP deadline signal already pending')

            def deadline_expired(signum, frame):
                raise BudgetExpired('Shared solve budget exhausted during HTTP')

            signal.signal(signal.SIGALRM, deadline_expired)
            armed = True
            signal.setitimer(signal.ITIMER_REAL, self.remaining())
            signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
            yield
            self.remaining()
        finally:
            signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGALRM})
            if armed:
                signal.setitimer(signal.ITIMER_REAL, 0)
                if signal.SIGALRM in signal.sigpending():
                    signal.sigtimedwait({signal.SIGALRM}, 0)
                signal.signal(signal.SIGALRM, previous_handler)
            signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)

    def owned_operation(self, original):
        def bounded(argv, cwd, log, cap):
            # Preserve the original supervisor's ownership, cleanup and receipt.
            return original(argv, cwd, log, self.remaining(cap))
        return bounded
