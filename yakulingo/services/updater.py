# yakulingo/services/updater.py
"""
自動アップデートサービス - GitHub Releases ベース

Windows認証プロキシに対応した自動アップデート機能を提供します。
"""

import logging
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional, Callable
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import zipfile
import time

# HTTP関連
import base64
import urllib.request
import urllib.error
import ssl
from urllib.parse import urlparse

# Module logger
logger = logging.getLogger(__name__)

# Windows固有のモジュール（条件付きインポート）
if platform.system() == "Windows":
    import winreg
    try:
        import sspi
        import sspicon
        import win32security
        HAS_PYWIN32 = True
    except ImportError:
        HAS_PYWIN32 = False
else:
    HAS_PYWIN32 = False


class UpdateStatus(Enum):
    """アップデート状態"""
    UP_TO_DATE = "up_to_date"
    UPDATE_AVAILABLE = "update_available"
    DOWNLOADING = "downloading"
    READY_TO_INSTALL = "ready_to_install"
    ERROR = "error"


@dataclass
class VersionInfo:
    """バージョン情報"""
    version: str
    release_date: str
    download_url: str
    release_notes: str
    file_size: int = 0
    requires_reinstall: bool = False  # 依存関係変更により再セットアップが必要


@dataclass
class UpdateResult:
    """アップデート結果"""
    status: UpdateStatus
    current_version: str
    latest_version: Optional[str] = None
    version_info: Optional[VersionInfo] = None
    message: str = ""
    error: Optional[str] = None


class ProxyConfig:
    """Windowsプロキシ設定の検出と管理"""

    def __init__(self):
        self.proxy_server: Optional[str] = None
        self.proxy_bypass: list[str] = []
        self.use_proxy: bool = False
        self._detect_proxy()

    def _detect_proxy(self) -> None:
        """Windowsレジストリからプロキシ設定を検出"""
        if platform.system() != "Windows":
            return

        # Check if winreg is available (not available on non-Windows)
        try:
            winreg_module = winreg
        except NameError:
            return

        try:
            # インターネット設定からプロキシを取得
            key_path = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
            with winreg_module.OpenKey(winreg_module.HKEY_CURRENT_USER, key_path) as key:
                # プロキシが有効かチェック
                try:
                    proxy_enable, _ = winreg_module.QueryValueEx(key, "ProxyEnable")
                    self.use_proxy = bool(proxy_enable)
                except FileNotFoundError:
                    self.use_proxy = False

                if self.use_proxy:
                    # プロキシサーバーを取得
                    try:
                        proxy_server, _ = winreg_module.QueryValueEx(key, "ProxyServer")
                        self.proxy_server = proxy_server
                    except FileNotFoundError:
                        pass

                    # バイパスリストを取得
                    try:
                        bypass, _ = winreg_module.QueryValueEx(key, "ProxyOverride")
                        self.proxy_bypass = [b.strip() for b in bypass.split(";")]
                    except FileNotFoundError:
                        pass
        except (OSError, ValueError, TypeError) as e:
            logger.warning("プロキシ設定の検出に失敗: %s", e)

    def get_proxy_dict(self) -> dict[str, str]:
        """urllib用のプロキシ辞書を返す"""
        if not self.use_proxy or not self.proxy_server:
            return {}

        # http://proxy:port または proxy:port 形式をサポート
        proxy = self.proxy_server
        if not proxy.startswith(("http://", "https://")):
            proxy = f"http://{proxy}"

        return {
            "http": proxy,
            "https": proxy,
        }

    def should_bypass(self, url: str) -> bool:
        """指定URLがプロキシバイパス対象かチェック"""
        parsed = urlparse(url)
        host = parsed.hostname or ""

        for bypass in self.proxy_bypass:
            if bypass == "<local>":
                if "." not in host:
                    return True
            elif bypass.startswith("*"):
                if host.endswith(bypass[1:]):
                    return True
            elif host == bypass:
                return True

        return False


