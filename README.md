PyYAML
======

A full-featured YAML processing framework for Python

## Installation

To install, type `python setup.py install`.

By default, the `setup.py` script checks whether LibYAML is installed and if
so, builds and installs LibYAML bindings.
To skip the check and force installation of LibYAML bindings, use the option
`--with-libyaml`: `python setup.py --with-libyaml install`.
To disable the check and skip building and installing LibYAML bindings, use
`--without-libyaml`: `python setup.py --without-libyaml install`.

When LibYAML bindings are installed, you may use fast LibYAML-based parser and
emitter as follows:

    >>> yaml.load(stream, Loader=yaml.CLoader)
    >>> yaml.dump(data, Dumper=yaml.CDumper)

If you don't trust the input YAML stream, you should use:

    >>> yaml.safe_load(stream)

## Recovering multiple documents

A stream with several YAML documents may contain one corrupted document.
`yaml.load_all` stops at the first error; `yaml.load_all_recover` instead
yields either the value or a `yaml.DocumentRecoveryError` for every document:

    >>> for item in yaml.safe_load_all_recover(stream):
    ...     if isinstance(item, yaml.DocumentRecoveryError):
    ...         print("discarded", item.discarded_start, item.discarded_end)
    ...     else:
    ...         print(item)

Recovery resumes only at provable document boundaries (a `---` or `...`
indicator at column 0 followed by whitespace or end of input), so quoted
scalars and block scalars cannot be mistaken for separators.  Each document
gets a fresh loader, so directives, tag handles and anchors never leak into
the next document.  `DocumentRecoveryError` carries the failing document
index, the input position of the error and the discarded input range.
`max_scan_chars` bounds how much is scanned after a failure before the next
boundary; exceeding it yields `yaml.RecoveryAborted` and stops iteration.
Inputs are consumed lazily, so a large file is not read before the first
document is returned.

Some corruption cannot be recovered safely and is reported instead of
guessed: a directive without an adjacent `---` (a plain scalar may legally
continue through it), free content after `...` without a new `---`, damage
inside the first implicit document before any boundary, and streams whose
only separators are indented (and therefore not actual indicators).  See the
`yaml.recovery` module docstring for the full list.

## Testing

PyYAML includes a comprehensive test suite.

To run the complete local test suite, type:

    make test

This creates a local Python environment, runs the pure Python tests, builds a
local copy of LibYAML, and then runs the LibYAML extension tests. The local
LibYAML build is pinned by `LIBYAML-REF`, which defaults to `0.2.5`.

To run only one test mode:

    make test-python
    make test-libyaml

To test with a specific Python version:

    make test PYTHON-VERSION=3.13.5

## Further Information

* For more information, check the
  [PyYAML homepage](https://github.com/yaml/pyyaml).

* [PyYAML tutorial and reference](http://pyyaml.org/wiki/PyYAMLDocumentation).

* Discuss PyYAML with the maintainers on
  Matrix at https://matrix.to/#/#pyyaml:yaml.io or
  IRC #pyyaml irc.libera.chat

* Submit bug reports and feature requests to the
  [PyYAML bug tracker](https://github.com/yaml/pyyaml/issues).

## License

The PyYAML module was written by Kirill Simonov <xi@resolvent.net>.
It is currently maintained by the YAML and Python communities.

PyYAML is released under the MIT license.

See the file LICENSE for more details.
