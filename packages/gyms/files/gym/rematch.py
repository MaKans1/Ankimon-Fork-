"""
rematch.py - rematch gym leaders you've beaten.

  * Ankimon > Game > Expeditions > Gym Rematches: the leaders you've beaten in
    the region you're in. Pick one to see their team (scaled to you) and what
    they can drop.
  * They come back stronger: level = your top three's average + HARDER (your
    level cap applies), never below the original fight. The team is the
    leader's rematch version for that level (rematch_data: evolved Pokemon,
    newer moves - up to 6 versions per leader).
  * One challenge per gym interval (Settings > Gyms > Reviews Between Gym
    Challenges), shared with expeditions: a rematch OR an expedition. Cards
    count in every region; it doesn't stack. Starting either uses it, win or
    lose.
  * Rewards: cash scaled to the level, EXP (scales with their levels), and
    2-4 drops from the leader's themed loot (more and better at higher
    versions). Badges and gym progress are never touched.
  * A small "rematch ready" notice (Settings > Battle > Wild Battle Popups).
  * Needs the wild package too (the Expeditions menu comes with it).
"""
import dataclasses
import os

from aqt import mw
from aqt.qt import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QListWidget,
                    QListWidgetItem, QPushButton, Qt)

from . import gym_config as CFG
from .gym_data import GymMon, ladder, full_ladder, current_region
from .rematch_data import REMATCH
from . import rewards

HARDER = 3              # rematch level = your top three's average + this
MAX_DRAWS = 4
_META_LAST = "rematch_last"          # lifetime review count when a rematch was last used
_META_NOTIFIED = "rematch_notified"  # which cooldown the "ready" notice was shown for


def _ui():
    from . import gym_ui
    return gym_ui


def _lifetime():
    return _ui()._current_reviews()


def _last():
    P = _ui().progress()
    v = P.get_meta(_META_LAST)
    if v is None:                       # the cooldown starts when rematches arrive
        now = _lifetime()
        P.set_meta(_META_LAST, now)
        return now
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def counter():
    """(cards so far, cards needed) toward the next rematch - every region counts."""
    need = max(1, CFG.reviews_per_gym())
    return min(need, max(0, _lifetime() - _last())), need


def ready():
    have, need = counter()
    return have >= need


def consume():
    """A rematch was started: the cooldown begins again."""
    _ui().progress().set_meta(_META_LAST, _lifetime())


def _popup_on():
    try:
        from ..singletons import settings_obj
        v = settings_obj.get("battle.popup_rematch", True)
        return str(v).strip().lower() not in ("false", "0", "no", "off")
    except Exception:
        return True


def has_menu():
    """The Expeditions menu (and so Gym Rematches) comes with the wild package."""
    return os.path.exists(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                       "wild", "wild_menus.py"))


def on_review():
    """Once per answered card: a small notice the moment a rematch is ready."""
    try:
        if not CFG.enabled() or not ready() or not has_menu():
            return
        P = _ui().progress()
        stamp = str(_last())
        if P.get_meta(_META_NOTIFIED) == stamp:
            return
        P.set_meta(_META_NOTIFIED, stamp)
        if _popup_on() and P.defeated_ids():
            from aqt.utils import tooltip
            tooltip("A challenge is ready - a gym rematch or an expedition (Ankimon > Game > Expeditions).",
                    period=4000)
    except Exception:
        pass


def beaten_here():
    """Leaders you can rematch here: those you've beaten, plus the other
    version's leader in a Galar slot you've cleared (Bea / Allister...)."""
    ids = _ui().progress().defeated_ids()
    return [g for g in full_ladder(current_region())
            if int(g.gym_id) in REMATCH and (g.gym_id in ids or (getattr(g, "pair", 0) and g.pair in ids))]


def _my_levels():
    """Your three highest team levels, at your current level cap."""
    from . import gym_battle as GB
    cap = _ui().current_cap()
    out = []
    for rec in GB.available_party():
        try:
            lv = int(rec.get("level") or 1)
        except (TypeError, ValueError):
            lv = 1
        out.append(min(lv, cap) if cap else lv)
    return sorted(out, reverse=True)[:3]