class NTLMProxyHandler(urllib.request.BaseHandler):
    """
    Windows認証（NTLM/Negotiate）プロキシハンドラ

    pywin32がインストールされている場合はSSPIを使用し、
    現在のWindowsユーザーの認証情報で自動的にプロキシ認証を行います。
    """

    handler_order = 400  # ProxyHandler の後に処理

    def __init__(self, proxy_config: ProxyConfig):
        self.proxy_config = proxy_config
        self._auth_cache: dict[str, str] = {}

    def http_error_407(self, req, fp, code, msg, headers):
        """407 Proxy Authentication Required の処理"""
        if not HAS_PYWIN32:
            raise urllib.error.HTTPError(
                req.full_url, code,
                "プロキシ認証が必要ですが、pywin32がインストールされていません。\n"
                "pip install pywin32 を実行してください。",
                headers, fp
            )

        # Proxy-Authenticate ヘッダーを確認
        auth_header = headers.get("Proxy-Authenticate", "")

        if "NTLM" in auth_header or "Negotiate" in auth_header:
            return self._handle_ntlm_auth(req, headers)

        return None

    def _handle_ntlm_auth(self, req, headers):
        """NTLM/Negotiate認証を処理"""
        try:
            # SSPIコンテキストを作成
            scheme = "Negotiate" if "Negotiate" in headers.get("Proxy-Authenticate", "") else "NTLM"

            # クライアント認証コンテキストを初期化
            ctx = sspi.ClientAuth(scheme)

            # Type 1 メッセージ（NEGOTIATE）を生成
            _, out_buf = ctx.authorize(None)
            auth_token = base64.b64encode(out_buf[0].Buffer).decode('ascii')

            # 認証トークン付きでリクエストを再送
            new_req = urllib.request.Request(
                req.full_url,
                data=req.data,
                headers=dict(req.headers),
                method=req.get_method()
            )
            new_req.add_header("Proxy-Authorization", f"{scheme} {auth_token}")

            # プロキシ設定を取得
            proxy_dict = self.proxy_config.get_proxy_dict()
            if proxy_dict:
                proxy_handler = urllib.request.ProxyHandler(proxy_dict)
                opener = urllib.request.build_opener(proxy_handler)
                response = opener.open(new_req)

                # Type 2 メッセージ（CHALLENGE）を受信した場合
                if response.status == 407:
                    challenge = response.headers.get("Proxy-Authenticate", "")
                    if scheme in challenge:
                        # チャレンジを抽出
                        token_start = challenge.find(scheme) + len(scheme) + 1
                        challenge_token = challenge[token_start:].strip()

                        # Type 3 メッセージ（AUTHENTICATE）を生成
                        challenge_bytes = base64.b64decode(challenge_token)
                        _, out_buf = ctx.authorize(challenge_bytes)
                        auth_token = base64.b64encode(out_buf[0].Buffer).decode('ascii')

                        # 最終認証リクエスト
                        final_req = urllib.request.Request(
                            req.full_url,
                            data=req.data,
                            headers=dict(req.headers),
                            method=req.get_method()
                        )
                        final_req.add_header("Proxy-Authorization", f"{scheme} {auth_token}")
                        return opener.open(final_req)

                return response

        except (ValueError, RuntimeError, OSError) as e:
            logger.error("NTLM認証に失敗: %s", e)
            raise

        return None


