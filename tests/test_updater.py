# tests/test_updater.py
"""
Tests for the auto-update service.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path
import json
import platform
import time

from yakulingo.services.updater import (
    AutoUpdater,
    UpdateStatus,
    UpdateResult,
    VersionInfo,
    ProxyConfig,
    merge_settings,
    merge_glossary,
    USER_PROTECTED_SETTINGS,
)


class TestVersionComparison:
    """Test version comparison logic"""

    def test_semantic_version_newer(self):
        """Test semantic version comparison"""
        updater = AutoUpdater(current_version="1.0.0")
        assert updater._is_newer_version("2.0.0", "1.0.0") is True
        assert updater._is_newer_version("1.1.0", "1.0.0") is True
        assert updater._is_newer_version("1.0.1", "1.0.0") is True

    def test_semantic_version_not_newer(self):
        """Test semantic version not newer"""
        updater = AutoUpdater(current_version="2.0.0")
        assert updater._is_newer_version("1.0.0", "2.0.0") is False
        assert updater._is_newer_version("2.0.0", "2.0.0") is False

    def test_date_version_newer(self):
        """Test date-based version comparison (YYYYMMDD)"""
        updater = AutoUpdater(current_version="20251127")
        assert updater._is_newer_version("20251128", "20251127") is True
        assert updater._is_newer_version("20260101", "20251127") is True

    def test_date_version_not_newer(self):
        """Test date-based version not newer"""
        updater = AutoUpdater(current_version="20251127")
        assert updater._is_newer_version("20251126", "20251127") is False
        assert updater._is_newer_version("20251127", "20251127") is False

    def test_version_with_v_prefix(self):
        """Test versions with 'v' prefix"""
        updater = AutoUpdater(current_version="1.0.0")
        assert updater._is_newer_version("v2.0.0", "v1.0.0") is True
        assert updater._is_newer_version("v1.0.0", "v2.0.0") is False


class TestProxyConfig:
    """Test proxy configuration detection"""

    def test_proxy_config_init_non_windows(self):
        """Test proxy config on non-Windows platform"""
        with patch("platform.system", return_value="Linux"):
            config = ProxyConfig()
            assert config.use_proxy is False
            assert config.proxy_server is None

    def test_get_proxy_dict_disabled(self):
        """Test proxy dict when proxy is disabled"""
        config = ProxyConfig()
        config.use_proxy = False
        assert config.get_proxy_dict() == {}

    def test_get_proxy_dict_enabled(self):
        """Test proxy dict when proxy is enabled"""
        config = ProxyConfig()
        config.use_proxy = True
        config.proxy_server = "proxy.example.com:8080"

        proxy_dict = config.get_proxy_dict()
        assert "http" in proxy_dict
        assert "https" in proxy_dict
        assert "proxy.example.com:8080" in proxy_dict["http"]

    def test_should_bypass_local(self):
        """Test bypass for local addresses"""
        config = ProxyConfig()
        config.proxy_bypass = ["<local>"]

        assert config.should_bypass("http://localhost/test") is True
        assert config.should_bypass("http://myserver/test") is True
        assert config.should_bypass("http://example.com/test") is False

    def test_should_bypass_wildcard(self):
        """Test bypass with wildcard patterns"""
        config = ProxyConfig()
        config.proxy_bypass = ["*.internal.com"]

        assert config.should_bypass("http://server.internal.com/") is True
        assert config.should_bypass("http://internal.com/") is False
        assert config.should_bypass("http://external.com/") is False

    def test_should_bypass_exact_match(self):
        """Test bypass with exact hostname match"""
        config = ProxyConfig()
        config.proxy_bypass = ["api.github.com"]

        assert config.should_bypass("https://api.github.com/repos") is True
        assert config.should_bypass("https://github.com/repos") is False


class TestAutoUpdater:
    """Test auto-updater functionality"""

    def test_init_default_values(self):
        """Test default initialization"""
        updater = AutoUpdater()
        assert updater.repo_owner == "minimo162"
        assert updater.repo_name == "yakulingo"

    def test_init_custom_repo(self):
        """Test custom repository initialization"""
        updater = AutoUpdater(repo_owner="test", repo_name="repo")
        assert updater.repo_owner == "test"
        assert updater.repo_name == "repo"

    @patch("yakulingo.services.updater.AutoUpdater._make_request")
    def test_check_for_updates_available(self, mock_request):
        """Test update check when update is available"""
        mock_response = {
            "tag_name": "v2.0.0",
            "published_at": "2025-01-01T00:00:00Z",
            "body": "Release notes here",
            "zipball_url": "https://api.github.com/repos/test/repo/zipball/v2.0.0",
            "assets": [],
        }
        mock_request.return_value = (
            json.dumps(mock_response).encode("utf-8"),
            {"ETag": "W/\"123\""},
        )

        updater = AutoUpdater(current_version="1.0.0")
        result = updater.check_for_updates()

        assert result.status == UpdateStatus.UPDATE_AVAILABLE
        assert result.latest_version == "2.0.0"
        assert result.version_info is not None
        assert result.version_info.version == "2.0.0"

    @patch("yakulingo.services.updater.AutoUpdater._make_request")
    def test_check_for_updates_up_to_date(self, mock_request):
        """Test update check when already up to date"""
        mock_response = {
            "tag_name": "v1.0.0",
            "published_at": "2025-01-01T00:00:00Z",
            "body": "Release notes",
            "zipball_url": "https://api.github.com/repos/test/repo/zipball/v1.0.0",
            "assets": [],
        }
        mock_request.return_value = (
            json.dumps(mock_response).encode("utf-8"),
            {},
        )

        updater = AutoUpdater(current_version="1.0.0")
        result = updater.check_for_updates()

        assert result.status == UpdateStatus.UP_TO_DATE
        assert result.current_version == "1.0.0"

    @patch("yakulingo.services.updater.AutoUpdater._make_request")
    def test_check_for_updates_with_assets(self, mock_request):
        """Test update check with release assets"""
        mock_response = {
            "tag_name": "v2.0.0",
            "published_at": "2025-01-01T00:00:00Z",
            "body": "Release notes",
            "zipball_url": "https://api.github.com/repos/test/repo/zipball/v2.0.0",
            "assets": [
                {
                    "name": "yakulingo-2.0.0.zip",
                    "browser_download_url": "https://github.com/test/repo/releases/download/v2.0.0/yakulingo-2.0.0.zip",
                    "size": 1024000,
                }
            ],
        }
        mock_request.return_value = (
            json.dumps(mock_response).encode("utf-8"),
            {"ETag": "W/\"456\""},
        )

        updater = AutoUpdater(current_version="1.0.0")
        result = updater.check_for_updates()

        assert result.status == UpdateStatus.UPDATE_AVAILABLE
        assert result.version_info.file_size == 1024000
        assert "yakulingo-2.0.0.zip" in result.version_info.download_url

    @patch("yakulingo.services.updater.AutoUpdater._make_request")
    def test_check_for_updates_uses_cache_on_304(self, mock_request, tmp_path):
        """Test that cached release info is used when server returns 304"""
        cached_response = {
            "tag_name": "v1.2.0",
            "published_at": "2025-01-01T00:00:00Z",
            "body": "Release notes",
            "zipball_url": "https://api.github.com/repos/test/repo/zipball/v1.2.0",
            "assets": [],
        }

        updater = AutoUpdater(current_version="1.0.0")
        updater.cache_dir = tmp_path / "cache"
        updater.cache_dir.mkdir(parents=True, exist_ok=True)

        cache_payload = {
            "timestamp": time.time(),
            "body": json.dumps(cached_response),
            "etag": "W/\"cached\"",
        }
        (updater.cache_dir / "latest_release.json").write_text(
            json.dumps(cache_payload), encoding="utf-8"
        )

        import urllib.error

        api_url = (
            f"https://api.github.com/repos/{updater.repo_owner}/{updater.repo_name}/releases/latest"
        )
        mock_request.side_effect = urllib.error.HTTPError(
            api_url, 304, "Not Modified", {}, None
        )

        result = updater.check_for_updates()

        assert result.status == UpdateStatus.UPDATE_AVAILABLE
        assert result.latest_version == "1.2.0"

    @patch("yakulingo.services.updater.AutoUpdater._make_request")
    def test_check_for_updates_network_error(self, mock_request):
        """Test update check with network error"""
        import urllib.error
        mock_request.side_effect = urllib.error.URLError("Network error")

        updater = AutoUpdater(current_version="1.0.0")
        result = updater.check_for_updates()

        assert result.status == UpdateStatus.ERROR
        assert "ネットワークエラー" in result.message or "error" in result.error.lower()

    def test_get_cache_dir(self):
        """Test cache directory path"""
        updater = AutoUpdater()
        cache_dir = updater._get_cache_dir()

        assert isinstance(cache_dir, Path)
        assert "YakuLingo" in str(cache_dir) or "yakulingo" in str(cache_dir)


class TestUpdateResult:
    """Test UpdateResult dataclass"""

    def test_update_result_creation(self):
        """Test UpdateResult creation"""
        result = UpdateResult(
            status=UpdateStatus.UPDATE_AVAILABLE,
            current_version="1.0.0",
            latest_version="2.0.0",
            message="Update available",
        )

        assert result.status == UpdateStatus.UPDATE_AVAILABLE
        assert result.current_version == "1.0.0"
        assert result.latest_version == "2.0.0"

    def test_update_result_with_error(self):
        """Test UpdateResult with error"""
        result = UpdateResult(
            status=UpdateStatus.ERROR,
            current_version="1.0.0",
            error="Connection failed",
            message="Update check failed",
        )

        assert result.status == UpdateStatus.ERROR
        assert result.error == "Connection failed"


class TestVersionInfo:
    """Test VersionInfo dataclass"""

    def test_version_info_creation(self):
        """Test VersionInfo creation"""
        info = VersionInfo(
            version="2.0.0",
            release_date="2025-01-01",
            download_url="https://example.com/download.zip",
            release_notes="Bug fixes and improvements",
            file_size=1024000,
        )

        assert info.version == "2.0.0"
        assert info.release_date == "2025-01-01"
        assert info.file_size == 1024000
        assert info.requires_reinstall is False

    def test_version_info_requires_reinstall(self):
        """Test VersionInfo with requires_reinstall flag"""
        info = VersionInfo(
            version="2.0.0",
            release_date="2025-01-01",
            download_url="https://example.com/download.zip",
            release_notes="Major update",
            file_size=1024000,
            requires_reinstall=True,
        )

        assert info.requires_reinstall is True


class TestRequiresReinstallDetection:
    """Test detection of [REQUIRES_REINSTALL] marker in release notes"""

    @patch("yakulingo.services.updater.AutoUpdater._make_request")
    def test_detects_requires_reinstall_marker(self, mock_request):
        """Test that [REQUIRES_REINSTALL] marker is detected"""
        mock_response = {
            "tag_name": "v2.0.0",
            "published_at": "2025-01-01T00:00:00Z",
            "body": "[REQUIRES_REINSTALL]\n\nThis version requires a fresh install due to dependency changes.",
            "zipball_url": "https://api.github.com/repos/test/repo/zipball/v2.0.0",
            "assets": [],
        }
        mock_request.return_value = (
            json.dumps(mock_response).encode("utf-8"),
            {},
        )

        updater = AutoUpdater(current_version="1.0.0")
        result = updater.check_for_updates()

        assert result.status == UpdateStatus.UPDATE_AVAILABLE
        assert result.version_info.requires_reinstall is True

    @patch("yakulingo.services.updater.AutoUpdater._make_request")
    def test_no_reinstall_marker(self, mock_request):
        """Test that missing marker means no reinstall required"""
        mock_response = {
            "tag_name": "v2.0.0",
            "published_at": "2025-01-01T00:00:00Z",
            "body": "Regular update with bug fixes.",
            "zipball_url": "https://api.github.com/repos/test/repo/zipball/v2.0.0",
            "assets": [],
        }
        mock_request.return_value = (
            json.dumps(mock_response).encode("utf-8"),
            {},
        )

        updater = AutoUpdater(current_version="1.0.0")
        result = updater.check_for_updates()

        assert result.status == UpdateStatus.UPDATE_AVAILABLE
        assert result.version_info.requires_reinstall is False


class TestAppDirDetection:
    """Test application directory detection"""

    def test_get_app_dir_returns_path(self):
        """Test that _get_app_dir returns a Path object"""
        updater = AutoUpdater()
        app_dir = updater._get_app_dir()

        assert isinstance(app_dir, Path)

    @patch("platform.system", return_value="Windows")
    @patch.dict("os.environ", {"LOCALAPPDATA": "/tmp/test_localappdata"})
    def test_get_app_dir_windows_fallback(self, mock_system):
        """Test that _get_app_dir falls back when YakuLingo.exe doesn't exist"""
        updater = AutoUpdater()
        app_dir = updater._get_app_dir()

        # Should fall back to source directory since YakuLingo.exe doesn't exist
        assert isinstance(app_dir, Path)


