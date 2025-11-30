# tests/test_updater.py
"""
Tests for the auto-update service.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path
import json
import platform

from yakulingo.services.updater import (
    AutoUpdater,
    UpdateStatus,
    UpdateResult,
    VersionInfo,
    ProxyConfig,
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
        mock_request.return_value = json.dumps(mock_response).encode("utf-8")

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
        mock_request.return_value = json.dumps(mock_response).encode("utf-8")

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
        mock_request.return_value = json.dumps(mock_response).encode("utf-8")

        updater = AutoUpdater(current_version="1.0.0")
        result = updater.check_for_updates()

        assert result.status == UpdateStatus.UPDATE_AVAILABLE
        assert result.version_info.file_size == 1024000
        assert "yakulingo-2.0.0.zip" in result.version_info.download_url

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
        mock_request.return_value = json.dumps(mock_response).encode("utf-8")

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
        mock_request.return_value = json.dumps(mock_response).encode("utf-8")

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
        """Test that _get_app_dir falls back when run.bat doesn't exist"""
        updater = AutoUpdater()
        app_dir = updater._get_app_dir()

        # Should fall back to source directory since run.bat doesn't exist
        assert isinstance(app_dir, Path)


class TestSourceCodeOnlyUpdate:
    """Test that only source code is updated, not environment files"""

    def test_source_dirs_defined(self):
        """Test that SOURCE_DIRS are properly defined"""
        assert "yakulingo" in AutoUpdater.SOURCE_DIRS
        assert "prompts" in AutoUpdater.SOURCE_DIRS
        # Environment directories should NOT be in the list
        assert ".venv" not in AutoUpdater.SOURCE_DIRS
        assert ".uv-python" not in AutoUpdater.SOURCE_DIRS
        assert ".playwright-browsers" not in AutoUpdater.SOURCE_DIRS
        # config is not in distribution ZIP (created by setup.ps1)
        assert "config" not in AutoUpdater.SOURCE_DIRS

    def test_source_files_defined(self):
        """Test that SOURCE_FILES are properly defined"""
        assert "app.py" in AutoUpdater.SOURCE_FILES
        assert "pyproject.toml" in AutoUpdater.SOURCE_FILES
        assert "uv.toml" in AutoUpdater.SOURCE_FILES
        # requirements.txt is not in distribution ZIP
        assert "requirements.txt" not in AutoUpdater.SOURCE_FILES

    def test_user_files_defined(self):
        """Test that USER_FILES are properly defined for backup"""
        assert "glossary.csv" in AutoUpdater.USER_FILES
        assert "config/settings.json" in AutoUpdater.USER_FILES
