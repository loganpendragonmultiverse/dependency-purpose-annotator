# Testing

Run `ruff format --check .`, `ruff check .`, `mypy src`, `pytest`, and `python -m build`. CI runs the supported OS/Python matrix.

## 1.1.0 regression acceptance

Run the complete existing suite plus the new regression fixtures. Confirm the documented command produces the selected output, malformed input remains actionable, and source files remain unchanged. Correct scoped imports, parse Python AST evidence, separate standard/local modules, and add reviewed purposes, mappings, exceptions and baseline diffs.

Regression acceptance includes malformed manifest types, duplicate baseline
names, Python name normalization, roots under ignored ancestor names, source and
manifest symlinks, and exclusive output creation. Run the unchanged full checks
and 90% coverage gate, then exercise installed wheel/source distributions.
