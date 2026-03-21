# BYOND RSC Extractor

Extract resources from BYOND `*.rsc` / RAD containers, including nested containers and optionally encrypted entries.

This project is focused on practical asset recovery for Dream Maker / BYOND cache files (for example `*.dmi`, `*.ogg`, `*.png`, `*.jpg`, fonts, and unknown blobs).

## What This Tool Does

- Parses BYOND RAD streams (`length + valid + payload` records).
- Parses RSC entry payloads (metadata + filename + raw bytes).
- Writes files using embedded names when available.
- Recursively extracts nested RAD streams often found in cache archives.
- Detects common file signatures for validation (`PNG`, `OggS`, `WAVE`, `MIDI`, `JPEG`, `ZIP`, `TTF`, `OTF`).
- Optionally attempts to decrypt entries marked with BYOND's encryption flag (`0x80`).

## Repository Layout

- `extract_rsc.py`: Main extractor CLI.
- `seed_finder.c`: Native helper used to recover decryption seeds from known plaintext prefixes.
- `seed_finder` (or `seed_finder.exe` on Windows): Compiled helper binary (auto-built when possible).
- `sample_rscs/`: Sample input archive(s) for local testing.
- `extracted/`: Example output directory.

## Requirements

- Python 3.10+ (uses modern type syntax such as `str | None`).
- Optional C compiler (`cc`, `gcc`, or `clang`) if you want automatic seed recovery for encrypted entries.

No third-party Python packages are required.

## Quick Start

Extract one file:

```bash
python3 extract_rsc.py sample_rscs/byond.rsc
```

Extract multiple containers at once:

```bash
python3 extract_rsc.py -o extracted path/to/a.rsc path/to/b.rsc
```

On Windows (PowerShell):

```powershell
py .\extract_rsc.py -o .\extracted "C:\path\to\cache.rsc"
```

Note: `byond.exe` is not required by this script. You only need the `.rsc` file path(s).

## CLI Reference

```text
usage: extract_rsc.py [-h] [-o OUT] [--skip-encrypted] [--decrypt-encrypted]
                      [--decrypted-subdir DECRYPTED_SUBDIR]
                      [--encrypted-subdir ENCRYPTED_SUBDIR]
                      [--no-recursive] [--quiet]
                      inputs [inputs ...]
```

- `inputs`: One or more input `.rsc` files.
- `-o, --out`: Output directory (default: `extracted`).
- `--skip-encrypted`: Do not write entries that are still encrypted.
- `--decrypt-encrypted`: Attempt decryption of encrypted media entries using recovered seeds.
- `--decrypted-subdir`: Directory name for successful decrypts (default: `decrypted`).
- `--encrypted-subdir`: Directory name for still-encrypted outputs (default: `encrypted`).
- `--no-recursive`: Disable nested RAD stream extraction.
- `--quiet`: Summary-only output.

## Output Behavior

- Uses embedded filename from each entry when present.
- Sanitizes paths to prevent traversal and invalid filesystem characters.
- Falls back to `entry_000123.<ext>` when no usable name exists.
- Appends `.enc` to files still encrypted at write time.
- Writes successful decrypts under `<container>/decrypted/` by default.
- Writes unresolved encrypted files under `<container>/encrypted/` by default.
- Appends `__dupN` for duplicate output paths.
- Creates nested extraction trees under `<output>/<input-stem>/nested/...`.

## Supported Entry Types

Current `TYPE_INFO` mapping in the extractor:

- `0x01`: MIDI (`.midi`) expected signature `MThd`
- `0x02`: OGG/WAV (`.ogg`) expected signatures `OggS` or `RIFF....WAVE`
- `0x03`: DMI/PNG (`.dmi`) expected PNG signature
- `0x06`: PNG (`.png`) expected PNG signature
- `0x0B`: JPG (`.jpg`) expected JPEG signature
- `0x0E`: Font (`.ttf`) expected `TTF/OTF`
- `0x0A`: Nested RAD/RSC payload (`.rsc`)
- Unknown types are written as `.bin`

If a type has known signatures, extraction reports `validation=ok` or `validation=fail(...)`.

## Decryption Model

When `--decrypt-encrypted` is enabled:

1. Encrypted entries are detected via type bit `0x80`.
2. For known suffixes (`.dmi`, `.png`, `.ogg`, `.jpg`, `.mid`, etc.), the extractor provides:
   - expected plaintext prefix (for example PNG header),
   - first 16 ciphertext bytes.
3. `seed_finder` brute-forces candidate seeds that satisfy the prefix constraint.
4. Candidate seeds are applied with the BYOND state step/XOR transform.
5. Decryption is accepted only if signature checks match expected media kinds.

Important implementation detail: `seed_finder.c` assumes seeds are monotonically non-decreasing within a single container stream. This matches the observed sample cache behavior used here, but it is still a heuristic.

## Limitations

- Not all encrypted entries will decrypt.
- Seed recovery currently depends on known file prefixes and recognized extensions.
- Entries with unknown formats or non-standard prefixes cannot be seed-recovered yet.
- If no compiler is available, encrypted extraction still works, but auto seed recovery is disabled.
- Some containers can include types not yet mapped in `TYPE_INFO`; they will be extracted as `.bin`.

## Integrity Validation and Sanity Checks

The extractor prints summary counters:

- `Validation ok` / `Validation fail`
- `Decrypt success` / `Decrypt failed`
- `Seeds recovered` / `Seeds missing`

You can also manually verify outputs:

```bash
file extracted/byond/*.dmi
xxd -l 16 extracted/byond/some_file.dmi
```

Expected PNG header for valid DMI/PNG starts with:

```text
89 50 4E 47 0D 0A 1A 0A
```

## Tested Example in This Repository

Command run:

```bash
python3 extract_rsc.py --quiet --decrypt-encrypted -o /tmp/byond_readme_test sample_rscs/byond.rsc
```

Observed summary:

```text
Containers parsed:   1
RAD entries total:   5958
RSC entries parsed:  5958
Encrypted entries:   67
Seeds recovered:     2
Seeds missing:       65
Decrypt success:     2
Decrypt failed:      0
Files written:       5958
Validation ok:       50
Validation fail:     0
```

From this run, two encrypted `.dmi` entries were successfully decrypted and verified as valid PNG image data (`byond/decrypted/Density.dmi` and `byond/decrypted/Fanatichnye vzglyady-Violet Lakko-YourHero.dmi`).

## Development Smoke Tests

Syntax check:

```bash
python3 -m py_compile extract_rsc.py
```

Basic extraction:

```bash
python3 extract_rsc.py --quiet -o /tmp/byond_readme_test_raw sample_rscs/byond.rsc
```

Extraction with decryption attempts:

```bash
python3 extract_rsc.py --quiet --decrypt-encrypted -o /tmp/byond_readme_test sample_rscs/byond.rsc
```

Skip still-encrypted outputs:

```bash
python3 extract_rsc.py --quiet --skip-encrypted -o /tmp/byond_readme_test_skip sample_rscs/byond.rsc
```

## Troubleshooting

- `Could not build/find seed helper` warning:
  - Install a C compiler, or place a compiled `seed_finder` binary next to `extract_rsc.py`.
- Many `.enc` files remain:
  - This is expected when seeds cannot be recovered for those entries.
- `validation=fail(...)` appears:
  - Payload signature does not match expected type. Keep the file for manual analysis.

## Legal and Ethical Use

Only extract assets you are authorized to inspect or archive. Respect game licenses, server policies, and intellectual property restrictions.
