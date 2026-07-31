#!/usr/bin/env python3
"""
Adapt a raw AmneziaWG config (extracted from .vpn via amnezia_vpn_to_wg_config)
into a gateway-ready config: drop the DNS line (gateway runs its own dnsmasq),
ensure `Table = off`, and wire up PostUp/PostDown route hooks.

Usage:
    vpngw-adapt-amneziawg.py <input.conf> <output.conf>

Idempotent — running it on an already-adapted config is a no-op.
"""

import sys
from pathlib import Path

POSTUP = "PostUp = /opt/vpngateway/scripts/vpngw-fix-routes.sh"
POSTDOWN = "PostDown = /opt/vpngateway/scripts/vpngw-on-vpn-down.sh"
SKIP_LEADING_COMMENT_PREFIXES = (
    "# Generated on:", "# VPN Key:", "# Keenetic:",
)
OPTIONAL_EMPTY_INTERFACE_KEYS = {
    "I1", "I2", "I3", "I4", "I5",
}


def adapt(raw: str) -> str:
    lines = raw.splitlines()
    out: list[str] = []
    section: str | None = None
    has_table = has_postup = has_postdown = False
    interface_done = False

    def flush_interface_extras():
        """Append Table/PostUp/PostDown to the [Interface] block if missing."""
        nonlocal has_table, has_postup, has_postdown
        if not has_table:
            out.append("Table = off")
            has_table = True
        if not has_postup:
            out.append(POSTUP)
            has_postup = True
        if not has_postdown:
            out.append(POSTDOWN)
            has_postdown = True

    # Skip leading generator comments + first blank line(s)
    skip_leading = True
    for line in lines:
        stripped = line.strip()

        if skip_leading:
            if not stripped:
                continue
            if stripped.startswith(SKIP_LEADING_COMMENT_PREFIXES):
                continue
            skip_leading = False

        # Section header
        if stripped.startswith("[") and stripped.endswith("]"):
            if section == "Interface" and not interface_done:
                flush_interface_extras()
                if out and out[-1].strip():
                    out.append("")  # blank line between sections
                interface_done = True
            section = stripped[1:-1]
            out.append(line)
            continue

        if section == "Interface":
            if "=" in stripped:
                key, value = stripped.split("=", 1)
                key = key.strip()
                if key in OPTIONAL_EMPTY_INTERFACE_KEYS and not value.strip():
                    continue
            if stripped.startswith("DNS"):
                # Drop — dnsmasq on the gateway handles DNS.
                continue
            if stripped.startswith("Table"):
                has_table = True
            elif stripped.startswith("PostUp"):
                has_postup = True
            elif stripped.startswith("PostDown"):
                has_postdown = True

        out.append(line)

    # If we never saw a [Peer] section, flush at the end.
    if section == "Interface" and not interface_done:
        flush_interface_extras()

    text = "\n".join(out).rstrip() + "\n"
    return text


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    src, dst = Path(argv[1]), Path(argv[2])
    if not src.is_file():
        print(f"error: input not found: {src}", file=sys.stderr)
        return 2
    dst.write_text(adapt(src.read_text()))
    dst.chmod(0o600)
    print(f"adapted {src} -> {dst}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
