import datetime
import math
from pathlib import Path

import pytest

import yaml
from yaml.constructor import (
    ConstructorError,
    SafeConstructor,
    FullConstructor,
    UnsafeConstructor,
)
from yaml.loader import (
    BaseLoader,
    SafeLoader,
    FullLoader,
    Loader,
    UnsafeLoader,
)
from yaml.schema import (
    CORE_IMPLICIT_RESOLVERS,
    YAML12CoreResolver,
    YAML12SafeDumper,
    YAML12SafeLoader,
)


# Sentinel marking scalars that fail to load (value construction, not merely
# a non-matching implicit rule).
ERROR = object()
NAN = float('nan')
INF = float('inf')

CORE_LOADERS = [
    yaml.YAML12SafeLoader,
    yaml.YAML12FullLoader,
    yaml.YAML12Loader,
]


def assert_same(actual, expected):
    if isinstance(expected, float) and math.isnan(expected):
        assert isinstance(actual, float) and math.isnan(actual)
        return
    assert actual == expected
    assert type(actual) is type(expected)


# Ambiguous plain scalars: (scalar, YAML 1.1 default result, 1.2 core result)
AMBIGUOUS_SCALARS = [
    # booleans: yes/no/on/off and single letters are strings in the core schema
    ('on', True, 'on'),
    ('On', True, 'On'),
    ('ON', True, 'ON'),
    ('off', False, 'off'),
    ('Off', False, 'Off'),
    ('OFF', False, 'OFF'),
    ('yes', True, 'yes'),
    ('Yes', True, 'Yes'),
    ('YES', True, 'YES'),
    ('no', False, 'no'),
    ('No', False, 'No'),
    ('NO', False, 'NO'),
    ('y', 'y', 'y'),
    ('Y', 'Y', 'Y'),
    ('n', 'n', 'n'),
    ('N', 'N', 'N'),
    ('true', True, True),
    ('True', True, True),
    ('TRUE', True, True),
    ('false', False, False),
    ('False', False, False),
    ('FALSE', False, False),
    ('fAlse', 'fAlse', 'fAlse'),
    ('TrUE', 'TrUE', 'TrUE'),
    # null
    ('~', None, None),
    ('null', None, None),
    ('Null', None, None),
    ('NULL', None, None),
    ('NuLL', 'NuLL', 'NuLL'),
    # integers and integer bases
    ('0', 0, 0),
    ('+0', 0, 0),
    ('-0', 0, 0),
    ('23', 23, 23),
    ('+23', 23, 23),
    ('-23', -23, -23),
    ('0123', 83, 123),          # 1.1: octal 83 / 1.2: decimal 123
    ('00', 0, 0),
    ('010', 8, 10),
    ('07', 7, 7),
    ('08', '08', 8),            # 1.1 octal rule rejects digit 8
    ('0o17', '0o17', 15),       # core-only octal prefix
    ('0o0', '0o0', 0),
    ('0x1f', 31, 31),
    ('0x0', 0, 0),
    ('-0x30', -48, '-0x30'),    # 0o/0x carry no sign in the core schema
    ('+0x10', 16, '+0x10'),
    ('0b1010', 10, '0b1010'),   # no binary integers in the core schema
    ('1_000', 1000, '1_000'),
    ('100_000', 100000, '100_000'),
    ('190:20:30', 685230, '190:20:30'),   # no sexagesimal in the core schema
    ('12:30', 750, '12:30'),
    # floats
    ('3.', 3.0, 3.0),
    ('3.14', 3.14, 3.14),
    ('-3.14', -3.14, -3.14),
    ('.5', 0.5, 0.5),
    ('.14', 0.14, 0.14),
    ('001.23', 1.23, 1.23),
    ('1e3', '1e3', 1000.0),     # scientific notation without '.' is core-only
    ('0.3e3', '0.3e3', 300.0),
    ('3e3', '3e3', 3000.0),
    ('3.3e+3', 3300.0, 3300.0),
    ('.1_4', 0.14, '.1_4'),
    ('85_230.15', 85230.15, '85_230.15'),
    ('85.230_15e+03', 85230.15, '85.230_15e+03'),
    ('190:20:30.15', 685230.15, '190:20:30.15'),
    ('inf', 'inf', 'inf'),
    ('nan', 'nan', 'nan'),
    ('.inF', '.inF', '.inF'),
    ('.', '.', '.'),
    ('._', '._', '._'),
    ('.inf', INF, INF),
    ('-.Inf', -INF, -INF),
    ('+.INF', INF, INF),
    ('.NaN', NAN, NAN),
    # timestamps: implicit resolution is outside the core schema
    ('2001-12-15', datetime.date(2001, 12, 15), '2001-12-15'),
    ('2001-12-15T02:59:43.1Z',
     datetime.datetime(2001, 12, 15, 2, 59, 43, 100000,
                       tzinfo=datetime.timezone.utc),
     '2001-12-15T02:59:43.1Z'),
    ('2001-12-15 2:59:43.10 -5',
     datetime.datetime(2001, 12, 15, 2, 59, 43, 100000,
                       tzinfo=datetime.timezone(
                           datetime.timedelta(days=-1, seconds=68400))),
     '2001-12-15 2:59:43.10 -5'),
    ('2001-1-1', '2001-1-1', '2001-1-1'),
    ('2001-13-01', ERROR, '2001-13-01'),
    ('2001-02-30', ERROR, '2001-02-30'),
]


