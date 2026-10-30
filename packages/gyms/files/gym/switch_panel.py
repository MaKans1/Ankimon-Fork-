"""
switch_panel.py — switching in gym battles (user 2026-10-27).

"⇄ Switch…" (manual mode, Showdown engine) swaps the move grid for this panel:
one card per teammate still standing, then "← Back to moves". Clicking a card
switches to it, and that uses your turn.

    ┃ Magnezone              [Recommended]     <- the tag shows on hover
    ┃ Electric / Steel · 100%
    ┃ ▬▬▬▬▬▬▬▬▬▬▬▬ (HP)
    ┃ ▲ Zap Cannon     ▲ Discharge
    ┃ ▼ Flash Cannon     Electric Terrain

The arrows are each move against the foe out now (its Tera type once it has
Terastallized): ▲ super effective, ▼ not very effective or no effect, nothing
for normal damage or a status move. Recommended / Not recommended is the same
simple read the other way too: its best move against the foe, and the foe's
moves (or, without them, its types) against it. Types only, like move cards.
"""

from aqt.qt import (QPushButton, QWidget, QLabel, QHBoxLayout, QVBoxLayout, QGridLayout,
                    QColor, QPainter, QRectF, QSizePolicy, Qt, pyqtSignal)

from .move_card import card_info, foe_types, multiplier, _details, _night, _cap, TYPE_COLOURS

_UP, _DOWN = "▲", "▼"
_MULT = {"super": 2.0, "normal": 1.0, "weak": 0.5, "none": 0.0}


def hp_colour(frac) -> str:
    """As in the games: green above half, yellow to a fifth, red below."""
    return "#4ade80" if frac > 0.5 else "#facc15" if frac > 0.2 else "#f87171"


class _HpBar(QWidget):
    """Thin HP bar that sizes its fill to its own width each time it paints
    (a fill sized from the card's resize could read the bar's width before
    layout, and showed a full bar at 59%)."""

    def __init__(self, frac, night, parent=None):
        super().__init__(parent)
        self.frac = max(0.0, min(1.0, float(frac)))
        self.setFixedHeight(4)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._track = QColor("#3a3f47" if night else "#d8dbe0")
        self._fill = QColor(hp_colour(self.frac))

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        r = QRectF(self.rect())
        p.setBrush(self._track)
        p.drawRoundedRect(r, 2, 2)
        if self.frac > 0:
            p.setBrush(self._fill)
            p.drawRoundedRect(QRectF(0, 0, max(2.0, r.width() * self.frac), r.height()), 2, 2)
        p.end()


def move_name(mv) -> str:
    """"Shadow Punch" for "shadowpunch" (the move data's own name)."""
    return str(_details(mv).get("name") or str(mv).replace("-", " ").title())


def move_arrow(move, foe, foe_tera=None):
    """"up" (super effective), "down" (not very effective / no effect) or None."""
    kind = (card_info(move, foe, foe_tera) or {}).get("kind")
    return "up" if kind == "super" else "down" if kind in ("weak", "none") else None


def _offense(mon, foe, foe_tera=None) -> float:
    """Its best damaging move's effectiveness on the foe (1.0 if it has none)."""
    best = None
    for mv in list(getattr(mon, "attacks", None) or []):
        m = _MULT.get((card_info(mv, foe, foe_tera) or {}).get("kind"))
        if m is not None:
            best = m if best is None else max(best, m)
    return 1.0 if best is None else best


def _defense(mon, foe) -> float:
    """The worst the foe's moves (or, without any, its types) do to it."""
    mine = foe_types(mon)
    if not mine:
        return 1.0
    worst = None
    for mv in list(getattr(foe, "attacks", None) or []):
        d = _details(mv)
        if not d or str(d.get("category") or "") == "Status":
            continue
        m = multiplier(mv, _cap(d.get("type")) or "Normal", mine)
        worst = m if worst is None else max(worst, m)
    if worst is None:
        worst = max([multiplier("", t, mine) for t in foe_types(foe)] or [1.0])
    return worst


def recommended(mon, foe, foe_tera=None) -> bool:
    """Recommended against the foe out now: nothing of its hits this one super
    effectively, and either this one hits it super effectively, or hits it
    normally while resisting what it has."""
    if mon is None or foe is None:
        return False
    off, dfn = _offense(mon, foe, foe_tera), _defense(mon, foe)
    if dfn >= 2:
        return False
    return off >= 2 or (off >= 1 and dfn < 1)