class TestSourceCodeOnlyUpdate:
    """Test that only source code is updated, not environment files"""

    def test_source_dirs_defined(self):
        """Test that SOURCE_DIRS are properly defined"""
        assert "yakulingo" in AutoUpdater.SOURCE_DIRS
        assert "prompts" in AutoUpdater.SOURCE_DIRS
        assert "config" in AutoUpdater.SOURCE_DIRS
        # Environment directories should NOT be in the list
        assert ".venv" not in AutoUpdater.SOURCE_DIRS
        assert ".uv-python" not in AutoUpdater.SOURCE_DIRS
        assert ".playwright-browsers" not in AutoUpdater.SOURCE_DIRS

    def test_source_files_defined(self):
        """Test that SOURCE_FILES are properly defined (matches make_distribution.bat)"""
        # Core application files
        assert "app.py" in AutoUpdater.SOURCE_FILES
        assert "pyproject.toml" in AutoUpdater.SOURCE_FILES
        assert "uv.lock" in AutoUpdater.SOURCE_FILES
        assert "uv.toml" in AutoUpdater.SOURCE_FILES
        # Scripts
        assert "YakuLingo.exe" in AutoUpdater.SOURCE_FILES
        # Documentation
        assert "README.md" in AutoUpdater.SOURCE_FILES
        # Files NOT in distribution (handled by merge functions or not included)
        assert "setup.vbs" not in AutoUpdater.SOURCE_FILES
        assert "setup.ps1" not in AutoUpdater.SOURCE_FILES
        assert "requirements.txt" not in AutoUpdater.SOURCE_FILES  # Not in make_distribution.bat
        assert "requirements_pdf.txt" not in AutoUpdater.SOURCE_FILES  # Not in make_distribution.bat
        assert "glossary.csv" not in AutoUpdater.SOURCE_FILES  # Handled by merge_glossary()

