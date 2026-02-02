from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
import tarfile
import zipfile
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Literal
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

OutputLanguage = Literal["en", "ja"]
Backend = Literal["gguf", "gguf_python", "transformers", "plamo"]

_RE_CODE_FENCE_LINE = re.compile(r"^\s*```.*$", re.MULTILINE)
_RE_LEADING_LABEL = re.compile(
    r"^\s*(?:Translation|Translated|訳|訳文|翻訳)\s*[:：]\s*", re.IGNORECASE
)
_RE_GEMMA_TURN = re.compile(r"<(?:start|end)_of_turn>\s*", re.IGNORECASE)
_RE_TRANSLATEGEMMA = re.compile(r"(^|/|-)translategemma(-|$)", re.IGNORECASE)

_EN_NUMBER_WITH_OPTIONAL_COMMAS_PATTERN = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
_RE_EN_NUMBER_WITH_LARGE_UNIT = re.compile(
    rf"(?P<prefix>\(?[▲+\-−]?[¥￥]?)"
    rf"(?P<number>{_EN_NUMBER_WITH_OPTIONAL_COMMAS_PATTERN})"
    rf"(?P<suffix>\)?)"
    r"\s*"
    r"(?P<unit>billion|trillion|trllion|bn)\b"
    r"(?:\s*(?P<yen>yen)(?![A-Za-z0-9]))?",
    re.IGNORECASE,
)
_RE_EN_NUMBER_WITH_SMALL_UNIT = re.compile(
    rf"(?P<prefix>\(?[▲+\-−]?[¥￥]?)"
    rf"(?P<number>{_EN_NUMBER_WITH_OPTIONAL_COMMAS_PATTERN})"
    rf"(?P<suffix>\)?)"
    r"\s*"
    r"(?P<unit>thousand|million)\b"
    r"(?:\s*(?P<yen>yen)(?![A-Za-z0-9]))?",
    re.IGNORECASE,
)
_RE_JP_OKU_CHOU_AMOUNT = re.compile(
    r"(?P<sign>[▲△+\-−])?\s*"
    rf"(?:(?P<trillion>{_EN_NUMBER_WITH_OPTIONAL_COMMAS_PATTERN})兆"
    rf"(?:(?P<oku>{_EN_NUMBER_WITH_OPTIONAL_COMMAS_PATTERN})億)?"
    rf"|(?P<oku_only>{_EN_NUMBER_WITH_OPTIONAL_COMMAS_PATTERN})億)"
    r"(?P<yen>円)?"
)
_RE_JP_MAN_SEN_AMOUNT = re.compile(
    r"(?P<sign>[▲△+\-−])?\s*(?P<man>\d[\d,]*(?:\.\d+)?)万(?:(?P<sen>\d[\d,]*(?:\.\d+)?)千)?(?P<unit>円|台)?"
)
_RE_JP_SEN_AMOUNT = re.compile(
    r"(?P<sign>[▲△+\-−])?\s*(?P<sen>\d[\d,]*(?:\.\d+)?)千(?P<unit>円|台)?"
)

_DEFAULT_LLAMA_CPP_REPO = "ggerganov/llama.cpp"
_DEFAULT_LLAMA_CPP_ASSET_SUFFIX = "bin-ubuntu-vulkan-x64.tar.gz"
_DEFAULT_LLAMA_SERVER_HOST = "127.0.0.1"
_DEFAULT_LLAMA_SERVER_PORT = 8090
_DEFAULT_LLAMA_SERVER_STARTUP_TIMEOUT_S = 120
_DEFAULT_HTTP_TIMEOUT_S = 60
_AUTO_N_GPU_LAYERS = 999
_RE_LLAMA_CLI_AVAILABLE_DEVICES_HEADER = re.compile(
    r"^\s*Available devices:\s*$", flags=re.IGNORECASE
)
_RE_LLAMA_CLI_DEVICE_LINE = re.compile(r"^\s*(?P<name>[A-Za-z]+\d+)\s*:", re.IGNORECASE)


