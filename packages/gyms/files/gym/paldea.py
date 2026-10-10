"""
paldea.py - Paldea's open world: "Where to next?"

  * Paldea's 8 gyms can be done in any order, and so can its 5 Titans (optional,
    no badge). On first arriving in Paldea - and after every Paldea gym or Titan
    you beat - a popup asks where to set off for next; the choice is remembered
    (gym_meta "route:Paldea").
  * Levels follow the ORDER: your 1st gym is the lowest tier, your 8th the
    highest, whichever leader it is (Gym.tiers, built by regions_build). Titans
    have their own 5 tiers.
  * After the 8th badge the popup offers the Pokemon League (Elite Four, Geeta,
    Nemona, in order) and any Titans you haven't done.
  * Close the popup without choosing and the first gym you haven't beaten is
    the default; Game > Expeditions (in Paldea) reopens it.
  * The ruinous stakes for the Treasures of Ruin shrines (see below).
"""
import dataclasses
import json

from .gym_data import ladder, get_gym, GYM, TITAN, OPEN_WORLD

REGION = "Paldea"
META = "route:Paldea"


# ------------------------------------------------------------- route state --
def _progress():
    from .gym_ui import progress
    return progress()


def _route() -> dict:
    try:
        return json.loads(_progress().get_meta(META) or "{}") or {}
    except Exception:
        return {}


def choose(gym_id) -> None:
    """Set where you're heading next (a gym, a Titan or the League's first boss)."""
    _progress().set_meta(META, json.dumps({"target": int(gym_id) if gym_id else None}))


def _defeated() -> set:
    try:
        return set(_progress().defeated_ids())
    except Exception:
        return set()


# ------------------------------------------------------------------ tiers --
def tier_of(g, defeated, lad=None) -> int:
    """Which tier this boss would be now: gyms by badges earned, Titans by
    Titans beaten (1-based, capped at the number of tiers)."""
    lad = lad if lad is not None else ladder(REGION)
    kind = TITAN if g.kind == TITAN else GYM
    done = sum(1 for x in lad if x.kind == kind and x.gym_id in defeated)
    return max(1, min(len(g.tiers or {}) or 1, done + 1))


def scaled(g, tier):
    """This gym / Titan with its team for that tier (unchanged if it has none)."""
    team = (g.tiers or {}).get(tier) or (g.tiers or {}).get(str(tier))
    if not team:
        return g
    return dataclasses.replace(g, team=list(team), recommended_level=max(m.level for m in team))


# ------------------------------------------------------------- next boss --
def next_boss(defeated, region=REGION):
    """gym_data.next_gym for Paldea: the chosen destination (at its tier), else
    the first gym not yet beaten, then the League in order."""
    lad = ladder(region)
    defeated = set(defeated or ())
    target = _route().get("target")
    if target:
        g = get_gym(int(target))
        if g is not None and g in lad and g.gym_id not in defeated:
            return scaled(g, tier_of(g, defeated)) if g.kind in (GYM, TITAN) else g
    gyms_left = [g for g in lad if g.kind == GYM and g.gym_id not in defeated]
    if gyms_left:
        return scaled(gyms_left[0], tier_of(gyms_left[0], defeated))
    league = [g for g in lad if g.kind not in (GYM, TITAN) and g.gym_id not in defeated]
    return league[0] if league else None


def options(defeated, lad=None):
    """[(gym at its tier, label)] for the popup: gyms left, Titans left, and the
    League once every badge is earned. lad: a demo ladder (Game > Test)."""
    lad = lad if lad is not None else ladder(REGION)
    defeated = set(defeated or ())
    out = []
    gyms_left = [g for g in lad if g.kind == GYM and g.gym_id not in defeated]
    for g in gyms_left:
        s = scaled(g, tier_of(g, defeated, lad))
        out.append((s, _label(g)))
    if not gyms_left:
        league = [g for g in lad if g.kind not in (GYM, TITAN) and g.gym_id not in defeated]
        if league:
            out.append((league[0], "Pokémon League"))
    for g in (x for x in lad if x.kind == TITAN and x.gym_id not in defeated):
        s = scaled(g, tier_of(g, defeated, lad))
        out.append((s, _label(g)))
    return out


def _label(g) -> str:
    """'Larry - Medali Gym (Normal)', 'Titan Klawf - Stony Cliff Titan (Rock)'."""
    return "%s - %s (%s)" % (g.leader, g.name, g.type_theme)


