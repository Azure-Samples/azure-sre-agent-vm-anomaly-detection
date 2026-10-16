"""Download the latest registered ``vm-anomaly-detector`` into ``detector/model/``.

    python -m ml.azureml.export [--version N] [--dest detector/model]

Copies ``model.pkl`` + ``metadata.json`` (adds a ``registered_model`` block to the metadata)
and refuses artefacts larger than 5 MB.
"""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from pathlib import Path

from ml.azureml.common import HERE, MODEL_NAME, ml_client

DEST = HERE.parent.parent / "detector" / "model"
MAX_BYTES = 5 * 1024 * 1024


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--version", default=None, help="model version (default: latest)")
    ap.add_argument("--dest", type=Path, default=DEST)
    args = ap.parse_args(argv)
    client = ml_client()

    if args.version:
        model = client.models.get(MODEL_NAME, version=args.version)
    else:
        model = client.models.get(MODEL_NAME, label="latest")

    with tempfile.TemporaryDirectory() as tmp:
        client.models.download(MODEL_NAME, version=model.version, download_path=tmp)
        pkl = next(Path(tmp).rglob("model.pkl"))
        md_path = pkl.with_name("metadata.json")
        size = pkl.stat().st_size
        if size > MAX_BYTES:
            raise SystemExit(f"model.pkl is {size / 1e6:.1f} MB (> 5 MB), not exporting")
        md = json.loads(md_path.read_text())
        md["registered_model"] = {
            "name": model.name,
            "version": model.version,
            "job": (model.tags or {}).get("job"),
            "workspace": client.workspace_name,
        }
        args.dest.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(pkl, args.dest / "model.pkl")
        (args.dest / "metadata.json").write_text(json.dumps(md, indent=2) + "\n")
    print(f"exported {model.name}:{model.version} -> {args.dest} ({size / 1e3:.0f} KB)")


if __name__ == "__main__":
    main()
