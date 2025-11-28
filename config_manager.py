"""
Configuration Manager
Manages application settings including glossary (local file or SharePoint).
"""

import json
import csv
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Tuple


@dataclass
class GlossaryConfig:
    """Glossary configuration - uses local CSV file"""
    enabled: bool = False
    file: str = "glossary.csv"


@dataclass
class SystemTrayConfig:
    """System tray configuration"""
    minimize_to_tray: bool = True
    start_minimized: bool = False


@dataclass
class HotkeyConfig:
    """Hotkey configuration"""
    jp_to_en: str = "ctrl+shift+e"
    en_to_jp: str = "ctrl+shift+j"


@dataclass
class AppConfig:
    """Application configuration"""
    glossary: GlossaryConfig = field(default_factory=GlossaryConfig)
    system_tray: SystemTrayConfig = field(default_factory=SystemTrayConfig)
    hotkeys: HotkeyConfig = field(default_factory=HotkeyConfig)


class ConfigManager:
    """
    Manages application configuration.
    Loads from and saves to config.json.
    """

    def __init__(self, config_path: Optional[Path] = None):
        if config_path is None:
            config_path = Path(__file__).parent / "config.json"
        self.config_path = config_path
        self.config: AppConfig = self._load()

    def _load(self) -> AppConfig:
        """Load configuration from file"""
        if not self.config_path.exists():
            # Create default config
            config = AppConfig()
            self._save(config)
            return config

        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # Parse nested configs
            glossary = GlossaryConfig(**data.get('glossary', {}))
            system_tray = SystemTrayConfig(**data.get('system_tray', {}))
            hotkeys = HotkeyConfig(**data.get('hotkeys', {}))

            return AppConfig(
                glossary=glossary,
                system_tray=system_tray,
                hotkeys=hotkeys
            )

        except Exception as e:
            print(f"Warning: Failed to load config: {e}")
            return AppConfig()

    def _save(self, config: AppConfig = None):
        """Save configuration to file"""
        if config is None:
            config = self.config

        try:
            data = {
                'glossary': asdict(config.glossary),
                'system_tray': asdict(config.system_tray),
                'hotkeys': asdict(config.hotkeys),
            }

            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)

        except Exception as e:
            print(f"Warning: Failed to save config: {e}")

    def save(self):
        """Save current configuration"""
        self._save(self.config)

    def reload(self):
        """Reload configuration from file"""
        self.config = self._load()

    # Convenience properties
    @property
    def glossary_enabled(self) -> bool:
        return self.config.glossary.enabled

    @property
    def minimize_to_tray(self) -> bool:
        return self.config.system_tray.minimize_to_tray

    @property
    def start_minimized(self) -> bool:
        return self.config.system_tray.start_minimized

    def _load_glossary(self) -> List[Tuple[str, str]]:
        """Load glossary terms from CSV file"""
        terms = []
        glossary_path = Path(__file__).parent / self.config.glossary.file

        if not glossary_path.exists():
            return terms

        try:
            with open(glossary_path, 'r', encoding='utf-8') as f:
                reader = csv.reader(f)
                for row in reader:
                    # Skip empty lines and comments
                    if not row or row[0].startswith('#'):
                        continue
                    if len(row) >= 2:
                        source = row[0].strip()
                        target = row[1].strip()
                        if source and target:
                            terms.append((source, target))
        except Exception as e:
            print(f"Warning: Failed to load glossary: {e}")

        return terms

    def get_glossary_file_path(self) -> Optional[Path]:
        """
        Get the glossary file path if glossary is enabled and file exists.
        Returns None if glossary is not enabled or file doesn't exist.
        """
        if not self.glossary_enabled:
            return None

        glossary_path = Path(__file__).parent / self.config.glossary.file
        if not glossary_path.exists():
            return None

        # Check if file has any terms
        terms = self._load_glossary()
        if not terms:
            return None

        return glossary_path

    def get_glossary_prompt_addition(self) -> str:
        """
        Get the prompt addition for glossary reference.
        Returns instruction to use the attached glossary file.
        """
        if not self.glossary_enabled:
            return ""

        glossary_path = self.get_glossary_file_path()
        if not glossary_path:
            return ""

        return """

[IMPORTANT: Use the attached glossary.csv file for consistent terminology]
The glossary file contains source→target term mappings.
You MUST use these exact translations when the source term appears.
"""

    def set_glossary_file(self, file_path: Optional[str]):
        """
        Set the glossary file path and enable/disable glossary.
        Args:
            file_path: Absolute path to glossary file, or None to disable
        """
        if file_path is None:
            self.config.glossary.enabled = False
            self.config.glossary.file = "glossary.csv"
        else:
            # Store as relative path if in same directory, otherwise absolute
            file_path = Path(file_path)
            app_dir = Path(__file__).parent
            try:
                rel_path = file_path.relative_to(app_dir)
                self.config.glossary.file = str(rel_path)
            except ValueError:
                # File is outside app directory, store absolute path
                self.config.glossary.file = str(file_path)
            self.config.glossary.enabled = True
        self.save()

    def get_glossary_display_name(self) -> str:
        """Get display name for current glossary file"""
        if not self.glossary_enabled:
            return "Not set"
        return Path(self.config.glossary.file).name


# Global config instance
_config_manager: Optional[ConfigManager] = None


def get_config() -> ConfigManager:
    """Get the global config manager instance"""
    global _config_manager
    if _config_manager is None:
        _config_manager = ConfigManager()
    return _config_manager
