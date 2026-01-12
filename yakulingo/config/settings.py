# yakulingo/config/settings.py
"""
Application settings management for YakuLingo.

設定ファイルの分離方式:
- settings.template.json: デフォルト値（開発者が管理、アップデートで上書き）
- user_settings.json: ユーザーが変更した設定のみ保存
- 起動時にtemplateを読み込み、user_settingsで上書き

キャッシュ機構:
- _settings_cache: パスをキーとしてAppSettingsインスタンスをキャッシュ
- load()はキャッシュを優先し、ファイルI/Oを削減
- save()時にキャッシュを更新
- invalidate_cache()で明示的にキャッシュをクリア可能
"""

import importlib.metadata
import logging
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import json
from importlib.metadata import PackageNotFoundError
from packaging.version import InvalidVersion, Version

# Module logger
logger = logging.getLogger(__name__)

# Settings cache: path -> (mtime_template, mtime_user, AppSettings)
# mtime is used to detect file changes and invalidate cache
_settings_cache: dict[str, tuple[float, float, "AppSettings"]] = {}
_settings_cache_lock = threading.Lock()

# ユーザーが変更可能な設定項目（user_settings.jsonに保存される）
USER_SETTINGS_KEYS = {
    # 翻訳スタイル設定（設定ダイアログで変更）
    "translation_style",
    # フォント設定（設定ダイアログで変更）
    "font_jp_to_en",
    "font_en_to_jp",
    "font_size_adjustment_jp_to_en",
    # 出力オプション（ファイル翻訳パネルで変更）
    "bilingual_output",
    "export_glossary",
    "use_bundled_glossary",
    # ブラウザ表示モード
    "browser_display_mode",
    # UI状態（自動保存）
    "last_tab",
    # 翻訳バックエンド（Copilot / Local AI）
    "translation_backend",
    "copilot_enabled",
    # Local AI（高度設定）
    "local_ai_model_path",
    "local_ai_server_dir",
    "local_ai_host",
    "local_ai_port_base",
    "local_ai_port_max",
    "local_ai_ctx_size",
    "local_ai_threads",
    "local_ai_temperature",
    "local_ai_max_tokens",
    "local_ai_batch_size",
    "local_ai_ubatch_size",
    "local_ai_max_chars_per_batch",
    "local_ai_max_chars_per_batch_file",
}

DEFAULT_MAX_CHARS_PER_BATCH = 4000


def resolve_browser_display_mode(
    requested_mode: str, screen_width: Optional[int]
) -> str:
    """Resolve browser display mode (side_panel is no longer supported)."""
    if requested_mode == "foreground":
        return "foreground"
    if requested_mode == "minimized":
        return "minimized"
    return "minimized"


@dataclass(frozen=True)
class LoginOverlayGuardResolved:
    enabled: bool
    source: str
    remove_after_version: Optional[str]
    current_version: Optional[str]
    expired: bool
    disable_reason: Optional[str]


@dataclass(frozen=True)
class BrowserDisplayAction:
    overlay_allowed: bool
    foreground_allowed: bool
    effective_mode: str
    guard_enabled: bool
    guard_source: str
    guard_disable_reason: Optional[str]


_ENV_WARNING_LOGGED: set[str] = set()


def _warn_env_once(var_name: str, message: str) -> None:
    if var_name in _ENV_WARNING_LOGGED:
        return
    _ENV_WARNING_LOGGED.add(var_name)
    logger.warning(message)


def _parse_env_bool(var_name: str, raw_value: Optional[str]) -> Optional[bool]:
    if raw_value is None:
        return None
    value = raw_value.strip().lower()
    if not value:
        _warn_env_once(var_name, f"Env {var_name} is empty; treating as unset")
        return None
    if value in ("1", "true", "yes", "on"):
        return True
    if value in ("0", "false", "no", "off"):
        return False
    _warn_env_once(
        var_name, f"Env {var_name} has invalid value '{raw_value}'; treating as unset"
    )
    return None


