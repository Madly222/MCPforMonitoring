"""
SSH Manager for MCP Server Monitor.

Provides async SSH connections to remote servers for:
- Executing commands
- Reading log files
- Real-time log tailing
- Service management (systemd and SysVinit)
"""

import asyncio
from pathlib import Path
from typing import Optional, AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

import asyncssh
from loguru import logger

from src.core.config import get_config, ServerConfig, KEYS_DIR

# Hard ceiling for establishing an SSH connection (TCP + auth). Without this,
# an unreachable / misconfigured host makes asyncssh.connect() hang for the OS
# default (tens of seconds up to minutes), which used to freeze the whole
# dashboard because status collection waits on every server at once.
SSH_CONNECT_TIMEOUT = 8.0  # fallback default; the live value comes from the store


def get_connect_timeout() -> float:
    """Current SSH connect timeout in seconds.

    Read from the runtime store on every attempt so a change in the superadmin
    panel applies immediately, with no restart. Falls back to the constant above
    if the store isn't available (standalone scripts, tests).
    """
    try:
        from src.web import runtime_config as rc
        return float(rc.get_ssh_timeout())
    except Exception:
        return SSH_CONNECT_TIMEOUT


def _friendly_ssh_error(raw: str) -> str:
    """Turn a raw SSH/OS error into a short, readable reason for the dashboard,
    while keeping the original text appended so it's still a real log line."""
    raw = (raw or "").strip()
    if not raw:
        return "Не удалось подключиться (причина неизвестна)"
    low = raw.lower()
    if "timed out" in low or "timeout" in low:
        return f"Таймаут подключения — хост недоступен или порт фильтруется. {raw}"
    if "refused" in low:
        return f"Соединение отклонено — SSH не слушает на этом порту. {raw}"
    if "no route to host" in low or "unreachable" in low:
        return f"Хост недоступен — нет маршрута. {raw}"
    if "permission denied" in low or "authentication" in low:
        return f"Ошибка авторизации — проверь user/ключ/пароль. {raw}"
    if "key" in low and ("not found" in low or "no such" in low):
        return f"SSH-ключ не найден. {raw}"
    if "name or service not known" in low or "getaddrinfo" in low:
        return f"Не удаётся разрешить имя хоста. {raw}"
    if "disabled" in low:
        return f"Сервер отключён в конфиге. {raw}"
    return raw


class InitSystem(Enum):
    SYSTEMD = "systemd"
    SYSVINIT = "sysvinit"
    UNKNOWN = "unknown"


@dataclass
class CommandResult:
    server_id: str
    command: str
    stdout: str
    stderr: str
    exit_code: int
    executed_at: datetime = field(default_factory=datetime.now)
    duration_ms: float = 0.0
    
    @property
    def success(self) -> bool:
        return self.exit_code == 0
    
    @property
    def output(self) -> str:
        if self.stderr:
            return f"{self.stdout}\n{self.stderr}".strip()
        return self.stdout.strip()


@dataclass
class ConnectionInfo:
    server_id: str
    host: str
    port: int
    user: str
    connected_at: datetime = field(default_factory=datetime.now)
    last_used: datetime = field(default_factory=datetime.now)
    init_system: InitSystem = InitSystem.UNKNOWN


@dataclass
class ServiceStatus:
    service_name: str
    process_name: str
    running: bool
    enabled: str
    pid: Optional[int] = None
    init_system: InitSystem = InitSystem.UNKNOWN


