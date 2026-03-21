# Desktop GUI Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a PySide6 desktop GUI (`gui.py`) that lets users drag-and-drop `.rsc` files for extraction with a progress bar, ETA, and scrolling file list, styled with an NFO/ANSI scene aesthetic.

**Architecture:** The existing `Extractor` class in `extract_rsc.py` gets two optional callbacks (`on_entry`, `on_progress_init`) so the GUI can receive per-file progress. The GUI runs extraction in a `QThread` and updates the UI via Qt signals. The CLI path is unchanged.

**Tech Stack:** Python 3.10+, PySide6, existing `extract_rsc.py` extractor

**Spec:** `docs/superpowers/specs/2026-03-20-desktop-gui-design.md`

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `extract_rsc.py` | Modify | Add `on_entry` and `on_progress_init` callbacks to `Extractor`, add `decrypt_attempted` tracking |
| `gui.py` | Create | PySide6 GUI application — window, worker thread, all UI components |
| `tests/test_extractor_callbacks.py` | Create | Tests for the new callback mechanism in `Extractor` |
| `tests/test_gui_worker.py` | Create | Tests for the GUI worker thread signal emissions |

---

## Chunk 1: Extractor Callback Refactor

### Task 1: Add callback parameters to Extractor

**Files:**
- Modify: `extract_rsc.py:321-348` (Extractor.__init__)
- Create: `tests/test_extractor_callbacks.py`

- [ ] **Step 0: Create tests directory**

Run: `mkdir -p /home/chase/projects/byond-extractor/tests`

- [ ] **Step 1: Create test file with first test — callbacks default to None**

```python
# tests/test_extractor_callbacks.py
"""Tests for Extractor callback mechanism."""
import pathlib
import tempfile

from extract_rsc import Extractor


def test_callbacks_default_to_none():
    with tempfile.TemporaryDirectory() as tmp:
        ext = Extractor(out_dir=pathlib.Path(tmp), verbose=False)
        assert ext.on_entry is None
        assert ext.on_progress_init is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/chase/projects/byond-extractor && python -m pytest tests/test_extractor_callbacks.py::test_callbacks_default_to_none -v`
Expected: FAIL — `Extractor` has no `on_entry` attribute

- [ ] **Step 3: Add on_entry and on_progress_init to Extractor.__init__**

In `extract_rsc.py`, modify `Extractor.__init__` signature and body. Add after existing parameters:

```python
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
        on_entry: "Callable[[dict], None] | None" = None,
        on_progress_init: "Callable[[int], None] | None" = None,
    ):
        # ... existing assignments ...
        self.on_entry = on_entry
        self.on_progress_init = on_progress_init
```

Also add `Callable` to the existing `from typing import Iterable` import: `from typing import Callable, Iterable`. Note: `from __future__ import annotations` is already present in the file, so annotations are evaluated lazily — but the import is still needed for any runtime references.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/chase/projects/byond-extractor && python -m pytest tests/test_extractor_callbacks.py::test_callbacks_default_to_none -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /home/chase/projects/byond-extractor
git add extract_rsc.py tests/test_extractor_callbacks.py
git commit -m "feat: add on_entry and on_progress_init callback params to Extractor"
```

### Task 2: Add on_progress_init call in _extract_rad_blob

**Files:**
- Modify: `extract_rsc.py:357-382` (_extract_rad_blob parse section)
- Modify: `tests/test_extractor_callbacks.py`

- [ ] **Step 1: Write test — on_progress_init receives valid entry count**

Append to `tests/test_extractor_callbacks.py`:

```python
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
    # The first call should be for the top-level container
    assert counts[0] > 0
```

Add `import pytest` at the top of the file.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/chase/projects/byond-extractor && python -m pytest tests/test_extractor_callbacks.py::test_on_progress_init_receives_valid_entry_count -v`
Expected: FAIL — `on_progress_init` is never called

- [ ] **Step 3: Add on_progress_init call after parsing RAD entries**

In `extract_rsc.py`, in `_extract_rad_blob`, after the parse loop that builds `parsed_entries` (after line 381) and before the seed recovery section (line 383), insert:

```python
        if self.on_progress_init is not None:
            self.on_progress_init(len(parsed_entries))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/chase/projects/byond-extractor && python -m pytest tests/test_extractor_callbacks.py::test_on_progress_init_receives_valid_entry_count -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /home/chase/projects/byond-extractor
git add extract_rsc.py tests/test_extractor_callbacks.py
git commit -m "feat: call on_progress_init with valid entry count during extraction"
```

