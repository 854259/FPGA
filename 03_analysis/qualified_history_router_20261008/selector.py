"""Select one complete prompt-derived recipe; ambiguity abstains to the caller.

This pure selector does not execute a worker, compiler, grader or model. Providers
are the separately pinned prompt-only producers; they receive only the two input
strings. An abstention means the original worker must handle the unchanged input.
"""
import hashlib
import json


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def select(prompt, interface, providers):
    """Return an unchanged recipe only when exactly one provider emits valid RTL."""
    if not isinstance(prompt, str) or not isinstance(interface, str):
        raise TypeError('Prompt and interface must be strings')
    names = [name for name, provider in providers]
    if not names or len(set(names)) != len(names):
        raise ValueError('Providers must have unique names')
    result = dict(schema='complete_prompt_recipe_selection_v1',
                  route='model', reason='no_complete_contract',
                  selected_provider=None, recipe=None,
                  prompt_sha256=digest(prompt), interface_sha256=digest(interface),
                  observed=[], actual_model_requests=0, actual_eda_calls=0)
    emitted = []
    invalid = False
    for name, provider in providers:
        receipt = provider(prompt, interface)
        valid = (type(receipt) is dict and type(receipt.get('emitted')) is bool
                 and receipt.get('prompt_sha256') == result['prompt_sha256']
                 and receipt.get('interface_sha256') == result['interface_sha256']
                 and all(type(receipt.get(k)) is int and receipt[k] == 0 for k in
                         ['actual_model_requests', 'actual_eda_calls', 'external_io_calls']))
        if valid and receipt['emitted']:
            rtl, contract = receipt.get('rtl'), receipt.get('contract')
            valid = (isinstance(rtl, str) and bool(rtl) and type(contract) is dict
                     and contract.get('all_prompt_consumed') is True)
            if valid:
                canonical = json.dumps(contract, sort_keys=True, separators=(',', ':'))
                valid = (receipt.get('rtl_sha256') == digest(rtl)
                         and receipt.get('contract_sha256') == digest(canonical))
        elif valid:
            valid = receipt.get('rtl') == '' and receipt.get('contract') is None
        result['observed'].append(dict(provider=name, valid=bool(valid),
                                       emitted=receipt.get('emitted') if type(receipt) is dict else None))
        invalid |= not valid
        if valid and receipt['emitted']:
            emitted.append((name, receipt))
    if invalid:
        result['reason'] = 'invalid_provider_receipt'
    elif len(emitted) > 1:
        result['reason'] = 'ambiguous_complete_contracts'
    elif len(emitted) == 1:
        name, receipt = emitted[0]
        # Preserve the actual producer's receipt and RTL; no rewrite or merge.
        result.update(route='mechanical', reason=None,
                      selected_provider=name, recipe=receipt)
    return result
