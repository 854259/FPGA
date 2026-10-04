"""Research-only recovery of one unambiguous complete fenced TopModule."""
import hashlib
import re


def extract_complete(text, baseline, strip_noncode):
    original = baseline.extract(text, "rtl")
    record = dict(changed=False, reason="baseline_preserved", original_sha256=hashlib.sha256(original.encode()).hexdigest())
    if "```" not in text:
        record["reason"] = "no_fences"
        return original, record
    if text.count("```") % 2:
        record["reason"] = "unclosed_fence"
        return original, record
    candidates = []
    for tag, block in re.findall(r"```([^\r\n`]*)\r?\n(.*?)```", text, re.S):
        if tag.strip().lower() not in ("", "verilog", "systemverilog", "sv"):
            continue
        code, closed = strip_noncode(block)
        if not closed or len(code) != len(block):
            record["reason"] = "unclosed_code_comment_or_string"
            return original, record
        tokens = list(re.finditer(r"\b(?:module|endmodule)\b", code))
        if not tokens:
            continue
        if len(tokens) != 2 or tokens[0].group() != "module" or tokens[1].group() != "endmodule":
            record["reason"] = "ambiguous_module_structure"
            return original, record
        declaration = re.match(r"module\s+TopModule\b", code[tokens[0].start():])
        if declaration is None:
            record["reason"] = "other_module_present"
            return original, record
        rest = code[tokens[0].start() + declaration.end():].lstrip()
        if not rest.startswith(("(", "#", ";")):
            record["reason"] = "declaration_not_clear"
            return original, record
        candidates.append(block[tokens[0].start():tokens[1].end()].strip() + "\n")
    if len(candidates) != 1:
        record["reason"] = "complete_module_not_unique"
        return original, record
    chosen = candidates[0]
    record.update(changed=chosen != original, reason="single_complete_fenced_module",
                  final_sha256=hashlib.sha256(chosen.encode()).hexdigest(), functional_improvement="unverified")
    return chosen, record
