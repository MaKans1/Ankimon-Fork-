"""
expedition.py - optional dungeons with a legendary at the end.

THE RULES
  - Ankimon > Game > Expeditions. Each region has its own: Kanto's three
    birds unlock at 5 Kanto badges; the other regions' at their intro badges.
    You can only set out on the expeditions of the region you're in.
  - You take your team (up to 6, in team order) through three floors of
    defenders, then the legendary. No entry cost; go any time.
  - Damage, status, PP and fainted Pokémon carry over from floor to floor.
    Between floors you make camp: use Potions, Revives, Full Heals, Elixirs...
    from your bag on anyone in the team.
  - The legendary has to be beaten in one go with the team as it is - there
    is no camp during that fight. Beat it = catch it.
  - If your whole team faints, or you retreat, the run ends. Nothing you own
    was ever damaged (the run fights on copies), so there is nothing to heal.
  - Cash for each floor cleared and the battle XP are banked and paid when the
    run ends (win or lose), so level-ups and evolutions don't pop up
    mid-dungeon.

Battles reuse the gym window and the Showdown engine (real game rules); the
only engine change is that a team can start a fight already damaged.
"""
import copy
import random
from types import SimpleNamespace
from typing import Dict, List, Optional

from aqt import mw
from aqt.qt import (QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
                    QPushButton, QMessageBox, QTimer, QFrame, QMenu, QWidget, Qt)

from .gym_state import Combatant, GymSession
from .expedition_data import EXPEDITIONS, Expedition
from . import gym_battle as GB
from . import gym_config as CFG

_run = None                     # the ExpeditionRun in progress, if any


def is_active() -> bool:
    return _run is not None


def _log(lvl, m):
    try:
        from ..singletons import logger
        logger.log(lvl, "[expedition] %s" % m)
    except Exception:
        print("[expedition] %s" % m)


# ------------------------------------------------------------ unlocks ----
EXPEDITION_REGION = "Kanto"      # default region (the birds live in Kanto)


def badges(region=EXPEDITION_REGION) -> int:
    try:
        from ..wild import wild_rules
        return int(wild_rules.badges(region) or 0)
    except Exception:
        return 0


def here() -> str:
    try:
        from ..wild import wild_rules
        return wild_rules.region()
    except Exception:
        return EXPEDITION_REGION


def caught(exp: Expedition) -> bool:
    try:
        from ..wild import dex
        return exp.legendary_id in dex.registered()
    except Exception:
        return False


def status(exp: Expedition):
    """(can_start, label)"""
    if caught(exp):
        return False, "%s caught" % exp.legendary
    reg = getattr(exp, "region", EXPEDITION_REGION)
    b = badges(reg)
    if b < exp.badges_needed:
        return False, "Locked - needs %d %s badges (you have %d)" % (
            exp.badges_needed, reg, b)
    if here() != reg:
        return False, "Travel to %s to set out" % reg
    return True, "Ready"


# -------------------------------------------------------------- items ----
HEAL = {"potion": 20, "super-potion": 60, "hyper-potion": 120, "max-potion": -1,
        "full-restore": -1, "fresh-water": 30, "soda-pop": 50, "lemonade": 70,
        "moomoo-milk": 100, "energy-powder": 60, "energy-root": 120,
        "berry-juice": 20, "sweet-heart": 20}
REVIVE = {"revive": 0.5, "max-revive": 1.0, "revival-herb": 1.0}
CURE = {"full-heal": None, "full-restore": None, "lava-cookie": None, "old-gateau": None,
        "casteliacone": None, "lumiose-galette": None, "shalour-sable": None,
        "antidote": ("psn", "tox"), "paralyze-heal": ("par",), "awakening": ("slp",),
        "burn-heal": ("brn",), "ice-heal": ("frz",)}
PP_ITEMS = {"ether": (10, False), "max-ether": (999, False), "elixir": (10, True), "max-elixir": (999, True)}
USABLE = set(HEAL) | set(REVIVE) | set(CURE) | set(PP_ITEMS)


def _label(name):
    return str(name).replace("-", " ").title()


def bag() -> Dict[str, int]:
    out = {}
    try:
        for it in mw.ankimon_db.get_all_items() or []:
            n = str(it.get("item_name") or "").lower()
            q = int(it.get("quantity") or 0)
            if n in USABLE and q > 0:
                out[n] = q
    except Exception as e:
        _log("warning", "could not read the bag: %s" % e)
    return out


