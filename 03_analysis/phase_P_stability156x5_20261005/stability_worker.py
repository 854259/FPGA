"""Unchanged phaseP worker; only ledger event identities include the repeat."""
from pathlib import Path
import argparse,ctypes,json,sys
import worker


def repeat_append(original,repeat):
    assert type(repeat) is int and 1<=repeat<=5
    def append(ledger,kind,event_id,message,details):
        return original(ledger,kind,event_id+':repeat='+str(repeat),message,dict(details,repeat=repeat))
    return append


def main(args):
    assert args.arm=='P' and type(args.repeat) is int and 1<=args.repeat<=5
    assert sys.platform=='linux' and ctypes.CDLL(None,use_errno=True).prctl(36,1,0,0,0)==0
    spec=json.loads((worker.ROOT/'RUN_SPEC.json').read_bytes())
    for n,h in spec['source_hashes'].items():assert worker.sha(worker.ROOT/n)==h
    for n,h in spec['dependency_hashes'].items():assert worker.sha(Path(spec['dependencies_cloud'])/n)==h
    sys.path.insert(0,'/workspace/team/tools/task-fifo-20261004');import activity
    original=activity.append;activity.append=repeat_append(original,args.repeat)
    try:
        paired=worker.load('stability_owned',Path(spec['dependencies_cloud'])/'paired_checkpoint.py')
        worker.run_worker(args,paired)
    finally:activity.append=original


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for n in ['out','kit','resource-check']:p.add_argument('--'+n,type=Path,required=True)
    p.add_argument('--task',required=True);p.add_argument('--arm',choices=['P'],required=True)
    p.add_argument('--repeat',type=int,required=True)
    main(p.parse_args())
