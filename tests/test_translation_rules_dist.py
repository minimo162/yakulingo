from pathlib import Path


def test_translation_rules_files_removed() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    default_path = repo_root / "prompts" / "translation_rules.txt"
    dist_path = repo_root / "prompts" / "translation_rules.dist.txt"

    assert not default_path.exists()
    assert not dist_path.exists()
