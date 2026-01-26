from __future__ import annotations

import threading

from yakulingo.config.settings import AppSettings
from yakulingo.services.translation_service import TranslationService


class DummyLocalClient:
    def __init__(self) -> None:
        self.calls = 0
        self._cancel_callback = None

    def set_cancel_callback(self, callback) -> None:  # noqa: ANN001
        self._cancel_callback = callback

    def translate_single(  # noqa: D401
        self,
        text: str,
        prompt: str,
        reference_files=None,  # noqa: ANN001
        on_chunk=None,  # noqa: ANN001
    ) -> str:
        _ = (prompt, reference_files, on_chunk)
        self.calls += 1
        return f"OK:{text}"


def test_translation_service_local_translate_does_not_block_on_copilot_lock() -> None:
    copilot_lock = threading.Lock()
    assert copilot_lock.acquire(timeout=1.0)
    try:
        service = TranslationService(
            config=AppSettings(translation_backend="local"),
            client_lock=copilot_lock,
        )

        dummy_client = DummyLocalClient()
        service._local_client = dummy_client  # type: ignore[assignment]
        service._local_prompt_builder = object()  # type: ignore[assignment]
        service._local_batch_translator = object()  # type: ignore[assignment]

        done = threading.Event()
        result_box: dict[str, str] = {}
        error_box: dict[str, BaseException] = {}

        def worker() -> None:
            try:
                result_box["result"] = service._translate_single_with_cancel(
                    "hello", "PROMPT"
                )
            except BaseException as exc:  # noqa: BLE001
                error_box["error"] = exc
            finally:
                done.set()

        thread = threading.Thread(target=worker)
        thread.start()

        assert done.wait(timeout=2.0), (
            "local translate should not wait for copilot_lock"
        )
        thread.join(timeout=1.0)
        assert not thread.is_alive()

        assert error_box == {}
        assert result_box["result"] == "OK:hello"
        assert dummy_client.calls == 1
    finally:
        copilot_lock.release()
