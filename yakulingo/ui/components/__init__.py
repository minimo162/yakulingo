# yakulingo/ui/components/__init__.py
"""
UI components for YakuLingo.

Heavy component imports are lazy-loaded for faster startup.
Use explicit imports like:
    from yakulingo.ui.components.text_panel import create_text_input_panel
"""

# Lazy-loaded components via __getattr__
_LAZY_IMPORTS = {
    "create_file_panel": "file_panel",
    "UpdateNotification": "update_notification",
    "check_updates_on_startup": "update_notification",
}


def __getattr__(name: str):
    """Lazy-load heavy component modules on first access."""
    if name in _LAZY_IMPORTS:
        module_name = _LAZY_IMPORTS[name]
        import importlib

        module = importlib.import_module(f".{module_name}", __package__)
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "create_file_panel",
    "UpdateNotification",
    "check_updates_on_startup",
]
