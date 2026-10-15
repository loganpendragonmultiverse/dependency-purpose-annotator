import json

import pytest

from dependency_purpose_annotator.cli import main
from dependency_purpose_annotator.core import analyze


def groups():
    return [{"name": name, "include": [name + "/**"]} for name in ("runtime", "test", "tooling")]


def fixture(root):
    (root / "pyproject.toml").write_text(
        '[project]\ndependencies=["Pillow", "test-only", "unused"]', encoding="utf-8"
    )
    (root / "package.json").write_text(
        json.dumps({"dependencies": {"@scope/tool": "1"}}), encoding="utf-8"
    )
    (root / "local.py").write_text("pass", encoding="utf-8")
    for group in ("runtime", "test", "tooling"):
        (root / group).mkdir()
        (root / group / "example.py").write_text(
            "import json, local\nfrom PIL import Image\n", encoding="utf-8"
        )
        (root / group / "example.ts").write_text(
            "import x from '@scope/tool/subpath';\nrequire('node:fs');", encoding="utf-8"
        )
    (root / "test" / "only.py").write_text("import test_only", encoding="utf-8")
    return {"root": str(root), "source_groups": groups(), "import_mappings": {"PIL": "Pillow"}}


def test_group_evidence_mappings_and_exclusions(tmp_path):
    data = fixture(tmp_path)
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    report = analyze(data)
    rows = {row["dependency"]: row for row in report["dependencies"]}
    assert rows["test-only"]["status"] == "non-runtime-observed"
    assert rows["test-only"]["evidence_by_group"]["runtime"] == []
    assert rows["pillow"]["status"] == rows["@scope/tool"]["status"] == "runtime-observed"
    assert rows["unused"]["status"] == "apparently-unused"
    for group, subreport in report["source_groups"].items():
        assert subreport["excluded_import_evidence"]["stdlib"] == [f"{group}/example.py:1:json"]
        assert subreport["excluded_import_evidence"]["local"] == [f"{group}/example.py:1:local"]
        assert subreport["undeclared_imports"] == []
    data["baseline"] = report
    assert analyze(data)["baseline_diff"] == {"added": [], "removed": [], "changed": []}
    assert all(p.read_bytes() == content for p, content in before.items())
    (tmp_path / "runtime" / "new.py").write_text("import test_only", encoding="utf-8")
    assert "test-only" in analyze(data)["baseline_diff"]["changed"]


def test_ungrouped_sources_and_legacy_reports(tmp_path):
    data = fixture(tmp_path)
    report = analyze({**data, "source_groups": [{"name": "test", "include": ["test/**"]}]})
    assert "runtime/example.py" in report["ungrouped_sources"]
    assert all(row["status"] != "runtime-observed" for row in report["dependencies"])
    legacy = analyze({"root": str(tmp_path)})
    assert "source_groups" not in legacy and "evidence_scope" not in legacy
    assert all("evidence_by_group" not in row for row in legacy["dependencies"])


@pytest.mark.parametrize(
    "value",
    [
        None,
        [],
        {},
        [None],
        [{"name": "runtime"}],
        [{"name": "other", "include": ["**"]}],
        [{"name": "runtime", "include": []}],
        [{"name": "runtime", "include": ["../bad"]}],
        [{"name": "runtime", "include": ["x", "x"]}],
        [{"name": "runtime", "include": ["**"]}] * 2,
        [{"name": "runtime", "include": ["**"]}, {"name": "test", "include": ["test/**"]}],
    ],
)
def test_invalid_and_overlapping_groups(tmp_path, value):
    data = fixture(tmp_path)
    with pytest.raises(ValueError, match="source_groups"):
        analyze({**data, "source_groups": value})


def test_grouped_cli_and_symlinks(tmp_path, capsys):
    data = fixture(tmp_path)
    source = tmp_path / "input.json"
    source.write_text(json.dumps(data), encoding="utf-8")
    assert main([str(source), "--format", "json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert "source_groups" in report
    assert main([str(source), "--format", "markdown"]) == 0
    assert "Evidence By Group" not in capsys.readouterr().out  # evidence stays in row JSON
    link = tmp_path / "runtime" / "link.py"
    try:
        link.symlink_to(tmp_path / "local.py")
    except OSError:
        pytest.skip("symlink creation unavailable")
    with pytest.raises(ValueError, match="symlink"):
        analyze(data)
    assert main([str(source)]) == 2


def test_group_validation_missing_root(tmp_path):
    with pytest.raises(ValueError, match="existing directory"):
        analyze({"root": str(tmp_path / "missing"), "source_groups": groups()})
