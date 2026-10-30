"""
gym_ui.py — offers gyms, then hands off to the gym window.

Public surface battle_loop.py uses stays two functions:

    gym_is_active()        -> bool  ; True while a gym window is open
    handle_review(reviews) -> None  ; called once per answered card

WHAT CHANGED
    handle_review no longer advances gym turns. Reviewing only *offers* a gym
    once you cross the threshold. The battle itself is played in
    gym_window.GymBattleWindow — it is a break from reviewing.

WHY gym_is_active() STILL PAUSES WILD BATTLES
    Gym and wild state are fully isolated — the gym never writes to the shared
    main_pokemon / enemy_pokemon objects (see gym_window for how). Wild
    battles are still paused while a gym window is open, but only because
    fighting two battles at once is nonsense, not because state could leak.
"""

from typing import List, Optional

from aqt import mw
from aqt.qt import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QCheckBox,
    QListWidget, QListWidgetItem, Qt, QMessageBox,
)

from ..singletons import logger
from .gym_state import GymSession, GymProgress, TEAM_SIZE
from .gym_data import next_gym, ladder_complete, current_region, level_cap, gate_reviews, ELITE4
from . import gym_battle as GB
from . import gym_config as CFG

_session: Optional[GymSession] = None
_window = None
_DECLINE_KEY = "declined_at"     # persisted, so the HUD counter stays honest
_last_selection = None           # party records, for a Classic Elite Four chain


def _log(lvl, m):
    try:
        logger.log(lvl, "[gym] %s" % m)
    except Exception:
        print("[gym] %s" % m)


_progress: Optional[GymProgress] = None


def progress() -> GymProgress:
    global _progress
    if _progress is None:
        _progress = GymProgress(mw.ankimon_db)
        try:
            from .gym_data import ALOLA_MIGRATION
            _progress.migrate_ids(ALOLA_MIGRATION, "alola_usum")
        except Exception as e:
            _log("warning", "Alola progress migration failed: %s" % e)
    return _progress


def current_cap():
    """This region's level cap right now (None once its Champion is beaten)."""
    try:
        return level_cap(progress().defeated_ids())
    except Exception:
        return None


def is_legendary(rec) -> bool:
    """One legendary per team (counted across every region)."""
    try:
        if str((rec or {}).get("tier") or "") in ("Legendary", "Mythical"):
            return True
        from ..functions.pokedex_functions import search_pokedex
        tags = search_pokedex(str(rec.get("name", "")).lower(), "tags") or []
        return any(t in ("Sub-Legendary", "Restricted Legendary", "Mythical") for t in tags)
    except Exception:
        return False


def gym_is_active() -> bool:
    """True while a gym window (or an expedition) is open, so wild battles
    stay paused and no gym is offered mid-dungeon."""
    if _window is not None and _session is not None and not _session.finished:
        return True
    try:
        from . import expedition
        return expedition.is_active()
    except Exception:
        return False


# --- per-region review clocks ---------------------------------------------
# Each region counts the cards you review while you're there; its count
# pauses while you're elsewhere. Every gate - the next gym, a rematch, the
# "Not now" cooldown - is measured on the clock of the region you're in, so
# arriving somewhere new never unlocks its first gym on the spot, and going
# away and coming back picks up exactly where you left off.
_CLOCK_REGION = "clock_region"      # whose clock is running
_CLOCK_START = "clock_entered"      # lifetime count when it started running