class AutoUpdater:
    """
    自動アップデートサービス

    GitHub Releasesから最新バージョンをチェックし、
    必要に応じてダウンロード・インストールを行います。
    """

    # GitHubリポジトリ設定（ユーザーが設定可能）
    DEFAULT_REPO_OWNER = "minimo162"
    DEFAULT_REPO_NAME = "yakulingo"

    def __init__(
        self,
        repo_owner: Optional[str] = None,
        repo_name: Optional[str] = None,
        current_version: Optional[str] = None,
    ):
        self.repo_owner = repo_owner or self.DEFAULT_REPO_OWNER
        self.repo_name = repo_name or self.DEFAULT_REPO_NAME
        self.current_version = current_version or self._get_current_version()

        # プロキシ設定を検出
        self.proxy_config = ProxyConfig()

        # URLオープナーを構築
        self._build_opener()

        # ダウンロードキャッシュディレクトリ
        self.cache_dir = self._get_cache_dir()

    def _get_current_version(self) -> str:
        """現在のバージョンを取得"""
        try:
            from yakulingo import __version__
            return __version__
        except ImportError:
            return "0.0.0"

    def _get_cache_dir(self) -> Path:
        """キャッシュディレクトリを取得"""
        if platform.system() == "Windows":
            base = Path(os.environ.get("LOCALAPPDATA", Path.home()))
            return base / "YakuLingo" / "updates"
        else:
            return Path.home() / ".yakulingo" / "updates"

    def _get_app_dir(self) -> Path:
        """
        アプリケーションディレクトリを取得

        配布版は %LOCALAPPDATA%\\YakuLingo にインストールされる
        """
        if platform.system() == "Windows":
            app_dir = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "YakuLingo"
            # インストール済みかチェック（YakuLingo.exe の存在で判断）
            if (app_dir / "YakuLingo.exe").exists():
                return app_dir

        # フォールバック: 現在のスクリプトの場所から推測
        return Path(__file__).parent.parent.parent

    def _build_opener(self) -> None:
        """URLオープナーを構築"""
        handlers = []

        # プロキシハンドラを追加
        if self.proxy_config.use_proxy:
            proxy_dict = self.proxy_config.get_proxy_dict()
            handlers.append(urllib.request.ProxyHandler(proxy_dict))

            # NTLM認証ハンドラを追加
            if HAS_PYWIN32:
                handlers.append(NTLMProxyHandler(self.proxy_config))

        # HTTPSハンドラ（証明書検証）
        ssl_context = ssl.create_default_context()
        handlers.append(urllib.request.HTTPSHandler(context=ssl_context))

        self.opener = urllib.request.build_opener(*handlers)

    def _make_request(
        self, url: str, headers: Optional[dict] = None, return_headers: bool = False
    ):
        """HTTP GETリクエストを実行"""
        req = urllib.request.Request(url)
        req.add_header("User-Agent", f"YakuLingo/{self.current_version}")
        req.add_header("Accept", "application/vnd.github+json")

        if headers:
            for key, value in headers.items():
                req.add_header(key, value)

        try:
            with self.opener.open(req, timeout=30) as response:
                data = response.read()
                if return_headers:
                    return data, response.headers
                return data
        except urllib.error.HTTPError as e:
            if e.code == 407:
                raise RuntimeError(
                    "プロキシ認証に失敗しました。\n"
                    "Windows認証プロキシを使用する場合は、pywin32をインストールしてください。"
                )
            raise

    def _load_release_cache(self) -> Optional[dict]:
        """最新リリース情報のキャッシュを読み込む"""
        cache_file = self.cache_dir / "latest_release.json"
        if not cache_file.exists():
            return None

        try:
            payload = json.loads(cache_file.read_text(encoding="utf-8"))
            # 1時間を超えたキャッシュは無効化
            if time.time() - payload.get("timestamp", 0) > 3600:
                return None
            return payload
        except (OSError, json.JSONDecodeError, ValueError):
            return None

    def _save_release_cache(self, body: bytes, etag: Optional[str]) -> None:
        """最新リリース情報のキャッシュを保存"""
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = self.cache_dir / "latest_release.json"
        payload = {
            "timestamp": time.time(),
            "body": body.decode("utf-8", errors="ignore"),
        }
        if etag:
            payload["etag"] = etag

        try:
            cache_file.write_text(json.dumps(payload), encoding="utf-8")
        except OSError:
            logger.debug("Failed to write release cache", exc_info=True)

    def check_for_updates(self) -> UpdateResult:
        """
        GitHub Releasesで最新バージョンをチェック

        Returns:
            UpdateResult: アップデート確認結果
        """
        try:
            # GitHub API: 最新リリースを取得
            api_url = f"https://api.github.com/repos/{self.repo_owner}/{self.repo_name}/releases/latest"

            cached_release = self._load_release_cache()
            headers: dict[str, str] = {}
            if cached_release and cached_release.get("etag"):
                headers["If-None-Match"] = cached_release["etag"]

            try:
                response_data, response_headers = self._make_request(
                    api_url, headers=headers or None, return_headers=True
                )
                etag = response_headers.get("ETag")
                self._save_release_cache(response_data, etag)
            except urllib.error.HTTPError as e:
                if e.code == 304 and cached_release and "body" in cached_release:
                    response_data = cached_release["body"].encode("utf-8")
                else:
                    raise

            release_info = json.loads(response_data.decode("utf-8"))

            # バージョン情報を抽出
            latest_version = release_info.get("tag_name", "").lstrip("v")
            release_date = release_info.get("published_at", "")[:10]
            release_notes = release_info.get("body", "")

            # ダウンロードURLを探す（zipball または特定のアセット）
            download_url = ""
            file_size = 0

            # アセットからZIPファイルを探す
            assets = release_info.get("assets", [])
            for asset in assets:
                if asset.get("name", "").endswith(".zip"):
                    download_url = asset.get("browser_download_url", "")
                    file_size = asset.get("size", 0)
                    break

            # アセットがなければ zipball_url を使用
            if not download_url:
                download_url = release_info.get("zipball_url", "")

            # 依存関係変更の検出（リリースノートに [REQUIRES_REINSTALL] が含まれているか）
            requires_reinstall = "[REQUIRES_REINSTALL]" in release_notes

            version_info = VersionInfo(
                version=latest_version,
                release_date=release_date,
                download_url=download_url,
                release_notes=release_notes,
                file_size=file_size,
                requires_reinstall=requires_reinstall,
            )

            # バージョン比較
            if self._is_newer_version(latest_version, self.current_version):
                return UpdateResult(
                    status=UpdateStatus.UPDATE_AVAILABLE,
                    current_version=self.current_version,
                    latest_version=latest_version,
                    version_info=version_info,
                    message=f"新しいバージョン {latest_version} が利用可能です",
                )
            else:
                return UpdateResult(
                    status=UpdateStatus.UP_TO_DATE,
                    current_version=self.current_version,
                    latest_version=latest_version,
                    message="最新バージョンを使用しています",
                )

        except urllib.error.URLError as e:
            return UpdateResult(
                status=UpdateStatus.ERROR,
                current_version=self.current_version,
                error=f"ネットワークエラー: {e.reason}",
                message="アップデートの確認に失敗しました",
            )
        except (json.JSONDecodeError, ValueError, KeyError, OSError) as e:
            return UpdateResult(
                status=UpdateStatus.ERROR,
                current_version=self.current_version,
                error=str(e),
                message="アップデートの確認に失敗しました",
            )

    def _is_newer_version(self, latest: str, current: str) -> bool:
        """バージョン比較（セマンティックバージョニングまたは日付形式に対応）"""
        def parse_version(v: str) -> tuple:
            # "v" プレフィックスを削除
            v = v.lstrip("v")

            # 日付形式（YYYYMMDD）かチェック
            if len(v) == 8 and v.isdigit():
                return (int(v),)

            # セマンティックバージョニング形式（x.y.z）
            parts = []
            for part in v.split("."):
                try:
                    parts.append(int(part))
                except ValueError:
                    # プレリリースタグなど
                    parts.append(part)
            return tuple(parts)

        try:
            return parse_version(latest) > parse_version(current)
        except (TypeError, ValueError):
            # 比較できない場合は文字列比較
            return latest > current

    def download_update(
        self,
        version_info: VersionInfo,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> Path:
        """
        アップデートをダウンロード

        Args:
            version_info: ダウンロードするバージョン情報
            progress_callback: 進捗コールバック(downloaded_bytes, total_bytes)

        Returns:
            Path: ダウンロードしたファイルのパス
        """
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        download_path = self.cache_dir / f"yakulingo-{version_info.version}.zip"

        # 既にダウンロード済みの場合はスキップ（サイズ一致時のみ）
        if download_path.exists():
            if version_info.file_size and download_path.stat().st_size != version_info.file_size:
                download_path.unlink(missing_ok=True)
            else:
                return download_path

        # ダウンロード実行
        req = urllib.request.Request(version_info.download_url)
        req.add_header("User-Agent", f"YakuLingo/{self.current_version}")

        with self.opener.open(req, timeout=300) as response:
            total_size = int(response.headers.get("Content-Length", 0) or version_info.file_size or 0)
            downloaded = 0

            with open(download_path, "wb") as f:
                while True:
                    chunk = response.read(8192)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)

                    if progress_callback and total_size > 0:
                        progress_callback(downloaded, total_size)

        return download_path

    # 更新対象ファイル/ディレクトリ一覧
    # 環境ファイル（.venv, .uv-python, .playwright-browsers）は含まない
    # 配布ZIPに含まれるファイルと一致させる（make_distribution.bat 参照）
    SOURCE_DIRS = ["yakulingo", "prompts", "config"]
    SOURCE_FILES = [
        "app.py",           # エントリーポイント
        "pyproject.toml",   # プロジェクト設定
        "uv.lock",          # 依存関係ロックファイル
        "uv.toml",          # UV設定
        "YakuLingo.exe",    # 起動ランチャー
        "README.md",        # ドキュメント
        # Note: glossary.csv はユーザー編集可能なため、アップデートで上書きしない
    ]
    # Note: config/settings.json は config/ フォルダごと上書きされる

    def install_update(self, zip_path: Path) -> bool:
        """
        ダウンロードしたアップデートをインストール

        ソースコードのみを更新し、Python環境やPlaywrightブラウザはそのまま保持します。

        Args:
            zip_path: ダウンロードしたZIPファイルのパス

        Returns:
            bool: インストール成功かどうか
        """
        try:
            # アプリケーションディレクトリを取得
            app_dir = self._get_app_dir()

            # 一時ディレクトリに展開
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_path = Path(temp_dir)

                # ZIPを展開
                with zipfile.ZipFile(zip_path, 'r') as zf:
                    zf.extractall(temp_path)

                # 展開されたディレクトリを特定（GitHub zipball は1つのルートディレクトリを持つ）
                extracted_dirs = list(temp_path.iterdir())
                if len(extracted_dirs) == 1 and extracted_dirs[0].is_dir():
                    source_dir = extracted_dirs[0]
                else:
                    source_dir = temp_path

                # _internal フォルダがあればそれをソースとして使用（配布ZIP形式）
                internal_dir = source_dir / "_internal"
                if internal_dir.exists() and internal_dir.is_dir():
                    source_dir = internal_dir

                # Windowsの場合、バッチファイルでアップデートを実行
                if platform.system() == "Windows":
                    return self._install_windows(source_dir, app_dir)
                else:
                    return self._install_unix(source_dir, app_dir)

        except (OSError, zipfile.BadZipFile, shutil.Error, ValueError) as e:
            logger.error("インストールに失敗: %s", e)
            return False

    def _install_windows(self, source_dir: Path, app_dir: Path) -> bool:
        """Windowsでのインストール処理（ソースコードのみ更新）"""
        # アップデートバッチファイルを作成
        batch_path = self.cache_dir / "update.bat"

        # 更新対象のディレクトリとファイルをリスト化
        dirs_to_update = " ".join(self.SOURCE_DIRS)
        files_to_update = " ".join(self.SOURCE_FILES)

        batch_content = f'''@echo off
chcp 65001 >nul
echo.
echo ============================================================
echo YakuLingo アップデート中...
echo ============================================================
echo.

REM アプリケーションの終了を待機
echo アプリケーションの終了を待機しています...
timeout /t 3 /nobreak >nul

cd /d "{app_dir}"

REM ユーザーデータをバックアップ（設定ファイル）
set "SETTINGS_BACKUP=%TEMP%\\yakulingo_settings_backup.json"
if exist "config\\settings.json" (
    echo ユーザー設定をバックアップしています...
    copy /y "config\\settings.json" "%SETTINGS_BACKUP%" >nul
)

REM ソースコードディレクトリを削除（環境ファイルは残す）
echo ソースコードを更新しています...
for %%d in ({dirs_to_update}) do (
    if exist "%%d" (
        echo   削除: %%d
        rmdir /s /q "%%d"
    )
)

REM ソースコードディレクトリをコピー
for %%d in ({dirs_to_update}) do (
    if exist "{source_dir}\\%%d" (
        echo   コピー: %%d
        xcopy /e /y /i /q "{source_dir}\\%%d" "{app_dir}\\%%d\\" >nul
    )
)

REM ユーザー設定を復元してマージ
if exist "%SETTINGS_BACKUP%" (
    echo ユーザー設定を復元しています...
    copy /y "%SETTINGS_BACKUP%" "config\\settings.json" >nul
    del "%SETTINGS_BACKUP%" >nul 2>&1
)
REM 設定ファイルのマージ（新規項目のみ追加）
echo 設定を更新しています...
if exist "{app_dir}\\.venv\\Scripts\\python.exe" (
    "{app_dir}\\.venv\\Scripts\\python.exe" -c "from pathlib import Path; import sys; sys.path.insert(0, str(Path(r'{app_dir}'))); from yakulingo.services.updater import merge_settings; added = merge_settings(Path(r'{app_dir}'), Path(r'{source_dir}')); print(f'  追加: {{added}} 件の新規設定' if added > 0 else '  新規設定はありません' if added == 0 else '  設定ファイルを新規作成しました')"
)

REM ソースコードファイルをコピー
for %%f in ({files_to_update}) do (
    if exist "{source_dir}\\%%f" (
        echo   コピー: %%f
        copy /y "{source_dir}\\%%f" "{app_dir}\\%%f" >nul
    )
)

REM 用語集のマージ（新規用語のみ追加）
echo.
echo 用語集を更新しています...
if exist "{source_dir}\\glossary.csv" (
    if exist "{app_dir}\\.venv\\Scripts\\python.exe" (
        "{app_dir}\\.venv\\Scripts\\python.exe" -c "from pathlib import Path; import sys; sys.path.insert(0, str(Path(r'{app_dir}'))); from yakulingo.services.updater import merge_glossary; added = merge_glossary(Path(r'{app_dir}'), Path(r'{source_dir}')); print(f'  追加: {{added}} 件の新規用語' if added > 0 else '  新規用語はありません' if added == 0 else '  用語集を新規作成しました')"
    ) else (
        echo   [SKIP] Python環境が見つかりません
    )
)

echo.
echo ============================================================
echo アップデート完了！
echo ============================================================
echo.
echo アプリケーションを再起動してください。
echo.
pause

REM 自身を削除
del "%~f0"
'''

        with open(batch_path, "w", encoding="utf-8") as f:
            f.write(batch_content)

        # バッチファイルを実行（新しいウィンドウで）
        try:
            subprocess.Popen(
                ["cmd", "/c", "start", "", str(batch_path)],
                creationflags=subprocess.CREATE_NEW_CONSOLE,
            )
        except OSError as e:
            logger.error("Failed to launch update batch file: %s", e)
            return False

        return True

    def _install_unix(self, source_dir: Path, app_dir: Path) -> bool:
        """Unix系OSでのインストール処理（ソースコードのみ更新）"""
        # シェルスクリプトを作成
        script_path = self.cache_dir / "update.sh"

        # 更新対象のディレクトリとファイルをリスト化
        dirs_to_update = " ".join(self.SOURCE_DIRS)
        files_to_update = " ".join(self.SOURCE_FILES)

        script_content = f'''#!/bin/bash
echo ""
echo "============================================================"
echo "YakuLingo アップデート中..."
echo "============================================================"
echo ""

sleep 3

cd "{app_dir}"

# ユーザーデータをバックアップ（設定ファイル）
SETTINGS_BACKUP="/tmp/yakulingo_settings_backup.json"
if [ -f "config/settings.json" ]; then
    echo "ユーザー設定をバックアップしています..."
    cp "config/settings.json" "$SETTINGS_BACKUP"
fi

# ソースコードディレクトリを削除（環境ファイルは残す）
echo "ソースコードを更新しています..."
for dir in {dirs_to_update}; do
    if [ -d "$dir" ]; then
        echo "  削除: $dir"
        rm -rf "$dir"
    fi
done

# ソースコードディレクトリをコピー
for dir in {dirs_to_update}; do
    if [ -d "{source_dir}/$dir" ]; then
        echo "  コピー: $dir"
        cp -r "{source_dir}/$dir" "{app_dir}/$dir"
    fi
done

# ユーザー設定を復元してマージ
if [ -f "$SETTINGS_BACKUP" ]; then
    echo "ユーザー設定を復元しています..."
    cp "$SETTINGS_BACKUP" "config/settings.json"
    rm -f "$SETTINGS_BACKUP"
fi
# 設定ファイルのマージ（新規項目のみ追加）
echo "設定を更新しています..."
if [ -f "{app_dir}/.venv/bin/python" ]; then
    "{app_dir}/.venv/bin/python" -c "from pathlib import Path; import sys; sys.path.insert(0, str(Path(r'{app_dir}'))); from yakulingo.services.updater import merge_settings; added = merge_settings(Path(r'{app_dir}'), Path(r'{source_dir}')); print(f'  追加: {{added}} 件の新規設定' if added > 0 else '  新規設定はありません' if added == 0 else '  設定ファイルを新規作成しました')"
fi

# ソースコードファイルをコピー
for file in {files_to_update}; do
    if [ -f "{source_dir}/$file" ]; then
        echo "  コピー: $file"
        cp "{source_dir}/$file" "{app_dir}/$file"
    fi
done

# 用語集のマージ（新規用語のみ追加）
echo ""
echo "用語集を更新しています..."
if [ -f "{source_dir}/glossary.csv" ]; then
    if [ -f "{app_dir}/.venv/bin/python" ]; then
        "{app_dir}/.venv/bin/python" -c "from pathlib import Path; import sys; sys.path.insert(0, str(Path(r'{app_dir}'))); from yakulingo.services.updater import merge_glossary; added = merge_glossary(Path(r'{app_dir}'), Path(r'{source_dir}')); print(f'  追加: {{added}} 件の新規用語' if added > 0 else '  新規用語はありません' if added == 0 else '  用語集を新規作成しました')"
    else
        echo "  [SKIP] Python環境が見つかりません"
    fi
fi

echo ""
echo "============================================================"
echo "アップデート完了！"
echo "============================================================"
echo ""
echo "アプリケーションを再起動してください。"

# 自身を削除
rm "$0"
'''

        with open(script_path, "w") as f:
            f.write(script_content)

        os.chmod(script_path, 0o755)

        # スクリプトを実行
        try:
            subprocess.Popen([str(script_path)])
        except OSError as e:
            logger.error("Failed to launch update script: %s", e)
            return False

        return True

    def cleanup_cache(self) -> None:
        """キャッシュディレクトリをクリーンアップ"""
        if self.cache_dir.exists():
            shutil.rmtree(self.cache_dir, ignore_errors=True)


