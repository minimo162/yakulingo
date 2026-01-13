import importlib.util
import sys
from pathlib import Path


def _load_tool_module():
    tool_path = Path(__file__).resolve().parents[1] / "tools" / "hf_to_gguf_quantize.py"
    spec = importlib.util.spec_from_file_location("hf_to_gguf_quantize", tool_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_extract_registered_architectures_parses_modelbase_register(tmp_path: Path) -> None:
    module = _load_tool_module()

    convert_script = tmp_path / "convert_hf_to_gguf.py"
    convert_script.write_text(
        '@ModelBase.register("LlamaForCausalLM", "LlamaModel")\n'
        "@ModelBase.register('NemotronForCausalLM')\n",
        encoding="utf-8",
    )

    registered = module._extract_registered_architectures(convert_script)
    assert "LlamaForCausalLM" in registered
    assert "LlamaModel" in registered
    assert "NemotronForCausalLM" in registered


def test_read_model_architectures_reads_config_json(tmp_path: Path) -> None:
    module = _load_tool_module()

    (tmp_path / "config.json").write_text(
        '{"architectures": ["NemotronFlashForCausalLM"], "model_type": "nemotron_flash"}',
        encoding="utf-8",
    )

    assert module._read_model_architectures(tmp_path) == ["NemotronFlashForCausalLM"]


def test_unsupported_arch_message_includes_gguf_recovery_hints(tmp_path: Path) -> None:
    module = _load_tool_module()

    msg = module._format_unsupported_arch_message(
        model_arch="NemotronFlashForCausalLM",
        hf_repo="nvidia/Nemotron-Flash-3B-Instruct",
        revision="main",
        llama_tag="b7718",
        convert_script=tmp_path / "convert_hf_to_gguf.py",
        registered_count=123,
    )

    assert "prebuilt GGUF" in msg
    assert "local_ai/models/" in msg
    assert ".gguf" in msg