def _env_int(name: str, default: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_bool(name: str, default: bool = False) -> bool:
    raw = (os.environ.get(name) or "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "y", "on")


def _env_float(name: str, default: float) -> float:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _cuda_visible() -> bool:
    value = (os.environ.get("CUDA_VISIBLE_DEVICES") or "").strip()
    if not value or value in ("-1", "none"):
        return False
    return True


def _env_str(name: str, default: str) -> str:
    raw = (os.environ.get(name) or "").strip()
    return raw or default


def _is_translategemma_model_id(model_id: str) -> bool:
    return bool(_RE_TRANSLATEGEMMA.search((model_id or "").strip()))


def _translategemma_lang_codes(output_language: OutputLanguage) -> tuple[str, str]:
    if output_language == "en":
        return "ja", "en"
    return "en", "ja"


def _parse_decimal(value: str) -> Decimal | None:
    if not value:
        return None
    try:
        return Decimal(value.replace(",", ""))
    except InvalidOperation:
        return None


def _format_number_with_commas(value: Decimal) -> str:
    sign = "-" if value < 0 else ""
    value = abs(value)
    try:
        if value == value.to_integral():
            return f"{sign}{int(value):,}"
    except (InvalidOperation, ValueError):
        return f"{sign}0"

    text = format(value.normalize(), "f")
    int_part, _, frac_part = text.partition(".")
    int_part_with_commas = f"{int(int_part):,}"
    frac_part = frac_part.rstrip("0")
    if frac_part:
        return f"{sign}{int_part_with_commas}.{frac_part}"
    return f"{sign}{int_part_with_commas}"


def _format_japanese_yen_amount(yen_amount: Decimal) -> str:
    sign_prefix = "-" if yen_amount < 0 else ""
    yen_amount = abs(yen_amount)
    try:
        yen_total = int(yen_amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except (InvalidOperation, ValueError):
        return f"{sign_prefix}0円"

    unit_chou = 1_000_000_000_000
    unit_oku = 100_000_000
    unit_man = 10_000

    chou = yen_total // unit_chou
    yen_total %= unit_chou
    oku = yen_total // unit_oku
    yen_total %= unit_oku
    man = yen_total // unit_man
    yen = yen_total % unit_man

    parts: list[str] = []
    if chou:
        parts.append(f"{chou}兆")
    if oku:
        parts.append(f"{oku:,}億")
    if man:
        if yen:
            parts.append(f"{man:,}万")
        else:
            parts.append(f"{man:,}万円")
    if yen:
        parts.append(f"{yen:,}円")

    if not parts:
        parts.append("0円")
    elif not parts[-1].endswith("円"):
        parts[-1] = f"{parts[-1]}円"

    return f"{sign_prefix}{''.join(parts)}"


def _format_oku_to_japanese_cho_oku(oku_amount: Decimal, *, include_yen: bool) -> str:
    sign_prefix = "-" if oku_amount < 0 else ""
    oku_amount = abs(oku_amount)

    if oku_amount == oku_amount.to_integral():
        oku_int = int(oku_amount)
        cho = oku_int // 10_000
        oku = oku_int % 10_000
        if cho and oku:
            base = f"{cho}兆{oku:,}億"
        elif cho:
            base = f"{cho}兆"
        else:
            base = f"{oku_int:,}億"
        return f"{sign_prefix}{base}{'円' if include_yen else ''}"

    text = format(oku_amount.normalize(), "f")
    int_part, _, frac_part = text.partition(".")
    int_part_with_commas = f"{int(int_part):,}"
    frac_part = frac_part.rstrip("0")
    base = (
        f"{int_part_with_commas}.{frac_part}億" if frac_part else f"{int_part_with_commas}億"
    )
    return f"{sign_prefix}{base}{'円' if include_yen else ''}"


def _normalize_en_units_to_japanese(text: str) -> str:
    if not text:
        return text

    def repl_small(match: re.Match[str]) -> str:
        prefix = match.group("prefix") or ""
        number_str = match.group("number") or ""
        suffix = match.group("suffix") or ""
        unit = (match.group("unit") or "").lower()
        yen_word = match.group("yen") or ""

        number = _parse_decimal(number_str)
        if number is None:
            return match.group(0)

        has_yen = bool(yen_word) or ("¥" in prefix or "￥" in prefix)
        prefix = prefix.replace("¥", "").replace("￥", "")

        multiplier = Decimal("1000") if unit == "thousand" else Decimal("1000000")
        amount = number * multiplier
        if has_yen:
            return f"{prefix}{_format_japanese_yen_amount(amount)}{suffix}"
        return f"{prefix}{_format_number_with_commas(amount)}{suffix}"

    def repl_large(match: re.Match[str]) -> str:
        prefix = match.group("prefix") or ""
        number_str = match.group("number") or ""
        suffix = match.group("suffix") or ""
        unit = (match.group("unit") or "").lower()
        yen_word = match.group("yen") or ""

        number = _parse_decimal(number_str)
        if number is None:
            return match.group(0)

        has_yen = bool(yen_word) or ("¥" in prefix or "￥" in prefix)
        prefix = prefix.replace("¥", "").replace("￥", "")

        unit_key = "billion" if unit == "bn" else unit
        if unit_key == "trllion":
            unit_key = "trillion"
        multiplier = Decimal("10") if unit_key == "billion" else Decimal("10000")
        oku_amount = number * multiplier
        jp_amount = _format_oku_to_japanese_cho_oku(oku_amount, include_yen=has_yen)
        return f"{prefix}{jp_amount}{suffix}"

    fixed = text
    fixed = _RE_EN_NUMBER_WITH_SMALL_UNIT.sub(repl_small, fixed)
    fixed = _RE_EN_NUMBER_WITH_LARGE_UNIT.sub(repl_large, fixed)
    return fixed


def _normalize_jp_units_to_english(text: str) -> str:
    if not text:
        return text

    def repl_oku_chou(match: re.Match[str]) -> str:
        sign_marker = (match.group("sign") or "").strip()
        is_negative = sign_marker in {"▲", "△", "-", "−"}
        sign = -1 if is_negative else 1
        has_yen = bool(match.group("yen"))

        trillion_str = match.group("trillion") or ""
        oku_str = match.group("oku") or ""
        oku_only_str = match.group("oku_only") or ""

        if trillion_str:
            trillion = _parse_decimal(trillion_str)
            if trillion is None:
                return match.group(0)
            oku_part = _parse_decimal(oku_str) if oku_str else Decimal(0)
            if oku_part is None:
                return match.group(0)
            value = (trillion + (oku_part / Decimal("10000"))) * Decimal(sign)
            value = value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
            formatted = _format_number_with_commas(value)
            unit = "trillion yen" if has_yen else "trillion"
            if sign < 0:
                return f"({formatted.lstrip('-')} {unit})"
            return f"{formatted} {unit}"

        oku_only = _parse_decimal(oku_only_str)
        if oku_only is None:
            return match.group(0)
        value = (oku_only / Decimal("10")) * Decimal(sign)
        value = value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
        formatted = _format_number_with_commas(value)
        unit = "billion yen" if has_yen else "billion"
        if sign < 0:
            return f"({formatted.lstrip('-')} {unit})"
        return f"{formatted} {unit}"

    man_sen_spans: list[tuple[int, int]] = []

    def repl_man_sen(match: re.Match[str]) -> str:
        raw = match.group(0) or ""
        man_sen_spans.append(match.span())

        sign_marker = (match.group("sign") or "").strip()
        sign = -1 if sign_marker in {"▲", "△", "-", "−"} else 1
        man = _parse_decimal(match.group("man") or "")
        if man is None:
            return raw
        sen = _parse_decimal(match.group("sen") or "") or Decimal(0)
        k_value = (man * Decimal("10") + sen) * Decimal(sign)
        formatted = _format_number_with_commas(k_value)
        unit = (match.group("unit") or "").strip()
        suffix = " yen" if unit == "円" else (" units" if unit == "台" else "")
        if sign < 0:
            return f"({formatted.lstrip('-')}k{suffix})"
        return f"{formatted}k{suffix}"

    def inside_man_sen(start: int) -> bool:
        return any(s <= start < e for s, e in man_sen_spans)

    def repl_sen(match: re.Match[str]) -> str:
        raw = match.group(0) or ""
        if inside_man_sen(match.start()):
            return raw
        sign_marker = (match.group("sign") or "").strip()
        sign = -1 if sign_marker in {"▲", "△", "-", "−"} else 1
        sen = _parse_decimal(match.group("sen") or "")
        if sen is None:
            return raw
        k_value = sen * Decimal(sign)
        formatted = _format_number_with_commas(k_value)
        unit = (match.group("unit") or "").strip()
        suffix = " yen" if unit == "円" else (" units" if unit == "台" else "")
        if sign < 0:
            return f"({formatted.lstrip('-')}k{suffix})"
        return f"{formatted}k{suffix}"

    fixed = _RE_JP_OKU_CHOU_AMOUNT.sub(repl_oku_chou, text)
    fixed = _RE_JP_MAN_SEN_AMOUNT.sub(repl_man_sen, fixed)
    fixed = _RE_JP_SEN_AMOUNT.sub(repl_sen, fixed)
    return fixed


def _pre_normalize_numeric_units(text: str, *, output_language: OutputLanguage) -> str:
    if output_language == "en":
        return _normalize_jp_units_to_english(text)
    return _normalize_en_units_to_japanese(text)


def _build_translategemma_messages(
    text: str, *, output_language: OutputLanguage
) -> list[dict[str, object]]:
    source, target = _translategemma_lang_codes(output_language)
    text = _pre_normalize_numeric_units(text, output_language=output_language)
    return [
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "source_lang_code": source,
                    "target_lang_code": target,
                    "text": text,
                }
            ],
        }
    ]


@dataclass(frozen=True)
class TranslationConfig:
    gguf_repo_id: str
    gguf_filename: str
    max_new_tokens: int
    n_ctx: int
    n_gpu_layers: int
    temperature: float
    allow_cpu: bool


def default_config() -> TranslationConfig:
    return TranslationConfig(
        gguf_repo_id=os.environ.get(
            "YAKULINGO_SPACES_GGUF_REPO_ID",
            "mradermacher/translategemma-27b-it-i1-GGUF",
        ),
        gguf_filename=os.environ.get(
            "YAKULINGO_SPACES_GGUF_FILENAME", "translategemma-27b-it.i1-Q4_K_M.gguf"
        ),
        max_new_tokens=_env_int("YAKULINGO_SPACES_MAX_NEW_TOKENS", 1024),
        n_ctx=_env_int("YAKULINGO_SPACES_N_CTX", 4096),
        n_gpu_layers=_env_int("YAKULINGO_SPACES_N_GPU_LAYERS", -1),
        temperature=_env_float("YAKULINGO_SPACES_TEMPERATURE", 0.0),
        allow_cpu=_env_bool("YAKULINGO_SPACES_ALLOW_CPU", False),
    )


