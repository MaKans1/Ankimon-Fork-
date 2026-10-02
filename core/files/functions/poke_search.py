"""
poke_search.py - one search rule for every Pokemon list in Ankimon.

    Type a name, part of a name, or a nickname  -> matching Pokemon
    Type an element type ("fire", "water")      -> every Pokemon of that type
    Words combine (all must match):
        "fire flying" -> Fire/Flying Pokemon
        "fire char"   -> Fire types whose name contains "char"
    A partial word (3+ letters) also matches the start of a type, so the
    list fills in while you type ("gro" -> Ground types and Growlithe).
    Any search sorts the results alphabetically by name.

Used by the team window (XP Share, adventure buddy, switch-in picker), the
bag's "Select Pokemon" picker, the PC box and the gym team select.
"""
import json
import re

TYPES = ["Normal", "Fire", "Water", "Electric", "Grass", "Ice", "Fighting", "Poison",
         "Ground", "Flying", "Psychic", "Bug", "Rock", "Ghost", "Dragon", "Dark",
         "Steel", "Fairy"]
_TYPE_SET = {t.lower() for t in TYPES}
PLACEHOLDER = "Search by name, nickname or type (e.g. fire)"


def tokens(query):
    return [t for t in re.split(r"[\s,/]+", (query or "").strip().lower()) if t]


def is_type(tok):
    return tok in _TYPE_SET


def has_type_term(query):
    return any(is_type(t) for t in tokens(query))


def parse_types(t):
    """Types as a lowercase set, from a list or the JSON text json_extract gives."""
    if t is None:
        return set()
    if isinstance(t, str):
        s = t.strip()
        if s.startswith("["):
            try:
                v = json.loads(s)
                if isinstance(v, (list, tuple)):
                    return {str(x).lower() for x in v}
            except (ValueError, TypeError):
                pass
        return {s.lower()} if s else set()
    if isinstance(t, (list, tuple, set)):
        return {str(x).lower() for x in t}
    return set()


def matches(query, name, nickname="", types=None):
    ts = tokens(query)
    if not ts:
        return True
    tset = types if isinstance(types, set) else parse_types(types)
    hay = ("%s %s" % (name or "", nickname or "")).lower()
    for t in ts:
        if is_type(t):
            if t not in tset:                  # a full type word filters by type
                return False
        elif t not in hay and not (len(t) >= 3 and any(x.startswith(t) for x in tset)):
            return False                       # partial word: name, or start of a type
    return True


def filter_sorted(items, query, name_of, nick_of=lambda x: "", types_of=lambda x: None,
                  level_of=lambda x: 0):
    """Filter a list; with a search term, sort A-Z by name (then higher level first)."""
    if not tokens(query):
        return list(items)
    out = [x for x in items if matches(query, name_of(x), nick_of(x), types_of(x))]

    def key(x):
        try:
            lv = -int(level_of(x) or 0)
        except (TypeError, ValueError):
            lv = 0
        return (str(name_of(x) or "").lower(), lv)
    return sorted(out, key=key)


def sql_filter(query):
    """(sql_fragment, params) for captured_pokemon rows: one AND per word -
    a type word must be in the type list, any other word in name or nickname."""
    parts, params = [], []
    for t in tokens(query):
        if is_type(t):
            parts.append("AND json_extract(data, '$.type') LIKE ?")
            params.append('%%"%s"%%' % t.capitalize())
        elif len(t) >= 3:
            parts.append("AND (LOWER(name) LIKE ? OR LOWER(json_extract(data, '$.nickname')) LIKE ?"
                         " OR LOWER(json_extract(data, '$.type')) LIKE ?)")
            params.extend(["%%%s%%" % t, "%%%s%%" % t, '%%"%s%%' % t])
        else:
            parts.append("AND (LOWER(name) LIKE ? OR LOWER(json_extract(data, '$.nickname')) LIKE ?)")
            params.extend(["%%%s%%" % t, "%%%s%%" % t])
    return " ".join(parts), params


# ------------------------------------------------------------------ Qt ----
def make_search_edit(placeholder=PLACEHOLDER):
    from aqt.qt import QLineEdit
    e = QLineEdit()
    e.setPlaceholderText(placeholder)
    e.setClearButtonEnabled(True)
    return e


