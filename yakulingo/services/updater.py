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

        try:
            # インターネット設定からプロキシを取得
            key_path = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                # プロキシが有効かチェック
                try:
                    proxy_enable, _ = winreg.QueryValueEx(key, "ProxyEnable")
                    self.use_proxy = bool(proxy_enable)
                except FileNotFoundError:
                    self.use_proxy = False

                if self.use_proxy:
                    # プロキシサーバーを取得
                    try:
                        proxy_server, _ = winreg.QueryValueEx(key, "ProxyServer")
                        self.proxy_server = proxy_server
                    except FileNotFoundError:
                        pass

                    # バイパスリストを取得
                    try:
                        bypass, _ = winreg.QueryValueEx(key, "ProxyOverride")
                        self.proxy_bypass = [b.strip() for b in bypass.split(";")]
                    except FileNotFoundError:
                        pass
        except Exception as e:
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

        except Exception as e:
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
            # インストール済みかチェック（run.vbs の存在で判断）
            if (app_dir / "run.vbs").exists():
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

    def _make_request(self, url: str, headers: Optional[dict] = None) -> bytes:
        """HTTP GETリクエストを実行"""
        req = urllib.request.Request(url)
        req.add_header("User-Agent", f"YakuLingo/{self.current_version}")
        req.add_header("Accept", "application/vnd.github+json")

        if headers:
            for key, value in headers.items():
                req.add_header(key, value)

        try:
            with self.opener.open(req, timeout=30) as response:
                return response.read()
        except urllib.error.HTTPError as e:
            if e.code == 407:
                raise RuntimeError(
                    "プロキシ認証に失敗しました。\n"
                    "Windows認証プロキシを使用する場合は、pywin32をインストールしてください。"
                )
            raise

    def check_for_updates(self) -> UpdateResult:
        """
        GitHub Releasesで最新バージョンをチェック

        Returns:
            UpdateResult: アップデート確認結果
        """
        try:
            # GitHub API: 最新リリースを取得
            api_url = f"https://api.github.com/repos/{self.repo_owner}/{self.repo_name}/releases/latest"

            response_data = self._make_request(api_url)
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
        except Exception as e:
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
        except Exception:
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

        # 既にダウンロード済みの場合はスキップ
        if download_path.exists():
            return download_path

        # ダウンロード実行
        req = urllib.request.Request(version_info.download_url)
        req.add_header("User-Agent", f"YakuLingo/{self.current_version}")

        with self.opener.open(req, timeout=300) as response:
            total_size = int(response.headers.get("Content-Length", 0))
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
        "run.vbs",          # 起動スクリプト
        "README.md",        # ドキュメント
    ]
    # ユーザー設定ファイル（上書きしない、バックアップ対象）
    USER_FILES = ["glossary.csv", "config/settings.json"]

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

                # バックアップを作成
                backup_dir = self.cache_dir / "backup"
                if backup_dir.exists():
                    shutil.rmtree(backup_dir)

                # ユーザー設定ファイルをバックアップ
                for file_rel in self.USER_FILES:
                    src = app_dir / file_rel
                    if src.exists():
                        dst = backup_dir / file_rel
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(src, dst)

                # Windowsの場合、バッチファイルでアップデートを実行
                if platform.system() == "Windows":
                    return self._install_windows(source_dir, app_dir, backup_dir)
                else:
                    return self._install_unix(source_dir, app_dir, backup_dir)

        except Exception as e:
            logger.error("インストールに失敗: %s", e)
            return False

    def _install_windows(self, source_dir: Path, app_dir: Path, backup_dir: Path) -> bool:
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

REM ソースコードファイルをコピー
for %%f in ({files_to_update}) do (
    if exist "{source_dir}\\%%f" (
        echo   コピー: %%f
        copy /y "{source_dir}\\%%f" "{app_dir}\\%%f" >nul
    )
)

REM バックアップからユーザー設定を復元
echo ユーザー設定を復元しています...
if exist "{backup_dir}\\config\\settings.json" (
    if not exist "{app_dir}\\config" mkdir "{app_dir}\\config"
    copy /y "{backup_dir}\\config\\settings.json" "{app_dir}\\config\\settings.json" >nul
)
if exist "{backup_dir}\\glossary.csv" (
    copy /y "{backup_dir}\\glossary.csv" "{app_dir}\\glossary.csv" >nul
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
        subprocess.Popen(
            ["cmd", "/c", "start", "", str(batch_path)],
            creationflags=subprocess.CREATE_NEW_CONSOLE,
        )

        return True

    def _install_unix(self, source_dir: Path, app_dir: Path, backup_dir: Path) -> bool:
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

# ソースコードファイルをコピー
for file in {files_to_update}; do
    if [ -f "{source_dir}/$file" ]; then
        echo "  コピー: $file"
        cp "{source_dir}/$file" "{app_dir}/$file"
    fi
done

# バックアップからユーザー設定を復元
echo "ユーザー設定を復元しています..."
if [ -f "{backup_dir}/config/settings.json" ]; then
    mkdir -p "{app_dir}/config"
    cp "{backup_dir}/config/settings.json" "{app_dir}/config/settings.json"
fi
if [ -f "{backup_dir}/glossary.csv" ]; then
    cp "{backup_dir}/glossary.csv" "{app_dir}/glossary.csv"
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
        subprocess.Popen([str(script_path)])

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
