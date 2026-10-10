import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUFF_HOOK = ROOT / ".claude" / "hooks" / "ruff.sh"


def run_ruff_hook(file: Path) -> subprocess.CompletedProcess[str]:
    payload = json.dumps({"tool_name": "Edit", "tool_input": {"file_path": str(file)}})
    return subprocess.run(
        [str(RUFF_HOOK)],
        input=payload,
        capture_output=True,
        text=True,
        env={**os.environ, "CLAUDE_PROJECT_DIR": str(ROOT)},
        check=False,
    )


def test_holdout_deny_rules_present() -> None:
    settings = json.loads((ROOT / ".claude" / "settings.json").read_text())
    deny = set(settings["permissions"]["deny"])
    assert {
        "Read(~/bidesk-holdout/**)",
        "Edit(~/bidesk-holdout/**)",
        "Bash(*bidesk-holdout*)",
        "Bash(*BIDESK_HOLDOUT_DIR*)",
        "Bash(make eval-holdout*)",
    } <= deny


def test_ruff_hook_formats_and_fixes(tmp_path: Path) -> None:
    file = tmp_path / "messy.py"
    file.write_text("import os\nx  =  [1,2,\n3]\n")
    result = run_ruff_hook(file)
    assert result.returncode == 0, result.stderr
    assert file.read_text() == "x = [1, 2, 3]\n"


def test_ruff_hook_reports_unfixable_errors(tmp_path: Path) -> None:
    file = tmp_path / "broken.py"
    file.write_text("def f() -> None:\n    return undefined_name\n")
    result = run_ruff_hook(file)
    assert result.returncode == 2
    assert "F821" in result.stderr


def test_ruff_hook_ignores_other_files(tmp_path: Path) -> None:
    file = tmp_path / "notes.md"
    file.write_text("x  =  1\n")
    result = run_ruff_hook(file)
    assert result.returncode == 0
    assert file.read_text() == "x  =  1\n"
