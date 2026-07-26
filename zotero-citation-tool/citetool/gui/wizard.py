"""First-run setup wizard.

Page 1 — Claude: subscription sign-in (launches the bundled Claude Code
CLI's browser login in a terminal window), or an API key as fallback.
Page 2 — Zotero: opens the exact key-creation page, one paste box, and a
live test that reports precisely ("✓ Connected — jane, 1,204 items,
write access confirmed" / "your key doesn't have write access ticked").
The user ID is derived from the key automatically — nothing to look up.
"""

from __future__ import annotations

import subprocess
import sys
import webbrowser

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QWizard, QWizardPage, QVBoxLayout, QHBoxLayout,
                               QLabel, QPushButton, QLineEdit, QRadioButton,
                               QButtonGroup)

from .. import config
from ..claude_verify import ClaudeVerifier, find_bundled_cli
from ..zotero_client import ZoteroClient, ZoteroError
from .worker import FunctionWorker

ZOTERO_NEW_KEY_URL = "https://www.zotero.org/settings/keys/new"

GREEN = "color: #1a7f37; font-weight: bold;"
RED = "color: #b42318; font-weight: bold;"
GREY = "color: #555;"


class ClaudePage(QWizardPage):
    def __init__(self, cfg: dict):
        super().__init__()
        self.cfg = cfg
        self._verified = False
        self.setTitle("Step 1 of 2 — Connect Claude")
        self.setSubTitle("Claude does the careful judgement work: checking each "
                         "source and repairing bad citation metadata.")
        lay = QVBoxLayout(self)

        self.rb_sub = QRadioButton("Use my Claude subscription (Pro/Max — recommended)")
        self.rb_key = QRadioButton("Use an Anthropic API key instead (pay-as-you-go)")
        self.rb_sub.setChecked(cfg.get("claude_auth_mode", "subscription") == "subscription")
        self.rb_key.setChecked(not self.rb_sub.isChecked())
        group = QButtonGroup(self)
        group.addButton(self.rb_sub); group.addButton(self.rb_key)
        lay.addWidget(self.rb_sub)

        sub_row = QHBoxLayout()
        self.btn_signin = QPushButton("Sign in with Claude…")
        self.btn_signin.clicked.connect(self._launch_signin)
        sub_row.addWidget(self.btn_signin)
        sub_hint = QLabel("A black window opens and your browser asks you to "
                          "approve. At the end, the black window shows a long "
                          "code starting with sk-ant-.")
        sub_hint.setWordWrap(True); sub_hint.setStyleSheet(GREY)
        sub_row.addWidget(sub_hint, 1)
        lay.addLayout(sub_row)

        lay.addWidget(QLabel("Copy that code (drag the mouse across it, then "
                             "press Enter) and paste it here:"))
        self.token_edit = QLineEdit()
        self.token_edit.setEchoMode(QLineEdit.Password)
        self.token_edit.setPlaceholderText("sk-ant-…  (from the black window)")
        lay.addWidget(self.token_edit)

        lay.addSpacing(12)
        lay.addWidget(self.rb_key)
        self.key_edit = QLineEdit()
        self.key_edit.setEchoMode(QLineEdit.Password)
        self.key_edit.setPlaceholderText("sk-ant-…  (from console.anthropic.com)")
        lay.addWidget(self.key_edit)

        lay.addSpacing(12)
        check_row = QHBoxLayout()
        self.btn_check = QPushButton("Check connection")
        self.btn_check.clicked.connect(self._check)
        check_row.addWidget(self.btn_check)
        self.status = QLabel("Not checked yet.")
        self.status.setWordWrap(True)
        check_row.addWidget(self.status, 1)
        lay.addLayout(check_row)
        lay.addStretch(1)

    def _launch_signin(self):
        cli = find_bundled_cli()
        if not cli:
            self.status.setStyleSheet(RED)
            self.status.setText("Couldn't find the bundled Claude sign-in program — "
                                "please report this (Help → copy log).")
            return
        try:
            if sys.platform == "win32":
                # cmd /k keeps the window open afterwards so the code it
                # prints stays on screen for copying.
                subprocess.Popen(["cmd", "/c", "start", "Claude sign-in",
                                  "cmd", "/k", cli, "setup-token"], shell=False)
            else:
                subprocess.Popen(["x-terminal-emulator", "-e", cli, "setup-token"])
            self.status.setStyleSheet(GREY)
            self.status.setText("Approve the sign-in in your browser, then copy "
                                "the long sk-ant-… code from the black window "
                                "into the box below.")
        except Exception as e:
            self.status.setStyleSheet(RED)
            self.status.setText(f"Couldn't open the sign-in window: {e}")

    def _mode(self) -> str:
        return "subscription" if self.rb_sub.isChecked() else "api_key"

    def _check(self):
        self.btn_check.setEnabled(False)
        self.status.setStyleSheet(GREY)
        self.status.setText("Checking — this takes a few seconds…")
        self.cfg["claude_oauth_token"] = self.token_edit.text().strip()
        config.save(self.cfg)   # the verifier reads the code from config
        verifier = ClaudeVerifier(model="haiku", auth_mode=self._mode(),
                                  api_key=self.key_edit.text().strip())
        self._worker = FunctionWorker(verifier.check_auth)
        self._worker.ok.connect(self._checked)
        self._worker.err.connect(lambda m: self._checked((False, m)))
        self._worker.start()

    def _checked(self, result):
        ok, detail = result
        self.btn_check.setEnabled(True)
        self._verified = ok
        if ok:
            self.status.setStyleSheet(GREEN)
            self.status.setText("✓ Claude is connected and responding.")
            self.cfg["claude_auth_mode"] = self._mode()
            self.cfg["anthropic_api_key"] = self.key_edit.text().strip()
        else:
            self.status.setStyleSheet(RED)
            if "not logged in" in detail.lower():
                self.status.setText("✗ The sign-in code hasn't reached the app — "
                                    "paste the long sk-ant-… code from the black "
                                    "window into the box above, then check again.")
            else:
                self.status.setText("✗ Not connected yet. If you just signed in, wait a "
                                    f"moment and try again. Detail: {detail}")
        self.completeChanged.emit()

    def isComplete(self) -> bool:
        return self._verified


