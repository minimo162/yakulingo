from __future__ import annotations

import json
from pathlib import Path

from yakulingo.config.settings import AppSettings


def test_local_ai_model_path_default_matches_template() -> None:
    root = Path(__file__).resolve().parent.parent
    template_path = root / "config" / "settings.template.json"
    data = json.loads(template_path.read_text(encoding="utf-8"))
    template_value = data.get("local_ai_model_path")
    assert template_value, "settings.template.json missing local_ai_model_path"

    default_value = AppSettings().local_ai_model_path
    assert default_value == template_value
