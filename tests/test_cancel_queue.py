from pathlib import Path

from yakulingo.models.types import FileQueueItem, TranslationStatus
from yakulingo.ui.app import YakuLingoApp
from yakulingo.ui.state import FileState


def test_cancel_queue_finalizes_ui(monkeypatch, tmp_path: Path) -> None:
    app = YakuLingoApp()
    monkeypatch.setattr(app, "_refresh_tabs", lambda: None)
    monkeypatch.setattr(app, "_refresh_content", lambda: None)

    item = FileQueueItem(
        id="item-1",
        path=tmp_path / "input.txt",
        status=TranslationStatus.PROCESSING,
        status_label="翻訳中...",
    )
    app.state.file_queue = [item]
    app.state.file_queue_running = True
    app.state.file_state = FileState.TRANSLATING

    app._cancel()

    assert app.state.file_queue_running is False
    assert app.state.file_state == FileState.ERROR
    assert app.state.error_message == "翻訳をキャンセルしました"
    assert item.status == TranslationStatus.CANCELLED
    assert item.status_label == "キャンセル"

