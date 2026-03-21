"""Tests for Extractor callback mechanism."""
import pathlib
import tempfile

from extract_rsc import Extractor


def test_callbacks_default_to_none():
    with tempfile.TemporaryDirectory() as tmp:
        ext = Extractor(out_dir=pathlib.Path(tmp), verbose=False)
        assert ext.on_entry is None
        assert ext.on_progress_init is None
