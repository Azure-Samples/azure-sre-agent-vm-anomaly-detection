"""Shared Azure ML settings."""

from __future__ import annotations

import json
import os
from pathlib import Path

from azure.ai.ml import MLClient
from azure.identity import DefaultAzureCredential

RESOURCE_GROUP = "rg-vm-anomaly-ml"
WORKSPACE = "mlw-vm-anomaly"
LOCATION = "eastus2"
MODEL_NAME = "vm-anomaly-detector"
COMPUTE = "cpu-ds3v2"
COMPUTE_SIZE = "Standard_DS3_v2"

HERE = Path(__file__).resolve().parent
LAST_JOB = HERE / ".last_job.json"


def credential() -> DefaultAzureCredential:
    return DefaultAzureCredential(exclude_interactive_browser_credential=True)


def ml_client(workspace: str | None = WORKSPACE) -> MLClient:
    subscription_id = os.environ.get("AZURE_SUBSCRIPTION_ID", "").strip()
    if not subscription_id:
        raise SystemExit("Set AZURE_SUBSCRIPTION_ID before using Azure ML")
    return MLClient(credential(), subscription_id, RESOURCE_GROUP, workspace)


def save_last_job(info: dict) -> None:
    LAST_JOB.write_text(json.dumps(info, indent=2))


def last_job_name() -> str:
    if not LAST_JOB.exists():
        raise SystemExit("no job recorded - pass --job <name> or run ml.azureml.submit first")
    return json.loads(LAST_JOB.read_text())["name"]
