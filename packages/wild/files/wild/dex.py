"""
dex.py - the "registered" Pokedex, per-region progress and region badges.

REGISTERED, NOT JUST OWNED
    Ankimon's Pokedex used to count only species you own right now, so
    evolving Charmander un-caught Charmander. A species is now registered the
    first time you own it and stays registered: the table dex_registered is
    filled from your collection (and released history) whenever an encounter
    ends, the Pokedex opens, or Anki starts.

REGION COMPLETION
    A region is complete when every species of its generation is registered,
    EXCEPT mythicals (Mew, Celebi, Jirachi...) - like Red/Blue's diploma, which
    counted 150. Completing one earns that region's Pokedex badge (ids 68-76).
    The Pokedex page shows 100% at that point... mostly.
"""
REGION_NAMES = ["Kanto", "Johto", "Hoenn", "Sinnoh", "Unova", "Kalos", "Alola", "Galar", "Paldea"]
REGION_RANGES = {1: (1, 151), 2: (152, 251), 3: (252, 386), 4: (387, 493), 5: (494, 649),
                 6: (650, 721), 7: (722, 809), 8: (810, 905), 9: (906, 1025)}
BADGE_BASE = 68              # Kanto = 68 ... Paldea = 76
_DDL = ("CREATE TABLE IF NOT EXISTS dex_registered ("
        "species_id INTEGER PRIMARY KEY, first_at TEXT)")
_ready = [False]
_cache = {"reg": None, "myth": None}


def _db():
    from aqt import mw
    db = mw.ankimon_db
    if not _ready[0]:
        db.execute(_DDL)
        _commit(db)
        _ready[0] = True
    return db


def _commit(db):
    try:
        db._get_connection().commit()
    except Exception:
        pass


def mythicals():
    """Species ids tagged Mythical in the pokedex data (Mew, Celebi, ...)."""
    if _cache["myth"] is None:
        out = set()
        try:
            from ..functions.pokedex_functions import _load_pokedex_cache
            for d in (_load_pokedex_cache() or {}).values():
                sid = d.get("species_id")
                if isinstance(sid, int) and sid <= 1025 and "Mythical" in (d.get("tags") or []):
                    out.add(sid)
        except Exception:
            pass
        _cache["myth"] = out
    return _cache["myth"]


def _owned_ids(db):
    ids = set()
    try:
        ids |= {int(i) for i in db.get_all_pokemon_ids() if i}
    except Exception:
        try:
            ids |= {int(p.get("id")) for p in db.get_all_pokemon() or [] if p and p.get("id")}
        except Exception:
            pass
    try:
        ids |= {int(p.get("id")) for p in db.get_history() or [] if p and p.get("id")}
    except Exception:
        pass
    return {i for i in ids if 1 <= i <= 1025}


def sync():
    """Register everything you own (or released). Returns the registered set."""
    from datetime import datetime
    db = _db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for sid in _owned_ids(db):
        db.execute("INSERT OR IGNORE INTO dex_registered (species_id, first_at) VALUES (?, ?)",
                   (sid, now))
    _commit(db)
    _cache["reg"] = {int(r[0]) for r in db.execute("SELECT species_id FROM dex_registered").fetchall()}
    return _cache["reg"]


def registered():
    if _cache["reg"] is None:
        try:
            return sync()
        except Exception:
            return set()
    return _cache["reg"]


def gen_of(dex):
    for g, (lo, hi) in REGION_RANGES.items():
        if lo <= int(dex) <= hi:
            return g
    return None


def region_progress(gen, reg=None):
    """{'have','need','myth_have','myth_total','complete','perfect'} for a gen."""
    reg = registered() if reg is None else reg
    lo, hi = REGION_RANGES[gen]
    myth = mythicals()
    core = [i for i in range(lo, hi + 1) if i not in myth]
    mys = [i for i in range(lo, hi + 1) if i in myth]
    have = sum(1 for i in core if i in reg)
    mhave = sum(1 for i in mys if i in reg)
    return {"have": have, "need": len(core), "myth_have": mhave, "myth_total": len(mys),
            "complete": have >= len(core), "perfect": have >= len(core) and mhave >= len(mys)}


def region_count(gen, reg=None):
    """Registered species of a region, mythicals included (for unlock checks)."""
    reg = registered() if reg is None else reg
    lo, hi = REGION_RANGES[gen]
    return sum(1 for i in reg if lo <= i <= hi)


def check_region_badges(announce=True):
    """Award any region badge whose region is now complete. Returns the
    names of newly earned badges."""
    earned = []
    try:
        from ..singletons import achievements
        from ..functions.badges_functions import check_for_badge, receive_badge
    except Exception:
        return earned
    reg = registered()
    for gen in REGION_RANGES:
        bid = BADGE_BASE + gen - 1
        if check_for_badge(achievements, bid):
            continue
        if region_progress(gen, reg)["complete"]:
            receive_badge(bid, achievements)
            earned.append(REGION_NAMES[gen - 1])
    if earned and announce:
        try:
            from aqt.utils import showInfo
            showInfo("Pokedex complete: %s!\n\nYou earned the %s." % (
                ", ".join(earned), " and ".join("%s Pokedex Badge" % r for r in earned)),
                title="Ankimon")
        except Exception:
            pass
    return earned


def sync_and_award():
    try:
        sync()
        check_region_badges()
    except Exception as e:
        print("Ankimon dex sync failed:", e)
