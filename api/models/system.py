"""System and service models."""

from pydantic import BaseModel


class InterfaceInfo(BaseModel):
    name: str
    up: bool
    ip_address: str | None = None
    tx_bytes: int = 0
    rx_bytes: int = 0


class ServiceInfo(BaseModel):
    name: str
    description: str = ""
    active: bool
    state: str
    enabled: bool


class SystemResources(BaseModel):
    uptime: str
    load_average: list[float]
    memory_total_mb: int
    memory_used_mb: int
    memory_percent: float
    cpu_count: int


class DashboardStatus(BaseModel):
    vpn: InterfaceInfo
    lan: InterfaceInfo
    services: dict[str, bool]
    domains_count: int
    ipset_entries: int
    resources: SystemResources


class IpsetInfo(BaseModel):
    name: str
    type: str
    entries: int
    max_entries: int
    memory_bytes: int


class IpRuleInfo(BaseModel):
    priority: int
    selector: str
    action: str


class RouteInfo(BaseModel):
    destination: str
    gateway: str | None = None
    device: str
    extra: str = ""
