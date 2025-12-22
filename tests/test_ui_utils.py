# tests/test_ui_utils.py
"""Tests for yakulingo.ui.utils module"""

import pytest
from pathlib import Path


class TestTempFileManager:
    """Test TempFileManager class"""

    def test_create_temp_file_basic(self, tmp_path, monkeypatch):
        """Creates temp file with given content"""
        from yakulingo.ui.utils import TempFileManager

        # Reset singleton for testing
        TempFileManager._instance = None

        manager = TempFileManager()
        # Override temp_dir to use test directory
        manager._temp_dir = tmp_path

        content = b"test content"
        path = manager.create_temp_file(content, "test.txt")

        assert path.exists()
        assert path.read_bytes() == content

    def test_create_temp_file_sanitizes_forbidden_chars(self, tmp_path):
        """Removes forbidden characters from filename"""
        from yakulingo.ui.utils import TempFileManager

        # Reset singleton for testing
        TempFileManager._instance = None

        manager = TempFileManager()
        manager._temp_dir = tmp_path

        content = b"test"

        # Test various forbidden characters
        # Note: os.path.basename() is called first, which strips path separators
        # So "file/name.txt" -> "name.txt", then sanitization is applied
        test_cases = [
            ("file:name.txt", "file_name.txt"),
            # "file/name.txt" becomes "name.txt" after basename (path separator)
            ("file/name.txt", "name.txt"),
            # "file\\name.txt" may be treated as path on Windows
            ("file*name.txt", "file_name.txt"),
            ("file?name.txt", "file_name.txt"),
            ('file"name.txt', "file_name.txt"),
            ("file<name.txt", "file_name.txt"),
            ("file>name.txt", "file_name.txt"),
            ("file|name.txt", "file_name.txt"),
            # "multi:char/test.txt" -> "test.txt" (basename) -> "test.txt"
            ("multi:char/test.txt", "test.txt"),
        ]

        def assert_sanitized_name(path: Path, expected_name: str) -> None:
            if path.name == expected_name:
                return
            expected = Path(expected_name)
            assert path.suffix == expected.suffix
            assert path.stem.startswith(f"{expected.stem}_")

        for original, expected in test_cases:
            TempFileManager._instance = None
            manager = TempFileManager()
            manager._temp_dir = tmp_path

            path = manager.create_temp_file(content, original)
            assert_sanitized_name(path, expected)

    def test_create_temp_file_preserves_japanese(self, tmp_path):
        """Preserves Japanese characters in filename"""
        from yakulingo.ui.utils import TempFileManager

        # Reset singleton for testing
        TempFileManager._instance = None

        manager = TempFileManager()
        manager._temp_dir = tmp_path

        content = b"test"
        path = manager.create_temp_file(content, "テスト文書.txt")

        assert path.name == "テスト文書.txt"
        assert path.exists()

    def test_create_temp_file_handles_path_traversal(self, tmp_path):
        """Prevents path traversal attacks"""
        from yakulingo.ui.utils import TempFileManager

        # Reset singleton for testing
        TempFileManager._instance = None

        manager = TempFileManager()
        manager._temp_dir = tmp_path

        content = b"test"

        # Path traversal attempts should result in just the filename
        path = manager.create_temp_file(content, "../../../etc/passwd")
        assert path.parent == tmp_path
        assert "passwd" in path.name

        # Even with forbidden chars
        TempFileManager._instance = None
        manager = TempFileManager()
        manager._temp_dir = tmp_path

        path = manager.create_temp_file(content, "..\\..\\secret.txt")
        assert path.parent == tmp_path

    def test_create_temp_file_uses_unique_names(self, tmp_path):
        """Creates unique names when the same filename is reused"""
        from yakulingo.ui.utils import TempFileManager

        TempFileManager._instance = None
        manager = TempFileManager()
        manager._temp_dir = tmp_path

        content = b"test"
        first = manager.create_temp_file(content, "duplicate.txt")
        second = manager.create_temp_file(content, "duplicate.txt")

        assert first != second
        assert first.name == "duplicate.txt"
        assert second.suffix == ".txt"
        assert second.stem.startswith("duplicate_")


class TestFilenameFormatting:
    """Test filename-related regex patterns"""

    def test_filename_forbidden_pattern(self):
        """Matches all Windows forbidden characters"""
        from yakulingo.ui.utils import _RE_FILENAME_FORBIDDEN

        # Should match these characters
        forbidden = '\\/:*?"<>|'
        for char in forbidden:
            assert _RE_FILENAME_FORBIDDEN.search(char), f"Should match {repr(char)}"

        # Should not match these characters
        allowed = "abcABC123_-.() 日本語"
        for char in allowed:
            assert not _RE_FILENAME_FORBIDDEN.search(char), f"Should not match {repr(char)}"
