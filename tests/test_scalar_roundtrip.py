"""Standalone round-trip regression tests for PyYAML scalar emission.

Scope: line folding, indentation, trailing newlines and Unicode.

Every case asserts the exact emitted *value* (and type) survives
``dump`` -> ``load``; several cases also pin the expected style marker or
escape form so a silently changed emitter is caught.  Values are either
taken from the input object itself or spelled out from the YAML spec.
"""

import random

import pytest

import yaml


SEED = 0xC0FFEE


def dump_text(value, **kw):
    """Dump with text output and return the emitted document."""
    kw.setdefault("Dumper", yaml.SafeDumper)
    kw.setdefault("allow_unicode", True)
    text = yaml.dump(value, **kw)
    assert isinstance(text, str)
    return text


def assert_scalar_roundtrip(value, text=None, **kw):
    """Assert ``value`` (or the precomputed ``text``) loads back identically.

    Returns the loaded value.  Both the value and its exact type are
    compared, so ``1`` vs ``"1"`` or ``None`` vs ``""`` are caught.
    """
    if text is None:
        text = dump_text(value, **kw)
    loaded = yaml.safe_load(text)
    assert loaded == value, (
        "round-trip mismatch for %r: emitted %r, got %r" % (value, text, loaded))
    assert type(loaded) is type(value), (
        "type drift for %r: %r -> %r" % (value, type(value).__name__,
                                         type(loaded).__name__))
    return loaded


# ---------------------------------------------------------------------------
# plain style
# ---------------------------------------------------------------------------

PLAIN_VALUES = [
    "simple",
    "two words here",
    "a-b_c.d",
    "unicode 世界 héllo",
    "x" * 120,  # unbreakable long token
    "a b c d e f g h i j k l",  # folds at narrow width
    "😀 starts with non-BMP",
]


@pytest.mark.parametrize("value", PLAIN_VALUES)
def test_plain_roundtrip(value):
    text = dump_text(value, default_style="")
    assert_scalar_roundtrip(value, text)
    # plain output is bare: no quote or block-style marker at the start
    assert text[0] not in "'\"|>", text


def test_plain_width_folding():
    value = "a b c d e f g h i j k l"
    narrow = dump_text(value, default_style="", width=20)
    wide = dump_text(value, default_style="", width=100)
    assert "\n  " in narrow  # continuation line emitted
    assert "\n  " not in wide
    assert_scalar_roundtrip(value, narrow)
    assert_scalar_roundtrip(value, wide)


# ---------------------------------------------------------------------------
# single-quoted style
# ---------------------------------------------------------------------------

SINGLE_QUOTED_VALUES = [
    "it's",
    "a''b",
    "  leading spaces",
    "trailing spaces  ",
    " ",
    "  ",
    "plain ok 123 - x: y",  # ': ' forces quoting
    "multi\nline\nvalue",
]


@pytest.mark.parametrize("value", SINGLE_QUOTED_VALUES)
def test_single_quoted_roundtrip(value):
    text = dump_text(value, default_style="'")
    assert text.startswith("'"), text
    assert_scalar_roundtrip(value, text)


def test_single_quote_escaping():
    text = dump_text("it's", default_style="'")
    assert text == "'it''s'\n"
    assert_scalar_roundtrip("it's", text)


# ---------------------------------------------------------------------------
# double-quoted style
# ---------------------------------------------------------------------------

DOUBLE_QUOTED_VALUES = [
    "tab\there",
    "NUL\x00BEL\x07",
    "a\rb",  # CR is escaped
    "a\x0bb",  # VT
    "a\x7fb",  # DEL
    "a\x85b",  # NEL
    "a b c d",  # LS / PS
    "﻿ x",  # BOM char is always escaped
    "x￿f"[:-1] + "y",  # U+FFFF (non-character, still round-trips escaped)
    "x\ud800y",  # lone surrogate escapes and reloads as-is
    "x\U0010FFFFy",  # max scalar value
    "emoji \U0001F600\U0001F680 end",
]


@pytest.mark.parametrize("value", DOUBLE_QUOTED_VALUES)
def test_double_quoted_roundtrip(value):
    text = dump_text(value, default_style='"')
    assert text.startswith('"'), text
    assert_scalar_roundtrip(value, text)


