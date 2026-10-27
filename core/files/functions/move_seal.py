"""
move_seal.py - sealed moves in capped fights (user 2026-10-26).

A Pokemon fighting below its real level (the region's wild cap, or a boss's level
in gyms, legendaries and expeditions) can't use moves it couldn't have at the
level it's fighting at:
  * a level-up move: from the level the species learns it (newest generation);
  * anything else - TM, tutor, egg, start or evolution moves: by tier
    (data_files/move_tiers.json, regions_build/make_move_tiers.py): tier 0
    always, tier 1 from Lv 30, tier 2 from Lv 45.
Nothing changes for good: the moves come back as soon as it fights at a high
enough level (badges in a new region raise the cap; the Champion lifts it). A
Pokemon with every move sealed fights with its best level-up moves for that level.
"""
import json
import os
import re

TIER_LEVEL = {0: 1, 1: 30, 2: 45}
_TIERS = None


def _id(m) -> str:
    return re.sub(r"[^a-z0-9]", "", str(m or "").lower())


def _tiers() -> dict:
    global _TIERS
    if _TIERS is None:
        try:
            p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data_files", "move_tiers.json")
            with open(p, encoding="utf-8") as f:
                _TIERS = json.load(f)
        except Exception:
            _TIERS = {}
    return _TIERS


def _learnset(species) -> dict:
    try:
        from .learnset_retrieval import _load_learnset_cache
        return (_load_learnset_cache() or {}).get(_id(species), {}).get("learnset", {}) or {}
    except Exception:
        return {}


def _levelup(codes):
    """Learn level from the newest generation's level-up code ("9L48" -> 48), or None."""
    best = None
    for c in codes or []:
        m = re.match(r"^(\d)L(\d+)$", str(c))
        if m:
            g, lv = int(m.group(1)), int(m.group(2))
            if best is None or g > best[0]:
                best = (g, lv)
    return best[1] if best else None


def required_level(species, move) -> int:
    """The lowest fight level at which this Pokemon may use the move."""
    lv = _levelup(_learnset(species).get(_id(move)))
    if lv and lv > 1:
        return lv
    return TIER_LEVEL.get(int(_tiers().get(_id(move), 1)), 30)


def seal(species, moves, fight_level, real_level):
    """(usable moves, {sealed move: level it unlocks}) for a fight at fight_level."""
    if int(fight_level) >= int(real_level):
        return list(moves), {}
    usable, sealed = [], {}
    for m in moves:
        need = required_level(species, m)
        if int(fight_level) >= need:
            usable.append(m)
        else:
            sealed[m] = need
    return usable, sealed


def fallback(species, level, n=4):
    """Its best level-up moves at this level (the last ones it would have learned),
    with at least one attack if it has any."""
    ls = _learnset(species)
    known = sorted(((lv, m) for m, codes in ls.items() for lv in [_levelup(codes)] if lv and lv <= int(level)
                    and required_level(species, m) <= int(level)),        # start moves follow the tiers too
                   key=lambda x: (x[0], x[1]))
    picks = [m for _lv, m in known][-n:]
    try:
        from .pokedex_functions import find_details_move
        attack = lambda m: str((find_details_move(m) or {}).get("category") or "Status") != "Status"
    except Exception:
        attack = lambda m: True
    if picks and not any(attack(m) for m in picks):
        hits = [m for _lv, m in known if attack(m)]
        if hits:
            picks = picks[1:] + [hits[-1]]
    return picks or ["tackle"]


# ------------------------------------------------------------ scaled moves --
# A second moveset for capped fights (user 2026-10-26): kept per region on the
# Pokemon's record (rec["scaled_moves"][region]) and built in the Pokemon panel
# from moves usable at the region's wild cap. The max-level moveset ("attacks")
# is never touched. A region's list fills itself the first time, and again when a
# move in it is above the cap (back in a lower-capped region): its usable
# max-level moves, topped up with its best level-up moves for that level.
def auto_scaled(species, max_moves, cap, real, n=4):
    usable, _sealed = seal(species, list(max_moves), cap, real)
    out = [_id(m) for m in usable][:n]
    for m in fallback(species, cap):
        if len(out) >= n:
            break
        if _id(m) not in out:
            out.append(_id(m))
    return out or ["tackle"]


def scaled_moves(rec, region, cap):
    """(moves, changed): the record's scaled moveset for `region` at `cap`."""
    name, real = rec.get("name", ""), int(rec.get("level") or 1)
    saved = list(((rec.get("scaled_moves") or {}).get(region)) or [])
    if saved and all(required_level(name, m) <= int(cap) for m in saved):
        return saved, False
    return auto_scaled(name, rec.get("attacks") or [], int(cap), real), True


def scaled_candidates(species, max_moves, cap):
    """Moves it may put in its scaled moveset at this cap: its level-up moves up to
    the cap and the moves it knows (TM ones too) - each one usable at the cap."""
    ls = _learnset(species)
    lv_moves = sorted((lv, m) for m, codes in ls.items() for lv in [_levelup(codes)] if lv and lv <= int(cap))
    out = []
    for m in [m for _lv, m in lv_moves] + [_id(x) for x in max_moves]:
        if m not in out and required_level(species, m) <= int(cap):
            out.append(m)
    return out
