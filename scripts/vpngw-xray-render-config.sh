#!/bin/bash
# Thin bash wrapper around vpngw-xray-render-config.py.
# Lives separately because systemd ExecStartPre wants a real executable
# path, and because some operators may want to plug a custom renderer
# without touching vpngw-xray.service.
set -euo pipefail
exec /opt/vpngateway/scripts/vpngw-xray-render-config.py "$@"