### Task 3: Add on_entry callback with status tracking

**Files:**
- Modify: `extract_rsc.py:387-453` (_extract_rad_blob write loop)
- Modify: `tests/test_extractor_callbacks.py`

- [ ] **Step 1: Write test — on_entry fires for each extracted file with correct dict keys**

Append to `tests/test_extractor_callbacks.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/chase/projects/byond-extractor && python -m pytest tests/test_extractor_callbacks.py::test_on_entry_fires_with_correct_dict_keys -v`
Expected: FAIL — `on_entry` is never called

- [ ] **Step 3: Add on_entry call and decrypt_attempted tracking in the write loop**

In `extract_rsc.py`, in the write loop of `_extract_rad_blob`:

1. Add `decrypt_attempted = False` after `decrypted = False` (line 390)
2. Inside the `if seed is not None:` block (line 393), set `decrypt_attempted = True` as the first statement (before `self.summary.decrypted_seed_found += 1`)
3. After `out_path.write_bytes(payload)` (after line 448) and before the nested recursion check (line 451), insert:

```python
            if self.on_entry is not None:
                if decrypted:
                    cb_status = "decrypted"
                elif decrypt_attempted:
                    cb_status = "decrypt_failed"
                elif entry.encrypted:
                    cb_status = "encrypted"
                else:
                    cb_status = "ok"
                self.on_entry({
                    "index": entry.index,
                    "source": source,
                    "name": entry.name,
                    "type_name": type_name,
                    "size": len(payload),
                    "status": cb_status,
                    "validation": validation_state,
                })
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/chase/projects/byond-extractor && python -m pytest tests/test_extractor_callbacks.py::test_on_entry_fires_with_correct_dict_keys -v`
Expected: PASS

- [ ] **Step 5: Run all existing tests/checks to ensure CLI path is unchanged**

Run: `cd /home/chase/projects/byond-extractor && python -m py_compile extract_rsc.py && python extract_rsc.py --quiet -o /tmp/byond_callback_test sample_rscs/byond.rsc`
Expected: Compiles cleanly, extraction succeeds with same summary output as before

- [ ] **Step 6: Commit**

```bash
cd /home/chase/projects/byond-extractor
git add extract_rsc.py tests/test_extractor_callbacks.py
git commit -m "feat: fire on_entry callback with status dict after each file write"
```

### Task 4: Run full callback test suite

**Files:**
- `tests/test_extractor_callbacks.py`

- [ ] **Step 1: Run all callback tests**

Run: `cd /home/chase/projects/byond-extractor && python -m pytest tests/test_extractor_callbacks.py -v`
Expected: All 3 tests PASS

- [ ] **Step 2: Run syntax check on extract_rsc.py**

Run: `cd /home/chase/projects/byond-extractor && python -m py_compile extract_rsc.py`
Expected: No output (clean compile)

---

## Chunk 2: GUI Application

### Task 5: Create gui.py with minimal window

**Files:**
- Create: `gui.py`

- [ ] **Step 1: Create gui.py with QApplication, main window, and ASCII header**

Create `gui.py` with:
- `QApplication` setup
- `MainWindow(QMainWindow)` with:
  - Window title "BYOND RSC Extractor", size 600x700, min 500x500
  - Black background, monospace font (try "Share Tech Mono", fallback to system monospace)
  - Central widget with `QVBoxLayout`
  - ASCII art header as `QLabel`:
    ```
     ██▄ ▀▄▀ ▄▀▄ █▄ █ █▀▄
     █▄█  █  ▀▄▀ █ ▀█ █▄▀
     ══════════════════════
       R S C   E X T R A C T O R
    ```
  - Cyan color (`#00aaff`) for header text
- `if __name__ == "__main__"` entry point

Full stylesheet for the window using the spec's color palette:

```python
STYLESHEET = """
    QMainWindow, QWidget {
        background-color: #000000;
        color: #c0c0c0;
        font-family: "Share Tech Mono", "Consolas", "Courier New", monospace;
        font-size: 12px;
    }
"""
```

- [ ] **Step 2: Verify it launches**

Run: `cd /home/chase/projects/byond-extractor && timeout 3 python gui.py 2>&1 || true`
Expected: Window opens briefly (timeout kills it). No import errors.

- [ ] **Step 3: Commit**

```bash
cd /home/chase/projects/byond-extractor
git add gui.py
git commit -m "feat: add gui.py with main window shell and NFO-style ASCII header"
```

### Task 6: Add drop zone widget

**Files:**
- Modify: `gui.py`

- [ ] **Step 1: Create DropZone widget class**

