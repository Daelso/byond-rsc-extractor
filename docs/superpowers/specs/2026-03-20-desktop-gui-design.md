# BYOND RSC Extractor — Desktop GUI Design

## Purpose

A desktop GUI for less technical users to extract resources from BYOND `.rsc` files. Lives alongside the existing CLI (`extract_rsc.py`) as `gui.py`. Targets the same Python 3.10+ environment with PySide6 as the only added dependency.

## Visual Direction

**NFO/ANSI scene aesthetic.** Cyan-on-black color scheme, monospaced typography (Share Tech Mono / system monospace fallback), blocky ASCII art header, box-drawing characters for separators. Restrained — no gradients, no glow, no animation beyond the progress bar. The entire window should read like a styled `.nfo` text file rendered as a native GUI.

### Color Palette

| Role | Color |
|------|-------|
| Background | `#000000` |
| Primary text | `#c0c0c0` |
| Accent / headings | `#00aaff` (cyan) |
| Success / OK | `#00aa44` (green) |
| Decrypted / warning | `#ccaa00` (yellow) |
| Encrypted / error | `#cc3333` (red) |
| Muted / metadata | `#333333` |
| Borders | `#003355` |
| Input backgrounds | `#000000` |

### Typography

- All UI text: monospaced font (Share Tech Mono if installed, else platform monospace)
- ASCII header banner in the title area using block characters
- Uppercase labels for buttons and status text

## Layout

Single-column stacked layout, top to bottom:

1. **Title bar area** — ASCII art "BYOND RSC EXTRACTOR" banner
2. **Drop zone** — dashed border area accepting drag-and-drop `.rsc` files, also clickable to open a file picker. Shows `▼ ▼ ▼ DROP .RSC FILE HERE` when empty.
3. **Settings row** — horizontal layout containing:
   - Output folder path display (read-only text field, defaults to `extracted/` next to the input file)
   - `[BROWSE]` button to pick output folder
   - `[✓] DECRYPT` checkbox (checked by default) — toggles `decrypt_encrypted` parameter on the `Extractor`. `write_encrypted` is always `True` in the GUI.
4. **Progress section** — shows during extraction:
   - Label row: `EXTRACTING: 1,247 / 5,958` on left, `ETA: 00:32` on right
   - Progress bar: cyan fill on dark background, percentage text overlay
5. **File list** — scrolling list that auto-scrolls to bottom as new entries appear. Each row shows:
   - Status prefix: `[+]` OK (green), `[*]` decrypted (yellow), `[!]` encrypted or decrypt_failed (red)
   - Filename
   - Right-aligned metadata: type name, file size, status label
   - Rows separated by thin dark borders
6. **Footer** — subtle decorative scene-style separator line

### Window Properties

- Default size: ~600x700px
- Resizable, minimum ~500x500px
- Window title: "BYOND RSC Extractor"

## Architecture

### File Structure

- `gui.py` — new file, the GUI application. Self-contained PySide6 app.
- `extract_rsc.py` — existing CLI, modified minimally to support progress callbacks.

### Callback Mechanism

Add optional callback parameters to the `Extractor` class:

```python
class Extractor:
    def __init__(
        self,
        ...,
        on_entry: Callable[[dict], None] | None = None,
        on_progress_init: Callable[[int], None] | None = None,
    ):
        self.on_entry = on_entry
        self.on_progress_init = on_progress_init
```

`on_entry` is called **after each file is written** (after `out_path.write_bytes(payload)`, before nested recursion) with a dict:

```python
{
    "index": int,           # entry index within the current container
    "source": str,          # container source label (e.g. "byond.rsc" or "byond.rsc::nested_name")
    "name": str,            # filename
    "type_name": str,       # e.g. "DMI/PNG", "OGG/WAV"
    "size": int,            # payload size in bytes
    "status": str,          # "ok", "decrypted", "decrypt_failed", "encrypted"
    "validation": str,      # "ok", "fail(...)", "n/a"
}
```

Status values:
- `"ok"` — unencrypted entry written normally
- `"decrypted"` — encrypted entry successfully decrypted and validated
- `"decrypt_failed"` — seed found but decrypted payload failed validation (written as `.enc`)
- `"encrypted"` — no seed found, written as `.enc`

`on_entry` fires for **all entries including nested containers**. The progress bar tracks against the top-level entry count only (see below), but nested entries still appear in the file list.

When callbacks are `None` (default), behavior is unchanged — the CLI path is unaffected.

### Two-Phase Extraction

To provide a progress bar from the start:

1. **Phase 1 — Parse:** Read the `.rsc` file and call `parse_rad_stream()` to get RAD entries, then count only those with `valid == 0x01` to get the extractable entry count. Call `on_progress_init(count)` so the GUI sets the progress bar maximum.
2. **Phase 2 — Extract:** Run the normal extraction loop. Each `on_entry` callback increments the progress counter.

