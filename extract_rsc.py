#!/usr/bin/env python3
"""Extract resources from BYOND RAD/RSC containers.

Supports:
- Standard .rsc files (RAD stream of RSC entries)
- Nested RAD/RSC streams stored inside entry payloads (common in http_cache.rsc)
- Integrity checks for known media signatures
- Optional decryption for entries with 0x80 encryption flag
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import os
import pathlib
import shutil
import subprocess
import sys
from collections import Counter
from typing import Callable, Iterable


RAD_HEADER_SIZE = 5
RSC_FIXED_SIZE = 17
ENCRYPTION_FLAG = 0x80
BUFFER_SIZE = 16

SEED_PATTERNS_BY_SUFFIX = {
    ".dmi": b"\x89PNG\r\n\x1a\n",
    ".png": b"\x89PNG\r\n\x1a\n",
    ".ogg": b"OggS\x00",
    ".jpg": b"\xff\xd8\xff",
    ".jpeg": b"\xff\xd8\xff",
    ".mid": b"MThd",
    ".midi": b"MThd",
}

# Base type mapping from byond-data-docs/formats/RSC.md
TYPE_INFO = {
    0x01: ("MIDI", ".midi", {"midi"}),
    0x02: ("OGG/WAV", ".ogg", {"ogg", "wav"}),
    0x03: ("DMI/PNG", ".dmi", {"png"}),
    0x06: ("PNG", ".png", {"png"}),
    # Observed in sample archives as unencrypted TTF/OTF payloads.
    0x0E: ("Font", ".ttf", {"ttf", "otf"}),
    0x0B: ("JPG", ".jpg", {"jpg"}),
    # Observed in client cache samples as nested RAD stream payloads.
    0x0A: ("Nested RAD/RSC", ".rsc", set()),
}


@dataclasses.dataclass
class RadEntry:
    index: int
    offset: int
    entry_length: int
    valid: int
    content: bytes


@dataclasses.dataclass
class RscEntry:
    index: int
    source: str
    entry_type: int
    unique_id: int
    timestamp: int
    original_timestamp: int
    name: str
    data: bytes

    @property
    def encrypted(self) -> bool:
        return (self.entry_type & ENCRYPTION_FLAG) != 0

    @property
    def base_type(self) -> int:
        return self.entry_type & ~ENCRYPTION_FLAG


def le_u32(blob: bytes, offset: int) -> int:
    return int.from_bytes(blob[offset : offset + 4], "little", signed=False)


def parse_rad_stream(blob: bytes, source: str) -> list[RadEntry]:
    entries: list[RadEntry] = []
    offset = 0
    index = 0
    while offset < len(blob):
        if len(blob) - offset < RAD_HEADER_SIZE:
            raise ValueError(
                f"{source}: truncated RAD header at offset {offset}"
            )
        entry_length = le_u32(blob, offset)
        valid = blob[offset + 4]
        content_start = offset + RAD_HEADER_SIZE
        content_end = content_start + entry_length
        if content_end > len(blob):
            raise ValueError(
                f"{source}: RAD entry {index} claims {entry_length} bytes at {offset},"
                f" beyond stream length"
            )
        entries.append(
            RadEntry(
                index=index,
                offset=offset,
                entry_length=entry_length,
                valid=valid,
                content=blob[content_start:content_end],
            )
        )
        offset = content_end
        index += 1
    return entries


def parse_rsc_content(content: bytes, source: str, index: int) -> RscEntry:
    if len(content) < RSC_FIXED_SIZE:
        raise ValueError(f"{source}: RAD entry {index} too short for RSC payload")

    entry_type = content[0]
    unique_id = le_u32(content, 1)
    timestamp = le_u32(content, 5)
    original_timestamp = le_u32(content, 9)
    data_length = le_u32(content, 13)

    name_end = content.find(b"\x00", RSC_FIXED_SIZE)
    if name_end == -1:
        raise ValueError(f"{source}: RAD entry {index} missing NUL filename terminator")

    name_bytes = content[RSC_FIXED_SIZE:name_end]
    try:
        name = name_bytes.decode("utf-8")
    except UnicodeDecodeError:
        name = name_bytes.decode("latin1", errors="replace")

    data_start = name_end + 1
    data_end = data_start + data_length
    if data_end > len(content):
        raise ValueError(
            f"{source}: RAD entry {index} data length {data_length} exceeds payload"
        )

    return RscEntry(
        index=index,
        source=source,
        entry_type=entry_type,
        unique_id=unique_id,
        timestamp=timestamp,
        original_timestamp=original_timestamp,
        name=name,
        data=content[data_start:data_end],
    )


def sanitize_relpath(name: str) -> pathlib.Path:
    raw = name.replace("\\", "/").lstrip("/")
    parts: list[str] = []
    for part in raw.split("/"):
        if not part or part in {".", ".."}:
            continue
        safe = "".join(ch if (32 <= ord(ch) < 127 and ch not in '<>:"|?*') else "_" for ch in part)
        safe = safe.strip()
        if safe:
            parts.append(safe)
    if not parts:
        return pathlib.Path()
    return pathlib.Path(*parts)


def base_type_info(base_type: int) -> tuple[str, str, set[str]]:
    return TYPE_INFO.get(base_type, (f"Unknown(0x{base_type:02X})", ".bin", set()))


def sniff_kind(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"OggS"):
        return "ogg"
    if data.startswith(b"RIFF") and len(data) >= 12 and data[8:12] == b"WAVE":
        return "wav"
    if data.startswith(b"MThd"):
        return "midi"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data.startswith(b"PK\x03\x04"):
        return "zip"
    if data.startswith(b"\x00\x01\x00\x00"):
        return "ttf"
    if data.startswith(b"OTTO"):
        return "otf"
    return None


def fmt_ts(ts: int) -> str:
    try:
        return dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (OverflowError, OSError, ValueError):
        return "invalid"


def is_valid_rad_stream(blob: bytes) -> bool:
    try:
        entries = parse_rad_stream(blob, "nested")
    except ValueError:
        return False
    if not entries:
        return False
    return all(e.valid in (0x00, 0x01) for e in entries)


def u32(value: int) -> int:
    return value & 0xFFFFFFFF


def byond_step_state(state: int, observed_byte: int) -> int:
    a = u32((observed_byte + state) * 0x1001 + 0x7ED55D16)
    c = u32((a >> 19) ^ a ^ 0xC761C23C)
    a2 = u32((c << 5) + u32(c + 0x165667B1))
    c2 = u32((a2 - 0x2C5D9B94) ^ u32(a2 << 9))
    a3 = u32(c2 * 9 - 0x028FB93B)
    return u32((a3 >> 16) ^ a3 ^ 0xB55A4F09)


def decrypt_beyond_payload(data: bytes, seed: int) -> bytes:
    state = u32(seed)
    out = bytearray(len(data))
    for i, b in enumerate(data):
        out[i] = b ^ (state & 0xFF)
        state = byond_step_state(state, b)
    return bytes(out)


def seed_pattern_for_entry(entry: RscEntry) -> bytes | None:
    suffix = pathlib.Path(entry.name).suffix.lower()
    return SEED_PATTERNS_BY_SUFFIX.get(suffix)


def build_seed_helper(binary_path: pathlib.Path, source_path: pathlib.Path) -> bool:
    if not source_path.exists():
        return False
    if binary_path.exists() and binary_path.stat().st_mtime >= source_path.stat().st_mtime:
        return True

    compiler = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
    if compiler is None:
        return False

    cmd = [compiler, "-O3", "-std=c99", str(source_path), "-o", str(binary_path)]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except (subprocess.SubprocessError, OSError):
        return False
    return binary_path.exists()


def recover_encryption_seeds(
    entries: list[RscEntry],
    helper_binary: pathlib.Path,
) -> dict[int, int]:
    lines: list[str] = []
    for entry in entries:
        if not entry.encrypted:
            continue
        pattern = seed_pattern_for_entry(entry)
        if not pattern or len(entry.data) < len(pattern):
            continue
        # Known pathological entries in sample sets can be all zero-bytes.
        if entry.data[:BUFFER_SIZE] == b"\x00" * min(BUFFER_SIZE, len(entry.data)):
            continue
        lines.append(f"{entry.index} {pattern.hex()} {entry.data[:BUFFER_SIZE].hex()}\n")

    if not lines:
        return {}

    try:
        proc = subprocess.run(
            [str(helper_binary)],
            input="".join(lines).encode("ascii"),
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except (subprocess.SubprocessError, OSError):
        return {}

    seed_map: dict[int, int] = {}
    for raw in proc.stdout.decode("ascii", errors="replace").splitlines():
        parts = raw.strip().split()
        if len(parts) != 2:
            continue
        idx_s, seed_s = parts
        if seed_s == "NONE":
            continue
        try:
            seed_map[int(idx_s)] = int(seed_s, 16)
        except ValueError:
            continue
    return seed_map


@dataclasses.dataclass
class Summary:
    containers_seen: int = 0
    rad_entries_total: int = 0
    rad_entries_invalid: int = 0
    parsed_rsc_entries: int = 0
    extracted_files: int = 0
    encrypted_entries: int = 0
    decrypted_seed_found: int = 0
    decrypted_seed_missing: int = 0
    decrypted_ok: int = 0
    decrypted_fail: int = 0
    validation_ok: int = 0
    validation_fail: int = 0
    type_counts: Counter[int] = dataclasses.field(default_factory=Counter)


class Extractor:
    def __init__(
        self,
        out_dir: pathlib.Path,
        write_encrypted: bool = True,
        decrypt_encrypted: bool = False,
        decrypted_subdir: str = "decrypted",
        encrypted_subdir: str = "encrypted",
        recurse_nested: bool = True,
        verbose: bool = True,
        on_entry: Callable[[dict], None] | None = None,
        on_progress_init: Callable[[int], None] | None = None,
    ):
        self.out_dir = out_dir
        self.write_encrypted = write_encrypted
        self.decrypt_encrypted = decrypt_encrypted
        self.decrypted_subdir = decrypted_subdir
        self.encrypted_subdir = encrypted_subdir
        self.recurse_nested = recurse_nested
        self.verbose = verbose
        self.on_entry = on_entry
        self.on_progress_init = on_progress_init
        self.summary = Summary()
        self._written_paths: Counter[pathlib.Path] = Counter()
        script_path = pathlib.Path(__file__).resolve()
        helper_source = script_path.with_name("seed_finder.c")
        helper_binary = script_path.with_name("seed_finder")
        if os.name == "nt":
            helper_binary = helper_binary.with_suffix(".exe")
        self._seed_helper = helper_binary if build_seed_helper(helper_binary, helper_source) else None
        if self.decrypt_encrypted and self._seed_helper is None and self.verbose:
            print("[WARN] Could not build/find seed helper. Encrypted entries will be kept as .enc")

    def extract_file(self, input_path: pathlib.Path) -> None:
        blob = input_path.read_bytes()
        source_name = input_path.name
        container_label = source_name
        container_dir = self.out_dir / input_path.stem
        self._extract_rad_blob(blob, container_label, container_dir)

    def _extract_rad_blob(self, blob: bytes, source: str, target_dir: pathlib.Path) -> None:
        self.summary.containers_seen += 1
        try:
            rad_entries = parse_rad_stream(blob, source)
        except ValueError as exc:
            print(f"[ERROR] {exc}")
            return

        target_dir.mkdir(parents=True, exist_ok=True)
        parsed_entries: list[RscEntry] = []
        for rad in rad_entries:
            self.summary.rad_entries_total += 1
            if rad.valid != 0x01:
                self.summary.rad_entries_invalid += 1
                continue
            try:
                entry = parse_rsc_content(rad.content, source, rad.index)
            except ValueError as exc:
                print(f"[WARN] {exc}")
                continue
            parsed_entries.append(entry)
            self.summary.parsed_rsc_entries += 1
            self.summary.type_counts[entry.entry_type] += 1
            if entry.encrypted:
                self.summary.encrypted_entries += 1

        seed_map: dict[int, int] = {}
        if self.decrypt_encrypted and self._seed_helper is not None:
            seed_map = recover_encryption_seeds(parsed_entries, self._seed_helper)

        for entry in parsed_entries:
            type_name, default_ext, expected_kinds = base_type_info(entry.base_type)
            payload = entry.data
            decrypted = False
            if entry.encrypted and self.decrypt_encrypted:
                seed = seed_map.get(entry.index)
                if seed is not None:
                    self.summary.decrypted_seed_found += 1
                    candidate = decrypt_beyond_payload(entry.data, seed)
                    kind_after = sniff_kind(candidate)
                    if expected_kinds and kind_after in expected_kinds:
                        payload = candidate
                        decrypted = True
                        self.summary.decrypted_ok += 1
                    elif not expected_kinds and kind_after is not None:
                        payload = candidate
                        decrypted = True
                        self.summary.decrypted_ok += 1
                    else:
                        self.summary.decrypted_fail += 1
                else:
                    self.summary.decrypted_seed_missing += 1

            effective_encrypted = entry.encrypted and not decrypted
            detected = sniff_kind(payload)
            validation_state = "n/a"
            if not effective_encrypted and expected_kinds:
                if detected in expected_kinds:
                    self.summary.validation_ok += 1
                    validation_state = "ok"
                else:
                    self.summary.validation_fail += 1
                    validation_state = f"fail(expected {sorted(expected_kinds)}, got {detected})"
            elif not effective_encrypted and detected is not None:
                self.summary.validation_ok += 1
                validation_state = f"ok(detected {detected})"

            ts_s = fmt_ts(entry.timestamp)
            state_s = " encrypted"
            if decrypted:
                state_s = " decrypted"
            elif not effective_encrypted:
                state_s = ""
            if self.verbose:
                print(
                    f"[{source}#{entry.index:05d}] type=0x{entry.entry_type:02X}"
                    f"({type_name}) len={len(payload)}{state_s} ts={ts_s}"
                    f" name={entry.name!r} validation={validation_state}"
                )

            if effective_encrypted and not self.write_encrypted:
                continue

            write_dir = target_dir
            if decrypted:
                write_dir = target_dir / self.decrypted_subdir
            elif effective_encrypted:
                write_dir = target_dir / self.encrypted_subdir

            out_path = self._choose_output_path(write_dir, entry, default_ext, effective_encrypted)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(payload)
            self.summary.extracted_files += 1

            if self.recurse_nested and not effective_encrypted and is_valid_rad_stream(payload):
                nested_dir = target_dir / "nested" / self._nested_name(entry, out_path)
                self._extract_rad_blob(payload, f"{source}::{entry.name or entry.index}", nested_dir)

    def _nested_name(self, entry: RscEntry, out_path: pathlib.Path) -> str:
        if entry.name:
            rel = sanitize_relpath(entry.name)
            if rel.parts:
                return "__".join(rel.parts)
        return out_path.stem

    def _choose_output_path(
        self,
        target_dir: pathlib.Path,
        entry: RscEntry,
        default_ext: str,
        encrypted: bool,
    ) -> pathlib.Path:
        rel = sanitize_relpath(entry.name)
        if rel.parts:
            candidate = target_dir / rel
        else:
            candidate = target_dir / f"entry_{entry.index:06d}{default_ext}"

        if encrypted:
            candidate = candidate.with_name(candidate.name + ".enc")
        elif not candidate.suffix:
            candidate = candidate.with_suffix(default_ext)

        return self._dedupe(candidate)

    def _dedupe(self, path: pathlib.Path) -> pathlib.Path:
        count = self._written_paths[path]
        self._written_paths[path] += 1
        if count == 0:
            return path
        stem = path.stem
        suffix = "".join(path.suffixes)
        parent = path.parent
        return parent / f"{stem}__dup{count}{suffix}"


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract resources from BYOND RAD/RSC files")
    parser.add_argument("inputs", nargs="+", type=pathlib.Path, help="Input .rsc file(s)")
    parser.add_argument("-o", "--out", type=pathlib.Path, default=pathlib.Path("extracted"), help="Output directory")
    parser.add_argument("--skip-encrypted", action="store_true", help="Skip writing encrypted entries")
    parser.add_argument(
        "--decrypt-encrypted",
        action="store_true",
        help="Attempt to decrypt encrypted entries (.ogg/.dmi/.png/.jpg/.mid) using recovered seeds",
    )
    parser.add_argument(
        "--decrypted-subdir",
        default="decrypted",
        help="Subdirectory name used for successfully decrypted files (default: decrypted)",
    )
    parser.add_argument(
        "--encrypted-subdir",
        default="encrypted",
        help="Subdirectory name used for still-encrypted files (default: encrypted)",
    )
    parser.add_argument("--no-recursive", action="store_true", help="Disable recursive parsing of nested RAD streams")
    parser.add_argument("--quiet", action="store_true", help="Suppress per-entry logs (summary only)")
    return parser.parse_args(list(argv))


def main(argv: Iterable[str]) -> int:
    args = parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)

    extractor = Extractor(
        out_dir=args.out,
        write_encrypted=not args.skip_encrypted,
        decrypt_encrypted=args.decrypt_encrypted,
        decrypted_subdir=args.decrypted_subdir,
        encrypted_subdir=args.encrypted_subdir,
        recurse_nested=not args.no_recursive,
        verbose=not args.quiet,
    )

    for input_path in args.inputs:
        if not input_path.exists():
            print(f"[ERROR] File not found: {input_path}")
            return 2
        extractor.extract_file(input_path)

    s = extractor.summary
    print("\nSummary")
    print(f"  Containers parsed:   {s.containers_seen}")
    print(f"  RAD entries total:   {s.rad_entries_total}")
    print(f"  RAD invalid skipped: {s.rad_entries_invalid}")
    print(f"  RSC entries parsed:  {s.parsed_rsc_entries}")
    print(f"  Encrypted entries:   {s.encrypted_entries}")
    print(f"  Seeds recovered:     {s.decrypted_seed_found}")
    print(f"  Seeds missing:       {s.decrypted_seed_missing}")
    print(f"  Decrypt success:     {s.decrypted_ok}")
    print(f"  Decrypt failed:      {s.decrypted_fail}")
    print(f"  Files written:       {s.extracted_files}")
    print(f"  Validation ok:       {s.validation_ok}")
    print(f"  Validation fail:     {s.validation_fail}")
    print("  Entry type counts:")
    for entry_type, count in sorted(s.type_counts.items()):
        type_name, _, _ = base_type_info(entry_type & ~ENCRYPTION_FLAG)
        enc = " encrypted" if entry_type & ENCRYPTION_FLAG else ""
        print(f"    0x{entry_type:02X}: {count} ({type_name}{enc})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
