"""Adversarial FAKE route/native/archive controls, never real quality evidence."""
import copy
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import tempfile
import types
import unittest
import zipfile

import audit
import synthesis
OBSERVATION='FAKE incomplete onehot semantics'
def waveform(extra=None):
    from native_material_fixture import fixture
    return fixture(pattern='101',cycles=2,module='SyntheticPipeline')[0] if extra is None else extra

ROOT = Path(__file__).resolve().parent


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8", newline="\n")


def fake_run(root, rc=0, interface="", crlf=False):
    run = root/"run"; run.mkdir()
    for name in ("synthesis.py", "reserved_keywords.py"):
        (run/name).write_bytes((ROOT/name).read_bytes())
    (run/"baseline_worker.py").write_bytes(b"FAKE baseline identity only; not executed\n")
    work = run/"results/samples/P/Synthetic/worker"; work.mkdir(parents=True)
    prompt = waveform().replace('\n','\r\n') if crlf else waveform()
    recipe = synthesis.synthesize(prompt,interface)
    (work/"prompt_only").mkdir()
    (work/"prompt_only/prompt.txt").write_text(prompt, encoding="utf-8", newline="\n")
    if interface:(work/"prompt_only/interface.txt").write_bytes(interface.encode())
    (work/"solution.v").write_bytes(recipe["rtl"].encode())
    (work/"emission").mkdir()
    (work/"emission/emitted.sv").write_bytes(recipe["rtl"].encode())
    save(work/"emission/contract.json", recipe["contract"])
    save(work/"synthesis_receipt.json", recipe)
    save(work/"requests.json", [])
    route = dict(schema=audit.ROUTE_SCHEMA, route="mechanical_serial_timer", outer_arm="P",
                 prompt_sha256=recipe["prompt_sha256"], interface_sha256=recipe["interface_sha256"],
                 interface_present=bool(interface), baseline_worker_sha256=audit.sha(run/"baseline_worker.py"),
                 synthesis_source_sha256=audit.sha(run/"synthesis.py"),
                 generated_solution_sha256=recipe["rtl_sha256"])
    save(work/"generation_route.json", route)
    compile_dir = work/"work/mechanical_compile-0"; compile_dir.mkdir(parents=True)
    (compile_dir/"candidate.sv").write_bytes(recipe["rtl"].encode())
    evidence = work/"native_receipts/0"; evidence.mkdir(parents=True)
    for name in ("source_before.sv", "source_after.sv"):
        (evidence/name).write_bytes(recipe["rtl"].encode())
    stdout = "FAKE normal compiler receipt\n" if rc == 0 else "ERROR: [FAKE] ordinary candidate syntax rejection\n"
    log = evidence/"owned_compile.log"; log.write_text(stdout, encoding="utf-8", newline="\n")
    cloud = PurePosixPath("/synthetic/table/run/results/samples/P/Synthetic/worker")
    command = dict(argv=["/workspace/AMD/2026.1/Vivado/bin/xvlog", "--sv",
                         str(cloud/"work/mechanical_compile-0/candidate.sv")],
                   timeout=False, launch_error=None, returncode=rc, remaining_live_group=[],
                   elapsed_s=.1, log_sha256=audit.sha(log), log_bytes=log.stat().st_size,
                   source_sha256=recipe["rtl_sha256"], source_before_sha256=recipe["rtl_sha256"],
                   source_after_sha256=recipe["rtl_sha256"])
    save(evidence/"command.json", command)
    excerpt = "\n".join(line for line in stdout.splitlines()
                        if re.search("ERROR|WARNING|FATAL", line))[:2048] or stdout[-2048:]
    trace = [
        dict(ts=0, tool="serial_timer_generation", round=0, route="mechanical_serial_timer",
             actual_model_requests=0, emitted_sha256=recipe["rtl_sha256"],
             contract_sha256=recipe["contract_sha256"]),
        dict(ts=1, tool="lint_start", round=0, generation_route="mechanical_serial_timer"),
        dict(ts=2, tool="lint", round=0, generation_route="mechanical_serial_timer", rc=rc,
             excerpt=excerpt, receipt_sha256=audit.sha(evidence/"command.json")),
        dict(ts=3, tool="native_feedback", round=0, generation_route="mechanical_serial_timer",
             text="", excerpt="", repair_requested=False),
    ]
    (work/"trace.jsonl").write_text("".join(json.dumps(event)+"\n" for event in trace),
                                  encoding="utf-8", newline="\n")
    save(work/"native_feedback.json",
         dict(text="", repair_requested=False, native_compile_returncode=rc))
    save(work/"worker_result.json",
         dict(complete=True, arm="P", requests=0, actual_model_requests=0,
              received_model_responses=0, generation_route="mechanical_serial_timer",
              elapsed_s=.1, solution_sha256=recipe["rtl_sha256"]))
    row = dict(arm="P", solve_deadline_reached=False, actual_model_requests=0,
               received_model_responses=0)
    return run, work, prompt, recipe, cloud, row


