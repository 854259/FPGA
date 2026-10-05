"""Read-only all302 prompt-only dispatch inventory: 0 model, 0 EDA, no score.

Only public input.prompt is passed into the new parser. IDs identify private
bindings after dispatch; neither IDs nor hidden fields decide support.
"""
import argparse
import collections
import hashlib
import json
from pathlib import Path

import native_reset_contract as native


ROOT = Path(__file__).resolve().parent
DATASET_SHA = "cbcd81295561ebb16e4d857e096f4d9908d042c33aff3b58abf236e868411857"
RUN = "10501050105010501050105010501050"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def save(path, data):
    path.write_bytes((json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object field")
        result[key] = value
    return result


def schedule_binding(c):
    """Pure schedule and two-actual-output transport check; no RTL is executed."""
    native._validate(c)
    rows = c["observations"]
    previous_data = 0
    input_assignments = 0
    actual_data_changes = 0
    for row in rows:
        if "input" in row["changes"]:
            input_assignments += 1
            if row["clock"] != 0:
                raise ValueError("data assigned while clock is high")
        if row["input"] != previous_data:
            actual_data_changes += 1
            if row["clock"] != 0:
                raise ValueError("data changed while clock is high")
        previous_data = row["input"]
        if type(row["expected_rising"]) is not int or type(row["expected_falling"]) is not int:
            raise ValueError("both scalar expected outputs required")
    tb = native.render_tb(c, RUN)
    if tb.count('$display("NRC_OBS ') != c["checks"]:
        raise ValueError("generated TB lost observations")
    # Synthetic passing sentinel verifies full output-value retention only.
    lines = [f'NRC_BEGIN {native._prefix(c, RUN)} observations={c["checks"]}']
    for row in rows:
        lines.append(native._observation_prefix(row) +
                     f' observed_rising={row["expected_rising"]} observed_falling={row["expected_falling"]}')
    lines.append(f'NRC_END {native._prefix(c, RUN)} observations={c["checks"]} mismatches=0')
    parsed = native.observations("\n".join(lines) + "\n", c, RUN)
    if len(parsed["observations"]) != c["checks"] or any(
            type(row.get("observed_rising")) is not str or type(row.get("observed_falling")) is not str
            for row in parsed["observations"]):
        raise ValueError("two actual output values were not retained per observation")
    return dict(observations=c["checks"], retained_scalar_actual_values=2 * c["checks"],
                data_assignments=input_assignments, actual_data_changes=actual_data_changes,
                all_data_assignments_clock_low=True, all_data_changes_clock_low=True,
                both_actual_outputs_retained=True,
                observation_plan_sha256=sha(json.dumps(rows, sort_keys=True).encode("utf-8")),
                generated_tb_sha256=sha(tb.encode("utf-8")),
                check_scope="pure schedule and synthetic output transport; no native compilation/execution")


def inspect_records(records, parse_fn=native.parse):
    """Metadata records never enter parse_fn; it receives exactly one prompt str."""
    bindings = []
    for index, record in enumerate(records):
        prompt = record["input"]["prompt"]
        if type(prompt) is not str:
            raise ValueError("public input.prompt must be a string")
        result = parse_fn(prompt)
        if result.get("status") not in ("supported", "abstain", "skip"):
            raise ValueError("invalid dispatch result")
        if result.get("prompt_sha256") != sha(prompt.encode("utf-8")):
            raise ValueError("dispatch result is bound to a different prompt")
        binding = dict(index=index, record_id=record["id"], prompt_sha256=sha(prompt.encode("utf-8")),
                       prompt_characters=len(prompt), status=result["status"],
                       reason=result.get("reason"), support_decision_inputs=["input.prompt"])
        if result["status"] == "supported":
            binding.update(module=result["module"], roles=result["roles"],
                           **schedule_binding(result))
        bindings.append(binding)
    return bindings


def main(dataset):
    data = dataset.read_bytes()
    if sha(data) != DATASET_SHA:
        raise ValueError("original all302 dataset SHA mismatch")
    source_lines = data.decode("utf-8").splitlines()
    records = [json.loads(line, object_pairs_hook=unique_object) for line in source_lines]
    if len(records) != 302 or len({record["id"] for record in records}) != 302:
        raise ValueError("all302 count or unique binding mismatch")
    bindings = inspect_records(records)
    for binding, line in zip(bindings, source_lines):
        binding["record_line_sha256"] = sha(line.encode("utf-8"))
    counts = collections.Counter(binding["status"] for binding in bindings)
    raw = ROOT / "raw_evidence"
    raw.mkdir(exist_ok=True)
    private = raw / "ALL302_DISPATCH_BINDINGS.json"
    save(private, dict(dataset_sha256=sha(data), synthetic_only=True,
                       actual_model_calls=0, actual_eda_calls=0,
                       independent_quality_admitted=0, quality_qualification=False,
                       source_sha256=sha((ROOT / "native_reset_contract.py").read_bytes()),
                       support_decision_inputs=["input.prompt"], bindings=bindings))
    # Public output contains aggregate counts/source hashes/native role bindings,
    # not record IDs, per-prompt hashes, raw prompts, context, harness or answers.
    public = dict(records=len(bindings),
                  counts={status: counts[status] for status in ("supported", "abstain", "skip")},
                  dataset_sha256=sha(data),
                  source_sha256={name: sha((ROOT / name).read_bytes())
                                 for name in ("native_reset_contract.py", "inventory.py", "test_native_reset_contract.py")},
                  supported_native_bindings=[dict(module=b["module"], roles=b["roles"])
                                             for b in bindings if b["status"] == "supported"],
                  actual_model_calls=0, actual_eda_calls=0, actual_fifo_submitted=False,
                  independent_quality_admitted=0, quality_qualification=False, adoption=False,
                  scope="prompt-only parser coverage and pure schedule/transport; no302 model or generalization score")
    save(ROOT / "INVENTORY.json", public)
    print(json.dumps(public, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    # This is the same original data file used by natural_input_adapter inventory.
    parser.add_argument("--dataset", type=Path,
                        default=ROOT.parent / "natural_harness_calibration_20261005/raw_evidence/ORIGINAL_DATASET.jsonl")
    main(parser.parse_args().dataset)
