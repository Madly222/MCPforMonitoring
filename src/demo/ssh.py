"""SSHManager that talks to the simulated demo hosts instead of real servers."""

import asyncio
import random
from datetime import datetime
from typing import AsyncIterator, Optional

from loguru import logger

from src.core.ssh_manager import CommandResult, SSHManager, build_sudo_command
from src.demo.hosts import RECURRING_EVENTS, SCRIPTED_EVENTS, DemoHost, build_fleet


class DemoSSHManager(SSHManager):
    def __init__(self):
        super().__init__()
        self.hosts: dict[str, DemoHost] = build_fleet()
        self._new_lines: dict[str, asyncio.Event] = {}
        self._events_task: Optional[asyncio.Task] = None

    def _host(self, server_id: str) -> DemoHost:
        host = self.hosts.get(server_id)
        if host is None:
            raise ValueError(f"Server not found: {server_id}")
        return host

    async def execute(self, server_id: str, command: str, timeout: float = 30.0) -> CommandResult:
        host = self._host(server_id)
        await asyncio.sleep(random.uniform(0.01, 0.06))  # a little network latency
        if not host.reachable:
            return CommandResult(server_id, command, "", "Connection timed out (demo: this host is down)", -1, duration_ms=8000)
        sudo = "sudo -S" in command or "sudo -n" in command
        stdout, stderr, code = host.run(command, sudo=sudo)
        if "2>&1" in command and stderr:
            stdout, stderr = stdout + stderr, ""
        return CommandResult(server_id, command, stdout, stderr, code, duration_ms=random.uniform(15, 60))

    async def execute_sudo(self, server_id: str, command: str, timeout: float = 30.0) -> CommandResult:
        return await self.execute(server_id, build_sudo_command(command, None), timeout)

    async def tail_logs(self, server_id: str, log_file: str, filter_pattern: Optional[str] = None) -> AsyncIterator[str]:
        host = self._host(server_id)
        if log_file != host.log_file:
            await asyncio.Event().wait()  # nothing ever arrives in other files
        self._ensure_event_feed()
        event = self._new_lines.setdefault(server_id, asyncio.Event())
        seen = len(host.log)
        while True:
            await event.wait()
            event.clear()
            for line in host.log[seen:]:
                if not filter_pattern or filter_pattern.lower() in line.lower():
                    yield line
            seen = len(host.log)

    async def tail_logs_sudo(self, server_id: str, log_file: str, filter_pattern: Optional[str] = None) -> AsyncIterator[str]:
        async for line in self.tail_logs(server_id, log_file, filter_pattern):
            yield line

    async def disconnect(self, server_id: str) -> None:
        self._init_systems.pop(server_id, None)

    async def close(self) -> None:
        if self._events_task:
            self._events_task.cancel()

    # ------------------------------------------------------------------ events

    def _ensure_event_feed(self) -> None:
        if self._events_task is None:
            self._events_task = asyncio.create_task(self._feed_events())

    def _emit(self, server_id: str, process: str, text: str) -> None:
        line = self.hosts[server_id].append_log(process, text)
        logger.debug(f"[demo] {server_id}: {line}")
        self._new_lines.setdefault(server_id, asyncio.Event()).set()

    async def _feed_events(self) -> None:
        """Write scripted errors shortly after start, then a random one every few minutes."""
        started = datetime.now()
        for delay, server_id, process, text in SCRIPTED_EVENTS:
            wait = delay - (datetime.now() - started).total_seconds()
            if wait > 0:
                await asyncio.sleep(wait)
            self._emit(server_id, process, text)
        while True:
            await asyncio.sleep(random.uniform(120, 300))
            self._emit(*random.choice(RECURRING_EVENTS))
