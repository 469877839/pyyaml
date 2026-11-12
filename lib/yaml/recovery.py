"""Recovery-based multi-document loading.

This module provides :func:`load_all_recover`, an alternative to
:func:`yaml.load_all` that isolates a corrupted YAML document instead of
aborting the whole stream.  Each document in the stream is yielded either as
its constructed Python value or as a :class:`DocumentRecoveryError` describing
what failed and which input range was discarded.  Recovery only happens at
provable document boundaries; when no safe boundary can be found, scanning
stops and a :class:`RecoveryAborted` is yielded.

Boundary rule (mirrors ``Scanner.check_document_start`` /
``check_document_end``): a line starting at column 0 whose first characters
are ``---`` or ``...`` followed by a space, tab, line break or end of input.
Because block scalar content is always indented and quoted/plain scalars
themselves stop (or error) at such a line, this never splits a valid
document.  Text such as ``"x --- y"`` or an indented ``---`` inside a block
scalar is therefore never mistaken for a boundary.

Corruption forms that must not (and cannot safely) be recovered:

* An unterminated quoted scalar that swallows text up to a column-0 ``---``.
  The indicator is a real boundary, so the broken document is reported with
  the range it occupied and the *following* document is recovered; the value
  that the broken document might have had is unrecoverable.
* A directive line (``%YAML``/``%TAG``) without an adjacent ``---``.  A
  plain scalar may legally continue through such a line, so it is not a
  provable boundary: the whole fragment is discarded instead of guessing.
* Free-standing content after a ``...`` end marker but before the next
  ``---``.  No safe boundary exists for it; it is reported as a
  :class:`DocumentRecoveryError`.
* Corruption inside the first (implicit) document before the first
  ``---``.  Everything up to the first column-0 indicator is one segment,
  so the invalid prefix is lost as a unit.
* Indented markers such as ``  ---`` are never boundaries (they are scalar
  content in YAML), so a document delimited only by indented markers cannot
  be recovered past its error.
"""

__all__ = [
    'DocumentRecoveryError',
    'RecoveryAborted',
    'load_all_recover',
    'safe_load_all_recover',
]

import codecs

from .error import YAMLError
from .reader import ReaderError

DEFAULT_CHUNK_SIZE = 8192
DEFAULT_MAX_SCAN_CHARS = 1 << 20

# Characters accepted right after a '---' / '...' indicator.  This matches
# Scanner.check_document_start / check_document_end (with the NUL standing in
# for end of input).
_INDICATOR_FOLLOWERS = '\0 \t\r\n\x85\u2028\u2029'

_LINE_BREAKS = '\r\n\x85\u2028\u2029'


class _Position:
    """Absolute position of a character in the decoded input stream."""

    __slots__ = ('index', 'line', 'column')

    def __init__(self, index=0, line=0, column=0):
        self.index = index
        self.line = line
        self.column = column

    def copy(self):
        return _Position(self.index, self.line, self.column)

    def advance(self, ch, next_ch=''):
        self.index += 1
        if ch in '\n\x85\u2028\u2029' \
                or (ch == '\r' and next_ch != '\n'):
            self.line += 1
            self.column = 0
        else:
            self.column += 1


class DocumentRecoveryError(YAMLError):
    """A document that could not be parsed or constructed.

    Instances are yielded (not raised) by :func:`load_all_recover`.

    Attributes:
        document_index: zero-based position of the document in the stream,
            counting documents that were successfully recovered as well.
        error: the original :class:`yaml.YAMLError` raised while loading the
            document.
        start: :class:`_Position` of the first character of the document.
        error_position: :class:`_Position` reported by the underlying error
            (falls back to the document start for errors without a mark).
        discarded_start: :class:`_Position` of the first discarded character.
        discarded_end: :class:`_Position` just past the last discarded
            character, i.e. the start of the next document or end of input.
        source: name of the input source when available.
    """

    def __init__(self, document_index, error, start, error_position,
            discarded_start, discarded_end, source=None):
        self.document_index = document_index
        self.error = error
        self.start = start
        self.error_position = error_position
        self.discarded_start = discarded_start
        self.discarded_end = discarded_end
        self.source = source
        super(DocumentRecoveryError, self).__init__(str(error))

    @property
    def discarded_chars(self):
        return self.discarded_end.index - self.discarded_start.index

    def __str__(self):
        return (
            "document %d could not be recovered: %s\n"
            "  error at line %d, column %d (index %d); discarded %d "
            "character(s) from line %d, column %d to line %d, column %d"
            % (
                self.document_index, self.error,
                self.error_position.line + 1, self.error_position.column + 1,
                self.error_position.index, self.discarded_chars,
                self.discarded_start.line + 1, self.discarded_start.column + 1,
                self.discarded_end.line + 1, self.discarded_end.column + 1,
            )
        )


