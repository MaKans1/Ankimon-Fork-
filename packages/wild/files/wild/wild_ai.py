"""
wild_ai.py - "pseudo-smart" move choice for wild battles (both sides).

Plain Python, no Anki imports: the balance sim and the addon run this exact file.

Each usable move gets a score in "fraction of a turn's worth" units:
  attacks       expected damage as a fraction of the foe's remaining HP
                (Gen 5+ damage formula: level, power, attack/defence with stat
                stages, STAB, type effectiveness, accuracy); a likely KO wins
  stat boosts   worth it while healthy and not yet boosted (max +2 per stat),
                only if the fight looks long enough to cash in
  debuffs       worth it early, while the foe is healthy and not yet lowered
  status        sleep > paralysis/toxic > burn (vs physical foes) > poison >
                confusion/leech seed - only if the foe has no status and isn't
                immune by type
  healing       only when below half HP
A little noise keeps it from being perfectly predictable.

Inputs are plain dicts so any engine can call it:
  side = {"level", "types", "atk", "def", "spa", "spd", "spe", "hp", "maxhp",
          "boosts": {"atk": n, ...}, "status": None|"par"|..., "volatiles": set()}
  move_data(id) -> dict in Showdown/poke-engine format (basePower, type,
          category, accuracy, boosts, target, status, volatileStatus, heal...)
  type_eff(attack_type, defender_types) -> multiplier
"""

STAGE = {-6: 2 / 8, -5: 2 / 7, -4: 2 / 6, -3: 2 / 5, -2: 2 / 4, -1: 2 / 3, 0: 1.0,
         1: 3 / 2, 2: 4 / 2, 3: 5 / 2, 4: 6 / 2, 5: 7 / 2, 6: 8 / 2}
_STATUS_VALUE = {"slp": 0.60, "par": 0.40, "tox": 0.40, "brn": 0.35, "psn": 0.25}
_VOLATILE_VALUE = {"confusion": 0.20, "leechseed": 0.30, "yawn": 0.30}
_BOOST_KEYS = {"attack": "atk", "defense": "def", "special-attack": "spa",
               "special-defense": "spd", "speed": "spe", "spa": "spa", "spd": "spd",
               "atk": "atk", "def": "def", "spe": "spe", "accuracy": "accuracy",
               "evasion": "evasion"}


def _acc(m):
    a = m.get("accuracy")
    return 1.0 if a is True or a is None else max(0.0, min(1.0, a / 100.0))


def _stat(side, key):
    return max(1.0, float(side.get(key) or 1)) * STAGE.get(int((side.get("boosts") or {}).get(key, 0)), 1.0)


def expected_damage(me, foe, m, type_eff):
    """Expected HP the move takes off the foe (0 for status moves)."""
    if (m.get("category") or "").lower() == "status":
        return 0.0
    bp = m.get("basePower") or 0
    if not bp:
        dmg = m.get("damage")
        if dmg == "level":
            return float(me["level"]) * _acc(m)
        if isinstance(dmg, (int, float)):
            return float(dmg) * _acc(m)
        return 0.0
    phys = (m.get("category") or "").lower() == "physical"
    a = _stat(me, "atk" if phys else "spa")
    d = _stat(foe, "def" if phys else "spd")
    if phys and me.get("status") == "brn":
        a *= 0.5
    base = ((2 * me["level"] / 5 + 2) * bp * a / d) / 50 + 2
    mtype = (m.get("type") or "").lower()
    stab = 1.5 if mtype in [t.lower() for t in me.get("types") or []] else 1.0
    eff = type_eff(mtype, [t.lower() for t in foe.get("types") or []])
    return base * stab * eff * _acc(m) * 0.925          # 0.925 = mean damage roll


def _immune_to_status(status, foe_types):
    t = {x.lower() for x in foe_types or []}
    if status in ("psn", "tox"):
        return bool(t & {"poison", "steel"})
    if status == "brn":
        return "fire" in t
    if status == "par":
        return "electric" in t
    if status == "frz":
        return "ice" in t
    return False


def score_move(mid, me, foe, move_data, type_eff, foe_best_frac):
    m = move_data(mid) or {}
    cat = str(m.get("category") or "").lower()
    me_hp = me["hp"] / max(1, me["maxhp"])
    foe_hp = foe["hp"] / max(1, foe["maxhp"])
    if cat != "status":
        dmg = expected_damage(me, foe, m, type_eff)
        frac = dmg / max(1, foe["hp"])
        if frac >= 1.0:
            return 2.0 + frac                     # KO now: always worth it
        prio = 0.05 if (m.get("priority") or 0) > 0 and frac > 0.3 else 0.0
        return frac + prio
    # turns the fight is likely to last for us (how long we survive)
    turns_left = 1.0 / max(0.05, foe_best_frac)
    boosts = m.get("boosts") or {}
    target_self = (m.get("target") in ("self", "allySide", "allies", "adjacentAllyOrSelf"))
    if m.get("heal") and (m.get("heal") or [0])[0] > 0:
        return 0.55 if me_hp < 0.5 else 0.0
    if boosts and target_self and any(v > 0 for v in boosts.values()):
        if me_hp < 0.6 or turns_left < 3:
            return 0.0
        room = [k for k, v in boosts.items() if v > 0
                and int((me.get("boosts") or {}).get(_BOOST_KEYS.get(k, k), 0)) < 2]
        return 0.35 if room else 0.0
    if boosts and any(v < 0 for v in boosts.values()):
        low = [k for k, v in boosts.items() if v < 0
               and int((foe.get("boosts") or {}).get(_BOOST_KEYS.get(k, k), 0)) > -2]
        return 0.22 * _acc(m) if low and foe_hp > 0.5 and turns_left >= 3 else 0.0
    st = m.get("status")
    if st:
        if foe.get("status") or _immune_to_status(st, foe.get("types")):
            return 0.0
        v = _STATUS_VALUE.get(st, 0.2)
        if st == "brn" and foe.get("atk", 0) < foe.get("spa", 0):
            v = 0.15                              # burn matters less vs special attackers
        return v * _acc(m)
    vs = m.get("volatileStatus")
    if vs in _VOLATILE_VALUE and vs not in (foe.get("volatiles") or set()):
        return _VOLATILE_VALUE[vs] * _acc(m)
    return 0.02


MAX_SUPPORT_USES = 2      # per move, per life - a support move that silently fails can't loop


def choose(moves, me, foe, move_data, type_eff, rng, foe_moves=None, noise=0.12, history=None):
    """Pick a move id from `moves` (already filtered: PP, checkmarks...).
    history: moves this side used since its current life began (for the repeat limit)."""
    moves = [m for m in moves if m]
    if not moves:
        return None
    history = list(history or [])
    foe_best = 0.0
    for fm in foe_moves or []:
        d = expected_damage(foe, me, move_data(fm) or {}, type_eff)
        foe_best = max(foe_best, d / max(1, me["hp"]))
    best, bv = moves[0], -1.0
    for mid in moves:
        s = score_move(mid, me, foe, move_data, type_eff, foe_best)
        cat = str((move_data(mid) or {}).get("category") or "").lower()
        if cat == "status" and history.count(mid) >= MAX_SUPPORT_USES:
            s = 0.0                            # used enough: attack instead
        s *= 1.0 + rng.uniform(-noise, noise)
        if s > bv:
            best, bv = mid, s
    return best
