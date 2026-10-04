"""Research-only recovery of one unambiguous complete fenced TopModule."""
import hashlib
import re


def extract_hierarchy(text, baseline, strip_noncode, missing_modules):
    """Retain complete helper definitions in one unambiguous fenced response.

    No RTL is invented or rewritten. Unsupported structure preserves the original
    extractor output. This is a research candidate, not the official extractor.
    """
    original = baseline.extract(text, "rtl")
    record = dict(changed=False, reason="baseline_preserved")
    if text.count("```") != 2:
        record["reason"] = "not_one_closed_fence"
        return original, record
    match = re.search(r"```([^\r\n`]*)\r?\n(.*?)```", text, re.S)
    if not match or match[1].strip().lower() not in ("", "verilog", "systemverilog", "sv"):
        record["reason"] = "unsupported_fence"
        return original, record
    block = match[2]
    code, closed = strip_noncode(block)
    if not closed or "`" in code or "\\" in code:
        record["reason"] = "unsupported_lexical_context"
        return original, record
    tokens = list(re.finditer(r"\b(?:module|endmodule)\b", code))
    if len(tokens) < 4 or len(tokens) % 2:
        record["reason"] = "not_complete_hierarchy"
        return original, record
    names, spans, cursor = [], [], 0
    for start, end in zip(tokens[::2], tokens[1::2]):
        if start[0] != "module" or end[0] != "endmodule" or code[cursor:start.start()].strip():
            record["reason"] = "unsupported_compilation_unit"
            return original, record
        name = re.match(r"module\s+([A-Za-z_][A-Za-z0-9_$]*)\s*(?=[(#;])", code[start.start():])
        if not name or name[1] in names:
            record["reason"] = "ambiguous_module_declaration"
            return original, record
        names.append(name[1])
        spans.append(block[start.start():end.end()].strip() + "\n")
        cursor = end.end()
    if code[cursor:].strip() or names.count("TopModule") != 1:
        record["reason"] = "unsupported_compilation_unit"
        return original, record
    if spans[names.index("TopModule")] != original:
        record["reason"] = "top_extraction_not_exact"
        return original, record
    missing = missing_modules(original)
    if not missing or any(name not in names for name in missing) or missing_modules(block):
        record["reason"] = "no_complete_missing_dependency"
        return original, record
    chosen = block.strip() + "\n"
    record.update(changed=chosen != original, reason="complete_fenced_hierarchy", modules=names,
                  restored_dependencies=missing)
    return chosen, record


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
