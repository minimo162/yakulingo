from __future__ import annotations

import json
from pathlib import Path

from yakulingo.config.settings import AppSettings, invalidate_settings_cache


def test_local_ai_defaults_match_template() -> None:
    root = Path(__file__).resolve().parent.parent
    template_path = root / "config" / "settings.template.json"
    data = json.loads(template_path.read_text(encoding="utf-8"))

    keys = [
        "local_ai_model_repo",
        "local_ai_model_revision",
        "local_ai_model_file",
        "local_ai_model_path",
        "local_ai_ctx_size",
        "local_ai_threads_batch",
        "local_ai_no_warmup",
        "local_ai_temperature",
        "local_ai_top_p",
        "local_ai_top_k",
        "local_ai_min_p",
        "local_ai_repeat_penalty",
        "local_ai_n_gpu_layers",
        "local_ai_flash_attn",
        "local_ai_cache_type_k",
        "local_ai_cache_type_v",
    ]

    invalidate_settings_cache()
    settings = AppSettings.load(root / "config" / "settings.json", use_cache=False)
    for key in keys:
        assert key in data, f"settings.template.json missing {key}"
        assert getattr(settings, key) == data[key]
