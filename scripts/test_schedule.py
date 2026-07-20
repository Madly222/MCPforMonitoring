"""
Offline tests for the configurable outage check schedule.

Covers runtime_config time validation/normalization and the scheduler's
"due today" decision (runs at/after the configured time, once per day, with
restart catch-up). No network. Run:

    python scripts/test_schedule.py
"""

import sys
import types
import asyncio
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import src.web.runtime_config as rc  # noqa: E402

_TMP = Path(tempfile.mkdtemp())
rc.RUNTIME_FILE = _TMP / "runtime_settings.json"

PASS, FAIL = "\033[92mPASS\033[0m", "\033[91mFAIL\033[0m"
_fail = 0


def check(name, cond, detail=""):
    global _fail
    print(f"  [{PASS if cond else FAIL}] {name}" + (f"  -> {detail}" if detail and not cond else ""))
    if not cond:
        _fail += 1


print("\n== runtime_config: schedule validation ==")
check("default is 08:00", rc.get_schedule_time("electric") == "08:00")
check("normalizes 8:05 -> 08:05", rc.set_schedule_time("electric", "8:05") == "08:05")
check("stores and reads back", rc.get_schedule_time("electric") == "08:05")
check("accepts 23:59", rc.set_schedule_time("acc", "23:59") == "23:59")
for bad in ("25:00", "08:60", "8", "abc", "08:5", ""):
    try:
        rc.set_schedule_time("acc", bad)
        check(f"rejects {bad!r}", False)
    except ValueError:
        check(f"rejects {bad!r}", True)
check("channels independent", rc.get_schedule_time("electric") == "08:05" and rc.get_schedule_time("acc") == "23:59")

print("\n== scheduler: due-today decision ==")
# Inject fake monitor modules so run_due_checks doesn't need network.
calls = {"electric": 0, "acc": 0}


def _make_fake(name):
    mod = types.ModuleType(f"src.monitoring.{name}_monitor")

    async def _check(force=False):
        calls[name] += 1
        class S: ok = True
        return S()
    setattr(mod, f"check_{name}_status", _check)
    return mod

sys.modules["src.monitoring.electric_monitor"] = _make_fake("electric")
sys.modules["src.monitoring.acc_monitor"] = _make_fake("acc")

import src.monitoring.outage_scheduler as sched  # noqa: E402
sched.STATE_FILE = _TMP / "outage_schedule_state.json"

now = datetime.now()
# Set both targets to one minute in the PAST -> due now.
past = (now - timedelta(minutes=1)).strftime("%H:%M")
rc.set_schedule_time("electric", past)
rc.set_schedule_time("acc", past)

asyncio.run(sched.run_due_checks())
check("electric ran (past target, not run today)", calls["electric"] == 1, f"calls={calls['electric']}")
check("acc ran", calls["acc"] == 1)

# Second invocation same day -> already ran -> no re-run.
asyncio.run(sched.run_due_checks())
check("no re-run same day", calls["electric"] == 1 and calls["acc"] == 1)

# Future target, fresh state -> not due.
calls["electric"] = 0
sched._save_state({})
future = (now + timedelta(hours=2)).strftime("%H:%M")
rc.set_schedule_time("electric", future)
asyncio.run(sched.run_due_checks())
check("not due before target time", calls["electric"] == 0, f"calls={calls['electric']}")

# Restart catch-up: state empty, target already passed -> runs.
calls["electric"] = 0
sched._save_state({})
rc.set_schedule_time("electric", past)
asyncio.run(sched.run_due_checks())
check("catch-up after restart (missed slot)", calls["electric"] == 1)

print()
if _fail:
    print(f"\033[91m{_fail} check(s) failed\033[0m")
    sys.exit(1)
print("\033[92mAll checks passed\033[0m")
