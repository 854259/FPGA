"""A Linux working deadline for the entire terminal supervisor, with cleanup reserve."""
import signal
import sys
import time

_active = False
_expired = False


def start(total_s, cleanup_reserve_s=20):
    global _active, _expired, _started, _total, _reserve, _previous
    assert sys.platform == 'linux' and not _active
    assert 0 < cleanup_reserve_s < total_s <= 450
    assert signal.getitimer(signal.ITIMER_REAL) == (0.0, 0.0)
    _started = time.monotonic()
    _total, _reserve = float(total_s), float(cleanup_reserve_s)
    _expired, _active = False, True
    _previous = signal.getsignal(signal.SIGALRM)

    def expire(signum, frame):
        global _expired
        _expired = True
        raise TimeoutError('complete terminal working deadline expired; cleanup reserve remains')

    signal.signal(signal.SIGALRM, expire)
    signal.setitimer(signal.ITIMER_REAL, _total - _reserve)
    return _started


def finish():
    global _active
    assert _active
    signal.setitimer(signal.ITIMER_REAL, 0)
    signal.signal(signal.SIGALRM, _previous)
    elapsed = time.monotonic() - _started
    _active = False
    return dict(total_cap_s=_total, working_cap_s=_total-_reserve,
                cleanup_reserve_s=_reserve, elapsed_s=elapsed,
                working_deadline_expired=_expired,
                within_complete_budget=elapsed <= _total)
