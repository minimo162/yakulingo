"""Tests for MsgProcessor recipient normalization."""

import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture
def processor():
    with patch.dict('sys.modules', {'extract_msg': MagicMock()}):
        from yakulingo.processors.msg_processor import MsgProcessor
        return MsgProcessor()


def test_normalize_recipient_with_email_as_name(processor):
    raw = "john.berzett@mazdatoyota.com <john.berzett@mazdatoyota.com>"
    normalized = processor._normalize_recipients(raw)
    assert normalized == "john.berzett@mazdatoyota.com"


def test_normalize_recipient_preserves_display_name(processor):
    raw = "John Berzett <john.berzett@mazdatoyota.com>"
    normalized = processor._normalize_recipients(raw)
    assert normalized == "John Berzett <john.berzett@mazdatoyota.com>"


def test_normalize_recipient_handles_multiple(processor):
    raw = "john.berzett@mazdatoyota.com; jane.doe@example.com"
    normalized = processor._normalize_recipients(raw)
    assert normalized == "john.berzett@mazdatoyota.com; jane.doe@example.com"


def test_normalize_recipient_quotes_comma_display_name(processor):
    raw = "Doe, John <john.doe@example.com>"
    normalized = processor._normalize_recipients(raw)
    assert normalized == '"Doe, John" <john.doe@example.com>'


def test_normalize_recipient_handles_comma_separated_angles(processor):
    raw = "Doe, John <john.doe@example.com>, Jane Smith <jane.smith@example.com>"
    normalized = processor._normalize_recipients(raw)
    assert normalized == '"Doe, John" <john.doe@example.com>; Jane Smith <jane.smith@example.com>'
