"""
rewards.py - themed gym loot.

Each leader has a loot pool in rematch_data.REMATCH[gym_id]["loot"]: TMs of
their type (stronger ones from later rematch versions), TMs of notable moves
their later versions use, the type's power item, its evolution stone, and
healing items that improve with the version. A draw picks a category by
LOOT_WEIGHT (TM / item / stone / heal), then an entry in it. TMs you already
own are skipped (a TM is never used up).
"""
import random

from .rematch_data import REMATCH, LOOT_WEIGHT


def _owned_names():
    try:
        from aqt import mw
        return {str(i.get("item_name") or "").lower() for i in (mw.ankimon_db.get_all_items() or [])}
    except Exception:
        return set()


def available(gym_id, version=0, owned=None):
    """Loot entries this leader can drop at this version."""
    owned = _owned_names() if owned is None else owned
    out = []
    for e in (REMATCH.get(int(gym_id)) or {}).get("loot", []):
        if e["min_version"] > version:
            continue
        if e["kind"] == "tm" and e["item"].lower() in owned:
            continue
        out.append(e)
    return out


def label(entry):
    if entry["kind"] == "tm":
        try:
            from ..move_names import format_move_name
            return "TM " + format_move_name(entry["item"])
        except Exception:
            return "TM " + entry["item"].replace("-", " ").title()
    try:
        from ..utils import item_display_name
        return item_display_name(entry["item"])
    except Exception:
        return entry["item"].replace("-", " ").title()


def chances(gym_id, version=0, owned=None):
    """[(label, % per draw)] for the rematch screen, most likely first."""
    pool = available(gym_id, version, owned)
    cats = {}
    for e in pool:
        cats.setdefault(e["kind"], []).append(e)
    total = sum(LOOT_WEIGHT.get(k, 0) for k in cats)
    out = []
    for k, es in cats.items():
        for e in es:
            out.append((label(e), 100.0 * LOOT_WEIGHT.get(k, 0) / max(1, total) / len(es)))
    return sorted(out, key=lambda x: -x[1])


def draw(gym_id, version=0, draws=2, rng=random):
    """Give `draws` items from this leader's pool; returns their labels
    ([] if the leader has no pool - the caller then uses the normal pool)."""
    if int(gym_id) not in REMATCH:
        return []
    from ..utils import give_item
    owned = _owned_names()
    got = []
    for _ in range(max(0, int(draws))):
        pool = available(gym_id, version, owned)
        if not pool:
            break
        cats = {}
        for e in pool:
            cats.setdefault(e["kind"], []).append(e)
        kinds = list(cats)
        kind = rng.choices(kinds, weights=[LOOT_WEIGHT.get(k, 1) for k in kinds], k=1)[0]
        e = rng.choice(cats[kind])
        try:
            give_item(e["item"], "TM" if e["kind"] == "tm" else None)
        except TypeError:
            give_item(e["item"])
        if e["kind"] == "tm":
            owned.add(e["item"].lower())          # no duplicate TM in one haul
        got.append(label(e))
    return got
