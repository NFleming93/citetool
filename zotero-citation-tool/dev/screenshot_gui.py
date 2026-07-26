"""Render every screen offscreen and save PNGs so the layouts can be
eyeballed without a display. Run: python dev/screenshot_gui.py"""

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import json
from PySide6.QtWidgets import QApplication

from citetool.gui.wizard import SetupWizard
from citetool.gui.main_window import MainWindow, STATUS_TEXT
from citetool.gui.review import ReviewDialog
from citetool.pipeline import Proposal

OUT = Path(__file__).parent / "screenshots"
OUT.mkdir(exist_ok=True)

app = QApplication([])
app.setStyle("Fusion")

cfg = {"claude_auth_mode": "subscription", "model": "sonnet",
       "zotero_username": "demo", "zotero_api_key": "x", "zotero_user_id": "1"}

# --- wizard, both pages ---
w = SetupWizard(dict(cfg))
w.resize(700, 480)
w.grab().save(str(OUT / "1-wizard-claude.png"))
w.next()
w.grab().save(str(OUT / "2-wizard-zotero.png"))

# --- main window mid-run with representative statuses ---
m = MainWindow(dict(cfg))
m.resize(1000, 640)
m.file_label.setText("Document: my-policy-paper.docx   (read-only)")
rows = [
    ("L001", "Anthropic launches Claude", "https://www.anthropic.com/claude", "ready", ""),
    ("L002", "National Preventive Health Strategy", "https://www.health.gov.au/…", "flagged",
     "date: taken from body text, not metadata"),
    ("L003", "ABS population statistics", "https://www.abs.gov.au/…", "unresolvable",
     "page unreachable and translators returned nothing"),
    ("L004", "Smith et al. 2023", "https://doi.org/10.1000/example123", "verifying", ""),
    ("L005", "AIHW health expenditure", "https://www.aihw.gov.au/…", "resolving", ""),
]
from PySide6.QtWidgets import QTableWidgetItem
for lid, anchor, url, status, detail in rows:
    r = m.table.rowCount()
    m.table.insertRow(r)
    m.table.setItem(r, 0, QTableWidgetItem(lid))
    m.table.setItem(r, 1, QTableWidgetItem(anchor))
    m.table.setItem(r, 2, QTableWidgetItem("Found"))
    m.table.setItem(r, 3, QTableWidgetItem(url))
    m._row_by_url.setdefault(url, []).append(r)
    m._on_event(url, status, detail)
m.btn_run.setEnabled(True)
m.btn_review.setEnabled(True)
m.grab().save(str(OUT / "3-main-window.png"))

# --- review dialog with the classic mix ---
schema = json.loads((Path(__file__).parents[1] / "citetool" / "data" /
                     "schema-fallback.json").read_text())
props = [
    Proposal(url="https://www.anthropic.com/claude", link_ids=["L001"],
             anchor="Anthropic launches Claude", status="ready", approved=True,
             item={"itemType": "webpage", "title": "Claude", "date": "2023",
                   "creators": [{"creatorType": "author", "name": "Anthropic"}]}),
    Proposal(url="https://www.health.gov.au/x", link_ids=["L002"],
             anchor="National Preventive Health Strategy", status="flagged", approved=True,
             item={"itemType": "report",
                   "title": "National Preventive Health Strategy 2021–2030",
                   "date": "2021-12-13",
                   "creators": [{"creatorType": "author",
                                 "name": "Australian Government Department of Health"}]},
             flags=[{"field": "date", "note": "taken from body text, not metadata"}]),
    Proposal(url="https://www.abs.gov.au/x", link_ids=["L003"],
             anchor="ABS population statistics", status="unresolvable",
             reason="page unreachable and translators returned nothing"),
    Proposal(url="https://doi.org/10.1000/example123", link_ids=["L004"],
             anchor="Smith et al. 2023", status="ready", approved=True,
             item={"itemType": "journalArticle", "title": "A translated article",
                   "date": "2023-05",
                   "creators": [{"creatorType": "author", "firstName": "Jane",
                                 "lastName": "Smith"}]}),
]
d = ReviewDialog(props, schema)
d.resize(1080, 480)
d.grab().save(str(OUT / "4-review.png"))

# --- edit dialog for the flagged report ---
from citetool.gui.review import EditDialog
e = EditDialog(props[1], schema)
e.resize(660, 520)
e.grab().save(str(OUT / "5-edit.png"))

print("saved:", sorted(p.name for p in OUT.glob("*.png")))
