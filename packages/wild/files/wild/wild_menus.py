"""
wild_menus.py - the clickable reviewer sprites and Game -> Travel.

Click your Pokemon   HP, moves (tick the ones to use against wild Pokemon,
                     forget / remember / TM), switch Pokemon, flee.
Click the wild one   level, dex number, region, types, ability, rarity,
                     moves, and how it compares with the one you own.

The sprites send pycmd('ankimon_wild:me' / 'ankimon_wild:foe') from the HUD;
the webview_did_receive_js_message hook below opens the dialogs.
"""
from aqt import mw, gui_hooks
from aqt.qt import (QAction, QActionGroup, QDialog, QVBoxLayout, QHBoxLayout,
                    QGridLayout, QLabel, QPushButton, QCheckBox, QMessageBox,
                    QTimer, QWidget, QFrame, Qt)

from . import wild_rules as W

_MSG_PREFIX = "ankimon_wild:"
_installed = {"hook": False}
_open = {"dlg": None}


def _S():
    from .. import singletons
    return singletons


def _gym_active():
    try:
        from ..gym import gym_ui
        return gym_ui.gym_is_active()
    except Exception:
        return False


def _refresh_hud():
    try:
        class _C:
            pass
        c = _C()
        c.web = mw.reviewer.web
        _S().reviewer_obj.update_life_bar(c, 0, 0)
    except Exception:
        pass


def _tip(msg, colour="#9CCC65"):
    try:
        from ..functions.drawing_utils import tooltipWithColour
        tooltipWithColour(msg, colour)
    except Exception:
        from aqt.utils import tooltip
        tooltip(msg)


def _name(p):
    nick = getattr(p, "nickname", None)
    base = _dn(getattr(p, "name", "?"))
    if nick and str(nick).lower() != base.lower():
        return "%s (%s)" % (nick, base)
    return base


def _types(p):
    return " / ".join(str(t).capitalize() for t in (getattr(p, "type", None) or [])) or "?"


def _status_line(p):
    bits = []
    st = str(getattr(p, "battle_status", "") or "").lower()
    names = {"par": "Paralysed", "brn": "Burned", "slp": "Asleep", "frz": "Frozen",
             "psn": "Poisoned", "tox": "Badly poisoned"}
    if st in names:
        bits.append(names[st])
    stages = getattr(p, "stat_stages", None) or {}
    labels = {"atk": "Atk", "def": "Def", "spa": "SpA", "spd": "SpD", "spe": "Spe",
              "accuracy": "Acc", "evasion": "Eva"}
    for k, lab in labels.items():
        v = int(stages.get(k, 0) or 0)
        if v:
            bits.append("%s %+d" % (lab, v))
    return ", ".join(bits)


def _move_text(move):
    e = W.move_data(move) or {}
    name = e.get("name") or str(move).replace("-", " ").title()
    typ = str(e.get("type") or "?").capitalize()
    cat = str(e.get("category") or "?").capitalize()
    bp = e.get("basePower") or 0
    acc = e.get("accuracy")
    acc_s = "-" if acc is True or acc is None else "%s%%" % acc
    return name, "%s  |  %s  |  Power %s  |  Acc %s" % (typ, cat, bp if bp else "-", acc_s)


def _move_tip(move):
    try:
        from ..pyobj.attack_dialog import move_tooltip
        return move_tooltip(W.move_id(move)) or ""
    except Exception:
        return ""


def _hline():
    f = QFrame()
    f.setFrameShape(QFrame.Shape.HLine)
    f.setFrameShadow(QFrame.Shadow.Sunken)
    return f


def _small(text, grey=True):
    lab = QLabel(text)
    lab.setWordWrap(True)
    lab.setStyleSheet("font-size: 11px;%s" % (" color: gray;" if grey else ""))
    return lab


