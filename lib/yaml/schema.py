
__all__ = [
    'CORE_IMPLICIT_RESOLVERS',
    'YAML12CoreResolver',
    'YAML12CoreConstructor',
    'YAML12SafeLoader',
    'YAML12FullLoader',
    'YAML12Loader',
    'YAML12SafeDumper',
    'YAML12Dumper',
]

import re
from types import MappingProxyType

from .composer import Composer
from .constructor import (
    SafeConstructor,
    FullConstructor,
    UnsafeConstructor,
    ConstructorError,
)
from .emitter import Emitter
from .loader import Reader, Scanner, Parser
from .representer import SafeRepresenter, Representer
from .resolver import BaseResolver
from .serializer import Serializer


# YAML 1.2.2 core schema tag resolution (section 10.3.2).  Unlike the YAML
# 1.1 rules used by `Resolver`, `on`/`off`/`yes`/`no` are plain strings,
# sexagesimal numbers and binary integers do not resolve implicitly, and
# timestamps are not part of the core schema.  Explicit tags are unaffected
# by implicit resolution and still reach the matching constructors.
_NULL_RE = re.compile(r'^(?:null|Null|NULL|~|)$')
_BOOL_RE = re.compile(r'^(?:true|True|TRUE|false|False|FALSE)$')
# Decimal integers may have leading zeros in the core schema, but octal
# (`0o`) and hexadecimal (`0x`) prefixes carry no sign.
_INT_RE = re.compile(
    r'^(?:[-+]?[0-9]+|0o[0-7]+|0x[0-9a-fA-F]+)$'
)
_FLOAT_RE = re.compile(
    r'^(?:[-+]?(?:\.[0-9]+|[0-9]+(?:\.[0-9]*)?)(?:[eE][-+]?[0-9]+)?'
    r'|[-+]?\.(?:inf|Inf|INF)'
    r'|\.(?:nan|NaN|NAN))$'
)


def _core_resolver_table():
    # Every call builds fresh containers so that loader instances never
    # share mutable resolver state with each other or with the class-level
    # tables used by the YAML 1.1 loaders.
    table = {}

    def add(tag, regexp, first):
        for char in first:
            table.setdefault(char, []).append((tag, regexp))

    add('tag:yaml.org,2002:null', _NULL_RE, ['~', 'n', 'N', ''])
    add('tag:yaml.org,2002:bool', _BOOL_RE, list('tTfF'))
    add('tag:yaml.org,2002:int', _INT_RE, list('-+0123456789'))
    add('tag:yaml.org,2002:float', _FLOAT_RE, list('-+0123456789.'))
    return table


# Immutable reference used as the template for each instance.  Entries are
# tuples of compiled regular expressions; every loader receives fresh list
# containers, so neither this template nor other instances can be changed
# through one loader's resolver table.
CORE_IMPLICIT_RESOLVERS = MappingProxyType({
    first: tuple(entries)
    for first, entries in _core_resolver_table().items()
})


class YAML12CoreResolver(BaseResolver):
    """Instance-scoped YAML 1.2 core schema resolver.

    The resolver tables are assigned in ``__init__`` instead of being built
    through the class-level ``add_implicit_resolver`` mechanism, so choosing
    the core schema for one loader cannot change ``SafeLoader``/``Loader``
    or any other loader.
    """

    def __init__(self):
        super().__init__()
        self.yaml_implicit_resolvers = {
            first: list(entries)
            for first, entries in CORE_IMPLICIT_RESOLVERS.items()
        }
        self.yaml_path_resolvers = {}


class YAML12CoreConstructor(SafeConstructor):
    """Core schema constructors with strict explicit-tag validation.

    Implicit resolution already guarantees that core scalars match the
    YAML 1.2 regular expressions.  Explicit tags bypass resolution, so the
    bool/int/float constructors re-check the core rules and raise
    ``ConstructorError`` on values that are not valid for the tag instead
    of silently accepting YAML 1.1 forms (for example ``!!bool on`` or
    ``!!int 0b10``).
    """

    def construct_yaml_null(self, node):
        value = self.construct_scalar(node)
        if not _NULL_RE.match(value):
            raise ConstructorError(
                None, None,
                "invalid YAML 1.2 core null %r (expected one of "
                "null/Null/NULL/~ or an empty scalar)" % value,
                node.start_mark,
            )
        return None

    def construct_yaml_timestamp(self, node):
        # Timestamps are not part of the core implicit resolution table;
        # an explicit ``!!timestamp`` tag still reaches this constructor.
        # Normalize lexical and calendar failures into ConstructorError so
        # bad explicit tags never leak low-level ValueError/AttributeError.
        if not self.timestamp_regexp.match(node.value):
            raise ConstructorError(
                None, None,
                "invalid timestamp %r" % node.value, node.start_mark)
        try:
            return super().construct_yaml_timestamp(node)
        except (ValueError, OverflowError) as exc:
            raise ConstructorError(
                None, None,
                "invalid timestamp %r: %s" % (node.value, exc),
                node.start_mark) from exc

    def construct_yaml_bool(self, node):
        value = self.construct_scalar(node)
        if not _BOOL_RE.match(value):
            raise ConstructorError(
                None, None,
                "invalid YAML 1.2 core bool %r (expected one of "
                "true/True/TRUE/false/False/FALSE)" % value,
                node.start_mark,
            )
        return value in ('true', 'True', 'TRUE')

    def construct_yaml_int(self, node):
        value = self.construct_scalar(node)
        if not _INT_RE.match(value):
            raise ConstructorError(
                None, None,
                "invalid YAML 1.2 core int %r" % value,
                node.start_mark,
            )
        sign = 1
        if value[0] == '-':
            sign = -1
        if value[0] in '+-':
            value = value[1:]
        if value == '0':
            return 0
        if value.startswith('0o'):
            return sign * int(value[2:], 8)
        if value.startswith('0x'):
            return sign * int(value[2:], 16)
        return sign * int(value)

    def construct_yaml_float(self, node):
        value = self.construct_scalar(node)
        if not _FLOAT_RE.match(value):
            raise ConstructorError(
                None, None,
                "invalid YAML 1.2 core float %r" % value,
                node.start_mark,
            )
        sign = 1
        if value[0] == '-':
            sign = -1
        if value[0] in '+-':
            value = value[1:]
        value = value.lower()
        if value == '.inf':
            return sign * self.inf_value
        if value == '.nan':
            return self.nan_value
        return sign * float(value)


