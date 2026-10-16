"""detector/features.py must be a verbatim copy of ml/features.py (train/serve parity)."""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
ML = ROOT / "ml" / "features.py"
DETECTOR = ROOT / "detector" / "features.py"


@pytest.mark.skipif(not DETECTOR.exists(), reason="detector/features.py not present yet")
def test_detector_features_is_verbatim_copy():
    assert DETECTOR.read_text() == ML.read_text(), (
        "detector/features.py differs from ml/features.py - re-vendor it: "
        "cp ml/features.py detector/features.py"
    )
