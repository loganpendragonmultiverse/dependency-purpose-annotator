import json
from pathlib import Path

import pytest

from dependency_purpose_annotator.cli import main
from dependency_purpose_annotator.core import PROJECT, analyze, render_json, render_markdown


def test_representative_sample_has_expected_result():
    data = json.loads(
        (Path(__file__).parents[1] / "examples" / "sample.json").read_text(encoding="utf-8")
    )
    report = analyze(data)
    assert report["version"] == 1 and report["project"] == PROJECT
    assert isinstance(report["dependencies"], list) and "undeclared_imports" in report
    assert f'"project": "{PROJECT}"' in render_json(report)
    assert PROJECT.replace("-", " ").title() in render_markdown(report)


def test_missing_required_input_is_rejected():
    with pytest.raises(ValueError):
        analyze({})


def test_cli_json_and_output_safety(tmp_path, capsys):
    source = Path(__file__).parents[1] / "examples" / "sample.json"
    assert main([str(source), "--format", "json"]) == 0
    assert json.loads(capsys.readouterr().out)["project"] == PROJECT
    output = tmp_path / "report.md"
    output.write_text("keep", encoding="utf-8")
    assert main([str(source), "--output", str(output)]) == 2


def test_scans_python_and_javascript_manifests(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname="fixture"\ndependencies=["requests>=2", "unused-lib"]\n',
        encoding="utf-8",
    )
    (tmp_path / "package.json").write_text(
        json.dumps(
            {
                "dependencies": {"lodash": "1"},
                "devDependencies": {"jest": "1"},
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "app.py").write_text("import requests\nimport local_module\n", encoding="utf-8")
    (tmp_path / "app.js").write_text("import value from 'lodash';\n", encoding="utf-8")
    report = analyze({"root": str(tmp_path)})
    status = {item["dependency"]: item["status"] for item in report["dependencies"]}
    assert status == {
        "jest": "apparently-unused",
        "lodash": "observed",
        "requests": "observed",
        "unused-lib": "apparently-unused",
    }
    assert "local-module" in report["undeclared_imports"]


def test_missing_root_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="existing directory"):
        analyze({"root": str(tmp_path / "missing")})
