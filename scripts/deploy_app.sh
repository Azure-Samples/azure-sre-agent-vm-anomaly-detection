#!/usr/bin/env bash
# Deploy app/server.py at a git ref to vm-app-01 through Azure VM Run Command.
#   scripts/deploy_app.sh main
#   scripts/deploy_app.sh <sha-or-branch>
# The VM never needs GitHub access: the file is read from this checkout (git show) and shipped
# base64-encoded inside the Run Command script. deploy.sh on the VM records the ref in
# /opt/demo-app/DEPLOY_LOG + syslog and restarts demo-app.service.
set -euo pipefail

ref="${1:-main}"
rg="${VM_ANOMALY_RG:-rg-vm-anomaly-demo}"
vm="${VM_ANOMALY_VM:-vm-app-01}"
repo_root="$(cd "$(dirname "$0")/.." && pwd)"

# The ref is interpolated into a root shell script on the VM: allow only plain git ref chars.
if [[ ! "$ref" =~ ^[A-Za-z0-9][A-Za-z0-9._/@-]*$ ]]; then
  echo "refusing ref with unexpected characters: $ref" >&2
  exit 2
fi
if ! git -C "$repo_root" rev-parse --verify --quiet "$ref^{commit}" >/dev/null; then
  git -C "$repo_root" fetch --quiet origin
fi
sha="$(git -C "$repo_root" rev-parse --short=12 "$ref^{commit}")"
label="$sha"
[[ "$ref" != "$sha" && "$ref" != "$(git -C "$repo_root" rev-parse "$ref")" ]] && label="$ref@$sha"
payload="$(git -C "$repo_root" show "$sha:app/server.py" | base64 -w0)"
deploy_sh="$(git -C "$repo_root" show "$sha:app/deploy.sh" | base64 -w0)"
unit="$(git -C "$repo_root" show "$sha:app/demo-app.service" | base64 -w0)"

script="set -e
printf '%s' '$deploy_sh' | base64 -d > /var/tmp/deploy.sh
install -o root -g root -m 0755 /var/tmp/deploy.sh /opt/demo-app/deploy.sh
printf '%s' '$unit' | base64 -d > /var/tmp/demo-app.service
if ! cmp -s /var/tmp/demo-app.service /etc/systemd/system/demo-app.service; then
  install -o root -g root -m 0644 /var/tmp/demo-app.service /etc/systemd/system/demo-app.service
  systemctl daemon-reload
fi
printf '%s' '$payload' | base64 -d > /var/tmp/server.py
/opt/demo-app/deploy.sh '$label' /var/tmp/server.py"

echo "deploying app/server.py@$label to $vm ($rg)" >&2
az vm run-command invoke -g "$rg" -n "$vm" --command-id RunShellScript \
  --scripts "$script" --query 'value[0].message' -o tsv
