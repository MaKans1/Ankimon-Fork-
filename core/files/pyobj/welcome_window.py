"""Welcome to Ankimon 2.x: starting region, daily card goal and catch behaviour
in one window (user 2026-10-28).

Players converting from the original Ankimon keep their Pokémon, so they never
see the starter screen and its goal prompt; they get this once on their first
start instead. New players see it right after choosing a starter (without the
region row - the starter screen already picked one). Help > Welcome to
Ankimon (debug) opens it any time.
"""
import json
import os

from aqt import mw
from aqt.qt import (QColor, QComboBox, QDialog, QFont, QFontMetrics, QHBoxLayout, QLabel,
                    QLineEdit, QPushButton, QStyledItemDelegate, Qt, QTimer, QVBoxLayout)

SEEN_KEY = "welcome_2x"            # metadata table: set once the window has been shown
REGIONS = ["Kanto", "Johto", "Hoenn", "Sinnoh", "Unova", "Kalos", "Alola", "Galar", "Paldea"]
# later regions with their own mechanics on top of gyms
ADVANCED = {"Alola": "Totem trials, kahunas and Z-Moves instead of gyms",
            "Galar": "Dynamax, a Sword or Shield choice and the Champion Cup",
            "Paldea": "Open world: gyms in any order, Titans and Terastallizing"}
TAG = "Not recommended for new players"
TAG_ROLE = 0x0101                   # Qt.ItemDataRole.UserRole + 1
RED = "#d64545"
# same choices and wording as Automatic Battle in Settings (lang/setting_description.json)
CATCH = [("0", "You choose each time (keys or buttons)"),
         ("1", "Always catch"),
         ("2", "Always defeat for EXP"),
         ("3", "Catch new species and better copies of yours, otherwise defeat for EXP")]


def _version():
    try:
        p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "manifest.json")
        return json.load(open(p, encoding="utf-8")).get("name") or "Ankimon 2"
    except Exception:
        return "Ankimon 2"


def _wild():
    try:
        from ..wild import wild_menus, wild_rules
        return wild_menus, wild_rules
    except Exception:
        return None, None                     # wild package off: one region, nothing to pick


def _db():
    from .database_manager import get_db
    return get_db()._get_connection()


def seen() -> bool:
    try:
        return _db().execute("SELECT value FROM metadata WHERE key = ?", (SEEN_KEY,)).fetchone() is not None
    except Exception:
        return True                           # can't tell: never nag


def mark_seen():
    try:
        con = _db()
        con.execute("INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)", (SEEN_KEY, _version()))
        con.commit()
    except Exception:
        pass


class _RegionDelegate(QStyledItemDelegate):
    """Region name, then a small red tag raised to its upper right."""

    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        if not index.data(TAG_ROLE):
            return
        name_w = QFontMetrics(option.font).horizontalAdvance(index.data() or "")
        f = QFont(option.font)
        if f.pointSizeF() > 0:
            f.setPointSizeF(max(7.0, f.pointSizeF() * 0.75))
        painter.save()
        painter.setFont(f)
        painter.setPen(QColor(RED))
        r = option.rect
        painter.drawText(r.left() + name_w + 12, r.top() + QFontMetrics(f).ascent() + 1, TAG)
        painter.restore()


