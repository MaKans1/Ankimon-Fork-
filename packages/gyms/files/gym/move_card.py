"""
move_card.py — the battle window's move buttons as small cards (2026-10-16).

    ┃ 1. Discharge                  [Super effective]
    ┃ Electric · Special · 80 pow · 100% · PP 15/15

The stripe on the left is the move's type colour (the games' palette); the
tag says how the move does against the Pokémon you're facing right now (its
types, or its Tera type once it has Terastallized). Abilities aren't counted -
like the games, the tag only knows types. Everything else (the full effect)
stays in the hover tooltip.

MoveButton is a QPushButton: set_card() shows the card; setText() goes back
to the plain one-line button the Max Move / Z-Move / Tera / Struggle states
use, so those keep their own look.
"""

from aqt.qt import QPushButton, QWidget, QLabel, QHBoxLayout, QVBoxLayout, Qt

# The games' type colours (stripes)
TYPE_COLOURS = {
    "Normal": "#A8A77A", "Fire": "#EE8130", "Water": "#6390F0", "Electric": "#F7D02C",
    "Grass": "#7AC74C", "Ice": "#96D9D6", "Fighting": "#C22E28", "Poison": "#A33EA1",
    "Ground": "#E2BF65", "Flying": "#A98FF3", "Psychic": "#F95587", "Bug": "#A6B91A",
    "Rock": "#B6A136", "Ghost": "#735797", "Dragon": "#6F35FC", "Dark": "#705746",
    "Steel": "#B7B7CE", "Fairy": "#D685AD", "Stellar": "#40B5A5",
}

# Tag colours (background, text) for light and dark themes
_TAGS = {
    "super": ("Super effective", ("#EAF3DE", "#3B6D11"), ("#27500A", "#C0DD97")),
    "weak": ("Not very effective", ("#FCEBEB", "#A32D2D"), ("#791F1F", "#F7C1C1")),
    "normal": ("Normal", ("#F1EFE8", "#5F5E5A"), ("#444441", "#D3D1C7")),
    "none": ("No effect", ("#F1EFE8", "#5F5E5A"), ("#444441", "#D3D1C7")),
    "status": ("Status", ("#F1EFE8", "#5F5E5A"), ("#444441", "#D3D1C7")),
}


def _night() -> bool:
    try:
        from aqt.theme import theme_manager
        return bool(theme_manager.night_mode)
    except Exception:
        return True


def _chart() -> dict:
    try:
        from ..business import _load_type_chart
        return _load_type_chart() or {}
    except Exception:
        return {}


def _details(move) -> dict:
    try:
        from ..functions.pokedex_functions import find_details_move
        return find_details_move(str(move)) or {}
    except Exception:
        return {}


def _cap(t) -> str:
    return str(t or "").strip().capitalize()


def foe_types(foe, tera=None) -> list:
    """The types a move is checked against: the Tera type once it has
    Terastallized (Stellar keeps its own), otherwise its species' types."""
    if tera and _cap(tera) not in ("", "Stellar"):
        return [_cap(tera)]
    src = getattr(foe, "source", None)
    types = getattr(src, "type", None) or (src.get("type") if isinstance(src, dict) else None) or []
    if isinstance(types, str):
        types = [types]
    return [_cap(t) for t in types if t]


def multiplier(move_id, move_type, defender, chart=None) -> float:
    """Type effectiveness of one move against a list of defending types."""
    chart = chart if chart is not None else _chart()
    mid = "".join(ch for ch in str(move_id).lower() if ch.isalnum())
    row = chart.get(_cap(move_type)) or {}
    m = 1.0
    for t in defender:
        if mid == "freezedry" and t == "Water":
            e = 2.0                                     # Freeze-Dry: super effective on Water
        elif mid == "thousandarrows" and t == "Flying":
            e = 1.0                                     # Thousand Arrows hits Flying types
        else:
            e = float(row.get(t, 1))
            if mid == "flyingpress":                    # Fighting and Flying at once
                e *= float((chart.get("Flying") or {}).get(t, 1))
        m *= e
    return m


