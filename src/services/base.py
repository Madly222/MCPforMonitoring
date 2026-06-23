"""
Base Service Handler.

Abstract base class for all service-specific handlers.
Provides common interface for service monitoring and management.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Any
from enum import Enum

from loguru import logger

from src.core.ssh_manager import SSHManager, CommandResult, ServiceStatus
from src.core.config import get_config


class ServiceState(Enum):
    RUNNING = "running"
    STOPPED = "stopped"
    FAILED = "failed"
    UNKNOWN = "unknown"


class HealthStatus(Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass
class ServiceInfo:
    server_id: str
    service_type: str
    service_name: str
    process_name: str
    state: ServiceState
    health: HealthStatus
    pid: Optional[int] = None
    config_file: Optional[str] = None
    log_files: list[str] = field(default_factory=list)
    extra_info: dict[str, Any] = field(default_factory=dict)
    checked_at: datetime = field(default_factory=datetime.now)


@dataclass
class HealthCheckResult:
    name: str
    passed: bool
    message: str
    details: Optional[dict] = None


@dataclass
class DiagnosticResult:
    name: str
    success: bool
    output: str
    error: Optional[str] = None


class BaseService(ABC):
    
    service_type: str = "generic"
    
    def __init__(self, ssh_manager: SSHManager, server_id: str):
        self.ssh = ssh_manager
        self.server_id = server_id
        self.config = get_config()
        self._service_config: Optional[dict] = None
        self._detected_service: Optional[dict] = None
        self._config_file: Optional[str] = None
        self._leases_file: Optional[str] = None
    
    @property
    def service_config(self) -> dict:
        if self._service_config is None:
            self._service_config = self.config.load_service_config(self.service_type)
        return self._service_config
    
    async def detect(self) -> Optional[dict]:
        if self._detected_service is not None:
            return self._detected_service
        
        detection = self.service_config.get("detection", {}).get("commands", [])
        
        for det in detection:
            result = await self.ssh.execute(self.server_id, det["check"], timeout=10.0)
            if result.success and "found" in result.stdout:
                self._detected_service = det
                logger.debug(f"Detected {det['name']} on {self.server_id}")
                return det
        
        logger.warning(f"No {self.service_type} service detected on {self.server_id}")
        return None
    
    async def get_service_name(self) -> Optional[str]:
        det = await self.detect()
        return det["service_name"] if det else None
    
    async def get_process_name(self) -> Optional[str]:
        det = await self.detect()
        return det.get("process_name", det["service_name"]) if det else None
    
    async def get_status(self) -> ServiceStatus:
        service_name = await self.get_service_name()
        process_name = await self.get_process_name()
        
        if not service_name:
            return ServiceStatus(
                service_name="unknown",
                process_name="unknown",
                running=False,
                enabled="unknown"
            )
        
        return await self.ssh.check_service_status(
            self.server_id,
            service_name,
            process_name
        )
    
    async def get_config_file(self) -> Optional[str]:
        if self._config_file is not None:
            return self._config_file
        
        det = await self.detect()
        if not det:
            return None
        
        file_paths = self.service_config.get("file_paths", {}).get(det["name"], {})
        config_paths = file_paths.get("config", [])
        
        if config_paths:
            self._config_file = await self.ssh.find_existing_file(
                self.server_id,
                config_paths
            )
        
        return self._config_file
    
    async def restart(self) -> CommandResult:
        service_name = await self.get_service_name()
        if not service_name:
            return CommandResult(
                server_id=self.server_id,
                command="restart",
                stdout="",
                stderr="Service not detected",
                exit_code=-1
            )
        
        logger.info(f"Restarting {service_name} on {self.server_id}")
        return await self.ssh.restart_service(self.server_id, service_name)
    
    async def start(self) -> CommandResult:
        service_name = await self.get_service_name()
        if not service_name:
            return CommandResult(
                server_id=self.server_id,
                command="start",
                stdout="",
                stderr="Service not detected",
                exit_code=-1
            )
        
        return await self.ssh.start_service(self.server_id, service_name)
    
    async def stop(self) -> CommandResult:
        service_name = await self.get_service_name()
        if not service_name:
            return CommandResult(
                server_id=self.server_id,
                command="stop",
                stdout="",
                stderr="Service not detected",
                exit_code=-1
            )
        
        return await self.ssh.stop_service(self.server_id, service_name)
    
    async def reload(self) -> CommandResult:
        service_name = await self.get_service_name()
        if not service_name:
            return CommandResult(
                server_id=self.server_id,
                command="reload",
                stdout="",
                stderr="Service not detected",
                exit_code=-1
            )
        
        return await self.ssh.reload_service(self.server_id, service_name)
    
    async def get_info(self) -> ServiceInfo:
        det = await self.detect()
        status = await self.get_status()
        config_file = await self.get_config_file()
        health = await self.check_health()
        
        if status.running:
            state = ServiceState.RUNNING
        else:
            state = ServiceState.STOPPED
        
        health_status = HealthStatus.HEALTHY
        for check in health:
            if not check.passed:
                health_status = HealthStatus.UNHEALTHY
                break
        
        return ServiceInfo(
            server_id=self.server_id,
            service_type=self.service_type,
            service_name=det["service_name"] if det else "unknown",
            process_name=det.get("process_name", "") if det else "unknown",
            state=state,
            health=health_status,
            pid=status.pid,
            config_file=config_file,
            log_files=await self.get_log_files(),
            extra_info=await self.get_extra_info()
        )
    
    async def get_log_files(self) -> list[str]:
        det = await self.detect()
        if not det:
            return []
        
        log_config = self.service_config.get("log_files", {}).get(det["name"], [])
        
        log_files = []
        for log in log_config:
            path = log.get("path") if isinstance(log, dict) else log
            if await self.ssh.file_exists(self.server_id, path):
                log_files.append(path)
        
        return log_files
    
    async def get_recent_logs(self, lines: int = 50) -> str:
        log_files = await self.get_log_files()
        
        if not log_files:
            return "No log files found for this service"
        
        log_file = log_files[0]
        
        result = await self.ssh.execute(
            self.server_id,
            f"tail -n {lines} {log_file} 2>/dev/null || echo 'Cannot read log file'"
        )
        
        return result.stdout if result.success else f"Error: {result.stderr}"
    
    @abstractmethod
    async def check_health(self) -> list[HealthCheckResult]:
        pass
    
    @abstractmethod
    async def get_extra_info(self) -> dict[str, Any]:
        pass
    
    @abstractmethod
    async def run_diagnostic(self, name: str) -> DiagnosticResult:
        pass