class ComboSearch:
    """Filters a QComboBox from a search box without losing the selection.

    entries: dicts with key (identity), data (itemData), label, name,
    nickname, types, icon (QPixmap or None). fixed: (label, data) rows that
    always stay on top, e.g. ("No XP Share", None). The current choice stays
    listed (pinned first) even when it doesn't match, so filtering never
    changes what gets saved - only picking does. Enter opens the dropdown.
    """

    def __init__(self, edit, combo, entries, fixed=(), on_refill=None):
        self.edit, self.combo, self.entries = edit, combo, list(entries)
        self.fixed, self.on_refill = list(fixed), on_refill
        self.keys = []
        edit.textChanged.connect(lambda _t: self.refill())
        edit.returnPressed.connect(combo.showPopup)
        self.refill()

    def current_key(self):
        i = self.combo.currentIndex()
        return self.keys[i] if 0 <= i < len(self.keys) else None

    def select(self, key):
        if key is not None and key in self.keys:
            self.combo.setCurrentIndex(self.keys.index(key))

    def refill(self):
        from aqt.qt import Qt
        cur = self.current_key()
        cur_fixed = self.combo.currentIndex() if cur is None else -1
        shown = filter_sorted(self.entries, self.edit.text(), lambda e: e.get("name"),
                              lambda e: e.get("nickname"), lambda e: e.get("types"),
                              lambda e: e.get("level"))
        if cur is not None and all(e["key"] != cur for e in shown):
            pinned = next((e for e in self.entries if e["key"] == cur), None)
            if pinned is not None:
                shown = [pinned] + shown
        c = self.combo
        c.blockSignals(True)
        c.clear()
        keys = []
        for label, data in self.fixed:
            c.addItem(label, data)
            keys.append(None)
        for e in shown:
            c.addItem(e["label"], e["data"])
            if e.get("icon") is not None:
                c.setItemData(c.count() - 1, e["icon"], Qt.ItemDataRole.DecorationRole)
            keys.append(e["key"])
        self.keys = keys
        if cur is not None and cur in keys:
            c.setCurrentIndex(keys.index(cur))
        elif 0 <= cur_fixed < len(self.fixed):
            c.setCurrentIndex(cur_fixed)
        else:
            c.setCurrentIndex(0 if keys else -1)
        c.blockSignals(False)
        if self.on_refill:
            self.on_refill(len([k for k in keys if k is not None]), len(self.entries))


def choose_pokemon(parent, title, entries, prompt="Select Pokémon:"):
    """Searchable picker dialog. entries: dicts with key, label, name,
    nickname, types, level. Returns the chosen entry's key, or None."""
    from aqt.qt import (QDialog, QVBoxLayout, QLabel, QListWidget, QListWidgetItem,
                        QDialogButtonBox, Qt)
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setMinimumSize(360, 460)
    lay = QVBoxLayout(dlg)
    lay.addWidget(QLabel(prompt))
    edit = make_search_edit()
    lay.addWidget(edit)
    lst = QListWidget()
    lay.addWidget(lst)
    count = QLabel("")
    count.setStyleSheet("color: gray; font-size: 11px;")
    lay.addWidget(count)
    bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    lay.addWidget(bb)

    def refill():
        shown = filter_sorted(entries, edit.text(), lambda e: e.get("name"),
                              lambda e: e.get("nickname"), lambda e: e.get("types"),
                              lambda e: e.get("level"))
        lst.clear()
        for e in shown:
            it = QListWidgetItem(e["label"])
            it.setData(Qt.ItemDataRole.UserRole, e["key"])
            lst.addItem(it)
        if lst.count():
            lst.setCurrentRow(0)
        count.setText("%d of %d shown" % (len(shown), len(entries)))

    edit.textChanged.connect(lambda _t: refill())
    edit.returnPressed.connect(lambda: dlg.accept() if lst.currentItem() else None)
    lst.itemDoubleClicked.connect(lambda _i: dlg.accept())
    bb.accepted.connect(dlg.accept)
    bb.rejected.connect(dlg.reject)
    refill()
    edit.setFocus()
    if dlg.exec() != QDialog.DialogCode.Accepted or lst.currentItem() is None:
        return None
    return lst.currentItem().data(Qt.ItemDataRole.UserRole)


def type_label(types):
    ts = sorted(parse_types(types))
    return "/".join(t.capitalize() for t in ts)
