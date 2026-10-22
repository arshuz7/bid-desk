import json
import re
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def example_label() -> dict[str, Any]:
    """The full example label in docs/evals.md, read from the doc so the two can't drift."""
    text = (ROOT / "docs" / "evals.md").read_text()
    block = re.search(r"```json\n(.*?)```", text, re.DOTALL)
    assert block, "docs/evals.md has no ```json example"
    return json.loads(block[1])