@pytest.mark.parametrize('scalar, default_value, core_value', AMBIGUOUS_SCALARS)
def test_ambiguous_scalar_matrix_default_vs_core(scalar, default_value,
        core_value):
    if default_value is ERROR:
        with pytest.raises(ValueError):
            yaml.safe_load(scalar)
    else:
        assert_same(yaml.safe_load(scalar), default_value)

    assert_same(yaml.load(scalar, Loader=YAML12SafeLoader), core_value)


@pytest.mark.parametrize('Loader', CORE_LOADERS)
@pytest.mark.parametrize('scalar, default_value, core_value', AMBIGUOUS_SCALARS)
def test_ambiguous_scalar_matrix_all_core_loaders(Loader, scalar,
        default_value, core_value):
    assert_same(yaml.load(scalar, Loader=Loader), core_value)


@pytest.mark.parametrize('Loader', CORE_LOADERS)
def test_all_core_loaders_share_core_construction(Loader):
    assert yaml.load('!!timestamp 2001-12-15', Loader=Loader) == \
        datetime.date(2001, 12, 15)
    with pytest.raises(ConstructorError):
        yaml.load('!!bool on', Loader=Loader)


@pytest.mark.parametrize('scalar, tag', [
    ('on', 'tag:yaml.org,2002:str'),
    ('yes', 'tag:yaml.org,2002:str'),
    ('0123', 'tag:yaml.org,2002:int'),
    ('0o17', 'tag:yaml.org,2002:int'),
    ('0b1010', 'tag:yaml.org,2002:str'),
    ('2001-12-15', 'tag:yaml.org,2002:str'),
    ('.inf', 'tag:yaml.org,2002:float'),
    ('~', 'tag:yaml.org,2002:null'),
])
def test_composed_nodes_use_core_tags(scalar, tag):
    assert yaml.compose(scalar, Loader=YAML12SafeLoader).tag == tag


# Explicit tags bypass implicit resolution; values that do not fit the tagged
# YAML 1.2 core type raise ConstructorError instead of falling back.
EXPLICIT_TAG_SCALARS = [
    ('!!null ~', None),
    ('!!null null', None),
    ('!!null', None),
    ('!!null NuLL', ERROR),
    ('!!bool true', True),
    ('!!bool FALSE', False),
    ('!!bool on', ERROR),
    ('!!bool yes', ERROR),
    ('!!int 23', 23),
    ('!!int 010', 10),
    ('!!int 0o17', 15),
    ('!!int 0x1f', 31),
    ('!!int 0b1010', ERROR),
    ('!!int 1_000', ERROR),
    ('!!int 190:20:30', ERROR),
    ('!!int -0x30', ERROR),
    ('!!float 3.14', 3.14),
    ('!!float 1e3', 1000.0),
    ('!!float .inf', INF),
    ('!!float .1_4', ERROR),
    ('!!float inf', ERROR),
    ('!!float 190:20:30.15', ERROR),
    ('!!str on', 'on'),
    ('!!str 0123', '0123'),
    ('!!str 2001-12-15', '2001-12-15'),
    ('!!str', ''),
    ('!!binary aGVsbG8=', b'hello'),
]


