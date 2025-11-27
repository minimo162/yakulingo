# Distribution Guide

## For Setup Administrator

### 1. Run Setup
```
Double-click setup.bat
```

### 2. Test
```
Double-click run.bat
```

### 3. Create ZIP for Distribution

**Include:**
- setup.bat
- run.bat
- translate.py
- pyproject.toml
- uv.toml
- .uv-cache/
- .uv-python/
- .playwright-browsers/

**Exclude:**
- .edge-profile/ (login credentials)
- .venv/
- uv.lock
- __pycache__/

---

## For End Users

1. Extract ZIP
2. Double-click run.bat
3. Login to M365 Copilot (first time only)
