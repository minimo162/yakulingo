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
    """Glossary configuration"""
    enabled: bool = False
    mode: str = "local"  # "local" or "sharepoint"
    local_file: str = "glossary.csv"
    sharepoint_url: str = ""
    description: str = "mode: 'local' = use local CSV file, 'sharepoint' = use SharePoint URL (paid Copilot only)"


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
    def glossary_url(self) -> str:
        return self.config.glossary.sharepoint_url

    @property
    def minimize_to_tray(self) -> bool:
        return self.config.system_tray.minimize_to_tray

    @property
    def start_minimized(self) -> bool:
        return self.config.system_tray.start_minimized

    def _load_local_glossary(self) -> List[Tuple[str, str]]:
        """Load glossary terms from local CSV file"""
        terms = []
        glossary_path = Path(__file__).parent / self.config.glossary.local_file

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

    def get_glossary_prompt_addition(self) -> str:
        """
        Get the prompt addition for glossary reference.
        Returns empty string if glossary is not configured.
        """
        if not self.glossary_enabled:
            return ""

        # SharePoint mode
        if self.config.glossary.mode == "sharepoint" and self.glossary_url:
            return f"""

[IMPORTANT: Glossary Reference]
Please refer to the glossary file for consistent terminology:
{self.glossary_url}

Use the terms defined in this glossary whenever applicable.
If a term appears in the glossary, you MUST use the specified translation.
"""

        # Local file mode
        if self.config.glossary.mode == "local":
            terms = self._load_local_glossary()
            if not terms:
                return ""

            # Format terms as a table
            terms_table = "\n".join(f"  {src} → {tgt}" for src, tgt in terms)

            return f"""

[IMPORTANT: Use the following glossary for consistent terminology]
{terms_table}

You MUST use these exact translations when the source term appears.
"""

        return ""


# Global config instance
_config_manager: Optional[ConfigManager] = None


def get_config() -> ConfigManager:
    """Get the global config manager instance"""
    global _config_manager
    if _config_manager is None:
        _config_manager = ConfigManager()
    return _config_manager
