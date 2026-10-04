"""Isolated deterministic experiment: cast only selector-confirmed self shifts.

The caller supplies the frozen selector module. This never reads task IDs,
testbenches, references, grades, or model responses. A patch is not a proof of
functional correctness; independent evaluation is required before adoption.
"""
from __future__ import annotations

import hashlib
import re


def patch(prompt: str, source: str, selector) -> tuple[str, dict]:
    selection = selector.analyze(prompt, source)
    record = {"selection": selection, "changed": False, "edits": [],
              "original_sha256": hashlib.sha256(source.encode()).hexdigest()}
    if selection["decision"] != "review":
        record["reason"] = "selection_" + selection["decision"]
        return source, record
    code, closed = selector._strip_noncode(source)
    if not closed or len(code) != len(source):
        record["reason"] = "offsets_not_reliable"
        return source, record
    risks = [finding for finding in selection["findings"] if finding["risk"]]
    edits = []
    for finding in risks:
        operand = finding["operand"]
        # Locate the same complete self-assignment recognized by the selector.
        # Restrict the replacement to the bare RHS identifier, leaving every
        # other byte (including comments, declarations and control flow) intact.
        pattern = re.compile(
            rf"\b{re.escape(operand)}\s*(?:<=|=(?!=))\s*\(*\s*"
            rf"(?P<operand>{re.escape(operand)})\s*>>>\s*"
            rf"(?P<amount>\d+)\s*\)*\s*;")
        matches = [match for match in pattern.finditer(code)
                   if code[:match.start()].count("\n") + 1 == finding["line"]
                   and int(match["amount"]) == finding["shift_amount"]]
        # Multiple identical assignments on one line are not disambiguated.
        if len(matches) != 1:
            record["reason"] = "assignment_location_ambiguous"
            return source, record
        start, end = matches[0].span("operand")
        if source[start:end] != operand or any(start == old[0] for old in edits):
            record["reason"] = "source_offset_or_duplicate_mismatch"
            return source, record
        edits.append((start, end, "$signed(" + operand + ")"))
    if not edits:
        record["reason"] = "no_confirmed_edits"
        return source, record
    updated = source
    for start, end, replacement in sorted(edits, reverse=True):
        updated = updated[:start] + replacement + updated[end:]
    after = selector.analyze(prompt, updated)
    if after["decision"] != "skip" or any(f["risk"] for f in after["findings"]):
        record["reason"] = "post_selection_not_clear"
        return source, record
    # Mechanically undo the planned insertions to verify an exact local edit.
    restored = updated
    adjustment = 0
    for start, end, replacement in sorted(edits):
        position = start + adjustment
        if restored[position:position + len(replacement)] != replacement:
            record["reason"] = "edit_invariant_failed"
            return source, record
        restored = restored[:position] + source[start:end] + restored[position + len(replacement):]
        # Restoring in source order leaves subsequent positions unshifted.
        adjustment = 0
    if restored != source:
        record["reason"] = "nonlocal_change_detected"
        return source, record
    record.update(changed=True, reason="explicit_signed_cast_only",
                  edits=[{"start": a, "end": b, "replacement": c} for a, b, c in sorted(edits)],
                  final_sha256=hashlib.sha256(updated.encode()).hexdigest(),
                  post_selection=after, functional_improvement="unverified")
    return updated, record
