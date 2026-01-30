from __future__ import annotations

import threading

from yakulingo.models.types import TextBlock
from yakulingo.services.prompt_builder import PromptBuilder
from yakulingo.services.translation_service import BatchTranslator


class DummyPromptBuilder:
    def normalize_input_text(self, text: str, output_language: str) -> str:
        return PromptBuilder.normalize_input_text(text, output_language)

    def build_batch(self, texts: list[str], **kwargs) -> str:  # noqa: ARG002
        return "prompt"


class BlockingCopilot:
    def __init__(self) -> None:
        self._cancel_callback = None
        self._counter_lock = threading.Lock()
        self._enter_count = 0
        self.first_entered = threading.Event()
        self.second_entered = threading.Event()
        self.release = threading.Event()

    def set_cancel_callback(self, callback) -> None:  # noqa: ANN001
        self._cancel_callback = callback

    def translate_sync(
        self,
        texts: list[str],
        prompt: str,
        reference_files,  # noqa: ANN001
        skip_clear_wait: bool,  # noqa: ARG002
        timeout=None,  # noqa: ANN001
        include_item_ids: bool = False,  # noqa: ARG002
    ) -> list[str]:
        _ = prompt
        _ = reference_files
        _ = timeout
        with self._counter_lock:
            self._enter_count += 1
            if self._enter_count == 1:
                self.first_entered.set()
            elif self._enter_count == 2:
                self.second_entered.set()
        self.release.wait(timeout=2.0)
        with self._counter_lock:
            self._enter_count -= 1
        return texts


def test_local_backend_calls_are_serialized_by_lock() -> None:
    backend_lock = threading.Lock()
    copilot = BlockingCopilot()
    translator = BatchTranslator(
        client=copilot,  # duck-typed
        prompt_builder=DummyPromptBuilder(),  # duck-typed
        max_chars_per_batch=1000,
        request_timeout=60,
        enable_cache=False,
        client_lock=backend_lock,
    )

    blocks = [TextBlock(id="1", text="hello", location="loc")]

    start_event = threading.Event()
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            if not start_event.wait(timeout=5.0):
                raise TimeoutError("start_event timeout")
            translator.translate_blocks_with_result(blocks, output_language="en")
        except BaseException as e:  # noqa: BLE001
            errors.append(e)

    t1 = threading.Thread(target=worker)
    t2 = threading.Thread(target=worker)
    t1.start()
    t2.start()
    start_event.set()

    assert copilot.first_entered.wait(timeout=3.0), (
        f"translate_sync not entered (errors={errors})"
    )
    # If the lock works, the second translate_sync must not run until we release the first.
    assert not copilot.second_entered.wait(timeout=0.2)

    copilot.release.set()
    t1.join(timeout=2.0)
    t2.join(timeout=2.0)

    assert not t1.is_alive()
    assert not t2.is_alive()
    assert errors == []