def fake_model(work, prompt):
    generation, repair = "FAKE generation skill", "FAKE repair skill"
    payload = dict(model="FAKE model", max_tokens=8192, temperature=0, top_p=1,
                   messages=[dict(role="system", content=generation),
                             dict(role="user", content=prompt)])
    response = dict(id="FAKE response id", usage=dict(prompt_tokens=4, completion_tokens=3),
                    choices=[dict(finish_reason="stop", message=dict(content="FAKE RTL"))])
    folder = work/"requests/0"
    save(folder/"request.json", payload); save(folder/"response.json", response)
    entry = dict(index=0, replayed=False, response_received=True,
                 request_sha256=audit.sha(folder/"request.json"),
                 response_sha256=audit.sha(folder/"response.json"), finish_reason="stop",
                 response_id=response["id"], usage=response["usage"])
    save(work/"requests.json", [entry])
    trace = [
        dict(tool="agent_meta", repairs=1,
             skill_sha256=hashlib.sha256(generation.encode()).hexdigest(),
             repair_skill_sha256=hashlib.sha256(repair.encode()).hexdigest()),
        dict(tool="llm_start", round=0),
        dict(tool="llm", round=0, finish="stop", tokens_in=4, tokens_out=3),
    ]
    (work/"trace.jsonl").write_text("".join(json.dumps(event)+"\n" for event in trace),
                                  encoding="utf-8", newline="\n")
    return dict(actual_model_requests=1, received_model_responses=1), dict(model="FAKE model"), generation, repair


