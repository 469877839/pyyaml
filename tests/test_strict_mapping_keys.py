import pytest

import yaml


def loader_classes():
    classes = [yaml.SafeLoader, yaml.FullLoader]
    if hasattr(yaml, "CSafeLoader"):
        classes.append(yaml.CSafeLoader)
        classes.append(yaml.CFullLoader)
    return classes


TWIN_CONFLICTS = """\
defaults: &defaults
  timeout: 30
  retries: 3
service:
  <<: *defaults
  timeout: 60
  retries: 3
  retries: 5
logging:
  level: info
  level: debug
"""


@pytest.mark.parametrize("Loader", loader_classes())
def test_strict_reports_both_positions_and_default_keeps_last(Loader):
    default = yaml.load(TWIN_CONFLICTS, Loader=Loader)
    assert default == {
        "defaults": {"timeout": 30, "retries": 3},
        "service": {"timeout": 60, "retries": 5},
        "logging": {"level": "debug"},
    }

    with pytest.raises(yaml.constructor.ConstructorError) as excinfo:
        yaml.load(TWIN_CONFLICTS, Loader=Loader, strict_mapping_keys=True)

    error = excinfo.value
    assert error.problem == "found duplicate key 'retries'"
    assert (error.problem_mark.line, error.problem_mark.column) == (7, 2)
    assert "line 7" in error.note
    assert (error.context_mark.line, error.context_mark.column) == (4, 2)

    with pytest.raises(yaml.constructor.ConstructorError) as excinfo:
        yaml.safe_load("logging:\n  level: info\n  level: debug\n",
                strict_mapping_keys=True)
    error = excinfo.value
    assert error.problem == "found duplicate key 'level'"
    assert (error.problem_mark.line, error.problem_mark.column) == (2, 2)
    assert "line 2" in error.note


@pytest.mark.parametrize("Loader", loader_classes())
def test_duplicate_explicit_key_rejected(Loader):
    with pytest.raises(yaml.constructor.ConstructorError):
        yaml.load("a: 1\na: 2\n", Loader=Loader, strict_mapping_keys=True)
    assert yaml.load("a: 1\na: 2\n", Loader=Loader) == {"a": 2}


@pytest.mark.parametrize("Loader", loader_classes())
def test_merge_override_is_not_a_duplicate(Loader):
    source = """\
base: &base {x: 1}
target:
  <<: *base
  x: 2
"""
    assert yaml.load(source, Loader=Loader, strict_mapping_keys=True) == {
        "base": {"x": 1}, "target": {"x": 2}}


@pytest.mark.parametrize("Loader", loader_classes())
def test_multiple_merge_sources_keep_first_precedence(Loader):
    source = """\
a: &a {x: 1}
b: &b {x: 2}
target:
  <<: [*a, *b]
"""
    assert yaml.load(source, Loader=Loader, strict_mapping_keys=True) == {
        "a": {"x": 1}, "b": {"x": 2}, "target": {"x": 1}}


@pytest.mark.parametrize("Loader", loader_classes())
def test_repeated_merge_source_is_not_a_duplicate(Loader):
    source = """\
base: &base {x: 1}
target:
  <<: [*base, *base]
  y: 2
"""
    assert yaml.load(source, Loader=Loader, strict_mapping_keys=True) == {
        "base": {"x": 1}, "target": {"x": 1, "y": 2}}


@pytest.mark.parametrize("Loader", loader_classes())
def test_duplicate_inside_inline_merge_source_is_rejected(Loader):
    with pytest.raises(yaml.constructor.ConstructorError):
        yaml.load("target: {<<: {x: 1, x: 2}}\n", Loader=Loader,
                strict_mapping_keys=True)
    assert yaml.load("target: {<<: {x: 1, x: 2}}\n", Loader=Loader) == {
        "target": {"x": 1}}


@pytest.mark.parametrize("Loader", loader_classes())
def test_equality_uses_constructed_keys(Loader):
    # True == 1, so these collide in the resulting dict.
    with pytest.raises(yaml.constructor.ConstructorError):
        yaml.load("t: {true: 1, 1: 2}\n", Loader=Loader,
                strict_mapping_keys=True)
    # Same text with different tags constructs different keys.
    assert yaml.load("t: {!!str 1: 1, 1: 2}\n", Loader=Loader,
            strict_mapping_keys=True) == {"t": {"1": 1, 1: 2}}


@pytest.mark.parametrize("Loader", loader_classes())
def test_unhashable_key_keeps_existing_error(Loader):
    with pytest.raises(yaml.constructor.ConstructorError, match="unhashable"):
        yaml.load("t: {[a]: 1}\n", Loader=Loader, strict_mapping_keys=True)
    with pytest.raises(yaml.constructor.ConstructorError, match="unhashable"):
        yaml.load("t: {[a]: 1}\n", Loader=Loader)


@pytest.mark.parametrize("Loader", loader_classes())
def test_anchor_cycles_keep_their_context(Loader):
    source = """\
a: &a
  b: &b
    <<: *a
  x: 1
"""
    result = yaml.load(source, Loader=Loader, strict_mapping_keys=True)
    nested = result["a"]["b"]
    assert nested["b"] is nested
    assert nested["x"] == 1
    assert result["a"]["x"] == 1


@pytest.mark.parametrize("Loader", loader_classes())
def test_self_merge_is_not_a_duplicate(Loader):
    source = "a: &a\n  <<: *a\n  x: 1\n"
    assert yaml.load(source, Loader=Loader, strict_mapping_keys=True) == {
        "a": {"x": 1}}


@pytest.mark.parametrize("Loader", loader_classes())
def test_custom_constructor_keeps_diagnostic_context(Loader):
    class StrictLoader(Loader):
        pass

    def construct_widget(loader, node):
        return {"widget": loader.construct_mapping(node)}

    StrictLoader.add_constructor("!widget", construct_widget)
    with pytest.raises(yaml.constructor.ConstructorError) as excinfo:
        yaml.load("!widget\nk: 1\nk: 2\n", Loader=StrictLoader,
                strict_mapping_keys=True)
    error = excinfo.value
    assert error.problem_mark.line == 2
    assert "line 2" in error.note


def test_loader_instance_flag_and_multi_documents():
    loader = yaml.SafeLoader("a: 1\n", strict_mapping_keys=True)
    assert loader.strict_mapping_keys is True
    loader.dispose()

    stream = yaml.safe_load_all("ok: 1\n---\na: 1\na: 2\n",
            strict_mapping_keys=True)
    assert next(stream) == {"ok": 1}
    with pytest.raises(yaml.constructor.ConstructorError):
        next(stream)


def test_strict_mode_off_by_default():
    assert yaml.SafeLoader("a: 1\n").strict_mapping_keys is False