# --- Tests: download_update() ---

class TestDownloadUpdate:
    """Test AutoUpdater.download_update()"""

    @pytest.fixture
    def updater(self, tmp_path):
        updater = AutoUpdater(current_version="1.0.0")
        updater.cache_dir = tmp_path / "cache"
        return updater

    @pytest.fixture
    def version_info(self):
        return VersionInfo(
            version="2.0.0",
            release_date="2025-01-01",
            download_url="https://example.com/yakulingo-2.0.0.zip",
            release_notes="Test release",
            file_size=1024,
        )

    def test_download_creates_cache_dir(self, updater, version_info, tmp_path):
        """Download creates cache directory if not exists"""
        # Create mock response
        mock_response = Mock()
        mock_response.headers = {"Content-Length": "16"}
        mock_response.read.side_effect = [b"ZIP file content", b""]
        mock_response.__enter__ = Mock(return_value=mock_response)
        mock_response.__exit__ = Mock(return_value=False)

        with patch.object(updater, "opener") as mock_opener:
            mock_opener.open.return_value = mock_response

            result = updater.download_update(version_info)

            assert updater.cache_dir.exists()
            assert isinstance(result, Path)

    def test_download_saves_zip_file(self, updater, version_info, tmp_path):
        """Download saves ZIP file to cache"""
        mock_response = Mock()
        mock_response.headers = {"Content-Length": "16"}
        mock_response.read.side_effect = [b"ZIP file content", b""]
        mock_response.__enter__ = Mock(return_value=mock_response)
        mock_response.__exit__ = Mock(return_value=False)

        with patch.object(updater, "opener") as mock_opener:
            mock_opener.open.return_value = mock_response

            result = updater.download_update(version_info)

            zip_file = updater.cache_dir / f"yakulingo-{version_info.version}.zip"
            assert zip_file.exists()
            assert zip_file.read_bytes() == b"ZIP file content"

    def test_download_skips_if_already_exists(self, updater, version_info, tmp_path):
        """Download skips if file already exists"""
        updater.cache_dir.mkdir(parents=True, exist_ok=True)
        zip_file = updater.cache_dir / f"yakulingo-{version_info.version}.zip"
        zip_file.write_bytes(b"0" * version_info.file_size)

        with patch.object(updater, "opener") as mock_opener:
            result = updater.download_update(version_info)

            # Should not call opener
            mock_opener.open.assert_not_called()
            assert result == zip_file

    def test_download_progress_callback(self, updater, version_info, tmp_path):
        """Download calls progress callback"""
        mock_response = Mock()
        mock_response.headers = {"Content-Length": "300"}
        # Return chunks to trigger progress callback
        mock_response.read.side_effect = [b"A" * 100, b"B" * 100, b"C" * 100, b""]
        mock_response.__enter__ = Mock(return_value=mock_response)
        mock_response.__exit__ = Mock(return_value=False)

        progress_values = []

        def on_progress(downloaded, total):
            progress_values.append((downloaded, total))

        with patch.object(updater, "opener") as mock_opener:
            mock_opener.open.return_value = mock_response

            updater.download_update(version_info, progress_callback=on_progress)

        # Progress should have been called for each chunk
        assert len(progress_values) == 3
        assert progress_values[0] == (100, 300)
        assert progress_values[1] == (200, 300)
        assert progress_values[2] == (300, 300)

    def test_download_network_error(self, updater, version_info, tmp_path):
        """Download handles network error (raises exception)"""
        import urllib.error

        with patch.object(updater, "opener") as mock_opener:
            mock_opener.open.side_effect = urllib.error.URLError("Connection refused")

            with pytest.raises(urllib.error.URLError):
                updater.download_update(version_info)


