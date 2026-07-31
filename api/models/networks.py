"""Network file management models."""

from pydantic import BaseModel


class NetworkFile(BaseModel):
    name: str
    filename: str
    description: str
    entry_count: int
    entries: list[str]


class NetworksResponse(BaseModel):
    files: list[NetworkFile]


class AddCidrsRequest(BaseModel):
    cidrs: list[str]


class CreateNetworkRequest(BaseModel):
    name: str
    description: str = ""
    cidrs: list[str]


class RawNetworkRequest(BaseModel):
    raw: str