class RecoveryAborted(YAMLError):
    """Recovery stopped because no safe boundary was found in time.

    Yielded (not raised) by :func:`load_all_recover` when the amount of input
    scanned after a failed document exceeds ``max_scan_chars`` without
    reaching a provable document boundary.  Documents already yielded are not
    affected and the remaining input is left untouched.

    Attributes:
        document_index: document that was being recovered when scanning
            stopped.
        limit: configured scan limit in decoded characters.
        scanned: number of characters actually scanned past the error.
        consumed: total number of characters consumed from the stream.
        position: :class:`_Position` where scanning stopped.
        error: the original load error that triggered the search, or ``None``
            when the limit was hit while looking for the start of a document.
    """

    def __init__(self, document_index, limit, scanned, consumed, position,
            error=None):
        self.document_index = document_index
        self.limit = limit
        self.scanned = scanned
        self.consumed = consumed
        self.position = position
        self.error = error
        super(RecoveryAborted, self).__init__(str(error) if error else "")

    def __str__(self):
        base = ("recovery aborted after scanning %d character(s) without a "
                "provable document boundary (limit %d) at line %d, column %d"
                % (self.scanned, self.limit, self.position.line + 1,
                        self.position.column + 1))
        if self.error is not None:
            base += "; triggering error: %s" % self.error
        return base


class _ScanBudget:
    """Tracks how far scanning may continue while recovering from a failure.

    The budget becomes active when a document fails and measures the number
    of decoded characters scanned until the next provable boundary; reaching
    a boundary resets it so valid documents of arbitrary size are unaffected.
    """

    __slots__ = ('limit', 'active', 'baseline')

    def __init__(self, limit):
        self.limit = float('inf') if limit is None else limit
        self.active = False
        self.baseline = 0

    def arm(self, position):
        self.active = True
        self.baseline = position

    def reset(self, position=None):
        # The boundary that ended the failed document is at (or before) its
        # own end; it must not disarm the search that is just starting.
        if position is not None and position <= self.baseline:
            return
        self.active = False
        self.baseline = 0


