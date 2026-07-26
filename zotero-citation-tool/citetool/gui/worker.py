"""Qt worker threads — all network and Claude work happens off the UI
thread, reporting through signals."""

from __future__ import annotations

from PySide6.QtCore import QThread, Signal


class FunctionWorker(QThread):
    """Run any callable in the background; deliver result or error."""
    ok = Signal(object)
    err = Signal(str)

    def __init__(self, fn, *args, parent=None):
        super().__init__(parent)
        self._fn, self._args = fn, args

    def run(self):
        try:
            self.ok.emit(self._fn(*self._args))
        except Exception as e:
            self.err.emit(f"{type(e).__name__}: {e}"[:500])


class MetadataWorker(QThread):
    """Phase 1+2: read the document, resolve + verify every link."""
    link_event = Signal(str, str, str)          # url, status, detail
    loaded = Signal(object)                     # extraction result
    done = Signal()
    err = Signal(str)

    def __init__(self, pipeline, docx_path: str, parent=None):
        super().__init__(parent)
        self.pipeline = pipeline
        self.docx_path = docx_path
        self.pipeline.progress = lambda u, s, d: self.link_event.emit(u, s, d)

    def run(self):
        try:
            self.loaded.emit(self.pipeline.load_document(self.docx_path))
            self.pipeline.run_metadata()
            self.done.emit()
        except Exception as e:
            self.err.emit(f"{type(e).__name__}: {e}"[:500])


class CommitWorker(QThread):
    """Phase 3, after review approval: dedup, collections, write, report."""
    link_event = Signal(str, str, str)
    done = Signal(dict)
    err = Signal(str)

    def __init__(self, pipeline, parent=None):
        super().__init__(parent)
        self.pipeline = pipeline
        self.pipeline.progress = lambda u, s, d: self.link_event.emit(u, s, d)

    def run(self):
        try:
            self.done.emit(self.pipeline.commit())
        except Exception as e:
            self.err.emit(f"{type(e).__name__}: {e}"[:500])
