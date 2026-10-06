"""AMD-only metadata admission probe; never imports the downloaded verifier."""
import argparse
import ast
import hashlib
import json
import re
import time
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Sequence

def inventory_metadata(args, started):
    """Inventory Git metadata only; never open a task, reference or result body."""
    if sys.platform != "linux":
        raise ValueError("AMD execution required")
    raw_plan = args.inventory_plan.read_bytes()
    if hashlib.sha256(raw_plan).hexdigest() != args.inventory_plan_sha256:
        raise ValueError("inventory plan drift")
    plan = json.loads(raw_plan)
    if hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != plan["source_sha256"]:
        raise ValueError("inventory source drift")
    raw = args.git_tree.read_bytes()
    if hashlib.sha256(raw).hexdigest() != plan["git_tree_sha256"]:
        raise ValueError("Git metadata drift")
    tree = json.loads(raw)
    if tree.get("truncated") is not False or tree.get("sha") != plan["upstream_commit"]:
        raise ValueError("incomplete or wrong upstream tree")
    paths = [row["path"] for row in tree["tree"]]
    if len(paths) != len(set(paths)):
        raise ValueError("duplicate Git paths")
    for row in tree["tree"]:
        if (row["path"].startswith("/") or ".." in row["path"].split("/")
                or not re.fullmatch(r"[0-9a-f]{40}", row["sha"])):
            raise ValueError("invalid Git metadata")
    blobs = [row for row in tree["tree"] if row["type"] == "blob"]
    prompts = [row for row in blobs if row["path"].startswith("Src/")
               and "/des/" in row["path"] and row["path"].endswith("/description.txt")]
    references = [row for row in blobs if row["path"].startswith("Des/")
                  and row["path"].endswith("/description.txt")]
    families = plan["family_roots"]  # Declared repository families, never task-ID exceptions.
    rows = []
    family_counts = {}
    for prompt in sorted(prompts, key=lambda row: row["path"]):
        family = prompt["path"].split("/")[1]
        if family not in families:
            raise ValueError("undeclared source family")
        family_counts[family] = family_counts.get(family, 0) + 1
        # Content-addressed pairing also exposes aliases; do not guess module names.
        matches = [row for row in references
                   if row["path"].split("/")[1] == families[family]
                   and row["sha"] == prompt["sha"] and row["size"] == prompt["size"]]
        assets = []
        if len(matches) == 1:
            directory = matches[0]["path"].rsplit("/", 1)[0] + "/"
            assets = [row for row in blobs if row["path"].startswith(directory)
                      and row["path"].lower().endswith((".v", ".sv", ".vh", ".svh"))]
        upstream = [row for row in blobs if row["path"].startswith("Src/"+family+"/")
                    and "/des/" not in row["path"]]
        asset_rows = [dict(path=a["path"], git_blob=a["sha"], bytes=a["size"],
                           upstream_same_blob_paths=[u["path"] for u in upstream
                                                     if u["sha"] == a["sha"]]) for a in assets]
        rows.append(dict(source_prompt_path=prompt["path"], family=family,
                         prompt_git_blob=prompt["sha"], description_bytes=prompt["size"],
                         matching_reference_prompt_paths=[m["path"] for m in matches],
                         reference_directory_rtl_assets=asset_rows,
                         pairing_unique=len(matches) == 1,
                         declared_license=plan["declared_family_license"][family],
                         contract_verified=False, dependencies_verified=False,
                         reference_trust_verified=False, independent_admitted=False))
    if len(rows) != plan["expected_tasks"] or family_counts != plan["expected_family_counts"]:
        raise ValueError("declared task/family count mismatch")
    report = dict(schema="source_contract_metadata_20261006_v1", complete=True,
                  source_sha256=plan["source_sha256"], upstream_commit=tree["sha"],
                  git_tree_sha256=plan["git_tree_sha256"], tree_entries=len(paths),
                  task_count=len(rows), family_counts=family_counts,
                  reference_description_count=len(references),
                  unique_description_blobs=len({r["prompt_git_blob"] for r in rows}),
                  unique_pairs=sum(r["pairing_unique"] for r in rows),
                  rows_with_no_rtl_assets=sum(not r["reference_directory_rtl_assets"] for r in rows),
                  rtl_assets=sum(len(r["reference_directory_rtl_assets"]) for r in rows),
                  assets_without_same_blob_upstream=sum(not a["upstream_same_blob_paths"]
                      for r in rows for a in r["reference_directory_rtl_assets"]),
                  task_rows=rows, model_calls=0, compiler_calls=0, simulator_calls=0,
                  task_prompts_or_reference_bodies_opened=False,
                  result_bodies_opened=False, upstream_code_executed=False,
                  team_wide_exposure="unknown", training_exposure="unknown",
                  independent_admitted=0, effective_independent_family_n=None,
                  full_batch_complete=False,
                  evidence_limit="Git-declared paths/blob identities only, not body verification or correctness. "
                    "No RTL-versus-testbench distinction, interface inference or dependency completeness from filenames.",
                  decision="Use inventory to freeze evaluation-side contract/source checks. "
                    "Retain every missing/ambiguous record; no model run, task selection or source stubbing.",
                  elapsed_s=time.monotonic()-started)
    args.out.mkdir(parents=True, exist_ok=False)
    (args.out / "RESULT.json").write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps({k: v for k, v in report.items() if k != "task_rows"}))


