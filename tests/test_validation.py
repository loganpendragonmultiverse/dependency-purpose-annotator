import json
from pathlib import Path

import pytest

from dependency_purpose_annotator.cli import main
from dependency_purpose_annotator.core import analyze


@pytest.mark.parametrize(
    "manifest",
    [[], None, {"dependencies": []}, {"dependencies": {"x": 1}}, {"devDependencies": None}],
)
def test_malformed_package_manifest_is_not_an_empty_inventory(tmp_path, manifest):
    (tmp_path / "package.json").write_text(json.dumps(manifest))
    with pytest.raises(TypeError):
        analyze({"root": str(tmp_path)})


@pytest.mark.parametrize(
    "manifest",
    [
        'project="bad"',
        '[project]\ndependencies="bad"',
        "[project]\ndependencies=[1]",
        '[project]\ndependencies=["@invalid"]',
    ],
)
def test_malformed_python_manifest_is_not_an_empty_inventory(tmp_path, manifest):
    (tmp_path / "pyproject.toml").write_text(manifest)
    with pytest.raises((ValueError, TypeError)):
        analyze({"root": str(tmp_path)})


def test_python_name_normalization_and_ignored_ancestor(tmp_path):
    root = tmp_path / "build" / "actual-repository"
    root.mkdir(parents=True)
    (root / "pyproject.toml").write_text('[project]\ndependencies=["Some...Package"]')
    (root / "app.py").write_text("import some_package\n")
    report = analyze({"root": str(root)})
    assert report["dependencies"][0]["dependency"] == "some-package"
    assert report["dependencies"][0]["status"] == "observed"


@pytest.mark.parametrize(
    "items", [[None], [{"dependency": ""}], [{"dependency": "x"}, {"dependency": "x"}]]
)
def test_baseline_rejects_invalid_or_duplicate_identity(tmp_path, items):
    with pytest.raises(ValueError, match="baseline"):
        analyze({"root": str(tmp_path), "baseline": {"dependencies": items}})


@pytest.mark.parametrize("kind", ["source", "manifest", "root"])
def test_symlink_boundaries_apply_to_ungrouped_scans(tmp_path, kind):
    root = tmp_path / "repo"
    root.mkdir()
    target = tmp_path / "outside.py"
    target.write_text("import private_package\n")
    try:
        if kind == "source":
            (root / "app.py").symlink_to(target)
        elif kind == "manifest":
            (root / "package.json").symlink_to(target)
        else:
            link = tmp_path / "linked"
            link.symlink_to(root, target_is_directory=True)
            root = link
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    with pytest.raises(ValueError, match="symlink"):
        analyze({"root": str(root)})


def test_root_type_and_exclusive_output_creation(tmp_path, monkeypatch):
    with pytest.raises(TypeError, match="root"):
        analyze({"root": 3})
    source = tmp_path / "input.json"
    source.write_text(json.dumps({"root": str(tmp_path)}))
    output = tmp_path / "report.md"
    original = Path.open

    def race(path, mode="r", *args, **kwargs):
        if path == output and mode == "x":
            with original(path, "w", encoding="utf-8") as handle:
                handle.write("other writer")
        return original(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", race)
    assert main([str(source), "--output", str(output)]) == 2
    assert output.read_text() == "other writer"


def test_dangling_output_symlink_is_never_followed(tmp_path):
    source = tmp_path / "input.json"
    data = {"root": str(tmp_path)}
    source.write_text(json.dumps(data))
    target = tmp_path / "absent-target"
    output = tmp_path / "report.md"
    try:
        output.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation unavailable")
    assert main([str(source), "--output", str(output)]) == 2
    assert output.is_symlink() and not target.exists()


def test_cross_manifest_identity_is_not_silently_overwritten(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\ndependencies=["shared-name"]')
    (tmp_path / "package.json").write_text(json.dumps({"dependencies": {"shared-name": "1"}}))
    with pytest.raises(ValueError, match="overlaps"):
        analyze({"root": str(tmp_path)})


def test_grouped_dangling_symlink_is_refused(tmp_path):
    link = tmp_path / "missing.py"
    try:
        link.symlink_to(tmp_path / "absent")
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation unavailable")
    with pytest.raises(ValueError, match="symlink"):
        analyze({"root": str(tmp_path), "source_groups": [{"name": "runtime", "include": ["**"]}]})


@pytest.mark.parametrize("grouped", [False, True])
@pytest.mark.parametrize("declaration", ["python", "javascript"])
def test_cross_language_evidence_does_not_satisfy_declaration(tmp_path, grouped, declaration):
    if declaration == "python":
        (tmp_path / "pyproject.toml").write_text('[project]\ndependencies=["requests"]\n')
        (tmp_path / "app.js").write_text('require("requests");\n')
        observed = "javascript"
    else:
        (tmp_path / "package.json").write_text('{"dependencies":{"requests":"*"}}')
        (tmp_path / "app.py").write_text("import requests\n")
        observed = "python"
    data = {"root": str(tmp_path)}
    if grouped:
        data["source_groups"] = [{"name": "runtime", "include": ["app.*"]}]
    report = analyze(data)
    row = report["dependencies"][0]
    assert row["status"] == "apparently-unused"
    assert row["evidence"] == []
    assert report["undeclared_imports"] == ["requests"]
    assert report["undeclared_imports_by_ecosystem"][observed] == ["requests"]
    if grouped:
        assert row["evidence_by_group"] == {"runtime": []}
