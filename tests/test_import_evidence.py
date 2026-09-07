import json
from pathlib import Path

import pytest

from dependency_purpose_annotator.core import analyze


def test_scoped_packages_python_aliases_and_review_diffs(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(json.dumps({"dependencies": {"@scope/tool": "1"}}))
    (tmp_path / "pyproject.toml").write_text('[project]\ndependencies=["Pillow", "cli-plugin"]')
    (tmp_path / "local.py").write_text("pass")
    (tmp_path / "app.py").write_text("import json, local\nfrom PIL import Image\n")
    (tmp_path / "app.ts").write_text("""// import bad from 'fake-one';
/* require('fake-two'); */
const text = "import x from 'fake-three'";
import value from '@scope/tool/subpath';
import 'side-effect';
const fs = require('node:fs');
const lazy = import('@scope/tool');
""")
    data = {
        "root": str(tmp_path),
        "import_mappings": {"PIL": "Pillow"},
        "purposes": {"pillow": "Image decoding"},
        "exceptions": {"cli-plugin": "Loaded through entry points"},
    }
    report = analyze(data)
    rows = {item["dependency"]: item for item in report["dependencies"]}
    assert rows["@scope/tool"]["status"] == rows["pillow"]["status"] == "observed"
    assert rows["pillow"]["purpose"] == "Image decoding"
    assert rows["cli-plugin"]["reviewed_exception"] == "Loaded through entry points"
    assert report["undeclared_imports"] == ["side-effect"]
    assert report["excluded_import_evidence"]["stdlib"] == ["app.py:1:json"]
    assert report["excluded_import_evidence"]["local"] == ["app.py:1:local"]
    data["baseline"] = report
    assert analyze(data)["baseline_diff"] == {"added": [], "removed": [], "changed": []}
    (tmp_path / "app.py").write_text("invalid syntax !")
    changed = analyze(data)
    assert "pillow" in changed["baseline_diff"]["changed"]
    assert changed["excluded_import_evidence"]["unparsed-source"] == ["app.py"]


@pytest.mark.parametrize(
    "field,value", [("purposes", []), ("exceptions", {"a": ""}), ("baseline", {})]
)
def test_invalid_review_metadata(tmp_path: Path, field: str, value: object) -> None:
    with pytest.raises((ValueError, TypeError), match=field):
        analyze({"root": str(tmp_path), field: value})
