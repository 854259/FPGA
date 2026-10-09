"""Facts comparing prompt-provided ports with candidate ports; no DUT/oracle I/O."""
import hashlib
import re
from agent_extract_boundary import tokens
from reserved_keywords import KEYWORDS

ID=r'[A-Za-z_][A-Za-z_0-9$]*'
MAX_SOURCE=131072


class Unsupported(ValueError):
    pass


def require(condition,reason):
    if not condition:raise Unsupported(reason)


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def module_ports(code):
    require(isinstance(code,str) and len(code)<=MAX_SOURCE,'source_bound')
    stream,error=tokens(code)
    require(not error and len(stream)<=24000,'lexical_or_token_bound')
    require(len(stream)>=6 and stream[0][0]=='module' and stream[-1][0]=='endmodule','one_complete_module_required')
    require(sum(t[0]=='module' for t in stream)==1 and sum(t[0]=='endmodule' for t in stream)==1,'one_module_required')
    module=stream[1][0]
    require(module is not None and re.fullmatch(ID,module) and module not in KEYWORDS,'module_identifier')
    require(code[stream[2][1]:stream[2][2]]=='(','unparameterized_ANSI_header_required')
    end=next((i for i in range(3,len(stream)) if code[stream[i][1]:stream[i][2]]==')'),None)
    require(end is not None and end+1<len(stream) and code[stream[end+1][1]:stream[end+1][2]]==';','complete_header')
    header=' '.join(code[a:b] for _,a,b in stream[3:end])
    ports={};direction=None;width=1
    for chunk in header.split(','):
        match=re.fullmatch(r'\s*(?:(input|output|inout)\s+)?(?:(?:wire|reg|logic)\s+)?'
                           r'(?:(?:signed|unsigned)\s+)?(?:\[\s*(\d+)\s*:\s*(\d+)\s*\]\s*)?('+ID+r')\s*',chunk)
        require(match is not None,'unsupported_header_port')
        if match[1]:direction=match[1];width=1
        require(direction is not None,'nonANSI_header_not_supported')
        if match[2] is not None:width=abs(int(match[2])-int(match[3]))+1
        name=match[4]
        require(name not in KEYWORDS and name not in ports and 1<=width<=65536,'invalid_duplicate_or_unbounded_port')
        ports[name]=dict(direction=direction,width=width)
    require(0<len(ports)<=256,'port_count_bound')
    return dict(module=module,ports=ports)


def prompt_ports(prompt,interface=''):
    require(isinstance(prompt,str) and isinstance(interface,str) and len(prompt)<=MAX_SOURCE and len(interface)<=32768,'prompt_bound')
    normalized=prompt.replace('\r\n','\n').replace('\r','\n')
    module=re.search(r'\bmodule\s+named\s+('+ID+r')\s+with\s+the\s+following\s+interface\.',normalized,re.I)
    bullets=re.findall(r'(?m)^[ \t]*-[ \t]*(input|output|inout)[ \t]+([^\n]+)$',normalized)
    expected=None
    if module and bullets:
        require(re.search(r'All\s+input\s+and\s+output\s+ports\s+are\s+one\s+bit\s+unless\s+otherwise\s+specified\.',normalized,re.I),'default_port_width_not_explicit')
        ports={}
        for direction,body in bullets:
            match=re.fullmatch(r'\s*('+ID+r')(?:\s*\(\s*(\d+)\s+bits?\s*\))?\s*',body)
            require(match is not None,'unsupported_port_bullet')
            name=match[1];width=int(match[2]) if match[2] else 1
            require(name not in KEYWORDS and name not in ports and 1<=width<=65536,'invalid_prompt_port')
            ports[name]=dict(direction=direction,width=width)
        expected=dict(module=module[1],ports=ports,source='explicit_prompt_port_bullets')
    elif re.match(r'\s*Consider\s+the\s+following\s+implementation\b',normalized,re.I):
        # A given faulty implementation supplies port facts. Differences are
        # reported for review, without assuming the shown port is itself correct.
        start=re.search(r'\bmodule\b',normalized);end=re.search(r'\bendmodule\b',normalized)
        require(start is not None and end is not None and start.start()<end.start(),'given_module_not_complete')
        require(len(re.findall(r'\bmodule\b',normalized[start.start():end.end()]))==1,'ambiguous_given_module')
        expected=dict(module_ports(normalized[start.start():end.end()]),source='provided_faulty_module_ports_review_only')
    if interface.strip():
        formal=module_ports(interface)
        if expected:
            require(formal=={k:expected[k] for k in ('module','ports')},'prompt_interface_conflict')
        return dict(formal,source='separate_interface')
    require(expected is not None,'no_explicit_port_contract')
    return expected


def check(prompt,code,interface=''):
    result=dict(schema='prompt_candidate_port_difference_v1',status='abstain',reason='',diagnostics=[],feedback='',
                prompt_sha256=digest(prompt),interface_sha256=digest(interface),candidate_sha256=digest(code),
                semantic_function_checked=False,RTL_rewritten=False,private_oracle_used=False)
    try:
        expected=prompt_ports(prompt,interface);candidate=module_ports(code)
        differences=[]
        if candidate['module']!=expected['module']:
            differences.append('Provided module name '+expected['module']+'; candidate module name '+candidate['module']+'.')
        for name,specified in expected['ports'].items():
            actual=candidate['ports'].get(name)
            if actual is None:differences.append('Provided port '+name+' is absent from candidate.')
            elif actual!=specified:
                differences.append('Provided port '+name+': '+specified['direction']+' '+str(specified['width'])+' bit(s); candidate: '+actual['direction']+' '+str(actual['width'])+' bit(s).')
        for name in candidate['ports'].keys()-expected['ports'].keys():
            differences.append('Candidate adds port '+name+' absent from the provided interface.')
        feedback=''
        if differences:
            feedback='Prompt-provided interface versus candidate port facts:\n'+'\n'.join(differences)
            feedback+='\nReview these differences against the task requirements; this check does not determine the functional correction.'
            if expected['source']=='provided_faulty_module_ports_review_only':
                feedback+=' The supplied implementation is described as faulty; a port difference is a review item, not proof that reverting that port is the correct fix.'
        require(len(feedback)<=4096,'feedback_bound_no_truncation')
        result.update(status='differences' if differences else 'match',expected=expected,candidate=candidate,
                      diagnostics=differences,feedback=feedback)
    except Unsupported as error:result['reason']=str(error)
    return result