def test_double_quoted_escape_forms():
    cases = {
        "a\x00b": '"a\\0b"\n',
        "a\tb": '"a\\tb"\n',
        "a\x85b c d": '"a\\Nb\\Lc\\Pd"\n',
        "﻿ x": '"\\uFEFF x"\n',
        "x\U0001F600y": '"x\\U0001F600y"\n',
    }
    for value, expected in cases.items():
        text = dump_text(value, default_style='"')
        assert text == expected
        assert_scalar_roundtrip(value, text)


def test_double_quoted_width_wrapping():
    value = "aaaa bbbb cccc dddd eeee"
    text = dump_text(value, default_style='"', width=10)
    assert "\\\n" in text  # backslash continuation lines
    assert_scalar_roundtrip(value, text)


# ---------------------------------------------------------------------------
# block scalars: chomping / indentation / trailing-newline matrix
# ---------------------------------------------------------------------------

BLOCK_VALUES = ["a\nb", "a\nb\n", "a\nb\n\n", "a\nb\n\n\n"]
BLOCK_STYLES = ["|", ">"]
# expected chomping hint derived from the trailing-newline count
CHOMP_HINTS = ["-", "", "+", "+"]


@pytest.mark.parametrize("style", BLOCK_STYLES, ids=["literal", "folded"])
@pytest.mark.parametrize("value,hint", list(zip(BLOCK_VALUES, CHOMP_HINTS)))
def test_block_chomping_matrix(style, value, hint):
    text = dump_text(value, default_style=style)
    marker = text.split("\n", 1)[0]
    assert marker == style + hint, (style, value, text)
    assert_scalar_roundtrip(value, text)


@pytest.mark.parametrize("style", ["|", ">"])
def test_block_blank_lines(style):
    for value in [
        "aa bb\n\ncc dd\n",
        "aa bb\n\n\ncc dd\n",
        "line1\n\n  indented\nline2\n",
    ]:
        assert_scalar_roundtrip(value, dump_text(value, default_style=style))


@pytest.mark.parametrize("style", ["|", ">"])
def test_block_leading_space_indent_indicator(style):
    # an explicit indentation indicator is required for leading whitespace
    text = dump_text("  indented line\nnext\n", default_style=style)
    assert text.split("\n", 1)[0] == style + "2", text
    assert_scalar_roundtrip("  indented line\nnext\n", text)

    text = dump_text("\nleading blank line\n", default_style=style)
    assert text.split("\n", 1)[0] == style + "2", text
    assert_scalar_roundtrip("\nleading blank line\n", text)


def test_literal_preserves_content_verbatim():
    value = "  spaced  x?\n  second line\n"
    text = dump_text(value, default_style="|")
    assert text == "|2\n    spaced  x?\n    second line\n"
    assert_scalar_roundtrip(value, text)


def test_literal_trailing_space_falls_back_to_quoted():
    # block scalars cannot hold a line-ending space; the emitter must
    # downgrade instead of silently dropping it
    value = "a \nb"
    text = dump_text(value, default_style="|")
    assert text.startswith('"'), text
    assert_scalar_roundtrip(value, text)


def test_folded_collapses_single_newlines_keeps_blanks():
    value = "aaaa bbbb cccc dddd eeee"
    text = dump_text(value, default_style=">", width=10)
    assert text == ">-\n  aaaa bbbb\n  cccc dddd\n  eeee\n"
    assert_scalar_roundtrip(value, text)

    multiline = "aa bb\ncc\n"
    text = dump_text(multiline, default_style=">")
    assert text == ">\n  aa bb\n\n  cc\n"
    assert_scalar_roundtrip(multiline, text)


@pytest.mark.parametrize("indent", [2, 4, 8])
def test_indent_applies_to_block_scalar_content(indent):
    value = ["a\nb\n"]
    text = dump_text(value, default_style="|", indent=indent)
    pad = " " * indent
    assert ("\n" + pad + "a\n") in text, text
    assert_scalar_roundtrip(value, text)


def test_empty_and_whitespace_scalars():
    for value in ["", " ", "  ", "\n", "a\n", "a\n\n"]:
        for style in ["", "'", '"', "|", ">"]:
            assert_scalar_roundtrip(value, dump_text(value, default_style=style))


# ---------------------------------------------------------------------------
# Unicode: BMP, non-BMP, combining, special breaks
# ---------------------------------------------------------------------------

