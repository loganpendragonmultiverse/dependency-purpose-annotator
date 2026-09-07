# Development contract

Explain declared dependencies from observable imports and flag apparently unused packages.

Preserve deterministic, source-safe behavior and the interpretation boundary documented in the README. Every feature release must update tests, version metadata, changelog, README claims, repository metadata, release assets, and the Forge catalog together.

## 1.1.0 improvement session

Correct scoped imports, parse Python AST evidence, separate standard/local modules, and add reviewed purposes, mappings, exceptions and baseline diffs.

Input may include `import_mappings` such as `{"PIL":"Pillow"}`, `purposes` and `exceptions` as dependency-name-to-text objects, plus `baseline` containing a prior JSON report. Evidence includes source line numbers. Python standard-library imports and local root/src modules are reported separately. JavaScript token scanning supports static ESM, side-effect imports, require and literal dynamic imports while skipping comments and string contents. Computed imports, custom aliases, regex literals and advanced bundler resolution remain outside this conservative static analysis. An exception records the operator's rationale; it never proves runtime use or deletes a dependency.

Local formatting, lint, strict types and regression tests pass. Public release completion requires the protected CI/CodeQL matrix, tagged artifacts and matching Forge catalog/detail deployment.
