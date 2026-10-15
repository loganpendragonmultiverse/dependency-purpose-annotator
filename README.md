# Dependency Purpose Annotator

[![CI](https://github.com/loganpendragonmultiverse/dependency-purpose-annotator/actions/workflows/ci.yml/badge.svg)](https://github.com/loganpendragonmultiverse/dependency-purpose-annotator/actions/workflows/ci.yml)

Explain declared dependencies from observable imports and flag apparently unused packages. The command uses explicit UTF-8 JSON input and produces reviewable JSON or Markdown output.

## Three-minute start

```bash
python -m pip install .
dependency-purpose examples/sample.json
dependency-purpose examples/sample.json --format json --output report.json
```

The example documents the v1 input shape. Existing report files are never overwritten. Source inputs are read-only except where the documented purpose explicitly creates a new output artifact.

## Privacy and platforms

The tool runs locally and does not upload input or include telemetry. Python 3.10 or newer is supported on Windows, macOS, and Linux.

## Interpretation boundary

Static import evidence is incomplete for plugins, reflection, command-line tools, generated code, and optional dependencies. Findings require human review.

## Development

```bash
python -m pip install -e ".[dev]"
ruff format --check .
ruff check .
mypy src
pytest
python -m build
```

The project is feature-complete for its documented v1 scope. Maintenance focuses on correctness, security, compatibility, and well-supported input improvements.

Part of the [Logan Pendragon Forge open-source collection](https://www.loganpendragonforge.com/open-source/). Licensed under the [MIT License](LICENSE).

## Version 1.1.0: reviewed improvements

Correct scoped imports, parse Python AST evidence, separate standard/local modules, and add reviewed purposes, mappings, exceptions and baseline diffs.

```bash
dependency-purpose examples/sample.json --format json
```

Input may include `import_mappings` such as `{"PIL":"Pillow"}`, `purposes` and `exceptions` as dependency-name-to-text objects, plus `baseline` containing a prior JSON report. Evidence includes source line numbers. Python standard-library imports and local root/src modules are reported separately. JavaScript token scanning supports static ESM, side-effect imports, require and literal dynamic imports while skipping comments and string contents. Computed imports, custom aliases, regex literals and advanced bundler resolution remain outside this conservative static analysis. An exception records the operator's rationale; it never proves runtime use or deletes a dependency.

## Explicit source groups

Optionally add `source_groups` to the JSON input:

```json
{
  "root": ".",
  "source_groups": [
    {"name": "runtime", "include": ["src/**"]},
    {"name": "test", "include": ["tests/**"]},
    {"name": "tooling", "include": ["tools/**"]}
  ]
}
```

Names are unique `runtime`, `test`, or `tooling`; one or more groups may be supplied. Includes are nonempty lists of relative POSIX globs, matched case-sensitively against the complete source path (`*` can span `/`). Duplicate patterns and a source matched by multiple groups are rejected. Unmatched sources are listed in `ungrouped_sources`, not silently treated as runtime. Grouped scans refuse symlink source files.

Each dependency gains `evidence_by_group` and an explicit `runtime-observed`, `non-runtime-observed`, or `apparently-unused` status. Group subreports retain their own import evidence, excluded standard/local-module evidence, and undeclared imports. Mappings, purposes and exceptions apply consistently to every group; Python and JavaScript use the existing conservative static parsers. A test/tooling import proves only static evidence in that selected group. Absence is not proof that a package can be removed. Baseline comparisons include changed grouped dependency rows. Omitting `source_groups` preserves the legacy report shape and statuses.
