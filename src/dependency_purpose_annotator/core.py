from __future__ import annotations

import ast
import fnmatch
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

PROJECT = "dependency-purpose-annotator"


def _javascript_imports(source: str) -> list[tuple[str, int]]:
    # Tokenize comments and quoted strings before interpreting static import forms.
    # Computed imports and template strings deliberately remain unclassified.
    pattern = re.compile(
        r"//[^\n]*|/\*[\s\S]*?\*/|'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"|`(?:\\.|[^`\\])*`|[\w$]+|[^\s]"
    )
    tokens = [
        match for match in pattern.finditer(source) if not match.group().startswith(("//", "/*"))
    ]
    found = []
    for i, token in enumerate(tokens):
        word = token.group()
        target = i + 1
        if word not in {"from", "import", "require"}:
            continue
        if target < len(tokens) and tokens[target].group() == "(":
            target += 1
        if target < len(tokens):
            literal = tokens[target].group()
            if len(literal) >= 2 and literal[0] in "\"'" and literal[-1] == literal[0]:
                name = literal[1:-1]
                if name and not name.startswith((".", "/")) and "\\" not in name:
                    found.append((name, source.count("\n", 0, token.start()) + 1))
    return found


def _require(data: dict[str, Any], key: str) -> Any:
    if not isinstance(data, dict):
        raise TypeError("input must be a JSON object")
    value = data.get(key)
    if value is None or value == "" or value == []:
        raise ValueError(f"{key} is required")
    return value


def _root(data: dict[str, Any]) -> Path:
    value = _require(data, "root")
    if not isinstance(value, str):
        raise TypeError("root must be a path string")
    selected = Path(value).expanduser().absolute()
    if any(path.is_symlink() for path in (selected, *selected.parents)):
        raise ValueError("root cannot contain symlink components")
    root = selected.resolve()
    if not root.is_dir():
        raise ValueError("root must be an existing directory")
    return root


def _declared(root: Path) -> dict[str, str]:
    declared: dict[str, str] = {}
    for name in ("pyproject.toml", "package.json"):
        if (root / name).is_symlink():
            raise ValueError("dependency manifests cannot be symlinks")
    pyproject = root / "pyproject.toml"
    if pyproject.exists():
        parsed = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        project = parsed.get("project", {})
        if not isinstance(project, dict):
            raise TypeError("pyproject project must be an object")
        dependencies = project.get("dependencies", [])
        if not isinstance(dependencies, list) or not all(isinstance(v, str) for v in dependencies):
            raise TypeError("pyproject dependencies must be an array of strings")
        for raw in dependencies:
            match = re.match(
                r"([A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?)(?=[ <>=!~\[;@]|$)", raw.strip()
            )
            if match is None:
                raise ValueError("pyproject dependency has no valid package name")
            name = re.sub(r"[-_.]+", "-", match[1]).lower()
            declared[name] = "pyproject.toml"
    package = root / "package.json"
    if package.exists():
        parsed = json.loads(package.read_text(encoding="utf-8"))
        if not isinstance(parsed, dict):
            raise TypeError("package.json must be an object")
        for section in ("dependencies", "devDependencies"):
            dependencies = parsed.get(section, {})
            if not isinstance(dependencies, dict) or not all(
                isinstance(k, str) and k.strip() and isinstance(v, str)
                for k, v in dependencies.items()
            ):
                raise TypeError("package dependency sections must map names to version strings")
            for name in dependencies:
                if name.lower() in declared and declared[name.lower()] == "pyproject.toml":
                    raise ValueError("dependency identity overlaps Python and JavaScript manifests")
                declared[name.lower()] = f"package.json:{section}"
    return declared


def _baseline_rows(baseline: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(baseline, dict) or not isinstance(baseline.get("dependencies"), list):
        raise TypeError("baseline must be a previous report with dependencies")
    rows: dict[str, dict[str, Any]] = {}
    for item in baseline["dependencies"]:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("dependency"), str)
            or not item["dependency"].strip()
            or item["dependency"] in rows
        ):
            raise ValueError("baseline dependency rows must have unique nonempty names")
        rows[item["dependency"]] = item
    return rows


def _dependency_purpose(data: dict[str, Any], paths: list[Path] | None = None) -> dict[str, Any]:
    root = _root(data)
    declared = _declared(root)
    imports: dict[str, dict[str, list[str]]] = {
        "python": defaultdict(list),
        "javascript": defaultdict(list),
    }
    ignored: dict[str, list[str]] = defaultdict(list)
    mappings = data.get("import_mappings", {})
    purposes = data.get("purposes", {})
    exceptions = data.get("exceptions", {})
    for key, value in (
        ("import_mappings", mappings),
        ("purposes", purposes),
        ("exceptions", exceptions),
    ):
        if not isinstance(value, dict) or not all(
            isinstance(k, str) and isinstance(v, str) and v.strip() for k, v in value.items()
        ):
            raise ValueError(f"{key} must map names to nonempty text")
    local_modules = {p.stem for base in (root, root / "src") for p in base.glob("*.py")}
    local_modules.update(
        p.parent.name for base in (root, root / "src") for p in base.glob("*/__init__.py")
    )
    for path in sorted(root.rglob("*") if paths is None else paths):
        if any(
            part in {".git", "node_modules", ".venv", "dist", "build"}
            for part in path.relative_to(root).parts
        ):
            continue
        if path.is_symlink() and (
            path.is_dir() or path.suffix in {".py", ".js", ".jsx", ".ts", ".tsx"}
        ):
            raise ValueError("cannot inspect symlink sources")
        if not path.is_file():
            continue
        if path.suffix == ".py":
            try:
                tree = ast.parse(path.read_text(encoding="utf-8-sig"))
            except (SyntaxError, UnicodeError):
                ignored["unparsed-source"].append(path.relative_to(root).as_posix())
                continue
            for node in ast.walk(tree):
                if not isinstance(node, (ast.Import, ast.ImportFrom)):
                    continue
                names = (
                    [alias.name for alias in node.names]
                    if isinstance(node, ast.Import)
                    else (
                        [node.module]
                        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0
                        else []
                    )
                )
                for imported in names:
                    name = imported.split(".")[0]
                    evidence = f"{path.relative_to(root).as_posix()}:{node.lineno}"
                    if name in sys.stdlib_module_names or name in local_modules:
                        ignored["stdlib" if name in sys.stdlib_module_names else "local"].append(
                            evidence + ":" + name
                        )
                        continue
                    name = re.sub(r"[-_.]+", "-", mappings.get(name, name)).lower()
                    imports["python"][name].append(evidence)
        elif path.suffix in {".js", ".jsx", ".ts", ".tsx"}:
            for name, line in _javascript_imports(
                path.read_text(encoding="utf-8", errors="ignore")
            ):
                if name.startswith("node:"):
                    continue
                package_name = (
                    "/".join(name.split("/")[:2]) if name.startswith("@") else name.split("/")[0]
                )
                imports["javascript"][package_name.lower()].append(
                    f"{path.relative_to(root).as_posix()}:{line}"
                )

    def evidence_for(name: str, source: str) -> list[str]:
        ecosystem = "python" if source == "pyproject.toml" else "javascript"
        return imports[ecosystem].get(name, [])

    undeclared = {
        ecosystem: sorted(
            set(observed)
            - {
                name
                for name, source in declared.items()
                if (source == "pyproject.toml") == (ecosystem == "python")
            }
        )
        for ecosystem, observed in imports.items()
    }
    rows = [
        {
            "dependency": name,
            "declared_in": source,
            "evidence": sorted(set(evidence_for(name, source))),
            "status": "observed" if evidence_for(name, source) else "apparently-unused",
            **({"purpose": purposes[name]} if name in purposes else {}),
            **({"reviewed_exception": exceptions[name]} if name in exceptions else {}),
        }
        for name, source in sorted(declared.items())
    ]
    result = {
        "dependencies": rows,
        "apparently_unused": [
            item["dependency"] for item in rows if item["status"] == "apparently-unused"
        ],
        "undeclared_imports": sorted(set().union(*undeclared.values())),
        "undeclared_imports_by_ecosystem": undeclared,
        "excluded_import_evidence": dict(sorted(ignored.items())),
    }
    baseline = data.get("baseline")
    if baseline is not None:
        old = _baseline_rows(baseline)
        current = {item["dependency"]: item for item in rows}
        result["baseline_diff"] = {
            "added": sorted(current.keys() - old.keys()),
            "removed": sorted(old.keys() - current.keys()),
            "changed": sorted(
                name for name in current.keys() & old.keys() if current[name] != old[name]
            ),
        }
    return result


def analyze(data: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise TypeError("input must be a JSON object")
    result = _grouped_purpose(data) if "source_groups" in data else _dependency_purpose(data)
    return {"version": 1, "project": PROJECT, **result}


def render_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, ensure_ascii=False, default=str) + "\n"


def render_markdown(report: dict[str, Any]) -> str:
    lines = [f"# {report['project'].replace('-', ' ').title()} report", ""]
    for key, value in report.items():
        if key not in {"version", "project"}:
            lines.extend(
                [
                    f"## {key.replace('_', ' ').title()}",
                    "",
                    f"```json\n{json.dumps(value, indent=2, ensure_ascii=False, default=str)}\n```",
                    "",
                ]
            )
    return "\n".join(lines).rstrip() + "\n"


def _grouped_purpose(data: dict[str, Any]) -> dict[str, Any]:
    root = _root(data)
    groups = data["source_groups"]
    if not isinstance(groups, list) or not groups:
        raise ValueError("source_groups must be a nonempty list")
    patterns: dict[str, list[str]] = {}
    for group in groups:
        if not isinstance(group, dict) or set(group) != {"name", "include"}:
            raise ValueError("source_groups entries need name and include")
        name, include = group["name"], group["include"]
        if (
            not isinstance(name, str)
            or name not in {"runtime", "test", "tooling"}
            or name in patterns
        ):
            raise ValueError("source_groups names must be unique runtime, test or tooling")
        if (
            not isinstance(include, list)
            or not include
            or not all(
                isinstance(p, str)
                and p
                and not p.startswith("/")
                and "\\" not in p
                and all(part not in {"", ".", ".."} for part in p.split("/"))
                for p in include
            )
        ):
            raise ValueError("source_groups include must contain relative POSIX glob patterns")
        if len(include) != len(set(include)):
            raise ValueError("source_groups include patterns must be unique")
        patterns[name] = include
    selected: dict[str, list[Path]] = {name: [] for name in sorted(patterns)}
    ungrouped = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if (
            path.is_symlink()
            and (path.is_dir() or path.suffix in {".py", ".js", ".jsx", ".ts", ".tsx"})
            and not any(
                part in {".git", "node_modules", ".venv", "dist", "build"}
                for part in relative.parts
            )
        ):
            raise ValueError("source_groups cannot inspect symlink sources")
        if (
            not path.is_file()
            or path.suffix not in {".py", ".js", ".jsx", ".ts", ".tsx"}
            or any(
                part in {".git", "node_modules", ".venv", "dist", "build"}
                for part in relative.parts
            )
        ):
            continue
        if path.is_symlink() or any(
            parent.is_symlink() for parent in path.parents if parent != root
        ):
            raise ValueError("source_groups cannot inspect symlink sources")
        matches = [
            name
            for name, pats in patterns.items()
            if any(fnmatch.fnmatchcase(relative.as_posix(), p) for p in pats)
        ]
        if len(matches) > 1:
            raise ValueError("source_groups overlap at " + relative.as_posix())
        if matches:
            selected[matches[0]].append(path)
        else:
            ungrouped.append(relative.as_posix())
    # Each group reuses the same parser, mappings, exclusions and reviewed metadata.
    reports = {
        name: _dependency_purpose({k: v for k, v in data.items() if k != "baseline"}, paths)
        for name, paths in selected.items()
    }
    result = _dependency_purpose(data, [path for paths in selected.values() for path in paths])
    grouped_rows = {
        name: {row["dependency"]: row for row in report["dependencies"]}
        for name, report in reports.items()
    }
    for row in result["dependencies"]:
        evidence = {
            name: rows[row["dependency"]]["evidence"] for name, rows in grouped_rows.items()
        }
        row["evidence_by_group"] = evidence
        row["status"] = (
            "runtime-observed"
            if evidence.get("runtime")
            else "non-runtime-observed"
            if any(evidence.values())
            else "apparently-unused"
        )
    if "baseline_diff" in result:
        old = _baseline_rows(data["baseline"])
        result["baseline_diff"]["changed"] = sorted(
            row["dependency"]
            for row in result["dependencies"]
            if row["dependency"] in old and row != old[row["dependency"]]
        )
    result["source_groups"] = reports
    result["ungrouped_sources"] = ungrouped
    result["evidence_scope"] = (
        "Only explicitly selected sources; test/tooling imports do not prove runtime use."
    )
    return result