_CORE_CONSTRUCTORS = (
    ('null', YAML12CoreConstructor.construct_yaml_null),
    ('timestamp', YAML12CoreConstructor.construct_yaml_timestamp),
    ('bool', YAML12CoreConstructor.construct_yaml_bool),
    ('int', YAML12CoreConstructor.construct_yaml_int),
    ('float', YAML12CoreConstructor.construct_yaml_float),
)

# Each constructor class gets its own copy of the dispatch table (add_*
# copies on first use), so the rebinding never changes the YAML 1.1 classes.
for _name, _constructor in _CORE_CONSTRUCTORS:
    YAML12CoreConstructor.add_constructor(
        'tag:yaml.org,2002:' + _name, _constructor)


class YAML12FullConstructor(FullConstructor, YAML12CoreConstructor):
    pass


class YAML12UnsafeConstructor(UnsafeConstructor, YAML12CoreConstructor):
    pass


for _constructor_cls in (YAML12FullConstructor, YAML12UnsafeConstructor):
    for _name, _constructor in _CORE_CONSTRUCTORS:
        _constructor_cls.add_constructor(
            'tag:yaml.org,2002:' + _name, _constructor)
del _constructor_cls, _name, _constructor


class YAML12SafeLoader(Reader, Scanner, Parser, Composer,
        YAML12CoreConstructor, YAML12CoreResolver):
    """Safe loader resolving plain scalars with the YAML 1.2 core schema."""

    def __init__(self, stream):
        Reader.__init__(self, stream)
        Scanner.__init__(self)
        Parser.__init__(self)
        Composer.__init__(self)
        YAML12CoreConstructor.__init__(self)
        YAML12CoreResolver.__init__(self)


class YAML12FullLoader(Reader, Scanner, Parser, Composer,
        YAML12FullConstructor, YAML12CoreResolver):
    """YAML 1.2 core counterpart of :class:`FullLoader`."""

    def __init__(self, stream):
        Reader.__init__(self, stream)
        Scanner.__init__(self)
        Parser.__init__(self)
        Composer.__init__(self)
        YAML12FullConstructor.__init__(self)
        YAML12CoreResolver.__init__(self)


class YAML12Loader(Reader, Scanner, Parser, Composer,
        YAML12UnsafeConstructor, YAML12CoreResolver):
    """YAML 1.2 core counterpart of the unsafe :class:`Loader`."""

    def __init__(self, stream):
        Reader.__init__(self, stream)
        Scanner.__init__(self)
        Parser.__init__(self)
        Composer.__init__(self)
        YAML12UnsafeConstructor.__init__(self)
        YAML12CoreResolver.__init__(self)


class YAML12SafeDumper(Emitter, Serializer, SafeRepresenter,
        YAML12CoreResolver):
    """Safe dumper paired with the YAML 1.2 core resolution rules.

    The core resolver is what the serializer consults to decide whether a
    scalar's tag can stay implicit, so strings such as ``0o10`` or
    ``0123`` are quoted when needed and keep their type on a core-schema
    reload.
    """

    def __init__(self, stream,
            default_style=None, default_flow_style=False,
            canonical=None, indent=None, width=None,
            allow_unicode=None, line_break=None,
            encoding=None, explicit_start=None, explicit_end=None,
            version=None, tags=None, sort_keys=True):
        Emitter.__init__(self, stream, canonical=canonical,
                indent=indent, width=width,
                allow_unicode=allow_unicode, line_break=line_break)
        Serializer.__init__(self, encoding=encoding,
                explicit_start=explicit_start, explicit_end=explicit_end,
                version=version, tags=tags)
        SafeRepresenter.__init__(self, default_style=default_style,
                default_flow_style=default_flow_style, sort_keys=sort_keys)
        YAML12CoreResolver.__init__(self)


class YAML12Dumper(Emitter, Serializer, Representer, YAML12CoreResolver):
    """Unsafe dumper paired with the YAML 1.2 core resolution rules."""

    def __init__(self, stream,
            default_style=None, default_flow_style=False,
            canonical=None, indent=None, width=None,
            allow_unicode=None, line_break=None,
            encoding=None, explicit_start=None, explicit_end=None,
            version=None, tags=None, sort_keys=True):
        Emitter.__init__(self, stream, canonical=canonical,
                indent=indent, width=width,
                allow_unicode=allow_unicode, line_break=line_break)
        Serializer.__init__(self, encoding=encoding,
                explicit_start=explicit_start, explicit_end=explicit_end,
                version=version, tags=tags)
        Representer.__init__(self, default_style=default_style,
                default_flow_style=default_flow_style, sort_keys=sort_keys)
        YAML12CoreResolver.__init__(self)
