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


LEGEND_IV_FLOOR = 21        # same floor as wild_rules.LEGEND_IV_FLOOR (was 25; user 2026-10-15: too easy to perfect)

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


def _progress():
    from .gym_ui import progress
    return progress()


def done(exp: Expedition) -> bool:
    """Finished for good: its legendary caught, or (a release expedition) cleared.
    2.0 saves: Burned Tower used to catch Entei, so owning Entei counts."""
    if getattr(exp, "repeatable", False):
        return False
    if getattr(exp, "releases", ()):
        try:
            if _progress().get_meta("exp_done_" + exp.key):
                return True
        except Exception:
            pass
        try:
            from ..wild import dex
            return any(i in dex.registered() for i in exp.releases)
        except Exception:
            return False
    return caught(exp)


def partner(exp: Expedition) -> Optional[Expedition]:
    """The other half of a pair expedition (Zacian / Zamazenta), if any."""
    k = getattr(exp, "excludes", "")
    return next((e for e in EXPEDITIONS if e.key == k), None) if k else None


def unlocked(place) -> bool:
    """A place opened by finishing an expedition (Area Zero). Until then it
    isn't offered anywhere at all."""
    try:
        if _progress().get_meta("unlock_" + place):
            return True
    except Exception:
        pass
    return any(done(e) for e in EXPEDITIONS if getattr(e, "unlocks", "") == place)


def held(item) -> int:
    """How many of an item are in your bag (key items too)."""
    try:
        for it in mw.ankimon_db.get_all_items() or []:
            if str(it.get("item_name") or "").lower() == item:
                return int(it.get("quantity") or 0)
    except Exception as e:
        _log("warning", "could not read the bag: %s" % e)
    return 0


def owned_ids() -> set:
    """Dex numbers of the Pokemon you own right now (team + PC)."""
    try:
        return {int(i) for i in (mw.ankimon_db.get_all_pokemon_ids() or set())}
    except Exception:
        return set()


def champion_beaten(region) -> bool:
    try:
        from .gym_data import champion_beaten as _cb
        return bool(_cb(_progress().defeated_ids(), region))
    except Exception:
        return False


def _names(ids, joiner=" and "):
    out = []
    for i in ids:
        try:
            from ..functions.pokedex_functions import search_pokedex_by_id
            out.append(_dn(search_pokedex_by_id(int(i))))
        except Exception:
            out.append("#%d" % int(i))
    return joiner.join(out)


def status(exp: Expedition):
    """(can_start, label)"""
    if done(exp):
        if getattr(exp, "releases", ()):
            return False, "Done - %s roam the wild" % _names(exp.releases)
        return False, "%s caught" % exp.legendary
    reg = getattr(exp, "region", EXPEDITION_REGION)
    other = partner(exp)
    if other is not None and done(other):
        return False, "You chose %s - %s may be roaming %s's wild" % (other.legendary, exp.legendary, reg)
    b = badges(reg)
    if b < exp.badges_needed:
        return False, "Locked - needs %d %s badges (you have %d)" % (
            exp.badges_needed, reg, b)
    first = getattr(exp, "needs_done", "")
    if first:
        other = next((e for e in EXPEDITIONS if e.key == first), None)
        if other is not None and not done(other):
            return False, "Locked - clear %s first" % other.name
    if getattr(exp, "needs_champion", False) and not champion_beaten(reg):
        return False, "Locked - beat %s's Champion first" % reg
    short = [(n, q) for n, q in getattr(exp, "needs_items", ()) if held(n) < q]
    if short:
        return False, "Locked - needs %s" % ", ".join(
            "%d %ss (you have %d)" % (q, _label(n), held(n)) for n, q in short)
    own = owned_ids()
    missing = [i for i in getattr(exp, "needs_owned", ()) if int(i) not in own]
    if missing:
        return False, "Locked - needs you to own %s" % _names(missing)
    anyof = getattr(exp, "needs_any", ())
    if anyof and not any(int(i) in own for i in anyof):
        return False, "Locked - needs you to own %s" % _names(anyof, " or ")
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


