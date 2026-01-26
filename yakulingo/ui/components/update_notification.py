# yakulingo/ui/components/update_notification.py
"""
自動アップデート通知コンポーネント
"""

import asyncio
from datetime import datetime
from typing import Optional

from nicegui import ui, Client

from yakulingo.services.updater import (
    AutoUpdater,
    UpdateStatus,
    UpdateResult,
    VersionInfo,
)
from yakulingo.config.settings import AppSettings


class UpdateNotification:
    """アップデート通知を管理するコンポーネント"""

    def __init__(self, settings: AppSettings, client: Optional[Client] = None):
        self.settings = settings
        self.updater: Optional[AutoUpdater] = None
        self.update_result: Optional[UpdateResult] = None
        self._notification_banner: Optional[ui.element] = None
        self._dialog: Optional[ui.dialog] = None
        self._client: Optional[Client] = client

    def set_client(self, client: Client):
        """クライアント参照を設定"""
        self._client = client

    def should_check_updates(self) -> bool:
        """アップデートチェックを実行すべきかどうか"""
        if not self.settings.auto_update_enabled:
            return False

        # 最後のチェックからの経過時間を確認
        if self.settings.last_update_check:
            try:
                last_check = datetime.fromisoformat(self.settings.last_update_check)
                elapsed = (datetime.now() - last_check).total_seconds()
                if elapsed < self.settings.auto_update_check_interval:
                    return False
            except ValueError:
                pass

        return True

    async def check_for_updates(self, silent: bool = True) -> Optional[UpdateResult]:
        """
        アップデートを非同期でチェック

        Args:
            silent: True の場合、エラー時に通知を表示しない
        """
        try:
            self.updater = AutoUpdater(
                repo_owner=self.settings.github_repo_owner,
                repo_name=self.settings.github_repo_name,
            )

            # バックグラウンドでチェック
            result = await asyncio.to_thread(self.updater.check_for_updates)
            self.update_result = result

            # チェック日時を更新
            self.settings.last_update_check = datetime.now().isoformat()

            return result

        except (OSError, ValueError, RuntimeError) as e:
            if not silent:
                ui.notify(f"アップデートチェックに失敗: {e}", type="warning")
            return None

    def create_update_banner(self) -> Optional[ui.element]:
        """アップデート通知バナーを作成"""
        if (
            not self.update_result
            or self.update_result.status != UpdateStatus.UPDATE_AVAILABLE
        ):
            return None

        info = self.update_result.version_info
        requires_reinstall = info.requires_reinstall if info else False

        # 再セットアップ必要時は警告色のバナー
        banner_classes = (
            "update-banner fixed top-0 left-0 right-0 z-50 "
            "px-4 py-2 flex items-center justify-center gap-4 "
        )
        if requires_reinstall:
            banner_classes += "warning-banner"  # M3 warning colors
        else:
            banner_classes += "primary-banner"  # M3 primary colors

        with ui.element("div").classes(banner_classes) as banner:
            self._notification_banner = banner

            if requires_reinstall:
                ui.icon("warning").classes("text-lg")
                ui.label(
                    f"バージョン {self.update_result.latest_version} は再セットアップが必要です"
                ).classes("text-sm")
            else:
                ui.icon("system_update").classes("text-lg")
                ui.label(
                    f"新しいバージョン {self.update_result.latest_version} が利用可能です"
                ).classes("text-sm")

            with ui.row().classes("gap-2"):
                ui.button(
                    "詳細",
                    on_click=lambda: self.show_update_dialog(),
                ).props("flat dense color=white").classes("text-xs")

                ui.button(
                    "後で",
                    on_click=lambda: self._dismiss_banner(),
                ).props("flat dense color=white").classes("text-xs opacity-70")

        return banner

    def _dismiss_banner(self):
        """バナーを閉じる"""
        if self._notification_banner:
            self._notification_banner.delete()
            self._notification_banner = None

    def show_update_dialog(self):
        """アップデート詳細ダイアログを表示"""
        if not self.update_result or not self.update_result.version_info:
            return

        info = self.update_result.version_info

        with ui.dialog() as dialog, ui.card().classes("w-96 max-h-[80vh]"):
            self._dialog = dialog

            # ヘッダー
            with ui.row().classes("w-full items-center justify-between mb-4"):
                with ui.row().classes("items-center gap-2"):
                    ui.icon("system_update").classes("text-2xl text-primary")
                    ui.label("アップデート").classes("text-lg font-semibold")
                ui.button(
                    icon="close",
                    on_click=dialog.close,
                ).props("flat round").classes("icon-btn")

            # 再セットアップ必要警告
            if info.requires_reinstall:
                with ui.element("div").classes("w-full warning-box mb-3"):
                    with ui.row().classes("items-start gap-2"):
                        ui.icon("warning").classes("text-warning text-lg")
                        with ui.column().classes("gap-1"):
                            ui.label("再セットアップが必要").classes(
                                "text-sm font-semibold text-on-warning-container"
                            )
                            ui.label(
                                "このバージョンは依存関係が変更されています。"
                                "共有フォルダの setup.vbs を実行してください。"
                            ).classes("text-xs text-on-warning-container")

            # バージョン情報
            with ui.column().classes("w-full gap-3"):
                with ui.row().classes("w-full justify-between items-center"):
                    ui.label("現在のバージョン").classes("text-sm text-muted")
                    ui.label(self.update_result.current_version).classes(
                        "text-sm font-medium"
                    )

                with ui.row().classes("w-full justify-between items-center"):
                    ui.label("新しいバージョン").classes("text-sm text-muted")
                    ui.label(info.version).classes("text-sm font-semibold text-primary")

                if info.release_date:
                    with ui.row().classes("w-full justify-between items-center"):
                        ui.label("リリース日").classes("text-sm text-muted")
                        ui.label(info.release_date).classes("text-sm")

            # リリースノート
            if info.release_notes:
                ui.separator().classes("my-3")
                ui.label("変更内容").classes("text-sm font-medium mb-2")
                with ui.scroll_area().classes("w-full max-h-40 border rounded p-2"):
                    # リリースノートから [REQUIRES_REINSTALL] マーカーを除去して表示
                    display_notes = info.release_notes.replace(
                        "[REQUIRES_REINSTALL]", ""
                    ).strip()
                    # Markdownのソフト改行をハード改行に変換（行末に2スペース追加）
                    # これによりGitHubリリースノートの改行が正しく表示される
                    display_notes = display_notes.replace("\n", "  \n")
                    ui.markdown(display_notes).classes("release-notes-content")

            # アクションボタン
            ui.separator().classes("my-3")

            if info.requires_reinstall:
                # 再セットアップ必要な場合は、setup.vbs実行を案内
                with ui.column().classes("w-full gap-2"):
                    ui.label("共有フォルダの setup.vbs を実行してください。").classes(
                        "text-xs text-muted text-center"
                    )
                    with ui.row().classes("w-full justify-end gap-2"):
                        ui.button(
                            "閉じる",
                            on_click=dialog.close,
                        ).classes("btn-primary")
            else:
                # 通常のアップデート
                with ui.row().classes("w-full justify-end gap-2"):

                    async def on_download():
                        await self._start_download(info, dialog)

                    ui.button(
                        "ダウンロード",
                        on_click=on_download,
                    ).classes("btn-primary")

        dialog.open()

    async def _start_download(self, info: VersionInfo, dialog: ui.dialog):
        """ダウンロードを開始"""
        dialog.close()

        if not self.updater:
            ui.notify("アップデーターが初期化されていません", type="warning")
            return

        try:
            # ダウンロード実行（高速なため通知なしで直接実行）
            zip_path = await asyncio.to_thread(
                lambda: self.updater.download_update(info, None)
            )

            # インストール確認ダイアログを直接表示
            await self._confirm_install(zip_path)

        except (OSError, ValueError, RuntimeError) as e:
            ui.notify(f"ダウンロードに失敗: {e}", type="negative")

    async def _confirm_install(self, zip_path):
        """インストール確認ダイアログ"""
        # asyncio.to_thread後はclientコンテキストが必要
        if not self._client:
            ui.notify("クライアント参照がありません", type="warning")
            return

        with self._client:
            with ui.dialog() as dialog, ui.card().classes("w-80"):
                with ui.column().classes("w-full gap-4 p-4"):
                    ui.icon("check_circle").classes(
                        "text-4xl text-positive self-center"
                    )
                    ui.label("ダウンロード完了").classes(
                        "text-lg font-semibold text-center"
                    )
                    ui.label(
                        "アプリケーションを終了してアップデートをインストールしますか？"
                    ).classes("text-sm text-center text-muted")

                    with ui.row().classes("w-full justify-end gap-2 mt-2"):
                        later_btn = (
                            ui.button("後で", on_click=dialog.close)
                            .props("flat")
                            .classes("text-muted")
                        )
                        install_btn = ui.button("インストール").classes("btn-primary")

                        async def on_install_click():
                            await self._do_install(
                                zip_path, dialog, install_btn, later_btn
                            )

                        install_btn.on_click(on_install_click)

            dialog.open()

    async def _do_install(self, zip_path, dialog: ui.dialog, install_btn, later_btn):
        """インストールを実行"""
        if not self.updater:
            return

        # ボタンを無効化してローディング表示
        install_btn.disable()
        install_btn.text = "インストール中..."
        later_btn.disable()

        try:
            # install_updateは同期処理だがスクリプト生成のみなので高速
            success = await asyncio.to_thread(
                lambda: self.updater.install_update(zip_path)
            )
            if success:
                dialog.close()
                ui.notify(
                    "アップデートの準備ができました。アプリケーションを再起動します...",
                    type="positive",
                    timeout=3000,
                )
                # 少し待ってからアプリを終了（通知を表示する時間）
                await asyncio.sleep(1.0)
                # アプリを終了（Windowsの場合はバッチファイルが処理を引き継ぐ）
                from yakulingo.ui.utils import write_launcher_state

                write_launcher_state("update_in_progress")
                await self._shutdown_app(exit_code=20)
            else:
                install_btn.enable()
                install_btn.text = "インストール"
                later_btn.enable()
                ui.notify("インストールに失敗しました", type="negative")
        except (OSError, ValueError, RuntimeError) as e:
            install_btn.enable()
            install_btn.text = "インストール"
            later_btn.enable()
            ui.notify(f"インストールエラー: {e}", type="negative")

    async def _shutdown_app(self, exit_code: int = 0):
        """アプリケーションを確実に終了する

        NiceGUIのon_shutdownで登録されたcleanup処理（翻訳停止、DB閉鎖など）を
        呼び出した後、プロセスを終了する。通常の×ボタン終了と同じ処理が行われる。
        """
        import os

        from nicegui import app as nicegui_app

        # NiceGUI のシャットダウンを実行（on_shutdown で登録された cleanup が呼ばれる）
        # これにより翻訳キャンセル、ローカルAI停止、DB閉鎖などが行われる
        nicegui_app.shutdown()

        # cleanup処理が完了するまで待機
        await asyncio.sleep(3.0)

        # NiceGUI shutdown でプロセスが終了しない場合のフォールバック
        os._exit(exit_code)


async def check_updates_on_startup(
    settings: AppSettings, client: Optional[Client] = None
) -> Optional[UpdateNotification]:
    """
    起動時にアップデートをチェック

    Args:
        settings: アプリケーション設定
        client: NiceGUIクライアント参照（asyncコンテキストでのUI操作に必要）

    Returns:
        アップデートが利用可能な場合は UpdateNotification インスタンス
    """
    notification = UpdateNotification(settings, client)

    if not notification.should_check_updates():
        return None

    result = await notification.check_for_updates(silent=True)

    if result and result.status == UpdateStatus.UPDATE_AVAILABLE:
        return notification

    return None
