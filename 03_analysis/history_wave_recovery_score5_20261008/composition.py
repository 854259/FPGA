"""Preserve the complete table parent; extend only its explicit abstentions.

Only prompt/interface strings reach the unchanged producers. Receipts retain
the exact original recipes. No task identity, reference, testbench or I/O input.
"""
import hashlib
import json

import table_synthesis
import selector
import onehot_producer
import timer_producer

SCHEMA = 'table_parent_history_extension_pure_v1'
TABLE_SHA = 'a18ac21891dc229b3252df9ac3122517874a08bb8d269e5763d9146eae1279e5'
PRODUCER_SHA = {
    'table': TABLE_SHA,
    'onehot': 'fc1af52cd3d76faf9eed812167eb8179ab40b3c3d32740062e6d444459701007',
    'timer': '9080c49a93c807a4e5291e729d0b3ccb85b8d78c680607510ebcec7192fa26d6',
}


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _json(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True,
                      separators=(',', ':')).encode('utf-8')


def _empty(prompt, interface):
    if type(prompt) is not str or type(interface) is not str:
        raise TypeError('Prompt and interface must be strings')
    return dict(schema=SCHEMA, emitted=False, rtl=None, rtl_sha256=None,
                contract=None, contract_sha256=None, selected_provider=None,
                selected_producer_sha256=None, original_recipe=None,
                original_recipe_sha256=None, parent_recipe=None,
                parent_recipe_sha256=None, extension_selection=None,
                extension_selection_sha256=None, actual_model_requests=0,
                actual_eda_calls=0, external_io_calls=0, score_gain_measured=False,
                input_hashes_bound=True, all_prompt_consumed=False,
                prompt_sha256=_sha(prompt.encode('utf-8')),
                interface_sha256=_sha(interface.encode('utf-8')),
                reason='parent_abstained')


def _bound(result, recipe, provider, prompt):
    """Invalid parent evidence raises; it cannot open the extension branch."""
    assert provider in PRODUCER_SHA
    assert type(recipe) is dict and type(recipe.get('emitted')) is bool
    assert recipe.get('prompt_sha256') == result['prompt_sha256']
    assert recipe.get('interface_sha256') == result['interface_sha256']
    assert all(type(recipe.get(k)) is int and recipe[k] == 0 for k in
               ('actual_model_requests', 'actual_eda_calls', 'external_io_calls'))
    if not recipe['emitted']:
        assert recipe.get('rtl') == '' and isinstance(recipe.get('reason'), str)
        return result
    assert isinstance(recipe.get('rtl'), str) and recipe['rtl']
    assert recipe.get('rtl_sha256') == _sha(recipe['rtl'].encode('utf-8'))
    if provider == 'table':
        parsed = table_synthesis.contract.parse_prompt(prompt)
        assert parsed['admitted'] is True and parsed['all_prompt_consumed'] is True
        assert recipe.get('all_prompt_consumed') is True
        contract = parsed['contract']
    else:
        contract = recipe['contract']
        assert type(contract) is dict and contract.get('all_prompt_consumed') is True
    assert type(contract) is dict
    assert recipe.get('contract_sha256') == _sha(_json(contract))
    return result | dict(emitted=True, rtl=recipe['rtl'],
                         rtl_sha256=recipe['rtl_sha256'], contract=contract,
                         contract_sha256=recipe['contract_sha256'],
                         selected_provider=provider,
                         selected_producer_sha256=PRODUCER_SHA[provider],
                         original_recipe=recipe, original_recipe_sha256=_sha(_json(recipe)),
                         all_prompt_consumed=True, reason='fully_consumed_' + provider)


def parent(prompt, interface=''):
    result = _empty(prompt, interface)
    recipe = table_synthesis.synthesize(prompt, interface)
    result = _bound(result, recipe, 'table', prompt)
    return result | dict(parent_recipe=recipe, parent_recipe_sha256=_sha(_json(recipe)))


def synthesize(prompt, interface=''):
    common = parent(prompt, interface)
    if common['emitted']:
        return common
    selection = selector.select(prompt, interface,
                                [('onehot', onehot_producer.synthesize),
                                 ('timer', timer_producer.synthesize)])
    common = common | dict(extension_selection=selection,
                           extension_selection_sha256=_sha(_json(selection)))
    if selection['recipe'] is None:
        assert selection['route'] == 'model' and selection['selected_provider'] is None
        return common | dict(reason=selection['reason'])
    assert selection['route'] == 'mechanical'
    assert selection['selected_provider'] in ('onehot', 'timer')
    return _bound(common, selection['recipe'], selection['selected_provider'], prompt)


def score_admission():
    raise RuntimeError('Draft composition requires a separately frozen score entry; score admission pending')
