# PyInstaller build spec. App-folder ("onedir") build: the Agent SDK
# bundles a ~275MB Claude CLI binary, and a single-file exe would
# re-extract all of it on every launch. This way startup is instant.
from PyInstaller.utils.hooks import collect_all

datas, binaries, hiddenimports = [], [], []
for pkg in ("claude_agent_sdk",):
    d, b, h = collect_all(pkg)
    datas += d; binaries += b; hiddenimports += h
datas += [("citetool/data", "citetool/data")]

a = Analysis(["main.py"], datas=datas, binaries=binaries,
             hiddenimports=hiddenimports + ["pypdf"], excludes=["tkinter"])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, exclude_binaries=True, name="CiteTool",
          console=False, icon=None)
coll = COLLECT(exe, a.binaries, a.datas, name="CiteTool")
