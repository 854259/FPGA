"""New comparison-route integration controls. Synthetic inputs; no model/EDA."""
import ast
import copy
import hashlib
import json
import math
from pathlib import Path
import re
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "reused"))
import composition
import fixture_support as fixture
from test_composition import table_prompt, vector_prompt


def functions(filename, names, extra=None):
    tree = ast.parse((ROOT / filename).read_bytes(), filename=filename)
    selected = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    assert {n.name for n in selected} == set(names)
    namespace = dict(Path=Path, hashlib=hashlib, json=json, re=re, math=math)
    namespace.update(extra or {})
    exec(compile(ast.Module(body=selected, type_ignores=[]), filename, "exec"), namespace)
    return namespace


class ComparisonRoutes(fixture.Fixture):
    def setUp(self):
        super().setUp()
        self.stage = functions("pilot.py", ["sha", "generation_binding", "frozen"],
                               dict(ROOT=self.owned, synthesis=composition))
        self.audit = functions("audit.py", ["sha", "read", "bound_route",
                               "mechanical_provenance", "audit"],
                               dict(ROUTE_SCHEMA="table_parent_vector_extension_generation_route_v1"))

    def fake_load(self, name, path):
        if Path(path).name == "map_runtime.py":
            return SimpleNamespace(vivado_tool=lambda _: "/workspace/AMD/2026.1/Vivado/bin/xvlog")
        return super().fake_load(name, path)

    def produce(self, prompt, arm):
        self.args.arm = arm
        self.args.out = self.root / ("sample_" + arm) / "worker"
        (self.source / "prompt.txt").write_bytes(prompt.encode())
        self.run_worker()
        if self.fallback_calls:
            journal = fixture.read(self.args.out / "requests.json")
            for item in journal:
                item.update(replayed=False, response_received=True)
            fixture.save(self.args.out / "requests.json", journal)

    def stage_bound(self, arm=None):
        return self.stage["generation_binding"](
            self.args.out, self.source, arm or self.args.arm,
            fixture.read(self.args.out / "requests.json"),
            dict(compiler_tools={"xvlog": {"path": "/workspace/AMD/2026.1/Vivado/bin/xvlog"}}))

    def audit_bound(self, arm=None):
        return self.audit["bound_route"](
            self.args.out, self.owned, arm or self.args.arm,
            (self.source / "prompt.txt").read_bytes().decode(),
            "", False, composition)

    def test_parent_C_and_P_are_independently_reconstructed(self):
        for arm in ("C", "P"):
            self.produce(table_prompt(), arm)
            bound = self.stage_bound()
            route, recipe = self.audit_bound()
            self.assertEqual(bound["generation_route"], "mechanical_table")
            self.assertEqual(route["route"], bound["generation_route"])
            self.assertEqual(recipe, composition.parent(table_prompt()))
            self.assertEqual(fixture.read(self.args.out / "requests.json"), [])
            row = dict(arm=arm, generation_route=route["route"],
                       solve_deadline_reached=False, actual_model_requests=0,
                       received_model_responses=0)
            evidence = self.audit["mechanical_provenance"](
                self.args.out, self.owned, self.task, row, recipe, self.args.out,
                SimpleNamespace(ENVIRONMENT_ERROR=re.compile("FAKE_ENVIRONMENT_BROKEN")),
                SimpleNamespace(parse=lambda _: {"status": "skip"}),
                lambda *args: self.fail("Unexpected native probe"))
            self.assertTrue(evidence["mechanical_recipe_bound"])

    def test_only_P_vector_is_mechanical_and_C_keeps_original_model(self):
        self.produce(vector_prompt(), "C")
        self.assertEqual(self.stage_bound()["generation_route"], "model")
        self.assertEqual(self.audit_bound()[0]["route"], "model")
        self.args.out = self.root / "unused"
        self.produce(vector_prompt(), "P")
        bound = self.stage_bound()
        route, recipe = self.audit_bound()
        self.assertEqual(bound["generation_route"], "mechanical_vector")
        row = dict(arm="P", generation_route=route["route"], solve_deadline_reached=False,
                   actual_model_requests=0, received_model_responses=0)
        self.audit["mechanical_provenance"](
            self.args.out, self.owned, self.task, row, recipe, self.args.out,
            SimpleNamespace(ENVIRONMENT_ERROR=re.compile("FAKE_ENVIRONMENT_BROKEN")),
            SimpleNamespace(parse=lambda _: {"status": "skip"}),
            lambda *args: self.fail("Unexpected native probe"))

    def test_P_vector_cannot_be_relabelled_as_C(self):
        self.produce(vector_prompt(), "P")
        for path in ("generation_route.json", "worker_result.json"):
            data = fixture.read(self.args.out / path)
            data["outer_arm" if path.startswith("generation") else "arm"] = "C"
            fixture.save(self.args.out / path, data)
        with self.assertRaises(AssertionError):
            self.stage_bound("C")
        with self.assertRaises(AssertionError):
            self.audit_bound("C")

    def test_C_parent_receipt_cannot_be_forged(self):
        self.produce(table_prompt(), "C")
        path = self.args.out / "synthesis_receipt.json"
        receipt = fixture.read(path)
        receipt["selected_provider"] = "vector"
        fixture.save(path, receipt)
        with self.assertRaises(AssertionError):
            self.stage_bound()
        with self.assertRaises(AssertionError):
            self.audit_bound()

    def test_C_zero_route_rejects_hidden_model_and_contract_mutation(self):
        self.produce(table_prompt(), "C")
        (self.args.out / "requests").mkdir()
        with self.assertRaises(AssertionError):
            self.stage_bound()
        (self.args.out / "requests").rmdir()
        path = self.args.out / "emission/contract.json"
        fixture.save(path, {"forged": True})
        with self.assertRaises(AssertionError):
            self.stage_bound()

    def test_C_parent_binds_raw_input_and_rejects_extra_input(self):
        self.produce(table_prompt().replace("\n", "\r\n"), "C")
        self.stage_bound()
        (self.args.out / "prompt_only/extra.txt").write_text("unapproved")
        with self.assertRaises(AssertionError):
            self.stage_bound()

    def test_both_model_abstentions_reject_zero_calls(self):
        for arm in ("C", "P"):
            self.produce("Unsupported synthetic prompt.", arm)
            self.assertEqual(self.stage_bound()["generation_route"], "model")
            fixture.save(self.args.out / "requests.json", [])
            result = fixture.read(self.args.out / "worker_result.json")
            result.update(requests=0, actual_model_requests=0)
            fixture.save(self.args.out / "worker_result.json", result)
            with self.assertRaises(AssertionError):
                self.stage_bound()

    def test_paired_metrics_count_C_table_and_reject_false_zero(self):
        tasks = ["synthetic_" + str(i).zfill(3) for i in range(156)]
        plan = {t: {a: {"route": "model"} for a in ("C", "P")} for t in tasks}
        plan[tasks[0]] = {a: {"route": "mechanical_table"} for a in ("C", "P")}
        plan[tasks[1]]["P"] = {"route": "mechanical_vector"}
        ns = functions("metrics.py", ["order", "aggregate", "decision"], dict(
            TASKS=tasks, ARMS=["C", "P"], COEFFICIENTS={0: 0., 1: .2, 2: .7, 3: 1.},
            TARGETS=tasks[113:], GUARDS=tasks[:113], ADMISSION={"tasks": plan},
            EMIT_TASKS={"C": tasks[:1], "P": tasks[:2]}))
        rows = []
        for task, arm in ns["order"](tasks):
            route = plan[task][arm]["route"]
            mechanical = route != "model"
            rows.append(dict(task=task, arm=arm, generation_route=route,
                actual_model_requests=0 if mechanical else 1,
                received_model_responses=0 if mechanical else 1,
                solve_deadline_reached=False, solve_elapsed_s=1.,
                stage_generation_binding_verified=True, route_receipt_sha256="a"*64,
                synthesis_receipt_sha256="b"*64, solution_sha256="c"*64,
                producer_contract_sha256="d"*64 if mechanical else None,
                emitted_solution_sha256="c"*64 if mechanical else None,
                verdict=dict(task_id=task, tool_error=None, level=3, coefficient=1.)))
        scorer = SimpleNamespace(summarize=lambda _: dict(
            tasks=156, scored_tasks=156, tool_errors=0, samples_per_task=1,
            level_counts={"L3": 156}))
        result = ns["aggregate"](rows, tasks, scorer)
        self.assertEqual(result["requests_by_arm"], {"C": 155, "P": 154})
        self.assertEqual(result["samples_by_generation_route"]["C"]["mechanical_table"], 1)
        bad = copy.deepcopy(rows)
        next(r for r in bad if r["generation_route"] == "model")["actual_model_requests"] = 0
        with self.assertRaises(AssertionError):
            ns["aggregate"](bad, tasks, scorer)
        flags = dict(generation_route_bound=True, input_bytes_bound=True,
            source_hashes_bound=True, solution_bytes_bound=True, native_execution_bound=True,
            original_model_replay_bound=True, synthesis_abstention_bound=True,
            mechanical_recipe_bound=True, empty_model_artifacts_bound=True)
        provenance = [dict(task=r["task"], arm=r["arm"],
                           generation_route=r["generation_route"], **flags) for r in rows]
        next(p for p in provenance if p["arm"] == "C" and p["generation_route"] == "model")["synthesis_abstention_bound"] = False
        self.assertFalse(ns["decision"](result, provenance, rows)["full156_evidence_valid"])

    def test_scoring_and_complete_audit_entries_remain_closed(self):
        with self.assertRaisesRegex(RuntimeError, "pending"):
            self.stage["frozen"](self.kit)
        with self.assertRaisesRegex(RuntimeError, "not frozen"):
            self.audit["audit"](None, None, None)


if __name__ == "__main__":
    unittest.main(failfast=True, verbosity=2)
