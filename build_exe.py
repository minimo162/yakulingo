"""
Build executable for distribution.
Run: python build_exe.py
"""

import subprocess
import sys

def build():
    """Build executable using PyInstaller"""

    # PyInstaller command
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",                    # Single .exe file
        "--windowed",                   # No console window
        "--name", "ExcelTranslator",    # Output name
        "--icon", "icon.ico",           # Icon (if exists)
        "--add-data", "prompt.txt;.",   # Include prompt file
        # Hidden imports for pywin32
        "--hidden-import", "win32com",
        "--hidden-import", "win32com.client",
        "--hidden-import", "pythoncom",
        "--hidden-import", "pywintypes",
        # Hidden imports for customtkinter
        "--hidden-import", "customtkinter",
        # Exclude unnecessary modules
        "--exclude-module", "matplotlib",
        "--exclude-module", "numpy",
        "--exclude-module", "pandas",
        "--exclude-module", "scipy",
        # Main script
        "translate.py"
    ]

    print("Building executable...")
    print(f"Command: {' '.join(cmd)}")

    result = subprocess.run(cmd)

    if result.returncode == 0:
        print("\n" + "=" * 50)
        print("Build successful!")
        print("Output: dist/ExcelTranslator.exe")
        print("=" * 50)
    else:
        print("\nBuild failed!")
        sys.exit(1)


if __name__ == "__main__":
    build()
