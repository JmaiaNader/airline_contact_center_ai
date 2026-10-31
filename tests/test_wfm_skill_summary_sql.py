from pathlib import Path


def test_employee_repository_does_not_use_pyformat_tokens_as_skill_labels():
    root = Path(__file__).resolve().parents[1]
    source = (root / "src" / "wfm" / "employee_repository.py").read_text(encoding="utf-8")

    assert "'%(L)s'" not in source
    assert "'%(verified)s'" not in source
    assert "'%(unverified)s'" not in source
    assert "[L" in source
