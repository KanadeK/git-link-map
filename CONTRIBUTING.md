# Contributing

Use Python 3.11 or newer. Clone this repository, create a virtual environment,
then run `python -m pip install -e ".[dev]"`.

Before proposing a change, run `ruff check .`, `ruff format --check .`,
`pytest`, and `python -m build`. Add a regression test for a behavior change.
Keep reports deterministic and document input assumptions and limits.
Use small synthetic fixtures without private data or third-party code.

Open an issue with a minimal reproducer before large changes. The maintainer
reviews and implements accepted proposals; CI never writes source commits.
Please use the private route in SECURITY.md for vulnerabilities.
