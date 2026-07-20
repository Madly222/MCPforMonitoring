"""
Configuration loader for MCP Server Monitor.

Loads and validates configuration from YAML files:
- secrets.yaml: Sensitive data (servers, credentials, API keys)
- config/settings.yaml: General settings
- config/services/*.yaml: Service-specific configurations
"""

import os
import sys
from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import BaseModel, Field, field_validator
from loguru import logger


def get_project_root() -> Path:
    return Path(__file__).parent.parent.parent


PROJECT_ROOT = get_project_root()
CONFIG_DIR = PROJECT_ROOT / "config"
SECRETS_FILE = PROJECT_ROOT / "secrets.yaml"
SETTINGS_FILE = CONFIG_DIR / "settings.yaml"
SERVICES_DIR = CONFIG_DIR / "services"
KEYS_DIR = PROJECT_ROOT / "keys"
KNOWLEDGE_DIR = PROJECT_ROOT / "knowledge_base"
LOGS_DIR = PROJECT_ROOT / "logs"
SESSIONS_DIR = PROJECT_ROOT / "sessions"


# Service types the monitor has handlers for (mirrors service_handlers /
# config/services/<type>.yaml). New types are added in code alongside a handler
# class; the superadmin console only lets operators pick from this list, never
# invent new ones. Extend this tuple when you add a handler.
VALID_SERVICE_TYPES = ("dhcp", "dns", "radius")


class ServerConfig(BaseModel):
    id: str
    host: str
    port: int = 22
    user: str
    auth_type: str = "key"
    auth_value: str
    sudo_password: Optional[str] = None
    distro: Optional[str] = None
    services: list[str] = Field(default_factory=list)
    enabled: bool = True

    @field_validator("auth_type")
    @classmethod
    def validate_auth_type(cls, v: str) -> str:
        if v not in ("key", "password"):
            raise ValueError("auth_type must be 'key' or 'password'")
        return v


# ==============================================================================
# ONU MONITORING MODELS
# ==============================================================================

class OLTConfig(BaseModel):
    """Configuration for a single OLT device."""
    id: str
    host: str
    port: int = 161
    community: Optional[str] = "public"
    version: str = "2c"
    vendor: str = "zte"
    enabled: bool = True
    # SSH for MAC retrieval
    ssh_username: Optional[str] = None
    ssh_password: Optional[str] = None
    ssh_port: int = 22
    # SNMPv3 fields
    username: Optional[str] = None
    auth_proto: Optional[str] = None
    auth_pass: Optional[str] = None
    priv_proto: Optional[str] = None
    priv_pass: Optional[str] = None

    @field_validator("version")
    @classmethod
    def validate_version(cls, v: str) -> str:
        if v not in ("2c", "3"):
            raise ValueError("version must be '2c' or '3'")
        return v

    @field_validator("vendor")
    @classmethod
    def validate_vendor(cls, v: str) -> str:
        if v not in ("zte", "huawei"):
            raise ValueError("vendor must be 'zte' or 'huawei'")
        return v


class ONUThresholds(BaseModel):
    """Signal level thresholds for ONU monitoring."""
    good: float = -20.0
    warning: float = -25.0


class ONUMonitoringConfig(BaseModel):
    """ONU monitoring configuration."""
    poll_interval: int = 60
    thresholds: ONUThresholds = Field(default_factory=ONUThresholds)
    olts: list[OLTConfig] = Field(default_factory=list)


# ==============================================================================
# OTHER MODELS
# ==============================================================================

class MCPServerConfig(BaseModel):
    web_host: str = "0.0.0.0"
    web_port: int = 4455
    session_secret: str
    session_expire_hours: int = 24


class ClaudeConfig(BaseModel):
    api_key: str
    model: str = "claude-sonnet-4-20250514"
    max_tokens: int = 1024
    timeout_seconds: int = 30


class EmailConfig(BaseModel):
    enabled: bool = False
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_tls: bool = True
    from_address: str = ""
    to_addresses: list[str] = Field(default_factory=list)


class WebUserConfig(BaseModel):
    username: str
    password: str
    role: str = "operator"

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        if v not in ("admin", "operator", "superadmin"):
            raise ValueError("role must be 'superadmin', 'admin' or 'operator'")
        return v


