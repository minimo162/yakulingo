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
    reference_files: list[str] = field(default_factory=lambda: ["glossary.csv"])

    # Output (常に別ファイルとして _translated 付きで保存)
    output_directory: Optional[str] = None  # None = same as input

    # UI
    last_tab: str = "text"
    window_width: int = 960
    window_height: int = 720

    # Advanced
    max_batch_size: int = 50            # Max texts per Copilot request
    max_chars_per_batch: int = 7000     # Max characters per batch (fits in 8000 with template)
    request_timeout: int = 120          # Seconds
    max_retries: int = 3

    # Copilot License
    # Free: 8000 chars, Paid: 128000 chars
    # Default to free (7500 with margin) for safety
    copilot_char_limit: int = 7500      # Max prompt chars before switching to file attachment

    # File Translation Options (共通オプション)
    bilingual_output: bool = False      # 対訳出力（原文と翻訳を交互に配置）
    export_glossary: bool = False       # 対訳CSV出力（glossaryとして再利用可能）

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
                    # Filter to only known fields to handle future version settings
                    known_fields = {f.name for f in cls.__dataclass_fields__.values()}
                    filtered_data = {k: v for k, v in data.items() if k in known_fields}
                    return cls(**filtered_data)
            except (json.JSONDecodeError, TypeError, UnicodeDecodeError) as e:
                logger.warning("Failed to load settings: %s", e)
                return cls()
        return cls()

    def save(self, path: Path) -> None:
        """Save settings to JSON file"""
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "reference_files": self.reference_files,
            "output_directory": self.output_directory,
            "last_tab": self.last_tab,
            "window_width": self.window_width,
            "window_height": self.window_height,
            "max_batch_size": self.max_batch_size,
            "max_chars_per_batch": self.max_chars_per_batch,
            "request_timeout": self.request_timeout,
            "max_retries": self.max_retries,
            "copilot_char_limit": self.copilot_char_limit,
            # File Translation Options
            "bilingual_output": self.bilingual_output,
            "export_glossary": self.export_glossary,
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
        """
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
        return paths

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
