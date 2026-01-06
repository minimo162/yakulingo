from unittest.mock import patch

from yakulingo.services.copilot_handler import CopilotHandler


def test_parse_batch_result_with_numbered_id_lines_crlf():
    handler = CopilotHandler()
    result = (
        "1. [[ID:1]] Nov. 2025 Finance MOR\r\n"
        "2. [[ID:2]] 2025/11/24\r\n"
        "3. [[ID:3]] Main Topics\r\n"
    )

    parsed = handler._parse_batch_result(result, 3, include_item_ids=True)

    assert parsed == [
        "Nov. 2025 Finance MOR",
        "2025/11/24",
        "Main Topics",
    ]


def test_parse_batch_result_preserves_number_only_content():
    handler = CopilotHandler()
    result = "1. [[ID:1]] 1.\n2. [[ID:2]] 2.\n"

    parsed = handler._parse_batch_result(result, 2, include_item_ids=True)

    assert parsed == ["1.", "2."]


def test_parse_batch_result_without_ids_keeps_id_text():
    handler = CopilotHandler()
    result = "1. Keep [[ID:1]] in text\n2. Next item\n"

    parsed = handler._parse_batch_result(result, 2, include_item_ids=False)

    assert parsed == ["Keep [[ID:1]] in text", "Next item"]


def test_parse_batch_result_marker_before_number_preserves_number():
    handler = CopilotHandler()
    result = "[[ID:1]] 1. Finance-related matter\n[[ID:2]] 2. Next item\n"

    parsed = handler._parse_batch_result(result, 2, include_item_ids=True)

    assert parsed == ["1. Finance-related matter", "2. Next item"]


def test_parse_batch_result_id_fallback_uses_numbering_order():
    handler = CopilotHandler()
    result = "2. [[ID:3]] Second item\n1. [[ID:4]] First item\n"

    parsed = handler._parse_batch_result(result, 2, include_item_ids=True)

    assert parsed == ["[[ID:4]] First item", "[[ID:3]] Second item"]


def test_apply_browser_display_mode_foreground_without_page():
    handler = CopilotHandler()
    handler._edge_layout_mode = None
    handler._page = None

    with patch.object(handler, "_get_browser_display_mode", return_value="foreground"), \
        patch.object(handler, "_bring_edge_window_to_front") as mock_bring, \
        patch.object(handler, "_bring_to_foreground_impl") as mock_foreground:
        handler._apply_browser_display_mode("Copilot")

    mock_foreground.assert_not_called()
    mock_bring.assert_called_once()
    _, kwargs = mock_bring.call_args
    assert kwargs.get("reason") == "foreground display mode"
