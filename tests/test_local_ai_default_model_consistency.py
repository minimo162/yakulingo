from __future__ import annotations

import json
import re
from pathlib import Path


def test_default_local_ai_model_consistency() -> None:
    repo_root = Path(__file__).resolve().parents[1]

    template_path = repo_root / "config" / "settings.template.json"
    template = json.loads(template_path.read_text(encoding="utf-8"))
    default_local_path = template["local_ai_model_path"]
    default_model_file = Path(default_local_path).name

    manifest_path = repo_root / "local_ai" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    assert manifest["model"]["file"] == default_model_file
    assert manifest["model"]["output"]["path"] == default_local_path

    script_path = repo_root / "packaging" / "install_local_ai.ps1"
    content = script_path.read_text(encoding="utf-8-sig")

    repo_match = re.search(
        r"^\s*\$defaultModelRepo\s*=\s*'(?P<value>[^']+)'",
        content,
        re.IGNORECASE | re.MULTILINE,
    )
    assert repo_match is not None
    file_match = re.search(
        r"^\s*\$defaultModelFile\s*=\s*'(?P<value>[^']+)'",
        content,
        re.IGNORECASE | re.MULTILINE,
    )
    assert file_match is not None
    revision_match = re.search(
        r"^\s*\$defaultModelRevision\s*=\s*'(?P<value>[^']+)'",
        content,
        re.IGNORECASE | re.MULTILINE,
    )
    assert revision_match is not None

    assert repo_match.group("value") == manifest["model"]["repo"]
    assert file_match.group("value") == default_model_file
    assert revision_match.group("value") == manifest["model"]["revision"]
