## Task 31: Fix Edge taskbar icon flash during resident startup

### Problem
When YakuLingo starts in resident mode, Edge's taskbar icon briefly appears (100-300ms) before the taskbar suppression thread hides it. This visual flicker is distracting to users.

### Root Cause
In `yakulingo/services/copilot_handler.py`, the `_start_edge_process()` method creates the Edge subprocess with an empty `subprocess.STARTUPINFO()`. The `startupinfo` object has no `SW_HIDE` flag, so Edge's initial window is created in a visible state. The taskbar suppression thread (`_start_edge_taskbar_suppression`) applies `WS_EX_TOOLWINDOW` style to hide the taskbar icon, but there's a 100-300ms race condition between window creation and style application.

### Required Changes

All changes are in `yakulingo/services/copilot_handler.py`, in the `_start_edge_process()` method.

#### Change 1: Set SW_HIDE on STARTUPINFO (around line ~2098-2099)

Current code:
```python
startupinfo = None
creationflags = 0
if sys.platform == "win32":
    startupinfo = subprocess.STARTUPINFO()
```

Change to:
```python
startupinfo = None
creationflags = 0
if sys.platform == "win32":
    startupinfo = subprocess.STARTUPINFO()
    if display_mode == "minimized":
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0  # SW_HIDE
```

This tells Windows to create the Edge process with its initial window hidden. The `display_mode == "minimized"` guard ensures this only applies in resident mode (where the user doesn't want to see Edge).

#### Change 2: Add CREATE_NO_WINDOW to creationflags (same location)

After the startupinfo block, add:
```python
    if display_mode == "minimized":
        creationflags |= 0x08000000  # CREATE_NO_WINDOW
```

Note: `CREATE_NO_WINDOW` (0x08000000) prevents creation of a console window for the child process. It does NOT affect GUI window rendering (Edge is a GUI app, not a console app), so Edge's Chromium rendering will work normally. The Edge GUI window will still be created but won't appear on the taskbar because of `SW_HIDE`.

**IMPORTANT**: Do NOT use `subprocess.CREATE_NO_WINDOW` directly — it may not exist on all Python versions. Use the raw constant `0x08000000` instead.

### Full expected result for the startupinfo block:

```python
startupinfo = None
creationflags = 0
if sys.platform == "win32":
    startupinfo = subprocess.STARTUPINFO()
    if display_mode == "minimized":
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0  # SW_HIDE
        creationflags |= 0x08000000  # CREATE_NO_WINDOW
```

### Important constraints
- Do NOT modify any other methods or files
- Do NOT remove or change `_start_edge_taskbar_suppression()` — keep it as a safety net
- Do NOT change the `--start-minimized` or `--window-position=-32000,-32000` Edge flags — keep them as additional safety
- Do NOT change `display_mode == "minimized"` logic or the `edge_args` array
- Only apply `SW_HIDE` and `CREATE_NO_WINDOW` when `display_mode == "minimized"` (i.e., resident mode). In other display modes, Edge should start normally.
- Run `python3 -c "import py_compile; py_compile.compile('yakulingo/services/copilot_handler.py', doraise=True)"` to verify syntax