# ------------------------------------------------------------------ popup --
def ask(parent=None, demo=False, on_pick=None, defeated=None, lad=None) -> bool:
    """The "Where to next?" popup. demo=True (Game > Test): nothing is saved,
    on_pick(gym) gets the choice, lad = the demo ladder. Returns True if picked."""
    from aqt import mw
    from aqt.qt import QDialog, QVBoxLayout, QLabel, QPushButton
    if not demo and REGION not in OPEN_WORLD:
        return False                    # Paldea's open world isn't installed
    defeated = set(defeated if defeated is not None else ([] if demo else _defeated()))
    opts = options(defeated, lad)
    if not opts:
        return False
    dlg = QDialog(parent or mw)
    dlg.setWindowTitle("Where to next?")
    v = QVBoxLayout(dlg)
    gyms_done = sum(1 for g in (lad if lad is not None else ladder(REGION)) if g.kind == GYM and g.gym_id in defeated)
    head = ("Paldea is wide open. Where do you want to set off for first?" if not gyms_done
            else "%d badge%s down. Where to next?" % (gyms_done, "" if gyms_done == 1 else "s"))
    lab = QLabel("<b>%s</b>" % head)
    lab.setWordWrap(True)
    v.addWidget(lab)
    picked = {}
    for g, label in opts:
        b = QPushButton(label)
        b.setStyleSheet("text-align:left; padding:5px 10px;")
        b.clicked.connect(lambda _c=False, gg=g: (picked.update(g=gg), dlg.accept()))
        v.addWidget(b)
    later = QPushButton("Decide later")
    later.clicked.connect(dlg.reject)
    v.addWidget(later)
    dlg.exec()
    g = picked.get("g")
    if g is None:
        return False
    if demo:
        if on_pick:
            on_pick(g)
    else:
        choose(g.gym_id)
        try:
            from aqt.utils import tooltip
            tooltip("Next: %s" % g.leader)
        except Exception:
            pass
    return True


def on_enter():
    """Travelled to Paldea: ask, unless a destination is already set."""
    if REGION not in OPEN_WORLD:
        return
    d = _defeated()
    t = _route().get("target")
    if t and int(t) not in d:
        return
    ask()


def after_win(gym):
    """A Paldea gym or Titan was beaten: clear the destination and ask again."""
    if getattr(gym, "region", "") != REGION or getattr(gym, "kind", "") not in (GYM, TITAN):
        return
    if getattr(gym, "is_test", False) or getattr(gym, "is_rematch", False) or REGION not in OPEN_WORLD:
        return
    choose(None)
    ask()


# ------------------------------------------------------ the ruinous stakes --
# Four stakes of each colour open the Treasures of Ruin shrines (Expeditions):
# purple Wo-Chien, yellow Chien-Pao, green Ting-Lu, blue Chi-Yu. They turn up
# while you review in Paldea, paced so finding all 16 takes a little longer
# than the region itself: STRETCH x your own pace (cards per story boss so far,
# at least the review cadence), never more than one ahead of that pace, and
# the last two only after the Champion. Each find is a random colour you haven't finished,
# so you never get a fifth of one colour. A popup only if item pickup popups
# are on (Settings: battle.popup_item_pickup).
STAKES = ("purple-stake", "yellow-stake", "green-stake", "blue-stake")
PER_COLOUR = 4
TOTAL = PER_COLOUR * len(STAKES)
STRETCH = 1.15
CATCH_UP_MAX = 0.25


def stake_chance(found, reviews, beaten, n_bosses, per_gym, last_win_at=0) -> float:
    """This card's chance of a stake (pure, for tests). last_win_at: the Paldea
    card count at your latest story-boss win."""
    if found >= TOTAL or n_bosses <= 0:
        return 0.0
    if found >= TOTAL * (beaten + 1) // (n_bosses + 1):
        return 0.0                              # no further ahead than your progress
    pace = max(per_gym, last_win_at / float(beaten)) if beaten else per_gym     # cards per boss
    length = STRETCH * n_bosses * max(1, pace)
    base = TOTAL / float(length)
    due = TOTAL * reviews / float(length)
    if found >= due + 1:
        return 0.0                              # never more than one ahead of the pace
    behind = due - found
    return base if behind < 1 else min(CATCH_UP_MAX, base * 3 * behind)


def _stake_counts() -> dict:
    out = {s: 0 for s in STAKES}
    try:
        from aqt import mw
        for it in mw.ankimon_db.get_all_items() or []:
            n = str(it.get("item_name") or "").lower()
            if n in out:
                out[n] = int(it.get("quantity") or 0)
    except Exception:
        pass
    return out


def stake_tick(rng=None):
    """Once per answered card (gym_ui.handle_review). The stake found, or None."""
    import random
    rng = rng or random
    if REGION not in OPEN_WORLD:
        return None
    try:
        from .gym_data import current_region
        if current_region() != REGION:
            return None
        from .gym_ui import region_reviews
        from . import gym_config as CFG
        counts = _stake_counts()
        found = sum(min(PER_COLOUR, c) for c in counts.values())
        story = [g for g in ladder(REGION) if g.kind != TITAN]
        d = _defeated()
        won = [g for g in story if g.gym_id in d]
        last = 0
        for g in won:
            r = _progress()._row(g.gym_id)
            last = max(last, int(r[3] or 0) if r else 0)
        if rng.random() >= stake_chance(found, region_reviews(REGION), len(won), len(story),
                                        CFG.reviews_per_gym(), last):
            return None
        open_ = [s for s in STAKES if counts[s] < PER_COLOUR]
        if not open_:
            return None
        pick = rng.choice(open_)
        from ..utils import give_item
        give_item(pick)
        _announce(pick, counts[pick] + 1)
        return pick
    except Exception as e:
        print("Ankimon stakes:", e)
        return None


def _announce(item, n):
    try:
        from ..singletons import settings_obj
        if str(settings_obj.get("battle.popup_item_pickup", True)).strip().lower() in ("false", "0", "no", "off"):
            return
        from aqt.utils import tooltip
        tooltip("You found a %s! (%d of %d)" % (item.replace("-", " ").title(), n, PER_COLOUR), period=4000)
    except Exception:
        pass

