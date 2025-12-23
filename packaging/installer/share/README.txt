============================================================
YakuLingo Distribution Guide (For Administrators)
============================================================

FOLDER STRUCTURE

Place the following in the shared folder:

  \\server\share\YakuLingo\
    setup.vbs              <-- Run this file
    YakuLingo_YYYYMMDD.zip <-- Distribution package
    README.txt             <-- This file
    .scripts\              <-- Internal scripts (do not modify)

------------------------------------------------------------

USER INSTRUCTIONS

Share these steps with your users:

  1. Open \\server\share\YakuLingo
  2. Double-click "setup.vbs"
  3. Wait for setup to complete
  4. Launch YakuLingo from the desktop shortcut
  Note: YakuLingo installs to %LOCALAPPDATA%\YakuLingo (not OneDrive-synced).

------------------------------------------------------------

UPDATING THE PACKAGE

1. In the development environment:
   a. If needed, run install_deps.bat
   b. Run make_distribution.bat
2. Copy the new YakuLingo_YYYYMMDD.zip to the shared folder
3. Delete older ZIP files
   (setup.ps1 automatically picks the newest ZIP)

------------------------------------------------------------

REQUIREMENTS

- Windows 10/11
- PowerShell 5.1+ (included with Windows)
- Read access to the shared folder

------------------------------------------------------------

TROUBLESHOOTING

Error: "Script execution is disabled"
  -> Always run setup.vbs (do not run .scripts\setup.ps1 directly)
     The VBS file sets the correct execution policy

Error: "ZIP file not found"
  -> Make sure a YakuLingo*.zip exists in the same folder

Error: "Access denied"
  -> Confirm the user has read permission on the share

============================================================
