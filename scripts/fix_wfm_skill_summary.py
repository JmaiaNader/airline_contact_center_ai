from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "src" / "wfm" / "employee_repository.py"

OLD_EXPRESSION = re.compile(
    r"CONCAT\(\s*ws\.skill_code\s*,\s*'%\(L\)s'\s*,\s*"
    r"es\.proficiency_level\s*,\s*CASE\s+WHEN\s+es\.is_verified\s*=\s*1\s+"
    r"THEN\s+'%\(verified\)s'\s+ELSE\s+'%\(unverified\)s'\s+END\s*\)",
    flags=re.IGNORECASE | re.DOTALL,
)

NEW_EXPRESSION = (
    "CONCAT(ws.skill_code, ' [L', es.proficiency_level, '] ', "
    "CASE WHEN es.is_verified = 1 THEN '(verified)' ELSE '(unverified)' END)"
)


def main() -> int:
    if not TARGET.is_file():
        raise SystemExit(f"Target file not found: {TARGET}")

    source = TARGET.read_text(encoding="utf-8")
    matches = list(OLD_EXPRESSION.finditer(source))
    if len(matches) != 1:
        raise SystemExit(
            "Safe patch stopped: expected exactly one skills-summary CONCAT "
            f"expression, found {len(matches)}. No file was changed."
        )

    updated = OLD_EXPRESSION.sub(NEW_EXPRESSION, source, count=1)
    if updated == source:
        raise SystemExit("Safe patch stopped: replacement made no change.")

    TARGET.write_text(updated, encoding="utf-8", newline="")
    print("PASS: fixed skills_summary SQL in src/wfm/employee_repository.py")
    print("The display format is now: skill_code [L3] (verified)")
    print("No database schema or data was changed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
