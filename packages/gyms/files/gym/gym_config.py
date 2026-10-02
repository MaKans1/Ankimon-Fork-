"""
gym_config.py — reads the Gym settings, with safe fallbacks.

Import-safe outside Anki (the unit tests import it), so every lookup falls
back to DEFAULTS if singletons/settings are unavailable or return junk.

Settings live in Ankimon's normal config, so they appear in the Settings
window and persist through its existing save path. Nothing bespoke.
"""

DEFAULTS = {
    "gym.enabled": True,
    # pacing.recommended() for the default goal (100 cards a day, 2 per round)
    "gym.reviews_per_gym": 225,
    "gym.retry_cost_reviews": 60,
    "gym.decline_cooldown_reviews": 40,
    "gym.leader_smart_moves": True,     # planning leaders; difficulty is tuned for this
    "gym.showdown_engine": True,        # real-game rules via Pokemon Showdown (falls back automatically)
    "gym.original_movesets": False,     # False = Modernized sets, True = exact Red/Blue sets
    "gym.auto_battle": True,
    "gym.show_battle_log": True,
    "gym.elite_four_classic": True,
}


def _raw(key):
    try:
        from ..singletons import settings_obj
        v = settings_obj.get(key)
        return DEFAULTS.get(key) if v is None else v
    except Exception:
        return DEFAULTS.get(key)


def get_bool(key) -> bool:
    v = _raw(key)
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "enabled", "on")
    return bool(DEFAULTS.get(key, False))


def get_int(key, lo=1, hi=100000) -> int:
    v = _raw(key)
    try:
        n = int(str(v).strip())
    except (TypeError, ValueError):
        n = int(DEFAULTS.get(key, lo))
    return max(lo, min(hi, n))


# Convenience accessors used across the package
def enabled() -> bool:
    return get_bool("gym.enabled")


def reviews_per_gym() -> int:
    return get_int("gym.reviews_per_gym", lo=10, hi=10000)


def retry_cost() -> int:
    return get_int("gym.retry_cost_reviews", lo=0, hi=10000)


def decline_cooldown() -> int:
    """Cards to wait after clicking "Not now" before offering again.

    Separate from reviews_per_gym on purpose. Reusing the cadence meant that
    at cadence 1 a decline re-offered instantly and the HUD counter sat pinned
    at "1 / 1", giving no sense of when the gym would come back.
    """
    return get_int("gym.decline_cooldown_reviews", lo=1, hi=10000)


def leader_smart_moves() -> bool:
    return get_bool("gym.leader_smart_moves")


def auto_battle() -> bool:
    return get_bool("gym.auto_battle")


def show_battle_log() -> bool:
    return get_bool("gym.show_battle_log")


def elite_four_classic() -> bool:
    """Classic Elite Four: fight all five back to back in one sitting.

    On  - beating a member chains straight into the next. Your team heals
          between them but cannot be swapped, and no review interval applies
          mid-run.
    Off - the Elite Four behave like ordinary gyms: an interval between each,
          and you re-pick your three every time.
    """
    return get_bool("gym.elite_four_classic")


def showdown_engine() -> bool:
    """Run gym fights on Pokémon Showdown's simulator (real-game rules).
    Falls back to the classic engine if the helper is missing or fails."""
    return get_bool("gym.showdown_engine")


def original_movesets() -> bool:
    """Gym Moveset: True = leaders use their exact Red/Blue moves (near-trivial);
    False (default) = Modernized sets."""
    return get_bool("gym.original_movesets")