@pytest.mark.parametrize('source, expected', EXPLICIT_TAG_SCALARS)
def test_explicit_tags_override_core_resolution(source, expected):
    if expected is ERROR:
        with pytest.raises(ConstructorError):
            yaml.load(source, Loader=YAML12SafeLoader)
    else:
        assert_same(yaml.load(source, Loader=YAML12SafeLoader), expected)


def test_explicit_str_forces_text_even_for_core_numbers():
    for source in ('!!str 0123', '!!str 0o17', '!!str .inf', '!!str true'):
        value = yaml.load(source, Loader=YAML12SafeLoader)
        assert type(value) is str and value == source.split(None, 1)[1]


def test_explicit_merge_key_still_flattens_under_core():
    # Plain ``<<`` is not resolved to the merge tag under the core schema,
    # but an explicit !!merge keeps the YAML 1.1 mapping merge behavior.
    implicit = yaml.load(
        "base: &base {x: 1}\ntarget:\n  <<: *base\n  y: 2\n",
        Loader=YAML12SafeLoader)
    assert implicit == {'base': {'x': 1},
                        'target': {'<<': {'x': 1}, 'y': 2}}

    explicit = yaml.load(
        "base: &base {x: 1}\ntarget:\n  !!merge <<: *base\n  y: 2\n",
        Loader=YAML12SafeLoader)
    assert explicit == {'base': {'x': 1},
                        'target': {'x': 1, 'y': 2}}


# Timestamp boundaries: implicit resolution in 1.2 core is always a string,
# while explicit !!timestamp uses the YAML 1.1 timestamp constructor.
TIMESTAMP_BOUNDARIES = [
    ('2001-12-15', datetime.date(2001, 12, 15), datetime.date(2001, 12, 15)),
    ('2001-12-15T02:59:43',
     datetime.datetime(2001, 12, 15, 2, 59, 43),
     datetime.datetime(2001, 12, 15, 2, 59, 43)),
    ('2001-12-15T02:59:43Z',
     datetime.datetime(2001, 12, 15, 2, 59, 43,
                       tzinfo=datetime.timezone.utc),
     datetime.datetime(2001, 12, 15, 2, 59, 43,
                       tzinfo=datetime.timezone.utc)),
    ('2001-12-15T02:59:43.1Z',
     datetime.datetime(2001, 12, 15, 2, 59, 43, 100000,
                       tzinfo=datetime.timezone.utc),
     datetime.datetime(2001, 12, 15, 2, 59, 43, 100000,
                       tzinfo=datetime.timezone.utc)),
    ('2001-12-15T02:59:43.1234567Z',
     datetime.datetime(2001, 12, 15, 2, 59, 43, 123456,
                       tzinfo=datetime.timezone.utc),
     datetime.datetime(2001, 12, 15, 2, 59, 43, 123456,
                       tzinfo=datetime.timezone.utc)),
    ('2001-12-15 2:59:43.10 -5',
     datetime.datetime(2001, 12, 15, 2, 59, 43, 100000,
                       tzinfo=datetime.timezone(
                           datetime.timedelta(days=-1, seconds=68400))),
     datetime.datetime(2001, 12, 15, 2, 59, 43, 100000,
                       tzinfo=datetime.timezone(
                           datetime.timedelta(days=-1, seconds=68400)))),
    ('2001-12-15T2:59:43Z',
     datetime.datetime(2001, 12, 15, 2, 59, 43,
                       tzinfo=datetime.timezone.utc),
     datetime.datetime(2001, 12, 15, 2, 59, 43,
                       tzinfo=datetime.timezone.utc)),
    ('2001-12-15T02:59:43+05:30',
     datetime.datetime(2001, 12, 15, 2, 59, 43,
                       tzinfo=datetime.timezone(
                           datetime.timedelta(seconds=19800))),
     datetime.datetime(2001, 12, 15, 2, 59, 43,
                       tzinfo=datetime.timezone(
                           datetime.timedelta(seconds=19800)))),
    ('2001-12-15T02:59:43.',
     datetime.datetime(2001, 12, 15, 2, 59, 43),
     datetime.datetime(2001, 12, 15, 2, 59, 43)),
    ('2001-1-1', '2001-1-1', datetime.date(2001, 1, 1)),
    ('2001-12-31', datetime.date(2001, 12, 31), datetime.date(2001, 12, 31)),
    ('9999-12-31T23:59:59Z',
     datetime.datetime(9999, 12, 31, 23, 59, 59,
                       tzinfo=datetime.timezone.utc),
     datetime.datetime(9999, 12, 31, 23, 59, 59,
                       tzinfo=datetime.timezone.utc)),
    ('2001-13-01', ValueError, ConstructorError),
    ('2001-02-30', ValueError, ConstructorError),
    ('2001-12-15T24:00:00Z', ValueError, ConstructorError),
    ('2001-12-15T2:59:43z', '2001-12-15T2:59:43z', ConstructorError),
]