**Nested containers:** Entries from nested RAD streams are not included in the progress bar total (they're discovered during extraction). The progress bar tracks top-level entries only. Nested entries appear in the file list but don't advance the progress bar. This means the bar may sit at 100% briefly while nested extraction finishes — acceptable for a "quick frontend."

This requires splitting `_extract_rad_blob` so the parse step can report totals before the write loop begins. The refactor points:
- Move the RAD/RSC parse loop in `_extract_rad_blob` (the loop that builds `parsed_entries`) into a helper that returns `parsed_entries` and calls `on_progress_init`
- The write loop in `_extract_rad_blob` (the loop that iterates `parsed_entries`, decrypts, validates, and writes files) remains as-is, with `on_entry` calls inserted after `write_bytes`

**Tracking `decrypt_failed` status:** The extraction loop needs a local flag (e.g. `decrypt_attempted = False`) set to `True` when a seed is found and decryption is attempted. After the decryption block, the callback status is determined by: if `decrypted` → `"decrypted"`, elif `decrypt_attempted` → `"decrypt_failed"`, elif `entry.encrypted` → `"encrypted"`, else → `"ok"`.

### Threading Model

```
Main Thread (Qt Event Loop)
  ├── Handles all UI updates
  ├── Receives signals from worker
  └── Never blocks

Worker QThread
  ├── Instantiates Extractor with verbose=False, on_entry callback, on_progress_init callback
  ├── After construction, checks extractor._seed_helper; if None and decrypt enabled, emits warn_message signal
  ├── Calls extract_file()
  ├── on_entry emits Qt signal → main thread updates file list + progress
  ├── on_progress_init emits Qt signal → main thread sets progress bar max
  └── After extract_file() returns, reads extractor.summary and emits extraction_finished signal
```

Signals (all use `object` type for safe Python dict passing through Qt):
- `entry_extracted = Signal(object)` — per-file update dict (see callback dict above)
- `progress_init = Signal(int)` — total extractable entry count for progress bar
- `extraction_finished = Signal(object)` — `Summary` dataclass instance (read from `extractor.summary` after `extract_file()` returns). The GUI displays a summary row with these `Summary` fields: `extracted_files`, `encrypted_entries`, `decrypted_ok`, `decrypted_fail`, `validation_ok`, `validation_fail`.
- `extraction_error = Signal(str)` — error message string
- `warn_message = Signal(str)` — warning text (e.g. no C compiler), displayed as yellow row in file list

### ETA Calculation

Track a rolling window of the last 50 entries' timestamps (`time.monotonic()`). Compute `entries_per_second = window_size / elapsed_window_time`, then `eta_seconds = (total - current) / entries_per_second`. Display as `MM:SS`.

### Cancellation

No cancel button in v1. Extraction is fast enough for typical `.rsc` files (5,958 entries completes in ~30s). If needed later, a `threading.Event` abort flag checked in the extraction loop would be the mechanism. Explicitly out of scope for now.

## Error Handling

All errors are displayed in-band within the file list — no modal popups.

| Scenario | Display | Timing |
|----------|---------|--------|
| Invalid/corrupted file dropped | Red row: `[!] ERROR: Not a valid RSC container` | Immediately on drop |
| Non-`.rsc` file dropped | Red row: `[!] ERROR: File must be a .rsc file` | Immediately on drop |
| No C compiler (decrypt checked) | Yellow row: `[*] WARN: No C compiler found — seed recovery disabled` | First row when extraction begins |
| File read error | Red row: `[!] ERROR: Could not read file: <reason>` | Immediately on drop |

## State Transitions

| State | Drop zone text | Progress | File list |
|-------|---------------|----------|-----------|
| **Idle** | `▼ ▼ ▼ DROP .RSC FILE HERE` | Hidden | Empty or previous results |
| **Extracting** | Shows current filename | Active with ETA | Scrolling entries |
| **Complete** | `▼ ▼ ▼ DROP .RSC FILE HERE` (reset) | 100%, shows "DONE" | Final list + summary row |
| **Error** | `▼ ▼ ▼ DROP .RSC FILE HERE` (reset) | Hidden | Error row displayed |

- Dropping a new file while **idle** or **complete** resets and starts fresh.
- Drops during **extracting** are ignored.

## Output Folder Default

When a `.rsc` file is loaded:
- Default output: `<directory containing the .rsc file>/extracted/`
- Note: `Extractor.extract_file()` appends `input_path.stem` as a subdirectory (e.g. `extracted/byond/` for `byond.rsc`). The GUI displays the base output dir; the stem subdirectory is created automatically by the extractor.
- User can override via `[BROWSE]` folder picker at any time before extraction starts.
- **Precedence rule:** Once the user explicitly picks a folder via BROWSE, that folder persists across new file drops. It is only reset if the user clears it or picks a new one. The auto-default only applies when no explicit choice has been made.

## Dependencies

- PySide6 (Qt for Python — LGPL licensed, no commercial restrictions)
- All existing dependencies remain unchanged

## Out of Scope

- Batch processing (multiple `.rsc` files at once) — CLI handles this
- `--no-recursive`, `--skip-encrypted`, subdir name options — advanced CLI flags stay CLI-only
- Embedded chiptune playback (tempting but no)
- Cancel button (extraction is fast enough; can add later via `threading.Event` if needed)