class SecretsConfig(BaseModel):
    servers: list[ServerConfig] = Field(default_factory=list)
    onu_monitoring: Optional[ONUMonitoringConfig] = None
    mcp_server: MCPServerConfig
    claude: ClaudeConfig
    email: EmailConfig = Field(default_factory=EmailConfig)
    web_users: list[WebUserConfig] = Field(default_factory=list)

    def get_server_password(self, server_id: str) -> str:
        for server in self.servers:
            if server.id == server_id and server.auth_type == "password":
                return server.auth_value
        return ""
    
    def get_sudo_password(self, server_id: str) -> Optional[str]:
        for server in self.servers:
            if server.id == server_id:
                if server.sudo_password:
                    return server.sudo_password
                if server.auth_type == "password":
                    return server.auth_value
        return None


class MonitoringRealtimeConfig(BaseModel):
    enabled: bool = True
    reconnect_delay_seconds: int = 5
    max_reconnect_attempts: int = 10


class MonitoringPollingConfig(BaseModel):
    interval_seconds: int = 300


class MonitoringHealthCheckConfig(BaseModel):
    interval_seconds: int = 60
    timeout_seconds: int = 10


class MonitoringAggregationConfig(BaseModel):
    wait_seconds: int = 30
    max_errors_per_batch: int = 10


class MonitoringConfig(BaseModel):
    realtime: MonitoringRealtimeConfig = Field(default_factory=MonitoringRealtimeConfig)
    polling: MonitoringPollingConfig = Field(default_factory=MonitoringPollingConfig)
    health_check: MonitoringHealthCheckConfig = Field(default_factory=MonitoringHealthCheckConfig)
    aggregation: MonitoringAggregationConfig = Field(default_factory=MonitoringAggregationConfig)


class ErrorProcessingConfig(BaseModel):
    dedup_window_seconds: int = 300
    min_severity: str = "warning"
    context_lines: int = 50


class ClaudeCacheConfig(BaseModel):
    enabled: bool = True
    ttl_hours: int = 24


class ClaudeRateLimitConfig(BaseModel):
    max_requests_per_minute: int = 10
    max_requests_per_hour: int = 100


class ClaudeOptimizationConfig(BaseModel):
    cache: ClaudeCacheConfig = Field(default_factory=ClaudeCacheConfig)
    rate_limit: ClaudeRateLimitConfig = Field(default_factory=ClaudeRateLimitConfig)


class LoggingRotationConfig(BaseModel):
    max_size_mb: int = 10
    backup_count: int = 5


class LoggingConfig(BaseModel):
    level: str = "INFO"
    rotation: LoggingRotationConfig = Field(default_factory=LoggingRotationConfig)
    format: str = "{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} | {message}"


class WebUIConfig(BaseModel):
    static_dir: str = "web"
    rate_limit_requests_per_minute: int = 60


class IncidentsStorageConfig(BaseModel):
    format: str = "json"
    directory: str = "logs/incidents"


class IncidentsConfig(BaseModel):
    storage: IncidentsStorageConfig = Field(default_factory=IncidentsStorageConfig)
    retention_days: int = 90