def assert_load(source, Loader, expected):
    if isinstance(expected, type) and issubclass(expected, Exception):
        with pytest.raises(expected):
            yaml.load(source, Loader=Loader)
    else:
        assert_same(yaml.load(source, Loader=Loader), expected)


@pytest.mark.parametrize('text, default_value, explicit_value',
                         TIMESTAMP_BOUNDARIES)
def test_timestamp_boundaries(text, default_value, explicit_value):
    assert_load(text, SafeLoader, default_value)
    assert_load('!!timestamp ' + text, YAML12SafeLoader, explicit_value)

    implicit = yaml.load(text, Loader=YAML12SafeLoader)
    assert type(implicit) is str and implicit == text


def _resolver_snapshot():
    return {
        cls: {first: tuple(entries)
              for first, entries in cls.yaml_implicit_resolvers.items()}
        for cls in (BaseLoader, SafeLoader, FullLoader,
                    Loader, UnsafeLoader)
    }


def _constructor_snapshot():
    return {
        cls: dict(cls.yaml_constructors)
        for cls in (SafeConstructor, FullConstructor,
                    UnsafeConstructor)
    }


def test_core_resolver_configuration_is_instance_scoped():
    resolvers_before = _resolver_snapshot()
    constructors_before = _constructor_snapshot()

    first = YAML12SafeLoader('on')
    second = YAML12SafeLoader('yes')
    try:
        # Each loader owns its table; neither borrows the class-level table.
        assert first.yaml_implicit_resolvers is not \
            second.yaml_implicit_resolvers
        assert first.yaml_implicit_resolvers is not \
            SafeLoader.yaml_implicit_resolvers
        assert 'tag:yaml.org,2002:timestamp' not in {
            tag for entries in first.yaml_implicit_resolvers.values()
            for tag, regexp in entries
        }
        # Instances can be retuned without affecting anybody else.
        first.yaml_implicit_resolvers = {}
        assert first.resolve(
            yaml.ScalarNode, 'on', (True, False)) == \
            'tag:yaml.org,2002:str'
        assert second.resolve(
            yaml.ScalarNode, 'on', (True, False)) == \
            'tag:yaml.org,2002:str'
    finally:
        first.dispose()
        second.dispose()

    assert _resolver_snapshot() == resolvers_before
    assert _constructor_snapshot() == constructors_before


