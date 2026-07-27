from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

import tomllib

PROJECT = "dependency-purpose-annotator"


def _require(data: dict[str, Any], key: str) -> Any:
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
    for path in sorted(root.rglob("*")):
        if not path.is_file() or any(
            part in {".git", "node_modules", ".venv", "dist", "build"} for part in path.parts
        ):
            continue
        if path.suffix == ".py":
            for name in re.findall(
                "(?m)^\\s*(?:from|import)\\s+([A-Za-z0-9_.-]+)",
                path.read_text(encoding="utf-8", errors="ignore"),
            ):
                imports[name.split(".")[0].lower().replace("_", "-")].append(
                    path.relative_to(root).as_posix()
                )
        elif path.suffix in {".js", ".jsx", ".ts", ".tsx"}:
            for name in re.findall(
                "(?:from\\s+|require\\()['\\\"]([^'\\\"./][^'\\\"]*)",
                path.read_text(encoding="utf-8", errors="ignore"),
            ):
                imports[name.split("/")[0].lower()].append(path.relative_to(root).as_posix())
    rows = [
        {
            "dependency": name,
            "declared_in": source,
            "evidence": sorted(set(imports.get(name, []))),
            "status": "observed" if imports.get(name) else "apparently-unused",
        }
        for name, source in sorted(declared.items())
    ]
    return {
        "dependencies": rows,
        "apparently_unused": [
            item["dependency"] for item in rows if item["status"] == "apparently-unused"
        ],
        "undeclared_imports": sorted(set(imports) - set(declared)),
    }


def analyze(data: dict[str, Any]) -> dict[str, Any]:
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
