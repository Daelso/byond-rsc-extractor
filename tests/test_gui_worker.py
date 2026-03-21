"""Tests for ExtractionWorker signal emissions."""
import pathlib
import sys
import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication
from gui import ExtractionWorker


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


def test_worker_emits_signals(qapp, tmp_path):
    rsc_path = pathlib.Path("sample_rscs/byond.rsc")
    if not rsc_path.exists():
        pytest.skip("sample_rscs/byond.rsc not available")

    progress_inits = []
    entries = []
    finished = []

    worker = ExtractionWorker(
        input_path=rsc_path,
        out_dir=tmp_path,
        decrypt=True,
    )
    worker.progress_init.connect(lambda n: progress_inits.append(n))
    worker.entry_extracted.connect(lambda d: entries.append(d))
    worker.extraction_finished.connect(lambda s: finished.append(s))

    worker.run()  # synchronous in test

    assert len(progress_inits) >= 1
    assert progress_inits[0] > 0
    assert len(entries) > 0
    assert len(finished) == 1
