"""Unexecuted agent-only extraction draft. Never edit the official baseline.

This small scanner recognizes module boundaries, not SystemVerilog syntax.
The original first-Markdown-fence selection and whitespace policy are retained.
Unsupported or ambiguous input delegates to the original extractor unchanged.
"""
import hashlib
import re

FENCE = re.compile(r"```(?:systemverilog|verilog|sv|cpp|c\+\+|c)?\s*(.*?)```", re.S)
NAME = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*\Z")
WORD_CHARS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_$")


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def tokens(text):
    """Return (word or None, start, end); opaque spans cannot become keywords."""
    result, i, size = [], 0, len(text)
    while i < size:
        start = i
        if text[i].isspace():
            i += 1
        elif text.startswith("//", i):
            ends = [p for p in (text.find("\n", i + 2), text.find("\r", i + 2)) if p >= 0]
            i = min(ends) + 1 if ends else size
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            if end < 0:
                return None, "unterminated_block_comment"
            i = end + 2
        elif text[i] == '"':
            i += 1
            while i < size and text[i] != '"':
                if text[i] == "\\":
                    i += 2
                else:
                    i += 1
            if i >= size:
                return None, "unterminated_string"
            i += 1
            result.append((None, start, i))
        elif text[i] == "\\":
            i += 1
            while i < size and not text[i].isspace():
                i += 1
            result.append((None, start, i))
        elif text[i] == "`":
            return None, "preprocessor_not_interpreted"
        elif text[i] in WORD_CHARS:
            i += 1
            while i < size and text[i] in WORD_CHARS:
                i += 1
            result.append((text[start:i], start, i))
        else:
            i += 1
            result.append((None, start, i))
    return result, None


def module_span(text):
    words, error = tokens(text)
    if error:
        return None, error
    active, matches = None, []
    for index, (word, start, end) in enumerate(words):
        if word == "module":
            if active is not None:
                return None, "nested_module_not_interpreted"
            name_index = index + 1
            if name_index < len(words) and words[name_index][0] in ("automatic", "static"):
                name_index += 1
            name = words[name_index][0] if name_index < len(words) else None
            if name is None or NAME.fullmatch(name) is None:
                return None, "module_name_not_supported"
            active = (name, start)
        elif word == "endmodule":
            if active is None:
                return None, "unmatched_endmodule"
            if active[0] == "TopModule":
                matches.append((active[1], end))
            active = None
    if active is not None:
        return None, "missing_real_endmodule"
    if len(matches) != 1:
        return None, "top_module_missing_or_ambiguous"
    return matches[0], None


def extract_with_receipt(text, track, original_extract):
    """Only an agent-side caller may select this policy; no prompt/ID inputs."""
    original = original_extract(text, track)
    match = FENCE.search(text)
    selected = match.group(1) if match else text
    receipt = dict(schema="agent_lexical_module_boundary_draft_v1", response_text_sha256=digest(text),
        selected_text_sha256=digest(selected), original_extracted_sha256=digest(original),
        changed=False, status="abstain", reason="non_rtl_unchanged", module_span=None,
        syntax_validated=False, compiled=False, score_measured=False,
        model_calls=0, EDA_calls=0, external_io_calls=0, semantic_edits=0)
    if track != "rtl":
        receipt["extracted_sha256"] = digest(original)
        return original, receipt
    span, error = module_span(selected)
    if error:
        receipt.update(reason=error, extracted_sha256=digest(original))
        return original, receipt
    code = selected[span[0]:span[1]].strip() + "\n"
    receipt.update(status="lexical_span_selected", reason=None, module_span=list(span),
        changed=code != original, extracted_sha256=digest(code))
    return code, receipt