class SSHConnectionPool:
    
    def __init__(self):
        self._connections: dict[str, asyncssh.SSHClientConnection] = {}
        self._connection_info: dict[str, ConnectionInfo] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._global_lock = asyncio.Lock()
    
    async def _get_lock(self, server_id: str) -> asyncio.Lock:
        async with self._global_lock:
            if server_id not in self._locks:
                self._locks[server_id] = asyncio.Lock()
            return self._locks[server_id]
    
    async def _create_connection(
        self, 
        server: ServerConfig
    ) -> asyncssh.SSHClientConnection:
        connect_timeout = get_connect_timeout()
        connect_kwargs = {
            "host": server.host,
            "port": server.port,
            "username": server.user,
            "known_hosts": None,
            # asyncssh's own timeout for the TCP connect + auth handshake.
            "connect_timeout": connect_timeout,
        }
        
        if server.auth_type == "key":
            key_path = KEYS_DIR / server.auth_value
            if not key_path.exists():
                raise FileNotFoundError(f"SSH key not found: {key_path}")
            connect_kwargs["client_keys"] = [str(key_path)]
        else:
            connect_kwargs["password"] = server.auth_value
        
        logger.debug(f"Connecting to {server.id} ({server.host}:{server.port})")
        
        # Belt-and-suspenders: even if connect_timeout doesn't fire (e.g. a DNS
        # resolution stall or a network black hole), this hard ceiling guarantees
        # the coroutine returns instead of hanging forever and blocking the fleet.
        try:
            conn = await asyncio.wait_for(
                asyncssh.connect(**connect_kwargs),
                timeout=connect_timeout + 2.0,
            )
        except asyncio.TimeoutError:
            raise ConnectionError(
                f"Timed out connecting to {server.id} "
                f"({server.host}:{server.port}) after {connect_timeout:.0f}s"
            )
        
        logger.info(f"Connected to {server.id} ({server.host})")
        
        return conn
    
    async def get_connection(
        self, 
        server: ServerConfig
    ) -> asyncssh.SSHClientConnection:
        lock = await self._get_lock(server.id)
        
        async with lock:
            if server.id in self._connections:
                conn = self._connections[server.id]
                try:
                    result = await asyncio.wait_for(
                        conn.run("echo ping", check=True),
                        timeout=5.0
                    )
                    if result.exit_status == 0:
                        self._connection_info[server.id].last_used = datetime.now()
                        return conn
                except Exception:
                    logger.warning(f"Connection to {server.id} is stale, reconnecting")
                    await self._close_connection(server.id)
            
            conn = await self._create_connection(server)
            self._connections[server.id] = conn
            self._connection_info[server.id] = ConnectionInfo(
                server_id=server.id,
                host=server.host,
                port=server.port,
                user=server.user
            )
            
            return conn
    
    async def _close_connection(self, server_id: str) -> None:
        if server_id in self._connections:
            try:
                self._connections[server_id].close()
                await self._connections[server_id].wait_closed()
            except Exception as e:
                logger.debug(f"Error closing connection to {server_id}: {e}")
            finally:
                del self._connections[server_id]
                if server_id in self._connection_info:
                    del self._connection_info[server_id]
    
    async def close_all(self) -> None:
        for server_id in list(self._connections.keys()):
            await self._close_connection(server_id)
        logger.info("All SSH connections closed")
    
    def get_connection_info(self, server_id: str) -> Optional[ConnectionInfo]:
        return self._connection_info.get(server_id)
    
    def set_init_system(self, server_id: str, init_system: InitSystem) -> None:
        if server_id in self._connection_info:
            self._connection_info[server_id].init_system = init_system
    
    def get_init_system(self, server_id: str) -> InitSystem:
        info = self._connection_info.get(server_id)
        return info.init_system if info else InitSystem.UNKNOWN
    
    def get_all_connections_info(self) -> list[ConnectionInfo]:
        return list(self._connection_info.values())