def body_provenance(args, started):
    """Private evaluator-only mechanical source audit; never executes corpus code."""
    if sys.platform != "linux":
        raise ValueError("AMD execution required")
    plan_raw = args.inventory_plan.read_bytes()
    if hashlib.sha256(plan_raw).hexdigest() != args.inventory_plan_sha256:
        raise ValueError("body audit plan drift")
    plan = json.loads(plan_raw)
    for path, expected in [
        (Path(__file__), plan["source_sha256"]),
        (args.body_manifest, plan["body_manifest_sha256"]),
        (args.body_inventory, plan["inventory_sha256"]),
    ]:
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError("body audit frozen input drift")
    manifest = json.loads(args.body_manifest.read_text())
    inventory = json.loads(args.body_inventory.read_text())
    if (manifest["upstream_commit"] != plan["upstream_commit"]
            or inventory["upstream_commit"] != plan["upstream_commit"]
            or len(inventory["task_rows"]) != 64
            or len(manifest["files"]) != plan["expected_files"]
            or len(manifest["blobs"]) != plan["expected_blobs"]):
        raise ValueError("body audit scope drift")

    # Preserve string literals and line structure. This is not a Verilog parser.
    comments = re.compile(r'"(?:\\.|[^"\\])*"|//[^\r\n]*|/\*[\s\S]*?\*/')
    def without_comments(text):
        return comments.sub(lambda m: re.sub(r"[^\r\n]", " ", m[0])
                            if m[0].startswith(("//", "/*")) else m[0], text)
    controls = [
        ('module x; // module fake;\nendmodule', 'module x;\nendmodule'),
        ('"//not a comment" /* hidden */', '"//not a comment"'),
        (chr(96) + 'include "a.vh"\n', chr(96) + 'include "a.vh"\n'),
    ]
    for source, expected in controls:
        if without_comments(source).split() != expected.split():
            raise ValueError("comment/string control failed")
    if without_comments('assign y = 0;') == without_comments('assign y = 1;'):
        raise ValueError("different logic collapsed")
    if without_comments('"/* kept */"') != '"/* kept */"':
        raise ValueError("string literal lost")

    blob_root = args.body_root.resolve()
    verified = {}
    for blob in manifest["blobs"]:
        ident = blob["git_blob"]
        if not re.fullmatch(r"[0-9a-f]{40}", ident) or ident in verified:
            raise ValueError("duplicate or unsafe body blob")
        path = blob_root / ident
        if path.is_symlink() or not path.is_file():
            raise ValueError("missing or linked body blob")
        raw = path.read_bytes()
        git_hash = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
        if len(raw) != blob["bytes"] or git_hash != ident:
            raise ValueError("source body Git identity drift")
        verified[ident] = dict(raw=raw, sha256=hashlib.sha256(raw).hexdigest())
    if {p.name for p in blob_root.iterdir()} != set(verified):
        raise ValueError("unfrozen file in body directory")
    files = {}
    for entry in manifest["files"]:
        name = entry["path"]
        if (name in files or name.startswith("/") or ".." in name.split("/")
                or entry["mode"] not in ("100644", "100755")
                or entry["sha"] not in verified):
            raise ValueError("unsafe or missing manifest entry")
        raw = verified[entry["sha"]]["raw"]
        if len(raw) != entry["size"]:
            raise ValueError("file size mismatch")
        # Latin1 is a lossless one-byte mapping; non-ASCII and NUL stay recorded.
        text = raw.decode("latin1").replace("\r\n", "\n").replace("\r", "\n")
        stripped = without_comments(text)
        rtl = name.lower().endswith((".v", ".sv", ".vh", ".svh"))
        modules = re.findall(r"\bmodule\s+(?:automatic\s+)?([A-Za-z_][A-Za-z0-9_$]*)", stripped) if rtl else []
        literal_includes = re.findall(r'(?m)^\s*' + chr(96) + r'include\s+"([^"\r\n]+)"', stripped) if rtl else []
        directive_count = len(re.findall(r"(?m)^\s*" + chr(96) + r"include\b", stripped)) if rtl else 0
        files[name] = dict(
            path=name, git_blob=entry["sha"], bytes=len(raw), sha256=verified[entry["sha"]]["sha256"],
            line_ending_normalized_sha256=hashlib.sha256(text.encode("latin1")).hexdigest(),
            comment_masked_sha256=hashlib.sha256(stripped.encode("latin1")).hexdigest(),
            rtl=rtl, lexical_modules=modules, literal_includes=literal_includes,
            nonliteral_include_count=directive_count-len(literal_includes),
            nonascii_bytes=sum(b > 127 for b in raw), nul_bytes=raw.count(b"\0"),
            license_keywords=sorted(set(re.findall(r"\b(?:SPDX-License-Identifier|LGPL|GPL|BSD|MIT)\b", text, re.I))),
            initial_keyword_hint=bool(re.search(r"\binitial\b", stripped)) if rtl else False,
            simulation_system_task_hint=bool(re.search(r"\$(?:display|finish|stop|fatal|error)\b", stripped)) if rtl else False,
            syntax_or_elaboration_verified=False)
    task_rows = []
    classes = {}
    for task in inventory["task_rows"]:
        family = task["family"]
        original = [row for name, row in files.items()
                    if name.startswith("Src/" + family + "/") and "/des/" not in name and row["rtl"]]
        descriptions = [task["source_prompt_path"]] + task["matching_reference_prompt_paths"]
        if len(descriptions) != 2 or files[descriptions[0]]["git_blob"] != files[descriptions[1]]["git_blob"]:
            raise ValueError("description body pair drift")
        assets = []
        for asset in task["reference_directory_rtl_assets"]:
            row = files[asset["path"]]
            if row["git_blob"] != asset["git_blob"]:
                raise ValueError("reference asset body drift")
            matches = {}
            for key in ("git_blob", "line_ending_normalized_sha256", "comment_masked_sha256"):
                matches[key] = [a["path"] for a in original if a[key] == row[key]]
            category = next((key for key, paths in matches.items() if paths), "no_mechanical_identity")
            classes[category] = classes.get(category, 0) + 1
            includes = []
            for include in row["literal_includes"]:
                # Enumerate candidates only; basename matching is not elaboration.
                candidates = [a["path"] for a in original if Path(a["path"]).name == Path(include).name]
                includes.append(dict(include=include, original_family_basename_candidates=candidates,
                                     resolution_verified=False))
            same_module = [a["path"] for a in original
                           if row["lexical_modules"] and a["lexical_modules"] == row["lexical_modules"]]
            assets.append(dict(path=row["path"], mechanical_identity=category, matching_paths=matches,
                               same_lexical_module_list_paths=same_module, include_hints=includes,
                               nonliteral_include_count=row["nonliteral_include_count"],
                               reference_trust_verified=False))
        task_rows.append(dict(source_prompt_path=task["source_prompt_path"], family=family,
                              descriptions_body_verified=True, assets=assets,
                              full_contract_verified=False, dependencies_verified=False,
                              source_license_verified=False, independent_admitted=False))
    report = dict(schema="source_body_provenance_20261006_v1", complete=True,
                  upstream_commit=plan["upstream_commit"], source_sha256=plan["source_sha256"],
                  body_manifest_sha256=plan["body_manifest_sha256"],
                  inventory_sha256=plan["inventory_sha256"], controls_passed=5,
                  files_verified=len(files), unique_blobs_verified=len(verified),
                  tasks_retained=len(task_rows), reference_assets=sum(len(t["assets"]) for t in task_rows),
                  mechanical_identity_counts=classes,
                  reference_assets_with_literal_includes=sum(bool(a["include_hints"]) for t in task_rows for a in t["assets"]),
                  unresolved_literal_include_hints=sum(not a["original_family_basename_candidates"]
                      for t in task_rows for asset in t["assets"] for a in asset["include_hints"]),
                  nonliteral_include_count=sum(a["nonliteral_include_count"] for t in task_rows for a in t["assets"]),
                  files_with_nonascii_bytes=sum(bool(r["nonascii_bytes"]) for r in files.values()),
                  files_with_nul_bytes=sum(bool(r["nul_bytes"]) for r in files.values()),
                  task_rows=task_rows, file_rows=list(files.values()),
                  model_calls=0, compiler_calls=0, simulator_calls=0,
                  evaluation_side_body_access=True, generator_body_exposure=False,
                  result_bodies_opened=False, upstream_code_executed=False,
                  syntax_or_elaboration_verified=False, full_contracts_verified=0,
                  independent_admitted=0, effective_independent_family_n=None,
                  team_wide_exposure="unknown", training_exposure="unknown", full_batch_complete=False,
                  evidence_limit="Mechanical identities and lexical hints only. Comments, module names, license keywords "
                    "and basename candidates do not prove behavior, license permission or complete dependencies. "
                    "All 64 tasks retained; no support stubs or candidate changes.",
                  elapsed_s=time.monotonic()-started)
    args.out.mkdir(parents=True, exist_ok=False)
    (args.out / "RESULT.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k not in ("task_rows", "file_rows")}))


def main():
    ap = argparse.ArgumentParser()
    source = ap.add_mutually_exclusive_group(required=True)
    source.add_argument("--source", type=Path)
    source.add_argument("--git-tree", type=Path)
    source.add_argument("--body-manifest", type=Path)
    ap.add_argument("--body-root", type=Path)
    ap.add_argument("--body-inventory", type=Path)
    ap.add_argument("--inventory-plan", type=Path)
    ap.add_argument("--inventory-plan-sha256")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--resource-check", type=Path, required=True)
    args = ap.parse_args()
    started = time.monotonic()
    # The external resource guard owns slot/model/process checks; its receipt must exist.
    guard = json.loads(args.resource_check.read_text())
    if not guard:
        raise ValueError("missing resource admission")
    if args.body_manifest:
        if not all((args.body_root, args.body_inventory, args.inventory_plan,
                    args.inventory_plan_sha256, guard.get("resource_idle"))):
            raise ValueError("frozen body audit and idle resource admission required")
        return body_provenance(args, started)
    if args.git_tree:
        if not args.inventory_plan or not args.inventory_plan_sha256 or not guard.get("resource_idle"):
            raise ValueError("frozen inventory plan and idle resource admission required")
        return inventory_metadata(args, started)
    raw = args.source.read_bytes()
    expected = "396da5f709ecd2ec79272f788a089992f1863d2e9b78d6aa103c70f4e44cc4ed"
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError("upstream verifier drift")
    tree = ast.parse(raw)
    functions = {"strip_comments", "read_text", "tb_is_self_checking",
                 "sim_failure_lines", "pass_metrics"}
    constants = {"SIM_FAIL_RE", "NEGATED_FAIL_RE", "STRING_LITERAL_RE",
                 "SELF_CHECK_TOKEN_RE"}
    selected = []
    found = set()
    spans = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in functions:
            selected.append(node)
            found.add(node.name)
            spans[node.name] = [node.lineno, node.end_lineno]
        elif isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name) and target.id in constants:
                selected.append(node)
                found.add(target.id)
                spans[target.id] = [node.lineno, node.end_lineno]
    if found != functions | constants:
        raise ValueError("reviewed function or constant missing")
    # Only the nine reviewed nodes execute: no upstream imports, CLI, subprocess or model code.
    env = {"re": re, "Path": Path, "Sequence": Sequence,
           "CandidateResult": SimpleNamespace}
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(args.source), "exec"), env)
    args.out.mkdir(parents=True, exist_ok=False)
    cases = [
        ("literal_no_errors", 'module tb; initial begin $display("No errors"); $finish; end endmodule', True, False),
        ("plain_print", 'module tb; initial begin $display("done"); $finish; end endmodule', False, False),
        ("conditional_mismatch", 'module tb; reg a,b; initial if(a!==b) $display("MISMATCH"); endmodule', True, True),
        ("comment_only", 'module tb; // error mismatch\ninitial $finish; endmodule', False, False),
    ]
    rows = []
    for name, source, expected_classifier, has_comparison in cases:
        path = args.out / (name + ".sv")
        path.write_text(source)
        actual = env["tb_is_self_checking"](path)
        assert actual is expected_classifier, name
        rows.append(dict(control=name, classified_self_checking=actual,
                         has_functional_comparison=has_comparison,
                         sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    no_errors = env["sim_failure_lines"]("No errors\n")
    actual_error = env["sim_failure_lines"]("MISMATCH\n")
    assert no_errors == [] and actual_error == ["MISMATCH"]
    bounded = env["pass_metrics"]([SimpleNamespace(
        status="pass", flow="equivalence", proof_type="bounded_seq")])
    assert bounded["function_pass"] == 1 and bounded["equivalence_pass_full"] == 0
    report = dict(
        schema="source_metadata_admission_20261006", complete=True,
        source_commit="3eea482f20c048966d54ed04c418b85e5fd4d498",
        source_sha256=expected, source_spans=spans, controls=rows,
        literal_no_errors_failure_lines=no_errors,
        actual_mismatch_failure_lines=actual_error,
        bounded_row_aggregate=bounded,
        classifier_false_positive_demonstrated=True,
        full_benchmark_false_acceptance_measured=False,
        compiler_calls=0, simulator_calls=0, model_calls=0,
        upstream_imported=False, upstream_cli_executed=False,
        task_prompts_or_reference_bodies_opened=False,
        independent_admitted=0, full_batch_complete=False,
        decision="Do not admit generic function_pass as full-correctness evidence. "
                 "Keep source as a candidate only; no corpus expansion or new generation.",
        elapsed_s=time.monotonic()-started,
    )
    (args.out / "RESULT.json").write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps(report, ensure_ascii=False))

if __name__ == "__main__":
    main()