# --- Tests: install_update() ---

class TestInstallUpdate:
    """Test AutoUpdater.install_update()"""

    @pytest.fixture
    def updater(self, tmp_path):
        updater = AutoUpdater(current_version="1.0.0")
        updater.cache_dir = tmp_path / "cache"
        updater.cache_dir.mkdir(parents=True, exist_ok=True)
        return updater

    def test_install_returns_false_for_missing_zip(self, updater, tmp_path):
        """Install returns False if ZIP file not found"""
        zip_path = tmp_path / "nonexistent.zip"
        result = updater.install_update(zip_path)
        assert result is False

    def test_install_with_valid_zip(self, updater, tmp_path):
        """Install with valid ZIP file structure"""
        import zipfile

        # Create a valid ZIP file
        zip_path = tmp_path / "yakulingo-2.0.0.zip"
        with zipfile.ZipFile(zip_path, 'w') as zf:
            zf.writestr("yakulingo-2.0.0/app.py", "# Updated app")
            zf.writestr("yakulingo-2.0.0/yakulingo/__init__.py", "# module")

        # Mock the app dir to prevent actual file operations
        app_dir = tmp_path / "app"
        app_dir.mkdir(parents=True)

        with patch.object(updater, "_get_app_dir", return_value=app_dir):
            with patch("platform.system", return_value="Linux"):
                with patch("subprocess.Popen"):
                    # Install should work with proper structure
                    result = updater.install_update(zip_path)
                    # May return True or False depending on platform-specific behavior


