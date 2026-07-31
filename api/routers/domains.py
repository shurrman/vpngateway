"""Domain management endpoints."""

import re

from fastapi import APIRouter

from models.common import ok, error
from models.domains import (
    AddDomainsRequest, DeleteDomainsRequest, RawDomainsRequest, DomainCheckRequest,
)
from services import file_manager as fm
from services import system_commands as sys_cmd
from services.script_runner import run_script

router = APIRouter(prefix="/domains", tags=["domains"])


@router.get("")
async def list_domains():
    """List all domain categories (one per config/domains*.lst file).
    Each category has its own groups (split inside the file by `# Comment`
    headers) and `raw` text for the editor."""
    categories = fm.read_domain_categories()
    total = sum(c["total"] for c in categories)
    return ok({"total": total, "categories": categories})


@router.post("")
async def add_domains(req: AddDomainsRequest):
    err = fm.add_domains(req.domains, req.group, req.category)
    if err:
        return error(err)
    result = await run_script("update-domains")
    if not result.success:
        return error(f"Failed to update dnsmasq config: {result.output}")
    return ok({"added": req.domains, "category": req.category}, log=result.output)


@router.delete("")
async def delete_domains(req: DeleteDomainsRequest):
    err = fm.delete_domains(req.domains, req.category)
    if err:
        return error(err)
    result = await run_script("update-domains")
    if not result.success:
        return error(f"Failed to update dnsmasq config: {result.output}")
    return ok({"deleted": req.domains}, log=result.output)


@router.put("")
async def replace_domains(req: RawDomainsRequest):
    err = fm.replace_domains_raw(req.raw, req.category)
    if err:
        return error(err)
    result = await run_script("update-domains")
    if not result.success:
        return error(f"Failed to update dnsmasq config: {result.output}")
    categories = fm.read_domain_categories()
    total = sum(c["total"] for c in categories)
    return ok({"total": total, "category": req.category}, log=result.output)


@router.post("/check")
async def check_domain(req: DomainCheckRequest):
    """Resolve a domain via dnsmasq and report whether any of its IPs
    are in the vpn_domains ipset (which determines if its traffic gets
    routed through the VPN).

    AWS console hosts return a CNAME chain in `dig +short`:
        us-west-2.console.cname-proxy.amazon.com.
        gr.aga.console-geo.us-west-2.amazonaws.com.
        a139bbb9abb3c20a4.awsglobalaccelerator.com.
        166.117.220.181
        166.117.52.212
    The old check tested ipset_test(ips[0]) on the first CNAME hostname
    and always returned False even when the actual IPs were in the set.
    Filter to numeric IPv4 only and consider the domain "in VPN" if any
    of them is in the ipset.
    """
    raw = await sys_cmd.dig_query(req.domain)
    ipv4 = [r for r in raw if re.match(r"^\d{1,3}(\.\d{1,3}){3}$", r)]
    in_ipset = False
    for ip in ipv4:
        if await sys_cmd.ipset_test(ip):
            in_ipset = True
            break
    return ok({
        "domain": req.domain,
        "resolved": raw,        # full dig chain (CNAMEs + IPs) for visibility
        "resolved_ips": ipv4,   # numeric IPs only — what we actually tested
        "in_vpn_ipset": in_ipset,
    })
