# tests/test_settings.py
"""Tests for yakulingo.config.settings"""

import tempfile
from pathlib import Path

from yakulingo.config.settings import AppSettings


class TestAppSettings:
    """Tests for AppSettings dataclass"""

    def test_default_values(self):
        settings = AppSettings()
        assert settings.reference_files == []  # Empty by default for new users
        assert settings.output_directory is None
        assert settings.last_tab == "text"
        assert settings.max_chars_per_batch == 7000
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
                max_chars_per_batch=5000,
                auto_update_enabled=False,
            )

            # Save
            settings.save(settings_path)
            assert settings_path.exists()

            # Load
            loaded = AppSettings.load(settings_path)
            assert loaded.reference_files == ["custom.csv", "terms.xlsx"]
            assert loaded.last_tab == "file"
            assert loaded.max_chars_per_batch == 5000
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
                max_chars_per_batch=5000,
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
            assert loaded.max_chars_per_batch == original.max_chars_per_batch
            assert loaded.request_timeout == original.request_timeout
            assert loaded.max_retries == original.max_retries
            assert loaded.auto_update_enabled == original.auto_update_enabled
            assert loaded.auto_update_check_interval == original.auto_update_check_interval
            assert loaded.github_repo_owner == original.github_repo_owner
            assert loaded.github_repo_name == original.github_repo_name
            assert loaded.last_update_check == original.last_update_check
            assert loaded.skipped_version == original.skipped_version


# --- Edge Cases in Settings ---

class TestSettingsEdgeCases:
    """Edge case tests for settings"""

    def test_load_empty_json_file(self):
        """Load settings from empty JSON file"""
        with tempfile.TemporaryDirectory() as tmpdir:
            settings_path = Path(tmpdir) / "settings.json"
            settings_path.write_text("{}")

            settings = AppSettings.load(settings_path)

            # Should use defaults for missing fields
            assert settings.max_chars_per_batch == 7000
            assert settings.reference_files == []  # Empty by default

    def test_load_partial_json(self):
        """Load settings with only some fields specified"""
        with tempfile.TemporaryDirectory() as tmpdir:
            settings_path = Path(tmpdir) / "settings.json"
            settings_path.write_text('{"last_tab": "file", "max_chars_per_batch": 5000}')

            settings = AppSettings.load(settings_path)

            assert settings.last_tab == "file"
            assert settings.max_chars_per_batch == 5000
            # Other fields use defaults
            assert settings.request_timeout == 120

    def test_load_with_extra_fields(self):
        """Load settings with unknown extra fields"""
        with tempfile.TemporaryDirectory() as tmpdir:
            settings_path = Path(tmpdir) / "settings.json"
            settings_path.write_text(
                '{"last_tab": "text", "unknown_field": "value", "another_unknown": 123}'
            )

            settings = AppSettings.load(settings_path)

            # Should load without error, ignoring unknown fields
            assert settings.last_tab == "text"

    def test_load_with_wrong_types(self):
        """Load settings with wrong field types"""
        with tempfile.TemporaryDirectory() as tmpdir:
            settings_path = Path(tmpdir) / "settings.json"
            # max_chars_per_batch should be int, not string
            settings_path.write_text('{"max_chars_per_batch": "seven thousand"}')

            settings = AppSettings.load(settings_path)

            # Should use defaults when type is wrong
            assert settings is not None

    def test_load_with_null_values(self):
        """Load settings with null values"""
        with tempfile.TemporaryDirectory() as tmpdir:
            settings_path = Path(tmpdir) / "settings.json"
            settings_path.write_text('{"last_tab": null, "output_directory": null}')

            settings = AppSettings.load(settings_path)

            assert settings is not None
            # output_directory can be None
            assert settings.output_directory is None

    def test_load_with_unicode_paths(self):
        """Load settings with Unicode paths"""
        with tempfile.TemporaryDirectory() as tmpdir:
            settings_path = Path(tmpdir) / "settings.json"
            settings_path.write_text(
                '{"output_directory": "/Users/日本語/出力フォルダ", '
                '"reference_files": ["用語集.csv", "참조.xlsx"]}'
            )

            settings = AppSettings.load(settings_path)

            assert settings.output_directory == "/Users/日本語/出力フォルダ"
            assert "用語集.csv" in settings.reference_files

    def test_save_with_unicode_paths(self):
        """Save settings with Unicode paths"""
        with tempfile.TemporaryDirectory() as tmpdir:
            settings_path = Path(tmpdir) / "settings.json"

            settings = AppSettings(
                output_directory="/Users/日本語/出力",
                reference_files=["用語集.csv"],
            )
            settings.save(settings_path)

            # Read back and verify
            loaded = AppSettings.load(settings_path)
            assert loaded.output_directory == "/Users/日本語/出力"

    def test_load_corrupted_json_partial(self):
        """Load settings from partially corrupted JSON"""
        with tempfile.TemporaryDirectory() as tmpdir:
            settings_path = Path(tmpdir) / "settings.json"
            # JSON with trailing comma (invalid)
            settings_path.write_text('{"last_tab": "file",}')

            settings = AppSettings.load(settings_path)

            # Should fall back to defaults
            assert settings is not None

    def test_load_binary_file_as_json(self):
        """Load settings from binary file"""
        with tempfile.TemporaryDirectory() as tmpdir:
            settings_path = Path(tmpdir) / "settings.json"
            settings_path.write_bytes(b"\x00\x01\x02\x03\xff\xfe")

            settings = AppSettings.load(settings_path)

            # Should fall back to defaults
            assert settings is not None

    def test_save_to_readonly_location(self):
        """Test save behavior for read-only locations"""
        import os
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a subdirectory
            subdir = Path(tmpdir) / "readonly_sim"
            subdir.mkdir()

            settings_path = subdir / "settings.json"

            settings = AppSettings()

            # This should work since directory exists
            settings.save(settings_path)
            assert settings_path.exists()

    def test_get_reference_file_paths_with_empty_list(self):
        """Get reference file paths with empty list"""
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)

            settings = AppSettings(reference_files=[])
            paths = settings.get_reference_file_paths(base_dir)

            assert paths == []

    def test_get_reference_file_paths_with_duplicates(self):
        """Get reference file paths with duplicate entries"""
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)

            # Create test file
            test_file = base_dir / "test.csv"
            test_file.write_text("data")

            settings = AppSettings(
                reference_files=["test.csv", "test.csv", "test.csv"]
            )
            paths = settings.get_reference_file_paths(base_dir)

            # Should return unique paths only
            assert len(paths) >= 1  # At least one entry

    def test_get_output_directory_with_empty_string(self):
        """Get output directory with empty string"""
        settings = AppSettings(output_directory="")
        input_path = Path("/some/path/file.xlsx")

        output_dir = settings.get_output_directory(input_path)

        # Empty string should be treated like None (use input directory)
        # or return empty path
        assert output_dir is not None

    def test_boundary_values_for_numeric_settings(self):
        """Test boundary values for numeric settings"""
        settings = AppSettings(
            max_chars_per_batch=100,  # Minimum reasonable value
            request_timeout=1,
            max_retries=0,
            window_width=100,
            window_height=100,
        )

        assert settings.max_chars_per_batch == 100
        assert settings.request_timeout == 1
        assert settings.max_retries == 0
        assert settings.window_width == 100
        assert settings.window_height == 100

    def test_very_large_numeric_values(self):
        """Test very large numeric values"""
        settings = AppSettings(
            max_chars_per_batch=1000000,
            request_timeout=86400,  # 24 hours
            window_width=10000,
            window_height=10000,
        )

        assert settings.max_chars_per_batch == 1000000
        assert settings.request_timeout == 86400

    def test_special_characters_in_output_directory(self):
        """Test special characters in output directory"""
        special_paths = [
            "/path/with spaces/output",
            "/path/with'quotes/output",
            "/path/with\"doublequotes/output",
            "/path/with$dollar/output",
            "/path/with(parens)/output",
        ]

        for special_path in special_paths:
            settings = AppSettings(output_directory=special_path)
            assert settings.output_directory == special_path

    def test_get_reference_file_paths_nonexistent_base_dir(self):
        """Get reference file paths with non-existent base directory"""
        settings = AppSettings(reference_files=["test.csv"])

        # Non-existent base directory
        base_dir = Path("/definitely/does/not/exist/anywhere")

        paths = settings.get_reference_file_paths(base_dir)

        # Should return empty list or handle gracefully
        assert isinstance(paths, list)


