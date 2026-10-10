"""Prompt-only bounded functional contract dispatch; no task IDs or answers."""
import priority_contract
import shift_contract


def parse(prompt):
    parsed=[('priority',priority_contract.parse(prompt)),('shift',shift_contract.parse(prompt))]
    supported=[(kind,c) for kind,c in parsed if c['status']=='supported']
    if len(supported)==1 and all(c['status'] in {'supported','skip'} for _,c in parsed):
        kind,c=supported[0];return dict(c,kind=kind)
    return dict(status='abstain',reason='unknown_or_ambiguous_complete_contract')


def module(c):return priority_contract if c['kind']=='priority' else shift_contract
def render_tb(c,task):return module(c).render_tb(c,task)
def counterexample(log,c):return module(c).counterexample(log,c)