class AuditControls(unittest.TestCase):
    def mechanical(self, values, parser=None, probe=None):
        run, work, prompt, recipe, cloud, row = values
        route, stored = audit.bound_route(work, run, "P", prompt, (work/"prompt_only/interface.txt").read_bytes().decode() if (work/"prompt_only/interface.txt").exists() else "", (work/"prompt_only/interface.txt").exists(), synthesis)
        self.assertEqual(route["route"], "mechanical_serial_timer")
        return audit.mechanical_provenance(
            work, run, "Synthetic", row, stored, cloud,
            types.SimpleNamespace(ENVIRONMENT_ERROR=re.compile("FAKE ENVIRONMENT FAILURE")),
            parser or types.SimpleNamespace(parse=lambda _: dict(status="unsupported")),
            probe or (lambda *_: self.fail("Unexpected fake semantic probe")))

    def test_exact_mechanical_zero_request_and_normal_compile_rejection_are_valid(self):
        for rc in (0, 1):
            with self.subTest(rc=rc), tempfile.TemporaryDirectory() as td:
                bound = self.mechanical(fake_run(Path(td), rc=rc))
                self.assertTrue(bound["mechanical_recipe_bound"])
                self.assertTrue(bound["empty_model_artifacts_bound"])
                self.assertTrue(bound["native_execution_bound"])
                self.assertIsNone(bound["first_reply_sha256"])

    def test_bound_semantic_mismatch_stays_a_valid_negative_recipe(self):
        with tempfile.TemporaryDirectory() as td:
            values = fake_run(Path(td)); run, work, *_ = values
            contract = dict(status="supported", checks=1)
            save(work/"map_check_0/contract.json", contract)
            (work/"map_check_0/input.sv").write_bytes((work/"solution.v").read_bytes())
            save(work/"map_check_0/feedback.json", dict(text="FAKE verified counterexample"))
            feedback = audit.read(work/"native_feedback.json"); feedback["text"] = "FAKE verified counterexample"
            save(work/"native_feedback.json", feedback)
            trace = [json.loads(line) for line in (work/"trace.jsonl").read_text().splitlines()]
            trace[-1]["text"] = trace[-1]["excerpt"] = feedback["text"]
            (work/"trace.jsonl").write_text("".join(json.dumps(e)+"\n" for e in trace), encoding="utf-8")
            bound = self.mechanical(values, types.SimpleNamespace(parse=lambda _: contract),
                                    lambda *_: dict(mismatches=1))
            self.assertTrue(bound["native_execution_bound"])

    def test_route_schema_arm_source_input_and_recipe_tamper_rejected(self):
        changes = [
            ("schema", "FAKE unrecognized schema"), ("outer_arm", "C"),
            ("prompt_sha256", "0"*64), ("interface_sha256", "0"*64),
            ("interface_present", True), ("synthesis_source_sha256", "0"*64),
            ("generated_solution_sha256", "0"*64), ("route", "model"),
        ]
        for field, value in changes:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as td:
                run, work, prompt, *_ = fake_run(Path(td))
                route = audit.read(work/"generation_route.json"); route[field] = value
                save(work/"generation_route.json", route)
                with self.assertRaises(AssertionError):
                    audit.bound_route(work, run, "P", prompt, "", False, synthesis)
        with tempfile.TemporaryDirectory() as td:
            run, work, prompt, *_ = fake_run(Path(td))
            recipe = audit.read(work/"synthesis_receipt.json"); recipe["contract"]["search_transitions"][0][0] = 99
            save(work/"synthesis_receipt.json", recipe)
            with self.assertRaises(AssertionError):
                audit.bound_route(work, run, "P", prompt, "", False, synthesis)

    def test_cannot_masquerade_observation_only_or_control_as_zero_call(self):
        with tempfile.TemporaryDirectory() as td:
            run, work, *_ = fake_run(Path(td))
            with self.assertRaises(AssertionError):
                audit.bound_route(work, run, "P", waveform(OBSERVATION), "", False, synthesis)
            with self.assertRaises(AssertionError):
                audit.bound_route(work, run, "C", waveform(), "", False, synthesis)

    def test_empty_journal_does_not_hide_request_response_or_llm_trace(self):
        for kind in ("request", "response", "directory", "trace"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as td:
                values = fake_run(Path(td)); work = values[1]
                if kind == "directory":
                    (work/"requests").mkdir()
                elif kind == "trace":
                    with (work/"trace.jsonl").open("a", encoding="utf-8") as file:
                        file.write(json.dumps(dict(tool="llm_start", round=0))+"\n")
                else:
                    save(work/f"unreported/{kind}.json", dict(fake=True))
                with self.assertRaises(AssertionError):
                    self.mechanical(values)

    def test_generated_final_and_physical_source_hashes_not_replaceable(self):
        for filename in ("solution.v", "emission/emitted.sv",
                         "native_receipts/0/source_after.sv", "work/mechanical_compile-0/candidate.sv"):
            with self.subTest(filename=filename), tempfile.TemporaryDirectory() as td:
                values = fake_run(Path(td)); work = values[1]
                (work/filename).write_bytes(b"FAKE replaced source\n")
                with self.assertRaises(AssertionError):
                    self.mechanical(values)

    def test_supervision_environment_wrong_command_and_physical_log_tamper_reject(self):
        for field, value in (("timeout", True), ("launch_error", "FAKE failure"),
                             ("remaining_live_group", [99999]), ("returncode", -9),
                             ("log_sha256", "0"*64), ("log_bytes", 0),
                             ("argv", ["/untrusted/xvlog", "--sv", "/fake/source"])):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as td:
                values = fake_run(Path(td)); work = values[1]; path = work/"native_receipts/0/command.json"
                command = audit.read(path); command[field] = value; save(path, command)
                with self.assertRaises(AssertionError):
                    self.mechanical(values)
        for stdout in ("FAKE ENVIRONMENT FAILURE\n", "Fatal: FAKE zero-code failure\n"):
            with self.subTest(stdout=stdout), tempfile.TemporaryDirectory() as td:
                values = fake_run(Path(td)); work = values[1]; folder = work/"native_receipts/0"
                (folder/"owned_compile.log").write_text(stdout, encoding="utf-8")
                command = audit.read(folder/"command.json")
                command["log_sha256"] = audit.sha(folder/"owned_compile.log")
                command["log_bytes"] = (folder/"owned_compile.log").stat().st_size
                save(folder/"command.json", command)
                with self.assertRaises(AssertionError):
                    self.mechanical(values)

    def test_model_route_keeps_real_lower_bound_and_physical_message_metadata(self):
        with tempfile.TemporaryDirectory() as td:
            work = Path(td); save(work/"requests.json", [])
            with self.assertRaises(AssertionError):
                audit.model_requests(work, dict(actual_model_requests=0, received_model_responses=0),
                                     dict(model="FAKE model"), "fake", "fake")
            row, spec, generation, repair = fake_model(work, "FAKE prompt")
            journal, body = audit.model_requests(work, row, spec, generation, repair)
            self.assertEqual(len(journal), 1)
            self.assertEqual(body["max_tokens"], 8192)
            save(work/"unreported/response.json", dict(fake=True))
            with self.assertRaises(AssertionError):
                audit.model_requests(work, row, spec, generation, repair)

    def test_model_injected_message_or_response_metadata_cannot_pass(self):
        for kind in ("third_message", "response_usage", "skill"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as td:
                work = Path(td); row, spec, generation, repair = fake_model(work, "FAKE prompt")
                if kind == "third_message":
                    payload = audit.read(work/"requests/0/request.json")
                    payload["messages"].append(dict(role="system", content="FAKE oracle injection"))
                    save(work/"requests/0/request.json", payload)
                    journal = audit.read(work/"requests.json")
                    journal[0]["request_sha256"] = audit.sha(work/"requests/0/request.json")
                    save(work/"requests.json", journal)
                elif kind == "response_usage":
                    journal = audit.read(work/"requests.json"); journal[0]["usage"]["completion_tokens"] = 999
                    save(work/"requests.json", journal)
                else:
                    generation = "FAKE altered skill"
                with self.assertRaises(AssertionError):
                    audit.model_requests(work, row, spec, generation, repair)

    def test_original_safe_archive_unpack_rejects_inventory_hash_and_path_attacks(self):
        shared = audit.shared_helper()
        for kind in ("valid", "hash", "inventory", "path", "duplicate"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as td:
                root = Path(td); archive = root/"fake.zip"; raw = b"FAKE archived input\n"
                member = "../escape" if kind == "path" else "run/FAKE.txt"
                expected = hashlib.sha256(raw).hexdigest()
                manifest = dict(files={member: "0"*64 if kind == "hash" else expected})
                with zipfile.ZipFile(archive, "w") as bundle:
                    bundle.writestr(member, raw)
                    if kind == "duplicate":
                        bundle.writestr(member, raw)
                    if kind == "inventory":
                        bundle.writestr("run/EXTRA.txt", raw)
                    bundle.writestr("ARCHIVE_MANIFEST.json", json.dumps(manifest))
                target = root/"unpacked"
                if kind == "valid":
                    shared.unpack(archive, target)
                    self.assertEqual((target/member).read_bytes(), raw)
                else:
                    with self.assertRaises(ValueError):
                        shared.unpack(archive, target)

    def test_all_29_protected_receipts_require_original109_and_complete_external_inventory(self):
        for attack in ('valid','extra_bound_root','old_count','sum_mismatch','tampered_gate','missing_gate','changed_anchor','omitted_anchor','bad_external_hash','rehashed_original_anchor'):
            with self.subTest(attack=attack),tempfile.TemporaryDirectory() as td:
                run=Path(td)
                base=(ROOT/'raw_evidence/IMMUTABLE_ORIGINAL109_CAPTURE.json').read_bytes()
                (run/'raw_evidence').mkdir();(run/'raw_evidence/IMMUTABLE_ORIGINAL109_CAPTURE.json').write_bytes(base)
                groups=json.loads(base)
                (run/'EXTERNAL_SOURCE_MANIFEST.json').write_bytes((ROOT/'EXTERNAL_SOURCE_MANIFEST.json').read_bytes())
                if attack=='extra_bound_root':
                    groups['groups']['FAKE-NEW']=dict(cloud_root='/workspace/team/runs/FAKE/new',spec_sha256='c'*64,source_hashes={'new-source':'d'*64})
                    groups['source_assets']+=1
                spec=dict(protected_group_count=len(groups['groups']),protected_source_assets=groups['source_assets'],external_inventory_manifest_sha256=audit.sha(run/'EXTERNAL_SOURCE_MANIFEST.json'),expected_samples=14)
                identity=next(iter(groups['groups']));sources=groups['groups'][identity]['source_hashes'];name=next(iter(sources))
                if attack=='old_count':spec.update(protected_group_count=95,protected_source_assets=6516)
                if attack=='sum_mismatch':del sources[name]
                if attack=='changed_anchor':sources[name]='0'*64
                if attack=='omitted_anchor':sources['unrelated-same-count']=sources.pop(name)
                if attack=='bad_external_hash':spec['external_inventory_manifest_sha256']='0'*64
                if attack=='rehashed_original_anchor':
                    changed=json.loads(base);changed['groups'][identity]['source_hashes'][name]='0'*64
                    save(run/'raw_evidence/IMMUTABLE_ORIGINAL109_CAPTURE.json',changed)
                save(run/'raw_evidence/PROTECTED_GROUPS_CAPTURE.json',groups)
                expected={n:dict(spec_sha256=item['spec_sha256'],source_hashes=item['source_hashes'],source_assets=len(item['source_hashes'])) for n,item in groups['groups'].items()}
                for i in range(29):save(run/'results/protected_source_checks'/(str(i).zfill(3)+'.json'),dict(index=i,schema='semantic_edge_protected_source_check_v1',verified=True,groups=expected,source_assets=groups['source_assets'],model_calls=0,eda_calls=0))
                if attack=='tampered_gate':
                    path=run/'results/protected_source_checks/028.json';row=audit.read(path);row['source_assets']=6516;save(path,row)
                if attack=='missing_gate':(run/'results/protected_source_checks/028.json').unlink()
                if attack in ('valid','extra_bound_root'):audit.protected_receipts(run,spec)
                else:
                    with self.assertRaises(AssertionError):audit.protected_receipts(run,spec)

    def test_matching_interface_raw_CRLF_recipe_is_independently_bound(self):
        from native_material_fixture import fixture
        for crlf in (False,True):
            with self.subTest(crlf=crlf),tempfile.TemporaryDirectory() as td:
                interface=fixture(module='SyntheticPipeline')[1]
                if crlf:interface=interface.replace('\n','\r\n')
                values=fake_run(Path(td),interface=interface,crlf=crlf)
                self.assertTrue(self.mechanical(values)['mechanical_recipe_bound'])
                path=values[1]/'prompt_only/interface.txt';path.write_bytes(path.read_bytes()+b'FAKE interface mutation')
                with self.assertRaises(AssertionError):self.mechanical(values)



if __name__ == "__main__":
    unittest.main()