class SwitchCard(QPushButton):
    """One teammate you could switch to (see the module docstring)."""

    def __init__(self, mon, foe, foe_tera=None, parent=None):
        super().__init__("", parent)
        self.mon = mon
        night = _night()
        sub_c = "#9aa4b2" if night else "#5f6b7a"
        up_c, down_c = ("#4ade80", "#f87171") if night else ("#2e9d4d", "#c0392b")
        rec = recommended(mon, foe, foe_tera)
        tag_bg, tag_fg = (("#27500A", "#C0DD97") if night else ("#EAF3DE", "#3B6D11")) if rec else \
                         (("#791F1F", "#F7C1C1") if night else ("#FCEBEB", "#A32D2D"))
        self._box = QWidget(self)
        lay = QVBoxLayout(self._box)
        lay.setContentsMargins(12, 6, 10, 6)
        lay.setSpacing(2)
        top = QHBoxLayout()
        top.setSpacing(6)
        name = QLabel("<b>%s</b>" % mon.name)
        self._tag = QLabel("Recommended" if rec else "Not recommended")
        self._tag.setStyleSheet("background: %s; color: %s; border-radius: 6px; padding: 1px 7px; font-size: 8pt;"
                                % (tag_bg, tag_fg))
        self._tag.setVisible(False)                       # hover shows it
        top.addWidget(name)
        top.addWidget(self._tag)
        top.addStretch(1)
        lay.addLayout(top)
        types = " / ".join(foe_types(mon)) or "?"
        frac = max(0.0, min(1.0, mon.hp / max(1, mon.max_hp)))
        pct = int(round(100.0 * frac))
        sub = QLabel("%s · %d%%" % (types, pct))
        sub.setStyleSheet("color: %s; font-size: 8pt;" % sub_c)
        lay.addWidget(sub)
        lay.addWidget(_HpBar(frac, night))
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(1)
        for i, mv in enumerate(list(mon.attacks or [])[:4]):
            a = move_arrow(mv, foe, foe_tera)
            mark = ('<span style="color:%s; font-size:7pt;">%s</span>&nbsp;' % (up_c if a == "up" else down_c,
                                                                                 _UP if a == "up" else _DOWN)
                    if a else '<span style="font-size:7pt;">&nbsp;&nbsp;&nbsp;</span>&nbsp;')
            lab = QLabel(mark + move_name(mv))
            lab.setStyleSheet("font-size: 9pt;")
            grid.addWidget(lab, i // 2, i % 2)
        lay.addLayout(grid)
        for w in [self._box] + self._box.findChildren(QWidget):
            w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        stripe = TYPE_COLOURS.get((foe_types(mon) or ["Normal"])[0], "#A8A77A")
        self.setStyleSheet(
            "QPushButton { background: palette(button); border: 1px solid palette(mid);"
            " border-left: 5px solid %s; border-radius: 0px; padding: 0px; }"
            "QPushButton:hover { border: 1px solid palette(highlight); border-left: 5px solid %s; }"
            "QPushButton:pressed { background: palette(mid); }" % (stripe, stripe))
        self.setToolTip("Switch to %s - uses your turn." % mon.name)
        self.setMinimumHeight(lay.sizeHint().height() + 4)
        self.setMinimumWidth(lay.sizeHint().width() + 10)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._box.setGeometry(self.rect())

    def showEvent(self, e):
        super().showEvent(e)
        self._box.setGeometry(self.rect())

    def enterEvent(self, e):
        self._tag.setVisible(True)
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._tag.setVisible(False)
        super().leaveEvent(e)


class SwitchPanel(QWidget):
    """The bench, shown in place of the move grid. chosen(mon) / back()."""
    chosen = pyqtSignal(object)
    back = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 6, 0, 0)
        self._grid = QGridLayout()
        self._grid.setSpacing(6)
        root.addLayout(self._grid)
        row = QHBoxLayout()
        b = QPushButton("← Back to moves")
        b.clicked.connect(self.back.emit)
        row.addWidget(b)
        row.addStretch(1)
        note = QLabel("Switching uses your turn")
        note.setStyleSheet("color: %s; font-size: 8pt;" % ("#9aa4b2" if _night() else "#5f6b7a"))
        row.addWidget(note)
        root.addLayout(row)

    def fill(self, bench, foe, foe_tera=None):
        """One card per teammate in `bench` (still standing, not the one out)."""
        while self._grid.count():
            w = self._grid.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        for i, mon in enumerate(bench):
            card = SwitchCard(mon, foe, foe_tera)
            card.clicked.connect(lambda _=False, m=mon: self.chosen.emit(m))
            self._grid.addWidget(card, i // 2, i % 2)
