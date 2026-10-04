"""Research-only recovery of complete, uniquely named, linked helper modules.

This is a conservative text recognizer, not a SystemVerilog parser or proof.
It preserves the frozen baseline on unsupported/ambiguous replies. Never
constructs helpers, repairs statements, or reads task identities or grades.
"""
import hashlib
import re

ID = r"[A-Za-z_][A-Za-z0-9_$]*"
TOKEN = re.compile(r"\b(?:module|endmodule)\b")


def _sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def _instance_after(code, end):
    rest = code[end:].lstrip()
    if rest.startswith("#"):
        rest = rest[1:].lstrip()
        if not rest.startswith("("):
            return False
        depth = 0
        for i, character in enumerate(rest):
            depth += (character == "(") - (character == ")")
            if depth == 0:
                rest = rest[i + 1:].lstrip()
                break
        else:
            return False
    instance = re.match(ID + r"\s*(?:\[[^\]]+\]\s*)?\(", rest)
    return instance is not None


def extract_bundle(text, baseline, strip_noncode):
    original = baseline.extract(text, "rtl")
    record = dict(changed=False, reason="baseline_preserved", original_sha256=_sha(original),
                  final_sha256=_sha(original), modules=[], functional_improvement="unverified")

    def preserve(reason):
        record["reason"] = reason
        return original, record

    if "```" in text:
        if text.count("```") % 2:
            return preserve("unclosed_fence")
        matches = list(re.finditer(r"```([^\r\n`]*)\r?\n(.*?)```", text, re.S))
        if len(matches) * 2 != text.count("```"):
            return preserve("unsupported_fence_layout")
        if any(m.group(1).strip().lower() not in ("", "verilog", "systemverilog", "sv") for m in matches):
            return preserve("unsupported_fence_language")
        blocks = [m.group(2) for m in matches]
    else:
        blocks = [text]
    modules = []
    for block in blocks:
        code, closed = strip_noncode(block)
        if not closed or len(code) != len(block):
            return preserve("unclosed_comment_or_string")
        if "`" in code or re.search(r"\b(?:package|import|interface|program|bind|config|primitive)\b", code):
            return preserve("unsupported_scope_or_directive")
        tokens = list(TOKEN.finditer(code))
        consumed = list(code)
        if len(tokens) % 2:
            return preserve("incomplete_module")
        for opening, closing in zip(tokens[::2], tokens[1::2]):
            if opening.group() != "module" or closing.group() != "endmodule":
                return preserve("nested_or_unpaired_module")
            declaration = re.match(r"module\s+(" + ID + r")\b", code[opening.start():closing.start()])
            if declaration is None:
                return preserve("unsupported_module_declaration")
            name = declaration.group(1)
            rest = code[opening.start() + declaration.end():].lstrip()
            if not rest.startswith(("(", "#", ";")):
                return preserve("unsupported_module_declaration")
            modules.append(dict(name=name, body=block[opening.start():closing.end()].strip() + "\n",
                                code=code[opening.start():closing.end()]))
            consumed[opening.start():closing.end()] = " " * (closing.end() - opening.start())
        if "".join(consumed).strip():
            return preserve("code_outside_complete_modules")
    names = [m["name"] for m in modules]
    record["modules"] = names
    if names.count("TopModule") != 1:
        return preserve("top_module_not_unique")
    if len(names) != len(set(names)):
        return preserve("duplicate_helper_name")
    if len(names) == 1:
        return preserve("single_top_baseline_preserved")
    by_name = {m["name"]: m for m in modules}
    edges = {}
    for module in modules:
        edges[module["name"]] = {
            name for name in names
            if any(_instance_after(module["code"], match.end())
                   for match in re.finditer(r"\b" + re.escape(name) + r"\b", module["code"]))
        }
    reached, active = set(), set()

    def visit(name):
        if name in active:
            return False
        if name in reached:
            return True
        active.add(name)
        for child in edges[name]:
            if not visit(child):
                return False
        active.remove(name)
        reached.add(name)
        return True

    if not visit("TopModule"):
        return preserve("recursive_module_bundle")
    if reached != set(names):
        return preserve("unreferenced_helper_or_alternative")
    chosen = by_name["TopModule"]["body"] + "\n" + "\n".join(m["body"] for m in modules if m["name"] != "TopModule")
    record.update(changed=chosen != original, reason="unique_complete_linked_bundle",
                  final_sha256=_sha(chosen), dependency_edges={k: sorted(v) for k, v in edges.items()})
    return chosen, record
