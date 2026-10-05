"""One stdout presentation factor after a normal native compiler return."""
import hashlib
from pathlib import Path
import re
import priority

PRIORITY_SHA='9c820ad49aec9d2525093d1350ebf80c44b2671a5ea349f34faed5a5257d4edd'


def normal_return(result):
    assert type(result['returncode']) is int and result['returncode'] >= 0
    assert result['timeout'] is False and result['launch_error'] is None
    assert type(result['remaining_live_group']) is list and not result['remaining_live_group']


def presented(arm, stdout, result):
    assert arm in ('C','P') and isinstance(stdout,str)
    normal_return(result)
    return priority.prioritize_stdout(stdout) if arm=='P' and result['returncode']>0 else stdout


def feedback(stdout):
    # Exact original runtime selection. The production runtime remains untouched.
    return '\n'.join(s for s in stdout.splitlines() if re.search('ERROR|WARNING|FATAL',s))[:2048] or stdout[-2048:]


def text_sha(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def proof(arm, stdout, result):
    delivered=presented(arm,stdout,result)
    selected=feedback(delivered);original=feedback(stdout)
    return dict(schema='compile_diag_presentation_v1',arm=arm,priority_sha256=PRIORITY_SHA,
        native_normal_return=True,physical_returncode=result['returncode'],
        priority_invoked=arm=='P' and result['returncode']>0,
        stdout_changed=delivered!=stdout,feedback_changed=selected!=original,
        raw_stdout_text_sha256=text_sha(stdout),delivered_stdout_sha256=text_sha(delivered),
        runtime_feedback_sha256=text_sha(selected),original_runtime_feedback_sha256=text_sha(original),
        runtime_feedback_characters=len(selected),original_runtime_feedback_characters=len(original),
        original_runtime_cap=2048,model_calls=0,eda_calls=0)


def record(arm,result,log,evidence,save,sha):
    """Record the separate delivered text; never rewrite raw native evidence."""
    log,evidence=Path(log),Path(evidence)
    normal_return(result)
    assert sha(log)==result['log_sha256'] and log.stat().st_size==result['log_bytes']
    stdout=log.read_text(encoding='utf-8',errors='replace')
    delivered=presented(arm,stdout,result)
    (evidence/'delivered_stdout.txt').write_text(delivered,encoding='utf-8',newline='\n')
    (evidence/'runtime_feedback.txt').write_text(feedback(delivered),encoding='utf-8',newline='\n')
    save(evidence/'presentation.json',proof(arm,stdout,result))
    assert sha(log)==result['log_sha256'] and log.stat().st_size==result['log_bytes']
    return delivered


def verify(arm,result,evidence,sha,read):
    """Independently recompute presentation from the retained full native log."""
    evidence=Path(evidence);log=evidence/'owned_compile.log'
    normal_return(result)
    assert sha(log)==result['log_sha256'] and log.stat().st_size==result['log_bytes']
    stdout=log.read_text(encoding='utf-8',errors='replace')
    delivered=presented(arm,stdout,result)
    expected=proof(arm,stdout,result)
    assert read(evidence/'presentation.json')==expected
    assert (evidence/'delivered_stdout.txt').read_bytes()==delivered.encode('utf-8')
    assert (evidence/'runtime_feedback.txt').read_bytes()==feedback(delivered).encode('utf-8')
    return stdout,delivered,expected