# 便利なユーティリティ関数
def check_for_updates(
    repo_owner: Optional[str] = None,
    repo_name: Optional[str] = None,
) -> UpdateResult:
    """
    アップデートをチェック（簡易関数）

    Args:
        repo_owner: GitHubリポジトリオーナー
        repo_name: GitHubリポジトリ名

    Returns:
        UpdateResult: アップデート確認結果
    """
    updater = AutoUpdater(repo_owner=repo_owner, repo_name=repo_name)
    return updater.check_for_updates()


# ユーザーがUIで明示的に変更した設定項目（アップデート時に保護される）
# これ以外の設定は開発者が自由に変更・削除可能
USER_PROTECTED_SETTINGS = {
    # 翻訳スタイル設定（設定ダイアログで変更）
    "translation_style",
    "text_translation_style",
    # フォント設定（設定ダイアログで変更）
    "font_jp_to_en",
    "font_en_to_jp",
    "font_size_adjustment_jp_to_en",
    # 出力オプション（ファイル翻訳パネルで変更）
    "bilingual_output",
    "export_glossary",
    "use_bundled_glossary",
    # UI状態（自動保存）
    "last_tab",
    "onboarding_completed",
    # 更新設定（更新ダイアログで変更）
    "skipped_version",
}


def merge_settings(app_dir: Path, source_dir: Path) -> int:
    """
    設定ファイルをマージ（ユーザー設定を保護しつつ新しい設定を適用）

    新しいバージョンの設定をベースとし、USER_PROTECTED_SETTINGS に含まれる
    ユーザーの設定のみを上書きします。これにより：
    - 開発者は新しい設定項目を追加できる
    - 開発者は不要な設定項目を削除できる
    - 開発者は技術的な設定のデフォルト値を変更できる
    - ユーザーの明示的な設定（UIで変更した項目）は保護される

    Args:
        app_dir: アプリケーションディレクトリ（ユーザーのsettings.jsonがある場所）
        source_dir: ソースディレクトリ（新しいsettings.jsonまたはテンプレートがある場所）

    Returns:
        int: 変更された設定項目数（正: 追加/変更, 負: 新規作成）
    """
    user_settings = app_dir / "config" / "settings.json"
    # 新しい設定ファイルまたはテンプレートを探す
    new_settings = source_dir / "config" / "settings.json"
    if not new_settings.exists():
        new_settings = source_dir / "config" / "settings.template.json"

    if not new_settings.exists():
        logger.info("新しい設定ファイルが見つかりません: %s", new_settings)
        return 0

    # ユーザーの設定が存在しない場合はコピー
    if not user_settings.exists():
        user_settings.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(new_settings, user_settings)
        logger.info("設定ファイルをコピーしました: %s", user_settings)
        return -1  # 新規作成を示す

    # 両方の設定を読み込む
    try:
        with open(user_settings, "r", encoding="utf-8") as f:
            user_data = json.load(f)
        with open(new_settings, "r", encoding="utf-8") as f:
            new_data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("設定ファイルの読み込みに失敗: %s", e)
        return 0

    # 新しい設定をベースとする（開発者の変更を反映）
    merged_data = dict(new_data)

    # ユーザー保護対象の設定のみを上書き
    preserved_count = 0
    for key in USER_PROTECTED_SETTINGS:
        if key in user_data:
            # ユーザーの設定値が新しい設定にも存在する場合のみ復元
            # （削除された設定は復元しない）
            if key in new_data:
                merged_data[key] = user_data[key]
                preserved_count += 1
                logger.debug("ユーザー設定を保持: %s", key)

    # 変更があれば保存
    with open(user_settings, "w", encoding="utf-8") as f:
        json.dump(merged_data, f, ensure_ascii=False, indent=2)

    # 追加された新規項目数をカウント
    added_keys = set(new_data.keys()) - set(user_data.keys())
    removed_keys = set(user_data.keys()) - set(new_data.keys())

    if added_keys:
        logger.info("新規設定項目: %s", ", ".join(added_keys))
    if removed_keys:
        logger.info("削除された設定項目: %s", ", ".join(removed_keys))
    if preserved_count > 0:
        logger.info("保持されたユーザー設定: %d 件", preserved_count)

    return len(added_keys)


