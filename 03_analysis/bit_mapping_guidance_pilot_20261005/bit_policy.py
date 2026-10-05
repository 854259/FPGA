"""Exact sealed generation suffix; original repair skill and runtime unchanged."""
from pathlib import Path
import hashlib

APPENDIX_SHA = '518a93fef56513e39467b67be1031c23fd1bf37ed9bcc1a672aa050e82dc6bce'


def appendix(root=None):
    root = Path(root) if root is not None else Path(__file__).absolute().parent
    raw = (root/'APPENDIX.txt').read_bytes()
    assert hashlib.sha256(raw).hexdigest() == APPENDIX_SHA
    return raw.decode('utf-8')


def install(runtime, arm, root=None):
    """Only wrapper output changes; return original function for final restore."""
    assert arm in ('C', 'P')
    suffix = appendix(root)
    original = runtime.skill_texts
    def skills():
        generation, repair = original()
        return (generation + suffix if arm == 'P' else generation), repair
    runtime.skill_texts = skills
    return original


def system_message(generation, repair, arm, attempt, root=None):
    """Pure independent audit reconstruction, not model transport or a new skill."""
    assert arm in ('C', 'P') and type(attempt) is int and attempt in (0, 1)
    suffix = appendix(root)
    return generation + (suffix if arm == 'P' else '') + ('\n' + repair if attempt else '')
