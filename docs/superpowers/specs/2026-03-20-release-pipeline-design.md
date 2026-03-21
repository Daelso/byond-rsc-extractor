# Release Pipeline Design

## Purpose

Automate building standalone single-file executables for Windows and Linux, published as GitHub Releases when a version tag is pushed.

## Trigger

Push a git tag matching `v*` (e.g. `v1.0.0`).

### Permissions

The workflow requires `contents: write` to create GitHub Releases. Specify `permissions: contents: write` at the workflow level.

## Workflow: `.github/workflows/release.yml`

### Build Matrix

Two parallel jobs:

| Runner | Platform | C Compiler | `seed_finder` binary | `--add-data` separator | Output name |
|--------|----------|-----------|---------------------|----------------------|-------------|
| `windows-latest` | Windows | MSVC (`cl.exe`) | `seed_finder.exe` | `;` | `BYOND_RSC_Extractor_Windows.exe` |
| `ubuntu-latest` | Linux | `gcc` | `seed_finder` | `:` | `BYOND_RSC_Extractor_Linux` |

### Build Job Steps

1. **Checkout** — `actions/checkout@v4`
2. **Set up Python 3.10** — `actions/setup-python@v5` with `python-version: "3.10"`
3. **Set up MSVC (Windows only)** — `ilammy/msvc-dev-cmd@v1` to make `cl.exe` available on PATH
4. **Compile `seed_finder`** — this step MUST fail the build if compilation fails (no silent failures):
   - Windows: `cl.exe /O2 seed_finder.c /Feseed_finder.exe` (no colon after `/Fe` for portability)
   - Linux: `gcc -O3 -std=c99 seed_finder.c -o seed_finder`
5. **Install Python deps:** `pip install PySide6 pyinstaller`
6. **Run PyInstaller:**
   - Windows: `pyinstaller --onefile --windowed --name "BYOND_RSC_Extractor_Windows" --add-data "seed_finder.exe;." gui.py`
   - Linux: `pyinstaller --onefile --name "BYOND_RSC_Extractor_Linux" --add-data "seed_finder:." gui.py`
   - `--windowed` on Windows suppresses the console window. Omitted on Linux to avoid stdout/stderr issues when no tty is attached (the GUI sets `verbose=False` so `Extractor` doesn't print, but defensive).
7. **Upload artifact** — `actions/upload-artifact@v4` with the file from `dist/`

### Release Job

Runs after both build jobs complete (`needs: [build]`).

Steps:
1. Download all artifacts — `actions/download-artifact@v4`
2. Create GitHub Release using `softprops/action-gh-release@v2` with:
   - Tag name from `github.ref_name`
   - Auto-generated release notes (`generate_release_notes: true`)
   - Both binaries attached as release assets

## Code Change: `extract_rsc.py`

### `build_seed_helper` return type change

Current signature: `def build_seed_helper(binary_path, source_path) -> bool`
New signature: `def build_seed_helper(binary_path, source_path) -> pathlib.Path | None`

The function currently returns `True`/`False`. Change it to return the `binary_path` on success, or `None` on failure. Add a PyInstaller fallback before returning `None`:

```python
def build_seed_helper(binary_path: pathlib.Path, source_path: pathlib.Path) -> pathlib.Path | None:
    # If binary already exists and is up to date, return it
    if binary_path.exists() and source_path.exists() and binary_path.stat().st_mtime >= source_path.stat().st_mtime:
        return binary_path

    # Try to compile (only if source exists)
    if source_path.exists():
        compiler = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
        if compiler is not None:
            cmd = [compiler, "-O3", "-std=c99", str(source_path), "-o", str(binary_path)]
            try:
                subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            except (subprocess.SubprocessError, OSError):
                pass
            if binary_path.exists():
                return binary_path

    # Fallback: check PyInstaller bundle directory
    # In a PyInstaller --onefile bundle, __file__ resolves to the temp _MEIPASS dir.
    # --add-data places the pre-compiled seed_finder binary in _MEIPASS root.
    # binary_path.name is "seed_finder" (or "seed_finder.exe"), which matches.
    # The compile path above is intentionally dead code in bundled mode
    # (source_path won't exist since seed_finder.c is not bundled).
    meipass = getattr(sys, '_MEIPASS', None)
    if meipass is not None:
        bundled = pathlib.Path(meipass) / binary_path.name
        if bundled.exists():
            return bundled

    return None
```

**Note on `__file__` in PyInstaller bundles:** `Extractor.__init__` derives `helper_binary` and `helper_source` from `pathlib.Path(__file__).resolve()`. In a bundle, `__file__` points into `_MEIPASS`. The source file (`seed_finder.c`) won't exist there, so compilation is skipped. The `_MEIPASS` fallback then finds the pre-compiled binary placed there by `--add-data`. The name match works because `binary_path.name` is `"seed_finder"` (or `"seed_finder.exe"`), which is exactly the filename `--add-data` copies. This is intentional, not coincidental.

**Note on `gui.py` import:** `gui.py` uses a static top-level `from extract_rsc import Extractor`, so PyInstaller's static analysis will detect it. No `--hidden-import` needed.

### Caller update in `Extractor.__init__`

Current:
```python
self._seed_helper = helper_binary if build_seed_helper(helper_binary, helper_source) else None
```

New:
```python
self._seed_helper = build_seed_helper(helper_binary, helper_source)
```

### Impact on CLI

None. The function returns a `Path` (truthy) or `None` (falsy). All downstream code already checks `if self._seed_helper is not None`, so behavior is identical.

## Output Naming

- Windows: `BYOND_RSC_Extractor_Windows.exe`
- Linux: `BYOND_RSC_Extractor_Linux`

## Files Created/Modified

| File | Action |
|------|--------|
| `.github/workflows/release.yml` | Create |
| `extract_rsc.py` | Modify (`build_seed_helper` return type + PyInstaller fallback) |

## Out of Scope

- macOS builds
- Code signing
- Auto-update mechanism
- Installer (`.msi`, `.deb`) — single binary is sufficient
