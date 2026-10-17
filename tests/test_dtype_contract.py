"""Python-generated dtype grammar is loaded unchanged by the JS contract tests."""
import json
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path

from genro_bag import Bag
from genro_builders import BuilderBase
from genro_builders.builder import element
from genro_builders.builder._grammar_export import _class_schema_to_grammar_document
from genro_builders.builder._grammar_load import _annotation


class DtypeContract(BuilderBase):
    _name = 'dtype_contract'

    @element()
    def typed(self, day: date, clock: time, stamp: datetime, amount: Decimal,
              payload: bytes, data: Bag, optional: date | None, dates: list[date]): ...


def test_exported_dtype_contract_matches_shared_fixture():
    document = _class_schema_to_grammar_document(DtypeContract)
    expected = json.loads((Path(__file__).parent / 'fixtures/dtypes.json').read_text())
    assert document == expected


def test_registered_domain_values_roundtrip_without_coercion(tmp_path):
    document = _class_schema_to_grammar_document(DtypeContract)
    path = tmp_path / 'dtypes.json'
    path.write_text(json.dumps(document))
    loaded = type('LoadedDtype', (BuilderBase,), {'_grammar_documents': (str(path),)})
    b=loaded()
    values=dict(day=date(2026,10,17), clock=time(9,30), stamp=datetime(2026,10,17,9,30),
                amount=Decimal('9007199254740993.25'), payload=b'abc', data=Bag(),
                optional=None, dates=[date(2026,10,17)])
    node=b.source.typed(**values)
    for key,value in values.items():
        if value is not None:
            assert type(node.attr[key]) is type(value)
            if key != 'data':
                assert node.attr[key] == value


def test_custom_registry_type_is_used_without_imports():
    from genro_tytx import TYPE_REGISTRY, SUFFIX_TO_TYPE, register_type
    from genro_tytx.registry import CUSTOM_TYPES
    from genro_builders.builder._utilities import _check_type
    class Domain:
        pass
    try:
        register_type(Domain, 'DTYPECONTRACT', lambda v: '', lambda s: Domain())
        annotation = _annotation({'kind':'dtype','dtype':'DTYPECONTRACT'}, 'test')
        assert _check_type(Domain(),annotation)
        assert not _check_type(object(),annotation)
    finally:
        TYPE_REGISTRY.pop(Domain,None)
        SUFFIX_TO_TYPE.pop('DTYPECONTRACT',None)
        CUSTOM_TYPES.discard(Domain)
