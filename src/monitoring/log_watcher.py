"""
Real-time Log Watcher.

Monitors log files on remote servers via SSH tail -F.
Detects errors and triggers processing pipeline.
"""

import asyncio
from typing import Optional, Callable, Awaitable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from loguru import logger

from src.core.config import get_config
from src.core.ssh_manager import get_ssh_manager, SSHManager


class LogEventType(Enum):
    """Type of log event."""
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"
    UNKNOWN = "unknown"


@dataclass
class LogEvent:
    """Represents a log event from monitored server."""
    server_id: str
    service_type: str
    log_file: str
    line: str
    event_type: LogEventType
    timestamp: datetime = field(default_factory=datetime.now)
    
    def __str__(self):
        return f"[{self.server_id}:{self.service_type}] {self.line[:100]}"


LogEventHandler = Callable[[LogEvent], Awaitable[None]]


class LogWatcher:
    """
    Watches log files on remote servers in real-time.
    
    Uses SSH tail -F to stream log lines and detect errors.
    """
    
    def __init__(self, ssh_manager: Optional[SSHManager] = None):
        self.ssh = ssh_manager or get_ssh_manager()
        self.config = get_config()
        self._tasks: dict[str, asyncio.Task] = {}
        self._running = False
        self._handlers: list[LogEventHandler] = []
        self._error_patterns: list[str] = []
        self._warning_patterns: list[str] = []
        self._ignore_patterns: list[str] = []
        self._load_patterns()
    
    def _load_patterns(self):
        """Load error and ignore patterns from knowledge base."""
        import re
        
        try:
            import yaml
            from src.core.config import KNOWLEDGE_DIR
            
            # Load ignore patterns
            ignore_file = KNOWLEDGE_DIR / "ignore_patterns.yaml"
            if ignore_file.exists():
                with open(ignore_file) as f:
                    data = yaml.safe_load(f) or {}
                
                for category, patterns in data.items():
                    if isinstance(patterns, list):
                        self._ignore_patterns.extend(patterns)
            
            # Common error patterns
            self._error_patterns = [
                r"error",
                r"fail(ed|ure)?",
                r"fatal",
                r"crit(ical)?",
                r"panic",
                r"exception",
                r"segfault",
                r"out of memory",
                r"refused",
                r"denied",
                r"timeout",
                r"unreachable",
            ]
            
            self._warning_patterns = [
                r"warn(ing)?",
                r"notice",
                r"alert",
            ]
            
            logger.debug(f"Loaded {len(self._ignore_patterns)} ignore patterns")
            
        except Exception as e:
            logger.error(f"Failed to load patterns: {e}")
    
    def _should_ignore(self, line: str) -> bool:
        """Check if line should be ignored."""
        import re
        
        for pattern in self._ignore_patterns:
            try:
                if re.search(pattern, line, re.IGNORECASE):
                    return True
            except re.error:
                continue
        
        return False
    
    def _classify_line(self, line: str) -> LogEventType:
        """Classify log line by severity."""
        import re
        
        line_lower = line.lower()
        
        for pattern in self._error_patterns:
            if re.search(pattern, line_lower):
                return LogEventType.ERROR
        
        for pattern in self._warning_patterns:
            if re.search(pattern, line_lower):
                return LogEventType.WARNING
        
        return LogEventType.INFO
    
    def add_handler(self, handler: LogEventHandler):
        """Add event handler."""
        self._handlers.append(handler)
        logger.debug(f"Added log event handler: {handler.__name__}")
    
    def remove_handler(self, handler: LogEventHandler):
        """Remove event handler."""
        if handler in self._handlers:
            self._handlers.remove(handler)
    
    async def _notify_handlers(self, event: LogEvent):
        """Notify all handlers about event."""
        for handler in self._handlers:
            try:
                await handler(event)
            except Exception as e:
                logger.error(f"Handler error: {e}")
    
    async def _watch_log_file(
        self,
        server_id: str,
        service_type: str,
        log_file: str,
        filter_pattern: Optional[str] = None
    ):
        """Watch a single log file."""
        task_id = f"{server_id}:{log_file}"
        logger.info(f"Starting log watch: {task_id}")
        
        settings = self.config.load_settings()
        reconnect_delay = settings.monitoring.realtime.reconnect_delay_seconds
        max_attempts = settings.monitoring.realtime.max_reconnect_attempts
        
        attempts = 0
        
        while self._running and attempts < max_attempts:
            try:
                async for line in self.ssh.tail_logs(server_id, log_file, filter_pattern):
                    if not self._running:
                        break
                    
                    if self._should_ignore(line):
                        continue
                    
                    event_type = self._classify_line(line)
                    
                    # Only process warnings and errors
                    if event_type in (LogEventType.ERROR, LogEventType.WARNING):
                        event = LogEvent(
                            server_id=server_id,
                            service_type=service_type,
                            log_file=log_file,
                            line=line,
                            event_type=event_type
                        )
                        
                        await self._notify_handlers(event)
                    
                attempts = 0  # Reset on successful connection
                
            except asyncio.CancelledError:
                logger.info(f"Log watch cancelled: {task_id}")
                break
                
            except Exception as e:
                attempts += 1
                logger.warning(f"Log watch error ({attempts}/{max_attempts}): {task_id} - {e}")
                
                if self._running and attempts < max_attempts:
                    await asyncio.sleep(reconnect_delay)
        
        logger.info(f"Log watch stopped: {task_id}")
    
    async def start(self):
        """Start watching all configured log files.

        Non-blocking: the per-server setup runs in the background and
        concurrently, so one unreachable host can't serialize (and stall)
        startup. The web app comes up immediately; watchers attach as each
        server responds.
        """
        if self._running:
            logger.warning("Log watcher already running")
            return
        
        self._running = True
        logger.info("Starting log watcher...")
        self._setup_task = asyncio.create_task(self._setup_all())

    async def _setup_all(self):
        servers = self.config.get_enabled_servers()
        await asyncio.gather(
            *[self._setup_server(server) for server in servers],
            return_exceptions=True,
        )
        logger.info(f"Log watcher ready with {len(self._tasks)} log file(s)")

    async def _setup_server(self, server):
        # One fast reachability probe first: if the host is down, skip all its
        # detection/file probes — each would otherwise burn the full connect
        # timeout, and a few dead hosts add up to minutes.
        ok, reason = await self.ssh.probe_connection(server.id)
        if not ok:
            logger.warning(f"Log watcher: skipping {server.id} — {reason}")
            return
        
        for service_type in server.services:
            try:
                service_config = self.config.load_service_config(service_type)
                
                # Get log files for this service
                log_files = service_config.get("log_files", {})
                
                # Try to detect which variant is installed
                detection = service_config.get("detection", {}).get("commands", [])
                detected_name = None
                
                for det in detection:
                    result = await self.ssh.execute(server.id, det["check"], timeout=10.0)
                    if result.success and "found" in result.stdout:
                        detected_name = det["name"]
                        break
                
                if detected_name and detected_name in log_files:
                    files_config = log_files[detected_name]
                else:
                    # Use first available
                    files_config = list(log_files.values())[0] if log_files else []
                
                for log_config in files_config:
                    if isinstance(log_config, dict):
                        log_path = log_config.get("path")
                        log_filter = log_config.get("filter")
                    else:
                        log_path = log_config
                        log_filter = None
                    
                    if not log_path:
                        continue
                    
                    # Check if file exists
                    if await self.ssh.file_exists(server.id, log_path):
                        task_id = f"{server.id}:{log_path}"
                        task = asyncio.create_task(
                            self._watch_log_file(
                                server.id,
                                service_type,
                                log_path,
                                log_filter
                            )
                        )
                        self._tasks[task_id] = task
                        logger.info(f"Watching: {task_id}")
                    else:
                        logger.debug(f"Log file not found: {log_path} on {server.id}")
            except Exception as e:
                logger.error(f"Log watcher setup failed for {server.id}/{service_type}: {e}")
    
    async def stop(self):
        """Stop watching all log files."""
        if not self._running:
            return
        
        logger.info("Stopping log watcher...")
        self._running = False
        
        setup_task = getattr(self, "_setup_task", None)
        if setup_task and not setup_task.done():
            setup_task.cancel()
            try:
                await setup_task
            except asyncio.CancelledError:
                pass
        
        for task_id, task in self._tasks.items():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        
        self._tasks.clear()
        logger.info("Log watcher stopped")
    
    @property
    def is_running(self) -> bool:
        """Check if watcher is running."""
        return self._running
    
    @property
    def watched_files(self) -> list[str]:
        """Get list of watched files."""
        return list(self._tasks.keys())


_log_watcher: Optional[LogWatcher] = None


def get_log_watcher() -> LogWatcher:
    """Get log watcher singleton instance."""
    global _log_watcher
    if _log_watcher is None:
        _log_watcher = LogWatcher()
    return _log_watcher
