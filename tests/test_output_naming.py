"""Tests for output naming and metadata filtering behavior."""
from __future__ import annotations

import pathlib

from extract_rsc import Extractor


def _u32(value: int) -> bytes:
    return int(value).to_bytes(4, "little", signed=False)


def _build_rsc(entries: list[tuple[int, int, str, bytes]]) -> bytes:
    chunks: list[bytes] = []
    for entry_type, unique_id, name, data in entries:
        name_bytes = name.encode("utf-8")
        content = (
            bytes([entry_type])
            + _u32(unique_id)
            + _u32(0)
            + _u32(0)
            + _u32(len(data))
            + name_bytes
            + b"\x00"
            + data
        )
        chunks.append(_u32(len(content)) + b"\x01" + content)
    return b"".join(chunks)


def test_flat_output_false_preserves_relative_path(tmp_path: pathlib.Path):
    blob = _build_rsc([(0x00, 1, "xZPR/xNO/scorcher/pointer.cur", b"CUR!")])
    src = tmp_path / "input.rsc"
    src.write_bytes(blob)

    out_dir = tmp_path / "out"
    ext = Extractor(out_dir=out_dir, flat_output=False, verbose=False)
    ext.extract_file(src)

    assert (out_dir / "input" / "xZPR" / "xNO" / "scorcher" / "pointer.cur").exists()


def test_flat_output_true_uses_basename_only(tmp_path: pathlib.Path):
    blob = _build_rsc([(0x00, 1, "xZPR/xNO/scorcher/pointer.cur", b"CUR!")])
    src = tmp_path / "input.rsc"
    src.write_bytes(blob)

    out_dir = tmp_path / "out"
    ext = Extractor(out_dir=out_dir, flat_output=True, verbose=False)
    ext.extract_file(src)

    assert (out_dir / "pointer.cur").exists()


def test_ddmi_metadata_skipped_by_default(tmp_path: pathlib.Path):
    ddmi = bytes.fromhex("44444d491c000000013309000008056c6f6262795f6261636b67726f756e640040ffffff")
    blob = _build_rsc([(0x0C, 123, "", ddmi)])
    src = tmp_path / "meta.rsc"
    src.write_bytes(blob)

    out_dir = tmp_path / "out"
    ext = Extractor(out_dir=out_dir, verbose=False)
    ext.extract_file(src)

    assert ext.summary.metadata_skipped == 1
    assert ext.summary.extracted_files == 0
    assert not any(p.is_file() for p in out_dir.rglob("*"))


def test_ddmi_metadata_can_be_included_with_readable_name(tmp_path: pathlib.Path):
    ddmi = bytes.fromhex("44444d491c000000013309000008056c6f6262795f6261636b67726f756e640040ffffff")
    blob = _build_rsc([(0x0C, 123, "", ddmi)])
    src = tmp_path / "meta.rsc"
    src.write_bytes(blob)

    out_dir = tmp_path / "out"
    ext = Extractor(out_dir=out_dir, write_metadata=True, verbose=False)
    ext.extract_file(src)

    files = [p for p in out_dir.rglob("*") if p.is_file()]
    assert ext.summary.metadata_skipped == 0
    assert ext.summary.extracted_files == 1
    assert len(files) == 1
    assert files[0].name.endswith(".ddmi")
    assert files[0].name.startswith("lobby_background")
