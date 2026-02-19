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
    "ui_keepalive_enabled",
    "ui_keepalive_interval_sec",
    # 出力オプション（ファイル翻訳パネルで変更）
    "bilingual_output",
    # ブラウザ表示モード
    "browser_display_mode",
    # UI状態（自動保存）
    "last_tab",
}

# 互換性のために読み飛ばす（user_settings.json から除去する）旧キー。
_DEPRECATED_USER_SETTINGS_KEYS = {
    "translation_backend",
    "copilot_enabled",
}

# Local AI設定はテンプレ管理（ユーザー変更不可）
_LOCAL_AI_SETTINGS_PREFIX = "local_ai_"

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

    # Output (常に別ファイルとして _translated 付きで保存)
    output_directory: Optional[str] = None  # None = same as input

    # UI
    last_tab: str = "text"
    # Translation backend (deprecated; kept for backward compatibility).
    # NOTE: YakuLingo runs local-only; this value is always forced to "local".
    translation_backend: str = "local"
    # Copilot availability (deprecated; kept for backward compatibility).
    # NOTE: Copilot is removed; this value is always forced to False.
    copilot_enabled: bool = False
    # NOTE: window_width/window_height は廃止。ウィンドウサイズは
    # _detect_display_settings() で論理解像度から動的に計算される。

    # Advanced
    max_chars_per_batch: int = (
        DEFAULT_MAX_CHARS_PER_BATCH  # Max characters per batch (prompt safety)
    )
    request_timeout: int = 600  # Seconds (10 minutes - allows for large translations)
    max_retries: int = 3

    # Local AI (llama.cpp llama-server) - M1 minimal settings
    # NOTE: Host is forced to 127.0.0.1 for security (no external exposure).
    local_ai_model_path: str = (
        "local_ai/models/NVIDIA-Nemotron-Nano-9B-v2-Japanese-Q4_K_M.gguf"
    )
    local_ai_server_dir: str = "local_ai/llama_cpp"
    local_ai_host: str = "127.0.0.1"
    local_ai_port_base: int = 4891
    local_ai_port_max: int = 4900
    local_ai_ctx_size: int = 2048
    local_ai_threads: int = 0  # 0=auto
    local_ai_threads_batch: Optional[int] = 0  # None=unset, 0=auto
    local_ai_temperature: float = 0.7
    local_ai_top_p: Optional[float] = 0.95
    local_ai_top_k: Optional[int] = 64
    local_ai_min_p: Optional[float] = 0.01
    local_ai_repeat_penalty: Optional[float] = 1.05
    local_ai_max_tokens: Optional[int] = 1024
    # Reasoning (thinking) controls for Nemotron-class models.
    local_ai_reasoning_enabled: bool = True
    local_ai_reasoning_budget: Optional[int] = 64
    local_ai_batch_size: Optional[int] = 512
    local_ai_ubatch_size: Optional[int] = 128
    local_ai_device: str = "none"
    local_ai_n_gpu_layers: int | str = 0
    local_ai_flash_attn: str = "auto"
    local_ai_no_warmup: bool = True
    local_ai_mlock: bool = False
    local_ai_no_mmap: bool = False
    local_ai_vk_force_max_allocation_size: Optional[int] = None
    local_ai_vk_disable_f16: bool = False
    local_ai_cache_type_k: Optional[str] = "q8_0"
    local_ai_cache_type_v: Optional[str] = "q8_0"

    # Local AI 送信分割（入力テキスト長での上限）
    # - local_ai_max_chars_per_batch: 複数テキストをまとめて送る経路（主にテキスト翻訳/バッチ翻訳）で使用
    # - local_ai_max_chars_per_batch_file: ファイル翻訳（ローカルAIバッチ翻訳）の分割上限（未設定時は local_ai_max_chars_per_batch を使用）
    local_ai_max_chars_per_batch: int = 1000
    local_ai_max_chars_per_batch_file: int = 1000

    # File Translation Options (共通オプション)
    bilingual_output: bool = False  # 対訳出力（原文と翻訳を交互に配置）
    translation_style: str = "minimal"  # File translation style (SSOT: minimal; standard/concise/minimal are normalized to minimal)

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

    # Idle freeze mitigation: periodic lightweight UI heartbeat (best-effort).
    ui_keepalive_enabled: bool = True
    ui_keepalive_interval_sec: int = 60
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
                    removed_local_ai = False
                    removed_deprecated = False
                    if isinstance(user_data, dict):
                        local_ai_keys = [
                            key
                            for key in user_data.keys()
                            if key.startswith(_LOCAL_AI_SETTINGS_PREFIX)
                        ]
                        if local_ai_keys:
                            for key in local_ai_keys:
                                user_data.pop(key, None)
                            removed_local_ai = True
                        deprecated_keys = [
                            key
                            for key in _DEPRECATED_USER_SETTINGS_KEYS
                            if key in user_data
                        ]
                        if deprecated_keys:
                            for key in deprecated_keys:
                                user_data.pop(key, None)
                            removed_deprecated = True
                    else:
                        user_data = {}
                    # Only apply known user settings keys
                    for key in USER_SETTINGS_KEYS:
                        if key in user_data:
                            data[key] = user_data[key]
                    if "login_overlay_guard" in user_data:
                        data["login_overlay_guard"] = user_data["login_overlay_guard"]
                        guard_source = "user"
                    logger.debug("Loaded user settings from: %s", user_settings_path)
                if removed_local_ai or removed_deprecated:
                    try:
                        with open(user_settings_path, "w", encoding="utf-8") as f:
                            json.dump(user_data, f, indent=2, ensure_ascii=False)
                        user_mtime = user_settings_path.stat().st_mtime
                        logger.debug(
                            "Cleaned disallowed keys from user_settings.json: %s",
                            user_settings_path,
                        )
                    except OSError as e:
                        logger.warning(
                            "Failed to clean disallowed keys from user_settings.json: %s",
                            e,
                        )
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                logger.warning("Failed to load user settings: %s", e)

        # NOTE: Legacy settings.json is NOT migrated to prevent bugs.
        # Users will start with fresh defaults from template.

        # Local-only mode: enforce deprecated backend keys regardless of persisted settings.
        data["copilot_enabled"] = False
        data["translation_backend"] = "local"

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

        # Translation backend (deprecated): YakuLingo is local-only.
        backend_raw = self.translation_backend
        backend = str(backend_raw or "").strip().lower()
        if backend and backend != "local":
            logger.info(
                "translation_backend is deprecated (got %s); forcing 'local'",
                backend_raw,
            )
        self.translation_backend = "local"

        copilot_enabled_raw = self.copilot_enabled
        if copilot_enabled_raw is not False:
            logger.info(
                "copilot_enabled is deprecated (got %s); forcing False",
                copilot_enabled_raw,
            )
        self.copilot_enabled = False

        if not isinstance(self.ui_keepalive_enabled, bool):
            logger.warning(
                "ui_keepalive_enabled invalid (%s), resetting to True",
                type(self.ui_keepalive_enabled).__name__,
            )
            self.ui_keepalive_enabled = True

        try:
            interval = int(self.ui_keepalive_interval_sec)
        except (TypeError, ValueError):
            logger.warning(
                "ui_keepalive_interval_sec invalid (%s), resetting to 60",
                self.ui_keepalive_interval_sec,
            )
            interval = 60
        if interval < 10:
            logger.warning(
                "ui_keepalive_interval_sec too small (%d), resetting to 60", interval
            )
            interval = 60
        if interval > 3600:
            interval = 3600
        self.ui_keepalive_interval_sec = interval

        # Translation style (file translation)
        # SSOT is "minimal"; accept legacy values ("standard"/"concise") and normalize.
        style = str(self.translation_style or "").strip().lower()
        if style not in {"standard", "concise", "minimal"}:
            if style:
                logger.warning(
                    "translation_style invalid (%s), resetting to 'minimal'",
                    self.translation_style,
                )
        self.translation_style = "minimal"

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
        if self.local_ai_threads_batch is not None:
            if isinstance(self.local_ai_threads_batch, bool):
                logger.warning(
                    "local_ai_threads_batch invalid (bool), resetting to None"
                )
                self.local_ai_threads_batch = None
            else:
                try:
                    threads_batch = int(self.local_ai_threads_batch)
                except (TypeError, ValueError):
                    logger.warning(
                        "local_ai_threads_batch invalid (%s), resetting to None",
                        self.local_ai_threads_batch,
                    )
                    self.local_ai_threads_batch = None
                else:
                    if threads_batch < 0:
                        logger.warning(
                            "local_ai_threads_batch out of range (%d), resetting to None",
                            threads_batch,
                        )
                        self.local_ai_threads_batch = None
                    else:
                        self.local_ai_threads_batch = threads_batch
        if self.local_ai_max_tokens is not None and self.local_ai_max_tokens < 1:
            logger.warning(
                "local_ai_max_tokens must be positive (%d), resetting to None",
                self.local_ai_max_tokens,
            )
            self.local_ai_max_tokens = None
        if not isinstance(self.local_ai_reasoning_enabled, bool):
            logger.warning(
                "local_ai_reasoning_enabled invalid (%s), resetting to True",
                type(self.local_ai_reasoning_enabled).__name__,
            )
            self.local_ai_reasoning_enabled = True
        if self.local_ai_reasoning_budget is not None:
            if isinstance(self.local_ai_reasoning_budget, bool):
                logger.warning(
                    "local_ai_reasoning_budget invalid (bool), resetting to None"
                )
                self.local_ai_reasoning_budget = None
            else:
                try:
                    budget = int(self.local_ai_reasoning_budget)
                except (TypeError, ValueError):
                    logger.warning(
                        "local_ai_reasoning_budget invalid (%s), resetting to None",
                        self.local_ai_reasoning_budget,
                    )
                    self.local_ai_reasoning_budget = None
                else:
                    if budget < 0:
                        logger.warning(
                            "local_ai_reasoning_budget must be >= 0 (%d), resetting to None",
                            budget,
                        )
                        self.local_ai_reasoning_budget = None
                    else:
                        self.local_ai_reasoning_budget = budget

        if (
            self.local_ai_reasoning_enabled
            and self.local_ai_reasoning_budget is not None
            and self.local_ai_max_tokens is not None
            and self.local_ai_reasoning_budget >= self.local_ai_max_tokens
        ):
            adjusted_budget = max(0, self.local_ai_max_tokens - 1)
            logger.warning(
                "local_ai_reasoning_budget (%d) must be < local_ai_max_tokens (%d), resetting to %d",
                self.local_ai_reasoning_budget,
                self.local_ai_max_tokens,
                adjusted_budget,
            )
            self.local_ai_reasoning_budget = adjusted_budget

        # Local AI ctx size constraints (conservative)
        if self.local_ai_ctx_size < 512:
            logger.warning(
                "local_ai_ctx_size too small (%d), resetting to 2048",
                self.local_ai_ctx_size,
            )
            self.local_ai_ctx_size = 2048

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

        # Local AI GPU offload settings
        if not isinstance(self.local_ai_device, str):
            logger.warning(
                "local_ai_device invalid (%s), resetting to 'none'",
                type(self.local_ai_device).__name__,
            )
            self.local_ai_device = "none"
        else:
            device = self.local_ai_device.strip()
            if not device:
                logger.warning("local_ai_device empty, resetting to 'none'")
                self.local_ai_device = "none"
            elif device.lower() == "none":
                self.local_ai_device = "none"
            else:
                self.local_ai_device = device

        n_gpu_layers = self.local_ai_n_gpu_layers
        if n_gpu_layers is None:
            self.local_ai_n_gpu_layers = 0
        elif isinstance(n_gpu_layers, bool):
            logger.warning("local_ai_n_gpu_layers invalid (bool), resetting to 0")
            self.local_ai_n_gpu_layers = 0
        elif isinstance(n_gpu_layers, int):
            if n_gpu_layers < 0:
                logger.warning(
                    "local_ai_n_gpu_layers out of range (%d), resetting to 0",
                    n_gpu_layers,
                )
                self.local_ai_n_gpu_layers = 0
        elif isinstance(n_gpu_layers, str):
            text = n_gpu_layers.strip().lower()
            if not text:
                logger.warning("local_ai_n_gpu_layers empty, resetting to 0")
                self.local_ai_n_gpu_layers = 0
            elif text in ("auto", "all"):
                self.local_ai_n_gpu_layers = text
            else:
                try:
                    value = int(text)
                except ValueError:
                    logger.warning(
                        "local_ai_n_gpu_layers invalid (%s), resetting to 0",
                        n_gpu_layers,
                    )
                    self.local_ai_n_gpu_layers = 0
                else:
                    if value < 0:
                        logger.warning(
                            "local_ai_n_gpu_layers out of range (%d), resetting to 0",
                            value,
                        )
                        self.local_ai_n_gpu_layers = 0
                    else:
                        self.local_ai_n_gpu_layers = value
        else:
            logger.warning(
                "local_ai_n_gpu_layers invalid (%s), resetting to 0",
                type(n_gpu_layers).__name__,
            )
            self.local_ai_n_gpu_layers = 0

        raw_flash_attn = self.local_ai_flash_attn
        if raw_flash_attn is None:
            self.local_ai_flash_attn = "auto"
        elif isinstance(raw_flash_attn, bool):
            self.local_ai_flash_attn = "1" if raw_flash_attn else "0"
        elif isinstance(raw_flash_attn, int):
            if raw_flash_attn in (0, 1):
                self.local_ai_flash_attn = str(raw_flash_attn)
            else:
                logger.warning(
                    "local_ai_flash_attn out of range (%d), resetting to 'auto'",
                    raw_flash_attn,
                )
                self.local_ai_flash_attn = "auto"
        elif isinstance(raw_flash_attn, str):
            text = raw_flash_attn.strip().lower()
            if text in ("auto", "0", "1"):
                self.local_ai_flash_attn = text
            elif text in ("true", "yes", "on"):
                self.local_ai_flash_attn = "1"
            elif text in ("false", "no", "off"):
                self.local_ai_flash_attn = "0"
            else:
                logger.warning(
                    "local_ai_flash_attn invalid (%s), resetting to 'auto'",
                    raw_flash_attn,
                )
                self.local_ai_flash_attn = "auto"
        else:
            logger.warning(
                "local_ai_flash_attn invalid (%s), resetting to 'auto'",
                type(raw_flash_attn).__name__,
            )
            self.local_ai_flash_attn = "auto"

        if not isinstance(self.local_ai_no_warmup, bool):
            logger.warning(
                "local_ai_no_warmup invalid (%s), resetting to False",
                type(self.local_ai_no_warmup).__name__,
            )
            self.local_ai_no_warmup = False
        if not isinstance(self.local_ai_mlock, bool):
            logger.warning(
                "local_ai_mlock invalid (%s), resetting to False",
                type(self.local_ai_mlock).__name__,
            )
            self.local_ai_mlock = False
        if not isinstance(self.local_ai_no_mmap, bool):
            logger.warning(
                "local_ai_no_mmap invalid (%s), resetting to False",
                type(self.local_ai_no_mmap).__name__,
            )
            self.local_ai_no_mmap = False

        if self.local_ai_vk_force_max_allocation_size is not None:
            if isinstance(self.local_ai_vk_force_max_allocation_size, bool):
                logger.warning(
                    "local_ai_vk_force_max_allocation_size invalid (bool), resetting to None"
                )
                self.local_ai_vk_force_max_allocation_size = None
            else:
                try:
                    value = int(self.local_ai_vk_force_max_allocation_size)
                except (TypeError, ValueError):
                    logger.warning(
                        "local_ai_vk_force_max_allocation_size invalid (%s), resetting to None",
                        self.local_ai_vk_force_max_allocation_size,
                    )
                    self.local_ai_vk_force_max_allocation_size = None
                else:
                    if value <= 0:
                        logger.warning(
                            "local_ai_vk_force_max_allocation_size out of range (%d), resetting to None",
                            value,
                        )
                        self.local_ai_vk_force_max_allocation_size = None
                    else:
                        self.local_ai_vk_force_max_allocation_size = value

        if not isinstance(self.local_ai_vk_disable_f16, bool):
            logger.warning(
                "local_ai_vk_disable_f16 invalid (%s), resetting to False",
                type(self.local_ai_vk_disable_f16).__name__,
            )
            self.local_ai_vk_disable_f16 = False

        if self.local_ai_cache_type_k is not None:
            if isinstance(self.local_ai_cache_type_k, bool):
                logger.warning(
                    "local_ai_cache_type_k invalid (bool), resetting to None"
                )
                self.local_ai_cache_type_k = None
            elif isinstance(self.local_ai_cache_type_k, str):
                text = self.local_ai_cache_type_k.strip()
                if not text or text.lower() in ("none", "null"):
                    self.local_ai_cache_type_k = None
                else:
                    self.local_ai_cache_type_k = text
            else:
                logger.warning(
                    "local_ai_cache_type_k invalid (%s), resetting to None",
                    type(self.local_ai_cache_type_k).__name__,
                )
                self.local_ai_cache_type_k = None

        if self.local_ai_cache_type_v is not None:
            if isinstance(self.local_ai_cache_type_v, bool):
                logger.warning(
                    "local_ai_cache_type_v invalid (bool), resetting to None"
                )
                self.local_ai_cache_type_v = None
            elif isinstance(self.local_ai_cache_type_v, str):
                text = self.local_ai_cache_type_v.strip()
                if not text or text.lower() in ("none", "null"):
                    self.local_ai_cache_type_v = None
                else:
                    self.local_ai_cache_type_v = text
            else:
                logger.warning(
                    "local_ai_cache_type_v invalid (%s), resetting to None",
                    type(self.local_ai_cache_type_v).__name__,
                )
                self.local_ai_cache_type_v = None

        # Local AI batch size constraints
        if self.local_ai_max_chars_per_batch < 100:
            logger.warning(
                "local_ai_max_chars_per_batch too small (%d), resetting to 1000",
                self.local_ai_max_chars_per_batch,
            )
            self.local_ai_max_chars_per_batch = 1000
        if self.local_ai_max_chars_per_batch_file < 100:
            logger.warning(
                "local_ai_max_chars_per_batch_file too small (%d), resetting to 1000",
                self.local_ai_max_chars_per_batch_file,
            )
            self.local_ai_max_chars_per_batch_file = 1000

        # Local AI sampling params constraints
        if self.local_ai_temperature < 0.0 or self.local_ai_temperature > 2.0:
            logger.warning(
                "local_ai_temperature out of range (%.3f), resetting to 0.7",
                self.local_ai_temperature,
            )
            self.local_ai_temperature = 0.7

        if self.local_ai_top_p is not None:
            try:
                top_p = float(self.local_ai_top_p)
            except (TypeError, ValueError):
                logger.warning(
                    "local_ai_top_p invalid (%s), resetting to 0.95",
                    self.local_ai_top_p,
                )
                self.local_ai_top_p = 0.95
            else:
                if top_p < 0.0 or top_p > 1.0:
                    logger.warning(
                        "local_ai_top_p out of range (%.3f), resetting to 0.95",
                        top_p,
                    )
                    self.local_ai_top_p = 0.95
                else:
                    self.local_ai_top_p = top_p

        if self.local_ai_top_k is not None:
            try:
                top_k = int(self.local_ai_top_k)
            except (TypeError, ValueError):
                logger.warning(
                    "local_ai_top_k invalid (%s), resetting to 64", self.local_ai_top_k
                )
                self.local_ai_top_k = 64
            else:
                if top_k < 0:
                    logger.warning(
                        "local_ai_top_k out of range (%d), resetting to 64", top_k
                    )
                    self.local_ai_top_k = 64
                else:
                    self.local_ai_top_k = top_k

        if self.local_ai_min_p is not None:
            try:
                min_p = float(self.local_ai_min_p)
            except (TypeError, ValueError):
                logger.warning(
                    "local_ai_min_p invalid (%s), resetting to 0.01",
                    self.local_ai_min_p,
                )
                self.local_ai_min_p = 0.01
            else:
                if min_p < 0.0 or min_p > 1.0:
                    logger.warning(
                        "local_ai_min_p out of range (%.3f), resetting to 0.01", min_p
                    )
                    self.local_ai_min_p = 0.01
                else:
                    self.local_ai_min_p = min_p

        if self.local_ai_repeat_penalty is not None:
            try:
                repeat_penalty = float(self.local_ai_repeat_penalty)
            except (TypeError, ValueError):
                logger.warning(
                    "local_ai_repeat_penalty invalid (%s), resetting to 1.05",
                    self.local_ai_repeat_penalty,
                )
                self.local_ai_repeat_penalty = 1.05
            else:
                if repeat_penalty <= 0.0 or repeat_penalty > 2.0:
                    logger.warning(
                        "local_ai_repeat_penalty out of range (%.3f), resetting to 1.05",
                        repeat_penalty,
                    )
                    self.local_ai_repeat_penalty = 1.05
                else:
                    self.local_ai_repeat_penalty = repeat_penalty

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

        # Normalize legacy style values for persistence (SSOT: minimal).
        if "translation_style" in data:
            data["translation_style"] = "minimal"

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