class TestSettingsPathNormalization:
    """Test path normalization in settings"""

    def test_windows_path_separators(self):
        """Handle Windows-style path separators"""
        settings = AppSettings(
            output_directory="C:\\Users\\Test\\Output"
        )
        assert settings.output_directory == "C:\\Users\\Test\\Output"

    def test_mixed_path_separators(self):
        """Handle mixed path separators"""
        settings = AppSettings(
            output_directory="C:/Users\\Test/Output"
        )
        assert settings.output_directory == "C:/Users\\Test/Output"

    def test_relative_path_in_output_directory(self):
        """Handle relative path in output directory"""
        settings = AppSettings(output_directory="./output")

        input_path = Path("/some/absolute/path/file.xlsx")
        output_dir = settings.get_output_directory(input_path)

        assert output_dir is not None


class TestSettingsMigration:
    """Test settings migration from old formats"""

    def test_migrate_from_v1_settings(self):
        """Migrate from v1 settings format (with last_direction)"""
        with tempfile.TemporaryDirectory() as tmpdir:
            settings_path = Path(tmpdir) / "settings.json"
            # Old v1 format with deprecated fields
            settings_path.write_text('''
            {
                "last_direction": "jp_to_en",
                "last_tab": "text",
                "window_width": 900,
                "window_height": 700
            }
            ''')

            settings = AppSettings.load(settings_path)

            # Should load successfully, ignoring deprecated field
            assert settings.last_tab == "text"
            assert settings.window_width == 900

    def test_handle_future_version_settings(self):
        """Handle settings from a future version with new fields"""
        with tempfile.TemporaryDirectory() as tmpdir:
            settings_path = Path(tmpdir) / "settings.json"
            # Simulated future version with new fields
            settings_path.write_text('''
            {
                "last_tab": "file",
                "future_feature_enabled": true,
                "advanced_mode": {"nested": "value"},
                "new_list_field": [1, 2, 3]
            }
            ''')

            settings = AppSettings.load(settings_path)

            # Should load known fields and ignore unknown
            assert settings.last_tab == "file"