def card_info(move, foe=None, foe_tera=None) -> dict:
    """What the card shows for one move: stripe colour, tag kind, details line
    (without PP). {} when the move isn't in moves.json."""
    d = _details(move)
    if not d:
        return {}
    mtype = _cap(d.get("type")) or "Normal"
    cat = str(d.get("category") or "")
    power = d.get("basePower")
    acc = d.get("accuracy")
    acc_s = "never misses" if acc is True else ("%s%%" % acc if acc not in (None, "", 0) else "")
    bits = [mtype, cat]
    if cat != "Status" and power not in (None, 0, "0"):
        bits.append("%s pow" % power)
    if acc_s:
        bits.append(acc_s)
    kind = None
    if cat == "Status":
        kind = "status"
    elif foe is not None:
        defender = foe_types(foe, foe_tera)
        if defender:
            m = multiplier(move, mtype, defender)
            kind = "none" if m == 0 else "super" if m > 1 else "weak" if m < 1 else "normal"
    return {"type": mtype, "colour": TYPE_COLOURS.get(mtype, "#A8A77A"), "kind": kind,
            "details": " · ".join(b for b in bits if b)}


class MoveButton(QPushButton):
    """A move button that can show a card (see the module docstring)."""

    def __init__(self, text=""):
        super().__init__(text)
        self.card_on = False
        self._box = QWidget(self)
        lay = QVBoxLayout(self._box)
        lay.setContentsMargins(14, 5, 10, 5)
        lay.setSpacing(1)
        top = QHBoxLayout()
        top.setSpacing(8)
        self._name, self._tag, self._sub = QLabel(), QLabel(), QLabel()
        top.addWidget(self._name, 1)
        top.addWidget(self._tag, 0, Qt.AlignmentFlag.AlignVCenter)
        lay.addLayout(top)
        lay.addWidget(self._sub)
        for w in (self._box, self._name, self._tag, self._sub):
            # clicks and hovers go to the button underneath (tooltip, press)
            w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._box.hide()

    def set_card(self, name, info, pp_text=""):
        """Show the card. info: card_info(); name: "1. Discharge"."""
        if not info:
            self.setText("%s      %s" % (name, pp_text))
            return
        night = _night()
        sub = "#9aa4b2" if night else "#5f6b7a"
        self.card_on = True
        super().setText("")
        self._name.setText(name)
        self._name.setStyleSheet("background: transparent;")
        details = info["details"] + (" · " + pp_text if pp_text else "")
        self._sub.setText(details)
        f = self.font()
        if f.pointSizeF() > 0:
            self._sub.setStyleSheet("background: transparent; color: %s; font-size: %.1fpt;"
                                    % (sub, max(7.0, f.pointSizeF() - 1.5)))
        else:
            self._sub.setStyleSheet("background: transparent; color: %s;" % sub)
        kind = info.get("kind")
        if info.get("tag"):                      # a custom tag (a sealed move: "Sealed · Lv 45")
            kind = "status"
            text, light, dark = info["tag"], _TAGS["status"][1], _TAGS["status"][2]
            bg, fg = dark if night else light
            self._tag.setText(text)
            self._tag.setStyleSheet("background: %s; color: %s; border-radius: 6px; padding: 1px 7px;"
                                    " font-size: 8pt;" % (bg, fg))
            self._tag.show()
        elif kind in _TAGS:
            text, light, dark = _TAGS[kind]
            bg, fg = dark if night else light
            self._tag.setText("<s>%s</s>" % text if kind == "none" else text)
            self._tag.setStyleSheet("background: %s; color: %s; border-radius: 6px; padding: 1px 7px;"
                                    " font-size: 8pt;" % (bg, fg))
            self._tag.show()
        else:
            self._tag.hide()
        c = info["colour"]
        self.setStyleSheet(
            "QPushButton { background: palette(button); border: 1px solid palette(mid);"
            " border-left: 5px solid %s; border-radius: 0px; padding: 0px; }"
            "QPushButton:hover { border: 1px solid palette(highlight); border-left: 5px solid %s; }"
            "QPushButton:pressed { background: palette(mid); }"
            "QPushButton:disabled { border-left: 5px solid palette(mid); }" % (c, c))
        self.setMinimumHeight(max(48, self._box.layout().sizeHint().height()))
        self._box.setGeometry(self.rect())
        self._box.show()

    def card_width(self) -> int:
        """Width the card needs (the battle window widens to fit)."""
        return self._box.layout().sizeHint().width() + 10 if self.card_on else 0

    def setText(self, text):
        """Plain one-line button again (Max Moves, Z-Moves, Tera, Struggle)."""
        if self.card_on:
            self.card_on = False
            self._box.hide()
            self.setStyleSheet("")
            self.setMinimumHeight(34)
        super().setText(text)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._box.setGeometry(self.rect())
