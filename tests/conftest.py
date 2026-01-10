from __future__ import annotations

import sys
from pathlib import Path


# `uv run --extra test pytest` では `sys.path[0]` がリポジトリルートにならない場合があるため、
# `yakulingo` を確実に import できるようにプロジェクトルートを追加する。
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