def can_use(item, c: Combatant) -> bool:
    st = getattr(c, "status", None)
    if item in REVIVE:
        return c.hp <= 0
    if c.hp <= 0:
        return False
    if item in HEAL and c.hp < c.max_hp:
        return True
    if item in CURE and st:
        cures = CURE[item]
        return cures is None or st in cures
    if item in PP_ITEMS:
        return any(c.pp.get(m, 0) < c.max_pp.get(m, 0) for m in c.attacks)
    return False


def apply_item(item, c: Combatant) -> str:
    """Use one item on a team member (a run copy). Returns what happened."""
    name = c.name
    if item in REVIVE:
        c.hp = max(1, int(c.max_hp * REVIVE[item]))
        c.status = None
        return "%s was revived! (%d/%d HP)" % (name, c.hp, c.max_hp)
    out = []
    if item in HEAL and c.hp < c.max_hp:
        amt = HEAL[item]
        before = c.hp
        c.hp = c.max_hp if amt < 0 else min(c.max_hp, c.hp + amt)
        out.append("%s recovered %d HP." % (name, c.hp - before))
    if item in CURE and getattr(c, "status", None):
        cures = CURE[item]
        if cures is None or c.status in cures:
            out.append("%s was cured." % name)
            c.status = None
    if item in PP_ITEMS:
        amount, all_moves = PP_ITEMS[item]
        moves = [m for m in c.attacks if c.max_pp.get(m, 0)]
        if not all_moves:
            moves = sorted(moves, key=lambda m: c.pp.get(m, 0) / max(1, c.max_pp.get(m, 1)))[:1]
        for m in moves:
            c.pp[m] = min(c.max_pp[m], c.pp.get(m, 0) + amount)
        out.append("%s's PP was restored." % name)
    return " ".join(out) or "It had no effect."


def consume(item):
    try:
        mw.ankimon_db.update_item_quantity(item, -1)
    except Exception as e:
        _log("warning", "could not remove %s from the bag: %s" % (item, e))


# -------------------------------------------------------------- teams ----
def _team_records() -> List[dict]:
    recs = []
    try:
        for slot in mw.ankimon_db.get_team() or []:
            iid = slot.get("individual_id")
            rec = mw.ankimon_db.get_pokemon(iid) if iid else None
            if rec:
                rec.setdefault("individual_id", iid)
                recs.append(rec)
    except Exception as e:
        _log("error", "could not read your team: %s" % e)
    if not recs:
        try:
            main = mw.ankimon_db.get_main_pokemon()
            if main:
                recs = [main]
        except Exception:
            pass
    return recs[:6]


def build_team() -> List[Combatant]:
    out = []
    for rec in _team_records():
        p = GB._obj_from_saved(copy.deepcopy(rec))
        if p is None:
            continue
        pp = GB.build_pp(p.attacks)
        c = Combatant(name=p.name, level=p.level, max_hp=int(p.max_hp), hp=int(p.max_hp),
                      attacks=list(p.attacks), species_id=p.id, individual_id=p.individual_id,
                      is_player=True, source=p, pp=dict(pp), max_pp=dict(pp))
        c.carry = True          # gym_showdown passes HP / status / PP into the next fight
        c.status = None
        out.append(c)
    return out


def build_foes(floor) -> List[Combatant]:
    out = []
    for mon in floor.foes:
        p = GB.build_leader_pokemon(mon)
        if p is None:
            continue
        if floor.boss:
            # Legendaries: three perfect IVs, like the modern games
            iv = {k: random.randint(0, 31) for k in ("hp", "atk", "def", "spa", "spd", "spe")}
            for k in random.sample(list(iv), 3):
                iv[k] = 31
            p.iv = iv
            p.tier = "Legendary"
            mx = int(p.calculate_max_hp())
            p.max_hp = p.hp = p.current_hp = mx
        pp = GB.build_pp(p.attacks)
        out.append(Combatant(name=p.name, level=p.level, max_hp=int(p.max_hp), hp=int(p.max_hp),
                             attacks=list(p.attacks), species_id=p.id, is_player=False,
                             source=p, pp=dict(pp), max_pp=dict(pp)))
    return out


