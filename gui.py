#!/usr/bin/env python3
"""BYOND RSC Extractor — NFO/ANSI scene aesthetic GUI (PySide6)."""

from __future__ import annotations

import pathlib
import sys
import time

from PySide6.QtCore import (
    Qt,
    QThread,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QDragEnterEvent,
    QDropEvent,
    QFont,
    QFontDatabase,
    QIcon,
    QPalette,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from extract_rsc import Extractor


# ---------------------------------------------------------------------------
# Colour palette
# ---------------------------------------------------------------------------
C_BG        = "#000000"
C_TEXT      = "#c0c0c0"
C_ACCENT    = "#00aaff"
C_OK        = "#00aa44"
C_DECRYPT   = "#ccaa00"
C_ENC       = "#cc3333"
C_MUTED     = "#333333"
C_BORDER    = "#003355"
C_DIM_BLUE  = "#005588"
C_BTN_BG    = "#001a2e"
C_BTN_BORD  = "#0055aa"
C_PROG_BG   = "#001122"

STATUS_COLORS = {
    "ok":             C_OK,
    "decrypted":      C_DECRYPT,
    "encrypted":      C_ENC,
    "decrypt_failed": C_ENC,
    "error":          C_ENC,
    "warning":        C_DECRYPT,
    "summary":        C_ACCENT,
}

STATUS_SIGILS = {
    "ok":             "[+]",
    "decrypted":      "[*]",
    "encrypted":      "[!]",
    "decrypt_failed": "[!]",
    "error":          "[!]",
    "warning":        "[*]",
    "summary":        " ══",
}

MONO_FAMILIES = ["Courier New", "Courier", "Lucida Console", "DejaVu Sans Mono", "Monospace"]


def mono_font(size: int = 9) -> QFont:
    for fam in MONO_FAMILIES:
        f = QFont(fam, size)
        if QFontDatabase.hasFamily(fam):
            f.setStyleHint(QFont.StyleHint.Monospace)
            return f
    f = QFont()
    f.setStyleHint(QFont.StyleHint.Monospace)
    f.setFixedPitch(True)
    f.setPointSize(size)
    return f


# ---------------------------------------------------------------------------
# Worker thread
# ---------------------------------------------------------------------------
class ExtractionWorker(QThread):
    progress_init      = Signal(int)
    entry_extracted    = Signal(object)
    extraction_finished = Signal(object)
    extraction_error   = Signal(str)
    warn_message       = Signal(str)

    def __init__(self, input_path: pathlib.Path, out_dir: pathlib.Path, decrypt: bool):
        super().__init__()
        self.input_path = input_path
        self.out_dir    = out_dir
        self.decrypt    = decrypt

    def run(self) -> None:
        try:
            extractor = Extractor(
                out_dir=self.out_dir,
                write_encrypted=True,
                decrypt_encrypted=self.decrypt,
                flat_output=True,
                verbose=False,
                on_entry=lambda d: self.entry_extracted.emit(d),
                on_progress_init=lambda n: self.progress_init.emit(n),
            )
            if self.decrypt and extractor._seed_helper is None:
                self.warn_message.emit("No C compiler found — seed recovery disabled")
            extractor.extract_file(self.input_path)
            self.extraction_finished.emit(extractor.summary)
        except Exception as exc:  # noqa: BLE001
            self.extraction_error.emit(str(exc))


# ---------------------------------------------------------------------------
# Drop zone widget
# ---------------------------------------------------------------------------
class DropZone(QLabel):
    """Dashed-border label that accepts .rsc files via drag-and-drop or click."""

    file_dropped = Signal(str)

    _IDLE_TEXT = "▼ ▼ ▼\nDROP .RSC FILE HERE"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFont(mono_font(10))
        self.setMinimumHeight(80)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.reset_text()
        self.setStyleSheet(
            f"color: {C_ACCENT};"
            f"border: 2px dashed {C_BORDER};"
            f"background: {C_BG};"
            "padding: 8px;"
        )
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def reset_text(self) -> None:
        self.setText(self._IDLE_TEXT)

    def set_filename(self, name: str) -> None:
        self.setText(f"[ {name} ]")

    # --- drag-and-drop -------------------------------------------------------
    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # type: ignore[override]
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:  # type: ignore[override]
        urls = event.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            self.file_dropped.emit(path)

    # --- click to open file picker -------------------------------------------
    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open RSC File",
            "",
            "RSC Files (*.rsc);;All Files (*)",
        )
        if path:
            self.file_dropped.emit(path)


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------
HEADER_TEXT = (
    " ██▄ ▀▄▀ ▄▀▄ █▄ █ █▀▄\n"
    " █▄█  █  ▀▄▀ █ ▀█ █▄▀\n"
    " ══════════════════════\n"
    "   R S C   E X T R A C T O R"
)

