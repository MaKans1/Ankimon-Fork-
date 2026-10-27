"""
ankimon_packages.py - which Ankimon 2.0 packages (gyms, wild, showdown) are on.

Every update is the same full .ankiaddon. Anki replaces the whole add-on
folder except user_files, so the choice is kept in
user_files/ankimon2_packages.json and applied at startup, before anything
imports a package:

  * a package that's off has its files renamed (gym -> gym.off), so the core
    runs exactly as if it weren't installed;
  * Ankimon > Other > Packages... switches them (restart Anki to apply).

First start with no record yet (a new player, or updating from 2.0/2.03): a
package counts as yours if its files in user_files are older than this
install - Anki never overwrites user_files, so they're from your earlier
install. If none are, everything is on (new players, the full install).

Package files that have to live in user_files (badge art, the Showdown
helper scripts) ship inside the package as <folder>/_user_files and are
copied over when they differ: Anki skips user_files files that already
exist, so they would never update otherwise.
"""
import json
import os
import shutil
import time

ADDON = os.path.dirname(os.path.abspath(__file__))
USER = os.path.join(ADDON, "user_files")
STATE = os.path.join(USER, "ankimon2_packages.json")
OFF = ".off"
GRACE = 300            # seconds: files this much older than the install predate it

PACKAGES = {           # order matters: switched off right to left, on left to right
    "gyms": {
        "label": "Gyms",
        "summary": "Gym ladders in every region, badges, level caps, expeditions, rematches",
        "paths": ["gym"],
        "ship": "gym/_user_files",
        "evidence": ["user_files/sprites/gym_badges"],
        "requires": [],
    },
    "wild": {
        "label": "Wild",
        "summary": "Smarter wild battles, badge-based wild levels, team rotation, travel, Pokedex regions",
        "paths": ["wild"],
        "ship": "wild/_user_files",
        "evidence": ["user_files/sprites/badges/%d.png" % i for i in range(68, 77)],
        "requires": [],
    },
    "showdown": {
        "label": "Showdown",
        "summary": "Gym and expedition battles follow the real games' rules (Pokemon Showdown)",
        "paths": ["gym/showdown_setup.py", "user_files/showdown/bridge.js"],
        "ship": "gym/_showdown_user_files",
        "evidence": ["user_files/showdown/bridge.js"],
        "requires": ["gyms"],
    },
}


def _p(rel):
    return os.path.join(ADDON, *rel.split("/"))


# ---------------------------------------------------------------- state ----
def read_state():
    try:
        with open(STATE, encoding="utf-8") as f:
            d = json.load(f)
        return {p: bool(d.get("packages", {}).get(p, True)) for p in PACKAGES}
    except (OSError, ValueError):
        return None


def write_state(want, how):
    os.makedirs(USER, exist_ok=True)
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump({"packages": {p: bool(want.get(p)) for p in PACKAGES}, "how": how,
                   "updated": time.strftime("%Y-%m-%d %H:%M")}, f, indent=2)


def closure(want):
    """A package whose requirement is off is off too (showdown needs gyms)."""
    want = dict(want)
    for p, spec in PACKAGES.items():
        if want.get(p) and not all(want.get(r) for r in spec["requires"]):
            want[p] = False
    return want


def installed(p):
    """The package's main files are in the add-on (on or off)."""
    a = _p(PACKAGES[p]["paths"][0])
    if p == "showdown" and not os.path.isdir(_p("gym")):
        a = os.path.join(_p("gym") + OFF, "showdown_setup.py")
    return os.path.exists(a) or os.path.exists(a + OFF)


def enabled(p):
    return os.path.exists(_p(PACKAGES[p]["paths"][0]))


# ------------------------------------------------------- first-start guess ----
def install_time():
    return max(os.path.getmtime(_p(f)) for f in ("__init__.py", "manifest.json") if os.path.exists(_p(f)))


def _oldest(path):
    if os.path.isfile(path):
        return os.path.getmtime(path)
    times = [os.path.getmtime(os.path.join(r, f)) for r, _, fs in os.walk(path) for f in fs]
    return min(times) if times else None


def had_before(p, t=None):
    """Its user_files are older than this install: you had it before updating."""
    t = install_time() if t is None else t
    for rel in PACKAGES[p]["evidence"]:
        path = _p(rel)
        if os.path.exists(path):
            m = _oldest(path)
            if m is not None and m < t - GRACE:
                return True
    return False


def infer():
    t = install_time()
    had = {p: had_before(p, t) for p in PACKAGES}
    if not any(had.values()):
        return {p: True for p in PACKAGES}, "new install: everything on"
    return closure(had), "kept what you had: " + (", ".join(p for p in PACKAGES if had[p]) or "core only")


# -------------------------------------------------------------- applying ----
def _switch(p, on):
    for rel in PACKAGES[p]["paths"]:
        a = _p(rel)
        b = a + OFF
        if on and os.path.exists(b) and not os.path.exists(a):
            os.rename(b, a)
        elif not on and os.path.exists(a):
            if os.path.isdir(b):
                shutil.rmtree(b)
            elif os.path.exists(b):
                os.remove(b)
            os.rename(a, b)