UNICODE_VALUES = [
    "héllo 世界",  # BMP
    "a b",  # NBSP
    "é",  # combining accent
    "a b",  # LS (preserved verbatim in PyYAML)
    "a b",  # PS
    "😀\U0001F680",  # non-BMP
    "\U0010FFFF",  # max scalar value
]


@pytest.mark.parametrize("value", UNICODE_VALUES)
@pytest.mark.parametrize("allow_unicode", [True, False])
def test_unicode_roundtrip(value, allow_unicode):
    text = dump_text(value, allow_unicode=allow_unicode)
    assert_scalar_roundtrip(value, text)
    assert "�" not in text  # no replacement-character masking


def test_allow_unicode_controls_raw_bytes():
    value = "héllo 世界 \U0001F600"
    raw = dump_text(value, allow_unicode=True)
    escaped = dump_text(value, allow_unicode=False)
    assert "世界" in raw  # BMP emitted literally
    assert "\\u4E16" in escaped and "\\U0001F600" in escaped
    assert_scalar_roundtrip(value, raw)
    assert_scalar_roundtrip(value, escaped)


def test_double_quoted_escapes_non_bmp_even_when_allowed():
    value = "x\U0001F600y"
    for allow_unicode in (True, False):
        text = dump_text(value, default_style='"',
                         allow_unicode=allow_unicode)
        assert text == '"x\\U0001F600y"\n'
        assert_scalar_roundtrip(value, text)


def test_nel_survives_only_when_double_quoted():
    # U+0085 NEL is a YAML line break: raw NEL gets normalized on load,
    # so only the double-quoted escape form preserves the scalar value.
    value = "a\x85b"
    assert_scalar_roundtrip(value, dump_text(value, default_style='"'))

    single = dump_text(value, default_style="'")
    literal = dump_text(value, default_style="|")
    assert yaml.safe_load(single) == "a b"  # folded to a space
    assert yaml.safe_load(literal) == "a\nb"  # normalized to LF


# ---------------------------------------------------------------------------
# output encodings (bytes)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("encoding", ["utf-8", "utf-16-le", "utf-16-be"])
def test_bytes_output_encoding(encoding):
    value = "héllo 世界\nline two\n"
    out = yaml.dump(value, Dumper=yaml.SafeDumper, allow_unicode=True,
                    encoding=encoding)
    assert isinstance(out, bytes)
    assert_scalar_roundtrip(value, out)


def test_utf16_byte_order_mark():
    out = yaml.dump("abc", Dumper=yaml.SafeDumper, encoding="utf-16-le")
    assert out.startswith(b"\xff\xfe")
    assert yaml.safe_load(out) == "abc"


def test_latin1_bytes_output():
    out = yaml.dump("héllo", Dumper=yaml.SafeDumper, allow_unicode=True,
                    encoding="latin-1")
    assert isinstance(out, bytes) and b"h\xe9llo" in out
    # latin-1 bytes carry no BOM; decode explicitly before loading
    assert yaml.safe_load(out.decode("latin-1")) == "héllo"


@pytest.mark.parametrize("value,encoding", [
    ("héllo", "ascii"),
    ("Ā", "latin-1"),
    ("😀", "latin-1"),
])
def test_unencodable_output_raises(value, encoding):
    # an impossible encoding must fail loudly, never emit U+FFFD
    with pytest.raises(UnicodeEncodeError) as excinfo:
        yaml.dump(value, Dumper=yaml.SafeDumper, allow_unicode=True,
                  encoding=encoding)
    assert excinfo.value.encoding == encoding
    assert "�" not in str(excinfo.value.object)


# ---------------------------------------------------------------------------
# forbidden code points / bad encodings: reject instead of substituting
# ---------------------------------------------------------------------------

RAW_REJECTIONS = [
    (b"a: \xff\n", "invalid UTF-8 byte"),
    ("a: x\ud800y\n", "lone surrogate"),
    ("a: x￿y\n", "non-character U+FFFF"),
    ("a: \x07b\n", "C0 control BEL"),
    ("a: \x7fb\n", "DEL"),
]


@pytest.mark.parametrize("document,label", RAW_REJECTIONS)
def test_reader_rejects_forbidden_input(document, label):
    with pytest.raises(yaml.reader.ReaderError) as excinfo:
        yaml.safe_load(document)
    # exception ownership: ReaderError is the YAML-specific class
    assert type(excinfo.value).__module__ == "yaml.reader"
    assert isinstance(excinfo.value, yaml.YAMLError)
    assert "unacceptable character" in str(excinfo.value)


