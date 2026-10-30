"""
zmoves.py - Z-Moves (Alola).

  * The Z-Ring is a reward (your first totem trial). Owning it is all it
    takes: nothing to equip.
  * A Pokemon holding a Z-Crystal (Give to hold, in the bag or the PC) can
    turn one move of the crystal's type into its Z-Move, once per battle.
  * Alola only (user 2026-10-28, like Dynamax in Galar and Tera in Paldea): its
    gyms, trials, rematches and expeditions, on the Showdown engine (it runs the real
    Z-Move rules: power, Z-status effects, once per battle). The built-in
    engine and wild battles have no Z-Moves. Leaders never use them.
  * In the battle window: the "Z-Move" toggle turns the next move you pick
    into its Z-Move. Auto-battle spends it on the leader's last Pokemon, or
    when yours is low or about to be knocked out (gymsim.js autoZ).
"""
Z_RING = "z-ring"
REGION = "Alola"
Z_CRYSTALS = {
    "normalium-z": "Normal", "firium-z": "Fire", "waterium-z": "Water",
    "electrium-z": "Electric", "grassium-z": "Grass", "icium-z": "Ice",
    "fightinium-z": "Fighting", "poisonium-z": "Poison", "groundium-z": "Ground",
    "flyinium-z": "Flying", "psychium-z": "Psychic", "buginium-z": "Bug",
    "rockium-z": "Rock", "ghostium-z": "Ghost", "dragonium-z": "Dragon",
    "darkinium-z": "Dark", "steelium-z": "Steel", "fairium-z": "Fairy",
}


def crystal_type(item):
    """'firium-z' -> 'Fire'; None for anything that isn't a Z-Crystal."""
    return Z_CRYSTALS.get(str(item or "").lower())


def has_ring() -> bool:
    try:
        from aqt import mw
        it = mw.ankimon_db.get_item(Z_RING)
        return bool(it) and int((it.get("quantity") if isinstance(it, dict) else 1) or 0) > 0
    except Exception:
        return False


def _move_type(move) -> str:
    """'Tackle' -> 'Normal' (Ankimon's move data), or ''."""
    try:
        from ..functions.pokedex_functions import find_details_move
        d = find_details_move(str(move)) or {}
        return str(d.get("type") or "").capitalize()
    except Exception:
        return ""


def can_use_crystal(rec, item) -> bool:
    """True if this saved Pokemon (a dict with "attacks") knows a move of the
    crystal's type right now - holding it then gives a Z-Move."""
    t = crystal_type(item)
    if not t:
        return False
    return any(_move_type(m) == t for m in ((rec or {}).get("attacks") or []))


def z_moves_enabled() -> bool:
    """Z-Moves are on once you own the Z-Ring."""
    return has_ring()


def allowed(gym) -> bool:
    """Z-Moves in this fight: Alola's, with the Z-Ring. Test fights (Game > Test): anywhere, no Ring."""
    if getattr(gym, "is_test", False):
        return True
    return str(getattr(gym, "region", "") or "") == REGION and has_ring()


def crystal_for(moves) -> str:
    """A Z-Crystal one of these moves can use (its first attacking move's type), or ''."""
    by_type = {t: k for k, t in Z_CRYSTALS.items()}
    for m in moves or []:
        t = _move_type(m)
        if t in by_type:
            return by_type[t]
    return ""


def z_flag(manual_z: bool, auto: bool, test: bool = False):
    """What the Showdown helper is told this turn: True (use the picked move
    as its Z-Move), "auto" (auto-battle may spend it) or None. Test fights
    (Game > Test) count as owning the Z-Ring."""
    if not (has_ring() or test):
        return None
    if manual_z:
        return True
    return "auto" if auto else None
