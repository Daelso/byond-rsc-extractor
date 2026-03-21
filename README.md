# BYOND RSC Extractor

Extract resources from BYOND `.rsc` / RAD containers, including nested containers and encrypted entries.

Recovers `.dmi`, `.ogg`, `.png`, `.jpg`, fonts, and other assets from Dream Maker / BYOND cache files.

![BYOND RSC Extractor GUI](screenshot.png)

## Features

- Parses BYOND RAD/RSC streams and writes files using embedded names
- Recursively extracts nested RAD streams found in cache archives
- Validates extracted files against known signatures (PNG, OGG, WAVE, MIDI, JPEG, TTF/OTF)
- Optionally decrypts entries marked with BYOND's `0x80` encryption flag using brute-forced seed recovery

## Requirements

- Python 3.10+
- **GUI only:** PySide6 (`pip install PySide6`)
- **Decryption:** Optional C compiler (`cc`, `gcc`, or `clang`) for automatic seed recovery

## Quick Start

### GUI (recommended for most users)

```bash
python3 gui.py
```

Drop a `.rsc` file onto the window (or click to browse). The extractor shows a progress bar, ETA, and a live scrolling list of extracted files. Decryption is enabled by default.

### CLI

```bash
# Extract one file
python3 extract_rsc.py sample_rscs/byond.rsc

# Extract with decryption
python3 extract_rsc.py --decrypt-encrypted -o extracted sample_rscs/byond.rsc

# Multiple files
python3 extract_rsc.py -o extracted path/to/a.rsc path/to/b.rsc
```

On Windows: `py .\extract_rsc.py -o .\extracted "C:\path\to\cache.rsc"`

## CLI Options

| Flag | Description |
|------|-------------|
| `-o, --out` | Output directory (default: `extracted`) |
| `--decrypt-encrypted` | Attempt decryption of encrypted entries |
| `--skip-encrypted` | Don't write entries that are still encrypted |
| `--decrypted-subdir` | Subdirectory for decrypted files (default: `decrypted`) |
| `--encrypted-subdir` | Subdirectory for encrypted files (default: `encrypted`) |
| `--no-recursive` | Disable nested RAD stream extraction |
| `--quiet` | Summary-only output |

## Output

- Files are named using embedded filenames when available, otherwise `entry_NNNNNN.<ext>`
- Encrypted files get `.enc` suffix; decrypted files go into a `decrypted/` subdirectory
- Duplicate names are disambiguated with `__dupN` suffix
- Nested containers extract into `<output>/<input-stem>/nested/...`

## Supported Types

| Type | Extension | Signatures |
|------|-----------|-----------|
| `0x01` | `.midi` | `MThd` |
| `0x02` | `.ogg` | `OggS`, `RIFF...WAVE` |
| `0x03` | `.dmi` | PNG header |
| `0x06` | `.png` | PNG header |
| `0x0B` | `.jpg` | JPEG header |
| `0x0E` | `.ttf` | TTF/OTF |
| `0x0A` | `.rsc` | Nested RAD/RSC |
| Other | `.bin` | — |

## How Decryption Works

1. Encrypted entries are detected via type bit `0x80`
2. For known file types, the expected plaintext prefix and first 16 ciphertext bytes are fed to `seed_finder`
3. `seed_finder` brute-forces candidate seeds satisfying the prefix constraint
4. Candidates are applied with BYOND's state step/XOR transform
5. Decryption is accepted only if signature checks pass

Note: `seed_finder.c` assumes seeds are monotonically non-decreasing within a container. Not all encrypted entries will decrypt — seed recovery depends on known file prefixes.

## Repository Layout

| File | Purpose |
|------|---------|
| `gui.py` | Desktop GUI (PySide6) |
| `extract_rsc.py` | CLI extractor |
| `seed_finder.c` | Native seed recovery helper |
| `sample_rscs/` | Sample `.rsc` files for testing |

## Troubleshooting

- **"Could not build/find seed helper"** — Install a C compiler, or place a compiled `seed_finder` binary next to `extract_rsc.py`
- **Many `.enc` files** — Expected when seeds can't be recovered for those entries
- **`validation=fail(...)`** — Payload signature doesn't match expected type; keep for manual analysis

## Legal

Only extract assets you are authorized to inspect or archive. Respect game licenses, server policies, and intellectual property restrictions.
