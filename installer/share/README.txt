============================================================
YakuLingo Distribution Guide (For Administrators)
============================================================

FOLDER STRUCTURE

Place these files in your shared folder:

  \\server\share\YakuLingo\
    setup.vbs              <-- Users run this (recommended, no console)
    setup.bat              <-- Alternative (shows console window)
    YakuLingo_YYYYMMDD.zip <-- Distribution package
    README.txt             <-- This file
    .scripts\              <-- Internal scripts (do not modify)

------------------------------------------------------------

USER INSTRUCTIONS

Share these steps with your users:

  1. Open \\server\share\YakuLingo
  2. Double-click "setup.vbs"
  3. Click "Yes" to confirm
  4. Done! Launch from desktop shortcut

Note: setup.vbs provides a GUI-only experience without showing
      a command prompt window.

------------------------------------------------------------

UPDATING THE PACKAGE

1. In the development environment:
   a. Run install_deps.bat first (if not already done)
   b. Run make_distribution.bat
2. Copy the new YakuLingo_YYYYMMDD.zip to the shared folder
3. Delete old ZIP files
   (setup.ps1 automatically uses the newest ZIP)

------------------------------------------------------------

REQUIREMENTS

- Windows 10/11
- PowerShell 5.1+ (included with Windows)
- Read access to shared folder

------------------------------------------------------------

TROUBLESHOOTING

Error: "Script execution is disabled"
  -> Always run setup.bat (not .scripts\setup.ps1 directly)
     The batch file handles execution policy

Error: "ZIP file not found"
  -> Ensure YakuLingo*.zip exists in the same folder

Error: "Access denied"
  -> Check user has read permission on the share

============================================================