class _TextChunker:
    """Incrementally decode the supported YAML inputs into unicode chunks.

    Accepts ``str``, ``bytes`` (BOM-based encoding detection mirroring
    :class:`yaml.Reader`) and text or binary file-like objects.  The input is
    never read fully ahead: at most one chunk is pulled at a time and only
    when the consumer asks for more text.  A leading byte order mark is
    stripped, matching ``Scanner.scan_to_next_token``.
    """

    def __init__(self, stream, chunk_size=DEFAULT_CHUNK_SIZE):
        self.chunk_size = chunk_size
        self.name = getattr(stream, 'name', None)
        self._eof = False
        self._bom_stripped = False
        self.decode_error = None
        self._encoding = 'utf-8'
        self._pending = ''
        if isinstance(stream, str):
            self.name = self.name or '<unicode string>'
            self._mode = 'text'
            self._stream = None
            self._text = stream
            self._offset = 0
            self._decoder = None
        elif isinstance(stream, (bytes, bytearray)):
            self.name = self.name or '<byte string>'
            data = bytes(stream)
            if data.startswith(codecs.BOM_UTF16_LE):
                encoding = 'utf-16-le'
            elif data.startswith(codecs.BOM_UTF16_BE):
                encoding = 'utf-16-be'
            else:
                encoding = 'utf-8'
            self._mode = 'bytes'
            self._stream = data
            self._offset = 0
            self._encoding = encoding
            self._decoder = codecs.getincrementaldecoder(encoding)()
        else:
            self.name = self.name or '<file>'
            # Probe the stream type with a real read and keep the result; a
            # read(0) probe would itself consume data from some stream
            # implementations and could even be blocked.
            probe = stream.read(chunk_size)
            if isinstance(probe, bytes):
                self._mode = 'binary'
                if probe.startswith(codecs.BOM_UTF16_LE):
                    self._encoding = 'utf-16-le'
                elif probe.startswith(codecs.BOM_UTF16_BE):
                    self._encoding = 'utf-16-be'
                self._decoder = codecs.getincrementaldecoder(
                        self._encoding)()
            else:
                self._mode = 'text'
                self._decoder = None
            self._stream = stream
            self._offset = 0
            self._pending = probe

    @property
    def eof(self):
        return self._eof

    def _strip_bom(self, text):
        if not self._bom_stripped:
            if not text and not self._eof:
                # A partial multi-byte character can decode to nothing; keep
                # looking for the BOM at the start of the next chunk.
                return text
            self._bom_stripped = True
            while text and text[0] == '﻿':
                text = text[1:]
        return text

    def _decode_with_sentinel(self, raw, final):
        decoder = codecs.getincrementaldecoder(self._encoding)()
        text = []
        index = 0
        while index < len(raw):
            try:
                text.append(decoder.decode(raw[index:], final=final))
                index = len(raw)
                break
            except UnicodeDecodeError as exc:
                prefix_end = index + exc.start
                text.append(raw[index:prefix_end].decode(self._encoding,
                        errors='ignore'))
                text.append('\x00' * max(1, exc.end - exc.start))
                index = index + exc.end
                decoder = None
                if index >= len(raw):
                    break
                decoder = codecs.getincrementaldecoder(self._encoding)()
                # Re-feed the remainder in the next iteration.
        if decoder is not None and index == len(raw) and final:
            try:
                text.append(decoder.decode(b'', final=True))
            except UnicodeDecodeError:
                pass
        return ''.join(text)

    def _read_raw(self):
        if self._pending:
            data = self._pending
            self._pending = ''
            return data
        return self._stream.read(self.chunk_size)

    def read_chunk(self):
        """Return the next decoded chunk, or '' at end of input.

        Empty strings can also occur while a multi-byte sequence is being
        assembled, so callers must use :attr:`eof` to detect end of input.
        """
        if self._eof:
            return ''
        if self._mode == 'text':
            if self._stream is not None:
                chunk = self._read_raw()
                # Like Reader.update_raw, only an empty read means EOF; a
                # short read may simply be a partially filled buffer.
                if not chunk:
                    self._eof = True
            else:
                chunk = self._text[self._offset:
                        self._offset + self.chunk_size]
                if len(chunk) < self.chunk_size:
                    self._eof = True
            self._offset += len(chunk)
            return self._strip_bom(chunk)
        raw = self._stream[self._offset:self._offset + self.chunk_size] \
            if self._mode == 'bytes' \
            else self._read_raw()
        self._offset += len(raw)
        if self._mode == 'bytes':
            if len(raw) < self.chunk_size:
                self._eof = True
            decoded = self._decode(self._decoder, raw, self._eof)
            if not self._bom_stripped and not decoded and not self._eof:
                # Partial multi-byte sequence: wait for more bytes instead of
                # committing the BOM decision on an empty decode result.
                return ''
            return self._strip_bom(decoded)
        if not raw:
            self._eof = True
            if self._decoder is None:
                return ''
            return self._strip_bom(self._decode(self._decoder, b'', True))
        if self._decoder is None:
            if raw.startswith(codecs.BOM_UTF16_LE):
                self._encoding = 'utf-16-le'
            elif raw.startswith(codecs.BOM_UTF16_BE):
                self._encoding = 'utf-16-be'
            else:
                self._encoding = 'utf-8'
            self._decoder = codecs.getincrementaldecoder(
                    self._encoding)()
        return self._strip_bom(self._decode(self._decoder, raw, False))

    def _decode(self, decoder, raw, final):
        try:
            return decoder.decode(raw, final=final)
        except UnicodeDecodeError as exc:
            self.decode_error = exc
            # Keep boundary scanning alive by substituting NUL for undecodable
            # bytes.  NUL cannot occur in a valid YAML stream (the reader
            # rejects it), so its presence in a segment marks that segment as
            # the corrupted one without needing cross-segment byte offsets.
            return self._decode_with_sentinel(raw, final)