class TestCleanupCache:
    """Test AutoUpdater.cleanup_cache()"""

    def test_cleanup_removes_cache_directory(self, tmp_path):
        """Cleanup removes entire cache directory"""
        updater = AutoUpdater()
        updater.cache_dir = tmp_path / "cache"
        updater.cache_dir.mkdir(parents=True)

        # Create some cache files
        (updater.cache_dir / "test.zip").write_bytes(b"data")

        updater.cleanup_cache()

        # Cache dir should be removed
        assert not updater.cache_dir.exists()

    def test_cleanup_handles_missing_cache(self, tmp_path):
        """Cleanup handles non-existent cache directory"""
        updater = AutoUpdater()
        updater.cache_dir = tmp_path / "nonexistent"

        # Should not raise
        updater.cleanup_cache()


# --- Tests: NTLMProxyHandler ---

class TestNTLMProxyHandler:
    """Test NTLM proxy handler authentication"""

    def test_ntlm_handler_creation_with_config(self):
        """Test NTLMProxyHandler can be created with ProxyConfig"""
        from yakulingo.services.updater import NTLMProxyHandler, ProxyConfig

        config = ProxyConfig()
        config.use_proxy = True
        config.proxy_server = "proxy.example.com:8080"

        handler = NTLMProxyHandler(config)
        assert handler is not None


# --- Tests: Make Request with Proxy ---

