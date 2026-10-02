"""
wild_fallback.py - what battle_loop uses when the Wild Mode package isn't
installed: classic Ankimon wild battles (random moves, no level caps, no team
rotation). Same function names as wild/wild_rules.py, so battle_loop doesn't
care which one it got.
"""
import random

from ..poke_engine.data import all_move_json
from ..poke_engine.helpers import normalize_name

POPUP_KEYS = {
    "damage": "battle.popup_damage",
    "faint": "battle.popup_faint",
    "xp": "battle.popup_xp",
    "levelup": "battle.popup_levelup",
    "catch": "battle.popup_catch",
}


def popup(kind):
    try:
        from ..singletons import settings_obj
        v = settings_obj.get(POPUP_KEYS[kind], False)
        if isinstance(v, str):
            return v.strip().lower() in ("1", "true", "yes", "on", "enabled")
        return bool(v)
    except Exception:
        return False


def check_team_change():
    return False


def choose_moves(main_pokemon, enemy_pokemon, s, rng=random):
    ua = [a for a in (main_pokemon.attacks or []) if a]
    ea = [a for a in (enemy_pokemon.attacks or []) if a]
    return (rng.choice(ua) if ua else "splash"), (rng.choice(ea) if ea else "splash")


def move_details(move):
    e = all_move_json.get(normalize_name(str(move or ""))) or {}
    return {"category": str(e.get("category") or "physical").capitalize(), "type": e.get("type")}


def after_turn(s, user_attack, enemy_attack, heals_to_opponent, main_pokemon=None):
    return heals_to_opponent


def real_hp(pobj, engine_mon):
    return getattr(engine_mon, "hp", 0)