class WelcomeDialog(QDialog):
    def __init__(self, settings_obj, ask_region=True, parent=None):
        super().__init__(parent or mw)
        self.settings_obj = settings_obj
        self.setWindowTitle("Ankimon")
        self.setMinimumWidth(500)
        wild_menus, wild_rules = _wild()
        self.ask_region = ask_region and wild_rules is not None
        self.cur_goal = self._int("battle.daily_average", 100)
        self.cur_catch = self._int("battle.automatic_battle", 3)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 16)
        title = QLabel("Welcome to %s, let's get started" % _version())
        tf = title.font()
        if tf.pointSizeF() > 0:
            tf.setPointSizeF(tf.pointSizeF() * 1.35)
        tf.setBold(True)
        title.setFont(tf)
        lay.addWidget(title)
        lay.addSpacing(10)

        if self.ask_region:
            lay.addWidget(self._label("Starting region"))
            row = QHBoxLayout()
            self.region = QComboBox()
            self.region.setItemDelegate(_RegionDelegate(self.region))
            for i, r in enumerate(REGIONS):
                self.region.addItem(r)
                if r in ADVANCED:
                    self.region.setItemData(i, True, TAG_ROLE)
                    self.region.setItemData(i, ADVANCED[r], Qt.ItemDataRole.ToolTipRole)
            fm = QFontMetrics(self.region.font())
            self.region.view().setMinimumWidth(fm.horizontalAdvance("Paldea  " + TAG) + 40)
            self.start_region = wild_rules.region()
            self.region.setCurrentText(self.start_region)
            self.region_tag = QLabel(TAG)
            self.region_tag.setStyleSheet("color: %s; font-size: 11px;" % RED)
            self.region.currentTextChanged.connect(self._sync_tag)
            row.addWidget(self.region, 1)
            row.addWidget(self.region_tag)
            lay.addLayout(row)
            self._sync_tag(self.region.currentText())
            lay.addWidget(self._hint("You can travel between regions any time (Game › Travel), "
                                     "and each keeps its own progress."))
            lay.addSpacing(10)

        lay.addWidget(self._label("Daily card goal"))
        self.goal = QLineEdit(str(self.cur_goal))
        self.goal.setFixedWidth(110)
        lay.addWidget(self.goal)
        self.goal_err = self._error()
        lay.addWidget(self.goal_err)
        lay.addWidget(self._hint("Sets how fast you progress: gyms and EXP are paced to it. "
                                 "All of this can be changed later in Ankimon Settings."))
        lay.addSpacing(10)

        lay.addWidget(self._label("Catch behavior"))
        self.catch = QLineEdit(str(self.cur_catch))
        self.catch.setFixedWidth(50)
        lay.addWidget(self.catch)
        self.catch_err = self._error()
        lay.addWidget(self.catch_err)
        lay.addWidget(self._hint("Enter 0, 1, 2 or 3:\n" + "\n".join("%s  ·  %s" % c for c in CATCH)))

        self.goal.textEdited.connect(lambda _: self.goal_err.hide())
        self.catch.textEdited.connect(lambda _: self.catch_err.hide())
        btns = QHBoxLayout()
        btns.addStretch(1)
        go = QPushButton("Let's go")
        go.setDefault(True)
        go.clicked.connect(self._save)
        btns.addWidget(go)
        lay.addSpacing(8)
        lay.addLayout(btns)

    # ---------------------------------------------------------------- widgets
    def _int(self, key, default):
        try:
            return int(self.settings_obj.get(key, default))
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _label(text):
        w = QLabel(text)
        f = w.font()
        f.setBold(True)
        w.setFont(f)
        return w

    @staticmethod
    def _hint(text):
        w = QLabel(text)
        w.setWordWrap(True)
        w.setStyleSheet("color: #888;")             # readable in light and dark themes
        return w

    @staticmethod
    def _error():
        w = QLabel()
        w.setStyleSheet("color: %s;" % RED)
        w.hide()
        return w

    def _sync_tag(self, region):
        self.region_tag.setVisible(region in ADVANCED)
        self.region.setToolTip(ADVANCED.get(region, ""))

    # ------------------------------------------------------------------ save
    def _save(self):
        ok = True
        try:
            goal = int(self.goal.text().strip())
            assert 10 <= goal <= 5000
        except (ValueError, AssertionError):
            self.goal_err.setText("Enter a whole number from 10 to 5000")
            self.goal_err.show()
            ok = False
        c = self.catch.text().strip()
        if c not in {k for k, _ in CATCH}:
            self.catch_err.setText("Enter 0, 1, 2 or 3")
            self.catch_err.show()
            ok = False
        if not ok:
            return
        values = {"battle.daily_average": goal, "battle.automatic_battle": int(c)}
        # a new goal re-paces gyms and EXP, as the starter's goal prompt does; an
        # unchanged one leaves intervals you've tuned yourself alone
        if goal != self.cur_goal or not seen():
            try:
                from ..functions import pacing
                values.update(pacing.recommended(goal, self.settings_obj.get("battle.cards_per_round", 2)))
            except Exception:
                pass
        for k, v in values.items():
            self.settings_obj.set(k, v)
            try:                                # keep an open Settings window in step
                w = mw.settings_ankimon.input_widgets.get(k)
                if w is not None and hasattr(w, "setText"):
                    w.setText(str(v))
            except Exception:
                pass
        mark_seen()
        self.accept()
        if self.ask_region and self.region.currentText() != self.start_region:
            wild_menus, _ = _wild()
            QTimer.singleShot(0, lambda r=self.region.currentText(): wild_menus.travel(r))


def open_welcome(ask_region=True):
    """Show the window (modal). Returns True if the player saved it."""
    from ..singletons import settings_obj
    d = WelcomeDialog(settings_obj, ask_region=ask_region)
    saved = d.exec() == QDialog.DialogCode.Accepted
    mark_seen()                                # closing it counts too: Help menu reopens it
    return saved


def maybe_show():
    """Once per save, for players who arrive with Pokémon (converted from Ankimon)."""
    if seen():
        return
    QTimer.singleShot(1500, open_welcome)       # after the main window has settled