def merge_glossary(app_dir: Path, source_dir: Path) -> int:
    """
    用語集をマージ（新規用語のみ追加）

    ユーザーの用語集（glossary.csv）に、バンドル版の新規用語を追加します。
    重複判定は「ソース用語,翻訳結果」のペア全体で行います。
    例: 「日本,Japan」が存在しても「日本,JPN」は別の用語として追加されます。

    Args:
        app_dir: アプリケーションディレクトリ（ユーザーのglossary.csvがある場所）
        source_dir: ソースディレクトリ（新しいglossary.csvがある場所）

    Returns:
        int: 追加された用語数
    """
    user_glossary = app_dir / "glossary.csv"
    new_glossary = source_dir / "glossary.csv"

    if not new_glossary.exists():
        logger.info("新しい用語集が見つかりません: %s", new_glossary)
        return 0

    # ユーザーの用語集が存在しない場合は新しい用語集をコピー
    if not user_glossary.exists():
        user_glossary.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(new_glossary, user_glossary)
        logger.info("用語集をコピーしました: %s", user_glossary)
        return -1  # 新規作成を示す

    # 既存の用語ペア（ソース,翻訳）を収集
    existing_pairs: set[str] = set()

    with open(user_glossary, "r", encoding="utf-8-sig") as f:
        for line in f:
            stripped = line.strip()
            # コメント行と空行はスキップ
            if stripped and not stripped.startswith("#"):
                # ペア全体（ソース,翻訳）をキーとして保存
                existing_pairs.add(stripped)

    # 新しい用語集から、既存にないペアを収集
    new_terms: list[str] = []
    with open(new_glossary, "r", encoding="utf-8-sig") as f:
        for line in f:
            stripped = line.strip()
            # コメント行と空行はスキップ
            if stripped and not stripped.startswith("#"):
                # ペア全体で重複判定
                if stripped not in existing_pairs:
                    new_terms.append(line if line.endswith("\n") else line + "\n")

    # 新規用語があれば追加
    # Note: 追記モードでは utf-8 を使用（utf-8-sig は追記時に余分な BOM を追加してしまう）
    if new_terms:
        with open(user_glossary, "a", encoding="utf-8") as f:
            f.writelines(new_terms)
        logger.info("用語集に %d 件の新規用語を追加しました", len(new_terms))

    return len(new_terms)


# コマンドライン実行用（アップデートスクリプトから呼び出される）
if __name__ == "__main__":
    import sys

    if len(sys.argv) >= 4 and sys.argv[1] == "merge":
        # python -m yakulingo.services.updater merge <app_dir> <source_dir>
        app_dir = Path(sys.argv[2])
        source_dir = Path(sys.argv[3])
        added = merge_glossary(app_dir, source_dir)
        if added > 0:
            print(f"  追加: {added} 件の新規用語")
        elif added == -1:
            print("  用語集を新規作成しました")
        else:
            print("  新規用語はありません")
    else:
        print("Usage: python -m yakulingo.services.updater merge <app_dir> <source_dir>")
        sys.exit(1)