def _meta_int(key, default=0) -> int:
    try:
        v = progress().get_meta(key)
        return int(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def _sync_clock() -> int:
    """Bank the running clock if you've travelled. Returns the lifetime count."""
    g = _current_reviews()
    P = progress()
    run = P.get_meta(_CLOCK_REGION)
    if run is None:
        # First run: everything so far happened on Kanto's clock, so Kanto
        # progress keeps its meaning. Attempts in other regions were logged on
        # the old shared count; they restart at zero on their region's clock.
        P.set_meta("clock:Kanto", 0)
        P.set_meta(_CLOCK_START, 0)
        P.set_meta(_CLOCK_REGION, "Kanto")
        P.db.execute("UPDATE gym_progress SET last_attempt_rev=0 WHERE gym_id>=100")
        P._commit()
        run = "Kanto"
    cur = current_region()
    if run != cur:
        banked = _meta_int("clock:" + run) + max(0, g - _meta_int(_CLOCK_START, g))
        P.set_meta("clock:" + run, banked)
        P.set_meta(_CLOCK_START, g)
        P.set_meta(_CLOCK_REGION, cur)
    return g


def region_reviews(region=None) -> int:
    """Cards reviewed while in this region (default: the one you're in)."""
    try:
        g = _sync_clock()
        reg = region or current_region()
        banked = _meta_int("clock:" + reg)
        if reg == current_region():
            return banked + max(0, g - _meta_int(_CLOCK_START, g))
        return banked
    except Exception as e:
        _log("warning", "region clock failed, using the lifetime count: %s" % e)
        return _current_reviews()


# --- decline cooldown, persisted per region ---------------------------------
# Kept in gym_meta rather than a module global: a memory-only marker vanished
# on restart, so the HUD counter could disagree with when the gym would
# actually be offered again.
def _decline_key() -> str:
    return "%s:%s" % (_DECLINE_KEY, current_region())


def _declined_at() -> int:
    try:
        v = progress().get_meta(_decline_key())
        return int(v) if v is not None else -1
    except Exception:
        return -1


def _set_declined_at(value: int):
    try:
        progress().set_meta(_decline_key(), int(value))
    except Exception:
        pass


def _decline_target() -> int:
    """Review count at which a declined gym becomes offerable again.
    Returns -1 when no decline is outstanding."""
    d = _declined_at()
    return -1 if d < 0 else d + max(1, CFG.decline_cooldown())


# ------------------------------------------------------------ team select --
class _SortItem(QListWidgetItem):
    """List row that sorts by .order: original position, or name A-Z while
    a search is typed. order_orig is set once at creation."""
    order = (0,)
    order_orig = (0,)

    def __lt__(self, other):
        return self.order < getattr(other, "order", (0,))


def _held_label(rec) -> str:
    """'   - holding Normalium Z ✦' for the team list ('' when it holds nothing).
    ✦ = a Z-Crystal it can use right now (it knows a move of that type)."""
    item = (rec or {}).get("held_item")
    if not item:
        return ""
    try:
        from ..utils import item_display_name
        label = item_display_name(item)
    except Exception:
        label = str(item).replace("-", " ").title()
    try:
        from . import zmoves
        if zmoves.crystal_type(item) and zmoves.can_use_crystal(rec, item):
            label += " ✦"
    except Exception:
        pass
    return "   - holding %s" % label


def recommended_types(gym, limit=3) -> List[str]:
    """Attack types that hit the boss's team super-effectively, best first: ones
    that hit its ace (highest level) lead, then how much of the team they hit,
    then how well that type stands up to the team's own types."""
    try:
        from ..functions.pokedex_functions import search_pokedex
        from .move_card import _chart, multiplier
        chart = _chart()
        team = []
        for m in gym.team:
            types = search_pokedex(str(m.species).lower(), "types") or []
            if isinstance(types, str):
                types = [types]
            team.append((int(m.level), [str(t).capitalize() for t in types if t]))
        if not chart or not team:
            return []
        ace = max(range(len(team)), key=lambda i: (team[i][0], i))
        theirs = {t for _, ts in team for t in ts}
        ranked = []
        for atk in sorted(chart):
            hits = [multiplier("", atk, ts, chart) for _, ts in team]
            if max(hits) <= 1:
                continue
            taken = sum(multiplier("", t, [atk], chart) for t in theirs)
            ranked.append(((hits[ace] > 1, sum(h > 1 for h in hits), sum(hits), -taken), atk))
        ranked.sort(key=lambda r: r[0], reverse=True)
        return [atk for _, atk in ranked[:limit]]
    except Exception:
        return []


def brief_lines(gym) -> List[str]:
    """Who, their team, the types to bring - the challenge dialog's header and
    the HUD counter's hover card, so you can plan while reviewing."""
    lines = ["<b>%s</b> — %s specialist" % (gym.leader, gym.type_theme),
             "<b>Their team:</b> " + ", ".join(
                 "%s Lv%d" % (m.species, m.level) for m in gym.team)]
    rec = recommended_types(gym)
    if rec:
        lines.append("<b>Recommended:</b> " + ", ".join(rec))
    return lines


def progress_tip() -> str:
    """brief_lines for whoever the HUD counter is counting toward, as one
    HTML block ("" when the counter isn't about a gym)."""
    try:
        if not CFG.enabled() or gym_is_active():
            return ""
        gym = next_gym(progress().defeated_ids())
        return "<br>".join(brief_lines(gym)) if gym is not None else ""
    except Exception:
        return ""


class TeamSelectDialog(QDialog):
    """Pick exactly 3 from the player's 6-slot party."""

    def __init__(self, gym, party: List[dict], parent=None):
        super().__init__(parent)
        self.setWindowTitle("%s — %s" % (gym.name, gym.leader))
        self.selected: List[dict] = []
        lay = QVBoxLayout(self)

        for line in brief_lines(gym):
            lab = QLabel(line)
            lab.setWordWrap(True)
            lay.addWidget(lab)
        # The level YOUR team should be at (what the difficulty is tuned for);
        # the boss's own team level can differ by a few levels. Only the
        # "Selected" line's average uses these now.
        self.rec_level = (getattr(gym, "recommended_level", 0)
                          or max(m.level for m in gym.team))
        # boss fights: anything above the opponent's level fights at it (never raised)
        self.cap = GB.boss_level(gym) or current_cap()

        lay.addWidget(QLabel("Choose <b>%d</b> Pokemon:" % TEAM_SIZE))
        from ..functions import poke_search as PS
        self.search = PS.make_search_edit()
        lay.addWidget(self.search)
        self.list = QListWidget()
        self.list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        for n, rec in enumerate(party):
            tl = PS.type_label(rec.get("type"))
            it = _SortItem("%s   Lv %s%s%s" % (
                _dn(rec.get("name", "?")) + _unown_suffix(rec), rec.get("level", "?"),
                ("   " + tl) if tl else "", _held_label(rec)))
            it.setData(Qt.ItemDataRole.UserRole, rec)
            it.order = it.order_orig = (n,)
            self.list.addItem(it)
        lay.addWidget(self.list)
        self.search.textChanged.connect(self._filter)

        self.gym = gym
        pick = QPushButton("Choose team for me")
        pick.setToolTip("Picks three from your whole PC, with their best moves for this fight "
                        "(this fight only), and starts the battle.")
        pick.clicked.connect(self._autopick)
        lay.addWidget(pick)
        self.use_tms = QCheckBox("Use my TMs for better moves?")
        self.use_tms.setToolTip("Lets Choose team for me give a Pokémon a move from a TM you own, "
                                "for this fight. TMs aren't used up.")
        lay.addWidget(self.use_tms)

        self.auto = QCheckBox("Auto-battle (moves chosen for me)")
        self.auto.setChecked(CFG.auto_battle())
        lay.addWidget(self.auto)
        hint = QLabel("Unticked, you pick each move with the 1-4 keys or by "
                      "clicking. You can switch modes mid-battle.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#9aa4b2;")
        lay.addWidget(hint)

        self.count = QLabel("")
        lay.addWidget(self.count)
        self.list.itemSelectionChanged.connect(self._update)

        row = QHBoxLayout()
        self.ok = QPushButton("Challenge")
        self.ok.setEnabled(False)
        self.ok.clicked.connect(self._accept)
        cancel = QPushButton("Not now")
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        row.addWidget(self.ok)
        lay.addLayout(row)
        self._update()

    def _filter(self, text):
        """Name / nickname / type search. Picked Pokemon never get hidden."""
        from ..functions import poke_search as PS
        query = PS.tokens(text)
        for i in range(self.list.count()):
            it = self.list.item(i)
            rec = it.data(Qt.ItemDataRole.UserRole) or {}
            ok = PS.matches(text, rec.get("name"), rec.get("nickname"), rec.get("type"))
            it.setHidden(not ok and not it.isSelected())
            it.order = ((str(rec.get("name", "")).lower(), -int(rec.get("level") or 0))
                        if query else it.order_orig)
        self.list.sortItems()

    def _update(self):
        recs = [i.data(Qt.ItemDataRole.UserRole) for i in self.list.selectedItems()]
        n = len(recs)
        names = [str(r.get("name", "")).lower() for r in recs]
        dup = len(set(names)) < len(names)
        text = "Selected %d of %d" % (n, TEAM_SIZE)
        if recs:
            try:
                avg = sum(min(int(r.get("level", 0)), self.cap or 999) for r in recs) / float(n)
                gap = avg - self.rec_level
                text += "  -  average Lv %.0f (%s)" % (
                    avg, "at level" if abs(gap) < 1 else
                    "%d under" % round(-gap) if gap < 0 else "%d over" % round(gap))
            except Exception:
                pass
        if dup:
            text += "  -  pick three different species"
        legends = sum(1 for r in recs if is_legendary(r))
        if legends > 1:
            text += "  -  only one legendary per team"
        self.count.setText(text)
        self.ok.setEnabled(n == TEAM_SIZE and not dup and legends <= 1)

    def _accept(self):
        self.selected = [i.data(Qt.ItemDataRole.UserRole)
                         for i in self.list.selectedItems()]
        self.accept()

    def _autopick(self):
        """Choose team for me (autopick.py): three from the whole PC with moves
        for this fight only, then the fight starts."""
        from . import autopick
        try:
            picked = autopick.choose(self.gym, self.cap, self.use_tms.isChecked(), parent=self)
        except Exception as e:
            _log("error", "Choose team for me failed: %s" % e)
            picked = None
        if not picked:
            QMessageBox.information(self, "Choose team for me",
                                    "Couldn't pick a team for this fight. Choose three yourself.")
            return
        from aqt.utils import tooltip
        tooltip("Picked %s" % ", ".join(_dn(r.get("name", "?")) for r in picked), period=4000)
        self.selected = picked
        self.accept()

    @property
    def auto_battle(self) -> bool:
        return self.auto.isChecked()


# ---------------------------------------------------------------- offering --
def _finish(session: GymSession):
    """Called by the window when the fight ends. Discarding the damaged copies
    IS the heal, so there is nothing to restore."""
    global _session, _window
    chain_next = None
    try:
        notes = GB.finish_session(session, progress(), region_reviews())
        won = session.status == GymSession.WON
        body = [session.summary(), ""] + notes
        # Classic Elite Four: a win rolls straight into the next member with
        # the same three, healed, and no review interval in between.
        if won and session.gym.is_elite and CFG.elite_four_classic() and not getattr(session.gym, "is_rematch", False):
            nxt = next_gym(progress().defeated_ids())
            if nxt is not None and nxt.is_elite:
                chain_next = nxt
                body.append("")
                body.append("%s steps up next. Your team is healed, but you "
                            "keep the same three." % nxt.leader)

        if (won and not getattr(session.gym, "is_rematch", False) and not getattr(session.gym, "is_legend", False)
                and not getattr(session.gym, "is_test", False) and ladder_complete(progress().defeated_ids())):
            body.append("")
            if _full_ladder():
                body.append("That is the whole %s ladder — every gym, the Elite Four "
                            "and the Champion. Your level cap here is lifted." % current_region())
            else:
                body.append("That's every %s gym built so far. Travel on, or come "
                            "back when more open up." % current_region())
        # rich text so Z items show in gold (gym_battle.zspan / notes_html)
        box = QMessageBox(mw)
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle("You defeated %s!" % session.gym.leader if won
                           else "You lost to %s" % session.gym.leader)
        box.setTextFormat(Qt.TextFormat.RichText)
        box.setText(GB.notes_html(body))
        box.exec()
        if won and (getattr(session.gym, "totem", None) or getattr(session.gym, "titan", None)):
            from . import totem as _totem
            _totem.offer_catch(session.gym)     # Alola totem / Paldea Titan: its species may join you
        if won:
            try:                                # Paldea: "Where to next?" after a gym or Titan
                from . import paldea as _pal
                _pal.after_win(session.gym)
            except Exception as e:
                _log("warning", "Paldea route: %s" % e)
    except Exception as e:
        _log("error", "finishing gym failed: %s" % e)
    finally:
        # Must clear no matter what. If this threw partway, gym_is_active()
        # would stay True forever: no further gym offers, and wild battles
        # frozen because battle_loop returns early while a gym is "open".
        _close_engine(getattr(session, "engine", None))   # stops the Showdown helper
        _session, _window = None, None

    # Chain AFTER the globals are cleared, or gym_is_active() would still be
    # True and the next fight could not open.
    if chain_next is not None:
        try:
            start_gym(chain_next, reuse_selection=True)
        except Exception as e:
            _log("error", "elite chain failed: %s" % e)


def _full_ladder() -> bool:
    """This region has its whole ladder (Elite Four and Champion), like Kanto."""
    try:
        from .gym_data import ladder, CHAMPION
        return any(g.kind == CHAMPION for g in ladder())
    except Exception:
        return current_region() == "Kanto"


def _prestart_showdown(offer: bool = True):
    """Spawn the Showdown helper if it's enabled and installed; None otherwise
    (the fight then uses the classic engine). With the showdown package but
    no engine yet, offer the one-time download (showdown_setup)."""
    try:
        if not CFG.showdown_engine():
            return None
        from . import gym_showdown as GS
        if not GS.available():
            if offer:
                try:
                    from . import showdown_setup
                    showdown_setup.offer()
                except ImportError:
                    pass                # showdown package not installed
            _log("info", "Showdown runtime not installed - using the classic gym engine")
            return None
        return GS.ShowdownBattle()
    except Exception as e:
        _log("warning", "Showdown helper failed to start, using classic: %s" % e)
        return None


def _close_engine(engine):
    try:
        if engine is not None and hasattr(engine, "close"):
            engine.close()
    except Exception:
        pass


def start_gym(gym, reuse_selection: bool = False) -> bool:
    """Open team select, then the battle window. Returns True if a fight began."""
    global _session, _window, _last_selection

    party = GB.available_party()
    if len(party) < TEAM_SIZE:
        _log("info", "party has %d, need %d — gym skipped" % (len(party), TEAM_SIZE))
        return False

    # Start the Showdown helper now, so it loads while you pick your team.
    sd = _prestart_showdown()

    # A Classic Elite Four chain keeps the same three, healed, with no
    # re-pick and no interval between members.
    if reuse_selection and _last_selection:
        selection, auto = _last_selection, CFG.auto_battle()
    else:
        dlg = TeamSelectDialog(gym, party, parent=mw)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            if not (getattr(gym, "is_rematch", False) or getattr(gym, "is_legend", False)
                    or getattr(gym, "is_test", False)):
                _set_declined_at(region_reviews())
            _close_engine(sd)
            return False
        selection, auto = dlg.selected, dlg.auto_battle
        _last_selection = selection
    if sd is None:
        # the engine may have finished downloading while you picked your team
        sd = _prestart_showdown(offer=False)

    from . import tera as _tr
    if _tr.config_for(gym)["p2"] and getattr(gym, "tera", ""):
        # Paldea: the ace's Tera type is rolled for every fight (mostly counters)
        import copy as _copy
        gym = _copy.copy(gym)
        gym.tera_rolled = _tr.roll_ace_type(gym.tera)
    player = GB.build_player_team(selection, GB.boss_level(gym))     # fight at the boss's level
    if getattr(gym, "test_mech", "") in ("tera", "titan"):
        # Game > Test Tera: anyone holding nothing gets a Tera Shard of a random
        # type for this battle only
        import random as _rnd
        for c in player:
            if c.source is not None and not getattr(c.source, "held_item", None):
                c.source.held_item = _tr.shard_item(_rnd.choice(_tr.TYPES))
    if getattr(gym, "test_mech", "") == "z":
        # Game > Test Z-Moves: anyone holding nothing gets a Z-Crystal for one of
        # its moves, for this battle only (the copies are thrown away after)
        from . import zmoves as _zm
        for c in player:
            if c.source is not None and not getattr(c.source, "held_item", None):
                c.source.held_item = _zm.crystal_for(c.attacks) or None
    leader = GB.build_leader_team(gym)
    if getattr(gym, "is_legend", False):      # roaming legendary / mythical (legends.py)
        from . import legends as _lg
        _lg.prepare(leader, gym)
    if not player or not leader:
        _close_engine(sd)
        QMessageBox.warning(mw, "Gym",
                            "Could not build one of the teams. See the Ankimon log.")
        return False

    if getattr(gym, "is_rematch", False):
        from . import rematch as _rm
        _rm.consume()               # a rematch was started: its cooldown begins again
    elif not (getattr(gym, "is_legend", False) or getattr(gym, "is_test", False)):
        _set_declined_at(-1)        # accepted: any "Not now" cooldown is moot
    _session = GymSession(gym, player, leader)
    if sd is not None:
        try:
            from . import dmax as _dm, tera as _tr
            sd.start(player, leader, gym.leader, totem=getattr(gym, "totem", None),
                     dynamax=_dm.config_for(gym), tera=_tr.config_for(gym),
                     titan=getattr(gym, "titan", None), guard=GB.guard_for(gym), hp_mult=GB.HP_MULT,
                     aiswitch=GB.ai_switch_for(gym))
            _session.engine = sd            # real-game rules for this fight
        except Exception as e:
            _log("warning", "Showdown engine could not start this fight, using classic: %s" % e)
            _close_engine(sd)
    # One line per fight in app.log, so it's verifiable which engine ran.
    _log("info", "%s vs %s: engine = %s, movesets = %s" % (
        gym.name, gym.leader,
        "Showdown (real rules)" if _session.engine is not None else "classic",
        "Original" if CFG.original_movesets() else "Modernized"))
    from .gym_window import GymBattleWindow
    _window = GymBattleWindow(_session, auto, _finish, parent=mw)
    _window.show()
    _window.raise_()
    _window.activateWindow()
    return True


def progress_text() -> str:
    """One line for the reviewer HUD, e.g.

        37 / 100 until Stonewall Gym (Brock)
        82 / 100 until rematch vs Brock

    Denominator is read live from settings, so changing the interval updates
    the line on the next card without a restart. Counts up to the threshold.
    Returns "" when there is nothing useful to say (disabled, mid-battle).
    """
    try:
        if not CFG.enabled() or gym_is_active():
            return ""
        gym = next_gym(progress().defeated_ids())
        if gym is None:
            r = current_region()
            return ("All %s gyms defeated" % r if _full_ladder()
                    else "%s: every gym so far beaten - more coming" % r)

        reviews = region_reviews()
        row = progress()._row(gym.gym_id)
        attempts = row[2] if row else 0

        # Three gates can hold a gym back. Whichever sits furthest out is the
        # one actually binding, so that is what the counter should show —
        # otherwise the line sits pinned at "N / N" while nothing happens.
        gates = []
        # The Elite Four (Galar: the Champion Cup) go by their title, not
        # whichever member is next; "retry", not "rematch" (that's the Gym
        # Rematches feature for leaders you've beaten).
        if gym.kind == ELITE4:
            who = "the Champion Cup" if current_region() == "Galar" else "the Elite Four"
            full = who
        else:
            who, full = gym.leader, "%s (%s)" % (gym.name, gym.leader)
        if attempts > 0:
            gates.append((row[3] + max(1, CFG.retry_cost()),
                          max(1, CFG.retry_cost()),
                          "until you can retry %s" % who))
        else:
            gates.append((progress().unlock_point(gym, CFG.reviews_per_gym()),
                          max(1, gate_reviews(gym, CFG.reviews_per_gym())),
                          "until %s" % full))

        dt = _decline_target()
        if dt >= 0:
            gates.append((dt, max(1, CFG.decline_cooldown()),
                          "until %s is offered again" % who))

        target, denom, label = max(gates, key=lambda g: g[0])
        if reviews >= target:
            # every gate met: a full "300 / 300" read as stuck
            name = who[:1].upper() + who[1:]
            return "%s %s ready %s - next card" % (
                name, "are" if gym.kind == ELITE4 else "is",
                "for another try" if attempts > 0 else "to battle")
        have = denom - max(0, target - reviews)
        return "%d / %d %s" % (max(0, min(denom, have)), denom, label)
    except Exception:
        return ""          # the HUD must never break because of the gym


def progress_html() -> str:
    """The counter as a ready-to-append HUD div, or "" if there is nothing
    to show. Building the markup here keeps the reviewer_iframe patch to a
    few plain lines with no nested quoting."""
    line = progress_text()
    if not line:
        return ""
    return ('<div id="AnkimonGymProgress" style="text-align:center;'
            'font-size:12px;opacity:0.85;padding:2px 0 5px 0;">'
            + line + '</div>')


_menu_added = False


def _ankimon_menu(title_key):
    """An Ankimon submenu found by its title (Debug sits under Other; no import of
    menu_buttons), or None."""
    pm = getattr(mw, "pokemenu", None)
    if pm is None:
        return None
    try:
        title = mw.translator.translate(title_key).replace("&", "")
    except Exception:
        return None
    stack = [pm]
    while stack:
        for a in stack.pop().actions():
            m = a.menu()
            if m is not None:
                if a.text().replace("&", "") == title:
                    return m
                stack.append(m)
    return None


def ensure_menu():
    """Add a Tools entry so a rematch is reachable on demand.

    Self-installing from here rather than patching menu_buttons.py — one less
    core file touched. Without this there was no way to rechallenge a gym or
    even see *why* it was blocked, which is what made rematch look broken.
    """
    global _menu_added
    if _menu_added:
        return
    try:
        from aqt.qt import QAction
        act = QAction("Challenge Gym", mw)                  # Ankimon > Other > Debug (user 2026-10-28)
        act.setMenuRole(QAction.MenuRole.NoRole)
        act.triggered.connect(open_gym_manually)
        (_ankimon_menu("ankimon_debug_button_title") or _ankimon_menu("ankimon_game_button_title")
         or mw.form.menuTools).addAction(act)
        _menu_added = True
    except Exception as e:
        _menu_added = True          # never retry-spam on a broken menu API
        _log("warning", "could not add gym menu entry: %s" % e)


def handle_review(review_count: int = 0):
    """Called once per answered card. Only OFFERS a gym — never fights one.

    review_count from battle_loop is ignored: it is the daily figure. We use
    the lifetime count instead (see _current_reviews).
    """
    try:
        ensure_menu()
        _bump_reviews()
        try:
            from . import rematch as _rm
            _rm.on_review()             # small "rematch ready" notice
        except Exception:
            pass
        try:
            from . import legends as _lg
            _lg.maybe_offer()           # a roaming legendary / mythical crossed your path
        except Exception:
            pass
        try:
            from . import paldea as _pd
            _pd.stake_tick()            # Paldea: a ruinous stake, now and then
        except Exception:
            pass
        try:
            from . import mew as _mew
            _mew.on_review()            # Mew: a week of daily goals + Kanto's first 3 gyms
        except Exception:
            pass
        if gym_is_active():
            return                      # window open; nothing to do here
        if not CFG.enabled():
            return
        gym = next_gym(progress().defeated_ids())
        if gym is None:
            return
        reviews = region_reviews()
        ok, _reason = progress().can_challenge(gym, reviews)
        if not ok:
            return
        # If they said "not now", wait a full cadence before asking again
        # rather than popping the dialog on every single card.
        dt = _decline_target()
        if dt >= 0 and reviews < dt:
            return                      # still inside the "Not now" cooldown
        if dt >= 0:
            _set_declined_at(-1)        # cooldown served; clear it
        start_gym(gym)
    except Exception as e:
        _log("error", "handle_review failed: %s" % e)


def open_gym_manually():
    """Menu action: challenge the next gym now, if it is unlocked."""
    if gym_is_active():
        _window.raise_()
        return
    gym = next_gym(progress().defeated_ids())
    if gym is None:
        QMessageBox.information(mw, "Gyms", "You have beaten every gym in %s%s." % (
            current_region(), "" if _full_ladder() else " built so far"))
        return
    reviews = region_reviews()
    ok, reason = progress().can_challenge(gym, reviews)
    if not ok:
        # Show the arithmetic, not just "no". A silent gate is why the retry
        # felt broken rather than merely locked.
        det = ["Next up: %s (%s)" % (gym.name, gym.leader),
               "Reviews in %s: %d" % (current_region(), reviews),
               "Unlocks at: %d" % progress().unlock_point(
                   gym, CFG.reviews_per_gym())]
        a = progress().attempts(gym.gym_id)
        if a:
            row = progress()._row(gym.gym_id)
            det.append("Attempts so far: %d (last at review %d)" % (a, row[3]))
            det.append("Retry costs: %d reviews" % CFG.retry_cost())
        QMessageBox.information(mw, "Gyms", reason + "\n\n" + "\n".join(det))
        return
    start_gym(gym)


_life_cache: Optional[int] = None


def _current_reviews() -> int:
    """Lifetime reviews, counted from Anki's revlog.

    NOT ankimon_tracker.get_total_reviews() — that scrapes "Studied N cards"
    from studied_today(), so it is a DAILY figure that resets at midnight and
    is empty on a fresh session. Every gym gate keyed to it therefore moved
    backwards each night and could never be crossed reliably; that is what
    made rematch look broken even with the retry cost set to 1.

    revlog only ever grows, so thresholds stay meaningful across days.
    """
    global _life_cache
    if _life_cache is not None:
        return max(0, _life_cache - _baseline())
    try:
        _life_cache = int(mw.col.db.scalar("select count() from revlog") or 0)
    except Exception as e:
        _log("warning", "revlog count failed, falling back to daily: %s" % e)
        try:
            from ..singletons import ankimon_tracker_obj
            _life_cache = int(ankimon_tracker_obj.get_total_reviews())
        except Exception:
            _life_cache = 0
    return max(0, _life_cache - _baseline())


def _baseline() -> int:
    """Reviews already logged when the ladder started. Recorded once."""
    try:
        raw = _life_cache if _life_cache is not None else 0
        return progress().baseline(raw)
    except Exception:
        return 0


def _bump_reviews():
    """handle_review fires once per answered card, so a counted increment
    stays exact without re-running COUNT() on every single card."""
    global _life_cache
    if _life_cache is None:
        _current_reviews()
    else:
        _life_cache += 1


def _dn(n):
    """Real Pokémon name for display ("Iron Hands", "Mr. Mime")."""
    try:
        from ..functions.pokedex_functions import display_name
        return display_name(n)
    except Exception:
        s = str(n or "")
        return s[:1].upper() + s[1:]


def _unown_suffix(p):
    """" B" after an Unown's name (functions/unown.py); "" for anything else."""
    try:
        from ..functions.unown import suffix
        return suffix(p)
    except Exception:
        return ""


# Phone reviews (user 2026-10-26): cards done in AnkiMobile / AnkiDroid reach the
# review log with a sync. The lifetime count is cached per session, so count the
# log again after every sync - they then count toward the next gym, rematches and
# the region clock (battles, XP and training points stay desktop-only).
def _on_sync_finished(*_args):
    global _life_cache
    _life_cache = None


try:
    from aqt import gui_hooks as _gh
    _gh.sync_did_finish.append(_on_sync_finished)
except Exception as _e:
    _log("warning", "sync hook not added: %s" % _e)