def _parse_env_version(var_name: str, raw_value: Optional[str]) -> Optional[Version]:
    if raw_value is None:
        return None
    value = raw_value.strip()
    if not value:
        _warn_env_once(var_name, f"Env {var_name} is empty; treating as unset")
        return None
    try:
        return Version(value)
    except InvalidVersion:
        _warn_env_once(
            var_name,
            f"Env {var_name} has invalid version '{raw_value}'; treating as unset",
        )
        return None


def _parse_version_value(raw_value: object, field_name: str) -> Optional[Version]:
    if raw_value is None:
        return None
    if not isinstance(raw_value, str):
        logger.warning(
            "Login overlay guard %s must be a string, got %s",
            field_name,
            type(raw_value).__name__,
        )
        return None
    try:
        return Version(raw_value)
    except InvalidVersion:
        logger.warning(
            "Login overlay guard %s has invalid version '%s'", field_name, raw_value
        )
        return None


def _get_current_version() -> Optional[Version]:
    version_text: Optional[str] = None
    try:
        version_text = importlib.metadata.version("yakulingo")
    except PackageNotFoundError:
        try:
            from yakulingo import __version__ as fallback_version
        except Exception:
            fallback_version = None
        if fallback_version:
            version_text = fallback_version
    if not version_text:
        return None
    try:
        return Version(version_text)
    except InvalidVersion:
        logger.warning("Current version string is invalid: %s", version_text)
        return None


def resolve_login_overlay_guard(
    guard_config: object,
    source: str,
) -> LoginOverlayGuardResolved:
    config_enabled = False
    config_remove_after_version = None
    if isinstance(guard_config, dict):
        config_enabled = bool(guard_config.get("enabled", False))
        config_remove_after_version = guard_config.get("remove_after_version")
    elif guard_config is not None:
        logger.warning(
            "Login overlay guard config should be an object, got %s",
            type(guard_config).__name__,
        )

    env_enabled_raw = os.environ.get("YAKULINGO_LOGIN_OVERLAY_GUARD_ENABLED")
    env_remove_raw = os.environ.get(
        "YAKULINGO_LOGIN_OVERLAY_GUARD_REMOVE_AFTER_VERSION"
    )
    env_enabled = _parse_env_bool(
        "YAKULINGO_LOGIN_OVERLAY_GUARD_ENABLED", env_enabled_raw
    )
    env_remove_after = _parse_env_version(
        "YAKULINGO_LOGIN_OVERLAY_GUARD_REMOVE_AFTER_VERSION",
        env_remove_raw,
    )

    if env_enabled_raw is not None or env_remove_raw is not None:
        logger.info(
            "Login overlay guard env inputs: enabled=%r parsed=%s, remove_after_version=%r parsed=%s",
            env_enabled_raw,
            env_enabled,
            env_remove_raw,
            str(env_remove_after) if env_remove_after else None,
        )

    use_env = env_enabled is not None or env_remove_after is not None
    resolved_source = source
    enabled = config_enabled
    remove_after_version = _parse_version_value(
        config_remove_after_version, "remove_after_version"
    )
    if use_env:
        resolved_source = "env"
        enabled = bool(env_enabled) if env_enabled is not None else False
        remove_after_version = env_remove_after

    disable_reason = None
    expired = False
    current_version = _get_current_version()

    if enabled:
        if remove_after_version is None:
            disable_reason = "missing_or_invalid_remove_after_version"
            enabled = False
        elif current_version is None:
            disable_reason = "current_version_unknown"
            enabled = False
        elif current_version >= remove_after_version:
            disable_reason = "expired"
            enabled = False
            expired = True
    else:
        disable_reason = "disabled"

    if not enabled and disable_reason is None:
        disable_reason = "disabled"

    resolved = LoginOverlayGuardResolved(
        enabled=enabled,
        source=resolved_source,
        remove_after_version=str(remove_after_version)
        if remove_after_version
        else None,
        current_version=str(current_version) if current_version else None,
        expired=expired,
        disable_reason=disable_reason,
    )

    logger.info(
        "Login overlay guard resolved: enabled=%s source=%s remove_after_version=%s current_version=%s expired=%s disable_reason=%s",
        resolved.enabled,
        resolved.source,
        resolved.remove_after_version,
        resolved.current_version,
        resolved.expired,
        resolved.disable_reason,
    )

    return resolved


