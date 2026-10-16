#!/usr/bin/env bash
# Deploy the detector to the Function App created by infra/ (rg-vm-anomaly-demo).
#   detector/deploy.sh [function-app-name] [resource-group]
# Requires: az (logged in). Uses `func` (Azure Functions Core Tools) if present,
# otherwise zip deploy with remote build. detector/model/ must contain model.pkl +
# metadata.json (run `python -m detector.make_placeholder_model` for a placeholder).
set -euo pipefail

RG="${2:-${RESOURCE_GROUP:-rg-vm-anomaly-demo}}"
APP="${1:-${FUNCTION_APP:-}}"
HERE="$(cd "$(dirname "$0")" && pwd)"

if [[ -z "$APP" ]]; then
  APP="$(az functionapp list -g "$RG" --query "[?starts_with(name,'func-vm-anomaly')].name | [0]" -o tsv)"
  [[ -n "$APP" ]] || { echo "no func-vm-anomaly-* app in $RG; pass the name as arg 1" >&2; exit 1; }
fi
[[ -f "$HERE/model/model.pkl" && -f "$HERE/model/metadata.json" ]] || {
  echo "detector/model/{model.pkl,metadata.json} missing" >&2; exit 1; }

echo "deploying $HERE -> $APP ($RG)"
if command -v func >/dev/null 2>&1; then
  (cd "$HERE" && func azure functionapp publish "$APP" --python)
else
  ZIP="$(mktemp -d)/detector.zip"
  (cd "$HERE" && zip -qr "$ZIP" . -x@.funcignore -x '.venv/*' -x '__pycache__/*' -x 'local.settings.json')
  az functionapp deployment source config-zip -g "$RG" -n "$APP" --src "$ZIP" --build-remote true --timeout 900 -o none
  rm -f "$ZIP"
fi
echo "done. tail logs: az webapp log tail -g $RG -n $APP"