class _Segment:
    """A maximal stream slice between two provable document boundaries."""

    __slots__ = ('text', 'start', 'boundary', 'nonempty', 'error')

    def __init__(self, text, start, boundary, nonempty, error=None):
        self.text = text
        self.start = start
        self.boundary = boundary
        self.nonempty = nonempty
        self.error = error


def _is_indicator(text, index):
    """Check for a column-0 document indicator at ``text[index:]``.

    Mirrors ``Scanner.check_document_start`` / ``check_document_end``:
    ``---`` or ``...`` followed by a space, tab, line break or end of input.
    The caller guarantees ``index`` points at the first character of a line.
    """
    if index + 3 > len(text):
        return None
    prefix = text[index:index + 3]
    if prefix != '---' and prefix != '...':
        return None
    follower = text[index + 3] if index + 3 < len(text) else '\0'
    if follower not in _INDICATOR_FOLLOWERS:
        return None
    return prefix


def _split_segments(chunker, budget):
    """Split the decoded stream into :class:`_Segment` objects.

    Scanning is purely lexical: only column-0 ``---`` / ``...`` indicators
    qualify as boundaries, which is exactly the rule the scanner itself uses.
    Text inside quoted or block scalars can therefore never produce a false
    boundary (block scalar lines are indented; a quoted scalar containing a
    column-0 indicator is itself invalid in PyYAML).

    A ``---`` indicator starts a new segment.  A ``...`` indicator closes the
    current document at the end of its line; the following fragment (blank
    lines, comments, directives) is emitted as its own segment so the entry
    point can either attach it to the next explicit document or report it as
    an unrecoverable prologue error.

    Yields :class:`_Segment` items.  While ``budget`` is active (i.e. after a
    document failed), the open segment may not grow beyond ``budget.limit``
    characters without reaching a boundary; if it does, a
    :class:`RecoveryAborted` is yielded and scanning stops.  Segments already
    emitted remain valid.  Only the last (possibly partial) line of the read
    data is held back between chunks, so an indicator split across a chunk
    boundary is still recognized without buffering the whole stream.
    """
    tail = ''
    pos = _Position()
    line_start = 0

    segment_text = []
    segment_pos = _Position()
    segment_nonempty = False
    segment_boundary = None
    segment_error = None
    document_index = 0
    total_consumed = 0
    eof = False

    def emit():
        text = ''.join(segment_text)
        error = segment_error
        if error is None and '\x00' in text:
            error = chunker.decode_error
        return _Segment(text, segment_pos.copy(), segment_boundary,
                segment_nonempty, error)

    def reset_segment():
        return [], _Position(pos.index, pos.line, pos.column), False, None

    while not eof:
        chunk = chunker.read_chunk()
        eof = chunker.eof
        total_consumed += len(chunk)
        tail += chunk
        if eof:
            limit = len(tail)
        else:
            last_break = tail.rfind('\n')
            if last_break != -1:
                limit = last_break + 1
            elif tail.endswith('\r'):
                limit = len(tail) - 1
            else:
                limit = 0
        cursor = 0
        while cursor < limit:
            if pos.index - line_start == 0:
                indicator = _is_indicator(tail, cursor)
                if indicator == '---':
                    if segment_nonempty:
                        yield emit()
                        document_index += 1
                    budget.reset(pos.index)
                    segment_text = []
                    segment_pos = _Position(pos.index, pos.line, pos.column)
                    segment_nonempty = False
                    segment_boundary = indicator
                    segment_error = None
                elif indicator == '...':
                    segment_boundary = '...'
            ch = tail[cursor]
            next_ch = tail[cursor + 1] if cursor + 1 < len(tail) else ''
            pos.advance(ch, next_ch)
            if ch in _LINE_BREAKS:
                line_start = pos.index
                if segment_boundary == '...':
                    # The document-end indicator only owns its own line.
                    if segment_nonempty:
                        yield emit()
                        document_index += 1
                    segment_text, segment_pos, segment_nonempty, \
                            segment_error = reset_segment()
                    segment_boundary = None
            step = 2 if ch == '\r' and next_ch == '\n' else 1
            segment_text.append(tail[cursor:cursor + step])
            cursor += step
            if not ch.isspace():
                segment_nonempty = True
        tail = tail[limit:]
        scanned = pos.index - budget.baseline
        if budget.active and scanned > budget.limit:
            yield RecoveryAborted(document_index, budget.limit, scanned,
                    total_consumed, pos.copy())
            return
    if budget.active and pos.index - budget.baseline > budget.limit:
        yield RecoveryAborted(document_index, budget.limit,
                pos.index - budget.baseline, total_consumed, pos.copy())
        return
    if segment_nonempty:
        yield emit()


