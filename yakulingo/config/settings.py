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

import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import json

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
}

# Minimum screen width (logical px) to keep side_panel layout.
# If the app window would be too narrow, fall back to minimized mode.
MIN_SIDE_PANEL_APP_WIDTH = 650
SIDE_PANEL_GAP = 10
MIN_SIDE_PANEL_SCREEN_WIDTH = MIN_SIDE_PANEL_APP_WIDTH * 2 + SIDE_PANEL_GAP


def resolve_browser_display_mode(requested_mode: str, screen_width: Optional[int]) -> str:
    """Resolve browser display mode based on available screen width."""
    if requested_mode != "side_panel":
        return requested_mode
    if screen_width is None:
        return requested_mode
    if screen_width < MIN_SIDE_PANEL_SCREEN_WIDTH:
        return "minimized"
    return requested_mode


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
    # NOTE: window_width/window_height は廃止。ウィンドウサイズは
    # _detect_display_settings() で論理解像度から動的に計算される。

    # Advanced
    max_chars_per_batch: int = 1000     # Max characters per batch (Copilot input safety)
    request_timeout: int = 600          # Seconds (10 minutes - allows for large translations)
    max_retries: int = 3

    # File Translation Options (共通オプション)
    bilingual_output: bool = False      # 対訳出力（原文と翻訳を交互に配置）
    export_glossary: bool = False       # 対訳CSV出力（glossaryとして再利用可能）
    translation_style: str = "concise"  # ファイル翻訳の英訳スタイル: "standard", "concise", "minimal"

    # Text Translation Options
    use_bundled_glossary: bool = True        # 同梱の glossary.csv を使用するか（デフォルトでオン）

    # Font Settings (ファイル翻訳用 - 全形式共通)
    # フォントサイズ調整（JP→EN時）: 0で調整なし、負値で縮小
    font_size_adjustment_jp_to_en: float = 0.0  # pt
    font_size_min: float = 8.0  # pt (最小フォントサイズ)

    # 出力フォント（言語方向のみで決定、元フォント種別は無視）
    font_jp_to_en: str = "Arial"           # 英訳時の出力フォント
    font_en_to_jp: str = "MS Pゴシック"    # 和訳時の出力フォント

    # PDF Layout Options (PP-DocLayout-L)
    ocr_batch_size: int = 5             # ページ/バッチ（メモリ使用量とのトレードオフ）
    ocr_dpi: int = 300                  # レイアウト解析解像度（高いほど精度向上、処理時間増加）
    ocr_device: str = "auto"            # "auto", "cpu", "cuda"

    # Browser Display Mode (翻訳時のEdgeブラウザ表示方法)
    # "side_panel": アプリの横にパネルとして表示（翻訳経過が見える、デフォルト）
    # "minimized": 最小化して非表示
    # "foreground": 前面に表示
    browser_display_mode: str = "side_panel"

    # Auto Update
    auto_update_enabled: bool = True            # 起動時に自動チェック
    auto_update_check_interval: int = 0         # チェック間隔（秒）: 0 = 起動毎
    github_repo_owner: str = "minimo162"        # GitHubリポジトリオーナー
    github_repo_name: str = "yakulingo"         # GitHubリポジトリ名
    last_update_check: Optional[str] = None     # 最後のチェック日時（ISO形式）

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
        template_mtime = template_path.stat().st_mtime if template_path.exists() else 0.0
        user_mtime = user_settings_path.stat().st_mtime if user_settings_path.exists() else 0.0

        # Check cache
        if use_cache:
            with _settings_cache_lock:
                if cache_key in _settings_cache:
                    cached_template_mtime, cached_user_mtime, cached_settings = _settings_cache[cache_key]
                    if cached_template_mtime == template_mtime and cached_user_mtime == user_mtime:
                        logger.debug("Using cached settings for: %s", path)
                        return cached_settings

        # Start with defaults
        data = {}

        # 1. Load from template (developer defaults)
        if template_path.exists():
            try:
                with open(template_path, 'r', encoding='utf-8-sig') as f:
                    data = json.load(f)
                    logger.debug("Loaded template settings from: %s", template_path)
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                logger.warning("Failed to load template settings: %s", e)

        # 2. Override with user settings
        if user_settings_path.exists():
            try:
                with open(user_settings_path, 'r', encoding='utf-8-sig') as f:
                    user_data = json.load(f)
                    # Only apply known user settings keys
                    for key in USER_SETTINGS_KEYS:
                        if key in user_data:
                            data[key] = user_data[key]
                    logger.debug("Loaded user settings from: %s", user_settings_path)
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                logger.warning("Failed to load user settings: %s", e)

        # NOTE: Legacy settings.json is NOT migrated to prevent bugs.
        # Users will start with fresh defaults from template.

        # Clean up deprecated fields
        data.pop('last_direction', None)
        data.pop('window_width', None)
        data.pop('window_height', None)
        data.pop('pdf_bilingual_output', None)
        data.pop('pdf_export_glossary', None)
        data.pop('font_jp_to_en_mincho', None)
        data.pop('font_jp_to_en_gothic', None)
        data.pop('font_en_to_jp_serif', None)
        data.pop('font_en_to_jp_sans', None)
        data.pop('pdf_font_ja', None)
        data.pop('pdf_font_en', None)

        # Filter to only known fields
        known_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered_data = {k: v for k, v in data.items() if k in known_fields}

        settings = cls(**filtered_data)
        settings._validate()

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
            logger.warning("font_size_min too small (%.1f), resetting to 8.0", self.font_size_min)
            self.font_size_min = 8.0
        elif self.font_size_min > 72.0:
            logger.warning("font_size_min too large (%.1f), resetting to 8.0", self.font_size_min)
            self.font_size_min = 8.0

        # Batch size constraints
        if self.max_chars_per_batch < 100:
            logger.warning("max_chars_per_batch too small (%d), resetting to 1000", self.max_chars_per_batch)
            self.max_chars_per_batch = 1000

        # Timeout constraints
        if self.request_timeout < 10:
            logger.warning("request_timeout too small (%d), resetting to 600", self.request_timeout)
            self.request_timeout = 600
        elif self.request_timeout > 1800:
            logger.warning("request_timeout too large (%d), resetting to 600", self.request_timeout)
            self.request_timeout = 600

        # OCR settings
        if self.ocr_batch_size < 1:
            self.ocr_batch_size = 5
        if self.ocr_dpi < 72 or self.ocr_dpi > 600:
            logger.warning("ocr_dpi out of range (%d), resetting to 300", self.ocr_dpi)
            self.ocr_dpi = 300

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

        with open(user_settings_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        logger.debug("Saved user settings to: %s", user_settings_path)

        # Update cache with new modification times
        cache_key = str(path.resolve())
        template_mtime = template_path.stat().st_mtime if template_path.exists() else 0.0
        user_mtime = user_settings_path.stat().st_mtime if user_settings_path.exists() else 0.0
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

        for ref_file in self.reference_files:
            path = Path(ref_file)
            if not path.is_absolute():
                path = base_dir / path

            # Resolve to absolute path and check for path traversal
            resolved_path = path.resolve()

            # Ensure the resolved path is within the base directory
            try:
                resolved_path.relative_to(base_dir_resolved)
            except ValueError:
                # Path is outside base directory - skip for security
                continue

            if resolved_path.exists():
                paths.append(resolved_path)

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
