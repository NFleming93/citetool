"""The review gate. Every citation in a table; Claude's uncertainty flags
highlighted amber with its note ("author inferred from page footer —
check me"). Edit anything, untick anything. Nothing reaches Zotero until
this dialog is accepted."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                               QPushButton, QTableWidget, QTableWidgetItem,
                               QComboBox, QLineEdit, QCheckBox, QFormLayout,
                               QDialogButtonBox, QHeaderView, QWidget)

from ..zotero_schema import validate_item

AMBER = QColor(255, 236, 179)
RED = QColor(255, 214, 214)
GREEN = QColor(223, 245, 225)

_EXTRA_FIELDS = ["publisher", "institution", "reportNumber", "reportType",
                 "websiteTitle", "publicationTitle", "place", "DOI", "language"]


def _creators_text(item: dict) -> str:
    out = []
    for c in item.get("creators", []):
        out.append(c["name"] if c.get("name")
                   else f"{c.get('lastName','')}, {c.get('firstName','')}".strip(", "))
    return "; ".join(out)


class EditDialog(QDialog):
    def __init__(self, proposal, schema, parent=None):
        super().__init__(parent)
        self.proposal = proposal
        self.schema = schema
        self.setWindowTitle(f"Edit citation — {proposal.anchor}")
        self.setMinimumWidth(640)
        item = proposal.item
        lay = QVBoxLayout(self)

        form = QFormLayout()
        self.type_combo = QComboBox()
        types = [t["itemType"] for t in schema.get("itemTypes", [])]
        self.type_combo.addItems(types)
        if item.get("itemType") in types:
            self.type_combo.setCurrentText(item["itemType"])
        form.addRow("Item type", self.type_combo)
        self.title = QLineEdit(item.get("title", ""))
        form.addRow("Title", self.title)
        self.date = QLineEdit(item.get("date", ""))
        self.date.setPlaceholderText("e.g. 2024-03-14, March 2024, or 2023")
        form.addRow("Date", self.date)
        self.url = QLineEdit(item.get("url", ""))
        form.addRow("URL", self.url)
        self.extras: dict[str, QLineEdit] = {}
        for f in _EXTRA_FIELDS:
            if item.get(f):
                self.extras[f] = QLineEdit(str(item[f]))
                form.addRow(f, self.extras[f])
        lay.addLayout(form)

        lay.addWidget(QLabel("Authors — tick 'Org' for a corporate/institutional "
                             "author (name goes in the single Name box):"))
        self.ctable = QTableWidget(0, 4)
        self.ctable.setHorizontalHeaderLabels(["Org", "Name / Last name",
                                               "First name", "Role"])
        self.ctable.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        for c in item.get("creators", []):
            self._add_creator_row(bool(c.get("name")),
                                  c.get("name") or c.get("lastName", ""),
                                  c.get("firstName", ""),
                                  c.get("creatorType", "author"))
        lay.addWidget(self.ctable)
        crow = QHBoxLayout()
        b_add = QPushButton("Add author"); b_add.clicked.connect(
            lambda: self._add_creator_row(True, "", "", "author"))
        b_del = QPushButton("Remove selected"); b_del.clicked.connect(
            lambda: self.ctable.removeRow(self.ctable.currentRow()))
        crow.addWidget(b_add); crow.addWidget(b_del); crow.addStretch(1)
        lay.addLayout(crow)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def _add_creator_row(self, is_org: bool, name: str, first: str, role: str):
        r = self.ctable.rowCount()
        self.ctable.insertRow(r)
        cb_holder = QWidget(); h = QHBoxLayout(cb_holder)
        h.setContentsMargins(6, 0, 0, 0); h.setAlignment(Qt.AlignCenter)
        cb = QCheckBox(); cb.setChecked(is_org); h.addWidget(cb)
        self.ctable.setCellWidget(r, 0, cb_holder)
        self.ctable.setItem(r, 1, QTableWidgetItem(name))
        self.ctable.setItem(r, 2, QTableWidgetItem(first))
        role_combo = QComboBox(); role_combo.addItems(["author", "contributor", "editor"])
        role_combo.setCurrentText(role if role in ("author", "contributor", "editor")
                                  else "author")
        self.ctable.setCellWidget(r, 3, role_combo)

    def _save(self):
        item = dict(self.proposal.item)
        item["itemType"] = self.type_combo.currentText()
        item["title"] = self.title.text().strip()
        item["date"] = self.date.text().strip()
        item["url"] = self.url.text().strip()
        for f, edit in self.extras.items():
            item[f] = edit.text().strip()
        creators = []
        for r in range(self.ctable.rowCount()):
            cb = self.ctable.cellWidget(r, 0).findChild(QCheckBox)
            name = (self.ctable.item(r, 1).text() if self.ctable.item(r, 1) else "").strip()
            first = (self.ctable.item(r, 2).text() if self.ctable.item(r, 2) else "").strip()
            role = self.ctable.cellWidget(r, 3).currentText()
            if not name:
                continue
            if cb.isChecked():
                creators.append({"creatorType": role, "name": name})
            else:
                creators.append({"creatorType": role, "lastName": name,
                                 "firstName": first})
        item["creators"] = creators
        clean, problems = validate_item(item, self.schema)
        self.proposal.item = clean
        self.proposal.schema_problems = [p for p in problems if p != "no title"]
        if clean.get("title"):
            if self.proposal.status in ("ready", "flagged"):
                pass
        self.accept()


class ReviewDialog(QDialog):
    COLS = ["Add?", "In document as", "Type", "Title", "Author(s)", "Date",
            "Check this"]

    def __init__(self, proposals, schema, parent=None):
        super().__init__(parent)
        self.proposals = proposals
        self.schema = schema
        self.setWindowTitle("Review before writing to Zotero")
        self.setMinimumSize(1050, 560)
        lay = QVBoxLayout(self)
        intro = QLabel("Nothing has been written yet. Amber rows carry a note from "
                       "Claude about a field it wasn't sure of — double-click any "
                       "row to edit it. Untick anything you don't want added.")
        intro.setWordWrap(True)
        lay.addWidget(intro)

        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.Stretch)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.doubleClicked.connect(self._edit_row)
        lay.addWidget(self.table)
        self._fill()

        buttons = QDialogButtonBox()
        self.btn_commit = buttons.addButton("Approve && write to Zotero",
                                            QDialogButtonBox.AcceptRole)
        buttons.addButton(QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._commit)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def _rows(self):
        return [p for p in self.proposals
                if p.status in ("ready", "flagged", "unresolvable", "error")]

    def _fill(self):
        rows = self._rows()
        self.table.setRowCount(0)
        for p in rows:
            r = self.table.rowCount()
            self.table.insertRow(r)
            failed = p.status in ("unresolvable", "error")
            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemIsUserCheckable | (Qt.NoItemFlags if failed else Qt.ItemIsEnabled))
            chk.setCheckState(Qt.Checked if (p.approved and not failed) else Qt.Unchecked)
            self.table.setItem(r, 0, chk)
            notes = "; ".join(f"{f.get('field')}: {f.get('note')}" for f in p.flags)
            if p.schema_problems:
                notes = "; ".join(filter(None, [notes] + p.schema_problems))
            if failed:
                notes = f"NOT ADDED — {p.reason}"
            vals = [p.anchor, p.item.get("itemType", "—"), p.item.get("title", "—"),
                    _creators_text(p.item) or "—", p.item.get("date", "—"), notes]
            colour = RED if failed else (AMBER if p.status == "flagged" else GREEN)
            for c, v in enumerate(vals, start=1):
                cell = QTableWidgetItem(v)
                cell.setBackground(colour)
                if c == 6:
                    cell.setToolTip(v)
                self.table.setItem(r, c, cell)

    def _edit_row(self, index):
        p = self._rows()[index.row()]
        if p.status in ("unresolvable", "error"):
            return
        if EditDialog(p, self.schema, self).exec():
            self._fill()

    def _commit(self):
        for r, p in enumerate(self._rows()):
            if p.status in ("ready", "flagged"):
                p.approved = self.table.item(r, 0).checkState() == Qt.Checked
        self.accept()