def build_team(records=None, cap=None) -> List[Combatant]:
    """The three you picked (or, without a pick, your team). cap: the expedition's
    strongest foe - anything above it fights at it (gym_battle.boss_level)."""
    out = []
    for rec in (records if records is not None else _team_records()):
        p = GB._obj_from_saved(copy.deepcopy(rec), cap)
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
            # Legendaries: every IV from 25 (~80%) to 31 - strong, never a forced 31
            p.iv = {k: random.randint(LEGEND_IV_FLOOR, 31) for k in ("hp", "atk", "def", "spa", "spd", "spe")}
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
    def __init__(self, exp: Expedition, records=None, auto=None):
        self.exp = exp
        self.team = build_team(records, max((int(m.level) for f in exp.floors for m in f.foes), default=None))
        self.auto = CFG.auto_battle() if auto is None else bool(auto)
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
                              team=floor.foes, kind="expedition", is_elite=False,
                              guard=(GB.BOSS_GUARD if floor.boss else None),   # the legendary: hidden guard
                              region=getattr(self.exp, "region", EXPEDITION_REGION))
        session = GymSession(gym, alive, foes)
        if self.sd is not None:
            try:
                from . import dmax as _dm, tera as _tr
                self.sd.start(alive, foes, leader, wild=True, dynamax=_dm.config_for(gym),
                              tera=_tr.config_for(gym), guard=GB.guard_for(gym), hp_mult=GB.HP_MULT)
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
        self.window = GymBattleWindow(session, self.auto, self._floor_done, parent=mw)
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
        if getattr(self.exp, "releases", ()) and self.floor_i >= len(self.exp.floors) - 1:
            self._release()
            self._end("released")
            return
        if getattr(self.exp, "evolves", ()) and self.floor_i >= len(self.exp.floors) - 1:
            self._evolve()
            self._end("evolved")
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
            if getattr(self.exp, "unlocks", ""):
                _progress().set_meta("unlock_" + self.exp.unlocks, "1")
        except Exception as e:
            _log("error", "saving the legendary failed: %s" % e)
            QMessageBox.warning(mw, "Expedition", "You won, but saving %s failed: %s"
                                % (self.exp.legendary, e))

    def _release(self):
        """A release expedition is cleared: its legendaries start roaming."""
        try:
            _progress().set_meta("exp_done_" + self.exp.key, "1")
            from . import legends
            legends.release(self.exp.releases)
        except Exception as e:
            _log("error", "releasing %s failed: %s" % (self.exp.legendary, e))

    def _evolve(self):
        """The towers: evolve one of your Kubfu (you pick which)."""
        frm, to, to_name = self.exp.evolves
        self.evolved = None
        mons = [r for r in _all_records() if int(r.get("id") or 0) == int(frm)]
        if not mons:
            return
        pick = mons[0]
        if len(mons) > 1:
            from aqt.qt import QInputDialog
            labels = ["%s  Lv %d%s" % (r.get("nickname") or r.get("name"), int(r.get("level") or 1),
                                       "  (shiny)" if r.get("shiny") else "") for r in mons]
            choice, ok = QInputDialog.getItem(mw, self.exp.name, "Which %s evolves into %s?"
                                              % (_names((frm,)), to_name), labels, 0, False)
            if ok and choice in labels:
                pick = mons[labels.index(choice)]
        try:
            self.evolved = (pick.get("nickname") or pick.get("name"), evolve_record(pick, to, to_name))
        except Exception as e:
            _log("error", "evolving %s failed: %s" % (pick.get("name"), e))
            QMessageBox.warning(mw, "Expedition", "You cleared it, but the evolution failed: %s" % e)

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
        elif result == "released":
            title = "%s awoke!" % self.exp.legendary
            lines.insert(0, "%s burst out of %s and now roam %s's wild. Something powerful "
                            "may cross your path while you review." % (
                                _names(self.exp.releases), self.exp.name, self.exp.region))
        elif result == "evolved":
            ev = getattr(self, "evolved", None)
            title = ("%s evolved!" % ev[0]) if ev else "You cleared %s" % self.exp.name
            lines.insert(0, ("%s took in the tower's teachings and evolved into %s!" % ev) if ev else
                         "You reached the top, but you have no %s to train here." % _names(self.exp.evolves[:1]))
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
            "<b>Expeditions</b> - pick three of your team for three floors of defenders, then a "
            "legendary. Damage carries over between floors; camp between them to use items. "
            "The legendary has to be beaten in one go. Beat it = catch it.<br>%s" % _gate_line()))
        reg = here()
        local = [e for e in EXPEDITIONS if getattr(e, "region", EXPEDITION_REGION) == reg]
        if not local:
            v.addWidget(QLabel("<i>No expeditions in %s yet.</i>" % reg))
        for exp in local:
            box = QFrame()
            box.setFrameShape(QFrame.Shape.StyledPanel)
            row = QHBoxLayout(box)
            ok, label = status(exp)
            if exp.boss is not None:
                head = "%s Lv %d" % (exp.legendary, exp.boss.foes[0].level)
            elif getattr(exp, "evolves", ()):
                head = "%s evolves into %s" % (_names(exp.evolves[:1]), exp.legendary)
            else:
                head = "%s (they flee when woken)" % exp.legendary
            text = QLabel("<b>%s</b> - %s<br><span style='color:gray'>%s</span><br><i>%s</i>"
                          % (exp.name, head, exp.blurb, label))
            text.setWordWrap(True)
            row.addWidget(text, 1)
            b = QPushButton("Set out")
            b.setEnabled(ok and not _busy() and _gate_ready())
            b.clicked.connect(lambda _c=False, e=exp: self._go(e))
            row.addWidget(b)
            v.addWidget(box)
        try:
            from . import legends
            note = legends.menu_note(reg)
        except Exception:
            note = ""
        if note:
            hint = QLabel(note)
            hint.setWordWrap(True)
            v.addWidget(hint)
        from .gym_data import OPEN_WORLD
        if reg in OPEN_WORLD:               # open world: change where you're heading
            wb = QPushButton("Where to next...")
            wb.clicked.connect(self._where_next)
            v.addWidget(wb)
        rb = QPushButton("Gym Rematches...")
        try:
            from . import rematch
            have, need = rematch.counter()
            rb.setText("Gym Rematches...  (%s)" % ("ready!" if have >= need else "%d / %d cards" % (have, need)))
        except Exception:
            pass
        rb.clicked.connect(self._rematches)
        v.addWidget(rb)
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        v.addWidget(close, alignment=Qt.AlignmentFlag.AlignRight)

    def _where_next(self):
        self.accept()
        try:
            from . import paldea
            paldea.ask()
        except Exception as e:
            _log("error", "Where to next failed: %s" % e)

    def _rematches(self):
        self.accept()
        try:
            from . import rematch
            rematch.open_menu()
        except Exception as e:
            QMessageBox.warning(mw, "Gym Rematches", "Could not open rematches: %s" % e)

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
    if not _gate_ready():
        have, need = _gate()
        QMessageBox.information(mw, "Expedition", "Your next challenge (a rematch or an expedition) "
                                "is %d cards away." % max(0, need - have))
        return False
    # pick three, like a gym: the legendary is tuned for three type-matched Pokemon
    from . import gym_ui
    party = GB.available_party()
    if len(party) < 3:
        QMessageBox.information(mw, "Expedition", "You need at least three Pokémon in your team.")
        return False
    boss = exp.boss
    dlg = gym_ui.TeamSelectDialog(SimpleNamespace(
        name=exp.name, leader=exp.legendary, type_theme=_boss_type(exp), blurb=exp.blurb,
        team=list(boss.foes) if boss is not None else list(exp.floors[-1].foes),
        recommended_level=(boss.foes[0].level if boss is not None else 0)), party, parent=mw)
    if dlg.exec() != QDialog.DialogCode.Accepted:
        return False
    try:
        from . import rematch
        rematch.consume()                  # the shared challenge is used, win or lose
    except Exception as e:
        _log("warning", "could not use the challenge: %s" % e)
    run = ExpeditionRun(exp, dlg.selected, dlg.auto_battle)
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


