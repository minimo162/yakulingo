# yakulingo/ui/tray.py
from __future__ import annotations

import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


class TrayIcon:
    def __init__(self, host: str, port: int, icon_path: Path | None) -> None:
        self._host = host
        self._port = port
        self._icon_path = icon_path
        self._icon = None

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

        menu = pystray.Menu(
            pystray.MenuItem("Open", self._on_open, default=True),
            pystray.MenuItem("Hide", self._on_hide),
            pystray.MenuItem("Exit", self._on_exit),
        )
        self._icon = pystray.Icon("YakuLingo", image, "YakuLingo", menu)
        try:
            self._icon.run_detached()
        except Exception as exc:
            logger.debug("Tray icon start failed: %s", exc)
            self._icon = None

    def stop(self) -> None:
        icon = self._icon
        self._icon = None
        if icon is None:
            return
        try:
            icon.stop()
        except Exception as exc:
            logger.debug("Tray icon stop failed: %s", exc)

    def _on_open(self, _icon, _item) -> None:
        self._post_local("/api/activate", {"X-YakuLingo-Activate": "1"}, timeout=0.5)

    def _on_hide(self, _icon, _item) -> None:
        self._post_local("/api/ui-close", {"X-YakuLingo-Resident": "1"}, timeout=0.5)

    def _on_exit(self, _icon, _item) -> None:
        self._post_local("/api/shutdown", {"X-YakuLingo-Exit": "1"}, timeout=0.8)

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
