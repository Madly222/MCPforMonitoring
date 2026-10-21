"""The service handlers by service type. Register a new handler here."""

from src.services.base import BaseService
from src.services.dhcp import DHCPService
from src.services.dns import DNSService
from src.services.radius import RADIUSService

SERVICE_HANDLERS: dict[str, type[BaseService]] = {
    "dhcp": DHCPService,
    "dns": DNSService,
    "radius": RADIUSService,
}
