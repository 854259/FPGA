"""Lossless public task/file boundary for independent research, no model or EDA IO."""
from pathlib import PurePosixPath
import hashlib
import json
import re

FORMAT = ('Return only a JSON object with exactly one key, "files". Its value must '
          'map every requested output path to the complete UTF-8 text for that file. '
          'Preserve the module names, ports, parameters and behavior required by the '
          'original prompt and public context. Do not rename modules to TopModule. '
          'Do not return extra files, prose, tests or a second candidate.')

def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()

def safe_path(path):
    if not isinstance(path,str) or not path or '\\' in path or ':' in path or any(ord(c)<32 for c in path):
        raise ValueError('invalid public file path')
    p=PurePosixPath(path)
    if p.is_absolute() or '..' in p.parts or p.as_posix()!=path or path.endswith('/'):
        raise ValueError('file path must be canonical and relative')
    return path

def task_view(record):
    """Only supplied prompt/context and empty output targets cross the solver boundary."""
    if not isinstance(record,dict) or not isinstance(record.get('input'),dict) or not isinstance(record.get('output'),dict):
        raise ValueError('invalid natural task')
    original=record['input'];outputs=record['output']
    if set(original)!={'prompt','context'} or set(outputs)!={'response','context'}:
        raise ValueError('unexpected task schema')
    if not isinstance(original['prompt'],str) or not isinstance(original['context'],dict) or not isinstance(outputs['context'],dict):
        raise ValueError('prompt and context types must be exact')
    if outputs['response']!='' or not outputs['context'] or any(v!='' for v in outputs['context'].values()):
        raise ValueError('only empty output placeholders may enter a solver task')
    context={}
    for path,content in original['context'].items():
        if not isinstance(content,str):raise ValueError('public context must be UTF-8 text')
        context[safe_path(path)]=content
    targets=[safe_path(path) for path in outputs['context']]
    return dict(prompt=original['prompt'],context=context,output_paths=targets)

def user_content(view):
    """Serialize exact original Unicode strings; no context truncation or task ID."""
    return json.dumps(view,ensure_ascii=False,separators=(',',':'))

def research_skill(generation,repair):
    """A common format/ABI adaptation, applied identically to research C and P arms."""
    expected='你是 RTL 代码生成器。只输出一个完整、可综合的 Verilog/SystemVerilog `TopModule`，不要输出 Markdown、解释或测试台。'
    if not generation.startswith(expected+'\n') or generation.count('TopModule')!=1 or repair.count('TopModule')!=1:
        raise ValueError('unrecognized frozen skill layout')
    prefix='你是 RTL 代码生成器。按原题面和公开上下文生成完整、可综合的 Verilog/SystemVerilog 文件，模块名遵循原题面。'
    g=generation.replace(expected,prefix,1)+'\n\n'+FORMAT
    r=repair.replace('TopModule','题目要求的模块')
    return g,r

def messages(view,generation,repair,previous=None,diagnostics=None):
    g,r=research_skill(generation,repair)
    first=user_content(view)
    if previous is None:
        if diagnostics is not None:raise ValueError('first generation cannot have repair diagnostics')
        return [dict(role='system',content=g),dict(role='user',content=first)]
    if not isinstance(previous,dict) or set(previous)!=set(view['output_paths']) or not all(isinstance(s,str) for s in previous.values()) or not isinstance(diagnostics,str):
        raise ValueError('repair must bind the complete previous candidate and actual text diagnostics')
    content=first+'\nPrevious candidate files:\n'+json.dumps(previous,ensure_ascii=False,separators=(',',':'))+'\nCandidate diagnostics:\n'+diagnostics
    return [dict(role='system',content=g+'\n'+r),dict(role='user',content=content)]

def _unique(pairs):
    result={}
    for key,value in pairs:
        if key in result:raise ValueError('duplicate JSON key')
        result[key]=value
    return result

def candidate_files(reply,view):
    """No module renaming, searching, slicing, repaired content or missing-file fallback."""
    if not isinstance(reply,str):raise ValueError('candidate response must be text')
    text=reply.strip()
    if text.startswith('```'):
        fence=re.fullmatch(r'```(?:json)?\s*\n(.*?)\n```',text,re.S)
        if not fence:raise ValueError('response must contain exactly one JSON object')
        text=fence.group(1)
    payload=json.loads(text,object_pairs_hook=_unique)
    if not isinstance(payload,dict) or set(payload)!={'files'} or not isinstance(payload['files'],dict):
        raise ValueError('candidate must contain exactly the files object')
    files=payload['files']
    if set(files)!=set(view['output_paths']) or any(not isinstance(s,str) or not s.strip() for s in files.values()):
        raise ValueError('candidate must cover every requested path with nonempty text')
    for path in files:safe_path(path)
    return {path:files[path] for path in view['output_paths']}

def assembled_files(view,candidate):
    if not isinstance(candidate,dict) or set(candidate)!=set(view['output_paths']):
        raise ValueError('candidate paths must match the original targets')
    if any(not isinstance(s,str) or not s.strip() for s in candidate.values()):
        raise ValueError('candidate files must be nonempty text')
    # Input files that are explicitly designated outputs are writable partial designs.
    # All other original context (including docs and helper files) remains byte-identical.
    return {**view['context'],**candidate}

def binding(record,view):
    if view!=task_view(record):raise ValueError('solver task differs from the original public task')
    return dict(prompt_sha256=digest(view['prompt']),input_context_sha256={p:digest(s) for p,s in view['context'].items()},output_paths=view['output_paths'],user_content_sha256=digest(user_content(view)),original_names_and_content_preserved=True,hidden_harness_forwarded=False,answers_forwarded=False)