FOOTER_TEXT = "─── BYOND RSC EXTRACTOR v1.4 ── ──── ─── ── ─"


def _fmt_size(n: int) -> str:
    if n < 1024:
        return f"{n}B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f}KB"
    return f"{n / (1024 * 1024):.1f}MB"


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("BYOND RSC Extractor")
        self.resize(600, 700)
        self.setMinimumSize(500, 500)

        # Window icon — check PyInstaller bundle, then script directory
        icon_path = pathlib.Path(getattr(sys, '_MEIPASS', pathlib.Path(__file__).parent)) / "lol.ico"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        # State
        self._extracting           = False
        self._progress_initialized = False
        self._user_picked_output   = False
        self._total_entries        = 0
        self._done_entries         = 0
        self._eta_start: float     = 0.0
        self._worker: ExtractionWorker | None = None

        # Batch buffer — accumulate entries from worker, flush on timer
        self._pending_entries: list[dict] = []
        self._flush_timer = QTimer(self)
        self._flush_timer.setInterval(50)  # flush every 50ms
        self._flush_timer.timeout.connect(self._flush_entries)

        self._apply_palette()
        self._build_ui()

    # ------------------------------------------------------------------
    # Palette / theme
    # ------------------------------------------------------------------
    def _apply_palette(self) -> None:
        palette = QPalette()
        palette.setColor(QPalette.ColorRole.Window,     QColor(C_BG))
        palette.setColor(QPalette.ColorRole.WindowText, QColor(C_TEXT))
        palette.setColor(QPalette.ColorRole.Base,       QColor(C_BG))
        palette.setColor(QPalette.ColorRole.Text,       QColor(C_TEXT))
        palette.setColor(QPalette.ColorRole.Button,     QColor(C_BTN_BG))
        palette.setColor(QPalette.ColorRole.ButtonText, QColor(C_ACCENT))
        self.setPalette(palette)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        root = QWidget()
        root.setStyleSheet(f"background: {C_BG};")
        self.setCentralWidget(root)
        vbox = QVBoxLayout(root)
        vbox.setContentsMargins(10, 10, 10, 6)
        vbox.setSpacing(6)

        # 1. ASCII header
        header = QLabel(HEADER_TEXT)
        header.setFont(mono_font(10))
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.setStyleSheet(f"color: {C_ACCENT}; background: {C_BG};")
        vbox.addWidget(header)

        # 2. Drop zone
        self._drop_zone = DropZone()
        self._drop_zone.file_dropped.connect(self._on_file_dropped)
        vbox.addWidget(self._drop_zone)

        # 3. Settings row
        settings = QHBoxLayout()
        settings.setSpacing(6)

        self._out_edit = QLineEdit()
        self._out_edit.setReadOnly(True)
        self._out_edit.setFont(mono_font(9))
        self._out_edit.setPlaceholderText("OUTPUT DIRECTORY")
        self._out_edit.setStyleSheet(
            f"background: {C_BG}; border: 1px solid {C_BORDER}; color: {C_DIM_BLUE}; padding: 2px 4px;"
        )
        settings.addWidget(self._out_edit)

        browse_btn = QPushButton("[BROWSE]")
        browse_btn.setFont(mono_font(9))
        browse_btn.setStyleSheet(
            f"background: {C_BTN_BG}; border: 1px solid {C_BTN_BORD}; color: {C_ACCENT}; padding: 3px 8px;"
        )
        browse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        browse_btn.clicked.connect(self._on_browse)
        settings.addWidget(browse_btn)

        self._decrypt_cb = QCheckBox("[✓] DECRYPT")
        self._decrypt_cb.setChecked(True)
        self._decrypt_cb.setFont(mono_font(9))
        self._decrypt_cb.setStyleSheet(
            f"color: {C_ACCENT}; background: {C_BG};"
            f"QCheckBox::indicator {{ border: 1px solid {C_BORDER}; background: {C_BG}; }}"
            f"QCheckBox::indicator:checked {{ background: {C_ACCENT}; }}"
        )
        settings.addWidget(self._decrypt_cb)
        vbox.addLayout(settings)

        # 4. Progress section (hidden initially)
        self._progress_widget = QWidget()
        self._progress_widget.setVisible(False)
        prog_vbox = QVBoxLayout(self._progress_widget)
        prog_vbox.setContentsMargins(0, 0, 0, 0)
        prog_vbox.setSpacing(2)

        prog_labels = QHBoxLayout()
        self._label_count = QLabel("EXTRACTING: 0 / 0")
        self._label_count.setFont(mono_font(8))
        self._label_count.setStyleSheet(f"color: {C_DIM_BLUE};")
        self._label_eta = QLabel("ETA: --:--")
        self._label_eta.setFont(mono_font(8))
        self._label_eta.setStyleSheet(f"color: {C_DIM_BLUE};")
        self._label_eta.setAlignment(Qt.AlignmentFlag.AlignRight)
        prog_labels.addWidget(self._label_count)
        prog_labels.addWidget(self._label_eta)
        prog_vbox.addLayout(prog_labels)

        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._progress_bar.setTextVisible(True)
        self._progress_bar.setFixedHeight(14)
        self._progress_bar.setStyleSheet(
            f"QProgressBar {{"
            f"  background: {C_PROG_BG}; border: 1px solid {C_BORDER};"
            f"  height: 10px; text-align: center; color: {C_ACCENT}; font-size: 9px;"
            f"}}"
            f"QProgressBar::chunk {{"
            f"  background: qlineargradient(x1:0, x2:1,"
            f"    stop:0 #003366, stop:0.5 #0088cc, stop:1 #00bbff);"
            f"}}"
        )
        prog_vbox.addWidget(self._progress_bar)
        vbox.addWidget(self._progress_widget)

        # 5. File list — QListWidget for performance
        self._file_list = QListWidget()
        self._file_list.setFont(mono_font(9))
        self._file_list.setStyleSheet(
            f"QListWidget {{ background: {C_BG}; border: 1px solid {C_BORDER}; outline: none; }}"
            f"QListWidget::item {{ padding: 1px 4px; border-bottom: 1px solid #111; }}"
            f"QScrollBar:vertical {{ background: {C_BG}; width: 8px; }}"
            f"QScrollBar::handle:vertical {{ background: {C_BORDER}; }}"
        )
        vbox.addWidget(self._file_list, 1)  # stretch=1 → expands

        # 6. Footer
        footer = QLabel(FOOTER_TEXT)
        footer.setFont(mono_font(8))
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        footer.setStyleSheet(f"color: {C_BORDER}; background: {C_BG};")
        vbox.addWidget(footer)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _add_list_item(self, text: str, color: str) -> None:
        item = QListWidgetItem(text)
        item.setForeground(QColor(color))
        self._file_list.addItem(item)

    def _scroll_to_bottom(self) -> None:
        self._file_list.scrollToBottom()

    def _flush_entries(self) -> None:
        """Batch-add pending entries to the list widget."""
        if not self._pending_entries:
            return
        batch = self._pending_entries
        self._pending_entries = []

        for entry in batch:
            status = entry.get("status", "ok")
            name   = entry.get("name", "?")
            tname  = entry.get("type_name", "")
            size   = entry.get("size", 0)
            sigil  = STATUS_SIGILS.get(status, "[ ]")
            color  = STATUS_COLORS.get(status, C_TEXT)
            line   = f"{sigil} {name:<40s}  {tname:<10s} {_fmt_size(size):>8s}"
            self._add_list_item(line, color)

        self._done_entries += len(batch)
        self._progress_bar.setValue(min(self._done_entries, self._total_entries))
        self._label_count.setText(f"EXTRACTING: {self._done_entries} / {self._total_entries}")

        # ETA
        elapsed = time.monotonic() - self._eta_start
        if elapsed > 0.5 and self._done_entries > 0:
            rate = self._done_entries / elapsed
            remaining = self._total_entries - self._done_entries
            if rate > 0 and remaining > 0:
                secs = remaining / rate
                self._label_eta.setText(f"ETA: {int(secs) // 60:02d}:{int(secs) % 60:02d}")
            else:
                self._label_eta.setText("ETA: --:--")

        self._scroll_to_bottom()

    # ------------------------------------------------------------------
    # Slots — wiring
    # ------------------------------------------------------------------
    def _on_browse(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "SELECT OUTPUT DIRECTORY", "")
        if path:
            self._out_edit.setText(path)
            self._user_picked_output = True

    def _on_file_dropped(self, path: str) -> None:
        if self._extracting:
            return

        p = pathlib.Path(path)

        if p.suffix.lower() != ".rsc":
            self._add_list_item(f"[!] ERROR: File must be a .rsc file  ({p.name})", C_ENC)
            return

        try:
            _ = p.stat()
        except OSError as exc:
            self._add_list_item(f"[!] ERROR: {exc}", C_ENC)
            return

        self._file_list.clear()
        self._extracting = True
        self._progress_initialized = False
        self._pending_entries = []

        if not self._user_picked_output:
            out_dir = p.parent / "extracted"
            self._out_edit.setText(str(out_dir))
        else:
            out_dir = pathlib.Path(self._out_edit.text())

        self._drop_zone.set_filename(p.name)

        self._worker = ExtractionWorker(
            input_path=p,
            out_dir=out_dir,
            decrypt=self._decrypt_cb.isChecked(),
        )
        self._worker.progress_init.connect(self._on_progress_init)
        self._worker.entry_extracted.connect(self._on_entry_extracted)
        self._worker.extraction_finished.connect(self._on_extraction_finished)
        self._worker.extraction_error.connect(self._on_extraction_error)
        self._worker.warn_message.connect(
            lambda msg: self._add_list_item(f"[*] WARN: {msg}", C_DECRYPT)
        )
        self._flush_timer.start()
        self._worker.start()

    def _on_progress_init(self, total: int) -> None:
        if self._progress_initialized:
            return
        self._progress_initialized = True
        self._total_entries = total
        self._done_entries  = 0
        self._eta_start = time.monotonic()
        self._progress_bar.setRange(0, max(total, 1))
        self._progress_bar.setValue(0)
        self._label_count.setText(f"EXTRACTING: 0 / {total}")
        self._label_eta.setText("ETA: --:--")
        self._progress_widget.setVisible(True)

    def _on_entry_extracted(self, entry: dict) -> None:
        # Buffer entries — flushed by timer every 50ms
        self._pending_entries.append(entry)

    def _on_extraction_finished(self, summary) -> None:
        self._flush_timer.stop()
        self._flush_entries()  # flush any remaining
        self._extracting = False
        self._progress_bar.setValue(self._total_entries)
        self._label_eta.setText("ETA: DONE")

        s = summary
        self._add_list_item(
            f" ══ COMPLETE ══  "
            f"Files: {s.extracted_files}  "
            f"Encrypted: {s.encrypted_entries}  "
            f"Decrypted: {s.decrypted_ok}  "
            f"Failed: {s.decrypted_fail}  "
            f"Valid: {s.validation_ok}  "
            f"Invalid: {s.validation_fail}",
            C_ACCENT,
        )
        self._scroll_to_bottom()
        self._drop_zone.reset_text()

    def _on_extraction_error(self, msg: str) -> None:
        self._flush_timer.stop()
        self._extracting = False
        self._progress_widget.setVisible(False)
        self._add_list_item(f"[!] ERROR: {msg}", C_ENC)
        self._drop_zone.reset_text()

    # ------------------------------------------------------------------
    # Clean shutdown
    # ------------------------------------------------------------------
    def closeEvent(self, event) -> None:  # type: ignore[override]
        self._flush_timer.stop()
        if self._worker is not None and self._worker.isRunning():
            self._worker.terminate()
            self._worker.wait(3000)
        event.accept()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")          # neutral base — we paint over everything
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