def test_yaml12_use_does_not_change_default_loader_results():
    resolvers_before = _resolver_snapshot()
    constructors_before = _constructor_snapshot()

    for _ in range(5):
        assert yaml.safe_load('on') is True
        assert yaml.safe_load('0123') == 83
        assert yaml.load('on', Loader=YAML12SafeLoader) == 'on'
        assert yaml.load('0123', Loader=YAML12SafeLoader) == 123
        assert yaml.full_load('on') is True
        assert yaml.load('on', Loader=yaml.YAML12FullLoader) == 'on'
        assert yaml.load('on', Loader=Loader) is True
        assert yaml.load('on', Loader=yaml.YAML12Loader) == 'on'

    assert _resolver_snapshot() == resolvers_before
    assert _constructor_snapshot() == constructors_before

    # Explicit tags on the YAML 1.1 classes keep their old, permissive rules.
    assert yaml.safe_load('!!bool on') is True
    assert yaml.safe_load('!!int 0b10') == 2
    assert yaml.safe_load('!!float 1_4') == 14.0
    assert yaml.safe_load('!!null NuLL') is None


def test_two_configurations_interleaved_over_shared_source():
    source = (
        'on: 0123\n'
        'flag: yes\n'
        'octal: 0o17\n'
        'binary: 0b1010\n'
        'time: 2001-12-15\n'
        'explicit: !!timestamp 2001-12-15\n'
        'tagged: !!str 0123\n'
    )
    core_expected = {
        'on': 123,
        'flag': 'yes',
        'octal': 15,
        'binary': '0b1010',
        'time': '2001-12-15',
        'explicit': datetime.date(2001, 12, 15),
        'tagged': '0123',
    }
    default_expected = {
        True: 83,
        'flag': True,
        'octal': '0o17',
        'binary': 10,
        'time': datetime.date(2001, 12, 15),
        'explicit': datetime.date(2001, 12, 15),
        'tagged': '0123',
    }

    for _ in range(3):
        assert yaml.load(source, Loader=YAML12SafeLoader) == core_expected
        assert yaml.safe_load(source) == default_expected

    # The same loader class keeps its own configuration per instance.
    left = YAML12SafeLoader(source)
    right = SafeLoader(source)
    try:
        left_data = left.get_single_data()
        right_data = right.get_single_data()
    finally:
        left.dispose()
        right.dispose()
    assert left_data == core_expected
    assert right_data == default_expected


def test_load_all_multiple_documents_interleaved_configs():
    source = (
        '---\n'
        'on\n'
        '---\n'
        '0o10\n'
        '---\n'
        '2001-12-15\n'
        '---\n'
        '!!timestamp 2001-12-15\n'
        '---\n'
        '\n'
        '---\n'
        '0123\n'
    )
    core_documents = list(yaml.load_all(source, Loader=YAML12SafeLoader))
    assert core_documents == [
        'on',
        8,
        '2001-12-15',
        datetime.date(2001, 12, 15),
        None,
        123,
    ]

    default_documents = list(yaml.safe_load_all(source))
    assert default_documents == [
        True,
        '0o10',
        datetime.date(2001, 12, 15),
        datetime.date(2001, 12, 15),
        None,
        83,
    ]

    # Interleave both configurations over the same stream.
    for _ in range(2):
        assert list(yaml.safe_load_all(source)) == default_documents
        assert list(yaml.load_all(source, Loader=YAML12SafeLoader)) == \
            core_documents

    assert list(yaml.yaml12_load_all(source)) == core_documents


def _assert_equal_values_and_types(expected, actual):
    if isinstance(expected, float) and math.isnan(expected):
        assert isinstance(actual, float) and math.isnan(actual)
        return
    assert type(expected) is type(actual)
    if isinstance(expected, dict):
        assert expected.keys() == actual.keys()
        for key in expected:
            _assert_equal_values_and_types(expected[key], actual[key])
    elif isinstance(expected, (list, tuple)):
        assert len(expected) == len(actual)
        for item, reloaded in zip(expected, actual):
            _assert_equal_values_and_types(item, reloaded)
    elif isinstance(expected, set):
        assert expected == actual
    else:
        assert expected == actual


