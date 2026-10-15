# Changelog

## 1.2.0 - 2026-10-15

- Add explicit runtime/test/tooling source groups with separate evidence and runtime-specific statuses.
- Reject duplicate, invalid and overlapping groups; report ungrouped sources without treating them as runtime.
- Reuse conservative parsers and metadata across groups and preserve legacy ungrouped reports.

## 1.1.0 - 2026-09-07

- Correct scoped imports, parse Python AST evidence, separate standard/local modules, and add reviewed purposes, mappings, exceptions and baseline diffs.
- Added regression coverage for the audited behavior and invalid inputs.

## 1.0.0 - 2026-07-26

- Released the first complete Dependency Purpose Annotator command-line workflow.
- Added deterministic reporting, representative examples, cross-platform tests, and explicit limitations.
