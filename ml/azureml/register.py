"""Register the ``model`` output of a completed job as ``vm-anomaly-detector``.

python -m ml.azureml.register              # last job submitted by ml.azureml.submit
python -m ml.azureml.register --job <name>
"""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from azure.ai.ml.constants import AssetTypes
from azure.ai.ml.entities import Model

from ml.azureml.common import MODEL_NAME, last_job_name, ml_client


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--job", default=None, help="job name (default: last submitted)")
    args = ap.parse_args(argv)
    job_name = args.job or last_job_name()
    client = ml_client()

    job = client.jobs.get(job_name)
    if job.status != "Completed":
        raise SystemExit(f"job {job_name} is {job.status}, not Completed")

    with tempfile.TemporaryDirectory() as tmp:
        client.jobs.download(job_name, download_path=tmp, output_name="model")
        md_path = next(Path(tmp).rglob("metadata.json"))
        md = json.loads(md_path.read_text())
    m = md["metrics"]["mean"]
    tags = {
        "job": job_name,
        "model": md["model"],
        "trained_on": md["dataset"],
        "window": str(md["window"]),
        "threshold": str(md["threshold"]),
        "f1": f"{m['f1']:.3f}",
        "pa_f1": f"{m['pa_f1']:.3f}",
        "sklearn": md["versions"]["sklearn"],
    }
    model = client.models.create_or_update(
        Model(
            name=MODEL_NAME,
            path=f"azureml://jobs/{job_name}/outputs/model",
            type=AssetTypes.CUSTOM_MODEL,
            description=f"{md['model']} on {md['trained_on']}",
            tags=tags,
        )
    )
    print(f"registered {model.name}:{model.version} from job {job_name}")


if __name__ == "__main__":
    main()
