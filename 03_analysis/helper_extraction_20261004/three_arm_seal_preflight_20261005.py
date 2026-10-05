"""AMD U15: replay existing private U14 receipts; zero inference and EDA.

Historical bytes are copied into a fresh directory, never edited in place.
Constructed queue rows test dispatch bookkeeping only, not solver performance.
"""
import argparse
import copy
import json
from pathlib import Path
import time
import zipfile

import three_arm_queue_20261005 as queue
from three_arm_queue_20261005 import official

ARCHIVE_SHA = '1a5b4d9794ea87110fa71ab3b20f62521d34b160431d1780eefd20347022c0c7'
PREFIX = 'results/sources/queues/paired/'


def preflight(args):
    resource = official.resource_module()
    resource.check_resource(args.resource_check, args.kit, first=True)
    assert official.sha(args.archive) == ARCHIVE_SHA
    out = args.out.resolve(); assert not out.exists(); out.mkdir(parents=True)
    started = time.monotonic(); checks = []; callbacks = []

    def blocked(label, call):
        before = len(callbacks)
        try:
            call()
        except (AssertionError, FileNotFoundError, zipfile.BadZipFile) as error:
            assert len(callbacks) == before
            checks.append(dict(control=label, passed=True, rejection=type(error).__name__))
        else:
            raise AssertionError('Accepted invalid state: '+label)

    # All six real historical solver/judge receipts, including each A/P/B arm.
    historical = []; removed_cache = 0
    with zipfile.ZipFile(args.archive) as z:
        assert len(z.namelist()) == len(set(z.namelist()))
        for index in range(6):
            stem = PREFIX+'row_'+str(index).zfill(6)+'/'
            target = out/'historical'/('row_'+str(index).zfill(6)); target.mkdir(parents=True)
            for name in z.namelist():
                if not name.startswith(stem) or name.endswith('/'):
                    continue
                relative = name[len(stem):]; path = target/relative
                assert not Path(relative).is_absolute() and '..' not in Path(relative).parts
                assert path.resolve().is_relative_to(target)
                path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(z.read(name))
            reservation = json.loads((target/'STARTED.json').read_text())
            row, plan_hash = reservation['row'], reservation['plan_sha256']
            receipt = queue.verify_terminal(target, row, plan_hash)
            terminal_sha = official.sha(target/'TERMINAL.json')
            seal = queue.seal_row(target, row, plan_hash)
            assert queue.seal_row(target, row, plan_hash) == seal
            for name in receipt['files']:
                if 'xsim.dir' in Path(name).parts:
                    path = target/name
                    assert path.resolve().is_relative_to(out)
                    path.unlink(); removed_cache += 1
            assert queue.verify_terminal(target, row, plan_hash) == receipt
            assert official.sha(target/'TERMINAL.json') == terminal_sha
            historical.append(dict(index=index, arm=row['arm'], level=receipt['level'],
                terminal_sha256=terminal_sha, seal_sha256=official.sha(target/'SEALED.json'),
                archive_sha256=seal['archive_sha256'], source_manifest_unchanged=True))
    assert removed_cache == 14 and [r['level'] for r in historical] == [3,3,3,3,0,3]
    checks.append(dict(control='six_historical_receipts_after_cache_removal', passed=True, removed_cache_files=14))

    # Exercise actual queue.advance recovery with constructed receipts only.
    sources = queue.prepare_sources(out/'sources')
    task = out/'constructed_input'; task.mkdir()
    (task/'prompt.txt').write_text('U15 queue durability control; not a natural model task.')
    tasks = [dict(dataset='constructed',task='control',family='constructed',use='development',
                  task_dir=str(task),hashes={'prompt.txt':official.sha(task/'prompt.txt')})]
    plan = queue.build_plan(tasks,1,sources,Path(official.__file__),args.kit,5,900)
    queue.save(out/'CONTROL_PLAN.json',plan)
    paired = Path(sources['root'])/'queues/paired'

    def execute(argv,row,folder):
        callbacks.append(row['key'])
        (folder/'artifact.bin').write_bytes(b'frozen synthetic durability control')
        return dict(complete=True, actual_calls=1, unconfirmed_calls=0, synthetic=True, real_model_calls=0,
                    files={n:official.sha(folder/n) for n in ['STARTED.json','artifact.bin']})

    queue.advance(plan,paired,args.resource_check,execute)
    first = paired/'row_000000'; row = plan['rows'][0]; plan_hash = queue.digest(plan)
    (first/'artifact.bin').unlink()
    for unused in range(2): queue.advance(plan,paired,args.resource_check,execute)
    done = queue.advance(plan,paired,args.resource_check,execute)
    assert done['complete'] and done['reserved_calls']==5 and len(callbacks)==3
    assert len(set(callbacks))==3
    checks.append(dict(control='resume_after_cleanup_without_duplicate_dispatch',passed=True,
                       synthetic_callbacks=3,conservative_reserved_calls=5))

    def check(): return queue.advance(plan,paired,args.resource_check,execute)
    # A remaining live copy must still agree with the canonical ZIP.
    artifact = first/'artifact.bin'; artifact.write_bytes(b'drift')
    blocked('live_artifact_drift',check); artifact.unlink()
    for name in ['EVIDENCE.zip','TERMINAL.json','STARTED.json','SEALED.json']:
        path=first/name; original=path.read_bytes()
        path.write_bytes(original+b'\n ' if name.endswith('.json') else original+b'drift')
        if name=='SEALED.json':
            value=json.loads(original);value['row_key']='f'*64;queue.save(path,value)
        blocked(name+'_drift',check); path.write_bytes(original)
    for name in ['EVIDENCE.zip.pending','SEALED.json.pending']:
        path=first/name; path.write_text('interrupted seal')
        blocked(name+'_interrupted',check); path.unlink()
    marker=first/'SEALED.json'; marker_bytes=marker.read_bytes();marker.unlink()
    blocked('archive_without_seal',check); marker.write_bytes(marker_bytes)
    archive=first/'EVIDENCE.zip'; archive_bytes=archive.read_bytes();archive.unlink()
    blocked('seal_without_archive',check);archive.write_bytes(archive_bytes)
    # Keep the outer hash consistent to test member validation independently.
    with zipfile.ZipFile(archive) as z: members={n:z.read(n) for n in z.namelist()}
    for label,items in [('missing_archive_member',[(n,b) for n,b in members.items() if n!='artifact.bin']),
                        ('corrupt_archive_member',[(n,b'drift' if n=='artifact.bin' else b) for n,b in members.items()])]:
        with zipfile.ZipFile(archive,'w') as z:
            for n,b in items:z.writestr(n,b)
        value=json.loads(marker_bytes);value['archive_sha256']=official.sha(archive);queue.save(marker,value)
        blocked(label,check)
        archive.write_bytes(archive_bytes);marker.write_bytes(marker_bytes)
    terminal=first/'TERMINAL.json'; original=terminal.read_bytes(); value=json.loads(original)
    value['files']['../outside']='0'*64;queue.save(terminal,value)
    blocked('outside_row_path',check);terminal.write_bytes(original)
    assert check()['complete'] and len(callbacks)==3
    checks.append(dict(control='valid_recovery_after_restoring_negative_controls',passed=True))

    # Missing terminal remains unknown; an archive cannot justify a retry.
    terminal.unlink(); blocked('missing_terminal_never_retried',check);terminal.write_bytes(original)
    resource.check_resource(args.resource_check,args.kit)
    result=dict(schema='three_arm_seal_U15_v1',complete=True,passed=True,controls=checks,
        historical_rows=historical,source_archive_sha256=ARCHIVE_SHA,control_count=len(checks),
        real_model_calls=0,eda_calls=0,synthetic_callbacks=len(callbacks),elapsed_s=time.monotonic()-started,
        source_sha256=official.sha(__file__),queue_sha256=official.sha(queue.__file__),
        full_batch=False,independent_natural_tasks=0,adoption=False,
        limits=['Replay and persistence controls only; no new model or grading results.',
                'Seals detect accidental drift; they are not cryptographic authentication against a malicious writer.',
                'Private ZIPs must not be published. Remote duplication and capacity planning remain external requirements.'])
    queue.save(out/'RESULTS.json',result)
    print(json.dumps(result),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    for name in ['archive','kit','out','resource-check']:parser.add_argument('--'+name,type=Path,required=True)
    preflight(parser.parse_args())
