"""
tera.py - Terastallization (Paldea).

  * The Tera Orb is a reward (your first Paldea gym win). Owning it is all it
    takes: nothing to equip, and it's ready again for every battle.
  * Paldea gym-style fights only, on the Showdown engine (Gen 9 rules: Tera
    type, same-type bonus, Tera Blast, once per battle): Paldea gyms, Titans,
    the Elite Four and Champion, rematches, Paldea expeditions and the roaming
    legendaries you battle there.
  * A Pokemon can only Terastallize while holding a Tera Shard of a type
    ("water-tera-shard" = Tera Shard (Water)); it becomes that type. Whoever
    Terastallizes - you or a leader - swaps their weakest attack for Tera Blast
    for the rest of the battle (gymsim.js teraBlastSwap).
  * Leaders' aces (the last Pokemon they send out) Terastallize into a type rolled
    for every fight (roll_ace_type): mostly types that resist what normally beats
    the gym's type, plus one or two neutral or bad picks. A win drops the Tera
    Shard of the type their ace used in that battle.
  * In the battle window: the "◈ Tera" toggle Terastallizes your Pokemon with
    the next move you pick. Auto-battle uses it against the leader's ace or
    with your last Pokemon (gymsim.js autoTera).
  * Test fights (Game > Test) allow it anywhere, without the Orb.
"""
TERA_ORB = "tera-orb"
REGION = "Paldea"
CYAN = "#22d3ee"            # Tera text (Z-Moves gold, Dynamax purple)


TYPES = ["Normal", "Fire", "Water", "Electric", "Grass", "Ice", "Fighting", "Poison", "Ground", "Flying",
         "Psychic", "Bug", "Rock", "Ghost", "Dragon", "Dark", "Steel", "Fairy"]
# attacking type -> (super effective against, not very effective against, no effect on)
CHART = {
    "Normal": ((), ("Rock", "Steel"), ("Ghost",)),
    "Fire": (("Grass", "Ice", "Bug", "Steel"), ("Fire", "Water", "Rock", "Dragon"), ()),
    "Water": (("Fire", "Ground", "Rock"), ("Water", "Grass", "Dragon"), ()),
    "Electric": (("Water", "Flying"), ("Electric", "Grass", "Dragon"), ("Ground",)),
    "Grass": (("Water", "Ground", "Rock"), ("Fire", "Grass", "Poison", "Flying", "Bug", "Dragon", "Steel"), ()),
    "Ice": (("Grass", "Ground", "Flying", "Dragon"), ("Fire", "Water", "Ice", "Steel"), ()),
    "Fighting": (("Normal", "Ice", "Rock", "Dark", "Steel"), ("Poison", "Flying", "Psychic", "Bug", "Fairy"), ("Ghost",)),
    "Poison": (("Grass", "Fairy"), ("Poison", "Ground", "Rock", "Ghost"), ("Steel",)),
    "Ground": (("Fire", "Electric", "Poison", "Rock", "Steel"), ("Grass", "Bug"), ("Flying",)),
    "Flying": (("Grass", "Fighting", "Bug"), ("Electric", "Rock", "Steel"), ()),
    "Psychic": (("Fighting", "Poison"), ("Psychic", "Steel"), ("Dark",)),
    "Bug": (("Grass", "Psychic", "Dark"), ("Fire", "Fighting", "Poison", "Flying", "Ghost", "Steel", "Fairy"), ()),
    "Rock": (("Fire", "Ice", "Flying", "Bug"), ("Fighting", "Ground", "Steel"), ()),
    "Ghost": (("Psychic", "Ghost"), ("Dark",), ("Normal",)),
    "Dragon": (("Dragon",), ("Steel",), ("Fairy",)),
    "Dark": (("Psychic", "Ghost"), ("Fighting", "Dark", "Fairy"), ()),
    "Steel": (("Ice", "Rock", "Fairy"), ("Fire", "Water", "Electric", "Steel"), ()),
    "Fairy": (("Fighting", "Dragon", "Dark"), ("Fire", "Poison", "Steel"), ()),
}
COUNTER_SHARE = 0.8       # how often the ace's Tera is a counter pick (the rest: the wildcards)


def eff(attack, defend) -> float:
    se, nve, imm = CHART.get(attack, ((), (), ()))
    return 2.0 if defend in se else 0.5 if defend in nve else 0.0 if defend in imm else 1.0


def roll_ace_type(base_type, rng=None) -> str:
    """The ace's Tera type for this fight. base_type = the gym's type (Gym.tera).
    Counter picks: types that resist what is super effective against base_type
    (scored resist - weak over those threats); plus two wildcards - any other
    type, neutral or bad - so it's never fully predictable."""
    import random
    rng = rng or random
    base = base_type if base_type in CHART else "Normal"
    threats = [a for a in TYPES if eff(a, base) > 1]
    score = {c: sum(1 for a in threats if eff(a, c) < 1) - sum(1 for a in threats if eff(a, c) > 1) for c in TYPES}
    top = max(score.values())
    counters = [c for c in TYPES if score[c] >= max(1, top - 1)][:6] or [base]
    wild = rng.sample([c for c in TYPES if c not in counters], 2)
    weights = [COUNTER_SHARE / len(counters)] * len(counters) + [(1 - COUNTER_SHARE) / len(wild)] * len(wild)
    return rng.choices(counters + wild, weights=weights, k=1)[0]


def shard_item(type_name) -> str:
    """'Water' -> 'water-tera-shard'."""
    return "%s-tera-shard" % str(type_name).lower()


def shard_type(item) -> str:
    """'water-tera-shard' -> 'Water'; '' for anything else."""
    s = str(item or "").lower()
    if s.endswith("-tera-shard"):
        t = s[:-len("-tera-shard")].capitalize()
        return t if t in CHART else ""
    return ""


def shard_name(type_name) -> str:
    return "Tera Shard (%s)" % type_name


def has_orb() -> bool:
    try:
        from aqt import mw
        it = mw.ankimon_db.get_item(TERA_ORB)
        return bool(it) and int((it.get("quantity") if isinstance(it, dict) else 1) or 0) > 0
    except Exception:
        return False


def in_paldea(gym) -> bool:
    return str(getattr(gym, "region", "") or "") == REGION


def config_for(gym) -> dict:
    """{"p1": you may Terastallize, "p2": the leader's ace Terastallizes}."""
    # test fights (Game > Test, Tera / Titan ones): anywhere, no Orb needed
    test = bool(getattr(gym, "is_test", False)) and getattr(gym, "test_mech", "tera") in ("tera", "titan")
    if not (in_paldea(gym) or test):
        return {"p1": False, "p2": False}
    return {"p1": has_orb() or test, "p2": bool(getattr(gym, "tera", "") or "")}


def tera_flag(manual: bool, auto: bool, allowed: bool):
    """What the Showdown helper is told this turn: True (Terastallize with the
    picked move), "auto" (auto-battle may) or None."""
    if not allowed:
        return None
    if manual:
        return True
    return "auto" if auto else None