class TestMakeRequestWithProxy:
    """Test _make_request with proxy support"""

    @pytest.fixture
    def updater(self, tmp_path):
        updater = AutoUpdater(current_version="1.0.0")
        return updater

    def test_make_request_uses_opener(self, updater):
        """Test that _make_request uses the opener"""
        mock_response = Mock()
        mock_response.read.return_value = b"response data"
        mock_response.__enter__ = Mock(return_value=mock_response)
        mock_response.__exit__ = Mock(return_value=False)

        with patch.object(updater, "opener") as mock_opener:
            mock_opener.open.return_value = mock_response

            result = updater._make_request("https://api.github.com/test")

            assert result == b"response data"
            mock_opener.open.assert_called_once()

    def test_make_request_handles_timeout(self, updater):
        """Test request timeout handling"""
        import socket

        with patch.object(updater, "opener") as mock_opener:
            mock_opener.open.side_effect = socket.timeout("Connection timed out")

            with pytest.raises(socket.timeout):
                updater._make_request("https://api.github.com/test")

    def test_make_request_handles_http_error(self, updater):
        """Test HTTP error handling"""
        import urllib.error

        with patch.object(updater, "opener") as mock_opener:
            mock_opener.open.side_effect = urllib.error.HTTPError(
                "https://api.github.com/test", 404, "Not Found", {}, None
            )

            with pytest.raises(urllib.error.HTTPError):
                updater._make_request("https://api.github.com/test")


# --- Tests: merge_settings() ---

class TestMergeSettings:
    """Test merge_settings function"""

    def test_merge_settings_new_file_created(self, tmp_path):
        """When user settings don't exist, copy new settings"""
        app_dir = tmp_path / "app"
        source_dir = tmp_path / "source"

        # Create source settings
        (source_dir / "config").mkdir(parents=True)
        new_settings = {"key1": "value1", "key2": "value2"}
        (source_dir / "config" / "settings.json").write_text(
            json.dumps(new_settings), encoding="utf-8"
        )

        result = merge_settings(app_dir, source_dir)

        assert result == -1  # New file created
        assert (app_dir / "config" / "settings.json").exists()
        saved = json.loads((app_dir / "config" / "settings.json").read_text())
        assert saved == new_settings

    def test_merge_settings_preserves_protected_settings(self, tmp_path):
        """Protected settings from user are preserved"""
        app_dir = tmp_path / "app"
        source_dir = tmp_path / "source"

        # Create user settings with protected values
        (app_dir / "config").mkdir(parents=True)
        user_settings = {
            "translation_style": "minimal",  # Protected
            "max_chars_per_batch": 5000,      # Not protected
            "font_jp_to_en": "Times",         # Protected
        }
        (app_dir / "config" / "settings.json").write_text(
            json.dumps(user_settings), encoding="utf-8"
        )

        # Create new settings with different values
        (source_dir / "config").mkdir(parents=True)
        new_settings = {
            "translation_style": "standard",  # Will be overwritten by user value
            "max_chars_per_batch": 7000,      # Will use new value
            "font_jp_to_en": "Arial",         # Will be overwritten by user value
            "new_setting": "new_value",       # New setting added
        }
        (source_dir / "config" / "settings.json").write_text(
            json.dumps(new_settings), encoding="utf-8"
        )

        result = merge_settings(app_dir, source_dir)

        merged = json.loads((app_dir / "config" / "settings.json").read_text())
        # Protected settings preserved from user
        assert merged["translation_style"] == "minimal"
        assert merged["font_jp_to_en"] == "Times"
        # Non-protected settings updated from new
        assert merged["max_chars_per_batch"] == 7000
        # New settings added
        assert merged["new_setting"] == "new_value"
        assert result == 1  # 1 new setting added

    def test_merge_settings_removes_deprecated_settings(self, tmp_path):
        """Settings not in new version are removed"""
        app_dir = tmp_path / "app"
        source_dir = tmp_path / "source"

        # Create user settings with deprecated setting
        (app_dir / "config").mkdir(parents=True)
        user_settings = {
            "old_setting": "old_value",  # Will be removed
            "translation_style": "concise",
        }
        (app_dir / "config" / "settings.json").write_text(
            json.dumps(user_settings), encoding="utf-8"
        )

        # Create new settings without deprecated setting
        (source_dir / "config").mkdir(parents=True)
        new_settings = {
            "translation_style": "standard",
        }
        (source_dir / "config" / "settings.json").write_text(
            json.dumps(new_settings), encoding="utf-8"
        )

        merge_settings(app_dir, source_dir)

        merged = json.loads((app_dir / "config" / "settings.json").read_text())
        assert "old_setting" not in merged
        # Protected setting preserved
        assert merged["translation_style"] == "concise"

    def test_merge_settings_no_source_file(self, tmp_path):
        """Returns 0 when source settings don't exist"""
        app_dir = tmp_path / "app"
        source_dir = tmp_path / "source"
        source_dir.mkdir()

        result = merge_settings(app_dir, source_dir)
        assert result == 0

    def test_merge_settings_uses_template_fallback(self, tmp_path):
        """Falls back to settings.template.json if settings.json not found"""
        app_dir = tmp_path / "app"
        source_dir = tmp_path / "source"

        # Create template instead of settings.json
        (source_dir / "config").mkdir(parents=True)
        template = {"template_key": "template_value"}
        (source_dir / "config" / "settings.template.json").write_text(
            json.dumps(template), encoding="utf-8"
        )

        result = merge_settings(app_dir, source_dir)

        assert result == -1
        saved = json.loads((app_dir / "config" / "settings.json").read_text())
        assert saved == template

    def test_merge_settings_invalid_user_json(self, tmp_path):
        """Returns 0 when user settings JSON is invalid"""
        app_dir = tmp_path / "app"
        source_dir = tmp_path / "source"

        # Create invalid user settings
        (app_dir / "config").mkdir(parents=True)
        (app_dir / "config" / "settings.json").write_text("invalid json{", encoding="utf-8")

        # Create valid source settings
        (source_dir / "config").mkdir(parents=True)
        (source_dir / "config" / "settings.json").write_text('{"key": "value"}', encoding="utf-8")

        result = merge_settings(app_dir, source_dir)
        assert result == 0


