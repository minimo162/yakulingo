from __future__ import annotations

import argparse

from yakulingo.config.settings import AppSettings

from tools import bench_local_ai


def _make_args(**overrides: object) -> argparse.Namespace:
    base: dict[str, object] = {
        "max_tokens": None,
        "ctx_size": None,
        "threads": None,
        "threads_batch": None,
        "batch_size": None,
        "ubatch_size": None,
        "max_chars_per_batch": None,
        "max_chars_per_batch_file": None,
        "model_path": None,
        "server_dir": None,
        "host": None,
        "port_base": None,
        "port_max": None,
        "temperature": None,
        "device": None,
        "n_gpu_layers": None,
        "flash_attn": None,
        "no_warmup": False,
        "mlock": None,
        "no_mmap": None,
        "vk_force_max_allocation_size": None,
        "vk_disable_f16": False,
        "cache_type_k": None,
        "cache_type_v": None,
    }
    base.update(overrides)
    return argparse.Namespace(**base)


def test_apply_overrides_supports_threads_batch_mlock_no_mmap() -> None:
    settings = AppSettings()

    args = _make_args(threads_batch=12, mlock=True, no_mmap=True)
    overrides = bench_local_ai._apply_overrides(settings, args)

    assert settings.local_ai_threads_batch == 12
    assert settings.local_ai_mlock is True
    assert settings.local_ai_no_mmap is True
    assert overrides["local_ai_threads_batch"] == 12
    assert overrides["local_ai_mlock"] is True
    assert overrides["local_ai_no_mmap"] is True


def test_settings_payload_includes_threads_batch_mlock_no_mmap() -> None:
    settings = AppSettings(
        local_ai_threads_batch=0, local_ai_mlock=False, local_ai_no_mmap=False
    )
    settings._validate()

    payload = bench_local_ai._build_settings_payload(settings)

    assert payload["local_ai_threads_batch"] == 0
    assert payload["local_ai_mlock"] is False
    assert payload["local_ai_no_mmap"] is False