def rematch_level(gym_id):
    floor = REMATCH[int(gym_id)]["versions"][0]["min_level"]
    top = _my_levels()
    mine = round(sum(top) / len(top)) if top else floor
    return max(floor, min(100, mine + HARDER))


def version_for(gym_id, level):
    vi = 0
    for i, v in enumerate(REMATCH[int(gym_id)]["versions"]):
        if level >= v["min_level"]:
            vi = i
    return vi


def build(gym):
    """The rematch version of a beaten gym, scaled to your team."""
    data = REMATCH[int(gym.gym_id)]
    L = rematch_level(gym.gym_id)
    vi = version_for(gym.gym_id, L)
    team = [GymMon(sp, max(1, L - off), list(ms) or None) for sp, off, ms in data["versions"][vi]["team"]]
    orig = data["versions"][0]["min_level"]
    g = dataclasses.replace(gym, team=team, name="Rematch: %s" % gym.name,
                            cash_reward=int(gym.cash_reward * L / max(1, orig)),
                            recommended_level=L)
    g.is_rematch = True
    g.rematch_version = vi
    g.rematch_level = L
    g.loot_draws = min(MAX_DRAWS, 2 + vi // 2)
    return g


# ---------------------------------------------------------------- screen ----
class RematchDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent or mw)
        self.setWindowTitle("Gym Rematches")
        self.setMinimumSize(620, 420)
        v = QVBoxLayout(self)
        have, need = counter()
        status = ("<b>A challenge is ready</b> - a rematch or an expedition." if have >= need
                  else "%d / %d cards until your next challenge (a rematch or an expedition)." % (have, need))
        head = QLabel("<b>Gym rematches - %s</b><br>%s<br><span style='color:gray'>Leaders you've "
                      "beaten here come back stronger, scaled to your team, with their own loot. "
                      "One rematch or expedition per gym interval; cards count in every region.</span>"
                      % (current_region(), status))
        head.setWordWrap(True)
        v.addWidget(head)
        row = QHBoxLayout()
        self.list = QListWidget()
        self.gyms = beaten_here()
        for g in self.gyms:
            it = QListWidgetItem("%s - %s" % (g.leader, g.name))
            it.setData(Qt.ItemDataRole.UserRole, int(g.gym_id))
            self.list.addItem(it)
        self.detail = QLabel()
        self.detail.setWordWrap(True)
        self.detail.setAlignment(Qt.AlignmentFlag.AlignTop)
        row.addWidget(self.list, 1)
        row.addWidget(self.detail, 2)
        v.addLayout(row, 1)
        btns = QHBoxLayout()
        self.fight = QPushButton("Rematch")
        self.fight.clicked.connect(self._go)
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        btns.addStretch(1)
        btns.addWidget(self.fight)
        btns.addWidget(close)
        v.addLayout(btns)
        self.list.currentRowChanged.connect(self._show)
        if self.gyms:
            self.list.setCurrentRow(0)
        else:
            self.detail.setText("You haven't beaten any gym leaders in %s yet." % current_region())
        self._update_button()

    def _current(self):
        i = self.list.currentRow()
        return self.gyms[i] if 0 <= i < len(self.gyms) else None

    def _update_button(self):
        self.fight.setEnabled(bool(self._current()) and ready())
        if not ready():
            self.fight.setToolTip("Not ready yet - keep reviewing.")

    def _show(self, *_):
        g = self._current()
        if g is None:
            return
        rg = build(g)
        team = ", ".join("%s Lv %d" % (m.species, m.level) for m in rg.team)
        # what they might drop - no odds, no count (TMs you own are already left out)
        drops = dict.fromkeys(rewards.label(e) for e in rewards.available(g.gym_id, rg.rematch_version))
        loot = "".join("<li>%s</li>" % lbl for lbl in drops)
        self.detail.setText(
            "<b>%s</b> - %s specialist<br><b>Team:</b> %s<br>"
            "<b>Rewards:</b> $%d, EXP, and possible drops:<ul>%s</ul>"
            % (g.leader, g.type_theme, team, rg.cash_reward, loot or "<li>-</li>"))
        self._update_button()

    def _go(self):
        g = self._current()
        if g is None or not ready():
            return
        self.accept()
        _ui().start_gym(build(g))


def open_menu():
    RematchDialog(mw).exec()