# ---------------------------------------------------------------- run ----
class ExpeditionRun:
    def __init__(self, exp: Expedition):
        self.exp = exp
        self.team = build_team()
        self.floor_i = 0
        self.sd = None
        self.window = None
        self.xp_bank: Dict[str, int] = {}
        self.cash = 0
        self.log: List[str] = []
        self.caught_obj = None

    @property
    def floor(self):
        return self.exp.floors[self.floor_i]

    def start(self) -> bool:
        if not self.team:
            QMessageBox.warning(mw, "Expedition", "You need at least one Pokémon in your team.")
            return False
        try:
            from .gym_ui import _prestart_showdown
            self.sd = _prestart_showdown()
        except Exception:
            self.sd = None
        self._fight()
        return True

    # --- one floor ----------------------------------------------------
    def _fight(self):
        floor = self.floor
        alive = [c for c in self.team if c.hp > 0]
        foes = build_foes(floor)
        if not alive or not foes:
            self._end("error")
            return
        leader = floor.foes[0].species if floor.boss else "Wild Pokémon"
        gym = SimpleNamespace(gym_id=None, name="%s: %s" % (self.exp.name, floor.name),
                              leader=leader, badge_name="", cash_reward=floor.cash,
                              team=floor.foes, kind="expedition", is_elite=False)
        session = GymSession(gym, alive, foes)
        if self.sd is not None:
            try:
                self.sd.start(alive, foes, leader, wild=True)
                session.engine = self.sd
            except Exception as e:
                _log("warning", "Showdown could not start this floor, using classic: %s" % e)
                try:
                    self.sd.close()
                except Exception:
                    pass
                self.sd = None
        _log("info", "%s, %s: engine = %s" % (self.exp.name, floor.name,
                                               "Showdown" if session.engine is not None else "classic"))
        from .gym_window import GymBattleWindow
        self.window = GymBattleWindow(session, CFG.auto_battle(), self._floor_done, parent=mw)
        self.window.show()
        self.window.raise_()
        self.window.activateWindow()

    def _floor_done(self, session):
        # Called from inside the battle window's close; continue once it's gone.
        QTimer.singleShot(0, lambda: self._after_floor(session))

    def _after_floor(self, session):
        self.window = None
        floor = self.floor
        if session.status != GymSession.WON:
            self._end("lost" if not any(c.hp > 0 for c in self.team) else "fled")
            return
        survivors = [c for c in self.team if c.hp > 0]
        xp_each = max(1, int(sum(m.level for m in floor.foes) * 4 / max(1, len(survivors))))
        for c in survivors:
            self.xp_bank[c.individual_id] = self.xp_bank.get(c.individual_id, 0) + xp_each
        self.cash += floor.cash
        self.log.append("%s cleared (+%d XP each to %d, $%d)." % (floor.name, xp_each, len(survivors), floor.cash))
        if floor.boss:
            self._catch(session)
            self._end("won")
            return
        self.floor_i += 1
        camp = CampDialog(self, parent=mw)
        if camp.exec() == QDialog.DialogCode.Accepted:
            self._fight()
        else:
            self._end("retreat")

    def _catch(self, session):
        try:
            boss = session.leader_team[0].source
            from ..functions.pokemon_functions import shiny_chance
            from ..functions.encounter_functions import save_caught_pokemon
            from ..singletons import achievements
            boss.shiny = bool(shiny_chance())
            boss.tier = "Legendary"
            boss.stat_stages = {k: 0 for k in ("atk", "def", "spa", "spd", "spe", "accuracy", "evasion")}
            boss.battle_status = "fighting"
            save_caught_pokemon(boss, _dn(boss.name), achievements)
            self.caught_obj = boss
        except Exception as e:
            _log("error", "saving the legendary failed: %s" % e)
            QMessageBox.warning(mw, "Expedition", "You won, but saving %s failed: %s"
                                % (self.exp.legendary, e))

    # --- the end ------------------------------------------------------
    def _end(self, result):
        global _run
        try:
            if self.sd is not None:
                self.sd.close()
        except Exception:
            pass
        lines = list(self.log)
        paid = self._pay_out()
        if paid:
            lines.append(paid)
        if result == "won":
            title = "You caught %s!" % self.exp.legendary
            lines.insert(0, "%s is yours. It's in your collection now." % self.exp.legendary
                         + (" And it's SHINY!" if getattr(self.caught_obj, "shiny", False) else ""))
        elif result == "lost":
            title = "Your team was overwhelmed"
            lines.insert(0, "Everyone fainted on %s. You made it back safely - "
                            "your team is fine. Try again any time." % self.floor.name)
        elif result == "fled":
            title = "You fled %s" % self.exp.name
            lines.insert(0, "You ran from the fight on %s. Your team is fine - "
                            "try again any time." % self.floor.name)
        elif result == "retreat":
            title = "You left %s" % self.exp.name
            lines.insert(0, "You retreated before %s." % self.floor.name)
        else:
            title = "Expedition"
            lines.insert(0, "The expedition could not continue.")
        _run = None
        try:
            from ..wild import dex
            dex.sync_and_award()
        except Exception:
            pass
        QMessageBox.information(mw, title, "\n".join(lines))

    def _pay_out(self) -> str:
        parts = []
        if self.cash:
            try:
                from ..singletons import settings_obj
                settings_obj.set("trainer.cash", int(settings_obj.get("trainer.cash") or 0) + self.cash)
                parts.append("$%d" % self.cash)
            except Exception as e:
                _log("warning", "cash payout failed: %s" % e)
        if self.xp_bank:
            try:
                from ..singletons import logger, settings_obj, evo_window
                from ..functions.trainer_functions import xp_share_gain_exp
                for iid, xp in self.xp_bank.items():
                    # halves what it is given; handles level-ups and evolutions
                    xp_share_gain_exp(logger, settings_obj, evo_window, None, int(xp) * 2, iid)
                    self._sync_live(iid)
                parts.append("%d XP across %d Pokémon" % (sum(self.xp_bank.values()), len(self.xp_bank)))
            except Exception as e:
                _log("warning", "XP payout failed: %s" % e)
        return ("Earned: " + ", ".join(parts) + ".") if parts else ""

    @staticmethod
    def _sync_live(iid):
        """If the buddy gained levels, reload it so the HUD and wild battles see it."""
        try:
            from ..singletons import main_pokemon
            if getattr(main_pokemon, "individual_id", None) == iid:
                from ..functions.update_main_pokemon import update_main_pokemon
                update_main_pokemon(main_pokemon)
                main_pokemon.hp = main_pokemon.max_hp
        except Exception:
            pass