# ---------------------------------------------------------------- flee ----
def flee(message=None):
    """Free: a new wild Pokémon appears. Hidden rule: never a shiny.
    message: shown even with popups off (e.g. fleeing because you changed
    your team mid-fight)."""
    S = _S()
    from ..functions.encounter_functions import new_pokemon
    old = _name(S.enemy_pokemon)
    W.STATE.block_shiny = True
    try:
        # new_pokemon -> on_new_encounter: buddy back in front, team healed
        new_pokemon(S.enemy_pokemon, S.test_window, S.ankimon_tracker_obj, S.reviewer_obj)
    finally:
        W.STATE.block_shiny = False
    try:
        S.ankimon_tracker_obj.general_card_count_for_battle = 0
    except Exception:
        pass
    _refresh_hud()
    if message:
        from aqt.utils import tooltip
        tooltip(message, period=4000)
    else:
        W.tip("faint", "Got away safely from the wild %s!" % old, "#9CCC65")


# ------------------------------------------------------ buddy menu ----
class BuddyMenu(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent or mw)
        self.setWindowTitle("Your Pokémon")
        self.setMinimumWidth(460)
        self.lay = QVBoxLayout(self)
        self.body = None
        self.note_text = ""
        self._build()

    # --- layout ---
    def _build(self):
        if self.body is not None:
            self.lay.removeWidget(self.body)
            self.body.deleteLater()
        self.body = QWidget()
        v = QVBoxLayout(self.body)
        v.setContentsMargins(0, 0, 0, 0)
        mp = _S().main_pokemon
        star = " ★" if getattr(mp, "shiny", False) else ""
        v.addWidget(QLabel("<b style='font-size:15px'>%s%s</b> &nbsp; Lv %s &nbsp; "
                           "<span style='color:gray'>%s</span>" % (_name(mp), star, mp.level, _types(mp))))
        cap = W.level_cap()
        if cap and int(mp.level) > cap:
            v.addWidget(_small("Fights at Lv %d in %s (the level cap until you earn more badges here)."
                               % (cap, W.region())))
        hp_line = "HP %d / %d" % (int(mp.hp), int(mp.max_hp))
        st = _status_line(mp)
        if st:
            hp_line += "   |   " + st
        v.addWidget(QLabel(hp_line))
        team_line = self._team_line()
        if team_line:
            v.addWidget(_small(team_line))
        v.addWidget(_hline())

        v.addWidget(QLabel("<b>Moves</b>"))
        v.addWidget(_small("Ticked moves are the ones your Pokémon uses against wild "
                           "Pokémon. Hover a move for details."))
        grid = QGridLayout()
        iid = getattr(mp, "individual_id", None)
        self.boxes = []
        for row, mv in enumerate(list(mp.attacks or [])):
            name, detail = _move_text(mv)
            tip = _move_tip(mv)
            cb = QCheckBox(name)
            cb.setChecked(W.move_enabled(iid, mv))
            cb.setToolTip(tip)
            cb.toggled.connect(lambda on, m=mv, box=cb: self._toggle(m, on, box))
            self.boxes.append(cb)
            info = _small(detail)
            info.setToolTip(tip)
            fb = QPushButton("Forget")
            fb.setToolTip("Forget %s for good" % name)
            fb.clicked.connect(lambda _c=False, m=mv: self._forget(m))
            grid.addWidget(cb, row, 0)
            grid.addWidget(info, row, 1)
            grid.addWidget(fb, row, 2)
        grid.setColumnStretch(1, 1)
        v.addLayout(grid)

        row1 = QHBoxLayout()
        b = QPushButton("Remember a Move...")
        b.clicked.connect(self._remember)
        row1.addWidget(b)
        b = QPushButton("Learn from a TM...")
        b.clicked.connect(self._tm)
        row1.addWidget(b)
        v.addLayout(row1)
        v.addWidget(_hline())

        row2 = QHBoxLayout()
        b = QPushButton("Switch In...")
        b.setToolTip("Send in a team member for this fight. Your buddy is back "
                     "in front when the fight ends. (Change your buddy for good "
                     "in Game > Choose Pokémon Team.)")
        b.clicked.connect(self._switch)
        row2.addWidget(b)
        b = QPushButton("Flee")
        b.setToolTip("Free - a new wild Pokémon appears")
        b.clicked.connect(self._flee)
        row2.addWidget(b)
        row2.addStretch(1)
        b = QPushButton("Close")
        b.clicked.connect(self.accept)
        row2.addWidget(b)
        v.addLayout(row2)

        self.note = _small(self.note_text, grey=False)
        self.note.setStyleSheet("font-size: 11px; color: #C0392B;")
        v.addWidget(self.note)
        self.lay.addWidget(self.body)
        self.adjustSize()

    def _say(self, text):
        self.note_text = text
        self.note.setText(text)

    # --- actions ---
    def _toggle(self, move, on, box):
        mp = _S().main_pokemon
        if not on and not any(b.isChecked() for b in self.boxes):
            box.blockSignals(True)
            box.setChecked(True)
            box.blockSignals(False)
            self._say("Keep at least one move ticked.")
            return
        try:
            W.set_move_enabled(getattr(mp, "individual_id", None), move, on)
            self._say("")
        except Exception as e:
            self._say("Could not save that: %s" % e)

    def _sync_moves(self):
        S = _S()
        mp = S.main_pokemon
        try:
            d = mw.ankimon_db.get_pokemon(mp.individual_id)
            if d and d.get("attacks"):
                mp.attacks = list(d["attacks"])
        except Exception:
            pass

    def _forget(self, move):
        S = _S()
        mp = S.main_pokemon
        if len(mp.attacks or []) <= 1:
            self._say("It can't forget its last move.")
            return
        name, _d = _move_text(move)
        if QMessageBox.question(self, "Forget move",
                                "Forget %s? You can remember it again later if it's in "
                                "%s's level-up moves." % (name, _name(mp))) \
                != QMessageBox.StandardButton.Yes:
            return
        from ..gui_classes.pokemon_details import forget_attack
        forget_attack(mp.individual_id, list(mp.attacks), move, S.logger)
        self._sync_moves()
        self._build()

    def _remember(self):
        S = _S()
        mp = S.main_pokemon
        from ..functions.pokedex_functions import get_all_pokemon_moves
        from ..gui_classes.pokemon_details import remember_attack_details_window
        remember_attack_details_window(mp.individual_id, list(mp.attacks),
                                       get_all_pokemon_moves(mp.name, mp.level), S.logger)
        self._sync_moves()
        self._build()

    def _tm(self):
        S = _S()
        mp = S.main_pokemon
        from ..gui_classes.pokemon_details import tm_attack_details_window
        tm_attack_details_window(mp.id, mp.individual_id, list(mp.attacks), S.logger)
        self._sync_moves()
        self._build()

    def _switch(self):
        if _gym_active():
            self._say("Not during a gym battle.")
            return
        S = _S()
        mp = S.main_pokemon
        from ..functions import poke_search as PS
        ready = W.ready_teammates()
        entries = []
        for iid in ready:
            p = mw.ankimon_db.get_pokemon(iid)
            if not p:
                continue
            name = _dn(p.get("name", "?"))
            nick = p.get("nickname") or ""
            label = "%s (Lv %s)" % (name, p.get("level", "?"))
            if nick and str(nick).lower() != name.lower():
                label += " '%s'" % nick
            if p.get("shiny"):
                label += " ★"
            tl = PS.type_label(p.get("type"))
            if tl:
                label += " - " + tl
            entries.append({"key": p["individual_id"], "label": label, "name": name,
                            "nickname": nick, "types": PS.parse_types(p.get("type")),
                            "level": p.get("level")})
        if not entries:
            self._say("No team member is ready to switch in. Add Pokémon to your "
                      "team in Game > Choose Pokémon Team.")
            return
        key = PS.choose_pokemon(self, "Switch In", entries, "Send out (team order):")
        if not key:
            return
        if not W.switch_in(key):
            self._say("Could not switch to that Pokémon.")
            return
        _refresh_hud()
        W.tip("faint", "Go, %s!" % _name(mp))
        self._say("")
        self._build()

    def _team_line(self):
        try:
            cur = _S().main_pokemon.individual_id
            bits = []
            for iid in W.party():
                p = mw.ankimon_db.get_pokemon(iid) or {}
                n = str(p.get("nickname") or _dn(p.get("name") or "?"))
                if iid == cur:
                    n = "<b>%s</b>" % n
                elif iid in W.STATE.fainted:
                    n = "<s>%s</s>" % n
                bits.append(n)
            return "Team: " + "  >  ".join(bits) if len(bits) > 1 else ""
        except Exception:
            return ""

    def _flee(self):
        if _gym_active():
            self._say("You can't flee from a gym battle.")
            return
        flee()
        self.accept()


