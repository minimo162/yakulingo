import re
from pathlib import Path


def test_install_local_ai_script_does_not_assign_to_pid_variable() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    script_path = repo_root / "packaging" / "install_local_ai.ps1"

    content = script_path.read_text(encoding="utf-8-sig")

    pattern = re.compile(r"^\s*\$pid\s*=", re.IGNORECASE | re.MULTILINE)
    match = pattern.search(content)
    assert match is None, (
        f"Do not assign to $pid/$PID in {script_path} (found: {match.group(0)!r})"
    )
