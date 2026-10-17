"""Contract fixtures shared with genro-builders-js; no browser or JS evaluator."""
import json
from pathlib import Path

import pytest
from genro_bag.resolver import BagCbResolver
from genro_builders.contrib.html import HtmlBuilder
from genro_builders.builder.pointers import expression_slots, pointer_dependencies, pointer_transform

CASES = json.loads((Path(__file__).parent / 'fixtures/pointer-suffixes.json').read_text())


@pytest.mark.parametrize('case', CASES, ids=lambda case: case['name'])
def test_shared_suffix_contract(case):
    b = HtmlBuilder()
    for key, value in case['data'].items():
        b.data[key] = value
    node = b.source.div(**case['attrs'])
    before = dict(node.attr)
    if 'error' in case:
        with pytest.raises(ValueError, match=case['error']):
            b.runtime_values(node)
    else:
        assert b.runtime_values(node)[1] == case['expected']
    assert node.attr == before
    for key, value in case['data'].items():
        assert b.data[key] == value


def test_paths_dependencies_and_rebinding():
    b = HtmlBuilder()
    b.data.set_item('record.w', 7, unit='px')
    b.data['record.h'] = 8
    parent = b.source.div(datapath='record', node_id='anchor')
    node = parent.div(width='^.w:{}px', height='^#anchor.h:{width}:{}', unit='=.w?unit:{}')
    assert node.abs_datapath('^#anchor.w?unit:Unit: {}') == 'record.w?unit'
    assert node.abs_datapath('^.child.#parent.w:{}') == 'record.w'
    assert b.runtime_values(node)[1] == {'width':'7px','height':'7px:8','unit':'px'}
    assert node.pointers() == [('width','^.w'), ('height','^#anchor.h')]
    assert pointer_dependencies(node, node.attr['height']) == {'width'}
    b.data['record.w'] = 9
    assert b.runtime_values(node)[1]['height'] == '9px:8'
    node.attr['width'] = '^.h:{}em'
    assert b.runtime_values(node)[1]['height'] == '8em:8'
    assert pointer_dependencies(node, '${width}') == set()
    assert node.pointer_type('==false') is None
    assert pointer_transform('==a:b') is None
    assert pointer_transform('=a:Customer: {}') == ('=a',False,'Customer: {}')


def test_resolvers_read_once_and_named_results_are_not_pointers():
    b = HtmlBuilder()
    b.data['v'] = 1
    calls = []
    def read():
        calls.append(1)
        return '=literal'
    node = b.source.div(a=BagCbResolver(read, cache_time=0), title='^v:{a}', other='^v:{title}')
    assert b.runtime_values(node)[1] == {'a':'=literal','title':'=literal','other':'=literal'}
    assert calls == [1]


def test_static_expressions_keep_source_and_scan_only_code():
    body = '''_F({}, {pattern: '0.00', mask: '{} €'}) + /{regex}/.source /* {comment} */ + "{literal}" + {width}'''
    assert expression_slots(body) == ['', 'width']
    assert expression_slots('({} / 2) + /[{}]/.test("{") + `literal {x}`') == ['']
    b = HtmlBuilder()
    b.data['v'] = 2
    node = b.source.div(title='^v:='+body, width=3)
    assert b.runtime_values(node)[1]['title'] is None
    assert node.attr['title'] == '^v:='+body
    from genro_builders import SourceBag
    encoded=b.source.to_tytx()
    restored=SourceBag.from_tytx(encoded)
    assert restored.get_nodes()[0].attr['title'] == '^v:='+body


def test_named_source_metadata_is_read_without_projecting_it():
    b = HtmlBuilder()
    b.data['v'] = 3
    node = b.source.div(node_id='ref', title='^v:{node_id}:{}')
    assert b.runtime_values(node)[1] == {'title':'ref:3'}
