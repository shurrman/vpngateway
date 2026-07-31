"""IP network file management endpoints."""

from fastapi import APIRouter

from models.common import ok, error
from models.networks import AddCidrsRequest, CreateNetworkRequest
from services import file_manager as fm
from services.script_runner import run_script

router = APIRouter(prefix="/networks", tags=["networks"])


@router.get("")
async def list_networks():
    files = fm.list_network_files()
    return ok({"files": [f.model_dump() for f in files]})


@router.post("")
async def create_network(req: CreateNetworkRequest):
    err = fm.create_network_file(req.name, req.description, req.cidrs)
    if err:
        return error(err)
    result = await run_script("setup-routing")
    return ok({"name": req.name, "cidrs": req.cidrs}, log=result.output)


@router.get("/{name}")
async def get_network(name: str):
    nf = fm.get_network_file(name)
    if not nf:
        return error(f"Network file {name}-networks.lst not found")
    return ok(nf.model_dump())


@router.post("/{name}")
async def add_cidrs(name: str, req: AddCidrsRequest):
    err = fm.add_cidrs_to_network(name, req.cidrs)
    if err:
        return error(err)
    result = await run_script("setup-routing")
    return ok({"added": req.cidrs}, log=result.output)


@router.delete("/{name}")
async def delete_cidrs(name: str, req: AddCidrsRequest):
    err = fm.delete_cidrs_from_network(name, req.cidrs)
    if err:
        return error(err)
    result = await run_script("setup-routing")
    return ok({"deleted": req.cidrs}, log=result.output)


@router.delete("/{name}/file")
async def delete_network_file(name: str):
    err = fm.delete_network_file(name)
    if err:
        return error(err)
    result = await run_script("setup-routing")
    return ok({"deleted_file": f"{name}-networks.lst"}, log=result.output)
