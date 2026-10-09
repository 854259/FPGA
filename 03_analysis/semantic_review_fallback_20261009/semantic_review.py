"""Unqualified draft: one model review for unsupported clocked contracts, not an oracle."""
import hashlib
import re
import interface_feedback


def hint(prompt,interface,contract_status,compile_passed,attempt):
    """Original worker must supply real compile/contract facts; max2 stays external."""
    assert isinstance(prompt,str) and isinstance(interface,str)
    assert contract_status in ('supported','skip','abstain')
    assert type(compile_passed) is bool and type(attempt) is int and attempt in (0,1)
    receipt=dict(schema='unsupported_clocked_model_review_draft_v1',status='skip',reason='',text='',
                 prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest(),
                 interface_sha256=hashlib.sha256(interface.encode()).hexdigest(),contract_status=contract_status,
                 simulated_counterexample=False,function_verified=False,RTL_generated_or_modified=False,
                 review_uses_original_remaining_one_repair=True)
    if not compile_passed or attempt!=0 or contract_status=='supported':
        receipt['reason']='only_first_compile_pass_with_unsupported_function_contract'
        return receipt
    try:
        ports=interface_feedback.prompt_ports(prompt,interface)['ports']
    except interface_feedback.Unsupported as error:
        receipt['reason']='unbound_interface:'+str(error)
        return receipt
    clocks=[name for name,port in ports.items() if name in ('clk','clock') and port==dict(direction='input',width=1)]
    if len(clocks)!=1 or not re.search(r'\b(?:positive|negative|rising|falling)\s+edge\s+of\s+(?:the\s+)?clock\b',prompt,re.I):
        receipt['reason']='one_explicit_clock_edge_contract_required'
        return receipt
    text=('Compilation passed. No supported task-specific functional checker is available for this specification. '
          'Perform a semantic review of the candidate against the original specification: interface and bit ordering, '
          'clock edge, reset, any explicitly required initial state, state transitions and competing-event priorities, '
          'and output timing. Correct any inconsistency you find; if it already meets the specification, return the '
          'same RTL unchanged. This is an unverified model review request, not a measured counterexample. '
          'Do not invent new requirements or assume unspecified initial values.')
    receipt.update(status='review_requested',reason='unsupported_clocked_contract',text=text,clock=clocks[0])
    return receipt