def _error_position(error, segment):
    """Absolute position reported by ``error``.

    Marked errors carry one or more :class:`yaml.Mark` objects; reader errors
    carry a plain ``position``.  Anything else falls back to the start of the
    segment.
    """
    mark = getattr(error, 'problem_mark', None)
    if mark is None:
        mark = getattr(error, 'context_mark', None)
    if mark is not None:
        return _Position(segment.start.index + mark.index,
                segment.start.line + mark.line, mark.column)
    position = getattr(error, 'position', None)
    if position is not None:
        line, column = _line_column_at(segment.text, position, segment.start)
        return _Position(segment.start.index + position, line, column)
    return segment.start.copy()


def _line_column_at(text, offset, base):
    """Line/column of ``text[offset]`` relative to segment start ``base``."""
    line = base.line
    column = base.column
    index = 0
    while index < offset:
        ch = text[index]
        if ch == '\r':
            if index + 1 < offset and text[index + 1] == '\n':
                index += 1
            line += 1
            column = 0
        elif ch in '\n\x85\u2028\u2029':
            line += 1
            column = 0
        else:
            column += 1
        index += 1
    return line, column


def _failure(document_index, segment, source, error):
    end_line, end_column = _line_column_at(segment.text, len(segment.text),
            segment.start)
    end = _Position(segment.start.index + len(segment.text), end_line,
            end_column)
    position = _error_position(error, segment)
    if position.index > end.index:
        # Some parser errors point at the token that terminated the segment
        # (e.g. the next document start); clamp so the reported position stays
        # inside the discarded range.
        position = end.copy()
    return DocumentRecoveryError(
            document_index, error, segment.start.copy(), position,
            segment.start.copy(), end, source=source)


def _load_segment(Loader, segment, source):
    """Load one segment, turning byte-level problems into errors too."""
    if segment.error is not None:
        return None, _reader_error(source, segment)
    return _load_one(Loader, segment)


def _load_one(Loader, segment):
    loader = Loader(segment.text)
    try:
        if not loader.check_data():
            return None, None
        value = loader.get_data()
        # get_data() is lazy: parser/composer errors can surface only when
        # the loader is driven past the first document.  Drain the segment
        # fully so every failure is reported instead of silently becoming
        # a None value.
        while loader.check_data():
            loader.get_data()
        return value, None
    except YAMLError as error:
        return None, error
    finally:
        loader.dispose()