class ZoteroPage(QWizardPage):
    def __init__(self, cfg: dict):
        super().__init__()
        self.cfg = cfg
        self._ok = False
        self.setTitle("Step 2 of 2 — Connect your Zotero library")
        self.setSubTitle("Takes about three minutes, once, and it's free.")
        lay = QVBoxLayout(self)

        steps = QLabel(
            "1.  Press the button below — it opens Zotero's 'new key' page "
            "(log in / create a free account if asked).\n"
            "2.  On that page tick BOTH:   ☑ Allow library access    "
            "☑ Allow write access\n"
            "3.  Press 'Save Key', copy the key it shows you, and paste it here.")
        steps.setWordWrap(True)
        lay.addWidget(steps)

        self.btn_open = QPushButton("Open the Zotero key page in my browser")
        self.btn_open.clicked.connect(lambda: webbrowser.open(ZOTERO_NEW_KEY_URL))
        lay.addWidget(self.btn_open)

        lay.addSpacing(10)
        lay.addWidget(QLabel("Paste your new Zotero key:"))
        self.key_edit = QLineEdit()
        self.key_edit.setEchoMode(QLineEdit.Password)
        self.key_edit.editingFinished.connect(self._test)
        lay.addWidget(self.key_edit)

        row = QHBoxLayout()
        self.btn_test = QPushButton("Test connection")
        self.btn_test.clicked.connect(self._test)
        row.addWidget(self.btn_test)
        self.status = QLabel("Waiting for your key. It stays on this computer and "
                             "is only ever sent to zotero.org.")
        self.status.setWordWrap(True)
        row.addWidget(self.status, 1)
        lay.addLayout(row)
        lay.addStretch(1)

    def _test(self):
        key = self.key_edit.text().strip()
        if not key:
            return
        self.btn_test.setEnabled(False)
        self.status.setStyleSheet(GREY)
        self.status.setText("Testing against zotero.org…")

        def check():
            return ZoteroClient(key).connection_summary()

        self._worker = FunctionWorker(check)
        self._worker.ok.connect(self._tested)
        self._worker.err.connect(self._failed)
        self._worker.start()

    def _tested(self, summary: dict):
        self.btn_test.setEnabled(True)
        self._ok = True
        self.status.setStyleSheet(GREEN)
        self.status.setText(f"✓ Connected — {summary['username']}'s library, "
                            f"{summary['item_count']:,} items, write access confirmed.")
        self.cfg.update({"zotero_api_key": self.key_edit.text().strip(),
                         "zotero_user_id": summary["user_id"],
                         "zotero_username": summary["username"]})
        self.completeChanged.emit()

    def _failed(self, msg: str):
        self.btn_test.setEnabled(True)
        self._ok = False
        self.status.setStyleSheet(RED)
        self.status.setText(f"✗ {msg}")
        self.completeChanged.emit()

    def isComplete(self) -> bool:
        return self._ok


class SetupWizard(QWizard):
    def __init__(self, cfg: dict):
        super().__init__()
        self.cfg = cfg
        self.setWindowTitle("CiteTool — first-run setup")
        self.setWizardStyle(QWizard.ModernStyle)
        self.setMinimumSize(680, 460)
        self.addPage(ClaudePage(cfg))
        self.addPage(ZoteroPage(cfg))

    def accept(self):
        self.cfg["setup_complete"] = True
        config.save(self.cfg)
        super().accept()
