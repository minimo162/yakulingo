# tests/test_settings.py
"""Tests for ecm_translate.config.settings"""

import tempfile
from pathlib import Path

from ecm_translate.config.settings import AppSettings


class TestAppSettings:
    """Tests for AppSettings dataclass"""

    def test_default_values(self):
        settings = AppSettings()
        assert settings.reference_files == ["glossary.csv"]
        assert settings.output_directory is None
        assert settings.start_with_windows is False
        assert settings.last_direction == "jp_to_en"
        assert settings.max_batch_size == 50
        assert settings.request_timeout == 120
        assert settings.max_retries == 3

    def test_save_and_load(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            settings_path = Path(tmpdir) / "settings.json"

            # Create custom settings
            settings = AppSettings(
                reference_files=["custom.csv", "terms.xlsx"],
                last_direction="en_to_jp",
                max_batch_size=100
            )

            # Save
            settings.save(settings_path)
            assert settings_path.exists()

            # Load
            loaded = AppSettings.load(settings_path)
            assert loaded.reference_files == ["custom.csv", "terms.xlsx"]
            assert loaded.last_direction == "en_to_jp"
            assert loaded.max_batch_size == 100

    def test_load_nonexistent_file(self):
        settings = AppSettings.load(Path("/nonexistent/path/settings.json"))
        # Should return default settings
        assert settings.last_direction == "jp_to_en"

    def test_load_invalid_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            settings_path = Path(tmpdir) / "settings.json"
            settings_path.write_text("invalid json {{{")

            settings = AppSettings.load(settings_path)
            # Should return default settings
            assert settings.last_direction == "jp_to_en"

    def test_get_reference_file_paths(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)

            # Create test reference files
            glossary = base_dir / "glossary.csv"
            glossary.write_text("term,translation")
            terms = base_dir / "terms.xlsx"
            terms.write_text("dummy")

            settings = AppSettings(reference_files=["glossary.csv", "terms.xlsx", "missing.csv"])
            paths = settings.get_reference_file_paths(base_dir)

            # Should only return existing files
            assert len(paths) == 2
            assert glossary in paths
            assert terms in paths

    def test_get_output_directory_none(self):
        settings = AppSettings(output_directory=None)
        input_path = Path("/some/path/file.xlsx")

        output_dir = settings.get_output_directory(input_path)
        assert output_dir == Path("/some/path")

    def test_get_output_directory_custom(self):
        settings = AppSettings(output_directory="/custom/output")
        input_path = Path("/some/path/file.xlsx")

        output_dir = settings.get_output_directory(input_path)
        assert output_dir == Path("/custom/output")

    def test_save_creates_parent_directories(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            settings_path = Path(tmpdir) / "subdir" / "deep" / "settings.json"

            settings = AppSettings()
            settings.save(settings_path)

            assert settings_path.exists()