def load_all_recover(stream, Loader=None, *,
        max_scan_chars=DEFAULT_MAX_SCAN_CHARS,
        chunk_size=DEFAULT_CHUNK_SIZE):
    """Parse every YAML document, recovering from per-document failures.

    A generator that yields, for each document, either the constructed Python
    value or a :class:`DocumentRecoveryError`.  Unlike :func:`yaml.load_all`,
    a corrupted document does not stop iteration: its input range is
    discarded and parsing resumes at the next provable document boundary
    with a fresh loader, so directives, tag handles and anchors do not leak
    across documents.

    Arguments:
        stream: ``str``, ``bytes`` or a text/binary file-like object.
        Loader: loader class, defaulting to :class:`yaml.SafeLoader`.
        max_scan_chars: maximum number of decoded characters scanned while
            searching for the next boundary after a failure.  Exceeding it
            yields :class:`RecoveryAborted` and stops the generator.  Set to
            ``None`` to disable the limit.
        chunk_size: read size for file-like inputs; the stream is consumed
            lazily and never buffered in full.

    Boundaries are exactly those recognized by the scanner: a ``---`` or
    ``...`` indicator at column 0 followed by whitespace or end of input.
    Recovery therefore never splits a valid document, and similar text inside
    quoted or block scalars is not treated as a boundary.
    """
    if Loader is None:
        from .loader import SafeLoader as Loader
    budget = _ScanBudget(max_scan_chars)
    chunker = _TextChunker(stream, chunk_size=chunk_size)
    document_index = 0
    merged = None
    after_end = False
    for item in _split_segments(chunker, budget):
        if isinstance(item, RecoveryAborted):
            item.document_index = document_index
            yield item
            return
        segment = item
        if not segment.nonempty:
            continue
        if document_index > 0 and _is_end_only(segment.text) \
                and segment.error is None:
            continue
        if segment.boundary is None and after_end \
                and not _is_prologue(segment.text) and segment.error is None:
            # Free content after '...' has no provable document boundary.
            budget.arm(segment.start.index + len(segment.text))
            yield _failure(document_index, segment, chunker.name,
                    _prologue_error(segment))
            document_index += 1
            after_end = False
            continue
        if segment.boundary is None:
            if merged is not None and _is_prologue(segment.text) \
                    and segment.error is None:
                # Prologue following a document-end marker belongs to the
                # next explicit document.
                merged = _Segment(merged.text + segment.text,
                        merged.start.copy(), None, True, merged.error)
                continue
            if merged is not None:
                # Real content following a document-end marker without a new
                # document start: no provable boundary for that fragment.
                budget.arm(merged.start.index + len(merged.text))
                yield _failure(document_index, merged, chunker.name,
                        _prologue_error(merged))
                document_index += 1
                merged = None
            if _is_prologue(segment.text) and segment.error is None:
                # Leading directives/comments before the first explicit
                # document start belong to that document.
                merged = segment
                continue
            # An implicit document (or a corrupted one) loads on its own.
            value, error = _load_segment(Loader, segment, chunker.name)
            if error is not None:
                budget.arm(segment.start.index + len(segment.text))
                yield _failure(document_index, segment, chunker.name, error)
            else:
                yield value
            document_index += 1
            continue
        if merged is not None:
            segment = _Segment(merged.text + segment.text, merged.start.copy(),
                    segment.boundary, segment.nonempty,
                    merged.error or segment.error)
            merged = None
        value, error = _load_segment(Loader, segment, chunker.name)
        after_end = segment.boundary == '...'
        if error is not None:
            budget.arm(segment.start.index + len(segment.text))
            yield _failure(document_index, segment, chunker.name, error)
        else:
            yield value
        document_index += 1
    if merged is not None:
        # A trailing fragment without a document start is not a document.
        if merged.error is not None:
            yield _failure(document_index, merged, chunker.name,
                    _reader_error(chunker.name, merged))
        elif not _is_prologue(merged.text):
            yield _failure(document_index, merged, chunker.name,
                    _prologue_error(merged))


def _is_prologue(text):
    """True when ``text`` only contains comments, blank lines and directives.

    Such text before the first explicit document start (or between a
    document end and the next start) belongs to the following document:
    directives must precede their document start, while comments and blank
    lines are unconstrained.  Any other content means the fragment is a real
    (implicit) document or an invalid region and must not be swallowed.
    """
    saw_anything = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        saw_anything = True
        if not (line.startswith('#') or line.startswith('%')):
            return False
    return saw_anything


def _reader_error(name, segment):
    """Build a :class:`ReaderError` for a segment with undecodable bytes."""
    index = segment.text.find('\x00')
    if index == -1:
        index = 0
    exc = segment.error
    return ReaderError(name or '<stream>', index,
            getattr(exc, 'object', b'')[getattr(exc, 'start', 0):
                getattr(exc, 'end', 0)],
            getattr(exc, 'encoding', 'unicode'),
            getattr(exc, 'reason', 'invalid character'))


def _is_end_only(text):
    """True when ``text`` only has document-end markers, comments, blanks."""
    saw_marker = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#'):
            continue
        if line == '...':
            saw_marker = True
            continue
        return False
    return saw_marker


def _prologue_error(segment):
    return YAMLError(
            "content outside a document: text after the stream start or "
            "after a document-end indicator '...' without a new "
            "document-start indicator '---'")


def safe_load_all_recover(stream, **kwargs):
    """Convenience wrapper using :class:`yaml.SafeLoader`."""
    from .loader import SafeLoader
    return load_all_recover(stream, SafeLoader, **kwargs)