Add a `DropZone(QLabel)` class to `gui.py`:
- Accepts drops (`setAcceptDrops(True)`)
- Displays `▼ ▼ ▼\nDROP .RSC FILE HERE` centered, cyan text
- Dashed border: `border: 2px dashed #003355;`
- On click: opens `QFileDialog.getOpenFileName` filtered to `*.rsc`
- `dragEnterEvent`: accept if URLs with `.rsc` extension, highlight border
- `dropEvent`: emit `file_dropped = Signal(str)` with the file path
- `dragLeaveEvent`: reset border style
- Minimum height ~80px

- [ ] **Step 2: Add DropZone to MainWindow layout**

Insert `DropZone` into the central layout after the ASCII header. Connect `file_dropped` signal to a `_on_file_dropped(path: str)` slot that stores the path (implementation in later task).

- [ ] **Step 3: Verify drag area appears and click opens file dialog**

Run: `cd /home/chase/projects/byond-extractor && timeout 5 python gui.py 2>&1 || true`
Expected: Window shows drop zone with dashed border and text

- [ ] **Step 4: Commit**

```bash
cd /home/chase/projects/byond-extractor
git add gui.py
git commit -m "feat: add drag-and-drop zone with file picker fallback"
```

### Task 7: Add settings row (output folder + decrypt checkbox)

**Files:**
- Modify: `gui.py`

- [ ] **Step 1: Add settings row to MainWindow**

Add a horizontal `QHBoxLayout` below the drop zone containing:
- `QLineEdit` (read-only) showing the output folder path, styled with `background: #000; border: 1px solid #003355; color: #005588; padding: 4px;`
- `QPushButton("[BROWSE]")` styled with `background: #001a2e; border: 1px solid #0055aa; color: #00aaff; padding: 4px 8px;`
  - On click: `QFileDialog.getExistingDirectory`, updates the line edit
  - Store a `_user_picked_output` bool flag, set to `True` when user explicitly picks
- `QCheckBox("[✓] DECRYPT")` checked by default, styled with cyan accent

- [ ] **Step 2: Wire output folder default logic**

In `_on_file_dropped`: if `_user_picked_output` is False, set the output line edit to `<rsc_file_parent>/extracted/`. If True, leave it as-is.

- [ ] **Step 3: Verify settings row appears and interacts**

Run manually: launch `gui.py`, verify browse opens folder picker, checkbox toggles.

- [ ] **Step 4: Commit**

```bash
cd /home/chase/projects/byond-extractor
git add gui.py
git commit -m "feat: add output folder picker and decrypt checkbox"
```

### Task 8: Add progress section

**Files:**
- Modify: `gui.py`

- [ ] **Step 1: Add progress widgets to MainWindow**

Add below the settings row (initially hidden via `setVisible(False)`):
- A `QHBoxLayout` for labels:
  - Left `QLabel`: `EXTRACTING: 0 / 0` (color `#005588`)
  - Right `QLabel`: `ETA: --:--` (color `#005588`)
- A `QProgressBar` styled to match NFO aesthetic:

```python
PROGRESS_STYLE = """
    QProgressBar {
        background: #001122;
        border: 1px solid #003355;
        height: 10px;
        text-align: center;
        color: #00aaff;
        font-size: 9px;
    }
    QProgressBar::chunk {
        background: qlineargradient(x1:0, x2:1, stop:0 #003366, stop:0.5 #0088cc, stop:1 #00bbff);
    }
"""
```

- Add methods:
  - `_show_progress(total: int)` — set max, show section
  - `_update_progress(current: int)` — update bar and label
  - `_update_eta(eta_str: str)` — update ETA label
  - `_hide_progress()` — hide section

- [ ] **Step 2: Commit**

```bash
cd /home/chase/projects/byond-extractor
git add gui.py
git commit -m "feat: add progress bar and ETA display"
```

### Task 9: Add file list widget

**Files:**
- Modify: `gui.py`

- [ ] **Step 1: Add scrolling file list**

Add a `QScrollArea` containing a `QVBoxLayout` (or use `QListWidget` with custom styling) below the progress section. This is the main area — set it to expand (`stretch=1`).

Style each row as a `QLabel` or custom widget with:
- Left side: status prefix + filename
  - `[+]` green (`#00aa44`) for status `"ok"`
  - `[*]` yellow (`#ccaa00`) for status `"decrypted"`
  - `[!]` red (`#cc3333`) for status `"encrypted"` or `"decrypt_failed"`
