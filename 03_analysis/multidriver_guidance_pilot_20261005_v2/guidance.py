"""Append one generic hint to confirmed compiler multi-driver diagnostics.

The caller must supply actual native error diagnostics, never generated prose,
task text, RTL or a timeout/launch/cleanup failure. No source or files are read.
"""
import re


MULTIDRIVER_ERROR = re.compile(
    r'^[ \t]*ERROR:[ \t]*\[VRFC[ \t]+10-3818\][^\r\n]*'
    r'\binvalid combination of procedural drivers\b', re.M)

APPENDIX = (
    '\n\n[Procedural-writer repair guidance]\n'
    'Self-assignment still writes a variable; changing its type does not remove a second procedural writer. '
    'Give each storage variable one owning procedural process. For clocked storage, keep combinational '
    'next-value variables separate and update the stored value only in its clocked owner. '
    'Preserve the original behavior and interface.'
)


def augment_diagnostics(diagnostic):
    """Preserve every original character; append once for the exact real error.

    An existing exact appendix at the end is retained unchanged. The hint adds
    no signal names: all names remain solely in the original native diagnostic.
    """
    if not isinstance(diagnostic, str):
        raise TypeError('native diagnostic must be text')
    if diagnostic.endswith(APPENDIX) or not MULTIDRIVER_ERROR.search(diagnostic):
        return diagnostic
    return diagnostic + APPENDIX
