import io

import pytest

import yaml


CHUNK_SIZES = (1, 2, 3, 4, 7, 16, 4096)


def _recover(stream, chunk_size=4096, **kwargs):
    return list(yaml.load_all_recover(stream, chunk_size=chunk_size, **kwargs))


def _is_error(item):
    return isinstance(item, yaml.DocumentRecoveryError)


def _is_abort(item):
    return isinstance(item, yaml.RecoveryAborted)


@pytest.mark.parametrize('chunk_size', CHUNK_SIZES)
def test_good_bad_good(chunk_size):
    text = "good: 1\n---\nbad: [\n---\nlast: 3\n"
    result = _recover(text, chunk_size=chunk_size)

    assert len(result) == 3
    assert result[0] == {'good': 1}
    assert _is_error(result[1])
    assert result[2] == {'last': 3}

    failure = result[1]
    assert failure.document_index == 1
    assert isinstance(failure.error, yaml.YAMLError)
    # The bad segment starts at its '---' line and ends at the next one.
    assert failure.start.index == 8
    assert failure.start.line == 1
    assert failure.error_position.line == 2 + 1  # absolute line 3
    assert failure.discarded_start.index == 8
    assert failure.discarded_end.index == 19
    assert failure.discarded_chars == 11
    assert 'document 1' in str(failure)


@pytest.mark.parametrize('chunk_size', CHUNK_SIZES)
def test_pseudo_separator_inside_quoted_scalar(chunk_size):
    text = "a: \"x --- y\"\nb: 'p ... q'\n---\nc: 3\n"
    result = _recover(text, chunk_size=chunk_size)
    assert result == [{'a': 'x --- y', 'b': 'p ... q'}, {'c': 3}]


@pytest.mark.parametrize('chunk_size', CHUNK_SIZES)
def test_pseudo_separator_inside_block_scalar(chunk_size):
    text = "a: |\n  ---\n  ...x\n  text\n---\nc: 3\n"
    result = _recover(text, chunk_size=chunk_size)
    assert len(result) == 2
    assert result[0]['a'] == '---\n...x\ntext\n'
    assert result[1] == {'c': 3}


@pytest.mark.parametrize('chunk_size', CHUNK_SIZES)
def test_pseudo_separator_in_plain_scalar_and_flow(chunk_size):
    plain = "----\n...x\n---\nc: 3\n"
    result = _recover(plain, chunk_size=chunk_size)
    assert result == ['---- ...x', {'c': 3}]

    flow = "a: [\n  '---',\n  \"...\"\n]\n---\nc: 3\n"
    result = _recover(flow, chunk_size=chunk_size)
    assert result == [{'a': ['---', '...']}, {'c': 3}]


@pytest.mark.parametrize('chunk_size', CHUNK_SIZES)
def test_anchors_and_directives_do_not_leak(chunk_size):
    text = "a: &x 1\nb: *x\n---\na: 2\n---\nc: *x\n"
    result = _recover(text, chunk_size=chunk_size)
    assert result[0] == {'a': 1, 'b': 1}
    assert result[1] == {'a': 2}
    assert _is_error(result[2])
    assert 'undefined alias' in str(result[2].error)

    directives = "%YAML 1.1\n---\na: 1\n---\nb: 2\n"
    result = _recover(directives, chunk_size=chunk_size)
    assert result == [{'a': 1}, {'b': 2}]


@pytest.mark.parametrize('chunk_size', CHUNK_SIZES)
def test_error_recovery_crlf(chunk_size):
    text = "a: 1\r\n---\r\nbad: [\r\n---\r\nc: 3\r\n"
    result = _recover(text, chunk_size=chunk_size)
    assert result[0] == {'a': 1}
    assert _is_error(result[1])
    assert result[2] == {'c': 3}


@pytest.mark.parametrize('chunk_size', CHUNK_SIZES)
def test_empty_documents(chunk_size):
    result = _recover("---\n---\n---\n", chunk_size=chunk_size)
    assert result == [None, None, None]


@pytest.mark.parametrize('chunk_size', CHUNK_SIZES)
def test_document_end_marker(chunk_size):
    assert _recover("a: 1\n...\n---\nb: 2\n", chunk_size=chunk_size) == \
            [{'a': 1}, {'b': 2}]
    assert _recover("a: 1\n...\n# note\n---\nb: 2\n",
            chunk_size=chunk_size) == [{'a': 1}, {'b': 2}]
    assert _recover("a: 1\n...\n%YAML 1.1\n---\nb: 2\n",
            chunk_size=chunk_size) == [{'a': 1}, {'b': 2}]


def test_load_all_still_stops_on_error():
    text = "good: 1\n---\nbad: [\n---\nlast: 3\n"
    with pytest.raises(yaml.YAMLError):
        list(yaml.load_all(text, yaml.SafeLoader))


def test_streaming_does_not_read_full_stream_upfront():
    class SlowTextStream(io.StringIO):
        def __init__(self, data):
            super().__init__(data)
            self.read_sizes = []

        def read(self, size=-1):
            self.read_sizes.append(size)
            return super().read(size)

    stream = SlowTextStream("a: 1\n---\nbad: [\n---\nc: 3\n")
    generator = yaml.load_all_recover(stream, chunk_size=4)
    first = next(generator)
    assert first == {'a': 1}
    assert stream.tell() < len(stream.getvalue())
    assert len(stream.read_sizes) > 1
    rest = [type(item).__name__ for item in generator]
    assert rest == ['DocumentRecoveryError', 'dict']


