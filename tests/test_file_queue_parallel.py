import asyncio
from pathlib import Path

import pytest

from yakulingo.config.settings import AppSettings
from yakulingo.models.types import FileQueueItem, TranslationStatus
from yakulingo.ui.app import YakuLingoApp


@pytest.mark.asyncio
async def test_run_queue_parallel_does_not_hang_when_worker_raises(monkeypatch, tmp_path: Path):
    app = YakuLingoApp()
    app._copilot = object()
    app._settings = AppSettings()

    sample_path = tmp_path / "sample.txt"
    sample_path.write_text("test", encoding="utf-8")

    item = FileQueueItem(
        id="item-1",
        path=sample_path,
        output_language="en",
        output_language_overridden=False,
        translation_style="concise",
        status=TranslationStatus.PENDING,
        status_label="待機中",
    )
    app.state.file_queue = [item]
    app.state.file_queue_active_id = item.id

    class DummyTranslationService:
        def __init__(self, *_args, **_kwargs) -> None:
            return None

    import yakulingo.services.translation_service as translation_service_module

    monkeypatch.setattr(translation_service_module, "TranslationService", DummyTranslationService)

    async def _boom(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(app, "_translate_queue_item", _boom)

    await asyncio.wait_for(app._run_queue_parallel(), timeout=1.0)

    assert item.status == TranslationStatus.FAILED
    assert item.status_label == "失敗"
    assert "boom" in item.error_message

