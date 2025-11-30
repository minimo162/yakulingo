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

    # Output (常に別ファイルとして _EN/_JP 付きで保存)
    output_directory: Optional[str] = None  # None = same as input

    # UI
    last_direction: str = "jp_to_en"
    last_tab: str = "text"
    window_width: int = 900
    window_height: int = 700

    # Advanced
    max_batch_size: int = 50            # Max texts per Copilot request
    request_timeout: int = 120          # Seconds
    max_retries: int = 3

    @classmethod
    def load(cls, path: Path) -> "AppSettings":
        """Load settings from JSON file"""
        if path.exists():
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
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
            "last_direction": self.last_direction,
            "last_tab": self.last_tab,
            "window_width": self.window_width,
            "window_height": self.window_height,
            "max_batch_size": self.max_batch_size,
            "request_timeout": self.request_timeout,
            "max_retries": self.max_retries,
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


def get_default_reference_dir() -> Path:
    """Get default reference files directory"""
    return Path(__file__).parent.parent.parent / "reference_files"
