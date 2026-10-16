"""Submit ``job.yaml`` to the Azure ML workspace provisioned by infra/main.bicep and wait.

    az login ...   # service principal or user, see docs/04-demo-runbook.md
    python -m ml.azureml.submit            # submit + stream logs until done
    python -m ml.azureml.submit --no-wait

Workspace ``mlw-vm-anomaly`` (rg-vm-anomaly-ml) and its ``Standard_DS3_v2`` cluster (0..1 nodes)
are declared in infra/modules/ml.bicep; run ``infra/deploy.sh`` first.
"""

from __future__ import annotations

import argparse
import shutil
import time

from azure.ai.ml import load_job
from azure.core.exceptions import ResourceNotFoundError

from ml.azureml.common import (
    COMPUTE,
    HERE,
    RESOURCE_GROUP,
    WORKSPACE,
    ml_client,
    save_last_job,
)

ML_DIR = HERE.parent
STAGE = HERE / "src"
TERMINAL = {"Completed", "Failed", "Canceled", "NotResponding"}


def require_infra(client) -> None:
    """Fail fast with a pointer to infra/ if the Bicep-managed workspace/cluster are missing."""
    try:
        client.compute.get(COMPUTE)
    except ResourceNotFoundError as e:
        raise SystemExit(
            f"{WORKSPACE}/{COMPUTE} not found in {RESOURCE_GROUP}: run infra/deploy.sh "
            "(infra/modules/ml.bicep) first"
        ) from e


def stage_code() -> None:
    """Copy the ml package (without raw data / caches) into ./src for upload."""
    if STAGE.exists():
        shutil.rmtree(STAGE)
    shutil.copytree(
        ML_DIR,
        STAGE / "ml",
        ignore=shutil.ignore_patterns("raw", "__pycache__", "src", ".last_job.json", "*.pyc"),
    )


def wait(client, name: str, poll_s: int = 30) -> str:
    """Poll until the job is terminal (``jobs.stream`` needs storage-key access)."""
    last = None
    while True:
        status = client.jobs.get(name).status
        if status != last:
            print(f"{time.strftime('%H:%M:%S')} {name}: {status}", flush=True)
            last = status
        if status in TERMINAL:
            return status
        time.sleep(poll_s)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--no-wait", action="store_true")
    ap.add_argument("--wait-for", default=None, help="only wait for an existing job")
    args = ap.parse_args(argv)
    if args.wait_for:
        client = ml_client()
        status = wait(client, args.wait_for)
        info = {"name": args.wait_for, "studio_url": client.jobs.get(args.wait_for).studio_url}
        save_last_job({**info, "status": status})
        raise SystemExit(0 if status == "Completed" else 1)

    client = ml_client()
    require_infra(client)
    stage_code()

    job = client.jobs.create_or_update(load_job(HERE / "job.yaml"))
    info = {"name": job.name, "studio_url": job.studio_url}
    save_last_job(info)
    print(f"submitted job {job.name}\n{job.studio_url}")
    if not args.no_wait:
        status = wait(client, job.name)
        save_last_job({**info, "status": status})
        print(f"job {job.name}: {status}")
        if status != "Completed":
            raise SystemExit(1)


if __name__ == "__main__":
    main()
