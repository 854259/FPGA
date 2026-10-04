"""Read-only hints for a deliberately narrow source subset; never a patch.

Only single-name internal numeric packed declarations and direct decimal bit
selects are recognized. No parameter evaluation, generate expansion, port ranges,
part selects or nested function/task scopes. Hints require real EDA confirmation.
"""
import re

MODULES = re.compile(r"\b(module|endmodule)\b")
DECL = re.compile(r"(?m)^[ \t]*(?:wire|reg|logic|bit)\s+(?:(?:signed|unsigned)\s+)?\[\s*(-?\d+)\s*:\s*(-?\d+)\s*\]\s+([A-Za-z_]\w*)\s*;")
ANY_DECL = re.compile(r"\b(?:wire|reg|logic|bit)\s+(?:(?:signed|unsigned)\s+)?(?:\[[^\]]*\]\s*)?([^;]*);")


def inspect(code, strip_noncode):
    masked, closed = strip_noncode(code)
    record = dict(status="scanned", hints=[], declarations=0, skipped_scopes=0)
    if not closed:
        record["status"] = "unclosed_noncode"
        return record
    if "`" in masked:
        record["status"] = "unsupported_directive"
        return record
    tokens = list(MODULES.finditer(masked))
    if not tokens or len(tokens) % 2 or any(a.group(1) != "module" or b.group(1) != "endmodule" for a, b in zip(tokens[::2], tokens[1::2])):
        record["status"] = "unpaired_modules"
        return record
    for opening, closing in zip(tokens[::2], tokens[1::2]):
        scope = masked[opening.start():closing.start()]
        name = re.match(r"module\s+([A-Za-z_]\w*)\b", scope)
        if not name or re.search(r"\b(?:function|task|class|interface|typedef)\b", scope):
            record["skipped_scopes"] += 1
            continue
        declarations = list(DECL.finditer(scope))
        for declaration in declarations:
            signal = declaration.group(3)
            # Any repeated textual declaration is ambiguous (including locals
            # in nested blocks); do not attribute a select to the wrong scope.
            # Broad declaration-text matching also sees inline block locals,
            # sibling names and initializer uses. Extra abstention is acceptable
            # here: the result is only a prioritization hint, never a diagnosis.
            if sum(bool(re.search(r"\b" + re.escape(signal) + r"\b", d.group(1))) for d in ANY_DECL.finditer(scope)) != 1:
                continue
            record["declarations"] += 1
            low, high = sorted((int(declaration.group(1)), int(declaration.group(2))))
            pattern = re.compile(r"(?<![\w.$])" + re.escape(signal) + r"\s*\[\s*(-?\d+)\s*\]")
            for selected in pattern.finditer(scope):
                value = int(selected.group(1))
                if not low <= value <= high:
                    offset = opening.start() + selected.start()
                    record["hints"].append(dict(module=name.group(1), signal=signal, index=value, range_low=low, range_high=high, line=code.count("\n", 0, offset) + 1, kind="literal_internal_vector_select_outside_declared_range", confirmed_compiler_error=False))
    return record