def sync_files(p):
    """Copy the package's shipped user_files where missing or different."""
    src = _p(PACKAGES[p]["ship"])
    n = 0
    if not os.path.isdir(src):
        return 0
    for r, _, fs in os.walk(src):
        for f in fs:
            s = os.path.join(r, f)
            d = os.path.join(USER, os.path.relpath(s, src))
            try:
                with open(s, "rb") as a:
                    new = a.read()
                if os.path.exists(d):
                    with open(d, "rb") as b:
                        if b.read() == new:
                            continue
                os.makedirs(os.path.dirname(d), exist_ok=True)
                shutil.copyfile(s, d)
                n += 1
            except OSError:
                pass
    return n


def apply():
    """Startup, before any package is imported. Never raises."""
    report = {}
    try:
        want = read_state()
        if want is None:
            want, how = infer()
            write_state(want, how)
            report["first_start"] = how
        want = closure(want)
        for p in reversed(list(PACKAGES)):
            if not want[p]:
                _switch(p, False)
        for p in PACKAGES:
            if want[p]:
                _switch(p, True)
                report[p] = sync_files(p)
    except Exception as e:                      # a broken switch must never stop Anki
        report["error"] = repr(e)
    return report


# ---------------------------------------------------------------- update ----
REPO = "https://github.com/MaKans1/Ankimon-Fork-"
LATEST = REPO + "/releases/latest/download/Ankimon.ankiaddon"   # every release from 2.5 on has this name


def open_update():
    """Help > Update: one file for everyone (it used to fetch the original
    Ankimon, which would have replaced 2.0)."""
    from aqt import mw
    from aqt.qt import QMessageBox, Qt
    from aqt.utils import openLink

    on = [PACKAGES[p]["label"] for p in PACKAGES if enabled(p)]
    box = QMessageBox(mw)
    box.setWindowTitle("Update Ankimon")
    box.setTextFormat(Qt.TextFormat.RichText)
    box.setText("<b>Updating is one file for everyone.</b><ol>"
                "<li>Click <b>Download</b> - your browser gets the newest Ankimon.ankiaddon.</li>"
                "<li>Double-click the file (or Tools &gt; Add-ons &gt; Install from file).</li>"
                "<li>Restart Anki.</li></ol>"
                "Your Pokémon, items and progress are kept, and so are your packages "
                "(now: %s - change them in Ankimon &gt; Other &gt; Packages).<br><br>"
                "<small>If Anki ever says <i>Access is denied</i>: close Anki, start it while holding "
                "<b>Shift</b> (add-ons off for that session), then Tools &gt; Add-ons &gt; Install from file "
                "and pick the downloaded file. Restart Anki.</small>" % (", ".join(on) or "core only"))
    dl = box.addButton("Download", QMessageBox.ButtonRole.AcceptRole)
    news = box.addButton("What's new", QMessageBox.ButtonRole.HelpRole)
    box.addButton("Close", QMessageBox.ButtonRole.RejectRole)
    box.exec()
    if box.clickedButton() is dl:
        openLink(LATEST)
    elif box.clickedButton() is news:
        openLink(REPO + "/releases/latest")


# ---------------------------------------------------------------- dialog ----
def open_dialog():
    from aqt import mw
    from aqt.qt import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox, QPushButton
    from aqt.utils import tooltip

    want = closure(read_state() or {p: enabled(p) for p in PACKAGES})
    dlg = QDialog(mw)
    dlg.setWindowTitle("Ankimon Packages")
    v = QVBoxLayout(dlg)
    head = QLabel("<b>Ankimon 2.6 packages</b><br>Untick a package to switch it off. "
                  "Your Pokémon, items and progress are kept either way. "
                  "Changes apply when you restart Anki, and updates keep your choice.")
    head.setWordWrap(True)
    v.addWidget(head)
    boxes = {}
    for p, spec in PACKAGES.items():
        cb = QCheckBox("%s - %s" % (spec["label"], spec["summary"]))
        cb.setChecked(bool(want[p]))
        if not installed(p):
            cb.setEnabled(False)
            cb.setText(cb.text() + "  (not in this download - install the full Ankimon file)")
        if spec["requires"]:
            cb.setToolTip("Needs " + ", ".join(PACKAGES[r]["label"] for r in spec["requires"]))
        boxes[p] = cb
        v.addWidget(cb)

    def _sync():
        for p, spec in PACKAGES.items():
            ok = all(boxes[r].isChecked() for r in spec["requires"])
            if not ok:
                boxes[p].setChecked(False)
            boxes[p].setEnabled(ok and installed(p))
    for cb in boxes.values():
        cb.toggled.connect(lambda *_: _sync())
    _sync()

    row = QHBoxLayout()
    save, cancel = QPushButton("Save"), QPushButton("Cancel")
    row.addStretch(1)
    row.addWidget(save)
    row.addWidget(cancel)
    v.addLayout(row)
    cancel.clicked.connect(dlg.reject)

    def _save():
        new = closure({p: boxes[p].isChecked() for p in PACKAGES})
        if new != want:
            write_state(new, "chosen")
            tooltip("Saved. Restart Anki to apply.", period=4000)
        dlg.accept()
    save.clicked.connect(_save)
    dlg.exec()
