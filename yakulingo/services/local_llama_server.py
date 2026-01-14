# yakulingo/services/local_llama_server.py
"""
Local AI (llama.cpp llama-server) process manager.

Design goals (M1):
- Use a single resident llama-server process per machine/user session.
- Bind to 127.0.0.1 only (never expose externally).
- Reuse existing server when safe, otherwise start a new one on an available port.
- Persist server state in a user-writable location (~/.yakulingo/local_ai_server.json).
"""

from __future__ import annotations

import json
import logging
import os
import socket
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import psutil

from yakulingo.config.settings import AppSettings

logger = logging.getLogger(__name__)

_HELP_TEXT_CACHE: dict[tuple[str, int, int], str] = {}
_HELP_TEXT_CACHE_LOCK = threading.Lock()
_EXE_SUPPORTED_CACHE: dict[tuple[str, int, int], bool] = {}
_EXE_SUPPORTED_CACHE_LOCK = threading.Lock()
_NO_PROXY_LOCAL_HOSTS = ("127.0.0.1", "localhost")
_REUSE_FAST_PATH_TTL_S = 120.0
_REUSE_HEALTHCHECK_TIMEOUT_S = 0.25


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _app_base_dir() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _user_data_dir() -> Path:
    path = Path.home() / ".yakulingo"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _merge_no_proxy_items() -> list[str]:
    items: list[str] = []
    seen: set[str] = set()
    for name in ("NO_PROXY", "no_proxy"):
        raw = os.environ.get(name, "")
        for item in raw.split(","):
            token = item.strip()
            if not token:
                continue
            lowered = token.lower()
            if lowered in seen:
                continue
            items.append(token)
            seen.add(lowered)
    for host in _NO_PROXY_LOCAL_HOSTS:
        lowered = host.lower()
        if lowered in seen:
            continue
        items.append(host)
        seen.add(lowered)
    return items


def ensure_no_proxy_for_localhost() -> None:
    items = _merge_no_proxy_items()
    if not items:
        return
    value = ",".join(items)
    os.environ["NO_PROXY"] = value
    os.environ["no_proxy"] = value


def _atomic_write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    tmp_path.replace(path)


def _safe_read_json(path: Path) -> Optional[dict]:
    try:
        if not path.exists():
            return None
        with open(path, "r", encoding="utf-8-sig") as f:
            obj = json.load(f)
        return obj if isinstance(obj, dict) else None
    except Exception:
        logger.debug("Failed to read json: %s", path, exc_info=True)
        return None


def _normalize_path_text(path: Path) -> str:
    try:
        return str(path.resolve()).replace("\\", "/").lower()
    except Exception:
        return str(path).replace("\\", "/").lower()


def _resolve_from_app_base(path_text: str) -> Path:
    path = Path(path_text)
    if path.is_absolute():
        return path
    return _app_base_dir() / path


