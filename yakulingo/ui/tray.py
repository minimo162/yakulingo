# yakulingo/ui/tray.py
from __future__ import annotations

import logging
import sys
import threading
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

TrayStatusProvider = Callable[[], str | tuple[str, str] | None]


class TrayIcon:
    def __init__(
        self,
        host: str,
        port: int,
        icon_path: Path | None,
        *,
        status_provider: TrayStatusProvider | None = None,
        status_interval: float = 3.0,
    ) -> None:
        self._host = host
        self._port = port
        self._icon_path = icon_path
        self._icon = None
        self._status_provider = status_provider
        self._status_interval = max(1.0, float(status_interval))
        self._status_text = "Copilot: Unknown"
        self._status_tooltip = self._status_text
        self._status_stop = threading.Event()
        self._status_thread: threading.Thread | None = None

    def start(self) -> None:
        if sys.platform != "win32":
            return
        if self._icon is not None:
            return
        if self._icon_path is None or not self._icon_path.exists():
            logger.debug("Tray icon skipped: icon path missing")
            return
        try:
            import pystray
            from PIL import Image
        except Exception as exc:
            logger.debug("Tray icon unavailable: %s", exc)
            return
        try:
            image = Image.open(self._icon_path)
        except Exception as exc:
            logger.debug("Tray icon load failed: %s", exc)
            return

        def _status_label(_item) -> str:
            return self._status_text

        status_item = pystray.MenuItem(_status_label, lambda *_: None, enabled=False)
        menu = pystray.Menu(
            status_item,
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Open", self._on_open, default=True),
            pystray.MenuItem("Hide", self._on_hide),
            pystray.MenuItem("Exit", self._on_exit),
        )
        self._icon = pystray.Icon("YakuLingo", image, "YakuLingo", menu)
        self._refresh_status()
        try:
            self._icon.run_detached()
            self._start_status_monitor()
        except Exception as exc:
            logger.debug("Tray icon start failed: %s", exc)
            self._icon = None

    def stop(self) -> None:
        self._stop_status_monitor()
        icon = self._icon
        self._icon = None
        if icon is None:
            return
        try:
            icon.stop()
        except Exception as exc:
            logger.debug("Tray icon stop failed: %s", exc)

    def _on_open(self, _icon, _item) -> None:
        self._post_local("/api/open-text", {"X-YakuLingo-Open": "1"}, timeout=0.7)

    def _on_hide(self, _icon, _item) -> None:
        self._post_local("/api/ui-close", {"X-YakuLingo-Resident": "1"}, timeout=0.5)

    def _on_exit(self, _icon, _item) -> None:
        self._post_local("/api/shutdown", {"X-YakuLingo-Exit": "1"}, timeout=0.8)

    def _start_status_monitor(self) -> None:
        if self._status_provider is None or self._status_thread is not None:
            return
        self._status_stop.clear()

        def _worker() -> None:
            while not self._status_stop.is_set():
                self._refresh_status()
                self._status_stop.wait(self._status_interval)

        self._status_thread = threading.Thread(
            target=_worker,
            daemon=True,
            name="tray_status",
        )
        self._status_thread.start()

    def _stop_status_monitor(self) -> None:
        self._status_stop.set()
        self._status_thread = None

    def _refresh_status(self) -> None:
        label, tooltip = self._get_status_text()
        if label == self._status_text and tooltip == self._status_tooltip:
            return
        self._status_text = label
        self._status_tooltip = tooltip
        if self._icon is None:
            return
        self._icon.title = f"YakuLingo - {tooltip}"
        try:
            self._icon.update_menu()
        except Exception:
            pass

    def _get_status_text(self) -> tuple[str, str]:
        provider = self._status_provider
        if provider is None:
            return ("Copilot: Unknown", "Copilot: Unknown")
        try:
            value = provider()
        except Exception as exc:
            logger.debug("Tray status provider failed: %s", exc)
            return ("Copilot: Unknown", "Copilot: Unknown")

        label = ""
        tooltip = ""
        if isinstance(value, tuple):
            if value:
                label = str(value[0]) if value[0] else ""
            if len(value) > 1:
                tooltip = str(value[1]) if value[1] else ""
        elif isinstance(value, str):
            label = value.strip()
        else:
            label = ""

        label = label or "Copilot: Unknown"
        tooltip = tooltip or label
        return (label, tooltip)

    def _post_local(self, path: str, headers: dict[str, str], timeout: float) -> None:
        try:
            import urllib.request

            url = f"http://{self._format_control_host()}:{self._port}{path}"
            request = urllib.request.Request(
                url,
                data=b"{}",
                headers={"Content-Type": "application/json", **headers},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=timeout):
                pass
        except Exception as exc:
            logger.debug("Tray action failed (%s): %s", path, exc)

    def _format_control_host(self) -> str:
        host = (self._host or "").strip()
        if host in ("", "0.0.0.0", "::"):
            host = "127.0.0.1"
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        return host
