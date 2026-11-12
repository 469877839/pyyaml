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

## YAML 1.2 core schema

The default loaders follow the YAML 1.1 implicit resolution rules, so plain
scalars such as `on`/`yes` become booleans and `0123` is parsed as an octal
integer.  Explicitly choose the YAML 1.2 core schema with the opt-in
`YAML12SafeLoader`/`YAML12SafeDumper` classes (or the `yaml12_*` helpers);
the default `SafeLoader`/`Loader` behavior is unchanged.

    >>> yaml.yaml12_load('on')          # 'on' (a string)
    >>> yaml.yaml12_load('0123')        # 123 (decimal, not octal 83)
    >>> yaml.yaml12_load('0o17')        # 15
    >>> yaml.yaml12_load('0b1010')      # '0b1010' (no binary integers)
    >>> yaml.yaml12_load('2001-12-15')  # '2001-12-15' (no implicit timestamp)

Each loader instance gets its own resolver table, so selecting the core
schema for one loader never affects other loaders.  Explicit tags bypass
implicit resolution: `!!str 0123` always yields the string `'0123'`, and
`!!timestamp 2001-12-15` still builds a `datetime.date`.  Use
`YAML12SafeDumper` (via `yaml12_dump`/`yaml12_dump_all`) so output reloaded
with `YAML12SafeLoader` keeps the same values and types.

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