# ------------------------------------------------------- wild info ----
def collection_status(ep):
    shiny = bool(getattr(ep, "shiny", False))
    try:
        from ..functions.encounter_functions import _duplicate_verdict
        rec = {"id": ep.id, "level": ep.level, "shiny": shiny,
               "iv": dict(getattr(ep, "iv", None) or {})}
        keep, best, why = _duplicate_verdict(rec)
    except Exception:
        return ""
    if best is None:
        return ("Not caught yet - this would be your first shiny one." if shiny
                else "Not caught yet.")
    own = "You own a %sLv %s." % ("shiny " if shiny else "", best.get("level", "?"))
    try:
        if _S().settings_obj.get("battle.replace_duplicate_catches") is False:
            return own + " (Duplicates are kept.)"
    except Exception:
        pass
    if keep:
        return own + " Catching this one would upgrade it: %s." % why
    return own + " Yours is better: %s." % why


class WildInfo(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent or mw)
        self.setWindowTitle("Wild Pokémon")
        self.setMinimumWidth(440)
        v = QVBoxLayout(self)
        ep = _S().enemy_pokemon
        star = " ★ shiny" if getattr(ep, "shiny", False) else ""
        v.addWidget(QLabel("<b style='font-size:15px'>Wild %s</b>%s &nbsp; Lv %s"
                           % (_dn(ep.name), star, ep.level)))
        try:
            dex = int(ep.id)
            g = W.gen_of(dex)
            v.addWidget(QLabel("National Dex #%03d  |  %s (Gen %s)" % (dex, W.region_name(dex), g)))
        except Exception:
            pass
        gender = {"M": "Male", "F": "Female"}.get(str(getattr(ep, "gender", "")).upper(), "Unknown")
        grid = QGridLayout()
        rows = [("Type", _types(ep)),
                ("Ability", str(getattr(ep, "ability", "?")).replace("_", " ").title()),
                ("Rarity", str(getattr(ep, "tier", "?") or "?")),
                ("Gender", gender),
                ("HP", "%d / %d" % (int(ep.hp), int(ep.max_hp)))]
        st = _status_line(ep)
        if st:
            rows.append(("Status", st))
        bd = W.band()
        if bd:
            b, lo, hi = bd
            area = "Lv %d-%d with %s" % (lo, hi, "the champion beaten" if b == 9
                                         else "%d badge%s" % (b, "" if b == 1 else "s"))
            if int(ep.level) > hi:
                area += " - this one is unusually strong!"
            rows.append(("Area", area))
        rows.append(("Region", W.region()))
        for i, (k, val) in enumerate(rows):
            grid.addWidget(QLabel("<b>%s</b>" % k), i, 0)
            lab = QLabel(val)
            lab.setWordWrap(True)
            grid.addWidget(lab, i, 1)
        grid.setColumnStretch(1, 1)
        v.addLayout(grid)
        v.addWidget(_hline())
        v.addWidget(QLabel("<b>Moves</b>"))
        mg = QGridLayout()
        for i, mv in enumerate(list(ep.attacks or [])):
            name, detail = _move_text(mv)
            tip = _move_tip(mv)
            a = QLabel(name)
            a.setToolTip(tip)
            d = _small(detail)
            d.setToolTip(tip)
            mg.addWidget(a, i, 0)
            mg.addWidget(d, i, 1)
        mg.setColumnStretch(1, 1)
        v.addLayout(mg)
        v.addWidget(_hline())
        cs = collection_status(ep)
        if cs:
            v.addWidget(_small(cs, grey=False))
        row = QHBoxLayout()
        row.addStretch(1)
        b = QPushButton("Close")
        b.clicked.connect(self.accept)
        row.addWidget(b)
        v.addLayout(row)


