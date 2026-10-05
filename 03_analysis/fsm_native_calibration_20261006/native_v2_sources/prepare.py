"""AMD-only packet preparation; creates no RUN_SPEC and runs no EDA/model."""
import argparse
import sys
from pathlib import Path

import calibration as c


def main(args):
    c.require(sys.platform == "linux", "AMD Linux execution only")
    root, cases = args.root.resolve(), args.case_root.resolve()
    c.require(cases.is_relative_to(root), "case packet must be inside future stage root")
    items = c.describe_cases(cases)
    prepared = root/"prepared_cases"
    prepared.mkdir(exist_ok=False)
    for item in items:
        folder = prepared/item["label"]
        folder.mkdir()
        (folder/"candidate.sv").write_bytes(item["source"].encode())
        (folder/"tb.sv").write_bytes(item["tb"].encode())
        c.save(folder/"expected_observations.json", item["expected_observations"])
    c.save(root/"CASE_PLAN_DRAFT.json", c.plan(items))
    c.save(root/"PREPARATION_RECEIPT_DRAFT.json", dict(
        schema="fsm_native_v2_packet_preparation_draft_v1",
        planned=c.PLANNED, plan_sha256=c.file_sha(root/"CASE_PLAN_DRAFT.json"),
        production_hashes=c.PRODUCTION_HASHES, case_root_relative=cases.relative_to(root).as_posix(),
        model_calls=0, native_calls=0, frozen=False, queued=False, native_qualified=False,
        note="Root must complete AMD pure/source review, freeze CASE_PLAN/RUN_SPEC and own guard before execution."))
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--case-root", type=Path, required=True)
    raise SystemExit(main(parser.parse_args()))