RICH_DATA = {
    'bools': [True, False],
    'none': None,
    'ints': [42, -7, 0, 15, 31, 123],
    'floats': [3.5, 0.0, float('inf'), -float('inf'), float('nan')],
    'strings': ['on', 'yes', '0123', '0o17', '0b1010', '1_000', '1e3',
                '2001-12-15', '.inf', 'null', 'true', ''],
    'date': datetime.date(2001, 12, 15),
    'aware': datetime.datetime(2001, 12, 15, 2, 59, 43,
                               tzinfo=datetime.timezone.utc),
    'naive': datetime.datetime(2001, 12, 15, 2, 59, 43),
    'nested': {'on': 'on', 'list': [1, None, True, 'x']},
    'set': {'a', 'b'},
    'bytes': b'hello',
}


@pytest.mark.parametrize('Dumper', [YAML12SafeDumper, yaml.YAML12Dumper])
def test_core_dumper_round_trip_preserves_values_and_types(Dumper):
    output = yaml.dump(RICH_DATA, Dumper=Dumper, sort_keys=True)
    reloaded = yaml.load(output, Loader=YAML12SafeLoader)
    _assert_equal_values_and_types(RICH_DATA, reloaded)

    # Multiple documents keep values and types as well; formatting may differ.
    documents = [RICH_DATA, {'on': 'on', 'n': None}, [1, True, 'end']]
    output_all = yaml.dump_all(documents, Dumper=Dumper)
    reloaded_all = list(yaml.load_all(output_all, Loader=YAML12SafeLoader))
    assert len(reloaded_all) == len(documents)
    for expected, actual in zip(documents, reloaded_all):
        _assert_equal_values_and_types(expected, actual)


def test_core_dumper_quotes_core_only_scalar_strings():
    # Strings that are numbers under 1.2 but text under 1.1 must be quoted by
    # the paired dumper so a core-schema reload keeps their string type.
    for value in ('1e3', '0o17', '08', '0123'):
        output = yaml.dump(value, Dumper=YAML12SafeDumper)
        reloaded = yaml.load(output, Loader=YAML12SafeLoader)
        assert reloaded == value and type(reloaded) is str
        assert output.lstrip().startswith(("'", '"'))

    # Strings that are text under both schemas stay plain and still reload as
    # strings under the core rules.
    for value in ('on', 'yes', '0b1010', '1_000', '2001-12-15', 'inf'):
        output = yaml.dump(value, Dumper=YAML12SafeDumper)
        reloaded = yaml.load(output, Loader=YAML12SafeLoader)
        assert reloaded == value and type(reloaded) is str


def test_safe_dumper_round_trip_under_matching_1_1_loader():
    # The classic SafeLoader/SafeDumper pair remains self-consistent.
    output = yaml.safe_dump(RICH_DATA, sort_keys=True)
    reloaded = yaml.safe_load(output)
    _assert_equal_values_and_types(RICH_DATA, reloaded)


def test_safe_dumper_output_reloaded_with_core_loader_intersection():
    # Values that mean the same thing under both schemas round-trip across
    # the pair without losing value or type.
    shared = {
        'int': 42, 'float': 3.5, 'bool': True, 'none': None,
        'string': 'on', 'list': [1, True, None, 'on'],
        'inf': float('inf'),
    }
    output = yaml.safe_dump(shared)
    reloaded = yaml.load(output, Loader=YAML12SafeLoader)
    _assert_equal_values_and_types(shared, reloaded)