@dataclass(frozen=True)
class _LlamaAsset:
    tag: str
    name: str
    url: str


@dataclass
class _LlamaServerRuntime:
    exe_path: Path
    base_url: str
    model_id: str
    process: subprocess.Popen[bytes]
    log_path: Path
    log_handle: object
    asset_name: str


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _bundled_llama_server_path() -> Path | None:
    root = _repo_root()
    candidates = [
        root / "local_ai" / "llama_cpp" / "vulkan" / "llama-server.exe",
        root / "local_ai" / "llama_cpp" / "avx2" / "llama-server.exe",
        root / "local_ai" / "llama_cpp" / "generic" / "llama-server.exe",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _cache_base_dir() -> Path:
    hf_home = (os.environ.get("HF_HOME") or "").strip()
    if hf_home:
        return Path(hf_home) / "yakulingo"
    return Path.home() / ".cache" / "huggingface" / "yakulingo"


def _github_get_json(url: str, *, timeout_s: int) -> object:
    req = Request(url, headers={"User-Agent": "yakulingo-spaces"})
    with urlopen(req, timeout=timeout_s) as resp:
        body = resp.read()
    return json.loads(body.decode("utf-8"))


def _resolve_llama_asset() -> _LlamaAsset:
    direct_url = (os.environ.get("YAKULINGO_SPACES_LLAMA_CPP_URL") or "").strip()
    if direct_url:
        return _LlamaAsset(tag="custom", name=Path(direct_url).name, url=direct_url)

    repo = _env_str("YAKULINGO_SPACES_LLAMA_CPP_REPO", _DEFAULT_LLAMA_CPP_REPO)
    suffix = _env_str(
        "YAKULINGO_SPACES_LLAMA_CPP_ASSET_SUFFIX", _DEFAULT_LLAMA_CPP_ASSET_SUFFIX
    )

    data = _github_get_json(
        f"https://api.github.com/repos/{repo}/releases/latest",
        timeout_s=_DEFAULT_HTTP_TIMEOUT_S,
    )
    if not isinstance(data, dict):
        raise RuntimeError("llama.cpp の GitHub Release 情報の取得に失敗しました。")

    tag = str(data.get("tag_name") or "").strip()
    if not tag:
        raise RuntimeError("llama.cpp の release tag が取得できませんでした。")

    assets = data.get("assets")
    if not isinstance(assets, list):
        raise RuntimeError("llama.cpp の assets 情報が取得できませんでした。")

    wanted_suffix = suffix.lower()
    best: tuple[str, str] | None = None
    names: list[str] = []
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        name = str(asset.get("name") or "").strip()
        url = str(asset.get("browser_download_url") or "").strip()
        if not name or not url:
            continue
        names.append(name)
        if name.lower().endswith(wanted_suffix):
            best = (name, url)
            break

    if best is None:
        joined = ", ".join(names[:25])
        more = "" if len(names) <= 25 else f" …(+{len(names) - 25})"
        raise RuntimeError(
            "llama.cpp の事前ビルド済みバイナリが見つかりません。"
            f"（repo={repo}, tag={tag}, suffix={suffix}）\n"
            f"利用可能な assets: {joined}{more}\n"
            "ヒント: `YAKULINGO_SPACES_LLAMA_CPP_ASSET_SUFFIX` を見直すか、"
            "`YAKULINGO_SPACES_LLAMA_CPP_URL` を直接指定してください。"
        )

    name, url = best
    return _LlamaAsset(tag=tag, name=name, url=url)


def _strip_archive_suffix(name: str) -> str:
    lowered = name.lower()
    if lowered.endswith(".tar.gz"):
        return name[: -len(".tar.gz")]
    if lowered.endswith(".tgz"):
        return name[: -len(".tgz")]
    if lowered.endswith(".zip"):
        return name[: -len(".zip")]
    return Path(name).stem


def _ensure_executable(path: Path) -> None:
    try:
        path.chmod(path.stat().st_mode | 0o111)
    except Exception:
        return


def _download_url(url: str, dest_path: Path, *, timeout_s: int) -> None:
    tmp_path = dest_path.with_name(dest_path.name + ".partial")
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        req = Request(url, headers={"User-Agent": "yakulingo-spaces"})
        with urlopen(req, timeout=timeout_s) as resp, open(tmp_path, "wb") as f:
            shutil.copyfileobj(resp, f)
        tmp_path.replace(dest_path)
    finally:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except Exception:
            pass


def _validate_relpath(name: str) -> None:
    p = Path(name)
    if p.is_absolute() or any(part == ".." for part in p.parts):
        raise RuntimeError(f"アーカイブに危険なパスが含まれています: {name}")


def _extract_archive(archive_path: Path, dest_dir: Path) -> None:
    name = archive_path.name.lower()
    if name.endswith(".zip"):
        with zipfile.ZipFile(archive_path) as zf:
            for info in zf.infolist():
                _validate_relpath(info.filename)
            zf.extractall(dest_dir)
        return

    with tarfile.open(archive_path, "r:*") as tf:
        for member in tf.getmembers():
            _validate_relpath(member.name)
        tf.extractall(dest_dir)


def _find_llama_server(root: Path) -> Path | None:
    if not root.exists():
        return None
    for filename in ("llama-server", "llama-server.exe"):
        for candidate in root.rglob(filename):
            if candidate.is_file():
                return candidate
    return None


def _llama_server_override_path() -> Path | None:
    raw = (os.environ.get("YAKULINGO_SPACES_LLAMA_SERVER_PATH") or "").strip()
    if not raw:
        return None
    path = Path(raw)
    if path.exists():
        return path
    raise RuntimeError(f"YAKULINGO_SPACES_LLAMA_SERVER_PATH が存在しません: {path}")


def _ensure_llama_server_binary() -> tuple[Path, str]:
    override = _llama_server_override_path()
    if override is not None:
        _ensure_executable(override)
        return override, override.name

    if os.name == "nt":
        bundled = _bundled_llama_server_path()
        if bundled is not None:
            _ensure_executable(bundled)
            return bundled, bundled.name

    asset = _resolve_llama_asset()
    repo = _env_str("YAKULINGO_SPACES_LLAMA_CPP_REPO", _DEFAULT_LLAMA_CPP_REPO)
    repo_dir = repo.replace("/", "__").replace("\\", "__")
    base_dir = _cache_base_dir() / "llama_cpp" / repo_dir / asset.tag

    extract_dir = base_dir / _strip_archive_suffix(asset.name)
    existing = _find_llama_server(extract_dir)
    if existing is not None:
        _ensure_executable(existing)
        return existing, asset.name

    archive_path = base_dir / asset.name
    if not archive_path.exists():
        _download_url(asset.url, archive_path, timeout_s=_DEFAULT_HTTP_TIMEOUT_S)

    staging_dir = extract_dir.with_name(extract_dir.name + "._staging")
    if staging_dir.exists():
        shutil.rmtree(staging_dir, ignore_errors=True)
    staging_dir.mkdir(parents=True, exist_ok=True)

    try:
        _extract_archive(archive_path, staging_dir)
        found = _find_llama_server(staging_dir)
        if found is None:
            raise RuntimeError(
                f"llama.cpp アーカイブ内に llama-server が見つかりません: {asset.name}"
            )
        _ensure_executable(found)

        if extract_dir.exists():
            shutil.rmtree(extract_dir, ignore_errors=True)
        staging_dir.replace(extract_dir)
    finally:
        if staging_dir.exists():
            shutil.rmtree(staging_dir, ignore_errors=True)

    resolved = _find_llama_server(extract_dir)
    if resolved is None:
        raise RuntimeError(f"llama-server の展開に失敗しました: {asset.name}")
    _ensure_executable(resolved)
    return resolved, asset.name


def _llama_server_host() -> str:
    return _env_str("YAKULINGO_SPACES_LLAMA_SERVER_HOST", _DEFAULT_LLAMA_SERVER_HOST)


def _llama_server_port() -> int:
    return _env_int("YAKULINGO_SPACES_LLAMA_SERVER_PORT", _DEFAULT_LLAMA_SERVER_PORT)


def _llama_server_startup_timeout_s() -> int:
    return _env_int(
        "YAKULINGO_SPACES_LLAMA_SERVER_STARTUP_TIMEOUT",
        _DEFAULT_LLAMA_SERVER_STARTUP_TIMEOUT_S,
    )


def _llama_server_log_path() -> Path:
    base = _cache_base_dir() / "spaces"
    base.mkdir(parents=True, exist_ok=True)
    return base / "llama_server.log"


def _read_tail_text(path: Path, *, max_bytes: int) -> str:
    if max_bytes <= 0:
        return ""
    try:
        if not path.exists():
            return ""
        size = path.stat().st_size
        offset = max(0, int(size) - int(max_bytes))
        with open(path, "rb") as f:
            f.seek(offset)
            data = f.read()
        text = data.decode("utf-8", errors="replace")
        if offset > 0:
            nl = text.find("\n")
            if nl != -1:
                text = text[nl + 1 :]
        return text
    except Exception:
        return ""


def _get_help_text(exe_path: Path) -> str:
    try:
        proc = subprocess.run(
            [str(exe_path), "--help"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except Exception:
        return ""
    return (proc.stdout or "") + "\n" + (proc.stderr or "")


def _help_has_long(help_text: str, flag: str) -> bool:
    return bool(help_text) and flag in help_text


def _help_has_short(help_text: str, flag: str) -> bool:
    if not help_text or not flag.startswith("-") or flag.startswith("--"):
        return False
    return bool(re.search(rf"(?m)^\s*{re.escape(flag)}(?:,|\s)", help_text))


def _infer_device_from_asset(asset_name: str) -> str | None:
    lowered = (asset_name or "").strip().lower()
    if not lowered:
        return None
    if "vulkan" in lowered:
        return "vulkan"
    if "cuda" in lowered:
        return "cuda"
    if "hip" in lowered:
        return "hip"
    if "opencl" in lowered:
        return "opencl"
    if "sycl" in lowered:
        return "sycl"
    return None


def _find_llama_cli_exe(server_exe_path: Path) -> Path | None:
    candidates = [
        server_exe_path.with_name("llama-cli.exe"),
        server_exe_path.with_name("llama-cli"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _parse_llama_cli_devices(text: str) -> list[str]:
    lines = (text or "").splitlines()
    devices: list[str] = []
    seen: set[str] = set()
    in_section = False
    section_found = False

    for line in lines:
        if not in_section:
            if _RE_LLAMA_CLI_AVAILABLE_DEVICES_HEADER.match(line):
                in_section = True
                section_found = True
            continue

        match = _RE_LLAMA_CLI_DEVICE_LINE.match(line)
        if not match:
            continue
        name = match.group("name").strip()
        if not name:
            continue
        key = name.lower()
        if key in seen:
            continue
        devices.append(name)
        seen.add(key)

    if section_found:
        return devices

    for line in lines:
        match = _RE_LLAMA_CLI_DEVICE_LINE.match(line)
        if not match:
            continue
        name = match.group("name").strip()
        if not name:
            continue
        key = name.lower()
        if key in seen:
            continue
        devices.append(name)
        seen.add(key)

    return devices


def _select_default_llama_device(asset_name: str, devices: list[str]) -> str | None:
    if not devices:
        return None
    lowered_asset = (asset_name or "").strip().lower()
    if "vulkan" in lowered_asset:
        for dev in devices:
            if dev.lower().startswith("vulkan"):
                return dev
        return None
    if "cuda" in lowered_asset:
        for dev in devices:
            if dev.lower().startswith("cuda"):
                return dev
        return None
    return devices[0]


def _resolve_llama_device_auto(server_exe_path: Path, asset_name: str) -> str | None:
    llama_cli_path = _find_llama_cli_exe(server_exe_path)
    if llama_cli_path is None:
        return None
    try:
        completed = subprocess.run(
            [str(llama_cli_path), "--list-devices"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=2.0,
            check=False,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except Exception:
        return None
    output = completed.stdout or ""
    devices = _parse_llama_cli_devices(output)
    return _select_default_llama_device(asset_name, devices)


def _build_llama_server_args(
    *,
    exe_path: Path,
    model_path: str,
    host: str,
    port: int,
    n_ctx: int,
    n_gpu_layers: int,
    use_cuda: bool,
    asset_name: str,
) -> list[str]:
    help_text = _get_help_text(exe_path)

    args: list[str] = [str(exe_path), "--host", host, "--port", str(port)]

    if _help_has_short(help_text, "-m"):
        args += ["-m", model_path]
    elif _help_has_long(help_text, "--model"):
        args += ["--model", model_path]
    else:
        args += ["-m", model_path]

    ctx = max(256, int(n_ctx))
    if _help_has_long(help_text, "--ctx-size"):
        args += ["--ctx-size", str(ctx)]
    elif _help_has_short(help_text, "-c"):
        args += ["-c", str(ctx)]

    if _help_has_long(help_text, "--device"):
        if use_cuda:
            device = (os.environ.get("YAKULINGO_SPACES_LLAMA_DEVICE") or "").strip()
            if not device or device.lower() == "auto":
                device = _resolve_llama_device_auto(exe_path, asset_name) or ""
            if not device:
                raise RuntimeError(
                    "llama.cpp の GPU デバイスが見つかりません（--list-devices が空）。"
                    "Vulkan 版バイナリの場合、ZeroGPU 環境では Vulkan デバイスが見つからないことがあります。"
                    "CPU で動かす場合は `YAKULINGO_SPACES_N_GPU_LAYERS=0` を設定してください。"
                )
            args += ["--device", device]
        else:
            args += ["--device", "none"]

    ngl_flag: str | None = None
    if _help_has_long(help_text, "--n-gpu-layers"):
        ngl_flag = "--n-gpu-layers"
    elif _help_has_short(help_text, "-ngl"):
        ngl_flag = "-ngl"

    if ngl_flag:
        ngl_value = int(n_gpu_layers)
        if use_cuda:
            if ngl_value < 0:
                ngl_value = _AUTO_N_GPU_LAYERS
        else:
            ngl_value = 0
        args += [ngl_flag, str(ngl_value)]

    return args


def _http_json(
    *,
    method: str,
    url: str,
    body: dict | None,
    timeout_s: int,
    headers: dict[str, str] | None = None,
) -> object:
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if headers:
        for key, value in headers.items():
            req.add_header(str(key), str(value))
    with urlopen(req, timeout=timeout_s) as resp:
        payload = resp.read()
    return json.loads(payload.decode("utf-8"))


def _probe_openai_model_id(base_url: str) -> str | None:
    data = _http_json(
        method="GET", url=f"{base_url}/v1/models", body=None, timeout_s=5, headers=None
    )
    if not isinstance(data, dict):
        return None
    items = data.get("data")
    if not isinstance(items, list) or not items:
        return None
    first = items[0]
    if not isinstance(first, dict):
        return None
    model_id = first.get("id")
    if model_id is None:
        return None
    return str(model_id)


def _wait_for_llama_server(
    *, base_url: str, process: subprocess.Popen[bytes], timeout_s: int
) -> str:
    deadline = time.monotonic() + max(1, int(timeout_s))
    last_error: str | None = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"llama-server が終了しました（exit_code={process.returncode}）。")
        try:
            model_id = _probe_openai_model_id(base_url)
            if model_id:
                return model_id
        except (HTTPError, URLError, TimeoutError) as e:
            last_error = str(e)
        except Exception as e:
            last_error = str(e)
        time.sleep(0.4)
    raise RuntimeError(
        f"llama-server の起動がタイムアウトしました（timeout={timeout_s}s）。"
        + (f" 最後のエラー: {last_error}" if last_error else "")
    )


def _openai_completions(
    *,
    base_url: str,
    model_id: str,
    prompt: str,
    max_tokens: int,
    temperature: float,
) -> str:
    payload = {
        "model": model_id,
        "prompt": prompt,
        "max_tokens": int(max_tokens),
        "temperature": float(temperature),
        "top_p": 1.0,
        "stop": ["<end_of_turn>"],
        "stream": False,
    }
    data = _http_json(
        method="POST",
        url=f"{base_url}/v1/completions",
        body=payload,
        timeout_s=60,
        headers=None,
    )
    return _extract_llama_text(data)


class PlamoTranslator:
    def backend_label(self) -> str:
        return "plamo"

    def engine_label(self) -> str:
        return "chat-completions"

    def quant_label(self) -> str:
        return "api"

    def runtime_device(self) -> str:
        return "remote"

    def translate(self, text: str, *, output_language: OutputLanguage) -> str:
        cleaned = (text or "").strip()
        if not cleaned:
            return ""

        cleaned = _pre_normalize_numeric_units(cleaned, output_language=output_language)

        api_key = (os.environ.get("YAKULINGO_SPACES_PLAMO_API_KEY") or "").strip()
        if not api_key:
            api_key = (os.environ.get("PLAMO_API_KEY") or "").strip()
        if not api_key:
            raise RuntimeError(
                "PLaMo API キーが未設定です（Secrets に YAKULINGO_SPACES_PLAMO_API_KEY を設定してください）。"
            )

        base_url = _env_str(
            "YAKULINGO_SPACES_PLAMO_BASE_URL",
            "https://platform.preferredai.jp/api/completion/v1",
        ).rstrip("/")
        model = _env_str("YAKULINGO_SPACES_PLAMO_MODEL", "plamo-2.2-prime")
        temperature = float(_env_float("YAKULINGO_SPACES_PLAMO_TEMPERATURE", 0.0))
        max_tokens = max(1, int(_env_int("YAKULINGO_SPACES_PLAMO_MAX_TOKENS", 1024)))
        timeout_s = max(
            1,
            int(_env_int("YAKULINGO_SPACES_PLAMO_TIMEOUT_S", _DEFAULT_HTTP_TIMEOUT_S)),
        )
        max_retries = max(0, int(_env_int("YAKULINGO_SPACES_PLAMO_MAX_RETRIES", 2)))

        prompt = _build_prompt(cleaned, output_language=output_language).strip()
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": "You are a translation engine. Output the translation only.",
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }

        headers = {"Authorization": f"Bearer {api_key}"}
        last_error: Exception | None = None
        for attempt in range(max_retries + 1):
            try:
                data = _http_json(
                    method="POST",
                    url=f"{base_url}/chat/completions",
                    body=payload,
                    timeout_s=timeout_s,
                    headers=headers,
                )
                content = _extract_chat_completion_content(data)
                return _clean_translation_output(content)
            except HTTPError as e:
                last_error = e
                detail = _read_http_error_body(e)
                status = getattr(e, "code", None)
                raise RuntimeError(
                    _format_plamo_http_error(status=status, detail=detail)
                ) from e
            except (URLError, TimeoutError) as e:
                last_error = e
                if attempt >= max_retries:
                    raise RuntimeError(f"PLaMo API に接続できません: {e}") from e
                time.sleep(0.5 * (attempt + 1))
            except Exception as e:
                last_error = e
                raise RuntimeError(f"PLaMo API の呼び出しに失敗しました: {e}") from e

        raise RuntimeError(f"PLaMo API の呼び出しに失敗しました: {last_error}")


def _read_http_error_body(error: HTTPError) -> str | None:
    try:
        raw = error.read()
    except Exception:
        return None
    if not raw:
        return None
    try:
        return raw.decode("utf-8", errors="replace")
    except Exception:
        return None


def _extract_chat_completion_content(data: object) -> str:
    if isinstance(data, dict):
        choices = data.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0]
            if isinstance(first, dict):
                message = first.get("message")
                if isinstance(message, dict):
                    content = message.get("content")
                    if content is not None:
                        return str(content)
                content = first.get("text")
                if content is not None:
                    return str(content)
    return str(data or "")


def _format_plamo_http_error(*, status: int | None, detail: str | None) -> str:
    base = "PLaMo API がエラーを返しました"
    if status is None:
        return base
    if status == 401:
        return f"{base}（401: 認証失敗）。API キーを確認してください。"
    if status == 403:
        return f"{base}（403: アクセス拒否）。プロジェクト/権限を確認してください。"
    if status == 429:
        return f"{base}（429: レート制限）。時間をおいて再試行してください。"
    if status >= 500:
        return f"{base}（{status}: サーバー側エラー）。時間をおいて再試行してください。"
    if detail:
        return f"{base}（{status}）。詳細: {detail}"
    return f"{base}（{status}）。"

class GGUFTranslator:
    def __init__(self, config: TranslationConfig | None = None) -> None:
        self._config = config or default_config()
        self._lock = threading.Lock()
        self._runtime: _LlamaServerRuntime | None = None
        self._device: str | None = None

    def _dispose_runtime(self) -> None:
        runtime = self._runtime
        self._runtime = None
        if runtime is None:
            return

        try:
            close = getattr(runtime.log_handle, "close", None)
            if callable(close):
                close()
        except Exception:
            pass

    def runtime_device(self) -> str:
        if self._device:
            return self._device
        if _cuda_visible() and self._config.n_gpu_layers != 0:
            return "cuda"
        return "cpu"

    def backend_label(self) -> str:
        return "gguf"

    def engine_label(self) -> str:
        return "llama-server"

    def quant_label(self) -> str:
        match = re.search(r"-(Q[^.]+)\.gguf$", self._config.gguf_filename, re.IGNORECASE)
        return match.group(1) if match else "unknown"

    def translate(self, text: str, *, output_language: OutputLanguage) -> str:
        cleaned = (text or "").strip()
        if not cleaned:
            return ""

        cleaned = _pre_normalize_numeric_units(cleaned, output_language=output_language)
        max_new_tokens = max(1, int(self._config.max_new_tokens))
        prompt = _build_gguf_prompt(cleaned, output_language=output_language)
        runtime = self._get_runtime()

        try:
            generated = _openai_completions(
                base_url=runtime.base_url,
                model_id=runtime.model_id,
                prompt=prompt,
                max_tokens=max_new_tokens,
                temperature=float(self._config.temperature),
            )
        except Exception as e:
            raise RuntimeError(
                f"翻訳に失敗しました（backend=gguf/llama.cpp/llama-server, device={self.runtime_device()}）: {e}"
            ) from e

        return _clean_translation_output(generated)

    def _get_runtime(self) -> _LlamaServerRuntime:
        if self._runtime is not None and self._runtime.process.poll() is None:
            return self._runtime
        self._dispose_runtime()

        with self._lock:
            if self._runtime is not None and self._runtime.process.poll() is None:
                return self._runtime
            self._dispose_runtime()

            hf_token = _hf_token()

            try:
                from huggingface_hub import (  # type: ignore[import-not-found]
                    hf_hub_download,
                )
            except ModuleNotFoundError as e:
                raise RuntimeError(
                    "Spaces 用の依存関係が不足しています。"
                    "（例: pip install -r spaces/requirements.txt）"
                ) from e

            cuda_visible = _cuda_visible()
            gpu_requested = int(self._config.n_gpu_layers) != 0
            use_cuda = cuda_visible and gpu_requested
            if gpu_requested and not cuda_visible and not self._config.allow_cpu:
                raise RuntimeError(
                    "GPU が利用できません（ZeroGPU が割り当てられていない可能性があります）。"
                    "Space の Hardware を ZeroGPU に設定してください。"
                    "（デバッグ用途で CPU を許可する場合は YAKULINGO_SPACES_ALLOW_CPU=1、"
                    "または YAKULINGO_SPACES_N_GPU_LAYERS=0）"
                )

            gguf_path = hf_hub_download(
                repo_id=self._config.gguf_repo_id,
                filename=self._config.gguf_filename,
                token=hf_token,
            )

            exe_path, asset_name = _ensure_llama_server_binary()
            host = _llama_server_host()
            port = _llama_server_port()
            base_url = f"http://{host}:{port}"
            n_gpu_layers = int(self._config.n_gpu_layers)

            args = _build_llama_server_args(
                exe_path=exe_path,
                model_path=str(gguf_path),
                host=host,
                port=port,
                n_ctx=int(self._config.n_ctx),
                n_gpu_layers=n_gpu_layers,
                use_cuda=use_cuda,
                asset_name=asset_name,
            )

            log_path = _llama_server_log_path()
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_handle = open(log_path, "ab")
            try:
                process = subprocess.Popen(  # noqa: S603
                    args,
                    stdout=log_handle,
                    stderr=subprocess.STDOUT,
                )
            except Exception:
                try:
                    log_handle.close()
                except Exception:
                    pass
                raise

            try:
                model_id = _wait_for_llama_server(
                    base_url=base_url,
                    process=process,
                    timeout_s=_llama_server_startup_timeout_s(),
                )
            except Exception as e:
                try:
                    process.terminate()
                except Exception:
                    pass
                try:
                    log_handle.close()
                except Exception:
                    pass
                tail = _read_tail_text(log_path, max_bytes=32_000).strip()
                if tail:
                    raise RuntimeError(
                        f"llama-server の起動に失敗しました: {e}\n\n直近のログ:\n\n{tail}"
                    ) from e
                raise

            self._device = "cuda" if use_cuda else "cpu"
            runtime = _LlamaServerRuntime(
                exe_path=exe_path,
                base_url=base_url,
                model_id=model_id,
                process=process,
                log_path=log_path,
                log_handle=log_handle,
                asset_name=asset_name,
            )
            self._runtime = runtime
            return runtime


class LlamaCppPythonTranslator:
    def __init__(self, config: TranslationConfig | None = None) -> None:
        self._config = config or default_config()
        self._lock = threading.Lock()
        self._llama: object | None = None
        self._device: str | None = None

    def backend_label(self) -> str:
        return "gguf"

    def engine_label(self) -> str:
        return "llama-cpp-python"

    def quant_label(self) -> str:
        match = re.search(r"-(Q[^.]+)\.gguf$", self._config.gguf_filename, re.IGNORECASE)
        return match.group(1) if match else "unknown"

    def runtime_device(self) -> str:
        if self._device:
            return self._device
        if _cuda_visible() and self._config.n_gpu_layers != 0:
            return "cuda"
        return "cpu"

    def translate(self, text: str, *, output_language: OutputLanguage) -> str:
        cleaned = (text or "").strip()
        if not cleaned:
            return ""

        if not _cuda_visible() and not self._config.allow_cpu:
            raise RuntimeError(
                "GPU 縺悟茜逕ｨ縺ｧ縺阪∪縺帙ｓ・・eroGPU 縺悟牡繧雁ｽ薙※繧峨ｌ縺ｦ縺・↑縺・庄閭ｽ諤ｧ縺後≠繧翫∪縺呻ｼ峨・"
                "Space 縺ｮ Hardware 繧・ZeroGPU 縺ｫ險ｭ螳壹＠縺ｦ縺上□縺輔＞縲・"
                "・医ョ繝舌ャ繧ｰ逕ｨ騾斐〒 CPU 繧定ｨｱ蜿ｯ縺吶ｋ蝣ｴ蜷医・ YAKULINGO_SPACES_ALLOW_CPU=1・峨・"
            )

        cleaned = _pre_normalize_numeric_units(cleaned, output_language=output_language)
        prompt = _build_gguf_prompt(cleaned, output_language=output_language)
        max_new_tokens = max(1, int(self._config.max_new_tokens))
        temperature = float(self._config.temperature)

        llama = self._get_llama()
        try:
            create_completion = getattr(llama, "create_completion", None)
            if not callable(create_completion):
                raise RuntimeError("llama-cpp-python の API が想定と異なります（create_completion がありません）")

            data = create_completion(  # type: ignore[call-arg]
                prompt=prompt,
                max_tokens=max_new_tokens,
                temperature=temperature,
                top_p=1.0,
                stop=["<end_of_turn>"],
                stream=False,
            )
            generated = _extract_llama_text(data)
        except Exception as e:
            raise RuntimeError(
                f"鄙ｻ險ｳ縺ｫ螟ｱ謨励＠縺ｾ縺励◆・・ackend=gguf/llama-cpp-python, device={self.runtime_device()}・・ {e}"
            ) from e

        return _clean_translation_output(generated)

    def _get_llama(self) -> object:
        if self._llama is not None:
            return self._llama

        with self._lock:
            if self._llama is not None:
                return self._llama

            hf_token = _hf_token()
            try:
                from huggingface_hub import (  # type: ignore[import-not-found]
                    hf_hub_download,
                )
            except ModuleNotFoundError as e:
                raise RuntimeError(
                    "huggingface-hub 縺瑚ｦ九▽縺九ｊ縺ｾ縺帙ｓ・・paces 縺ｮ萓晏ｭ倬未菫ゅｒ遒ｺ隱阪＠縺ｦ縺上□縺輔＞・峨・"
                ) from e

            try:
                import llama_cpp  # type: ignore[import-not-found]
            except ModuleNotFoundError as e:
                raise RuntimeError(
                    "llama-cpp-python 縺瑚ｦ九▽縺九ｊ縺ｾ縺帙ｓ・・paces 縺ｮ requirements.txt 縺ｫ CUDA 瀵・譛ｬ繝薙Ν繝峨・ wheel 繧定ｿｽ蜉縺励※縺上□縺輔＞・峨・"
                    "・亥屓驕ｿ: --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cu124・峨・"
                ) from e

            gguf_path = hf_hub_download(
                repo_id=self._config.gguf_repo_id,
                filename=self._config.gguf_filename,
                token=hf_token,
            )

            ctx = max(256, int(self._config.n_ctx))
            ngl = int(self._config.n_gpu_layers)
            if ngl < 0:
                ngl = _AUTO_N_GPU_LAYERS
            if not _cuda_visible():
                ngl = 0

            Llama = getattr(llama_cpp, "Llama", None)
            if not callable(Llama):
                raise RuntimeError("llama-cpp-python の Llama クラスが見つかりません")

            llama = Llama(  # type: ignore[call-arg]
                model_path=str(gguf_path),
                n_ctx=ctx,
                n_gpu_layers=ngl,
                verbose=False,
            )
            self._llama = llama
            self._device = "cuda" if _cuda_visible() and ngl != 0 else "cpu"
            return llama


class TransformersTranslator:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._model: object | None = None
        self._tokenizer: object | None = None
        self._processor: object | None = None
        self._model_id: str | None = None
        self._device: str | None = None

    def backend_label(self) -> str:
        return "transformers"

    def quant_label(self) -> str:
        return "4bit" if _env_bool("YAKULINGO_SPACES_HF_LOAD_IN_4BIT", True) else "bf16"

    def runtime_device(self) -> str:
        if self._device:
            return self._device
        return "cuda" if _cuda_visible() else "cpu"

    def translate(self, text: str, *, output_language: OutputLanguage) -> str:
        cleaned = (text or "").strip()
        if not cleaned:
            return ""

        cleaned = _pre_normalize_numeric_units(cleaned, output_language=output_language)
        if not _cuda_visible() and not _env_bool("YAKULINGO_SPACES_ALLOW_CPU", False):
            raise RuntimeError(
                "GPU が利用できません（ZeroGPU が割り当てられていない可能性があります）。"
                "Space の Hardware を ZeroGPU に設定してください。"
            )

        model_id = _env_str("YAKULINGO_SPACES_HF_MODEL_ID", "google/translategemma-27b-it")
        if _is_translategemma_model_id(model_id):
            return self._translate_translategemma(cleaned, output_language=output_language)

        prompt = _build_prompt(cleaned, output_language=output_language)
        max_new_tokens = max(1, int(_env_int("YAKULINGO_SPACES_MAX_NEW_TOKENS", 1024)))
        temperature = float(_env_float("YAKULINGO_SPACES_TEMPERATURE", 0.0))

        model, tokenizer = self._get_model_and_tokenizer(model_id=model_id)

        try:
            import torch  # type: ignore[import-not-found]
        except ModuleNotFoundError as e:
            raise RuntimeError("torch が見つかりません（Spaces の依存関係を確認してください）。") from e

        do_sample = temperature > 0.0
        prompt_text = self._format_chat_prompt(tokenizer, prompt)

        inputs = tokenizer(prompt_text, return_tensors="pt")  # type: ignore[operator]
        input_ids = inputs["input_ids"]
        attention_mask = inputs.get("attention_mask")

        device = "cuda" if torch.cuda.is_available() and _cuda_visible() else "cpu"
        if device == "cuda":
            input_ids = input_ids.to("cuda")
            if attention_mask is not None:
                attention_mask = attention_mask.to("cuda")

        pad_token_id = getattr(tokenizer, "pad_token_id", None)
        eos_token_id = getattr(tokenizer, "eos_token_id", None)
        if pad_token_id is None and eos_token_id is not None:
            pad_token_id = eos_token_id

        kwargs: dict[str, object] = {
            "input_ids": input_ids,
            "max_new_tokens": max_new_tokens,
            "do_sample": do_sample,
            "top_p": 1.0,
        }
        if attention_mask is not None:
            kwargs["attention_mask"] = attention_mask
        if pad_token_id is not None:
            kwargs["pad_token_id"] = pad_token_id
        if eos_token_id is not None:
            kwargs["eos_token_id"] = eos_token_id
        if do_sample:
            kwargs["temperature"] = temperature

        gen = model.generate(**kwargs)  # type: ignore[operator]
        generated_ids = gen[0][input_ids.shape[-1] :]

        out = tokenizer.decode(generated_ids, skip_special_tokens=True)  # type: ignore[operator]
        self._device = "cuda" if device == "cuda" else "cpu"
        return _clean_translation_output(out)

    def _format_chat_prompt(self, tokenizer: object, prompt: str) -> str:
        apply = getattr(tokenizer, "apply_chat_template", None)
        if callable(apply):
            try:
                return apply(  # type: ignore[operator]
                    [{"role": "user", "content": prompt}],
                    tokenize=False,
                    add_generation_prompt=True,
                )
            except Exception:
                pass
        return f"<bos><start_of_turn>user\n{prompt}<end_of_turn>\n<start_of_turn>model\n"

    def _translate_translategemma(self, text: str, *, output_language: OutputLanguage) -> str:
        max_new_tokens = max(1, int(_env_int("YAKULINGO_SPACES_MAX_NEW_TOKENS", 1024)))
        temperature = float(_env_float("YAKULINGO_SPACES_TEMPERATURE", 0.0))
        do_sample = temperature > 0.0
        model_id = _env_str("YAKULINGO_SPACES_HF_MODEL_ID", "google/translategemma-27b-it")

        model, processor = self._get_translategemma_model_and_processor(model_id=model_id)
        messages = _build_translategemma_messages(text, output_language=output_language)

        try:
            import torch  # type: ignore[import-not-found]
        except ModuleNotFoundError as e:
            raise RuntimeError("torch が見つかりません（Spaces の依存関係を確認してください）。") from e

        apply = getattr(processor, "apply_chat_template", None)
        if not callable(apply):
            raise RuntimeError("TranslateGemma の chat template を適用できません（apply_chat_template がありません）。")

        inputs = apply(  # type: ignore[operator]
            messages,
            tokenize=True,
            add_generation_prompt=True,
            return_dict=True,
            return_tensors="pt",
        )
        to = getattr(inputs, "to", None)
        if callable(to):
            try:
                inputs = to(getattr(model, "device", None), dtype=torch.bfloat16)
            except Exception:
                try:
                    inputs = to(getattr(model, "device", None))
                except Exception:
                    pass

        input_ids = inputs["input_ids"]  # type: ignore[index]
        input_len = int(input_ids.shape[-1])

        kwargs: dict[str, object] = {
            **inputs,  # type: ignore[arg-type]
            "max_new_tokens": max_new_tokens,
            "do_sample": do_sample,
        }
        if do_sample:
            kwargs["temperature"] = temperature
            kwargs["top_p"] = 1.0

        gen = model.generate(**kwargs)  # type: ignore[operator]
        generated_ids = gen[0][input_len:]

        decode = getattr(processor, "decode", None)
        if not callable(decode):
            raise RuntimeError("TranslateGemma の decode が利用できません。")
        out = decode(generated_ids, skip_special_tokens=True)  # type: ignore[operator]

        self._device = "cuda" if _cuda_visible() else "cpu"
        return _clean_translation_output(out)

    def _get_model_and_tokenizer(self, *, model_id: str) -> tuple[object, object]:
        if self._model is not None and self._tokenizer is not None:
            return self._model, self._tokenizer

        with self._lock:
            if self._model is not None and self._tokenizer is not None:
                return self._model, self._tokenizer

            revision = (os.environ.get("YAKULINGO_SPACES_HF_REVISION") or "").strip() or None
            load_in_4bit = _env_bool("YAKULINGO_SPACES_HF_LOAD_IN_4BIT", True)
            hf_token = _hf_token()

            try:
                from transformers import (  # type: ignore[import-not-found]
                    AutoModelForCausalLM,
                    AutoTokenizer,
                )
            except ModuleNotFoundError as e:
                raise RuntimeError(
                    "transformers が見つかりません（Spaces の依存関係を確認してください）。"
                ) from e

            quant_config = None
            if load_in_4bit:
                try:
                    import torch  # type: ignore[import-not-found]
                    from transformers import BitsAndBytesConfig  # type: ignore[import-not-found]
                    import bitsandbytes  # noqa: F401
                except ModuleNotFoundError as e:
                    raise RuntimeError(
                        "4bit 量子化の依存関係（bitsandbytes）が不足しています。"
                        "（回避: `YAKULINGO_SPACES_HF_LOAD_IN_4BIT=0`）"
                    ) from e
                quant_config = BitsAndBytesConfig(
                    load_in_4bit=True,
                    bnb_4bit_quant_type="nf4",
                    bnb_4bit_use_double_quant=True,
                    bnb_4bit_compute_dtype=torch.bfloat16,
                )

            tokenizer = AutoTokenizer.from_pretrained(
                model_id, revision=revision, token=hf_token
            )
            model = AutoModelForCausalLM.from_pretrained(
                model_id,
                revision=revision,
                token=hf_token,
                device_map="auto",
                torch_dtype="auto",
                quantization_config=quant_config,
            )

            self._model = model
            self._tokenizer = tokenizer
            self._processor = None
            self._model_id = model_id
            return model, tokenizer

    def _get_translategemma_model_and_processor(self, *, model_id: str) -> tuple[object, object]:
        if self._model is not None and self._processor is not None and self._model_id == model_id:
            return self._model, self._processor

        with self._lock:
            if self._model is not None and self._processor is not None and self._model_id == model_id:
                return self._model, self._processor

            revision = (os.environ.get("YAKULINGO_SPACES_HF_REVISION") or "").strip() or None
            load_in_4bit = _env_bool("YAKULINGO_SPACES_HF_LOAD_IN_4BIT", True)
            hf_token = _hf_token()

            try:
                from transformers import (  # type: ignore[import-not-found]
                    AutoModelForImageTextToText,
                    AutoProcessor,
                )
            except ModuleNotFoundError as e:
                raise RuntimeError(
                    "transformers が見つかりません（Spaces の依存関係を確認してください）。"
                ) from e
            except ImportError as e:
                raise RuntimeError(
                    "TranslateGemma 用の AutoModelForImageTextToText/AutoProcessor が利用できません。"
                    "transformers のバージョンを確認してください。"
                ) from e

            quant_config = None
            if load_in_4bit:
                try:
                    import torch  # type: ignore[import-not-found]
                    from transformers import BitsAndBytesConfig  # type: ignore[import-not-found]
                    import bitsandbytes  # noqa: F401
                except ModuleNotFoundError as e:
                    raise RuntimeError(
                        "4bit 量子化の依存関係（bitsandbytes）が不足しています。"
                        "（回避: `YAKULINGO_SPACES_HF_LOAD_IN_4BIT=0`）"
                    ) from e
                quant_config = BitsAndBytesConfig(
                    load_in_4bit=True,
                    bnb_4bit_quant_type="nf4",
                    bnb_4bit_use_double_quant=True,
                    bnb_4bit_compute_dtype=torch.bfloat16,
                )

            processor = AutoProcessor.from_pretrained(
                model_id, revision=revision, token=hf_token
            )
            model = AutoModelForImageTextToText.from_pretrained(
                model_id,
                revision=revision,
                token=hf_token,
                device_map="auto",
                torch_dtype="auto",
                quantization_config=quant_config,
            )

            self._model = model
            self._tokenizer = None
            self._processor = processor
            self._model_id = model_id
            return model, processor


def _build_prompt(text: str, *, output_language: OutputLanguage) -> str:
    if output_language == "en":
        return (
            "Translate the following Japanese text into English.\n"
            "Output the translation only.\n\n"
            f"{text}\n"
        )
    return (
        "Translate the following English text into Japanese.\n"
        "Output the translation only.\n\n"
        f"{text}\n"
    )


def _build_gguf_prompt(text: str, *, output_language: OutputLanguage) -> str:
    prompt = _build_prompt(text, output_language=output_language).strip()
    return f"<bos><start_of_turn>user\n{prompt}<end_of_turn>\n<start_of_turn>model\n"


def _extract_llama_text(result: object) -> str:
    if isinstance(result, dict):
        choices = result.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0]
            if isinstance(first, dict):
                value = first.get("text") or ""
                return str(value)
    return str(result or "")


def _clean_translation_output(text: str) -> str:
    cleaned = (text or "").strip()
    if not cleaned:
        return ""
    cleaned = _RE_GEMMA_TURN.sub("", cleaned).strip()
    cleaned = _RE_CODE_FENCE_LINE.sub("", cleaned).strip()
    cleaned = _RE_LEADING_LABEL.sub("", cleaned).strip()
    return cleaned


_default_translator = GGUFTranslator()
_gguf_python_translator = LlamaCppPythonTranslator()
_transformers_translator = TransformersTranslator()
_plamo_translator = PlamoTranslator()


def _select_backend() -> Backend:
    raw = (os.environ.get("YAKULINGO_SPACES_BACKEND") or "auto").strip().lower()
    if raw in ("gguf", "llama", "llama-server", "llama_server"):
        return "gguf"
    if raw in ("gguf-python", "gguf_python", "llama-cpp-python", "llama_cpp_python", "llama_cpp"):
        return "gguf_python"
    if raw in ("transformers", "torch", "hf"):
        return "transformers"
    if raw in ("plamo", "preferredai", "preferred-ai", "pfn"):
        return "plamo"
    if os.name != "nt" and _cuda_visible():
        return "transformers"
    return "gguf"


def get_translator() -> GGUFTranslator | LlamaCppPythonTranslator | TransformersTranslator | PlamoTranslator:
    backend = _select_backend()
    if backend == "transformers":
        return _transformers_translator
    if backend == "gguf_python":
        return _gguf_python_translator
    if backend == "plamo":
        return _plamo_translator
    return _default_translator


def _hf_token() -> str | None:
    token = (
        os.environ.get("HF_TOKEN")
        or os.environ.get("HUGGINGFACEHUB_API_TOKEN")
        or os.environ.get("HUGGINGFACE_HUB_TOKEN")
        or ""
    ).strip()
    return token or None
