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
    assert template["local_ai_model_file"] == default_model_file
    assert template["local_ai_model_repo"]
    assert template["local_ai_model_revision"]

    manifest_path = repo_root / "local_ai" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    assert manifest["model"]["repo"] == template["local_ai_model_repo"]
    assert manifest["model"]["revision"] == template["local_ai_model_revision"]
    assert manifest["model"]["file"] == default_model_file
    assert manifest["model"]["output"]["path"] == default_local_path

    script_path = repo_root / "packaging" / "install_local_ai.ps1"
    content = script_path.read_text(encoding="utf-8-sig")

    assert "settings.template.json" in content
    assert "local_ai_model_repo" in content
    assert "local_ai_model_file" in content
    assert re.search(r"LOCAL_AI_MODEL_REPO", content)
    assert re.search(r"LOCAL_AI_MODEL_FILE", content)