- Right side: type name, formatted size (KB/MB), status label
- Font size: 10px, monospace
- Border bottom: `1px solid #001122`

Add methods:
- `_add_file_row(entry_dict: dict)` — create and append a row, auto-scroll to bottom
- `_add_message_row(text: str, color: str)` — for errors/warnings (red/yellow)
- `_add_summary_row(summary)` — format key Summary fields as a final row
- `_clear_file_list()` — remove all rows

Helper: `_format_size(size_bytes: int) -> str` — returns "1.2 KB", "3.4 MB", etc.

- [ ] **Step 2: Add footer label**

Below the file list, add a `QLabel` with decorative text:
```
─── BYOND RSC EXTRACTOR v1.0 ── ──── ─── ── ─
```
Color `#003355`, centered.

- [ ] **Step 3: Commit**

```bash
cd /home/chase/projects/byond-extractor
git add gui.py
git commit -m "feat: add scrolling file list and footer"
```

### Task 10: Create ExtractionWorker QThread

**Files:**
- Modify: `gui.py`
- Create: `tests/test_gui_worker.py`

- [ ] **Step 1: Write test — worker emits progress_init and entry_extracted signals**

```python
# tests/test_gui_worker.py
"""Tests for ExtractionWorker signal emissions."""
import pathlib
import sys
import pytest

# PySide6 may not be installed in CI — skip gracefully
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

    worker.run()  # run synchronously in test

    assert len(progress_inits) >= 1
    assert progress_inits[0] > 0
    assert len(entries) > 0
    assert len(finished) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/chase/projects/byond-extractor && python -m pytest tests/test_gui_worker.py::test_worker_emits_signals -v`
Expected: FAIL — `ExtractionWorker` does not exist

- [ ] **Step 3: Implement ExtractionWorker**

Add `ExtractionWorker(QThread)` to `gui.py`:

```python
from PySide6.QtCore import QThread, Signal
import pathlib
import time
from extract_rsc import Extractor


class ExtractionWorker(QThread):
    progress_init = Signal(int)
    entry_extracted = Signal(object)
    extraction_finished = Signal(object)
    extraction_error = Signal(str)
    warn_message = Signal(str)

    def __init__(self, input_path: pathlib.Path, out_dir: pathlib.Path, decrypt: bool):
        super().__init__()
        self.input_path = input_path
        self.out_dir = out_dir
        self.decrypt = decrypt

    def run(self):
        try:
            extractor = Extractor(
                out_dir=self.out_dir,
                write_encrypted=True,
                decrypt_encrypted=self.decrypt,
                verbose=False,
                on_entry=lambda d: self.entry_extracted.emit(d),
                on_progress_init=lambda n: self.progress_init.emit(n),
            )
            if self.decrypt and extractor._seed_helper is None:
                self.warn_message.emit("No C compiler found — seed recovery disabled")
            extractor.extract_file(self.input_path)
            self.extraction_finished.emit(extractor.summary)
        except Exception as exc:
            self.extraction_error.emit(str(exc))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/chase/projects/byond-extractor && python -m pytest tests/test_gui_worker.py::test_worker_emits_signals -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /home/chase/projects/byond-extractor
git add gui.py tests/test_gui_worker.py
git commit -m "feat: add ExtractionWorker QThread with signal emissions"
```

### Task 11: Wire everything together — extraction flow

**Files:**
- Modify: `gui.py`

- [ ] **Step 1: Implement _on_file_dropped slot**

In `MainWindow`, implement `_on_file_dropped(self, path: str)`:

```python
def _on_file_dropped(self, path: str):
    file_path = pathlib.Path(path)

    # Validate
    if self._extracting:
        return  # ignore during extraction
    if not file_path.suffix.lower() == ".rsc":
        self._add_message_row("[!] ERROR: File must be a .rsc file", "#cc3333")
        return
    try:
        if not file_path.exists():
            raise FileNotFoundError("file does not exist")
        # Quick read check
        file_path.stat()
    except OSError as exc:
        self._add_message_row(f"[!] ERROR: Could not read file: {exc}", "#cc3333")
        return

    # Reset UI
    self._clear_file_list()
    self._extracting = True

    # Set default output if user hasn't explicitly picked
    if not self._user_picked_output:
        default_out = file_path.parent / "extracted"
        self._output_edit.setText(str(default_out))

    out_dir = pathlib.Path(self._output_edit.text())
    decrypt = self._decrypt_checkbox.isChecked()

    # Update drop zone text
    self._drop_zone.setText(file_path.name)

    # Start worker
    self._worker = ExtractionWorker(file_path, out_dir, decrypt)
    self._worker.progress_init.connect(self._on_progress_init)
    self._worker.entry_extracted.connect(self._on_entry_extracted)
    self._worker.extraction_finished.connect(self._on_extraction_finished)
    self._worker.extraction_error.connect(self._on_extraction_error)
    self._worker.warn_message.connect(
        lambda msg: self._add_message_row(f"[*] WARN: {msg}", "#ccaa00")
    )
    self._worker.start()
```

