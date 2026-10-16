#!/usr/bin/env bash
# First-time install on the VM (run by cloud-init from infra/modules/vm.bicep).
# /opt/demo-app is root-owned; the demoapp service user can only read it.
set -euo pipefail

source_dir="$(cd "$(dirname "$0")" && pwd)"
ref="${DEMO_APP_REF:-bootstrap}"
if (( EUID != 0 )); then
  exec sudo -- "$0"
fi
id demoapp &>/dev/null || useradd --system --no-create-home --shell /usr/sbin/nologin demoapp
install -d -o root -g root -m 0755 /opt/demo-app
install -o root -g root -m 0644 "$source_dir/server.py" /opt/demo-app/server.py
install -o root -g root -m 0755 "$source_dir/deploy.sh" /opt/demo-app/deploy.sh
install -o root -g root -m 0644 "$source_dir/demo-app.service" /etc/systemd/system/demo-app.service
touch /opt/demo-app/DEPLOY_LOG
chmod 0644 /opt/demo-app/DEPLOY_LOG
systemctl daemon-reload
systemctl enable demo-app.service
/opt/demo-app/deploy.sh "$ref"