# ------------------------------------------------------------ wiring ----
def open_menu(what):
    if _open["dlg"] is not None:
        return                                  # one at a time (double clicks)
    try:
        dlg = BuddyMenu(mw) if what == "me" else WildInfo(mw) if what == "foe" else None
        if dlg is None:
            return
        _open["dlg"] = dlg
        dlg.exec()
    except Exception as e:
        try:
            from ..pyobj.error_handler import show_warning_with_traceback
            show_warning_with_traceback(parent=mw, exception=e, message="Ankimon wild menu:")
        except Exception:
            print("Ankimon wild menu error:", e)
    finally:
        _open["dlg"] = None


def _on_js_message(handled, message, context):
    if isinstance(message, str) and message.startswith(_MSG_PREFIX):
        what = message[len(_MSG_PREFIX):]
        QTimer.singleShot(0, lambda: open_menu(what))
        return (True, None)
    return handled


def travel(name):
    """Go to another region: its wild Pokémon, gyms, levels and level cap."""
    from aqt.utils import tooltip
    if name == W.region():
        return
    if _gym_active():
        tooltip("Finish the battle you're in before travelling.")
        return
    W.set_region(name)
    S = _S()
    try:
        from ..functions.encounter_functions import new_pokemon
        new_pokemon(S.enemy_pokemon, S.test_window, S.ankimon_tracker_obj, S.reviewer_obj)
        S.ankimon_tracker_obj.general_card_count_for_battle = 0
    except Exception as e:
        print("Ankimon travel: new encounter failed:", e)
    _refresh_hud()
    cap = W.level_cap()
    b = W.badges() or 0
    tooltip("Welcome to %s! %s badge%s here%s." % (
        name, b if b < 9 else "All", "" if b == 1 else "s",
        (" - your Pokémon fight at up to Lv %d" % cap) if cap else ""), period=5000)