def resolve_browser_display_action(
    requested_mode: str,
    screen_width: Optional[int],
    guard: LoginOverlayGuardResolved,
) -> BrowserDisplayAction:
    effective_mode = resolve_browser_display_mode(requested_mode, screen_width)
    overlay_allowed = not guard.enabled
    foreground_allowed = effective_mode == "foreground" or not guard.enabled

    action = BrowserDisplayAction(
        overlay_allowed=overlay_allowed,
        foreground_allowed=foreground_allowed,
        effective_mode=effective_mode,
        guard_enabled=guard.enabled,
        guard_source=guard.source,
        guard_disable_reason=guard.disable_reason,
    )

    logger.info(
        "Browser display action resolved: requested=%s effective=%s guard_enabled=%s guard_source=%s guard_reason=%s overlay_allowed=%s foreground_allowed=%s",
        requested_mode,
        effective_mode,
        guard.enabled,
        guard.source,
        guard.disable_reason,
        action.overlay_allowed,
        action.foreground_allowed,
    )

    return action


@dataclass
class AppSettings:
    """Application settings"""

    # Reference Files (用語集、参考資料など)
    # Default is empty; bundled glossary can be enabled via use_bundled_glossary
    reference_files: list[str] = field(default_factory=list)

    # Cache for resolved reference file paths (not persisted)
    _ref_paths_cache: Optional[tuple[str, list[Path]]] = field(
        default=None, repr=False, compare=False
    )

    # Output (常に別ファイルとして _translated 付きで保存)
    output_directory: Optional[str] = None  # None = same as input

    # UI
    last_tab: str = "text"
    # Translation backend ("copilot" or "local")
    translation_backend: str = "copilot"
    # Copilot availability (feature flag)
    copilot_enabled: bool = True
    # NOTE: window_width/window_height は廃止。ウィンドウサイズは
    # _detect_display_settings() で論理解像度から動的に計算される。

    # Advanced
    max_chars_per_batch: int = (
        DEFAULT_MAX_CHARS_PER_BATCH  # Max characters per batch (Copilot input safety)
    )
    request_timeout: int = 600  # Seconds (10 minutes - allows for large translations)
    max_retries: int = 3

    # Local AI (llama.cpp llama-server) - M1 minimal settings
    # NOTE: Host is forced to 127.0.0.1 for security (no external exposure).
    local_ai_model_path: str = "local_ai/models/shisa-v2.1-qwen3-8B-UD-Q4_K_XL.gguf"
    local_ai_server_dir: str = "local_ai/llama_cpp"
    local_ai_host: str = "127.0.0.1"
    local_ai_port_base: int = 4891
    local_ai_port_max: int = 4900
    local_ai_ctx_size: int = 8192
    local_ai_threads: int = 0  # 0=auto
    local_ai_temperature: float = 0.7
    local_ai_max_tokens: Optional[int] = 1024
    local_ai_batch_size: Optional[int] = 512
    local_ai_ubatch_size: Optional[int] = 128
    local_ai_max_chars_per_batch: int = 1000
    local_ai_max_chars_per_batch_file: int = 800

    # File Translation Options (共通オプション)
    bilingual_output: bool = False  # 対訳出力（原文と翻訳を交互に配置）
    export_glossary: bool = False  # 対訳CSV出力（glossaryとして再利用可能）
    translation_style: str = (
        "concise"  # ファイル翻訳の英訳スタイル: "standard", "concise", "minimal"
    )

    # Text Translation Options
    use_bundled_glossary: bool = (
        True  # 同梱の glossary.csv を使用するか（デフォルトでオン）
    )

    # Font Settings (ファイル翻訳用 - 全形式共通)
    # フォントサイズ調整（JP→EN時）: 0で調整なし、負値で縮小
    font_size_adjustment_jp_to_en: float = 0.0  # pt
    font_size_min: float = 8.0  # pt (最小フォントサイズ)

    # 出力フォント（言語方向のみで決定、元フォント種別は無視）
    font_jp_to_en: str = "Arial"  # 英訳時の出力フォント
    font_en_to_jp: str = "MS Pゴシック"  # 和訳時の出力フォント

    # PDF Layout Options (PP-DocLayout-L)
    ocr_batch_size: int = 5  # ページ/バッチ（メモリ使用量とのトレードオフ）
    ocr_dpi: int = 300  # レイアウト解析解像度（高いほど精度向上、処理時間増加）
    ocr_device: str = "auto"  # "auto", "cpu", "cuda"

    # Browser Display Mode (翻訳時のEdgeブラウザ表示方法)
    # "minimized": 最小化して非表示
    # "foreground": 前面に表示
    browser_display_mode: str = "minimized"
    # Login overlay guard (Edge foreground/overlay A/B guard)
    login_overlay_guard: dict[str, object] = field(
        default_factory=lambda: {"enabled": False, "remove_after_version": None}
    )

    # Auto Update
    auto_update_enabled: bool = True  # 起動時に自動チェック
    auto_update_check_interval: int = 0  # チェック間隔（秒）: 0 = 起動毎
    github_repo_owner: str = "minimo162"  # GitHubリポジトリオーナー
    github_repo_name: str = "yakulingo"  # GitHubリポジトリ名
    last_update_check: Optional[str] = None  # 最後のチェック日時（ISO形式）

    _login_overlay_guard_resolved: Optional[LoginOverlayGuardResolved] = field(
        default=None, init=False, repr=False, compare=False
    )
    _login_overlay_guard_source: str = field(
        default="default", init=False, repr=False, compare=False
    )

    @classmethod
    def load(cls, path: Path, use_cache: bool = True) -> "AppSettings":
        """Load settings from template and user settings files.

        分離方式:
        1. settings.template.json からデフォルト値を読み込み
        2. user_settings.json でユーザー設定を上書き

        キャッシュ機構:
        - use_cache=True（デフォルト）の場合、キャッシュを優先
        - ファイルの更新時刻が変わった場合は自動的にリロード
        - use_cache=Falseで強制リロード

        Args:
            path: 設定ファイルのパス（config/settings.json または config/settings.template.json）
                  実際にはtemplateとuser_settingsを探すためのベースパスとして使用
            use_cache: キャッシュを使用するかどうか（デフォルト: True）
        """
        # Determine base config directory
        config_dir = path.parent
        template_path = config_dir / "settings.template.json"
        user_settings_path = config_dir / "user_settings.json"

        cache_key = str(path.resolve())

        # Get current file modification times
        template_mtime = (
            template_path.stat().st_mtime if template_path.exists() else 0.0
        )
        user_mtime = (
            user_settings_path.stat().st_mtime if user_settings_path.exists() else 0.0
        )

        # Check cache
        if use_cache:
            with _settings_cache_lock:
                if cache_key in _settings_cache:
                    cached_template_mtime, cached_user_mtime, cached_settings = (
                        _settings_cache[cache_key]
                    )
                    if (
                        cached_template_mtime == template_mtime
                        and cached_user_mtime == user_mtime
                    ):
                        logger.debug("Using cached settings for: %s", path)
                        return cached_settings

        # Start with defaults
        data = {}
        guard_source = "default"

        # 1. Load from template (developer defaults)
        if template_path.exists():
            try:
                with open(template_path, "r", encoding="utf-8-sig") as f:
                    data = json.load(f)
                    if "login_overlay_guard" in data:
                        guard_source = "template"
                    logger.debug("Loaded template settings from: %s", template_path)
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                logger.warning("Failed to load template settings: %s", e)

        # 2. Override with user settings
        if user_settings_path.exists():
            try:
                with open(user_settings_path, "r", encoding="utf-8-sig") as f:
                    user_data = json.load(f)
                    # Only apply known user settings keys
                    for key in USER_SETTINGS_KEYS:
                        if key in user_data:
                            data[key] = user_data[key]
                    if "login_overlay_guard" in user_data:
                        data["login_overlay_guard"] = user_data["login_overlay_guard"]
                        guard_source = "user"
                    logger.debug("Loaded user settings from: %s", user_settings_path)
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                logger.warning("Failed to load user settings: %s", e)

        # NOTE: Legacy settings.json is NOT migrated to prevent bugs.
        # Users will start with fresh defaults from template.

        # Clean up deprecated fields
        data.pop("last_direction", None)
        data.pop("window_width", None)
        data.pop("window_height", None)
        data.pop("pdf_bilingual_output", None)
        data.pop("pdf_export_glossary", None)
        data.pop("font_jp_to_en_mincho", None)
        data.pop("font_jp_to_en_gothic", None)
        data.pop("font_en_to_jp_serif", None)
        data.pop("font_en_to_jp_sans", None)
        data.pop("pdf_font_ja", None)
        data.pop("pdf_font_en", None)

        # Filter to only known fields
        known_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered_data = {k: v for k, v in data.items() if k in known_fields}

        settings = cls(**filtered_data)
        settings._login_overlay_guard_source = guard_source
        settings._validate()
        settings._login_overlay_guard_resolved = resolve_login_overlay_guard(
            settings.login_overlay_guard,
            settings._login_overlay_guard_source,
        )

        # Update cache
        with _settings_cache_lock:
            _settings_cache[cache_key] = (template_mtime, user_mtime, settings)

        return settings

    def _validate(self) -> None:
        """Validate and normalize setting values for consistency.

        Ensures values are within acceptable ranges and cross-validates
        related settings. Invalid values are reset to defaults with warnings.
        """
        # Font size constraints
        if self.font_size_min < 1.0:
            logger.warning(
                "font_size_min too small (%.1f), resetting to 8.0", self.font_size_min
            )
            self.font_size_min = 8.0
        elif self.font_size_min > 72.0:
            logger.warning(
                "font_size_min too large (%.1f), resetting to 8.0", self.font_size_min
            )
            self.font_size_min = 8.0

        # Batch size constraints
        if self.max_chars_per_batch < 100:
            logger.warning(
                "max_chars_per_batch too small (%d), resetting to %d",
                self.max_chars_per_batch,
                DEFAULT_MAX_CHARS_PER_BATCH,
            )
            self.max_chars_per_batch = DEFAULT_MAX_CHARS_PER_BATCH

        # Translation backend
        if self.translation_backend not in ("copilot", "local"):
            logger.warning(
                "translation_backend invalid (%s), resetting to 'copilot'",
                self.translation_backend,
            )
            self.translation_backend = "copilot"
        if not isinstance(self.copilot_enabled, bool):
            logger.warning(
                "copilot_enabled invalid (%s), resetting to True",
                type(self.copilot_enabled).__name__,
            )
            self.copilot_enabled = True
        if not self.copilot_enabled and self.translation_backend == "copilot":
            logger.info(
                "copilot_enabled is false; forcing translation_backend to 'local'"
            )
            self.translation_backend = "local"

        # Local AI security: always bind to localhost
        if self.local_ai_host != "127.0.0.1":
            logger.warning(
                "local_ai_host must be 127.0.0.1 (got %s); forcing localhost for security",
                self.local_ai_host,
            )
            self.local_ai_host = "127.0.0.1"

        # Local AI port range constraints
        if self.local_ai_port_base < 1024 or self.local_ai_port_base > 65535:
            logger.warning(
                "local_ai_port_base out of range (%d), resetting to 4891",
                self.local_ai_port_base,
            )
            self.local_ai_port_base = 4891
        if self.local_ai_port_max < 1024 or self.local_ai_port_max > 65535:
            logger.warning(
                "local_ai_port_max out of range (%d), resetting to %d",
                self.local_ai_port_max,
                min(65535, self.local_ai_port_base + 9),
            )
            self.local_ai_port_max = min(65535, self.local_ai_port_base + 9)
        if self.local_ai_port_max < self.local_ai_port_base:
            suggested = min(65535, self.local_ai_port_base + 9)
            logger.warning(
                "local_ai_port_max must be >= local_ai_port_base (%d < %d), resetting to %d",
                self.local_ai_port_max,
                self.local_ai_port_base,
                suggested,
            )
            self.local_ai_port_max = suggested

        # Local AI misc numeric constraints
        if self.local_ai_threads < 0:
            logger.warning(
                "local_ai_threads must be >=0 (%d), resetting to 0",
                self.local_ai_threads,
            )
            self.local_ai_threads = 0
        if self.local_ai_max_tokens is not None and self.local_ai_max_tokens < 1:
            logger.warning(
                "local_ai_max_tokens must be positive (%d), resetting to None",
                self.local_ai_max_tokens,
            )
            self.local_ai_max_tokens = None

        # Local AI ctx size constraints (conservative)
        if self.local_ai_ctx_size < 512:
            logger.warning(
                "local_ai_ctx_size too small (%d), resetting to 8192",
                self.local_ai_ctx_size,
            )
            self.local_ai_ctx_size = 8192

        # Local AI batch sizing (safety clamps)
        if self.local_ai_batch_size is not None:
            if self.local_ai_batch_size < 1:
                logger.warning(
                    "local_ai_batch_size must be positive (%d), resetting to None",
                    self.local_ai_batch_size,
                )
                self.local_ai_batch_size = None
            elif self.local_ai_batch_size > self.local_ai_ctx_size:
                logger.warning(
                    "local_ai_batch_size too large (%d), resetting to %d",
                    self.local_ai_batch_size,
                    self.local_ai_ctx_size,
                )
                self.local_ai_batch_size = self.local_ai_ctx_size

        if self.local_ai_ubatch_size is not None:
            if self.local_ai_ubatch_size < 1:
                logger.warning(
                    "local_ai_ubatch_size must be positive (%d), resetting to None",
                    self.local_ai_ubatch_size,
                )
                self.local_ai_ubatch_size = None
            elif (
                self.local_ai_batch_size is not None
                and self.local_ai_ubatch_size > self.local_ai_batch_size
            ):
                logger.warning(
                    "local_ai_ubatch_size too large (%d), resetting to %d",
                    self.local_ai_ubatch_size,
                    self.local_ai_batch_size,
                )
                self.local_ai_ubatch_size = self.local_ai_batch_size
            elif self.local_ai_ubatch_size > self.local_ai_ctx_size:
                logger.warning(
                    "local_ai_ubatch_size too large (%d), resetting to %d",
                    self.local_ai_ubatch_size,
                    self.local_ai_ctx_size,
                )
                self.local_ai_ubatch_size = self.local_ai_ctx_size

        # Local AI batch size constraints
        if self.local_ai_max_chars_per_batch < 100:
            logger.warning(
                "local_ai_max_chars_per_batch too small (%d), resetting to 1000",
                self.local_ai_max_chars_per_batch,
            )
            self.local_ai_max_chars_per_batch = 1000
        if self.local_ai_max_chars_per_batch_file < 100:
            logger.warning(
                "local_ai_max_chars_per_batch_file too small (%d), resetting to 800",
                self.local_ai_max_chars_per_batch_file,
            )
            self.local_ai_max_chars_per_batch_file = 800

        # Local AI sampling params constraints
        if self.local_ai_temperature < 0.0 or self.local_ai_temperature > 2.0:
            logger.warning(
                "local_ai_temperature out of range (%.3f), resetting to 0.2",
                self.local_ai_temperature,
            )
            self.local_ai_temperature = 0.2

        # Timeout constraints
        if self.request_timeout < 10:
            logger.warning(
                "request_timeout too small (%d), resetting to 600", self.request_timeout
            )
            self.request_timeout = 600
        elif self.request_timeout > 1800:
            logger.warning(
                "request_timeout too large (%d), resetting to 600", self.request_timeout
            )
            self.request_timeout = 600

        # OCR settings
        if self.ocr_batch_size < 1:
            self.ocr_batch_size = 5
        if self.ocr_dpi < 72 or self.ocr_dpi > 600:
            logger.warning("ocr_dpi out of range (%d), resetting to 300", self.ocr_dpi)
            self.ocr_dpi = 300

    @property
    def login_overlay_guard_resolved(self) -> LoginOverlayGuardResolved:
        """Return the resolved login overlay guard configuration."""
        if self._login_overlay_guard_resolved is None:
            self._login_overlay_guard_resolved = resolve_login_overlay_guard(
                self.login_overlay_guard,
                self._login_overlay_guard_source,
            )
        return self._login_overlay_guard_resolved

    def save(self, path: Path) -> None:
        """Save user settings to user_settings.json.

        ユーザーが変更した設定のみをuser_settings.jsonに保存。
        settings.template.jsonは変更しない。
        保存後、キャッシュを更新する。

        Args:
            path: 設定ファイルのパス（config/settings.json）
                  実際にはconfig/user_settings.jsonに保存
        """
        config_dir = path.parent
        user_settings_path = config_dir / "user_settings.json"
        template_path = config_dir / "settings.template.json"

        config_dir.mkdir(parents=True, exist_ok=True)

        # Only save user-changeable settings
        data = {}
        for key in USER_SETTINGS_KEYS:
            if hasattr(self, key):
                data[key] = getattr(self, key)

        with open(user_settings_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        logger.debug("Saved user settings to: %s", user_settings_path)

        # Update cache with new modification times
        cache_key = str(path.resolve())
        template_mtime = (
            template_path.stat().st_mtime if template_path.exists() else 0.0
        )
        user_mtime = (
            user_settings_path.stat().st_mtime if user_settings_path.exists() else 0.0
        )
        with _settings_cache_lock:
            _settings_cache[cache_key] = (template_mtime, user_mtime, self)

    def get_reference_file_paths(self, base_dir: Path) -> list[Path]:
        """
        Get resolved reference file paths.
        Returns only existing files within the base directory.

        Security: Validates paths to prevent path traversal attacks.

        Performance: Caches results to avoid repeated path resolution.
        Cache is invalidated when base_dir or reference_files change.
        """
        # Create cache key from base_dir and reference_files
        base_dir_str = str(base_dir.resolve())
        cache_key = f"{base_dir_str}:{','.join(self.reference_files)}"

        # Check cache
        if self._ref_paths_cache is not None:
            cached_key, cached_paths = self._ref_paths_cache
            if cached_key == cache_key:
                return cached_paths

        # Resolve paths
        paths = []
        base_dir_resolved = base_dir.resolve()
        base_dir_abs = base_dir.absolute()

        for ref_file in self.reference_files:
            path = Path(ref_file)
            if not path.is_absolute():
                path = base_dir_abs / path
            path = path.absolute()

            # Resolve to absolute path and check for path traversal
            resolved_path = path.resolve()

            # Ensure the resolved path is within the base directory
            try:
                resolved_path.relative_to(base_dir_resolved)
            except ValueError:
                # Path is outside base directory - skip for security
                continue

            if path.exists():
                # Keep the original (absolute) path representation to avoid
                # Windows 8.3 short/long path mismatches in callers/tests.
                paths.append(path)

        # Update cache
        self._ref_paths_cache = (cache_key, paths)
        return paths

    def invalidate_reference_cache(self):
        """Invalidate the reference file paths cache."""
        self._ref_paths_cache = None

    def get_output_directory(self, input_path: Path) -> Path:
        """
        Get output directory for translated file.
        Returns input file's directory if output_directory is None.
        """
        if self.output_directory:
            return Path(self.output_directory)
        return input_path.parent


def get_default_settings_path() -> Path:
    """Get default settings file path"""
    return Path(__file__).parent.parent.parent / "config" / "settings.json"


def get_default_prompts_dir() -> Path:
    """Get default prompts directory"""
    return Path(__file__).parent.parent.parent / "prompts"


def invalidate_settings_cache(path: Optional[Path] = None) -> None:
    """Invalidate settings cache.

    Args:
        path: 特定のパスのキャッシュのみクリアする場合に指定。
              Noneの場合は全キャッシュをクリア。
    """
    with _settings_cache_lock:
        if path is None:
            _settings_cache.clear()
            logger.debug("Cleared all settings cache")
        else:
            cache_key = str(path.resolve())
            if cache_key in _settings_cache:
                del _settings_cache[cache_key]
                logger.debug("Cleared settings cache for: %s", path)
