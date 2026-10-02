from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton, QScrollArea, QFrame
from PyQt6.QtCore import Qt

from ..utils import format_move_name


def _move_details(move_id):
    """Look up a move's stats. Returns {} if anything is unavailable, so the
    dialog degrades to plain buttons rather than failing."""
    try:
        from ..functions.pokedex_functions import find_details_move
        return find_details_move(move_id) or {}
    except Exception:
        return {}


def _fmt_accuracy(acc):
    # moves.json stores "always hits" as boolean True rather than a number.
    if acc is True:
        return "—"
    try:
        return "%s%%" % int(acc)
    except (TypeError, ValueError):
        return "—"


def _tooltip_for(move_id):
    """Rich hover text: type, category, power, accuracy, PP and effect."""
    d = _move_details(move_id)
    name = format_move_name(move_id)
    if not d:
        return "<b>%s</b><br>No details available." % name

    power = d.get("basePower")
    power = "—" if power in (None, 0, "0") else str(power)
    cat = d.get("category") or "—"
    rows = [
        ("Type", d.get("type") or "—"),
        ("Category", cat),
        ("Power", power),
        ("Accuracy", _fmt_accuracy(d.get("accuracy"))),
        ("PP", str(d.get("pp") or "—")),
    ]
    body = "".join(
        "<tr><td style='padding-right:10px;color:#9aa4b2;'>%s</td>"
        "<td><b>%s</b></td></tr>" % (k, v) for k, v in rows)
    desc = d.get("shortDesc") or d.get("desc") or ""
    desc_html = ("<div style='margin-top:6px;max-width:260px;'>%s</div>"
                 % desc) if desc else ""
    return ("<div style='font-size:12px;'><b style='font-size:13px;'>%s</b>"
            "<table style='margin-top:4px;'>%s</table>%s</div>"
            % (name, body, desc_html))


def _summary_line(move_id):
    """One-line stat strip shown on the button itself."""
    d = _move_details(move_id)
    if not d:
        return ""
    power = d.get("basePower")
    power = "—" if power in (None, 0, "0") else str(power)
    return "%s · %s · Pow %s · Acc %s · PP %s" % (
        d.get("type") or "—", d.get("category") or "—", power,
        _fmt_accuracy(d.get("accuracy")), d.get("pp") or "—")


class AttackDialog(QDialog):
    def __init__(self, attacks, new_attack):
        super().__init__()
        self.attacks = attacks
        self.new_attack = new_attack
        self.selected_attack = None
        self.initUI()

    def initUI(self):
        # Display human-readable move names (e.g. "Thunderbolt") while the
        # dialog still returns the RAW move id in ``self.selected_attack`` so
        # callers can index the real ``attacks`` list. The raw move is stashed
        # on each button via a dynamic property and read back in attackSelected.
        new_attack_display = format_move_name(self.new_attack)
        self.setWindowTitle(
            f"Select which Attack to Replace with {new_attack_display}"
        )
        self.setMinimumWidth(430)
        layout = QVBoxLayout()

        layout.addWidget(
            QLabel(f"Select which Attack to Replace with {new_attack_display}")
        )

        # --- the incoming move, with its own stats and hover text ---------
        incoming = QLabel("<b>New move — %s</b><br>"
                          "<span style='color:#9aa4b2;font-size:11px;'>%s</span>"
                          % (new_attack_display, _summary_line(self.new_attack)))
        incoming.setToolTip(_tooltip_for(self.new_attack))
        incoming.setWordWrap(True)
        incoming.setStyleSheet(
            "border:1px solid #3a7; border-radius:6px; padding:6px;")
        layout.addWidget(incoming)

        hint = QLabel("Hover any move for its full details.")
        hint.setStyleSheet("color:#9aa4b2; font-size:11px;")
        layout.addWidget(hint)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(line)

        layout.addWidget(QLabel("Replace which current move?"))

        for attack in self.attacks:
            summary = _summary_line(attack)
            label = format_move_name(attack)
            button = QPushButton("%s\n%s" % (label, summary) if summary else label)
            button.setToolTip(_tooltip_for(attack))
            button.setProperty("raw_move", attack)
            button.setMinimumHeight(44)
            button.setStyleSheet("text-align:center; padding:4px;")
            button.clicked.connect(self.attackSelected)
            layout.addWidget(button)

        reject_button = QPushButton("Reject Attack")
        reject_button.setToolTip(
            "Keep the current moves and do not learn %s." % new_attack_display)
        reject_button.clicked.connect(self.attackNoneSelected)
        layout.addWidget(reject_button)
        self.setLayout(layout)

    def attackSelected(self):
        sender = self.sender()
        # Return the RAW move id (not the formatted label) so callers can index
        # the underlying ``attacks`` list correctly.
        self.selected_attack = sender.property("raw_move")
        self.accept()

    def attackNoneSelected(self):
        sender = self.sender()
        self.selected_attack = sender.text()
        self.reject()


def move_tooltip(move_id):
    """Public alias so other screens (the gym battle window) can show the
    same hover card without duplicating the formatting."""
    return _tooltip_for(move_id)