def _travel_label(r):
    b = W.badges(r)
    try:
        from ..gym import gym_data
        total = gym_data.badge_count(r)
    except Exception:
        total = 8
    if b is None:
        return r
    return "%s   (%s)" % (r, "Champion" if b >= 9 else "%d/%d badges" % (b, total))


def _refresh_travel_menu(sub):
    cur = W.region()
    for act in sub.actions():
        r = act.data()
        if r:
            act.setText(_travel_label(r))
            act.setChecked(r == cur)


def install(game_menu):
    """Called once from menu_buttons at startup."""
    if not _installed["hook"]:
        gui_hooks.webview_did_receive_js_message.append(_on_js_message)
        _installed["hook"] = True
    sub = game_menu.addMenu("Travel")
    group = QActionGroup(sub)
    group.setExclusive(True)
    for r in W.REGIONS:
        act = QAction(r, sub)
        act.setData(r)
        act.setMenuRole(QAction.MenuRole.NoRole)
        act.setCheckable(True)
        act.triggered.connect(lambda _c=False, name=r: travel(name))
        group.addAction(act)
        sub.addAction(act)
    sub._ankimon_region_group = group          # keep a reference
    # badge counts change as you play: relabel each time the menu opens
    sub.aboutToShow.connect(lambda m=sub: _refresh_travel_menu(m))
    _refresh_travel_menu(sub)
    act = QAction("Wild Battle: Your Pokémon...", game_menu)
    act.setMenuRole(QAction.MenuRole.NoRole)
    act.triggered.connect(lambda: open_menu("me"))
    game_menu.addAction(act)
    act = QAction("Expeditions...", game_menu)
    act.setMenuRole(QAction.MenuRole.NoRole)
    act.triggered.connect(_open_expeditions)
    game_menu.addAction(act)
    # Register what you already own in the Pokedex (and award any region
    # badge already earned) once Anki has finished starting up.
    QTimer.singleShot(4000, _startup_dex)


def _open_expeditions():
    try:
        from ..gym import expedition
        expedition.open_menu()
    except Exception as e:
        try:
            from ..pyobj.error_handler import show_warning_with_traceback
            show_warning_with_traceback(parent=mw, exception=e, message="Ankimon expeditions:")
        except Exception:
            print("Ankimon expeditions error:", e)


def _startup_dex():
    try:
        from . import dex
        dex.sync_and_award()
    except Exception as e:
        print("Ankimon: Pokedex sync at startup failed:", e)


def _dn(n):
    """Real Pokémon name for display ("Iron Hands", "Mr. Mime")."""
    try:
        from ..functions.pokedex_functions import display_name
        return display_name(n)
    except Exception:
        s = str(n or "")
        return s[:1].upper() + s[1:]
