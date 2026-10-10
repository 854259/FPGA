"""Propagate one existing solve budget to HTTP and owned tool operations."""
import math
import time
import hashlib
from pathlib import Path


class BudgetExpired(RuntimeError):
    pass


class SolveBudget:
    def __init__(self, seconds=300, clock=None):
        if type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds <= 0:
            raise ValueError('Invalid shared solve budget')
        self.clock = clock or time.monotonic
        self.started = self.clock()
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
        elapsed = self.clock() - self.started
        assert math.isfinite(elapsed) and elapsed >= 300
        digest = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
        return dict(schema='shared_worker_budget_expired_v1', budget_s=300, elapsed_s=elapsed,
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

    def owned_operation(self, original):
        def bounded(argv, cwd, log, cap):
            # Preserve the original supervisor's ownership, cleanup and receipt.
            return original(argv, cwd, log, self.remaining(cap))
        return bounded
