"""
Context Menu Installer
Adds "Translate" option to Windows right-click context menu.

Run as Administrator to install/uninstall.
"""

import sys
import os
import ctypes
from pathlib import Path

# Check if running as admin
def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False


def get_python_path():
    """Get the Python executable path"""
    return sys.executable


def get_script_path():
    """Get the translate.py script path"""
    return str(Path(__file__).parent / "translate.py")


def install_context_menu():
    """Install context menu entries"""
    import winreg

    python_path = get_python_path()
    script_path = get_script_path()

    # Command to run translation
    # We use a helper script that copies selected text and runs translation
    command_jp_to_en = f'"{python_path}" "{script_path}" --context-menu --jp-to-en'
    command_en_to_jp = f'"{python_path}" "{script_path}" --context-menu --en-to-jp'

    try:
        # Add to general context menu (*\shell)
        base_key_path = r"*\shell"

        # JP → EN menu item
        key_path_jp = f"{base_key_path}\\TranslateJPtoEN"
        with winreg.CreateKey(winreg.HKEY_CLASSES_ROOT, key_path_jp) as key:
            winreg.SetValue(key, "", winreg.REG_SZ, "Translate JP → EN")
            winreg.SetValueEx(key, "Icon", 0, winreg.REG_SZ, "shell32.dll,21")

        with winreg.CreateKey(winreg.HKEY_CLASSES_ROOT, f"{key_path_jp}\\command") as key:
            winreg.SetValue(key, "", winreg.REG_SZ, command_jp_to_en)

        # EN → JP menu item
        key_path_en = f"{base_key_path}\\TranslateENtoJP"
        with winreg.CreateKey(winreg.HKEY_CLASSES_ROOT, key_path_en) as key:
            winreg.SetValue(key, "", winreg.REG_SZ, "Translate EN → JP")
            winreg.SetValueEx(key, "Icon", 0, winreg.REG_SZ, "shell32.dll,21")

        with winreg.CreateKey(winreg.HKEY_CLASSES_ROOT, f"{key_path_en}\\command") as key:
            winreg.SetValue(key, "", winreg.REG_SZ, command_en_to_jp)

        print("✓ Context menu installed successfully!")
        print("  - 'Translate JP → EN' added")
        print("  - 'Translate EN → JP' added")
        print("\nRight-click on any file to see the new menu items.")
        return True

    except PermissionError:
        print("✗ Error: Administrator privileges required.")
        print("  Please run this script as Administrator.")
        return False
    except Exception as e:
        print(f"✗ Error installing context menu: {e}")
        return False


def uninstall_context_menu():
    """Remove context menu entries"""
    import winreg

    try:
        base_key_path = r"*\shell"

        # Remove JP → EN
        try:
            winreg.DeleteKey(winreg.HKEY_CLASSES_ROOT, f"{base_key_path}\\TranslateJPtoEN\\command")
            winreg.DeleteKey(winreg.HKEY_CLASSES_ROOT, f"{base_key_path}\\TranslateJPtoEN")
            print("✓ 'Translate JP → EN' removed")
        except FileNotFoundError:
            print("  'Translate JP → EN' was not installed")

        # Remove EN → JP
        try:
            winreg.DeleteKey(winreg.HKEY_CLASSES_ROOT, f"{base_key_path}\\TranslateENtoJP\\command")
            winreg.DeleteKey(winreg.HKEY_CLASSES_ROOT, f"{base_key_path}\\TranslateENtoJP")
            print("✓ 'Translate EN → JP' removed")
        except FileNotFoundError:
            print("  'Translate EN → JP' was not installed")

        print("\nContext menu entries removed.")
        return True

    except PermissionError:
        print("✗ Error: Administrator privileges required.")
        print("  Please run this script as Administrator.")
        return False
    except Exception as e:
        print(f"✗ Error uninstalling context menu: {e}")
        return False


def show_menu():
    """Show interactive menu"""
    print("=" * 50)
    print("Universal Translator - Context Menu Installer")
    print("=" * 50)
    print()

    if not is_admin():
        print("⚠ Warning: Not running as Administrator")
        print("  Some operations may fail.")
        print()

    print("Options:")
    print("  1. Install context menu")
    print("  2. Uninstall context menu")
    print("  3. Exit")
    print()

    choice = input("Enter your choice (1-3): ").strip()

    if choice == "1":
        print()
        install_context_menu()
    elif choice == "2":
        print()
        uninstall_context_menu()
    elif choice == "3":
        print("Goodbye!")
    else:
        print("Invalid choice.")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        if "--install" in sys.argv:
            install_context_menu()
        elif "--uninstall" in sys.argv:
            uninstall_context_menu()
        else:
            print("Usage: python install_context_menu.py [--install | --uninstall]")
    else:
        show_menu()

    input("\nPress Enter to exit...")