def test_binary_stream_recovery():
    data = "a: 1\n---\nb: 2\n---\n".encode() + b"bad: \xff\n---\nc: 4\n"
    result = _recover(data, chunk_size=5)
    assert result[0] == {'a': 1}
    assert result[1] == {'b': 2}
    assert _is_error(result[2])
    from yaml.reader import ReaderError
    assert isinstance(result[2].error, ReaderError)
    assert result[2].error_position.line == 4  # 1-based line
    assert result[3] == {'c': 4}


def test_scan_limit_aborts_without_timely_boundary():
    # After a failed document, the region scanned while searching for the
    # next provable boundary is bounded.  Here the next document start is
    # more than max_scan_chars away from the failure.
    tail = ("# padding\n" * 40)
    text = "good: 1\n---\nbad: [\n---\n" + tail + "---\nlate: 4\n"
    result = _recover(text, chunk_size=64, max_scan_chars=100)
    assert any(_is_abort(item) for item in result)
    abort = next(item for item in result if _is_abort(item))
    assert abort.limit == 100
    assert abort.scanned > 100
    assert abort.position.index > 0

    # A boundary reached within the budget keeps recovery going and resets it.
    bounded = "good: 1\n---\nbad: [\n---\n" + ("x" * 50) + "\n---\nlate: 4\n"
    result = _recover(bounded, chunk_size=64, max_scan_chars=100)
    assert not any(_is_abort(item) for item in result)
    assert result[-1] == {'late': 4}

    # Disabling the limit always yields regular results, never aborts.
    result = _recover(text, chunk_size=64, max_scan_chars=None)
    assert not any(_is_abort(item) for item in result)


def test_large_valid_document_not_limited():
    text = "big: |\n" + ("  row\n" * 3000) + "---\nnext: true\n"
    result = _recover(text, chunk_size=64, max_scan_chars=100)
    assert not any(_is_abort(item) for item in result)
    assert result[0]['big'].count('row') == 3000
    assert result[1] == {'next': True}


def test_safe_alias_matches_main_entry():
    result = list(yaml.safe_load_all_recover("a: 1\n---\nb: [\n---\nc: 3\n"))
    assert result[0] == {'a': 1}
    assert _is_error(result[1])
    assert result[2] == {'c': 3}


def test_valid_stream_matches_safe_load_all():
    text = "a: 1\n---\nb: 2\n---\nc: 3\n"
    assert _recover(text) == list(yaml.safe_load_all(text))


def test_unrecoverable_forms_are_reported_not_guessed():
    # Free content after '...' without a new '---' has no provable boundary.
    result = _recover("a: 1\n...\nb: 2\n---\nc: 3\n")
    assert result[0] == {'a': 1}
    assert _is_error(result[1])
    assert result[2] == {'c': 3}

    # An unterminated quoted scalar consumes up to the next real boundary;
    # that boundary is still respected, so the following document survives.
    result = _recover("a: \"unclosed\n---\nb: 2\n")
    assert _is_error(result[0])
    assert result[1] == {'b': 2}


@pytest.mark.parametrize('chunk_size', CHUNK_SIZES)
@pytest.mark.parametrize('encoding,bom', [
    ('utf-8', b'\xef\xbb\xbf'),
    ('utf-16-le', b'\xff\xfe'),
    ('utf-16-be', b'\xfe\xff'),
])
def test_encoded_streams(chunk_size, encoding, bom):
    data = bom + "a: 1\n---\nbad: [\n---\nc: 3\n".encode(encoding)
    result = _recover(data, chunk_size=chunk_size)
    assert result[0] == {'a': 1}
    assert _is_error(result[1])
    assert result[2] == {'c': 3}


def test_discarded_range_is_exact_input_slice():
    text = "good: 1\n---\nbad: [\n---\nlast: 3\n"
    result = _recover(text)
    failure = result[1]
    assert text[failure.discarded_start.index:failure.discarded_end.index] \
            == "---\nbad: [\n"
    assert failure.start.index <= failure.error_position.index \
            <= failure.discarded_end.index


def test_indented_marker_is_not_a_boundary():
    # '  ---' is scalar content in YAML, so it must stay inside one document.
    text = "a: 1\n  ---\n"
    result = _recover(text, chunk_size=1)
    assert len(result) == 1
    assert not _is_error(result[0])


def test_documents_before_abort_are_kept():
    text = "good: 1\n---\nbad: [\n---\n" + ("# filler\n" * 50) + "---\nlate: 4\n"
    result = _recover(text, chunk_size=64, max_scan_chars=100)
    assert result[0] == {'good': 1}
    assert _is_error(result[1])
    assert _is_abort(result[-1])
    assert result[-1].document_index == 2


def test_error_message_mentions_both_positions():
    text = "good: 1\n---\nbad: [\n---\nlast: 3\n"
    failure = _recover(text)[1]
    message = str(failure)
    assert 'line 4, column 1' in message
    assert 'discarded 11 character(s)' in message
    assert 'from line 2, column 1 to line 4, column 1' in message
