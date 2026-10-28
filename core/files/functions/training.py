"""
training.py - Ankimon 2.5: training points (user 2026-10-15; reviews 2026-10-22).

Your buddy earns a training point for every half of your daily card goal you
review (Settings: battle.daily_average), so meeting the goal earns 2 a day.
Spend a point with the "+" next to a stat in the Pokemon's details: +1 to that
stat's IV, up to 31.

Points used to come from friendship (one per 50) - far too fast. Each Pokemon
keeps what it had earned that way (training_legacy, frozen once, the first
review after this update); friendship no longer adds points, and it still drives
friendship evolutions and the no-trade evolution rule as before.
"""
POINTS_PER = 50            # the old friendship rate (frozen legacy points only)
IV_MAX = 31
STATS = ("hp", "atk", "def", "spa", "spd", "spe")
COUNT_KEY = "training_review_count"
MIGRATED_KEY = "training_legacy_frozen"
_migrated = None


def step() -> int:
    """Cards per training point: half the daily card goal."""
    try:
        from ..singletons import settings_obj
        return max(1, int(settings_obj.get("battle.daily_average") or 100) // 2)
    except Exception:
        return 50


def _int(v):
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def _is_migrated() -> bool:
    global _migrated
    if _migrated is None:
        try:
            from aqt import mw
            _migrated = bool(mw.ankimon_db.get_user_data(MIGRATED_KEY, False))
        except Exception:
            return False
    return bool(_migrated)


def available(rec) -> int:
    """Unspent training points of a saved Pokemon (dict)."""
    legacy = rec.get("training_legacy")
    if legacy is None:                      # not frozen yet: what friendship had earned
        legacy = 0 if _is_migrated() else _int(rec.get("friendship")) // POINTS_PER
    return max(0, _int(legacy) + _int(rec.get("training_earned")) - _int(rec.get("training_spent")))


def _freeze_legacy(db):
    """Once: every Pokemon keeps the points friendship had earned it so far."""
    global _migrated
    for rec in db.get_all_pokemon() or []:
        if rec and rec.get("individual_id") and rec.get("training_legacy") is None:
            rec["training_legacy"] = _int(rec.get("friendship")) // POINTS_PER
            db.save_pokemon(rec)
    db.set_user_data(MIGRATED_KEY, True)
    _migrated = True


def on_review():
    """Once per answered card: every step() cards, your buddy earns a point."""
    try:
        from aqt import mw
        db = mw.ankimon_db
        if not _is_migrated():
            _freeze_legacy(db)
        n = _int(db.get_user_data(COUNT_KEY, 0)) + 1
        if n < step():
            db.set_user_data(COUNT_KEY, n)
            return
        db.set_user_data(COUNT_KEY, 0)
        # Only your buddy trains - not a teammate fighting in its place after it
        # fainted (team rotation makes that one the saved buddy until the
        # encounter ends; wild_rules.buddy_iid still names yours)
        rec = None
        try:
            from ..wild import wild_rules as _wr
            _iid = _wr.buddy_iid()
            rec = db.get_pokemon(_iid) if _iid else None
        except Exception:
            rec = None
        rec = rec or db.get_main_pokemon()
        if not rec or not rec.get("individual_id"):
            return
        rec["training_earned"] = _int(rec.get("training_earned")) + 1
        db.save_pokemon(rec)
        try:
            from aqt.utils import tooltip
            tooltip("%s earned a training point (%d to spend)." % (rec.get("nickname") or rec.get("name"),
                                                                     available(rec)), period=3000)
        except Exception:
            pass
    except Exception as e:
        print("Ankimon training:", e)


def train(individual_id, stat) -> str:
    """Spend one point: +1 to that IV. '' on success, else why not."""
    from aqt import mw
    db = mw.ankimon_db
    rec = db.get_pokemon(individual_id)
    if not rec or stat not in STATS:
        return "That Pokémon couldn't be found."
    if available(rec) <= 0:
        return ("No training points yet - your buddy earns one for every %d cards you review "
                "(2 for a day's card goal)." % step())
    iv = dict(rec.get("iv") or {})
    if int(iv.get(stat, 0) or 0) >= IV_MAX:
        return "That IV is already at its best."
    iv[stat] = int(iv.get(stat, 0) or 0) + 1
    rec["iv"] = iv
    rec["training_spent"] = int(rec.get("training_spent") or 0) + 1
    try:
        from ..business import calculate_cp_from_dict
        rec["cp"] = calculate_cp_from_dict(rec)
    except Exception:
        pass
    db.save_pokemon(rec)
    try:                                   # your buddy in memory, too
        from ..singletons import main_pokemon
        if getattr(main_pokemon, "individual_id", None) == individual_id:
            from .update_main_pokemon import update_main_pokemon
            update_main_pokemon(main_pokemon)
    except Exception:
        pass
    return ""