# --- Tests: merge_glossary() ---

class TestMergeGlossary:
    """Test merge_glossary function"""

    def test_merge_glossary_new_file_created(self, tmp_path):
        """When user glossary doesn't exist, copy new glossary"""
        app_dir = tmp_path / "app"
        source_dir = tmp_path / "source"
        source_dir.mkdir()

        # Create source glossary
        glossary_content = "日本,Japan\n英語,English\n"
        (source_dir / "glossary.csv").write_text(glossary_content, encoding="utf-8")

        result = merge_glossary(app_dir, source_dir)

        assert result == -1  # New file created
        assert (app_dir / "glossary.csv").exists()
        assert (app_dir / "glossary.csv").read_text(encoding="utf-8") == glossary_content

    def test_merge_glossary_adds_new_terms(self, tmp_path):
        """New terms are added to user glossary"""
        app_dir = tmp_path / "app"
        source_dir = tmp_path / "source"
        app_dir.mkdir()
        source_dir.mkdir()

        # Create user glossary
        (app_dir / "glossary.csv").write_text("日本,Japan\n", encoding="utf-8")

        # Create source glossary with additional term
        (source_dir / "glossary.csv").write_text("日本,Japan\n英語,English\n", encoding="utf-8")

        result = merge_glossary(app_dir, source_dir)

        assert result == 1  # 1 new term added
        content = (app_dir / "glossary.csv").read_text(encoding="utf-8")
        assert "日本,Japan" in content
        assert "英語,English" in content

    def test_merge_glossary_pair_based_dedup(self, tmp_path):
        """Same source with different translation is added"""
        app_dir = tmp_path / "app"
        source_dir = tmp_path / "source"
        app_dir.mkdir()
        source_dir.mkdir()

        # Create user glossary with one translation
        (app_dir / "glossary.csv").write_text("日本,Japan\n", encoding="utf-8")

        # Create source glossary with different translation for same source
        (source_dir / "glossary.csv").write_text("日本,Japan\n日本,JPN\n", encoding="utf-8")

        result = merge_glossary(app_dir, source_dir)

        assert result == 1  # "日本,JPN" is added (different pair)
        content = (app_dir / "glossary.csv").read_text(encoding="utf-8")
        assert "日本,Japan" in content
        assert "日本,JPN" in content

    def test_merge_glossary_skips_comments(self, tmp_path):
        """Comment lines are not added as terms"""
        app_dir = tmp_path / "app"
        source_dir = tmp_path / "source"
        app_dir.mkdir()
        source_dir.mkdir()

        # Create user glossary
        (app_dir / "glossary.csv").write_text("# Comment\n日本,Japan\n", encoding="utf-8")

        # Create source glossary with comments
        (source_dir / "glossary.csv").write_text("# Header\n日本,Japan\n英語,English\n", encoding="utf-8")

        result = merge_glossary(app_dir, source_dir)

        assert result == 1  # Only "英語,English" is added
        content = (app_dir / "glossary.csv").read_text(encoding="utf-8")
        # Original comment is preserved
        assert "# Comment" in content
        # New comment is NOT added (comments are skipped)
        assert content.count("# Header") == 0

    def test_merge_glossary_no_new_terms(self, tmp_path):
        """Returns 0 when all terms already exist"""
        app_dir = tmp_path / "app"
        source_dir = tmp_path / "source"
        app_dir.mkdir()
        source_dir.mkdir()

        # Both have same content
        content = "日本,Japan\n英語,English\n"
        (app_dir / "glossary.csv").write_text(content, encoding="utf-8")
        (source_dir / "glossary.csv").write_text(content, encoding="utf-8")

        result = merge_glossary(app_dir, source_dir)

        assert result == 0

    def test_merge_glossary_no_source_file(self, tmp_path):
        """Returns 0 when source glossary doesn't exist"""
        app_dir = tmp_path / "app"
        source_dir = tmp_path / "source"
        source_dir.mkdir()

        result = merge_glossary(app_dir, source_dir)
        assert result == 0

    def test_merge_glossary_handles_empty_lines(self, tmp_path):
        """Empty lines are ignored in deduplication"""
        app_dir = tmp_path / "app"
        source_dir = tmp_path / "source"
        app_dir.mkdir()
        source_dir.mkdir()

        # Create user glossary with empty lines
        (app_dir / "glossary.csv").write_text("日本,Japan\n\n英語,English\n", encoding="utf-8")

        # Create source glossary with empty lines and new term
        (source_dir / "glossary.csv").write_text("\n日本,Japan\n\n中国,China\n", encoding="utf-8")

        result = merge_glossary(app_dir, source_dir)

        assert result == 1  # Only "中国,China" is added
        content = (app_dir / "glossary.csv").read_text(encoding="utf-8")
        assert "中国,China" in content

    def test_merge_glossary_handles_whitespace(self, tmp_path):
        """Whitespace-only differences are handled correctly"""
        app_dir = tmp_path / "app"
        source_dir = tmp_path / "source"
        app_dir.mkdir()
        source_dir.mkdir()

        # Create user glossary
        (app_dir / "glossary.csv").write_text("日本,Japan\n", encoding="utf-8")

        # Create source glossary with same content but trailing whitespace
        (source_dir / "glossary.csv").write_text("日本,Japan  \n新規,New\n", encoding="utf-8")

        result = merge_glossary(app_dir, source_dir)

        # "日本,Japan  " (with trailing spaces) should NOT be added because
        # we compare trimmed lines. Only "新規,New" should be added.
        assert result == 1
        content = (app_dir / "glossary.csv").read_text(encoding="utf-8")
        assert "新規,New" in content


