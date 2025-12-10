#!/usr/bin/env python3
"""
アップデート用ZIPファイル作成スクリプト

GitHub Releasesにアップロードするための軽量なZIPファイルを作成します。
Python環境は含まず、ソースコードと設定ファイルのみを含みます。

使用方法:
    python packaging/make_update_zip.py [--output OUTPUT_PATH]

出力:
    yakulingo-{version}.zip
"""

import argparse
import zipfile
from pathlib import Path
import sys

# プロジェクトルートを取得
PROJECT_ROOT = Path(__file__).parent.parent

# updater.py と同じ定義（同期を保つこと）
SOURCE_DIRS = ["yakulingo", "prompts", "config"]
SOURCE_FILES = [
    "app.py",
    "pyproject.toml",
    "uv.lock",
    "uv.toml",
    "YakuLingo.exe",
    "README.md",
    "glossary.csv",  # マージ処理用に含める
]

# 除外パターン
EXCLUDE_PATTERNS = [
    "__pycache__",
    "*.pyc",
    "*.pyo",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "*.egg-info",
    ".git",
    ".DS_Store",
    "Thumbs.db",
]


def should_exclude(path: Path) -> bool:
    """ファイル/ディレクトリを除外すべきか判定"""
    name = path.name

    for pattern in EXCLUDE_PATTERNS:
        if pattern.startswith("*"):
            if name.endswith(pattern[1:]):
                return True
        elif name == pattern:
            return True

    return False


def get_version() -> str:
    """pyproject.tomlからバージョンを取得"""
    pyproject = PROJECT_ROOT / "pyproject.toml"

    if pyproject.exists():
        content = pyproject.read_text(encoding="utf-8")
        for line in content.splitlines():
            if line.strip().startswith("version"):
                # version = "20251127" の形式をパース
                parts = line.split("=", 1)
                if len(parts) == 2:
                    version = parts[1].strip().strip('"').strip("'")
                    return version

    return "unknown"


def create_update_zip(output_path: Path | None = None) -> Path:
    """アップデート用ZIPを作成"""
    version = get_version()

    if output_path is None:
        output_path = PROJECT_ROOT / "dist" / f"yakulingo-{version}.zip"

    output_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"アップデートZIP作成中: {output_path}")
    print(f"バージョン: {version}")
    print()

    file_count = 0
    total_size = 0

    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # ディレクトリを追加
        for dir_name in SOURCE_DIRS:
            dir_path = PROJECT_ROOT / dir_name
            if not dir_path.exists():
                print(f"  [SKIP] ディレクトリが見つかりません: {dir_name}")
                continue

            print(f"  追加中: {dir_name}/")

            for file_path in dir_path.rglob("*"):
                if file_path.is_file() and not should_exclude(file_path):
                    # 親ディレクトリが除外対象でないかチェック
                    if any(should_exclude(p) for p in file_path.parents):
                        continue

                    arcname = file_path.relative_to(PROJECT_ROOT)
                    zf.write(file_path, arcname)
                    file_count += 1
                    total_size += file_path.stat().st_size

        # 個別ファイルを追加
        for file_name in SOURCE_FILES:
            file_path = PROJECT_ROOT / file_name
            if not file_path.exists():
                print(f"  [SKIP] ファイルが見つかりません: {file_name}")
                continue

            print(f"  追加中: {file_name}")
            zf.write(file_path, file_name)
            file_count += 1
            total_size += file_path.stat().st_size

    zip_size = output_path.stat().st_size
    compression_ratio = (1 - zip_size / total_size) * 100 if total_size > 0 else 0

    print()
    print("=" * 60)
    print(f"完了!")
    print(f"  ファイル数: {file_count}")
    print(f"  元サイズ: {total_size / 1024 / 1024:.2f} MB")
    print(f"  ZIPサイズ: {zip_size / 1024 / 1024:.2f} MB ({compression_ratio:.1f}% 圧縮)")
    print(f"  出力先: {output_path}")
    print("=" * 60)

    return output_path


def main():
    parser = argparse.ArgumentParser(
        description="アップデート用ZIPファイルを作成します"
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        help="出力ファイルパス（デフォルト: dist/yakulingo-{version}.zip）"
    )

    args = parser.parse_args()

    try:
        create_update_zip(args.output)
    except (OSError, zipfile.BadZipFile) as e:
        print(f"エラー: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