# --------------------------------------------------------------- camp ----
def _hp_text(c):
    if c.hp <= 0:
        return "<span style='color:#C0392B'><b>FAINTED</b></span>"
    st = (" <b>%s</b>" % str(c.status).upper()) if getattr(c, "status", None) else ""
    low = [m for m in c.attacks if c.max_pp.get(m) and c.pp.get(m, 0) <= c.max_pp[m] // 4]
    pp = (" <span style='color:gray'>(low PP: %s)</span>" % ", ".join(_label(m) for m in low)) if low else ""
    return "%d / %d HP%s%s" % (c.hp, c.max_hp, st, pp)


class CampDialog(QDialog):
    """Between floors: patch the team up from the bag, then press on."""

    def __init__(self, run: ExpeditionRun, parent=None):
        super().__init__(parent or mw)
        self.run = run
        self.setWindowTitle("Camp - %s" % run.exp.name)
        self.setMinimumWidth(520)
        self.lay = QVBoxLayout(self)
        self.body = None
        self.note = ""
        self._build()

    def _build(self):
        if self.body is not None:
            self.lay.removeWidget(self.body)
            self.body.deleteLater()
        self.body = QWidget()
        v = QVBoxLayout(self.body)
        v.setContentsMargins(0, 0, 0, 0)
        run, floor = self.run, self.run.floor
        if floor.boss:
            nxt = ("<b>Next: %s, Lv %d.</b> This is the last camp - the fight has to be won "
                   "in one go with the team as it is." % (floor.foes[0].species, floor.foes[0].level))
        else:
            nxt = "<b>Next: %s</b> - %s" % (floor.name, ", ".join(
                "%s Lv %d" % (m.species, m.level) for m in floor.foes))
        v.addWidget(QLabel("Floor %d of %d cleared. %s" % (run.floor_i, len(run.exp.floors), nxt)))
        lab = QLabel()
        lab.setWordWrap(True)
        v.addWidget(lab)
        lab.setText("<br>".join("<b>%s</b> Lv %d - %s" % (c.name, c.level, _hp_text(c)) for c in run.team))
        v.addWidget(self._line())

        items = bag()
        if items:
            v.addWidget(QLabel("<b>Bag</b> - click an item, then pick who gets it"))
            grid = QGridLayout()
            for i, (name, qty) in enumerate(sorted(items.items())):
                b = QPushButton("%s  x%d" % (_label(name), qty))
                b.setEnabled(any(can_use(name, c) for c in run.team))
                b.clicked.connect(lambda _c=False, n=name, btn=b: self._pick_target(n, btn))
                grid.addWidget(b, i // 3, i % 3)
            v.addLayout(grid)
        else:
            v.addWidget(QLabel("Your bag has no Potions, Revives or Full Heals. "
                               "(The Ankimon Mart sells them.)"))
        if self.note:
            n = QLabel(self.note)
            n.setStyleSheet("color:#2E86C1;")
            n.setWordWrap(True)
            v.addWidget(n)
        v.addWidget(self._line())
        row = QHBoxLayout()
        leave = QPushButton("Retreat")
        leave.setToolTip("End the expedition. You keep the cash and XP earned so far.")
        leave.clicked.connect(self.reject)
        go = QPushButton("Face %s!" % floor.foes[0].species if floor.boss else "Continue to %s" % floor.name)
        go.setDefault(True)
        go.clicked.connect(self.accept)
        row.addWidget(leave)
        row.addStretch(1)
        row.addWidget(go)
        v.addLayout(row)
        self.lay.addWidget(self.body)
        self.adjustSize()

    @staticmethod
    def _line():
        f = QFrame()
        f.setFrameShape(QFrame.Shape.HLine)
        f.setFrameShadow(QFrame.Shadow.Sunken)
        return f

    def _pick_target(self, item, btn):
        menu = QMenu(self)
        for c in self.run.team:
            a = menu.addAction("%s  (%s)" % (c.name, "fainted" if c.hp <= 0 else "%d/%d HP" % (c.hp, c.max_hp)))
            a.setEnabled(can_use(item, c))
            a.triggered.connect(lambda _c=False, cc=c: self._use(item, cc))
        menu.exec(btn.mapToGlobal(btn.rect().bottomLeft()))

    def _use(self, item, c):
        if not can_use(item, c) or bag().get(item, 0) <= 0:
            return
        self.note = apply_item(item, c)
        consume(item)
        self._build()


# --------------------------------------------------------------- menu ----
class ExpeditionMenu(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent or mw)
        self.setWindowTitle("Expeditions")
        self.setMinimumWidth(560)
        v = QVBoxLayout(self)
        v.addWidget(QLabel(
            "<b>Expeditions</b> - three floors of defenders, then a legendary. "
            "Damage carries over between floors; camp between them to use items. "
            "The legendary has to be beaten in one go. Beat it = catch it.<br>"
            "<span style='color:gray'>Your team: %s</span>" % (
                ", ".join("%s Lv %d" % (c.name, c.level) for c in build_team()) or "none")))
        reg = here()
        local = [e for e in EXPEDITIONS if getattr(e, "region", EXPEDITION_REGION) == reg]
        if not local:
            v.addWidget(QLabel("<i>No expeditions in %s yet.</i>" % reg))
        for exp in local:
            box = QFrame()
            box.setFrameShape(QFrame.Shape.StyledPanel)
            row = QHBoxLayout(box)
            ok, label = status(exp)
            boss = exp.boss.foes[0]
            text = QLabel("<b>%s</b> - %s Lv %d<br><span style='color:gray'>%s</span><br><i>%s</i>"
                          % (exp.name, exp.legendary, boss.level, exp.blurb, label))
            text.setWordWrap(True)
            row.addWidget(text, 1)
            b = QPushButton("Set out")
            b.setEnabled(ok and not _busy())
            b.clicked.connect(lambda _c=False, e=exp: self._go(e))
            row.addWidget(b)
            v.addWidget(box)
        away = {}
        for e in EXPEDITIONS:
            r = getattr(e, "region", EXPEDITION_REGION)
            if r != reg:
                away.setdefault(r, []).append(e.name)
        if away:
            other = QLabel("<span style='color:gray'>Elsewhere: %s</span>" % "; ".join(
                "%s (%s)" % (r, ", ".join(n)) for r, n in away.items()))
            other.setWordWrap(True)
            v.addWidget(other)
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        v.addWidget(close, alignment=Qt.AlignmentFlag.AlignRight)

    def _go(self, exp):
        self.accept()
        start(exp)


def _busy() -> bool:
    if _run is not None:
        return True
    try:
        from . import gym_ui
        return gym_ui._window is not None and gym_ui._session is not None \
            and not gym_ui._session.finished
    except Exception:
        return False


def start(exp: Expedition) -> bool:
    global _run
    if _busy():
        QMessageBox.information(mw, "Expedition", "Finish the battle you're in first.")
        return False
    ok, label = status(exp)
    if not ok:
        QMessageBox.information(mw, "Expedition", label)
        return False
    run = ExpeditionRun(exp)
    _run = run
    try:
        if not run.start():
            _run = None
            return False
    except Exception as e:
        _run = None
        _log("error", "could not start %s: %s" % (exp.name, e))
        QMessageBox.warning(mw, "Expedition", "Could not start: %s" % e)
        return False
    return True


def open_menu():
    if _run is not None and _run.window is not None:
        _run.window.raise_()
        return
    ExpeditionMenu(mw).exec()


def _dn(n):
    """Real Pokémon name for display ("Iron Hands", "Mr. Mime")."""
    try:
        from ..functions.pokedex_functions import display_name
        return display_name(n)
    except Exception:
        s = str(n or "")
        return s[:1].upper() + s[1:]
