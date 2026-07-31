"""Domain management models."""

from pydantic import BaseModel


class DomainGroup(BaseModel):
    name: str
    domains: list[str]


class DomainCategory(BaseModel):
    """One config/domains*.lst file rendered for the API."""
    id: str          # "main" / "aws" / "github" — used in mutating requests
    filename: str    # e.g. "domains-aws.lst"
    total: int
    groups: list[DomainGroup]
    raw: str


class DomainsResponse(BaseModel):
    total: int
    categories: list[DomainCategory]


class AddDomainsRequest(BaseModel):
    domains: list[str]
    group: str | None = None
    category: str = "main"


class DeleteDomainsRequest(BaseModel):
    domains: list[str]
    # If omitted, the domain is removed from whichever category contains it.
    category: str | None = None


class RawDomainsRequest(BaseModel):
    raw: str
    category: str = "main"


class DomainCheckRequest(BaseModel):
    domain: str


class DomainCheckResponse(BaseModel):
    domain: str
    resolved: list[str]      # full dig chain (CNAMEs + IPs)
    resolved_ips: list[str]  # IPv4 only
    in_vpn_ipset: bool
