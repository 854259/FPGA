"""Research-only factual diagnostic extraction; never changes candidate code."""
import hashlib
import csv
import io
import json
import re


MESSAGE = re.compile(r"^(WARNING|CRITICAL WARNING|ERROR): \[([A-Za-z]+ \d+-\d+)\] (.*)$")
LOCATION = re.compile(r"\s+\[([^\[\]\r\n]+):(\d+)\]\s*$")
RULE = re.compile(r"^(ASSIGN|INFER|CLOCK|RESET|QOR)-\d+(?: \(T\d+\))?$")


def inspect_report(report_text, expected_count):
    """Reject unknown/malformed reports and mismatched counts, including empty ones."""
    text = report_text.strip()
    rows, kind = [], "unknown"
    try:
        if not text:
            kind = "empty_headerless_csv"
        elif text.startswith("{") or text.startswith('"cols"'):
            kind = "json"
            data = json.loads(text if text.startswith("{") else "{" + text + "}")
            if not isinstance(data, dict) or not isinstance(data.get("rows"), list):
                raise ValueError("JSON rows missing")
            rows = data["rows"]
        elif "RTL Linter Report" in text and "2. Expanded" in text:
            kind = "ascii_table"
            positions, in_expanded, header = [], False, False
            for line in text.splitlines():
                if line.strip() == "2. Expanded":
                    positions, in_expanded, header = [], True, False
                    rows = []
                    continue
                if not in_expanded:
                    continue
                if line.startswith("+") and "-" in line:
                    if not positions:
                        positions = [i for i, c in enumerate(line) if c == "+"]
                    elif rows:
                        break
                    continue
                if not line.startswith("|") or not positions:
                    continue
                fields = [line[a + 1:b].strip() for a, b in zip(positions, positions[1:])]
                if fields and fields[0].lower() == "rule id":
                    header = True
                    continue
                if any(fields):
                    rows.append(fields)
            if not header:
                raise ValueError("Expanded table header missing")
        else:
            kind = "headerless_csv"
            rows = list(csv.reader(io.StringIO(text), strict=True))
        for row in rows:
            if not isinstance(row, (list, tuple)) or len(row) != 7 or not RULE.fullmatch(str(row[0]).strip()):
                raise ValueError("unknown rule or noncanonical row; wrapped ASCII cells require separate handling")
        if len(rows) != expected_count:
            raise ValueError("report count does not match tool log")
        return dict(format=kind, verified=True, parsed_count=len(rows), rows=rows, error=None)
    except (ValueError, csv.Error) as exc:
        return dict(format=kind, verified=False, parsed_count=len(rows), rows=[], error=str(exc))


def extract_messages(log_text, source_text, source_path):
    """Bind locations only to the actual candidate; preserve duplicate occurrences."""
    lines = source_text.splitlines()
    rows = []
    seen = {}
    for log_line, line in enumerate(log_text.splitlines(), 1):
        match = MESSAGE.match(line)
        if not match:
            continue
        severity, code, message = match.groups()
        location = LOCATION.search(message)
        path, source_line = (location[1], int(location[2])) if location else (None, None)
        bound = path == source_path and source_line is not None and 1 <= source_line <= len(lines)
        context = None
        if bound:
            context = [dict(line=n, text=lines[n - 1])
                       for n in range(max(1, source_line - 2), min(len(lines), source_line + 2) + 1)]
        key = (severity, code, message)
        if key in seen:
            rows[seen[key]]["occurrences"] += 1
            rows[seen[key]]["log_lines"].append(log_line)
            continue
        seen[key] = len(rows)
        rows.append(dict(severity=severity, code=code, message=message,
                         source_path=path, source_line=source_line, source_location_verified=bound,
                         context=context, occurrences=1, log_lines=[log_line]))
    return rows


def calibration(rows, configuration):
    selected = [r for r in rows if r["mode"] == "lint" and r["configuration"] == configuration]
    positives = [r for r in selected if r["role"] == "diagnostic_positive"]
    negatives = [r for r in selected if r["role"] == "diagnostic_negative"]
    verified = (len(positives) >= 2 and len(negatives) >= 1
                and all(r["tool_execution_valid"] and r.get("report_parse_verified") is True and len(r["linter_counts"]) == 1
                        and r["linter_counts"][0] > 0 for r in positives)
                and all(r["tool_execution_valid"] and r.get("report_parse_verified") is True and r["linter_counts"] == [0] for r in negatives))
    return dict(verified=verified, configuration=configuration,
                positive_counts={r["case"]: r["linter_counts"] for r in positives},
                negative_counts={r["case"]: r["linter_counts"] for r in negatives},
                reason="positive and negative controls passed" if verified else "diagnostic mechanism not established by both positive controls and clean guard")


def analyze(row, log_bytes, source_bytes, source_path, capability):
    if hashlib.sha256(log_bytes).hexdigest() != row["log_sha256"]:
        raise ValueError("log identity mismatch")
    if hashlib.sha256(source_bytes).hexdigest() != row["source_sha256"]:
        raise ValueError("source identity mismatch")
    if capability["configuration"] != row["configuration"]:
        raise ValueError("capability belongs to a different configuration")
    messages = extract_messages(log_bytes.decode(errors="replace"), source_bytes.decode(errors="replace"), source_path)
    if not row["tool_execution_valid"]:
        status = "tool_failed"
    elif row["mode"] != "lint":
        status = "synthesis_diagnostics_only"
    elif row.get("report_parse_verified") is not True:
        status = "lint_report_unverified"
    elif not capability["verified"]:
        status = "lint_unverified"
    elif row["linter_counts"] == [0]:
        status = "zero_lint_violations_functional_correctness_unknown"
    else:
        status = "lint_violations_require_specification_review"
    return dict(case=row["case"], configuration=row["configuration"], mode=row["mode"], status=status,
                lint_engine_verified=capability["verified"], messages=messages,
                unique_messages=len(messages), raw_message_occurrences=sum(x["occurrences"] for x in messages),
                bound_unique_messages=sum(x["source_location_verified"] for x in messages),
                source_sha256=row["source_sha256"], log_sha256=row["log_sha256"],
                automatic_repair_authorized=False, functional_correctness="unknown")
