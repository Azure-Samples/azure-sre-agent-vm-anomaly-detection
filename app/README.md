---
title: Demo application
description: Reporting service and intentional memory-leak incident
---

## Service

The Python HTTP service exposes health, version, report, and statistics endpoints
on port 8080. Its normal report cache is bounded, but historical reports are kept
in an intentionally unbounded archive.

`scripts/inject_traffic.sh` triggers one bulk historical export on the demo VM.
`scripts/stop_traffic.sh` restarts the service and releases its memory.
Use this application only in the dedicated demonstration environment.

`install.sh` installs the systemd unit; `deploy.sh` updates the selected source
revision and records it in `/opt/demo-app/DEPLOY_LOG`.
