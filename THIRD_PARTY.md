# Third-party materials

No vendored third-party source or fixtures. Runtime Python dependencies: none.
Python's standard library is PSF-licensed; the separately installed Git
executable is GPL-2.0-only and is not bundled or linked into this package.
The tool invokes documented Git CLI plumbing.

Development dependencies: setuptools, build, pytest, pytest-cov and Ruff (MIT),
coverage.py (Apache-2.0). Official checkout/setup-python CI actions are MIT.
Synthetic fixture commits exist only inside temporary test repositories and
are never pushed; they do not change the history of this repository.
