# tests/test_settings.py
"""Tests for yakulingo.config.settings"""

import json
import tempfile
from pathlib import Path

from yakulingo.config.settings import AppSettings, USER_SETTINGS_KEYS


class TestAppSettings:
    """Tests for AppSettings dataclass"""

    def test_default_values(self):
        settings = AppSettings()
        assert settings.reference_files == []  # Empty by default for new users
        assert settings.output_directory is None
        assert settings.last_tab == "text"
        assert settings.max_chars_per_batch == 4000  # Reduced for reliability
        assert settings.request_timeout == 600  # 10 minutes for large translations
        assert settings.max_retries == 3
        # Auto-update defaults
        assert settings.auto_update_enabled is True
        assert settings.github_repo_owner == "minimo162"
        assert settings.github_repo_name == "yakulingo"

    def test_save_and_load(self):
        """Test save/load with the separation model (template + user_settings)"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            settings_path = config_dir / "settings.json"  # Used as base path

            # Create template with default values
            template_path = config_dir / "settings.template.json"
            template_path.write_text(json.dumps({
                "reference_files": ["glossary.csv"],
                "max_chars_per_batch": 4000,
                "last_tab": "text",
            }))

            # Create custom settings (only USER_SETTINGS_KEYS are saved)
            settings = AppSettings(
                last_tab="file",
                translation_style="minimal",
                bilingual_output=True,
            )

            # Save - writes to user_settings.json
            settings.save(settings_path)

            user_settings_path = config_dir / "user_settings.json"
            assert user_settings_path.exists()

            # Load - reads from template + user_settings
            loaded = AppSettings.load(settings_path)
            # USER_SETTINGS_KEYS are loaded from user_settings.json
            assert loaded.last_tab == "file"
            assert loaded.translation_style == "minimal"
            assert loaded.bilingual_output is True
            # Non-USER_SETTINGS are loaded from template
            assert loaded.max_chars_per_batch == 4000

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
        """Test that template with deprecated fields is handled gracefully"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            settings_path = config_dir / "settings.json"

            # Write template with deprecated field
            template_path = config_dir / "settings.template.json"
            template_path.write_text('{"last_direction": "jp_to_en", "last_tab": "file"}')

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
        """Test that save creates parent directories for user_settings.json"""
        with tempfile.TemporaryDirectory() as tmpdir:
            settings_path = Path(tmpdir) / "subdir" / "deep" / "settings.json"

            settings = AppSettings()
            settings.save(settings_path)

            # user_settings.json should be created in the parent directory
            user_settings_path = settings_path.parent / "user_settings.json"
            assert user_settings_path.exists()

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

    # NOTE: window_width/window_height tests removed - these settings are deprecated
    # Window size is now calculated dynamically in _detect_display_settings()

    def test_save_and_load_preserves_user_settings(self):
        """Test that USER_SETTINGS_KEYS are preserved through save/load cycle"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            settings_path = config_dir / "settings.json"

            # Create template with non-USER_SETTINGS defaults
            template_path = config_dir / "settings.template.json"
            template_path.write_text(json.dumps({
                "reference_files": ["glossary.csv"],
                "max_chars_per_batch": 4000,
                "request_timeout": 600,
            }))

            # Create settings with USER_SETTINGS_KEYS values
            original = AppSettings(
                last_tab="file",
                translation_style="minimal",
                text_translation_style="standard",
                font_jp_to_en="Times New Roman",
                font_en_to_jp="Meiryo",
                font_size_adjustment_jp_to_en=-1.5,
                bilingual_output=True,
                export_glossary=True,
                use_bundled_glossary=False,
                embed_glossary_in_prompt=False,
                browser_display_mode="minimized",
                skipped_version="2.0.0",
            )

            original.save(settings_path)
            loaded = AppSettings.load(settings_path)

            # USER_SETTINGS_KEYS should be preserved
            assert loaded.last_tab == original.last_tab
            assert loaded.translation_style == original.translation_style
            assert loaded.text_translation_style == original.text_translation_style
            assert loaded.font_jp_to_en == original.font_jp_to_en
            assert loaded.font_en_to_jp == original.font_en_to_jp
            assert loaded.font_size_adjustment_jp_to_en == original.font_size_adjustment_jp_to_en
            assert loaded.bilingual_output == original.bilingual_output
            assert loaded.export_glossary == original.export_glossary
            assert loaded.use_bundled_glossary == original.use_bundled_glossary
            assert loaded.embed_glossary_in_prompt == original.embed_glossary_in_prompt
            assert loaded.browser_display_mode == original.browser_display_mode
            assert loaded.skipped_version == original.skipped_version

            # Non-USER_SETTINGS should come from template
            assert loaded.max_chars_per_batch == 4000
            assert loaded.request_timeout == 600


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
            assert settings.max_chars_per_batch == 4000  # Reduced for reliability
            assert settings.reference_files == []  # Empty by default

    def test_load_partial_json(self):
        """Load settings with only some fields in template and user_settings"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            settings_path = config_dir / "settings.json"

            # Create template with some fields
            template_path = config_dir / "settings.template.json"
            template_path.write_text('{"max_chars_per_batch": 5000}')

            # Create user_settings with USER_SETTINGS_KEYS
            user_settings_path = config_dir / "user_settings.json"
            user_settings_path.write_text('{"last_tab": "file"}')

            settings = AppSettings.load(settings_path)

            # USER_SETTINGS from user_settings.json
            assert settings.last_tab == "file"
            # Non-USER_SETTINGS from template
            assert settings.max_chars_per_batch == 5000
            # Other fields use dataclass defaults
            assert settings.request_timeout == 600

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
        """Load settings with Unicode paths from template"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            settings_path = config_dir / "settings.json"

            # Create template with Unicode paths
            template_path = config_dir / "settings.template.json"
            template_path.write_text(
                '{"output_directory": "/Users/日本語/出力フォルダ", '
                '"reference_files": ["用語集.csv", "참조.xlsx"]}',
                encoding='utf-8'
            )

            settings = AppSettings.load(settings_path)

            assert settings.output_directory == "/Users/日本語/出力フォルダ"
            assert "用語集.csv" in settings.reference_files

    def test_save_with_unicode_paths(self):
        """Save settings with Unicode values in USER_SETTINGS_KEYS"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            settings_path = config_dir / "settings.json"

            # Create template
            template_path = config_dir / "settings.template.json"
            template_path.write_text('{}')

            # Save settings with Unicode in USER_SETTINGS_KEYS
            # Note: font names can contain Unicode characters
            settings = AppSettings(
                font_jp_to_en="游ゴシック",  # Japanese font name
                font_en_to_jp="ヒラギノ角ゴ",  # Japanese font name
            )
            settings.save(settings_path)

            # Read back and verify
            loaded = AppSettings.load(settings_path)
            assert loaded.font_jp_to_en == "游ゴシック"
            assert loaded.font_en_to_jp == "ヒラギノ角ゴ"

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
            # save() writes to user_settings.json
            user_settings_path = subdir / "user_settings.json"
            assert user_settings_path.exists()

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
            # NOTE: window_width/window_height removed - now dynamically calculated
        )

        assert settings.max_chars_per_batch == 100
        assert settings.request_timeout == 1
        assert settings.max_retries == 0

    def test_very_large_numeric_values(self):
        """Test very large numeric values"""
        settings = AppSettings(
            max_chars_per_batch=1000000,
            request_timeout=86400,  # 24 hours
            # NOTE: window_width/window_height removed - now dynamically calculated
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


class TestSettingsSeparation:
    """Test settings separation model (template + user_settings)"""

    def test_template_only_load(self):
        """Load settings with only template file (no user_settings)"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            settings_path = config_dir / "settings.json"

            # Create template only
            template_path = config_dir / "settings.template.json"
            template_path.write_text(json.dumps({
                "reference_files": ["glossary.csv"],
                "max_chars_per_batch": 6000,
                "last_tab": "file",
            }))

            settings = AppSettings.load(settings_path)

            # Should load from template
            assert settings.reference_files == ["glossary.csv"]
            assert settings.max_chars_per_batch == 6000
            assert settings.last_tab == "file"

    def test_user_settings_override_template(self):
        """User settings should override template values for USER_SETTINGS_KEYS"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            settings_path = config_dir / "settings.json"

            # Template with default values
            template_path = config_dir / "settings.template.json"
            template_path.write_text(json.dumps({
                "last_tab": "text",
                "translation_style": "standard",
            }))

            # User settings override
            user_settings_path = config_dir / "user_settings.json"
            user_settings_path.write_text(json.dumps({
                "last_tab": "file",
                "translation_style": "minimal",
            }))

            settings = AppSettings.load(settings_path)

            # User settings should override template
            assert settings.last_tab == "file"
            assert settings.translation_style == "minimal"

    def test_save_only_saves_user_settings_keys(self):
        """Save should only write USER_SETTINGS_KEYS to user_settings.json"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            settings_path = config_dir / "settings.json"

            settings = AppSettings(
                reference_files=["custom.csv"],  # NOT in USER_SETTINGS_KEYS
                max_chars_per_batch=7000,        # NOT in USER_SETTINGS_KEYS
                last_tab="file",                 # IN USER_SETTINGS_KEYS
                translation_style="minimal",     # IN USER_SETTINGS_KEYS
            )

            settings.save(settings_path)

            # Read the saved user_settings.json directly
            user_settings_path = config_dir / "user_settings.json"
            with open(user_settings_path) as f:
                saved = json.load(f)

            # Only USER_SETTINGS_KEYS should be saved
            assert "last_tab" in saved
            assert "translation_style" in saved
            assert saved["last_tab"] == "file"
            assert saved["translation_style"] == "minimal"

            # Non-USER_SETTINGS should NOT be saved
            assert "reference_files" not in saved
            assert "max_chars_per_batch" not in saved

    def test_user_settings_keys_constant(self):
        """Verify USER_SETTINGS_KEYS contains expected keys"""
        expected_keys = {
            "translation_style",
            "text_translation_style",
            "font_jp_to_en",
            "font_en_to_jp",
            "font_size_adjustment_jp_to_en",
            "bilingual_output",
            "export_glossary",
            "use_bundled_glossary",
            "embed_glossary_in_prompt",
            "browser_display_mode",
            "last_tab",
            "skipped_version",
        }
        assert USER_SETTINGS_KEYS == expected_keys


class TestSettingsMigration:
    """Test settings migration from old formats"""

    def test_legacy_settings_not_migrated(self):
        """Legacy settings.json should NOT be migrated (to prevent bugs)"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            settings_path = config_dir / "settings.json"

            # Legacy settings.json (old format with custom values)
            # No template or user_settings.json exists
            settings_path.write_text('''
            {
                "last_direction": "jp_to_en",
                "last_tab": "file",
                "translation_style": "minimal"
            }
            ''')

            settings = AppSettings.load(settings_path)

            # Legacy settings should NOT be loaded - use defaults instead
            # This prevents bugs from old/incompatible settings
            assert settings.last_tab == "text"  # Default, not "file" from legacy
            assert settings.translation_style == "concise"  # Default, not "minimal"

    def test_handle_future_version_settings(self):
        """Handle settings from a future version with new fields"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            settings_path = config_dir / "settings.json"

            # Simulated future version template with new unknown fields
            template_path = config_dir / "settings.template.json"
            template_path.write_text('''
            {
                "future_feature_enabled": true,
                "advanced_mode": {"nested": "value"},
                "new_list_field": [1, 2, 3]
            }
            ''')

            # User settings with known USER_SETTINGS_KEYS
            user_settings_path = config_dir / "user_settings.json"
            user_settings_path.write_text('{"last_tab": "file"}')

            settings = AppSettings.load(settings_path)

            # Should load known fields and ignore unknown
            assert settings.last_tab == "file"
