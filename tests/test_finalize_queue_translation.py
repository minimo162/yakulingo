from pathlib import Path

import pytest

from yakulingo.models.types import FileQueueItem, TranslationResult, TranslationStatus
from yakulingo.ui.app import YakuLingoApp
from yakulingo.ui.state import FileState


@pytest.mark.asyncio
async def test_finalize_queue_translation_surfaces_first_error(monkeypatch, tmp_path: Path):
    app = YakuLingoApp()
    monkeypatch.setattr(app, "_refresh_tabs", lambda: None)
    monkeypatch.setattr(app, "_refresh_content", lambda: None)

    item = FileQueueItem(
        id="item-1",
        path=tmp_path / "missing.txt",
        status=TranslationStatus.FAILED,
        status_label="失敗",
        error_message="boom",
    )
    app.state.file_queue = [item]

    await app._finalize_queue_translation()

    assert app.state.file_state == FileState.ERROR
    assert app.state.error_message == "boom"


@pytest.mark.asyncio
async def test_finalize_queue_translation_reports_cancel(monkeypatch, tmp_path: Path):
    app = YakuLingoApp()
    monkeypatch.setattr(app, "_refresh_tabs", lambda: None)
    monkeypatch.setattr(app, "_refresh_content", lambda: None)

    item = FileQueueItem(
        id="item-1",
        path=tmp_path / "missing.txt",
        status=TranslationStatus.CANCELLED,
        status_label="キャンセル",
    )
    app.state.file_queue = [item]

    await app._finalize_queue_translation()

    assert app.state.file_state == FileState.ERROR
    assert app.state.error_message == "翻訳をキャンセルしました"


@pytest.mark.asyncio
async def test_finalize_queue_translation_reports_missing_output(monkeypatch, tmp_path: Path):
    app = YakuLingoApp()
    monkeypatch.setattr(app, "_refresh_tabs", lambda: None)
    monkeypatch.setattr(app, "_refresh_content", lambda: None)

    result = TranslationResult(
        status=TranslationStatus.COMPLETED,
        output_path=tmp_path / "translated.xlsx",
    )
    item = FileQueueItem(
        id="item-1",
        path=tmp_path / "input.xlsx",
        status=TranslationStatus.COMPLETED,
        status_label="完了",
        result=result,
    )
    app.state.file_queue = [item]

    await app._finalize_queue_translation()

    assert app.state.file_state == FileState.ERROR
    assert app.state.error_message == "翻訳は完了しましたが出力ファイルが見つかりません"

