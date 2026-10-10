"""Propagate one existing solve budget to HTTP and owned tool operations."""
import math
import time


class SolveBudget:
    def __init__(self, seconds=300, clock=None):
        if type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds <= 0:
            raise ValueError('Invalid shared solve budget')
        self.clock = clock or time.monotonic
        self.end = self.clock() + seconds

    def remaining(self, cap=None):
        remaining = self.end - self.clock()
        if remaining <= 0:
            raise RuntimeError('Shared solve budget exhausted; no further dispatch')
        if cap is not None:
            if type(cap) not in (int, float) or not math.isfinite(cap) or cap <= 0:
                raise ValueError('Invalid operation cap')
            remaining = min(remaining, cap)
        return remaining

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