def test_cross_schema_dump_needs_paired_dumper_for_core_only_strings():
    # The YAML 1.1 SafeDumper does not know the core-only numeric forms, so
    # their string form is emitted plain and a core reload changes the type.
    for value, reloaded_type in [('1e3', float), ('0o17', int), ('08', int)]:
        output = yaml.safe_dump(value)
        assert type(yaml.load(output, Loader=YAML12SafeLoader)) is \
            reloaded_type
        # The paired core dumper keeps the string type instead.
        paired = yaml.dump(value, Dumper=YAML12SafeDumper)
        reloaded = yaml.load(paired, Loader=YAML12SafeLoader)
        assert type(reloaded) is str and reloaded == value

    # A 1.1 timestamp carries no explicit tag and therefore becomes text on a
    # core reload; the paired dumper emits an explicit !!timestamp instead.
    date_value = datetime.date(2001, 12, 15)
    assert type(yaml.load(yaml.safe_dump(date_value),
                          Loader=YAML12SafeLoader)) is str
    paired = yaml.dump(date_value, Dumper=YAML12SafeDumper)
    assert '!!timestamp' in paired
    assert yaml.load(paired, Loader=YAML12SafeLoader) == date_value


def test_convenience_functions_round_trip():
    data = {'on': 'on', 'yes': 'yes', 'number': 0o17, 'flag': True,
            'time': datetime.date(2001, 12, 15)}
    output = yaml.yaml12_dump(data, sort_keys=True)
    assert yaml.yaml12_load(output) == data
    assert list(yaml.yaml12_load_all(yaml.yaml12_dump_all([data, data]))) == \
        [data, data]


def test_empty_documents_remain_null_under_core():
    assert yaml.load('', Loader=YAML12SafeLoader) is None
    assert list(yaml.load_all('---\n---\n', Loader=YAML12SafeLoader)) == \
        [None, None]


def test_core_resolver_table_matches_published_schema():
    expected_first_chars = {
        '~', 'n', 'N', '', 't', 'T', 'f', 'F',
        '-', '+', '0', '1', '2', '3', '4', '5', '6', '7', '8', '9', '.',
    }
    assert set(CORE_IMPLICIT_RESOLVERS) == expected_first_chars
    assert YAML12CoreResolver().yaml_implicit_resolvers is not \
        CORE_IMPLICIT_RESOLVERS


CORE_MATRIX_PATH = Path(__file__).parent / 'data' / 'schema-core.yaml'


def _matrix_source(key):
    if key == '#empty':
        return ''
    if key.endswith(' #empty'):
        return key[:-len(' #empty')]
    return key


def _matrix_value_matches(value, expected_type, expected_data):
    if expected_type == 'null':
        return value is None
    if expected_type == 'bool':
        return value is (expected_data == 'true()')
    if expected_type == 'int':
        return (type(value) is int and value == int(expected_data))
    if expected_type == 'float':
        return type(value) is float and value == float(expected_data)
    if expected_type == 'inf':
        return (type(value) is float and value ==
                (INF if expected_data == 'inf()' else -INF))
    if expected_type == 'nan':
        return type(value) is float and math.isnan(value)
    if expected_type == 'str':
        return type(value) is str and value == expected_data
    raise AssertionError('unknown core matrix type: %r' % (expected_type,))


def test_full_published_core_schema_matrix():
    with CORE_MATRIX_PATH.open('rb') as stream:
        matrix = yaml.safe_load(stream)

    failures = []
    for key, expected in sorted(matrix.items()):
        source = _matrix_source(key)
        if expected == 'error':
            try:
                yaml.load(source, Loader=YAML12SafeLoader)
            except ConstructorError:
                pass
            else:
                failures.append('%r: expected ConstructorError' % key)
            continue

        expected_type, expected_data, expected_dump = expected
        try:
            value = yaml.load(source, Loader=YAML12SafeLoader)
        except Exception as exc:
            failures.append('%r: load raised %s: %s'
                            % (key, type(exc).__name__, exc))
            continue
        if not _matrix_value_matches(value, expected_type, expected_data):
            failures.append('%r: %r (%s) is not %s %r'
                            % (key, value, type(value).__name__,
                               expected_type, expected_data))
            continue

        dumped = yaml.dump(value, Dumper=YAML12SafeDumper)
        if dumped.endswith('\n...\n'):
            dumped = dumped[:-5]
        if dumped.endswith('\n'):
            dumped = dumped[:-1]
        if dumped != expected_dump:
            failures.append('%r: dump %r != %r'
                            % (key, dumped, expected_dump))

    assert not failures, '\n'.join(failures)