class SettingsConfig(BaseModel):
    monitoring: MonitoringConfig = Field(default_factory=MonitoringConfig)
    error_processing: ErrorProcessingConfig = Field(default_factory=ErrorProcessingConfig)
    claude_optimization: ClaudeOptimizationConfig = Field(default_factory=ClaudeOptimizationConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    web_ui: WebUIConfig = Field(default_factory=WebUIConfig)
    incidents: IncidentsConfig = Field(default_factory=IncidentsConfig)


class ConfigLoader:
    
    _instance: Optional["ConfigLoader"] = None
    _secrets: Optional[SecretsConfig] = None
    _settings: Optional[SettingsConfig] = None
    _service_configs: dict[str, dict[str, Any]] = {}
    
    def __new__(cls) -> "ConfigLoader":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def load_yaml(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            raise FileNotFoundError(f"Configuration file not found: {path}")
        
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        
        return data or {}
    
    def load_secrets(self, path: Optional[Path] = None) -> SecretsConfig:
        if self._secrets is not None:
            return self._secrets
        
        secrets_path = path or SECRETS_FILE
        
        if not secrets_path.exists():
            logger.error(f"Secrets file not found: {secrets_path}")
            logger.info("Please copy secrets.example.yaml to secrets.yaml and configure it")
            sys.exit(1)
        
        try:
            data = self.load_yaml(secrets_path)
            self._secrets = SecretsConfig(**data)
            self._merge_runtime_overrides()
            logger.info("Secrets configuration loaded successfully")
            return self._secrets
        except Exception as e:
            logger.error(f"Failed to load secrets: {e}")
            sys.exit(1)
    
    def _merge_runtime_overrides(self) -> None:
        """
        Merge web-edited server/OLT overrides over secrets.yaml.
        
        Seed-and-own: on first load the runtime store is seeded from secrets.yaml;
        afterwards the store is the source of truth. Any failure here is non-fatal
        and falls back to the secrets.yaml values so startup never breaks.
        """
        try:
            import src.web.runtime_config as rc
        except Exception:
            return
        
        try:
            if not rc.servers_seeded():
                rc.seed_servers([s.model_dump() for s in self._secrets.servers])
            # Rebuild per-entry so one malformed stored server is skipped (and
            # logged) instead of discarding every runtime edit for the fleet.
            merged = []
            for d in rc.get_servers():
                try:
                    merged.append(ServerConfig(**d))
                except Exception as ex:
                    logger.error(
                        f"Skipping invalid server '{d.get('id', '?')}' "
                        f"from runtime store: {ex}"
                    )
            self._secrets.servers = merged
        except Exception as e:
            logger.error(f"Runtime server override skipped (using secrets.yaml): {e}")
        
        try:
            if self._secrets.onu_monitoring is not None:
                if not rc.olts_seeded():
                    rc.seed_olts([o.model_dump() for o in self._secrets.onu_monitoring.olts])
                self._secrets.onu_monitoring.olts = [
                    OLTConfig(**d) for d in rc.get_olts()
                ]
        except Exception as e:
            logger.error(f"Runtime OLT override skipped (using secrets.yaml): {e}")
    
    def load_settings(self, path: Optional[Path] = None) -> SettingsConfig:
        if self._settings is not None:
            return self._settings
        
        settings_path = path or SETTINGS_FILE
        
        if not settings_path.exists():
            logger.warning(f"Settings file not found: {settings_path}, using defaults")
            self._settings = SettingsConfig()
            return self._settings
        
        try:
            data = self.load_yaml(settings_path)
            self._settings = SettingsConfig(**data)
            logger.info("Settings configuration loaded successfully")
            return self._settings
        except Exception as e:
            logger.warning(f"Failed to load settings: {e}, using defaults")
            self._settings = SettingsConfig()
            return self._settings
    
    def load_service_config(self, service_type: str) -> dict[str, Any]:
        if service_type in self._service_configs:
            return self._service_configs[service_type]
        
        service_file = SERVICES_DIR / f"{service_type}.yaml"
        
        if not service_file.exists():
            logger.warning(f"Service config not found: {service_file}")
            return {}
        
        try:
            data = self.load_yaml(service_file)
            self._service_configs[service_type] = data
            logger.debug(f"Service config loaded: {service_type}")
            return data
        except Exception as e:
            logger.warning(f"Failed to load service config {service_type}: {e}")
            return {}
    
    def get_enabled_servers(self) -> list[ServerConfig]:
        secrets = self.load_secrets()
        return [s for s in secrets.servers if s.enabled]
    
    def get_server_by_id(self, server_id: str) -> Optional[ServerConfig]:
        secrets = self.load_secrets()
        for server in secrets.servers:
            if server.id == server_id:
                return server
        return None
    
    def get_ssh_key_path(self, key_filename: str) -> Path:
        return KEYS_DIR / key_filename
    
    def get_sudo_password(self, server_id: str) -> Optional[str]:
        secrets = self.load_secrets()
        return secrets.get_sudo_password(server_id)
    
    # ONU Configuration methods
    def get_onu_monitoring_config(self) -> Optional[ONUMonitoringConfig]:
        secrets = self.load_secrets()
        return secrets.onu_monitoring
    
    def get_enabled_olts(self) -> list[OLTConfig]:
        config = self.get_onu_monitoring_config()
        if config:
            return [olt for olt in config.olts if olt.enabled]
        return []
    
    def get_olt_by_id(self, olt_id: str) -> Optional[OLTConfig]:
        config = self.get_onu_monitoring_config()
        if config:
            for olt in config.olts:
                if olt.id == olt_id:
                    return olt
        return None
    
    def reload(self) -> None:
        self._secrets = None
        self._settings = None
        self._service_configs = {}
        logger.info("Configuration reload requested")


def get_config() -> ConfigLoader:
    return ConfigLoader()