def _find_llama_server_exe(dir_path: Path) -> Optional[Path]:
    candidates = [
        dir_path / "llama-server.exe",
        dir_path / "server.exe",
        dir_path / "llama-server",
        dir_path / "server",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _file_fingerprint(path: Path) -> tuple[int, int]:
    stat = path.stat()
    return stat.st_size, int(stat.st_mtime)


def _help_cache_key(path: Path) -> tuple[str, int, int]:
    try:
        size, mtime = _file_fingerprint(path)
    except OSError:
        size, mtime = 0, 0
    return _normalize_path_text(path), size, mtime


def _get_help_text_cached(server_exe_path: Path) -> str:
    key = _help_cache_key(server_exe_path)
    with _HELP_TEXT_CACHE_LOCK:
        cached = _HELP_TEXT_CACHE.get(key)
    if cached is not None:
        return cached

    help_text = ""
    try:
        completed = subprocess.run(
            [str(server_exe_path), "--help"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=2.0,
            check=False,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        help_text = completed.stdout or ""
    except Exception:
        help_text = ""

    with _HELP_TEXT_CACHE_LOCK:
        _HELP_TEXT_CACHE[key] = help_text
    return help_text


def _is_port_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        # WindowsのSO_REUSEADDRは「使用中でもbindできる」等の危険な挙動になり得るため、
        # 空きポート判定では使わない（誤判定→他プロセス衝突の事故を避ける）。
        if os.name == "nt":
            try:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            except Exception:
                pass
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


def _http_get_json_with_status(
    host: str,
    port: int,
    path: str,
    timeout_s: float,
) -> tuple[Optional[dict], Optional[int], Optional[str]]:
    import urllib.error
    import urllib.request

    ensure_no_proxy_for_localhost()

    url = f"http://{host}:{port}{path}"
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            raw = resp.read()
            status_code = resp.getcode()
        try:
            payload = json.loads(raw.decode("utf-8"))
        except Exception:
            return None, status_code, "invalid json"
        return payload, status_code, None
    except urllib.error.HTTPError as e:
        return None, e.code, f"HTTP {e.code}"
    except Exception as e:
        return None, None, str(e)


def _http_get_json(host: str, port: int, path: str, timeout_s: float) -> Optional[dict]:
    payload, _, _ = _http_get_json_with_status(host, port, path, timeout_s)
    return payload


def _probe_openai_models(
    host: str, port: int, timeout_s: float = 0.8
) -> tuple[Optional[dict], Optional[str]]:
    models, status, error = _http_get_json_with_status(
        host, port, "/v1/models", timeout_s=timeout_s
    )
    if (
        isinstance(models, dict)
        and models.get("object") == "list"
        and isinstance(models.get("data"), list)
    ):
        return models, None
    if status is not None:
        return None, f"HTTP {status}"
    if error:
        return None, error
    return None, "invalid response"


def _is_openai_compatible_server(host: str, port: int, timeout_s: float = 0.8) -> bool:
    models, _ = _probe_openai_models(host, port, timeout_s=timeout_s)
    return models is not None


def _extract_first_model_id(models_payload: dict) -> Optional[str]:
    try:
        data = models_payload.get("data")
        if not isinstance(data, list) or not data:
            return None
        first = data[0]
        if not isinstance(first, dict):
            return None
        model_id = first.get("id")
        return model_id if isinstance(model_id, str) and model_id else None
    except Exception:
        return None


def _is_illegal_instruction_returncode(returncode: int) -> bool:
    if returncode in (3221225501, -1073741795):  # 0xC000001D
        return True
    return False


def _probe_executable_supported(exe_path: Path, timeout_s: float = 2.0) -> bool:
    try:
        completed = subprocess.run(
            [str(exe_path), "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_s,
            check=False,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if _is_illegal_instruction_returncode(completed.returncode):
            return False
        return True
    except subprocess.TimeoutExpired:
        return True
    except Exception:
        logger.debug("Failed to probe llama-server: %s", exe_path, exc_info=True)
        return True


def _is_executable_supported_cached(exe_path: Path) -> bool:
    key = _help_cache_key(exe_path)
    with _EXE_SUPPORTED_CACHE_LOCK:
        cached = _EXE_SUPPORTED_CACHE.get(key)
    if cached is not None:
        return cached

    supported = _probe_executable_supported(exe_path)
    with _EXE_SUPPORTED_CACHE_LOCK:
        _EXE_SUPPORTED_CACHE[key] = supported
    return supported


def _get_app_version_text() -> Optional[str]:
    import importlib.metadata

    try:
        return importlib.metadata.version("yakulingo")
    except Exception:
        try:
            from yakulingo import __version__

            return __version__
        except Exception:
            return None


@dataclass(frozen=True)
class LocalAIServerRuntime:
    host: str
    port: int
    base_url: str
    model_id: Optional[str]
    server_exe_path: Path
    server_variant: str
    model_path: Path


class LocalAIError(RuntimeError):
    pass


class LocalAINotInstalledError(LocalAIError):
    pass


class LocalAIServerStartError(LocalAIError):
    pass


class LocalLlamaServerManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._process: Optional[subprocess.Popen] = None
        self._process_log_fp = None
        self._runtime: Optional[LocalAIServerRuntime] = None
        self._reuse_fast_path_until: float = 0.0

    @staticmethod
    def get_state_path() -> Path:
        return _user_data_dir() / "local_ai_server.json"

    @staticmethod
    def get_log_path() -> Path:
        log_dir = _user_data_dir() / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        return log_dir / "local_ai_server.log"

    def get_runtime(self) -> Optional[LocalAIServerRuntime]:
        return self._runtime

    def note_server_ok(self, runtime: LocalAIServerRuntime) -> None:
        now = time.monotonic()
        with self._lock:
            current = self._runtime
            if current is None:
                return
            if current.host != runtime.host or current.port != runtime.port:
                return
            if self._process is None:
                self._reuse_fast_path_until = now + _REUSE_FAST_PATH_TTL_S

    def _can_fast_path(self, settings: AppSettings, model_path: Optional[Path]) -> bool:
        runtime = self._runtime
        if runtime is None:
            return False
        if model_path is None:
            return False
        try:
            if runtime.model_path.resolve() != model_path.resolve():
                return False
        except OSError:
            return False

        server_dir = self._resolve_server_dir(settings)
        try:
            exe_path = runtime.server_exe_path.resolve()
            server_dir = server_dir.resolve()
        except OSError:
            return False
        if not exe_path.is_relative_to(server_dir):
            return False

        port_base = int(settings.local_ai_port_base)
        port_max = int(settings.local_ai_port_max)
        if runtime.port < port_base or runtime.port > port_max:
            return False
        if runtime.host != "127.0.0.1":
            return False

        proc = self._process
        if proc is not None:
            if proc.poll() is not None:
                return False
            return True

        now = time.monotonic()
        if now < self._reuse_fast_path_until:
            return True

        models_payload, _ = _probe_openai_models(
            runtime.host, runtime.port, timeout_s=_REUSE_HEALTHCHECK_TIMEOUT_S
        )
        if models_payload is None:
            return False

        self._reuse_fast_path_until = now + _REUSE_FAST_PATH_TTL_S
        return True

    def ensure_ready(self, settings: AppSettings) -> LocalAIServerRuntime:
        with self._lock:
            runtime = self._ensure_ready_locked(settings)
            self._runtime = runtime
            return runtime

    def _ensure_ready_locked(self, settings: AppSettings) -> LocalAIServerRuntime:
        model_path = self._resolve_model_path(settings)
        if self._can_fast_path(settings, model_path):
            runtime = self._runtime
            assert runtime is not None
            return runtime
        server_dir = self._resolve_server_dir(settings)
        bundled_server_dir = _app_base_dir() / "local_ai" / "llama_cpp"

        if model_path is None:
            raise LocalAINotInstalledError(
                "ローカルAIのモデルが見つかりません。install_deps.bat を実行するか、設定の local_ai_model_path を確認してください。"
            )

        server_exe_path, server_variant = self._resolve_server_exe(server_dir)
        if server_exe_path is None and server_dir != bundled_server_dir:
            fallback_exe, fallback_variant = self._resolve_server_exe(
                bundled_server_dir
            )
            if fallback_exe is not None:
                server_dir = bundled_server_dir
                server_exe_path, server_variant = fallback_exe, fallback_variant
        if server_exe_path is None:
            if server_variant == "avx2_unsupported":
                raise LocalAIError(
                    "ローカルAI（AVX2版）はこのPCで動作しません（AVX2非対応）。generic 版の同梱/配布が必要です。"
                )
            raise LocalAINotInstalledError(
                "ローカルAIの llama-server が見つかりません。install_deps.bat を実行するか、設定の local_ai_server_dir を確認してください。"
            )

        host = "127.0.0.1"
        port_base = int(settings.local_ai_port_base)
        port_max = int(settings.local_ai_port_max)

        state_path = self.get_state_path()
        saved_state = _safe_read_json(state_path) or {}

        model_size, model_mtime = _file_fingerprint(model_path)
        expected_exe_norm = _normalize_path_text(server_exe_path)
        expected_model_norm = _normalize_path_text(model_path)

        reuse_candidate = self._try_reuse(
            saved_state,
            expected_host=host,
            expected_exe_norm=expected_exe_norm,
            expected_model_norm=expected_model_norm,
            expected_model_size=model_size,
            expected_model_mtime=model_mtime,
        )
        if reuse_candidate is not None:
            pid_create_time: Optional[float] = None
            raw_ct = saved_state.get("pid_create_time")
            if isinstance(raw_ct, (int, float)):
                pid_create_time = float(raw_ct)
            if pid_create_time is None:
                pid = saved_state.get("pid")
                if isinstance(pid, int) and pid > 0:
                    try:
                        pid_create_time = psutil.Process(pid).create_time()
                    except Exception:
                        pid_create_time = None

            self._write_state(
                state_path,
                {
                    **saved_state,
                    "host": reuse_candidate.host,
                    "port": reuse_candidate.port,
                    "pid": saved_state.get("pid"),
                    "pid_create_time": pid_create_time,
                    "server_exe_path_resolved": str(server_exe_path.resolve()),
                    "server_variant": server_variant,
                    "model_path_resolved": str(model_path.resolve()),
                    "model_size": model_size,
                    "model_mtime": model_mtime,
                    "last_ok_at": _utc_now_iso(),
                    "app_version": _get_app_version_text(),
                },
            )
            self._process = None
            self._reuse_fast_path_until = time.monotonic() + _REUSE_FAST_PATH_TTL_S
            return LocalAIServerRuntime(
                host=reuse_candidate.host,
                port=reuse_candidate.port,
                base_url=reuse_candidate.base_url,
                model_id=reuse_candidate.model_id,
                server_exe_path=server_exe_path,
                server_variant=server_variant,
                model_path=model_path,
            )

        free_port = self._find_free_port(host, port_base, port_max)
        if free_port is None:
            raise LocalAIServerStartError(
                f"ローカルAIの空きポートが見つかりませんでした（{port_base}-{port_max}）。"
            )

        self._reuse_fast_path_until = 0.0
        runtime = self._start_new_server(
            server_exe_path=server_exe_path,
            server_variant=server_variant,
            model_path=model_path,
            host=host,
            port=free_port,
            settings=settings,
        )

        pid = self._process.pid if self._process else None
        pid_create_time: Optional[float] = None
        if pid is not None:
            try:
                pid_create_time = psutil.Process(pid).create_time()
            except Exception:
                pid_create_time = None

        self._write_state(
            state_path,
            {
                "host": runtime.host,
                "port": runtime.port,
                "pid": pid,
                "pid_create_time": pid_create_time,
                "server_exe_path_resolved": str(server_exe_path.resolve()),
                "server_variant": server_variant,
                "model_path_resolved": str(model_path.resolve()),
                "model_size": model_size,
                "model_mtime": model_mtime,
                "started_at": _utc_now_iso(),
                "last_ok_at": _utc_now_iso(),
                "app_version": _get_app_version_text(),
            },
        )
        return runtime

    def stop(self, *, timeout_s: float = 5.0) -> None:
        with self._lock:
            self._stop_locked(timeout_s=timeout_s)

    def _stop_locked(self, *, timeout_s: float = 5.0) -> None:
        state_path = self.get_state_path()
        saved_state = _safe_read_json(state_path) or {}

        proc = self._process
        self._process = None
        self._reuse_fast_path_until = 0.0

        if proc is None:
            self._stop_by_state_if_safe(saved_state, timeout_s=timeout_s)
        else:
            try:
                proc.terminate()
                proc.wait(timeout=timeout_s)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass

        try:
            if self._process_log_fp:
                try:
                    self._process_log_fp.flush()
                except Exception:
                    pass
                self._process_log_fp.close()
        finally:
            self._process_log_fp = None

        self._runtime = None
        if saved_state:
            try:
                _atomic_write_json(
                    state_path,
                    {
                        **saved_state,
                        "pid": None,
                        "stopped_at": _utc_now_iso(),
                        "app_version": _get_app_version_text(),
                    },
                )
            except Exception:
                logger.debug(
                    "Failed to update local_ai_server.json on stop", exc_info=True
                )

    def _stop_by_state_if_safe(self, saved_state: dict, *, timeout_s: float) -> None:
        pid = saved_state.get("pid")
        if not isinstance(pid, int) or pid <= 0:
            return

        expected_ct = saved_state.get("pid_create_time")
        expected_create_time: Optional[float] = None
        if isinstance(expected_ct, (int, float)):
            expected_create_time = float(expected_ct)

        expected_exe = saved_state.get("server_exe_path_resolved")
        expected_model = saved_state.get("model_path_resolved")
        if not isinstance(expected_exe, str) or not isinstance(expected_model, str):
            return

        try:
            proc = psutil.Process(pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return

        try:
            exe = proc.exe()
            cmdline = " ".join(proc.cmdline() or [])
            create_time = (
                proc.create_time() if expected_create_time is not None else None
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return
        except Exception:
            return

        if expected_create_time is not None:
            if (
                create_time is None
                or abs(float(create_time) - expected_create_time) > 1.0
            ):
                return

        exe_norm = exe.replace("\\", "/").lower()
        expected_exe_norm = expected_exe.replace("\\", "/").lower()
        expected_model_norm = expected_model.replace("\\", "/").lower()
        cmd_norm = cmdline.replace("\\", "/").lower()

        if exe_norm != expected_exe_norm:
            return
        if expected_model_norm not in cmd_norm:
            return

        try:
            proc.terminate()
            proc.wait(timeout=timeout_s)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    def _resolve_model_path(self, settings: AppSettings) -> Optional[Path]:
        fixed = (
            _app_base_dir()
            / "local_ai"
            / "models"
            / "HY-MT1.5-1.8B-Q4_K_M.gguf"
        )
        return fixed if fixed.is_file() else None

    def _resolve_server_dir(self, settings: AppSettings) -> Path:
        raw = (settings.local_ai_server_dir or "").strip()
        if raw:
            return _resolve_from_app_base(raw)
        return _app_base_dir() / "local_ai" / "llama_cpp"

    def _resolve_server_exe(self, server_dir: Path) -> tuple[Optional[Path], str]:
        state = _safe_read_json(self.get_state_path()) or {}
        preferred = state.get("server_variant")
        preferred_variant = preferred if isinstance(preferred, str) else None

        candidates: list[tuple[str, Path]] = []
        direct_variant = server_dir.name.lower()
        base_dir = server_dir
        direct_variant_applied = False
        if direct_variant in ("vulkan", "avx2", "generic"):
            candidates.append((direct_variant, server_dir))
            base_dir = server_dir.parent
            direct_variant_applied = True

        if (base_dir / "vulkan").is_dir():
            candidate = base_dir / "vulkan"
            if candidate != server_dir:
                candidates.append(("vulkan", candidate))
        if (base_dir / "avx2").is_dir():
            candidate = base_dir / "avx2"
            if candidate != server_dir:
                candidates.append(("avx2", candidate))
        if (base_dir / "generic").is_dir():
            candidate = base_dir / "generic"
            if candidate != server_dir:
                candidates.append(("generic", candidate))

        if not direct_variant_applied:
            candidates.append(("direct", server_dir))

        if preferred_variant and not direct_variant_applied:
            candidates = sorted(
                candidates, key=lambda item: 0 if item[0] == preferred_variant else 1
            )

        avx2_unsupported = False
        for variant, dir_path in candidates:
            exe = _find_llama_server_exe(dir_path)
            if exe is None:
                continue
            if not _is_executable_supported_cached(exe):
                avx2_unsupported = True
                continue
            return exe, variant

        if avx2_unsupported:
            return None, "avx2_unsupported"
        return None, "unknown"

    def _find_free_port(
        self, host: str, port_base: int, port_max: int
    ) -> Optional[int]:
        for port in range(port_base, port_max + 1):
            if _is_port_free(host, port):
                return port
        return None

    def _try_reuse(
        self,
        state: dict,
        *,
        expected_host: str,
        expected_exe_norm: str,
        expected_model_norm: str,
        expected_model_size: int,
        expected_model_mtime: int,
    ) -> Optional[LocalAIServerRuntime]:
        host = state.get("host")
        port = state.get("port")
        pid = state.get("pid")

        if host != expected_host:
            return None
        if not isinstance(port, int):
            return None
        if not isinstance(pid, int) or pid <= 0:
            return None

        exe_path = state.get("server_exe_path_resolved")
        model_path = state.get("model_path_resolved")
        model_size = state.get("model_size")
        model_mtime = state.get("model_mtime")
        if not isinstance(exe_path, str) or not isinstance(model_path, str):
            return None
        if not isinstance(model_size, int) or not isinstance(model_mtime, int):
            return None

        if exe_path and exe_path.strip():
            if exe_path:
                if _normalize_path_text(Path(exe_path)) != expected_exe_norm:
                    return None
        if _normalize_path_text(Path(model_path)) != expected_model_norm:
            return None
        if model_size != expected_model_size:
            return None
        if int(model_mtime) != int(expected_model_mtime):
            return None

        expected_ct = state.get("pid_create_time")
        expected_create_time: Optional[float] = None
        if isinstance(expected_ct, (int, float)):
            expected_create_time = float(expected_ct)

        try:
            proc = psutil.Process(pid)
            if not proc.is_running():
                return None
            exe = proc.exe()
            cmdline = " ".join(proc.cmdline() or [])
            create_time = (
                proc.create_time() if expected_create_time is not None else None
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return None
        except Exception:
            return None

        if expected_create_time is not None:
            if (
                create_time is None
                or abs(float(create_time) - expected_create_time) > 1.0
            ):
                return None

        if exe and exe.strip():
            if exe.replace("\\", "/").lower() != expected_exe_norm:
                return None
        if expected_model_norm not in cmdline.replace("\\", "/").lower():
            return None
        # Short grace period to reuse a warming server before starting a new one.
        ready, last_error, models_payload = self._wait_ready(
            expected_host,
            port,
            None,
            timeout_s=4.0,
        )
        if not ready:
            if last_error:
                logger.debug(
                    "Local AI reuse probe failed (host=%s port=%d): %s",
                    expected_host,
                    port,
                    last_error,
                )
            return None
        model_id = (
            _extract_first_model_id(models_payload)
            if isinstance(models_payload, dict)
            else None
        )

        return LocalAIServerRuntime(
            host=expected_host,
            port=port,
            base_url=f"http://{expected_host}:{port}",
            model_id=model_id,
            server_exe_path=Path(exe_path),
            server_variant=str(state.get("server_variant") or "unknown"),
            model_path=Path(model_path),
        )

    def _start_new_server(
        self,
        *,
        server_exe_path: Path,
        server_variant: str,
        model_path: Path,
        host: str,
        port: int,
        settings: AppSettings,
    ) -> LocalAIServerRuntime:
        log_path = self.get_log_path()
        log_path.parent.mkdir(parents=True, exist_ok=True)

        args = self._build_server_args(
            server_exe_path=server_exe_path,
            server_variant=server_variant,
            model_path=model_path,
            host=host,
            port=port,
            settings=settings,
        )

        creationflags = 0
        if os.name == "nt":
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        log_fp = open(log_path, "a", encoding="utf-8", errors="replace")
        self._process_log_fp = log_fp
        logger.info("Starting llama-server: %s", " ".join(args))
        try:
            env = os.environ.copy()
            gpu_enabled = str(server_variant).lower() == "vulkan"
            if gpu_enabled:
                if settings.local_ai_vk_force_max_allocation_size:
                    env["GGML_VK_FORCE_MAX_ALLOCATION_SIZE"] = str(
                        settings.local_ai_vk_force_max_allocation_size
                    )
                if settings.local_ai_vk_disable_f16:
                    env["GGML_VK_DISABLE_F16"] = "1"
            proc = subprocess.Popen(
                args,
                stdout=log_fp,
                stderr=log_fp,
                stdin=subprocess.DEVNULL,
                creationflags=creationflags,
                env=env,
            )
        except OSError as e:
            log_fp.close()
            self._process_log_fp = None
            raise LocalAIServerStartError(
                f"llama-server の起動に失敗しました: {e}。詳細は {log_path} を確認してください。"
            ) from e

        self._process = proc

        ready, last_error, models_payload = self._wait_ready(
            host, port, proc, timeout_s=120.0
        )
        if not ready:
            rc = proc.poll()
            if rc is not None:
                raise LocalAIServerStartError(
                    f"llama-server の起動に失敗しました（終了コード={rc}）。詳細は {log_path} を確認してください。"
                )
            reason = f"準備確認エラー: {last_error}" if last_error else "準備確認エラー"
            raise LocalAIServerStartError(
                f"llama-server の起動がタイムアウトしました。{reason}。詳細は {log_path} を確認してください。"
            )

        models_payload = models_payload or {}
        model_id = (
            _extract_first_model_id(models_payload)
            if isinstance(models_payload, dict)
            else None
        )

        return LocalAIServerRuntime(
            host=host,
            port=port,
            base_url=f"http://{host}:{port}",
            model_id=model_id,
            server_exe_path=server_exe_path,
            server_variant=server_variant,
            model_path=model_path,
        )

    def _wait_ready(
        self,
        host: str,
        port: int,
        proc: Optional[subprocess.Popen] = None,
        *,
        timeout_s: float,
    ) -> tuple[bool, Optional[str], Optional[dict]]:
        deadline = time.monotonic() + timeout_s
        last_error: Optional[str] = None
        while time.monotonic() < deadline:
            if proc is not None:
                rc = proc.poll()
                if rc is not None:
                    return False, f"process exited ({rc})", None
            models_payload, error = _probe_openai_models(host, port, timeout_s=0.8)
            if models_payload is not None:
                return True, None, models_payload
            last_error = error
            delay = 0.25
            if error:
                lowered = error.lower()
                if "http 503" in lowered:
                    delay = 0.7
                elif "http 429" in lowered:
                    delay = 1.0
                elif "timed out" in lowered or "timeout" in lowered:
                    delay = 0.5
            time.sleep(delay)
        return False, last_error, None

    def _build_server_args(
        self,
        *,
        server_exe_path: Path,
        server_variant: str,
        model_path: Path,
        host: str,
        port: int,
        settings: AppSettings,
    ) -> list[str]:
        help_text = _get_help_text_cached(server_exe_path)

        import re

        def has_long(flag: str) -> bool:
            return flag in help_text

        def has_short(flag: str) -> bool:
            if not flag.startswith("-") or flag.startswith("--"):
                return False
            return bool(re.search(rf"(?m)^\s*{re.escape(flag)}(?:,|\s)", help_text))

        def normalize_device(value: Optional[str]) -> Optional[str]:
            if value is None:
                return None
            token = str(value).strip()
            return token or None

        def normalize_n_gpu_layers(value: Optional[object]) -> Optional[str]:
            if value is None:
                return None
            if isinstance(value, bool):
                return None
            if isinstance(value, (int, float)):
                return str(int(value))
            token = str(value).strip()
            return token or None

        gpu_enabled = str(server_variant).lower() == "vulkan"

        args: list[str] = [str(server_exe_path)]

        args += ["--host", host, "--port", str(port)]

        if has_short("-m"):
            args += ["-m", str(model_path)]
        elif help_text and has_long("--model"):
            args += ["--model", str(model_path)]
        else:
            args += ["-m", str(model_path)]

        if (
            help_text
            and settings.local_ai_ctx_size
            and (has_long("--ctx-size") or has_short("-c"))
        ):
            flag = "--ctx-size" if has_long("--ctx-size") else "-c"
            args += [flag, str(int(settings.local_ai_ctx_size))]

        threads_setting = settings.local_ai_threads
        threads = int(threads_setting) if threads_setting is not None else 0
        auto_threads: Optional[int] = None
        if threads <= 0:
            try:
                physical = psutil.cpu_count(logical=False)
            except Exception:
                physical = None
            if not physical or physical < 1:
                physical = os.cpu_count() or 1
            auto_threads = max(1, int(physical))
            threads = auto_threads
        if help_text and threads and (has_long("--threads") or has_short("-t")):
            flag = "--threads" if has_long("--threads") else "-t"
            args += [flag, str(threads)]
            if auto_threads is not None:
                logger.info(
                    "Local AI threads auto: %d (config=%s)", threads, threads_setting
                )
            else:
                logger.info("Local AI threads configured: %d", threads)
        elif auto_threads is not None:
            logger.info(
                "Local AI threads auto resolved to %d but flag not supported",
                threads,
            )

        threads_batch_setting = settings.local_ai_threads_batch
        threads_batch: Optional[int] = None
        auto_threads_batch: Optional[int] = None
        if threads_batch_setting is not None:
            try:
                threads_batch = int(threads_batch_setting)
            except (TypeError, ValueError):
                threads_batch = None
            else:
                if threads_batch <= 0:
                    auto_threads_batch = threads
                    threads_batch = auto_threads_batch
        if help_text and threads_batch and (
            has_long("--threads-batch") or has_short("-tb")
        ):
            flag = "--threads-batch" if has_long("--threads-batch") else "-tb"
            args += [flag, str(threads_batch)]
            if auto_threads_batch is not None:
                logger.info(
                    "Local AI threads-batch auto: %d (config=%s)",
                    threads_batch,
                    threads_batch_setting,
                )
            else:
                logger.info("Local AI threads-batch configured: %d", threads_batch)
        elif threads_batch_setting is not None and auto_threads_batch is not None:
            logger.info(
                "Local AI threads-batch auto resolved to %d but flag not supported",
                threads_batch,
            )
        elif threads_batch_setting is not None and threads_batch is not None:
            logger.info(
                "Local AI threads-batch configured (%s) but flag not supported",
                threads_batch,
            )

        if help_text and settings.local_ai_temperature is not None:
            if has_long("--temp"):
                args += ["--temp", str(float(settings.local_ai_temperature))]
            elif has_long("--temperature"):
                args += ["--temperature", str(float(settings.local_ai_temperature))]

        if settings.local_ai_max_tokens is not None:
            if help_text and has_long("--n-predict"):
                args += ["--n-predict", str(int(settings.local_ai_max_tokens))]
            elif help_text and has_short("-n"):
                args += ["-n", str(int(settings.local_ai_max_tokens))]

        batch_size = settings.local_ai_batch_size
        if help_text and batch_size is not None and batch_size > 0:
            if has_long("--batch-size"):
                args += ["--batch-size", str(int(batch_size))]
            elif has_short("-b"):
                args += ["-b", str(int(batch_size))]

        ubatch_size = settings.local_ai_ubatch_size
        if help_text and ubatch_size is not None and ubatch_size > 0:
            if has_long("--ubatch-size"):
                args += ["--ubatch-size", str(int(ubatch_size))]
            elif has_short("-ub"):
                args += ["-ub", str(int(ubatch_size))]

        if help_text and settings.local_ai_mlock and has_long("--mlock"):
            args += ["--mlock"]

        if help_text and settings.local_ai_no_mmap and has_long("--no-mmap"):
            args += ["--no-mmap"]

        device_value = normalize_device(settings.local_ai_device)
        n_gpu_layers_value = normalize_n_gpu_layers(settings.local_ai_n_gpu_layers)
        cpu_only_requested = False
        if device_value and device_value.lower() == "none":
            cpu_only_requested = True
        if n_gpu_layers_value == "0":
            cpu_only_requested = True

        device_supported = bool(help_text) and has_long("--device")
        ngl_flag = None
        if help_text:
            if has_long("--n-gpu-layers"):
                ngl_flag = "--n-gpu-layers"
            elif has_short("-ngl"):
                ngl_flag = "-ngl"

        applied_device: Optional[str] = None
        applied_n_gpu_layers: Optional[str] = None

        if device_supported:
            if cpu_only_requested:
                args += ["--device", "none"]
                applied_device = "none"
            elif gpu_enabled and device_value and device_value.lower() != "none":
                args += ["--device", device_value]
                applied_device = device_value

        if ngl_flag:
            if cpu_only_requested:
                args += [ngl_flag, "0"]
                applied_n_gpu_layers = "0"
            elif gpu_enabled and n_gpu_layers_value is not None:
                args += [ngl_flag, n_gpu_layers_value]
                applied_n_gpu_layers = n_gpu_layers_value

        if gpu_enabled and not cpu_only_requested:
            flash_attn = settings.local_ai_flash_attn
            if help_text and flash_attn and str(flash_attn).lower() != "auto":
                flag = None
                if has_short("-fa"):
                    flag = "-fa"
                elif has_long("--flash-attn"):
                    flag = "--flash-attn"
                elif has_long("--flash-attention"):
                    flag = "--flash-attention"
                if flag:
                    args += [flag, str(flash_attn)]

            cache_type_k = settings.local_ai_cache_type_k
            if help_text and cache_type_k:
                flag = None
                if has_long("--cache-type-k"):
                    flag = "--cache-type-k"
                elif has_short("-ctk"):
                    flag = "-ctk"
                if flag:
                    args += [flag, str(cache_type_k)]

            cache_type_v = settings.local_ai_cache_type_v
            if help_text and cache_type_v:
                flag = None
                if has_long("--cache-type-v"):
                    flag = "--cache-type-v"
                elif has_short("-ctv"):
                    flag = "-ctv"
                if flag:
                    args += [flag, str(cache_type_v)]

            if help_text and settings.local_ai_no_warmup and has_long("--no-warmup"):
                args += ["--no-warmup"]

        device_log = applied_device
        if not device_supported:
            device_log = "unsupported"
        elif device_log is None:
            device_log = "not-set"

        ngl_log = applied_n_gpu_layers
        if ngl_flag is None:
            ngl_log = "unsupported"
        elif ngl_log is None:
            ngl_log = "not-set"

        logger.info(
            "Local AI offload flags: --device %s / -ngl %s", device_log, ngl_log
        )

        return args

    def _write_state(self, path: Path, state: dict) -> None:
        try:
            _atomic_write_json(path, state)
        except Exception:
            logger.debug(
                "Failed to write local_ai_server.json: %s", path, exc_info=True
            )


_LOCAL_SERVER_MANAGER = LocalLlamaServerManager()


def get_local_llama_server_manager() -> LocalLlamaServerManager:
    return _LOCAL_SERVER_MANAGER
