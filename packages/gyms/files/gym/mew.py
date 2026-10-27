"""
mew.py — Mew, for a week of daily goals (user 2026-10-16; repeatable 2026-10-17).

Seven days in a row with at least your daily card goal (Settings: battle.daily_average)
and Kanto's first three gyms beaten (Brock, Misty, Lt. Surge): Mew joins you. Every
further seven days in a row, counted from the day after the last Mew, brings another.
This is the only way to get Mew (gym/legends.py keeps it out of the wild).
The region you're reviewing in doesn't matter. The streak is read from Anki's own
review log, so days before this was installed count too. It's checked on a day you
meet your goal, counting that day and the six before it.
"""
import time

MEW = 151
MEW_LEVEL = 30
NEEDS = (1, 2, 3)              # Kanto: Brock, Misty, Lt. Surge
STREAK = 7
JOINED = "mew_joined"           # set by the first gift
CHECKED = "mew_checked_day"     # the Anki day already checked after its goal was met
LAST = "mew_last_gift_day"      # day boundary (cutoff) of the day the last Mew came
GIFTS = "mew_gifts"
_DAY = 86400


def _progress():
    from .gym_ui import progress
    return progress()


def joined() -> bool:
    try:
        return bool(_progress().get_meta(JOINED))
    except Exception:
        return False


def _goal() -> int:
    try:
        from ..singletons import settings_obj
        return max(1, int(settings_obj.get("battle.daily_average") or 100))
    except Exception:
        return 100


def _cutoff() -> int:
    """Epoch seconds of the next Anki day boundary (respects the rollover hour)."""
    from aqt import mw
    try:
        return int(mw.col.sched.day_cutoff)
    except Exception:
        try:
            hour = int(mw.col.get_config("rollover", 4) or 4)
        except Exception:
            hour = 4
        lt = time.localtime()
        today = int(time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, hour, 0, 0, 0, 0, -1)))
        return today + _DAY if time.time() >= today else today


def _reviews(lo, hi) -> int:
    """Cards answered in [lo, hi) (epoch seconds): learning, review, relearning, filtered."""
    from aqt import mw
    return int(mw.col.db.scalar("SELECT count() FROM revlog WHERE id >= ? AND id < ? AND type IN (0, 1, 2, 3)",
                                lo * 1000, hi * 1000) or 0)


def streak(goal=None, cutoff=None, since=0) -> int:
    """Days in a row at or above the goal, ending today (once met) or yesterday;
    only days that start at or after `since` (the end of the last Mew's day) count."""
    goal = goal or _goal()
    hi = cutoff or _cutoff()
    n = 0
    for i in range(STREAK + 1):
        if hi - (i + 1) * _DAY < since:
            break
        got = _reviews(hi - (i + 1) * _DAY, hi - i * _DAY)
        if got >= goal:
            n += 1
        elif i == 0:
            continue                # today isn't done yet: count back from yesterday
        else:
            break
    return n


def _gift():
    import random
    from .gym_data import GymMon
    from .gym_battle import build_leader_pokemon, _dn
    from . import legends
    from ..functions.pokemon_functions import shiny_chance, pick_random_gender
    from ..functions.encounter_functions import save_caught_pokemon
    from ..singletons import achievements
    p = build_leader_pokemon(GymMon("Mew", MEW_LEVEL, None))
    if p is None:
        return None
    p.iv = {k: random.randint(legends.IV_FLOOR, 31) for k in ("hp", "atk", "def", "spa", "spd", "spe")}
    mx = int(p.calculate_max_hp())
    p.max_hp = p.hp = p.current_hp = mx
    p.shiny = bool(shiny_chance(1))
    p.tier = "Mythical"
    try:
        p.gender = pick_random_gender("mew")
    except Exception:
        pass
    save_caught_pokemon(p, _dn(p.name), achievements)
    P = _progress()
    P.set_meta(JOINED, "1")
    P.set_meta(GIFTS, str(int(P.get_meta(GIFTS) or 0) + 1))
    return p


def on_review():
    """Once per answered card (gym_ui.handle_review). Cheap: one count of today's
    reviews until the goal is met, then the streak once per Anki day."""
    try:
        P = _progress()
        if P.get_meta(JOINED) and not P.get_meta(LAST):
            # the first Mew came before gifts repeated: its day is the day last checked
            P.set_meta(LAST, P.get_meta(CHECKED) or "0")
        if not set(NEEDS) <= set(P.defeated_ids()):
            return
        cutoff, goal = _cutoff(), _goal()
        if P.get_meta(CHECKED) == str(cutoff):
            return
        if _reviews(cutoff - _DAY, cutoff) < goal:
            return
        P.set_meta(CHECKED, str(cutoff))
        again = bool(P.get_meta(JOINED))
        if streak(goal, cutoff, int(P.get_meta(LAST) or 0)) < STREAK:
            return
        p = _gift()
        if p is None:
            return
        P.set_meta(LAST, str(cutoff))
        msg = ("%s week of meeting your daily goal - and something was watching.\n\n"
               "%s joined you!%s" % ("Another" if again else "A whole", "Another Mew" if again else "Mew",
                                      "  And it's SHINY!" if p.shiny else ""))
        from aqt import mw
        from aqt.utils import showInfo
        mw.progress.single_shot(300, lambda: showInfo(msg, title="Ankimon"))
    except Exception as e:
        print("Ankimon Mew gift:", e)
