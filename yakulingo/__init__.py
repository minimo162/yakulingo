# yakulingo/__init__.py
"""
YakuLingo - Text + File Translation Application

A Japanese-English translation application using NiceGUI and M365 Copilot.
"""

from pathlib import Path


def _get_version() -> str:
    """
    pyproject.tomlからバージョンを動的に取得する。

    アップデート時に__init__.pyが更新されなくても、pyproject.tomlが更新されていれば
    正しいバージョンが表示される。pyproject.tomlはSOURCE_FILESに含まれているため、
    確実に更新される。

    Returns:
        str: バージョン文字列（例: "0.0.2"）
    """
    try:
        import tomllib  # Python 3.11+ standard library

        pyproject_path = Path(__file__).parent.parent / "pyproject.toml"
        if pyproject_path.exists():
            with open(pyproject_path, "rb") as f:
                data = tomllib.load(f)
            return data.get("project", {}).get("version", "0.0.0")
    except Exception:
        pass

    # フォールバック: ハードコードされたバージョン
    return "0.0.2"


__version__ = _get_version()
__app_name__ = "YakuLingo"
