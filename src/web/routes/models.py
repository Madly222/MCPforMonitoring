"""Request and response models shared by the API routers."""

from typing import Optional

from pydantic import BaseModel


class ServerStatus(BaseModel):
    id: str
    host: str
    enabled: bool
    connected: bool
    services: list[dict]
    system_info: Optional[dict] = None


class ServiceStatusModel(BaseModel):
    name: str
    type: str
    running: bool
    enabled: str
    health: str
    pid: Optional[int] = None
    extra: Optional[dict] = None


class CommandRequest(BaseModel):
    command: str


class CommandResponse(BaseModel):
    success: bool
    interpretation: Optional[str] = None
    commands_executed: Optional[list[dict]] = None
    result: Optional[str] = None
    error: Optional[str] = None
    source: str = "local"
    # Set when the command was not run because the risk policy wants a human to confirm it
    confirmation: Optional[dict] = None


class ConfirmRequest(BaseModel):
    confirmation_id: str


class ActionRequest(BaseModel):
    server_id: str
    service_type: str
    action: str


class ActionResponse(BaseModel):
    success: bool
    message: str
    output: Optional[str] = None


class ConsoleRequest(BaseModel):
    server_id: str
    command: str
    sudo: bool = False
