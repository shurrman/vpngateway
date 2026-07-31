#!/bin/bash
# Bash wrapper around vpngw-xray-stats.py — included for symmetry with
# the rest of the helper-script family (router calls `xray-stats` by
# short name via the SCRIPTS whitelist in api/config.py).
set -euo pipefail
exec /opt/vpngateway/scripts/vpngw-xray-stats.py "$@"
