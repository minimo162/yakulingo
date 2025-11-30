# ecm_translate/config/settings.py
"""
Application settings management for YakuLingo.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import json


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
    request_timeout: int = 120          # Seconds
    max_retries: int = 3

    # Auto Update
    auto_update_enabled: bool = True            # 起動時に自動チェック
    auto_update_check_interval: int = 86400     # チェック間隔（秒）: 24時間
    github_repo_owner: str = "minimo162"        # GitHubリポジトリオーナー
    github_repo_name: str = "ECM_translate"     # GitHubリポジトリ名
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
                    # Convert reference_files paths if needed
                    return cls(**data)
            except (json.JSONDecodeError, TypeError) as e:
                print(f"Warning: Failed to load settings: {e}")
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
            "request_timeout": self.request_timeout,
            "max_retries": self.max_retries,
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
        Returns only existing files.
        """
        paths = []
        for ref_file in self.reference_files:
            path = Path(ref_file)
            if not path.is_absolute():
                path = base_dir / path
            if path.exists():
                paths.append(path)
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
