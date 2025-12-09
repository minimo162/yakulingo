# yakulingo/config/settings.py
"""
Application settings management for YakuLingo.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import json

# Module logger
logger = logging.getLogger(__name__)


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
    window_width: int = 1400  # 3カラムレイアウト対応
    window_height: int = 850

    # Advanced
    max_chars_per_batch: int = 7000     # Max characters per batch (fits in 8000 with template)
    request_timeout: int = 120          # Seconds
    max_retries: int = 3

    # File Translation Options (共通オプション)
    bilingual_output: bool = False      # 対訳出力（原文と翻訳を交互に配置）
    export_glossary: bool = False       # 対訳CSV出力（glossaryとして再利用可能）
    translation_style: str = "concise"  # ファイル翻訳の英訳スタイル: "standard", "concise", "minimal"

    # Text Translation Options
    text_translation_style: str = "concise"  # テキスト翻訳の英訳スタイル: "standard", "concise", "minimal"
    use_bundled_glossary: bool = True        # 同梱の glossary.csv を使用するか（デフォルトでオン）

    # Font Settings (ファイル翻訳用 - 全形式共通)
    # フォントサイズ調整（JP→EN時）: 0で調整なし、負値で縮小
    font_size_adjustment_jp_to_en: float = 0.0  # pt
    font_size_min: float = 6.0  # pt (最小フォントサイズ)

    # 出力フォント（言語方向のみで決定、元フォント種別は無視）
    font_jp_to_en: str = "Arial"           # 英訳時の出力フォント
    font_en_to_jp: str = "MS Pゴシック"    # 和訳時の出力フォント

    # PDF Layout Options (PP-DocLayout-L)
    ocr_batch_size: int = 5             # ページ/バッチ（メモリ使用量とのトレードオフ）
    ocr_dpi: int = 200                  # レイアウト解析解像度（高いほど精度向上、処理時間増加）
    ocr_device: str = "auto"            # "auto", "cpu", "cuda"

    # Auto Update
    auto_update_enabled: bool = True            # 起動時に自動チェック
    auto_update_check_interval: int = 86400     # チェック間隔（秒）: 24時間
    github_repo_owner: str = "minimo162"        # GitHubリポジトリオーナー
    github_repo_name: str = "yakulingo"         # GitHubリポジトリ名
    last_update_check: Optional[str] = None     # 最後のチェック日時（ISO形式）
    skipped_version: Optional[str] = None       # スキップしたバージョン

    @classmethod
    def load(cls, path: Path) -> "AppSettings":
        """Load settings from JSON file"""
        if path.exists():
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # Remove deprecated fields
                    data.pop('last_direction', None)
                    # Migrate old PDF-only options to common options
                    if 'pdf_bilingual_output' in data and 'bilingual_output' not in data:
                        data['bilingual_output'] = data.pop('pdf_bilingual_output')
                    else:
                        data.pop('pdf_bilingual_output', None)
                    if 'pdf_export_glossary' in data and 'export_glossary' not in data:
                        data['export_glossary'] = data.pop('pdf_export_glossary')
                    else:
                        data.pop('pdf_export_glossary', None)
                    # Migrate old font settings (4 settings → 2 settings)
                    if 'font_jp_to_en_mincho' in data and 'font_jp_to_en' not in data:
                        data['font_jp_to_en'] = data.pop('font_jp_to_en_mincho')
                    else:
                        data.pop('font_jp_to_en_mincho', None)
                    data.pop('font_jp_to_en_gothic', None)
                    if 'font_en_to_jp_serif' in data and 'font_en_to_jp' not in data:
                        data['font_en_to_jp'] = data.pop('font_en_to_jp_serif')
                    else:
                        data.pop('font_en_to_jp_serif', None)
                    data.pop('font_en_to_jp_sans', None)
                    # Remove old PDF font settings (now unified)
                    data.pop('pdf_font_ja', None)
                    data.pop('pdf_font_en', None)
                    # Filter to only known fields to handle future version settings
                    known_fields = {f.name for f in cls.__dataclass_fields__.values()}
                    filtered_data = {k: v for k, v in data.items() if k in known_fields}
                    settings = cls(**filtered_data)
                    settings._validate()
                    return settings
            except (json.JSONDecodeError, TypeError, UnicodeDecodeError) as e:
                logger.warning("Failed to load settings: %s", e)
                return cls()
        return cls()

    def _validate(self) -> None:
        """Validate and normalize setting values for consistency.

        Ensures values are within acceptable ranges and cross-validates
        related settings. Invalid values are reset to defaults with warnings.
        """
        # Font size constraints
        if self.font_size_min < 1.0:
            logger.warning("font_size_min too small (%.1f), resetting to 6.0", self.font_size_min)
            self.font_size_min = 6.0
        elif self.font_size_min > 72.0:
            logger.warning("font_size_min too large (%.1f), resetting to 6.0", self.font_size_min)
            self.font_size_min = 6.0

        # Batch size constraints
        if self.max_chars_per_batch < 100:
            logger.warning("max_chars_per_batch too small (%d), resetting to 7000", self.max_chars_per_batch)
            self.max_chars_per_batch = 7000

        # Timeout constraints
        if self.request_timeout < 10:
            logger.warning("request_timeout too small (%d), resetting to 120", self.request_timeout)
            self.request_timeout = 120
        elif self.request_timeout > 600:
            logger.warning("request_timeout too large (%d), resetting to 120", self.request_timeout)
            self.request_timeout = 120

        # OCR settings
        if self.ocr_batch_size < 1:
            self.ocr_batch_size = 5
        if self.ocr_dpi < 72 or self.ocr_dpi > 600:
            logger.warning("ocr_dpi out of range (%d), resetting to 200", self.ocr_dpi)
            self.ocr_dpi = 200

    def save(self, path: Path) -> None:
        """Save settings to JSON file"""
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "reference_files": self.reference_files,
            "output_directory": self.output_directory,
            "last_tab": self.last_tab,
            "window_width": self.window_width,
            "window_height": self.window_height,
            "max_chars_per_batch": self.max_chars_per_batch,
            "request_timeout": self.request_timeout,
            "max_retries": self.max_retries,
            # File Translation Options
            "bilingual_output": self.bilingual_output,
            "export_glossary": self.export_glossary,
            "translation_style": self.translation_style,
            # Text Translation Options
            "text_translation_style": self.text_translation_style,
            "use_bundled_glossary": self.use_bundled_glossary,
            # Font Settings
            "font_size_adjustment_jp_to_en": self.font_size_adjustment_jp_to_en,
            "font_size_min": self.font_size_min,
            "font_jp_to_en": self.font_jp_to_en,
            "font_en_to_jp": self.font_en_to_jp,
            # PDF Layout Options
            "ocr_batch_size": self.ocr_batch_size,
            "ocr_dpi": self.ocr_dpi,
            "ocr_device": self.ocr_device,
            # Auto Update
            "auto_update_enabled": self.auto_update_enabled,
            "auto_update_check_interval": self.auto_update_check_interval,
            "github_repo_owner": self.github_repo_owner,
            "github_repo_name": self.github_repo_name,
            "last_update_check": self.last_update_check,
            "skipped_version": self.skipped_version,
        }
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

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