def _gate():
    """(cards so far, cards needed) for the shared rematch / expedition challenge."""
    try:
        from . import rematch
        return rematch.counter()
    except Exception:
        return 1, 1


def _gate_ready() -> bool:
    have, need = _gate()
    return have >= need


def _gate_line() -> str:
    have, need = _gate()
    if have >= need:
        return "<b>A challenge is ready</b> - an expedition or a gym rematch."
    return ("<span style='color:gray'>%d / %d cards until your next challenge (an expedition or "
            "a gym rematch).</span>" % (have, need))


def _boss_type(exp) -> str:
    try:
        from ..functions.pokedex_functions import search_pokedex
        boss = exp.boss
        name = boss.foes[0].species if boss is not None else exp.legendary
        return "/".join(search_pokedex(str(name).lower(), "types") or []) or "?"
    except Exception:
        return "?"


def open_menu():
    if _run is not None and _run.window is not None:
        _run.window.raise_()
        return
    ExpeditionMenu(mw).exec()


def _all_records() -> List[dict]:
    try:
        return list(mw.ankimon_db.get_all_pokemon() or [])
    except Exception as e:
        _log("warning", "could not read your Pokemon: %s" % e)
        return []


# Moves a tower teaches on evolving (Sw/Sh: learned on evolution)
SIGNATURE = {892: "Wicked Blow", 10191: "Surging Strikes"}


