#!/usr/bin/env bash
#
# Install the Network Uptime Monitor as a systemd service.
#
#   sudo ./install.sh
#
set -euo pipefail

SERVICE_NAME="uptime-monitor"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PY="$PROJECT_DIR/.venv/bin/python"
RUN_USER="${SUDO_USER:-$(id -un)}"

die() { echo "error: $*" >&2; exit 1; }

if [[ "$(id -u)" -ne 0 ]]; then
  die "please run with sudo:  sudo ./install.sh"
fi

[[ -f "$PROJECT_DIR/config.yaml" ]] || die "config.yaml not found in $PROJECT_DIR"
if [[ ! -f "$PROJECT_DIR/.env" ]]; then
  echo "warning: .env not found - alerts will be disabled (copy .env.example to .env)"
fi

echo "==> Installing Python dependencies"
if [[ ! -x "$VENV_PY" ]]; then
  sudo -u "$RUN_USER" python3 -m venv "$PROJECT_DIR/.venv"
fi
sudo -u "$RUN_USER" "$PROJECT_DIR/.venv/bin/pip" install --upgrade pip -q
sudo -u "$RUN_USER" "$PROJECT_DIR/.venv/bin/pip" install -r "$PROJECT_DIR/requirements.txt" -q

echo "==> Granting CAP_NET_RAW to the venv interpreter (for raw ICMP)"
command -v setcap >/dev/null 2>&1 || die "setcap not found - install libcap2-bin"
setcap cap_net_raw+ep "$VENV_PY"

echo "==> Writing /etc/systemd/system/$SERVICE_NAME.service"
cat > "/etc/systemd/system/$SERVICE_NAME.service" <<EOF
[Unit]
Description=Network Uptime Monitor
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$RUN_USER
WorkingDirectory=$PROJECT_DIR
ExecStart=$VENV_PY $PROJECT_DIR/monitor.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

echo "==> Enabling and starting the service"
systemctl daemon-reload
systemctl enable --now "$SERVICE_NAME"

echo
echo "Installed. Useful commands:"
echo "  systemctl status  $SERVICE_NAME"
echo "  journalctl -u $SERVICE_NAME -f"
echo "  sudo systemctl restart $SERVICE_NAME"