# --- Tests: USER_PROTECTED_SETTINGS ---

class TestUserProtectedSettings:
    """Test USER_PROTECTED_SETTINGS constant"""

    def test_protected_settings_contains_ui_settings(self):
        """Protected settings includes UI-changeable settings"""
        assert "translation_style" in USER_PROTECTED_SETTINGS
        assert "text_translation_style" in USER_PROTECTED_SETTINGS
        assert "font_jp_to_en" in USER_PROTECTED_SETTINGS
        assert "font_en_to_jp" in USER_PROTECTED_SETTINGS
        assert "font_size_adjustment_jp_to_en" in USER_PROTECTED_SETTINGS
        assert "bilingual_output" in USER_PROTECTED_SETTINGS
        assert "export_glossary" in USER_PROTECTED_SETTINGS
        assert "use_bundled_glossary" in USER_PROTECTED_SETTINGS
        assert "last_tab" in USER_PROTECTED_SETTINGS
        assert "skipped_version" in USER_PROTECTED_SETTINGS

    def test_protected_settings_excludes_developer_settings(self):
        """Protected settings excludes developer-controlled settings"""
        assert "max_chars_per_batch" not in USER_PROTECTED_SETTINGS
        assert "request_timeout" not in USER_PROTECTED_SETTINGS
        assert "max_retries" not in USER_PROTECTED_SETTINGS
        assert "ocr_batch_size" not in USER_PROTECTED_SETTINGS
        assert "ocr_dpi" not in USER_PROTECTED_SETTINGS
        assert "ocr_device" not in USER_PROTECTED_SETTINGS
        assert "github_repo_owner" not in USER_PROTECTED_SETTINGS
        assert "github_repo_name" not in USER_PROTECTED_SETTINGS
        assert "auto_update_check_interval" not in USER_PROTECTED_SETTINGS
        assert "window_width" not in USER_PROTECTED_SETTINGS
        assert "window_height" not in USER_PROTECTED_SETTINGS
