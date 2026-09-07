from __future__ import annotations

import ast
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


def _dependency_purpose(data: dict[str, Any]) -> dict[str, Any]:
    root = Path(_require(data, "root")).resolve()
    if not root.is_dir():
        raise ValueError("root must be an existing directory")
    declared: dict[str, str] = {}
    pyproject = root / "pyproject.toml"
    if pyproject.exists():
        parsed = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        for raw in parsed.get("project", {}).get("dependencies", []):
            name = re.split("[<>=!~\\[; ]", raw, maxsplit=1)[0].strip().lower().replace("_", "-")
            if name:
                declared[name] = "pyproject.toml"
    package = root / "package.json"
    if package.exists():
        parsed = json.loads(package.read_text(encoding="utf-8"))
        for section in ("dependencies", "devDependencies"):
            for name in parsed.get(section, {}):
                declared[name.lower()] = f"package.json:{section}"
    imports: dict[str, list[str]] = defaultdict(list)
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
    for path in sorted(root.rglob("*")):
        if not path.is_file() or any(
            part in {".git", "node_modules", ".venv", "dist", "build"} for part in path.parts
        ):
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
                    name = mappings.get(name, name).lower().replace("_", "-")
                    imports[name].append(evidence)
        elif path.suffix in {".js", ".jsx", ".ts", ".tsx"}:
            for name, line in _javascript_imports(
                path.read_text(encoding="utf-8", errors="ignore")
            ):
                if name.startswith("node:"):
                    continue
                package_name = (
                    "/".join(name.split("/")[:2]) if name.startswith("@") else name.split("/")[0]
                )
                imports[package_name.lower()].append(f"{path.relative_to(root).as_posix()}:{line}")
    rows = [
        {
            "dependency": name,
            "declared_in": source,
            "evidence": sorted(set(imports.get(name, []))),
            "status": "observed" if imports.get(name) else "apparently-unused",
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
        "undeclared_imports": sorted(set(imports) - set(declared)),
        "excluded_import_evidence": dict(sorted(ignored.items())),
    }
    baseline = data.get("baseline")
    if baseline is not None:
        if not isinstance(baseline, dict) or not isinstance(baseline.get("dependencies"), list):
            raise ValueError("baseline must be a previous report with dependencies")
        old = {
            item["dependency"]: item
            for item in baseline["dependencies"]
            if isinstance(item, dict) and isinstance(item.get("dependency"), str)
        }
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
    return {"version": 1, "project": PROJECT, **_dependency_purpose(data)}


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
