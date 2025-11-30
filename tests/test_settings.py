# tests/test_settings.py
"""Tests for yakulingo.config.settings"""

import tempfile
from pathlib import Path

from yakulingo.config.settings import AppSettings


class TestAppSettings:
    """Tests for AppSettings dataclass"""

    def test_default_values(self):
        settings = AppSettings()
        assert settings.reference_files == ["glossary.csv"]
        assert settings.output_directory is None
        assert settings.last_tab == "text"
        assert settings.max_batch_size == 50
        assert settings.request_timeout == 120
        assert settings.max_retries == 3
        # Auto-update defaults
        assert settings.auto_update_enabled is True
        assert settings.github_repo_owner == "minimo162"
        assert settings.github_repo_name == "yakulingo"

    def test_save_and_load(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            settings_path = Path(tmpdir) / "settings.json"

            # Create custom settings
            settings = AppSettings(
                reference_files=["custom.csv", "terms.xlsx"],
                last_tab="file",
                max_batch_size=100,
                auto_update_enabled=False,
            )

            # Save
            settings.save(settings_path)
            assert settings_path.exists()

            # Load
            loaded = AppSettings.load(settings_path)
            assert loaded.reference_files == ["custom.csv", "terms.xlsx"]
            assert loaded.last_tab == "file"
            assert loaded.max_batch_size == 100
            assert loaded.auto_update_enabled is False

    def test_load_nonexistent_file(self):
        settings = AppSettings.load(Path("/nonexistent/path/settings.json"))
        # Should return default settings
        assert settings.last_tab == "text"
        assert settings.auto_update_enabled is True

    def test_load_invalid_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            settings_path = Path(tmpdir) / "settings.json"
            settings_path.write_text("invalid json {{{")

            settings = AppSettings.load(settings_path)
            # Should return default settings
            assert settings.last_tab == "text"

    def test_load_removes_deprecated_last_direction(self):
        """Test that old settings with last_direction are handled gracefully"""
        with tempfile.TemporaryDirectory() as tmpdir:
            settings_path = Path(tmpdir) / "settings.json"
            # Write old-style settings with deprecated field
            settings_path.write_text('{"last_direction": "jp_to_en", "last_tab": "file"}')

            settings = AppSettings.load(settings_path)
            # Should load without error, ignoring deprecated field
            assert settings.last_tab == "file"
            assert not hasattr(settings, 'last_direction') or settings.__dict__.get('last_direction') is None

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

    def test_get_reference_file_paths_absolute(self):
        """Test handling of absolute paths in reference files"""
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            abs_file = base_dir / "absolute.csv"
            abs_file.write_text("data")

            settings = AppSettings(reference_files=[str(abs_file)])
            paths = settings.get_reference_file_paths(base_dir)

            assert len(paths) == 1
            assert abs_file in paths

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

    def test_auto_update_settings(self):
        """Test auto-update related settings"""
        settings = AppSettings(
            auto_update_enabled=False,
            auto_update_check_interval=3600,
            github_repo_owner="testowner",
            github_repo_name="testrepo",
            last_update_check="2025-01-01T00:00:00",
            skipped_version="2.0.0",
        )

        assert settings.auto_update_enabled is False
        assert settings.auto_update_check_interval == 3600
        assert settings.github_repo_owner == "testowner"
        assert settings.github_repo_name == "testrepo"
        assert settings.last_update_check == "2025-01-01T00:00:00"
        assert settings.skipped_version == "2.0.0"

    def test_window_size_settings(self):
        """Test window size settings"""
        settings = AppSettings(
            window_width=1200,
            window_height=800,
        )

        assert settings.window_width == 1200
        assert settings.window_height == 800

    def test_save_and_load_preserves_all_fields(self):
        """Test that all fields are preserved through save/load cycle"""
        with tempfile.TemporaryDirectory() as tmpdir:
            settings_path = Path(tmpdir) / "settings.json"

            original = AppSettings(
                reference_files=["a.csv", "b.xlsx"],
                output_directory="/out",
                last_tab="file",
                window_width=1000,
                window_height=600,
                max_batch_size=25,
                request_timeout=60,
                max_retries=5,
                auto_update_enabled=False,
                auto_update_check_interval=7200,
                github_repo_owner="owner",
                github_repo_name="repo",
                last_update_check="2025-01-01",
                skipped_version="1.0.0",
            )

            original.save(settings_path)
            loaded = AppSettings.load(settings_path)

            assert loaded.reference_files == original.reference_files
            assert loaded.output_directory == original.output_directory
            assert loaded.last_tab == original.last_tab
            assert loaded.window_width == original.window_width
            assert loaded.window_height == original.window_height
            assert loaded.max_batch_size == original.max_batch_size
            assert loaded.request_timeout == original.request_timeout
            assert loaded.max_retries == original.max_retries
            assert loaded.auto_update_enabled == original.auto_update_enabled
            assert loaded.auto_update_check_interval == original.auto_update_check_interval
            assert loaded.github_repo_owner == original.github_repo_owner
            assert loaded.github_repo_name == original.github_repo_name
            assert loaded.last_update_check == original.last_update_check
            assert loaded.skipped_version == original.skipped_version
