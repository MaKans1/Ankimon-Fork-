"""
totem.py - after an Alola totem trial.

  * offer_catch(gym): a guaranteed catch prompt for the defeated totem's
    species. You get a normal member of the species - no aura, no totem size,
    no special ability - at the totem's level, with every IV rolled from 16
    to 31 (a totem is always a strong specimen).
  * The trial's Z-Crystal is given with the other rewards (gym_battle.
    award_victory); zmoves.py is the hook for Z-Moves later.

The battle rules themselves (aura, calling for help, coming back at half HP)
live in the engines: gymsim.js (Showdown) and gym_engine.py (classic).
"""
import random

from aqt import mw
from aqt.qt import QMessageBox

TOTEM_IV_MIN, TOTEM_IV_MAX = 16, 31
STATS = ("hp", "atk", "def", "spa", "spd", "spe")


def _log(level, msg):
    try:
        from ..singletons import logger
        logger.log(level, "[gym] totem: %s" % msg)
    except Exception:
        print("[gym] totem: %s" % msg)


def _dn(n):
    try:
        from ..functions.pokedex_functions import display_name
        return display_name(n)
    except Exception:
        s = str(n or "")
        return s[:1].upper() + s[1:]


def roll_ivs(rng=random):
    """Every IV uniformly from 16 to 31."""
    return {k: rng.randint(TOTEM_IV_MIN, TOTEM_IV_MAX) for k in STATS}


def build_catch(gym):
    """The Pokemon you'd catch: a normal member of the totem's species."""
    from . import gym_battle as GB
    from .gym_data import GymMon
    mon = gym.team[0]
    p = GB.build_leader_pokemon(GymMon(mon.species, int(mon.level), list(mon.moves or []) or None))
    if p is None:
        return None
    p.iv = roll_ivs()
    p.tier = "Normal"
    p.stat_stages = {k: 0 for k in ("atk", "def", "spa", "spd", "spe", "accuracy", "evasion")}
    p.battle_status = "fighting"
    try:
        from ..functions.pokemon_functions import shiny_chance
        p.shiny = bool(shiny_chance())
    except Exception:
        p.shiny = False
    mx = int(p.calculate_max_hp())
    p.max_hp = p.hp = p.current_hp = mx
    return p


def offer_catch(gym) -> bool:
    """After winning a totem trial: ask, then save the catch. True if caught."""
    if not (getattr(gym, "totem", None) or getattr(gym, "titan", None)) or getattr(gym, "is_rematch", False):
        return False
    mon = gym.team[0]
    name = _dn(mon.species)
    r = QMessageBox.question(
        mw, "Titan" if getattr(gym, "titan", None) else "Totem trial",
        "Catch %s (Lv %d)?" % (name, int(mon.level)),
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.Yes)
    if r != QMessageBox.StandardButton.Yes:
        return False
    try:
        p = build_catch(gym)
        if p is None:
            raise ValueError("could not build %s" % mon.species)
        from ..functions.encounter_functions import save_caught_pokemon
        from ..singletons import achievements
        save_caught_pokemon(p, _dn(p.name), achievements)
        _log("info", "caught %s (Lv %d, IVs %s) after %s" % (p.name, p.level, p.iv, gym.name))
        return True
    except Exception as e:
        _log("error", "saving the totem catch failed: %s" % e)
        QMessageBox.warning(mw, "Totem trial", "You won, but saving %s failed: %s" % (name, e))
        return False