- [ ] **Step 2: Implement signal handler slots**

```python
def _on_progress_init(self, total: int):
    # Only honor the FIRST progress_init (top-level container).
    # Nested containers also fire on_progress_init but we ignore them
    # so the progress bar tracks top-level entries only.
    if self._progress_initialized:
        return
    self._progress_initialized = True
    self._total_entries = total
    self._current_entry = 0
    self._eta_times = []
    self._show_progress(total)

def _on_entry_extracted(self, entry: dict):
    self._add_file_row(entry)
    self._current_entry += 1
    self._update_progress(self._current_entry)
    # ETA calculation
    now = time.monotonic()
    self._eta_times.append(now)
    if len(self._eta_times) > 50:
        self._eta_times = self._eta_times[-50:]
    if len(self._eta_times) >= 2:
        elapsed = self._eta_times[-1] - self._eta_times[0]
        rate = len(self._eta_times) / elapsed if elapsed > 0 else 0
        remaining = self._total_entries - self._current_entry
        if rate > 0:
            eta_secs = remaining / rate
            mins, secs = divmod(int(eta_secs), 60)
            self._update_eta(f"{mins:02d}:{secs:02d}")

def _on_extraction_finished(self, summary):
    self._extracting = False
    self._update_eta("DONE")
    self._update_progress(self._total_entries)
    self._add_summary_row(summary)
    self._drop_zone.setText("▼ ▼ ▼\nDROP .RSC FILE HERE")

def _on_extraction_error(self, msg: str):
    self._extracting = False
    self._add_message_row(f"[!] ERROR: {msg}", "#cc3333")
    self._hide_progress()
    self._drop_zone.setText("▼ ▼ ▼\nDROP .RSC FILE HERE")
```

- [ ] **Step 3: Add _extracting state flag**

Initialize in `__init__`: `self._extracting = False`, `self._progress_initialized = False`
Initialize: `self._total_entries = 0`, `self._current_entry = 0`, `self._eta_times = []`

Also reset `self._progress_initialized = False` in `_on_file_dropped` (in the "Reset UI" section, alongside `self._clear_file_list()`).

- [ ] **Step 4: Implement _add_summary_row**

```python
def _add_summary_row(self, summary):
    text = (
        f"══ COMPLETE ══  "
        f"Files: {summary.extracted_files}  "
        f"Encrypted: {summary.encrypted_entries}  "
        f"Decrypted: {summary.decrypted_ok}  "
        f"Failed: {summary.decrypted_fail}  "
        f"Valid: {summary.validation_ok}  "
        f"Invalid: {summary.validation_fail}"
    )
    self._add_message_row(text, "#00aaff")
```

- [ ] **Step 5: Manual smoke test**

Run: `cd /home/chase/projects/byond-extractor && python gui.py`
Test: Drop or browse to `sample_rscs/byond.rsc`. Verify:
- Progress bar appears and fills
- File list populates with colored rows
- ETA updates
- Summary row appears at end
- Drop zone resets

- [ ] **Step 6: Commit**

```bash
cd /home/chase/projects/byond-extractor
git add gui.py
git commit -m "feat: wire extraction flow — drop, progress, file list, completion"
```

### Task 12: Run all tests and final verification

**Files:**
- All test files

- [ ] **Step 1: Run all tests**

Run: `cd /home/chase/projects/byond-extractor && python -m pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 2: Syntax check all Python files**

Run: `cd /home/chase/projects/byond-extractor && python -m py_compile extract_rsc.py && python -m py_compile gui.py`
Expected: No output (clean compile)

- [ ] **Step 3: Verify CLI still works unchanged**

Run: `cd /home/chase/projects/byond-extractor && python extract_rsc.py --quiet --decrypt-encrypted -o /tmp/byond_final_test sample_rscs/byond.rsc`
Expected: Same summary output as documented in README (5958 entries, 2 decrypted, etc.)

- [ ] **Step 4: Final commit if any cleanup needed**

```bash
cd /home/chase/projects/byond-extractor
git add extract_rsc.py gui.py tests/
git commit -m "chore: final cleanup and verification"
```