def evolve_record(rec, to_id, to_name) -> str:
    """Evolve a saved Pokemon into to_name (a form's id, like Urshifu-Rapid-Strike
    10191, works too - Ankimon's own evolution looks up growth by that id and fails).
    Keeps level, IVs/EVs, nature, shiny, held item; new species data, CP and HP."""
    from ..functions.pokedex_functions import search_pokedex, get_growth_rate, get_base_experience
    from ..functions.battle_functions import calculate_hp
    from ..business import calculate_cp_from_dict
    key = str(to_name).lower()
    rec = dict(mw.ankimon_db.get_pokemon(rec["individual_id"]) or rec)
    old = str(rec.get("name") or "")
    shown = _dn(to_name)
    if rec.get("nickname") and str(rec["nickname"]).strip().lower() == old.lower():
        rec["nickname"] = shown          # never renamed: follow the species
    rec["name"] = shown
    rec["id"] = int(to_id)
    rec["type"] = search_pokedex(key, "types")
    base = search_pokedex(key, "baseStats")
    rec["base_stats"] = base
    rec["stats"] = base
    sid = int(search_pokedex(key, "species_id") or to_id)
    try:
        rec["growth_rate"] = get_growth_rate(sid)
    except Exception:
        pass
    try:
        rec["base_experience"] = get_base_experience(int(search_pokedex(key, "actual_id") or to_id))
    except Exception:
        pass
    ab = search_pokedex(key, "abilities") or {}
    nums = [v for k, v in ab.items() if str(k).isdigit()] if isinstance(ab, dict) else []
    if nums:
        rec["ability"] = random.choice(nums)
    sig = SIGNATURE.get(int(to_id))
    atk = list(rec.get("attacks") or [])
    if sig and sig.lower() not in [str(a).lower() for a in atk]:
        if len(atk) < 4:
            atk.append(sig)
        else:
            try:
                from ..pyobj.attack_dialog import AttackDialog
                dlg = AttackDialog(atk, sig)
                if dlg.exec() == QDialog.DialogCode.Accepted and dlg.selected_attack in atk:
                    atk[atk.index(dlg.selected_attack)] = sig
            except Exception as e:
                _log("warning", "move prompt failed: %s" % e)
    rec["attacks"] = atk
    rec["xp"] = 0
    rec["current_hp"] = int(calculate_hp(int(base["hp"]), rec["level"], rec["ev"], rec["iv"]))
    rec["cp"] = calculate_cp_from_dict(rec)
    rec["evolution_rejected"] = False
    mw.ankimon_db.save_pokemon(rec)
    ExpeditionRun._sync_live(rec.get("individual_id"))
    return shown


def _dn(n):
    """Real Pokémon name for display ("Iron Hands", "Mr. Mime")."""
    try:
        from ..functions.pokedex_functions import display_name
        return display_name(n)
    except Exception:
        s = str(n or "")
        return s[:1].upper() + s[1:]
