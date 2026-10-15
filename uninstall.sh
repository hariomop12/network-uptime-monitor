#!/usr/bin/env bash
#
# Remove the Network Uptime Monitor systemd service.
#
#   sudo ./uninstall.sh
#
set -euo pipefail

SERVICE_NAME="uptime-monitor"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "error: please run with sudo:  sudo ./uninstall.sh" >&2
  exit 1
fi

systemctl disable --now "$SERVICE_NAME" 2>/dev/null || true
rm -f "/etc/systemd/system/$SERVICE_NAME.service"
systemctl daemon-reload

echo "Removed the $SERVICE_NAME service (logs and .env were left untouched)."
