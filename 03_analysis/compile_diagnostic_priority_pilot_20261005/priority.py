"""Prioritize distinct real compiler errors before the existing feedback cap.

The caller must have a confirmed failed native compile and preserve its original
full stdout, physical return code and receipt separately. Text is no attestation.
This changes only diagnostic presentation, without adding advice or signal names.
"""
import re

SEVERE = re.compile(r'^\s*(?:ERROR|FATAL)(?:\s|:)')
LOCATION = re.compile(r'(?P<file>\[[^\]\r\n]*\.(?:svh|sv|vh|v)):\d+(?::\d+)?\]\s*$', re.I)


def prioritize_stdout(stdout):
    """Keep first full severe messages, then the original other lines.

    Only a recognized trailing Verilog source line/column is excluded from the
    duplicate key. File path, diagnostic code, complete message and variable
    names remain in that key. Every retained line itself is unchanged. Different
    occurrences of the same message in one source file are not proved to share
    one semantic cause; the original full native log must remain available.

    No severity line means byte-for-character unchanged text. The existing
    runtime still applies its original 2048-character diagnostic selection/cap.
    """
    if not isinstance(stdout, str):
        raise TypeError('actual native stdout must be text')
    lines = stdout.splitlines()
    severe, rest, seen = [], [], set()
    for line in lines:
        if not SEVERE.match(line):
            rest.append(line)
            continue
        key = LOCATION.sub(lambda match: match['file'] + ']', line).strip()
        if key not in seen:
            severe.append(line)
            seen.add(key)
    if not severe:
        return stdout
    return '\n'.join(severe + rest)