class SSHManager:
    
    def __init__(self):
        self._pool = SSHConnectionPool()
        self._config = get_config()
        self._init_systems: dict[str, InitSystem] = {}
    
    async def execute(
        self, 
        server_id: str, 
        command: str,
        timeout: float = 30.0
    ) -> CommandResult:
        server = self._config.get_server_by_id(server_id)
        if not server:
            raise ValueError(f"Server not found: {server_id}")
        
        if not server.enabled:
            raise ValueError(f"Server is disabled: {server_id}")
        
        start_time = datetime.now()
        
        try:
            conn = await asyncio.wait_for(
                self._pool.get_connection(server),
                timeout=get_connect_timeout() + 5.0,
            )
            
            result = await asyncio.wait_for(
                conn.run(command),
                timeout=timeout
            )
            
            duration = (datetime.now() - start_time).total_seconds() * 1000
            
            cmd_result = CommandResult(
                server_id=server_id,
                command=command,
                stdout=result.stdout or "",
                stderr=result.stderr or "",
                exit_code=result.exit_status or 0,
                duration_ms=duration
            )
            
            logger.debug(
                f"Command on {server_id}: '{command[:50]}...' "
                f"exit_code={cmd_result.exit_code} duration={duration:.0f}ms"
            )
            
            return cmd_result
            
        except asyncio.TimeoutError:
            duration = (datetime.now() - start_time).total_seconds() * 1000
            logger.error(f"Command timeout on {server_id}: {command}")
            return CommandResult(
                server_id=server_id,
                command=command,
                stdout="",
                stderr="Command timed out",
                exit_code=-1,
                duration_ms=duration
            )
            
        except Exception as e:
            duration = (datetime.now() - start_time).total_seconds() * 1000
            logger.error(f"Command failed on {server_id}: {e}")
            return CommandResult(
                server_id=server_id,
                command=command,
                stdout="",
                stderr=str(e),
                exit_code=-1,
                duration_ms=duration
            )
    
    async def detect_init_system(self, server_id: str) -> InitSystem:
        if server_id in self._init_systems:
            return self._init_systems[server_id]
        
        detect_cmd = (
            "if command -v systemctl >/dev/null 2>&1 && "
            "systemctl --version >/dev/null 2>&1; then echo 'systemd'; "
            "elif [ -d /etc/init.d ]; then echo 'sysvinit'; "
            "else echo 'unknown'; fi"
        )
        
        result = await self.execute(server_id, detect_cmd, timeout=10.0)
        
        output = result.stdout.strip().lower()
        
        if "systemd" in output:
            init_sys = InitSystem.SYSTEMD
        elif "sysvinit" in output:
            init_sys = InitSystem.SYSVINIT
        else:
            init_sys = InitSystem.UNKNOWN
        
        self._init_systems[server_id] = init_sys
        self._pool.set_init_system(server_id, init_sys)
        
        logger.debug(f"Detected init system on {server_id}: {init_sys.value}")
        
        return init_sys

    async def execute_sudo(
        self,
        server_id: str,
        command: str,
        timeout: float = 30.0
    ) -> CommandResult:
        """
        Execute command with sudo.
        
        Uses sudo_password from config if available, otherwise falls back to
        auth_value for password auth, or passwordless sudo for key auth.
        
        PATH is set inside sudo environment to ensure commands are found.
        """
        sudo_password = self._config.get_sudo_password(server_id)
        
        # Full PATH for sudo environment - must be set INSIDE sudo via env
        sudo_path = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
        
        if sudo_password:
            # Escape single quotes in password
            escaped_password = sudo_password.replace("'", "'\\''")
            # -S reads password from stdin, -p '' suppresses custom prompt
            # Use env inside sudo to set PATH properly
            sudo_command = f"echo '{escaped_password}' | sudo -S -p '' env PATH={sudo_path} {command} 2>&1"
        else:
            # Try passwordless sudo (requires NOPASSWD in sudoers)
            # Still use env to ensure PATH is set correctly
            sudo_command = f"sudo env PATH={sudo_path} {command}"
        
        return await self.execute(server_id, sudo_command, timeout)

    async def check_service_status(
        self, 
        server_id: str, 
        service_name: str,
        process_name: Optional[str] = None
    ) -> ServiceStatus:
        init_sys = await self.detect_init_system(server_id)
        proc_name = process_name or service_name
        
        if init_sys == InitSystem.SYSTEMD:
            status_cmd = f"systemctl is-active {service_name} 2>/dev/null"
            enabled_cmd = f"systemctl is-enabled {service_name} 2>/dev/null"
            
            status_result = await self.execute(server_id, status_cmd)
            enabled_result = await self.execute(server_id, enabled_cmd)
            
            running = status_result.stdout.strip() == "active"
            enabled = enabled_result.stdout.strip()
            
        else:
            running_cmd = f"pgrep -x {proc_name} >/dev/null 2>&1 && echo 'running' || echo 'stopped'"
            enabled_cmd = f"ls /etc/rc2.d/S*{service_name}* >/dev/null 2>&1 && echo 'enabled' || echo 'disabled'"
            
            status_result = await self.execute(server_id, running_cmd)
            enabled_result = await self.execute(server_id, enabled_cmd)
            
            running = "running" in status_result.stdout.strip()
            enabled = enabled_result.stdout.strip()
        
        pid = None
        if running:
            pid_cmd = f"pgrep -x {proc_name} | head -1"
            pid_result = await self.execute(server_id, pid_cmd)
            try:
                pid = int(pid_result.stdout.strip())
            except (ValueError, TypeError):
                pass
        
        return ServiceStatus(
            service_name=service_name,
            process_name=proc_name,
            running=running,
            enabled=enabled,
            pid=pid,
            init_system=init_sys
        )
    
    async def restart_service(
        self, 
        server_id: str, 
        service_name: str
    ) -> CommandResult:
        init_sys = await self.detect_init_system(server_id)
        
        if init_sys == InitSystem.SYSTEMD:
            cmd = f"systemctl restart {service_name}"
        else:
            cmd = f"/etc/init.d/{service_name} restart"
        
        logger.info(f"Restarting {service_name} on {server_id} ({init_sys.value})")
        
        return await self.execute_sudo(server_id, cmd, timeout=60.0)
    
    async def start_service(
        self, 
        server_id: str, 
        service_name: str
    ) -> CommandResult:
        init_sys = await self.detect_init_system(server_id)
        
        if init_sys == InitSystem.SYSTEMD:
            cmd = f"systemctl start {service_name}"
        else:
            cmd = f"/etc/init.d/{service_name} start"
        
        logger.info(f"Starting {service_name} on {server_id}")
        
        return await self.execute_sudo(server_id, cmd, timeout=60.0)
    
    async def stop_service(
        self, 
        server_id: str, 
        service_name: str
    ) -> CommandResult:
        init_sys = await self.detect_init_system(server_id)
        
        if init_sys == InitSystem.SYSTEMD:
            cmd = f"systemctl stop {service_name}"
        else:
            cmd = f"/etc/init.d/{service_name} stop"
        
        logger.info(f"Stopping {service_name} on {server_id}")
        
        return await self.execute_sudo(server_id, cmd, timeout=60.0)
    
    async def reload_service(
        self, 
        server_id: str, 
        service_name: str
    ) -> CommandResult:
        init_sys = await self.detect_init_system(server_id)
        
        if init_sys == InitSystem.SYSTEMD:
            cmd = f"systemctl reload {service_name} 2>/dev/null || systemctl restart {service_name}"
        else:
            cmd = f"/etc/init.d/{service_name} reload 2>/dev/null || /etc/init.d/{service_name} restart"
        
        logger.info(f"Reloading {service_name} on {server_id}")
        
        return await self.execute_sudo(server_id, cmd, timeout=60.0)
    
    async def read_file(
        self, 
        server_id: str, 
        file_path: str,
        tail_lines: Optional[int] = None
    ) -> CommandResult:
        if tail_lines:
            command = f"tail -n {tail_lines} {file_path}"
        else:
            command = f"cat {file_path}"
        
        return await self.execute(server_id, command)
    
    async def read_file_sudo(
        self, 
        server_id: str, 
        file_path: str,
        tail_lines: Optional[int] = None
    ) -> CommandResult:
        """Read file with sudo privileges (for protected log files)."""
        if tail_lines:
            command = f"tail -n {tail_lines} {file_path}"
        else:
            command = f"cat {file_path}"
        
        return await self.execute_sudo(server_id, command)
    
    async def file_exists(self, server_id: str, file_path: str) -> bool:
        result = await self.execute(
            server_id, 
            f"[ -f {file_path} ] && echo 'exists' || echo 'not found'"
        )
        return "exists" in result.stdout
    
    async def find_existing_file(
        self, 
        server_id: str, 
        file_paths: list[str]
    ) -> Optional[str]:
        for path in file_paths:
            if await self.file_exists(server_id, path):
                return path
        return None
    
    async def tail_logs(
        self,
        server_id: str,
        log_file: str,
        filter_pattern: Optional[str] = None
    ) -> AsyncIterator[str]:
        server = self._config.get_server_by_id(server_id)
        if not server:
            raise ValueError(f"Server not found: {server_id}")
        
        if filter_pattern:
            command = f"tail -F {log_file} 2>/dev/null | grep --line-buffered '{filter_pattern}'"
        else:
            command = f"tail -F {log_file} 2>/dev/null"
        
        logger.info(f"Starting log tail on {server_id}: {log_file}")
        
        try:
            conn = await self._pool.get_connection(server)
            
            async with conn.create_process(command) as process:
                async for line in process.stdout:
                    yield line.rstrip("\n")
                    
        except asyncio.CancelledError:
            logger.info(f"Log tail cancelled for {server_id}: {log_file}")
            raise
            
        except Exception as e:
            logger.error(f"Log tail error on {server_id}: {e}")
            raise
    
    async def tail_logs_sudo(
        self,
        server_id: str,
        log_file: str,
        filter_pattern: Optional[str] = None
    ) -> AsyncIterator[str]:
        """Tail log file with sudo privileges (for protected log files)."""
        server = self._config.get_server_by_id(server_id)
        if not server:
            raise ValueError(f"Server not found: {server_id}")
        
        sudo_password = self._config.get_sudo_password(server_id)
        sudo_path = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
        
        if filter_pattern:
            tail_cmd = f"tail -F {log_file} 2>/dev/null | grep --line-buffered '{filter_pattern}'"
        else:
            tail_cmd = f"tail -F {log_file} 2>/dev/null"
        
        if sudo_password:
            escaped_password = sudo_password.replace("'", "'\\''")
            command = f"echo '{escaped_password}' | sudo -S -p '' env PATH={sudo_path} {tail_cmd}"
        else:
            command = f"sudo env PATH={sudo_path} {tail_cmd}"
        
        logger.info(f"Starting sudo log tail on {server_id}: {log_file}")
        
        try:
            conn = await self._pool.get_connection(server)
            
            async with conn.create_process(command) as process:
                async for line in process.stdout:
                    line = line.rstrip("\n")
                    # Filter out sudo password prompt artifacts if any
                    if not line.startswith("[sudo]"):
                        yield line
                    
        except asyncio.CancelledError:
            logger.info(f"Sudo log tail cancelled for {server_id}: {log_file}")
            raise
            
        except Exception as e:
            logger.error(f"Sudo log tail error on {server_id}: {e}")
            raise
    
    async def get_system_info(self, server_id: str) -> dict:
        commands = {
            "hostname": "hostname",
            "uptime": "uptime -p 2>/dev/null || uptime | sed 's/.*up/up/'",
            "load": "cat /proc/loadavg | cut -d' ' -f1-3",
            "memory": "free -m 2>/dev/null | grep Mem | awk '{print $3\"/\"$2\"MB\"}' || cat /proc/meminfo | grep MemTotal | awk '{print int($2/1024)\"MB\"}'",
            "disk": "df -h / | tail -1 | awk '{print $5}'"
        }
        
        info = {"server_id": server_id}
        
        for key, cmd in commands.items():
            result = await self.execute(server_id, cmd, timeout=10.0)
            info[key] = result.stdout.strip() if result.success else "unknown"
        
        init_sys = await self.detect_init_system(server_id)
        info["init_system"] = init_sys.value
        
        return info
    
    async def check_updates(self, server_id: str) -> CommandResult:
        """Check for available system updates."""
        server = self._config.get_server_by_id(server_id)
        if not server:
            raise ValueError(f"Server not found: {server_id}")
        
        distro = (server.distro or "").lower()
        
        if distro in ("debian", "ubuntu"):
            # Update package list and check for upgrades
            cmd = "apt update -qq && apt list --upgradable 2>/dev/null | grep -v '^Listing'"
        elif distro in ("centos", "rhel", "rocky", "alma"):
            cmd = "yum check-update -q || true"
        elif distro in ("fedora"):
            cmd = "dnf check-update -q || true"
        else:
            # Default to apt for unknown distros
            cmd = "apt update -qq && apt list --upgradable 2>/dev/null | grep -v '^Listing'"
        
        return await self.execute_sudo(server_id, cmd, timeout=120.0)
    
    async def test_connection(self, server_id: str) -> bool:
        try:
            result = await self.execute(server_id, "echo ok", timeout=10.0)
            return result.success and result.stdout.strip() == "ok"
        except Exception as e:
            logger.debug(f"Connection test failed for {server_id}: {e}")
            return False

    async def probe_connection(self, server_id: str) -> tuple[bool, Optional[str]]:
        """Like test_connection, but also returns a human-readable failure reason.

        The dashboard uses this so a down server can show *why* it's down
        (timeout / refused / auth / DNS / key) instead of a bare "not responding".
        Returns (True, None) on success, (False, reason) otherwise.
        """
        try:
            result = await self.execute(server_id, "echo ok", timeout=10.0)
            if result.success and result.stdout.strip() == "ok":
                return True, None
            raw = (result.stderr or "").strip() or f"exit code {result.exit_code}"
            return False, _friendly_ssh_error(raw)
        except Exception as e:
            logger.debug(f"Connection probe failed for {server_id}: {e}")
            return False, _friendly_ssh_error(str(e))
    
    async def test_sudo(self, server_id: str) -> bool:
        """Test if sudo works correctly on the server."""
        try:
            result = await self.execute_sudo(server_id, "whoami", timeout=10.0)
            return result.success and result.stdout.strip() == "root"
        except Exception as e:
            logger.debug(f"Sudo test failed for {server_id}: {e}")
            return False
    
    async def disconnect(self, server_id: str) -> None:
        """Drop any cached connection for one server so the next call reconnects.

        Used by the dashboard's per-server retry so a single stuck/stale host can
        be re-probed without touching the others.
        """
        await self._pool._close_connection(server_id)

    async def close(self) -> None:
        await self._pool.close_all()
    
    def get_active_connections(self) -> list[ConnectionInfo]:
        return self._pool.get_all_connections_info()


_ssh_manager: Optional[SSHManager] = None


def get_ssh_manager() -> SSHManager:
    global _ssh_manager
    if _ssh_manager is None:
        _ssh_manager = SSHManager()
    return _ssh_manager