#!/usr/bin/env bash
# On-VM deploy step. Usage: deploy.sh <git-ref> [<path-to-new-server.py>]
#   deploy.sh 3f9c2ab /var/tmp/server.py   # install new code, record ref, restart
#   deploy.sh 3f9c2ab                      # restart the current code under that ref label
# Records "<utc> deploy <ref> by <user>" in /opt/demo-app/DEPLOY_LOG and syslog so the
# deployment can be correlated with metrics (RCA).
set -euo pipefail

ref="${1:-}"
src="${2:-}"
if [[ -z "$ref" ]]; then
  echo "Usage: deploy.sh <git-ref> [<server.py>]" >&2
  exit 2
fi
who="${SUDO_USER:-$(id -un)}"
if (( EUID != 0 )); then
  exec sudo -- "$0" "$@"
fi
if [[ -n "$src" ]]; then
  python3 -m py_compile "$src"
  install -o root -g root -m 0644 "$src" /opt/demo-app/server.py
fi
printf 'DEMO_APP_VERSION=%s\n' "$ref" > /opt/demo-app/version.env
systemctl restart demo-app.service
printf '%s deploy %s by %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$ref" "$who" >> /opt/demo-app/DEPLOY_LOG
logger -t demo-app "deploy $ref by $who"
curl --fail --silent --retry 10 --retry-connrefused --retry-delay 1 \
  http://localhost:8080/version
echo
