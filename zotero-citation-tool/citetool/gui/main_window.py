"""Main window: pick a .docx (drag-and-drop or browse), watch each link
march through found → resolved → verified, review, commit, report."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                               QLabel, QPushButton, QComboBox, QFileDialog,
                               QTableWidget, QTableWidgetItem, QTextEdit,
                               QMessageBox, QHeaderView)

from .. import config
from ..claude_verify import ClaudeVerifier, MODEL_CHOICES
from ..pipeline import Pipeline, setup_logging, load_schema_cached
from ..zotero_client import ZoteroClient
from .review import ReviewDialog
from .worker import MetadataWorker, CommitWorker, FunctionWorker

STATUS_TEXT = {
    "resolving": ("Looking up metadata…", None),
    "fetching": ("Reading the page…", None),
    "verifying": ("Claude is checking…", None),
    "ready": ("✓ Verified", QColor(223, 245, 225)),
    "flagged": ("⚠ Verified — check note", QColor(255, 236, 179)),
    "unresolvable": ("✗ Couldn't resolve", QColor(255, 214, 214)),
    "error": ("✗ Error", QColor(255, 214, 214)),
    "matched": ("✓ Already in library", QColor(223, 245, 225)),
    "added": ("✓ Added to Zotero", QColor(223, 245, 225)),
    "failed": ("✗ Failed", QColor(255, 214, 214)),
}


class MainWindow(QMainWindow):
    def __init__(self, cfg: dict):
        super().__init__()
        self.cfg = cfg
        self.docx_path: str | None = None
        self.pipeline: Pipeline | None = None
        self.log_path = setup_logging()
        self.setWindowTitle(f"CiteTool — Zotero library: {cfg.get('zotero_username','')}")
        self.setMinimumSize(980, 620)
        self.setAcceptDrops(True)

        root = QWidget(); self.setCentralWidget(root)
        lay = QVBoxLayout(root)

        top = QHBoxLayout()
        self.btn_pick = QPushButton("Choose a .docx…  (or drop one anywhere here)")
        self.btn_pick.clicked.connect(self._pick)
        top.addWidget(self.btn_pick, 1)
        top.addWidget(QLabel("Claude model:"))
        self.model_combo = QComboBox()
        for alias, desc in MODEL_CHOICES:
            self.model_combo.addItem(desc, alias)
        idx = [a for a, _ in MODEL_CHOICES].index(cfg.get("model", "sonnet"))
        self.model_combo.setCurrentIndex(idx)
        top.addWidget(self.model_combo)
        lay.addLayout(top)

        self.file_label = QLabel("No document chosen yet. Your document is only "
                                 "ever read — never changed.")
        lay.addWidget(self.file_label)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Link", "In document as", "Status",
                                              "Detail"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        lay.addWidget(self.table, 1)

        btns = QHBoxLayout()
        self.btn_run = QPushButton("1 · Analyse document")
        self.btn_run.setEnabled(False)
        self.btn_run.clicked.connect(self._analyse)
        self.btn_review = QPushButton("2 · Review && write to Zotero…")
        self.btn_review.setEnabled(False)
        self.btn_review.clicked.connect(self._review)
        self.btn_log = QPushButton("Open run log")
        self.btn_log.clicked.connect(self._open_log)
        btns.addWidget(self.btn_run); btns.addWidget(self.btn_review)
        btns.addStretch(1); btns.addWidget(self.btn_log)
        lay.addLayout(btns)

        self.report = QTextEdit(); self.report.setReadOnly(True)
        self.report.setMaximumHeight(140); self.report.hide()
        lay.addWidget(self.report)
        self._row_by_url: dict[str, list[int]] = {}

    # ---- file choosing ----

    def dragEnterEvent(self, e):
        if any(u.toLocalFile().lower().endswith(".docx") for u in e.mimeData().urls()):
            e.acceptProposedAction()

    def dropEvent(self, e):
        for u in e.mimeData().urls():
            if u.toLocalFile().lower().endswith(".docx"):
                self._set_file(u.toLocalFile()); return

    def _pick(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose a Word document", "",
                                              "Word documents (*.docx)")
        if path:
            self._set_file(path)

    def _set_file(self, path: str):
        self.docx_path = path
        self.file_label.setText(f"Document: {Path(path).name}   (read-only)")
        self.btn_run.setEnabled(True)
        self.btn_review.setEnabled(False)
        self.report.hide()
        self.table.setRowCount(0)

    # ---- phase 1+2 ----

    def _analyse(self):
        self.btn_run.setEnabled(False)
        self.cfg["model"] = self.model_combo.currentData()
        config.save(self.cfg)
        try:
            verifier = ClaudeVerifier(model=self.cfg["model"],
                                      auth_mode=self.cfg["claude_auth_mode"],
                                      api_key=self.cfg.get("anthropic_api_key", ""))
            zotero = ZoteroClient(self.cfg["zotero_api_key"],
                                  self.cfg["zotero_user_id"])
            schema = load_schema_cached()
        except Exception as e:
            QMessageBox.critical(self, "Setup problem", str(e))
            self.btn_run.setEnabled(True)
            return
        self.pipeline = Pipeline(verifier=verifier, zotero=zotero, schema=schema)
        self._worker = MetadataWorker(self.pipeline, self.docx_path)
        self._worker.loaded.connect(self._on_loaded)
        self._worker.link_event.connect(self._on_event)
        self._worker.done.connect(self._on_metadata_done)
        self._worker.err.connect(self._on_error)
        self._worker.start()

    def _on_loaded(self, extraction):
        self.table.setRowCount(0)
        self._row_by_url = {}
        for l in extraction.links:
            r = self.table.rowCount()
            self.table.insertRow(r)
            self.table.setItem(r, 0, QTableWidgetItem(l.link_id))
            self.table.setItem(r, 1, QTableWidgetItem(l.anchor_text))
            self.table.setItem(r, 2, QTableWidgetItem("Found"))
            self.table.setItem(r, 3, QTableWidgetItem(l.url))
            self._row_by_url.setdefault(l.url, []).append(r)
        if not extraction.links:
            QMessageBox.information(self, "No links",
                                    "No web links were found in this document.")

    def _on_event(self, url: str, status: str, detail: str):
        text, colour = STATUS_TEXT.get(status, (status, None))
        if not url:
            self.file_label.setText(detail or text)
            return
        for r in self._row_by_url.get(url, []):
            self.table.item(r, 2).setText(text)
            if detail:
                self.table.item(r, 3).setText(detail)
            if colour:
                for c in range(self.table.columnCount()):
                    self.table.item(r, c).setBackground(colour)

    def _on_metadata_done(self):
        self.btn_run.setEnabled(True)
        self.btn_review.setEnabled(True)
        n_flag = sum(1 for p in self.pipeline.proposals if p.status == "flagged")
        n_fail = sum(1 for p in self.pipeline.proposals
                     if p.status in ("unresolvable", "error"))
        msg = "Verification finished. "
        if n_flag:
            msg += f"{n_flag} citation(s) carry a check-me note. "
        if n_fail:
            msg += f"{n_fail} link(s) couldn't be resolved (reported honestly, not guessed). "
        msg += "Nothing has been written yet — press Review."
        self.file_label.setText(msg)

    # ---- phase 3 ----

    def _review(self):
        dlg = ReviewDialog(self.pipeline.proposals, self.pipeline.schema, self)
        if not dlg.exec():
            return
        self.btn_review.setEnabled(False)
        self._cworker = CommitWorker(self.pipeline)
        self._cworker.link_event.connect(self._on_event)
        self._cworker.done.connect(self._on_committed)
        self._cworker.err.connect(self._on_error)
        self._cworker.start()

    def _on_committed(self, summary: dict):
        c = summary["counts"]
        lines = [f"Done.  Added: {c.get('added',0)}   Matched to existing: "
                 f"{c.get('matched-existing',0)}   Failed: {c.get('failed',0)}   "
                 f"Skipped: {c.get('skipped',0)}"]
        fails = [p for p in summary["proposals"] if p.action == "failed"]
        for p in fails:
            lines.append(f"  ✗ {p.anchor} — {p.failure or p.reason}   ({p.url})")
        lines.append(f"Mapping file for future use saved: {summary['citemap']}")
        lines.append("New items appear in the Zotero desktop app after its next "
                     "sync (the green arrow, or wait a minute).")
        self.report.setPlainText("\n".join(lines))
        self.report.show()
        self.file_label.setText("Run complete — summary below, full details in the log.")

    def _on_error(self, msg: str):
        self.btn_run.setEnabled(True)
        QMessageBox.critical(self, "Something went wrong",
                             msg + f"\n\nThe full log is at:\n{self.log_path}")

    def _open_log(self):
        import webbrowser
        webbrowser.open(str(self.log_path))
