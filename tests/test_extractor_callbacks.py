"""Tests for Extractor callback mechanism."""
import pathlib
import tempfile

import pytest

from extract_rsc import Extractor


def test_callbacks_default_to_none():
    with tempfile.TemporaryDirectory() as tmp:
        ext = Extractor(out_dir=pathlib.Path(tmp), verbose=False)
        assert ext.on_entry is None
        assert ext.on_progress_init is None


def test_on_progress_init_receives_valid_entry_count():
    """on_progress_init should be called with count of valid (0x01) RAD entries."""
    counts = []

    def capture_count(n: int) -> None:
        counts.append(n)

    rsc_path = pathlib.Path("sample_rscs/byond.rsc")
    if not rsc_path.exists():
        pytest.skip("sample_rscs/byond.rsc not available")

    with tempfile.TemporaryDirectory() as tmp:
        ext = Extractor(
            out_dir=pathlib.Path(tmp),
            verbose=False,
            on_progress_init=capture_count,
        )
        ext.extract_file(rsc_path)

    assert len(counts) >= 1
    assert counts[0] > 0


def test_on_entry_fires_with_correct_dict_keys():
    """on_entry should fire per written file with required dict keys."""
    entries = []

    def capture_entry(d: dict) -> None:
        entries.append(d)

    rsc_path = pathlib.Path("sample_rscs/byond.rsc")
    if not rsc_path.exists():
        pytest.skip("sample_rscs/byond.rsc not available")

    with tempfile.TemporaryDirectory() as tmp:
        ext = Extractor(
            out_dir=pathlib.Path(tmp),
            verbose=False,
            on_entry=capture_entry,
        )
        ext.extract_file(rsc_path)

    assert len(entries) > 0
    required_keys = {"index", "source", "name", "type_name", "size", "status", "validation"}
    for e in entries:
        assert required_keys.issubset(e.keys()), f"Missing keys in {e}"
        assert e["status"] in ("ok", "decrypted", "decrypt_failed", "encrypted")
        assert isinstance(e["size"], int)
        assert isinstance(e["source"], str)