@pytest.mark.parametrize("value,escape", [
    ("x\ud800y", "\\uD800"),
    ("x￿f"[:-1] + "y", "\\uFFFF"),
    ("a\x07b", "\\a"),
    ("a\x7fb", "\\x7F"),
])
def test_escaped_forms_of_forbidden_code_points_roundtrip(value, escape):
    # the same code points survive only when properly escaped on output
    text = dump_text(value, default_style='"')
    assert escape in text
    assert "�" not in text
    assert_scalar_roundtrip(value, text)


# ---------------------------------------------------------------------------
# explicit spec cases (YAML 1.1 chapter 2 / 9 examples)
# ---------------------------------------------------------------------------

SPEC_02_15 = """ >
  Sammy Sosa completed another
  fine season with great stats.

    63 Home Runs
    0.288 Batting Average

  What a year!
"""
SPEC_02_15_VALUE = (
    "Sammy Sosa completed another fine season with great stats.\n\n"
    "  63 Home Runs\n  0.288 Batting Average\n\nWhat a year!\n"
)

SPEC_09_18 = """
- | # Just the style
  literal
- >1 # Indentation indicator
  folded
- |+ # Chomping indicator
  keep

- >-1 # Both indicators
  strip
"""
SPEC_09_18_VALUE = ["literal\n", " folded\n", "keep\n\n", " strip"]

SPEC_09_29 = "> # Simple folded scalar\n folded\n text\n \tlines\n"
SPEC_09_29_VALUE = "folded text\n\tlines\n"


@pytest.mark.parametrize("document,expected", [
    (SPEC_02_15, SPEC_02_15_VALUE),
    (SPEC_09_29, SPEC_09_29_VALUE),
])
def test_spec_folded_cases(document, expected):
    loaded = yaml.safe_load(document)
    assert loaded == expected
    assert type(loaded) is str
    # and the parsed value must itself round-trip
    assert_scalar_roundtrip(loaded)


def test_spec_indent_and_chomp_indicators():
    assert yaml.safe_load(SPEC_09_18) == SPEC_09_18_VALUE
    for value in SPEC_09_18_VALUE:
        assert_scalar_roundtrip(value)


# ---------------------------------------------------------------------------
# the guard must actually catch lossy output (mutation checks)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("value", ["a\n", "a\n\n", "line\ntail\n"])
def test_guard_detects_dropped_trailing_newline(value):
    good = dump_text(value, default_style="|")
    assert_scalar_roundtrip(value, good)

    buggy = dump_text(value[:-1], default_style="|")
    with pytest.raises(AssertionError):
        assert_scalar_roundtrip(value, buggy)


def test_guard_detects_truncated_keep_chomp_block():
    value = "a\n\n"
    text = dump_text(value, default_style="|")
    assert text == "|+\n  a\n\n...\n"
    assert_scalar_roundtrip(value, text)

    truncated = text.replace("\n\n...\n", "\n...\n")  # lose one blank line
    assert yaml.safe_load(truncated) != value
    with pytest.raises(AssertionError):
        assert_scalar_roundtrip(value, truncated)


def test_guard_detects_type_drift():
    # the type assertion catches string/number or string/null confusion
    assert_scalar_roundtrip("123", dump_text("123"))
    with pytest.raises(AssertionError):
        assert_scalar_roundtrip("123", "123\n")


# ---------------------------------------------------------------------------
# deterministic boundary corpus (fixed seed)
# ---------------------------------------------------------------------------

def _corpus():
    rng = random.Random(SEED)
    # NEL is intentionally excluded: raw NEL is normalized on load, see
    # test_nel_survives_only_when_double_quoted
    alphabet = "ab \n\t'\"-:#" + "hé世界😀   "
    return [
        "".join(rng.choice(alphabet) for _ in range(rng.randrange(0, 14)))
        for _ in range(24)
    ]


CORPUS = _corpus()


@pytest.mark.parametrize("value", CORPUS)
def test_seeded_boundary_matrix(value):
    for style in ["", "'", '"', "|", ">"]:
        for width in (10, 40):
            text = dump_text(value, default_style=style, width=width)
            assert "�" not in text
            assert_scalar_roundtrip(value, text)


def test_seeded_corpus_is_deterministic():
    assert CORPUS == _corpus()
    assert len(CORPUS) == 24

