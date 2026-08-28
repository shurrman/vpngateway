"""LAN host discovery and runtime access-control models."""

from pydantic import BaseModel


class HostInfo(BaseModel):
    ip: str
    hostname: str = ""
    mac: str
    device: str = ""
    vpn_allowed: bool = True


class HostAccessRequest(BaseModel):
    enabled: bool
