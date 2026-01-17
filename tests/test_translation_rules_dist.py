from pathlib import Path


def test_translation_rules_dist_matches_default() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    default_path = repo_root / "prompts" / "translation_rules.txt"
    dist_path = repo_root / "prompts" / "translation_rules.dist.txt"

    assert default_path.exists()
    assert dist_path.exists()
    assert default_path.read_bytes() == dist_path.read_bytes()
