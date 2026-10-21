"""Run the offline self-check scripts in scripts/ as part of the pytest suite."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


@pytest.mark.parametrize("name", ["check_resolver", "check_schedule", "check_outage_filters"])
def test_offline_check_script(name):
    result = subprocess.run(
        [sys.executable, str(SCRIPTS / f"{name}.py")],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    assert result.returncode == 0, result.stdout + result.stderr
