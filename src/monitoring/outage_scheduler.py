"""
In-app daily scheduler for outage checks (electricity + water).

Runs each monitor once per day at the time configured by the superadmin
(runtime_config.get_schedule_time). Scheduling lives in-process because the web
service runs unprivileged and cannot rewrite systemd timers; this keeps the
schedule editable from the panel and takes effect within a minute.

State (last run date per channel) is persisted so a restart does not re-run a
check that already happened today, while a restart *after* a missed slot still
catches up (systemd Persistent=true behaviour). Email de-dup is content-based,
so even a redundant run never sends a duplicate.
"""

import asyncio
import json
from datetime import datetime
from pathlib import Path

from loguru import logger

from src.core.config import PROJECT_ROOT

STATE_FILE = PROJECT_ROOT / "logs" / "outage_schedule_state.json"

_CHANNELS = ("electric", "acc")


def _load_state() -> dict:
    try:
        if STATE_FILE.exists():
            with open(STATE_FILE, "r") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
    except Exception:
        pass
    return {}


def _save_state(state: dict) -> None:
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(STATE_FILE, "w") as f:
            json.dump(state, f)
    except Exception as e:
        logger.debug(f"Outage scheduler: state save failed: {e}")


def _target_today(channel: str, now: datetime) -> datetime:
    from src.web.runtime_config import get_schedule_time
    hh, mm = get_schedule_time(channel).split(":")
    return now.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)


async def run_due_checks() -> None:
    """Run any channel whose configured time has arrived and hasn't run today."""
    from src.monitoring.electric_monitor import check_electric_status
    from src.monitoring.acc_monitor import check_acc_status

    runners = {"electric": check_electric_status, "acc": check_acc_status}
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    state = _load_state()

    for channel in _CHANNELS:
        if state.get(channel) == today:
            continue
        if now < _target_today(channel, now):
            continue
        try:
            status = await runners[channel](force=True)
            state[channel] = today
            _save_state(state)
            logger.info(
                f"Outage scheduler: {channel} daily check ran "
                f"(ok={getattr(status, 'ok', None)})"
            )
        except Exception as e:
            logger.error(f"Outage scheduler: {channel} check failed: {e}")


async def scheduler_loop() -> None:
    """Background loop: checks every 30s whether a channel is due."""
    logger.info("Outage scheduler started (in-app, panel-configurable time)")
    await asyncio.sleep(10)  # let startup settle
    while True:
        try:
            await run_due_checks()
        except Exception as e:
            logger.error(f"Outage scheduler loop error: {e}")
        await asyncio.sleep(30)
