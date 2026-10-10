"""
dmax.py - Dynamax (Galar).

  * The Dynamax Band is a reward (your first Galar gym win). Owning it is all
    it takes: nothing to equip.
  * Galar gym-style fights only, on the Showdown engine (it runs the real rules:
    Max Moves and their side effects, double HP for 3 turns, once per battle,
    G-Max forms): Galar gyms, the Champion Cup, rematches, Galar expeditions and
    the roaming legendaries you battle in Galar. Like Sword/Shield's Power Spots.
  * Leaders Dynamax their ace (the last Pokemon they send out) when the gym's
    data says so (Gym.dynamax "dynamax" / "gmax"); Piers never does.
  * In the battle window: the purple "◆ Dynamax" toggle Dynamaxes your Pokemon
    with the next move you pick. Auto-battle Dynamaxes against the leader's ace
    or with your last Pokemon (gymsim.js autoDmax).
  * Test fights (Game > Test) let you Dynamax without the Band.
"""
DYNAMAX_BAND = "dynamax-band"
REGION = "Galar"
PURPLE = "#a855f7"          # Dynamax text; Z-Moves are gold (gym_battle.Z_GOLD)


def has_band() -> bool:
    try:
        from aqt import mw
        it = mw.ankimon_db.get_item(DYNAMAX_BAND)
        return bool(it) and int((it.get("quantity") if isinstance(it, dict) else 1) or 0) > 0
    except Exception:
        return False


def in_galar(gym) -> bool:
    return str(getattr(gym, "region", "") or "") == REGION


def config_for(gym) -> dict:
    """{"p1": you may Dynamax, "p2": the leader's ace Dynamaxes} for this fight."""
    # test fights (Game > Test, Dynamax ones): anywhere, no Band needed
    test = bool(getattr(gym, "is_test", False)) and getattr(gym, "test_mech", "dmax") == "dmax"
    if not (in_galar(gym) or test):
        return {"p1": False, "p2": False}
    you = has_band() or test
    leader = str(getattr(gym, "dynamax", "") or "") in ("dynamax", "gmax")
    return {"p1": you, "p2": leader}


def dmax_flag(manual: bool, auto: bool, allowed: bool):
    """What the Showdown helper is told this turn: True (Dynamax with the
    picked move), "auto" (auto-battle may Dynamax) or None."""
    if not allowed:
        return None
    if manual:
        return True
    return "auto" if auto else None
