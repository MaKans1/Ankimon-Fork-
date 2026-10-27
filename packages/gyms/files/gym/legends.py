"""
legends.py - roaming legendaries, mythicals and Mewtwo: ultra-rare encounters.

  * While you review, each new wild encounter has a small chance to bring one
    of these instead of staying ordinary (wild_rules.special_spawn rolls it):
      - a roamer, ~1 in 150 encounters while one roams the region you're in;
      - a one-time spawn (mythicals, Mewtwo), ~1 in 750 once its condition is
        met (badges and/or particular legendaries, nothing outside the game).
  * On your next card: "A wild Raikou appeared! Battle it?" Yes -> pick three
    team members -> a gym-style battle (Showdown when installed), your three
    against it. Auto or manual follows your gym setting. No -> it flees.
  * Win = you catch it (every IV 25-31). Lose = it flees. Roamers keep their
    damage between meetings and go back to roaming; one-time spawns heal and
    may turn up again later. No rematch button; badges, gym timers and
    rematches are never touched.
  * Strong, and tuned: level = the top of your wild level band in the region
    + its own offset (legends_data.OFFSETS), set so three type-advantaged
    Pokemon at the band top win about 75% of the time (balance_sim/
    legend_tune.js). Moves: its best attack, its best attack of another type
    and two support moves for that level (legends_data.SETS).
  * The region's Expeditions page says when powerful Pokemon may be in the
    wild, and names the ones you've met.
"""
import random

from aqt import mw
from aqt.qt import QMessageBox, QTimer, QApplication

ROAMER_RATE = 1.0 / 150
SPAWN_RATE = 1.0 / 750
STRONG = 12                     # fallback offset (legends_data.DEFAULT_OFFSET)
IV_FLOOR = 21                   # ~68% (was 25; user 2026-10-15); never a forced 31
LEGEND_GYM_BASE = 900000        # synthetic gym ids for these fights (never stored)

# dex id: (name, region, condition). Conditions (all must hold):
#   released=<expedition key>  that expedition was cleared (Burned Tower)
#   badges=N                   N badges in the region
#   champion=True              the region's Champion beaten
#   owns=(ids)                 you own every one of these right now
#   registered=N               N of the region's Pokemon registered in your Pokedex
#   legends=N                  you own N legendary/mythical species
#   fire_water=True            you own a Fire-type and a Water-type legendary
#   rate="rare"                a roamer at Mewtwo rarity (SPAWN_RATE) - the other half
#                              of a pair you chose (Zacian / Zamazenta...), Paldea DLC
# Ids over 10000 are regional forms (FORMS: the species they really are).
FORMS = {10169: "Articuno-Galar", 10170: "Zapdos-Galar", 10171: "Moltres-Galar"}
ROAMERS = {
    243: ("Raikou", "Johto", {"released": "burned_tower"}),
    244: ("Entei", "Johto", {"released": "burned_tower"}),
    380: ("Latias", "Hoenn", {"champion": True}),
    481: ("Mesprit", "Sinnoh", {"badges": 7}),
    488: ("Cresselia", "Sinnoh", {"champion": True}),
    641: ("Tornadus", "Unova", {"champion": True}),
    642: ("Thundurus", "Unova", {"champion": True}),
    # Galar: the Galarian birds roam after the Champion (Crown Tundra)
    10169: ("Articuno-Galar", "Galar", {"champion": True}),
    10170: ("Zapdos-Galar", "Galar", {"champion": True}),
    10171: ("Moltres-Galar", "Galar", {"champion": True}),
    # pairs: choose one on its expedition, the other roams (rarely) once you own it
    888: ("Zacian", "Galar", {"owns": (889,), "rate": "rare"}),
    889: ("Zamazenta", "Galar", {"owns": (888,), "rate": "rare"}),
    894: ("Regieleki", "Galar", {"owns": (895,), "rate": "rare"}),
    895: ("Regidrago", "Galar", {"owns": (894,), "rate": "rare"}),
    1007: ("Koraidon", "Paldea", {"owns": (1008,), "rate": "rare"}),
    1008: ("Miraidon", "Paldea", {"owns": (1007,), "rate": "rare"}),
    # Paldea DLC legendaries: rare roamers after the Champion
    1014: ("Okidogi", "Paldea", {"champion": True, "rate": "rare"}),
    1015: ("Munkidori", "Paldea", {"champion": True, "rate": "rare"}),
    1016: ("Fezandipiti", "Paldea", {"champion": True, "rate": "rare"}),
    1017: ("Ogerpon", "Paldea", {"champion": True, "rate": "rare"}),
    1024: ("Terapagos", "Paldea", {"champion": True, "rate": "rare"}),
    1025: ("Pecharunt", "Paldea", {"champion": True, "rate": "rare"}),
}
SPAWNS = {
    150: ("Mewtwo", "Kanto", {"badges": 8, "registered": 100}),
    251: ("Celebi", "Johto", {"champion": True, "owns": (243, 244, 245)}),
    385: ("Jirachi", "Hoenn", {"champion": True}),
    386: ("Deoxys", "Hoenn", {"owns": (384,)}),
    490: ("Manaphy", "Sinnoh", {"champion": True, "owns": (382,)}),
    489: ("Phione", "Sinnoh", {"owns": (490,)}),
    491: ("Darkrai", "Sinnoh", {"owns": (488,)}),
    492: ("Shaymin", "Sinnoh", {"champion": True, "registered": 100}),
    493: ("Arceus", "Sinnoh", {"owns": (483, 484, 487)}),
    494: ("Victini", "Unova", {"champion": True}),
    647: ("Keldeo", "Unova", {"owns": (638, 639, 640)}),
    648: ("Meloetta", "Unova", {"champion": True, "owns": (645,)}),
    649: ("Genesect", "Unova", {"owns": (646,)}),
    719: ("Diancie", "Kalos", {"champion": True, "owns": (703,)}),
    720: ("Hoopa", "Kalos", {"legends": 10}),
    721: ("Volcanion", "Kalos", {"fire_water": True}),
    893: ("Zarude", "Galar", {"champion": True}),
    # These only ever spawned through Ankimon's old wild tables, which no longer
    # offer legendaries (wild_rules.legendary_ids): now Mewtwo-style encounters.
    772: ("Type: Null", "Alola", {"champion": True}),
    789: ("Cosmog", "Alola", {"champion": True}),
    792: ("Lunala", "Alola", {"owns": (791,)}),       # Cosmog's line evolves into Solgaleo here
    800: ("Necrozma", "Alola", {"champion": True, "owns": (791,)}),
    801: ("Magearna", "Alola", {"champion": True}),
    802: ("Marshadow", "Alola", {"champion": True}),
    807: ("Zeraora", "Alola", {"champion": True}),
    808: ("Meltan", "Alola", {"champion": True}),
    809: ("Melmetal", "Alola", {"owns": (808,)}),     # Meltan can't evolve in Ankimon
    905: ("Enamorus", "Galar", {"champion": True}),
}
REGION_GEN = {"Kanto": 1, "Johto": 2, "Hoenn": 3, "Sinnoh": 4, "Unova": 5, "Kalos": 6,
              "Alola": 7, "Galar": 8, "Paldea": 9}
# legendary and mythical species (for Hoopa / Volcanion)
LEGEND_IDS = ({144, 145, 146, 150, 151} | set(range(243, 246)) | set(range(249, 252))
              | set(range(377, 387)) | set(range(480, 495)) | set(range(638, 650))
              | set(range(716, 722)) | set(range(785, 810)) | set(range(888, 899))
              | set(range(1001, 1011)) | set(range(1014, 1018)) | {1024, 1025}
              | {772, 773, 905})
# Mewtwo keeps its hand-picked set (wild_rules.LEGEND_SETS)

_pending = None                 # {"id", "kind"} waiting to be offered on the next card
_offering = False


def _log(level, msg):
    try:
        from ..singletons import logger
        logger.log(level, "[gym] legends: %s" % msg)
    except Exception:
        print("[gym] legends: %s" % msg)


def _ui():
    from . import gym_ui
    return gym_ui


def _meta_get(key, default=None):
    try:
        return _ui().progress().get_meta(key, default)
    except Exception:
        return default


def _meta_set(key, value):
    try:
        _ui().progress().set_meta(key, value)
    except Exception as e:
        _log("warning", "could not save %s: %s" % (key, e))


def _wild():
    from ..wild import wild_rules
    return wild_rules


def _name(i):
    hit = ROAMERS.get(i) or SPAWNS.get(i)
    if hit:
        return hit[0]
    try:
        from ..functions.pokedex_functions import search_pokedex_by_id, display_name
        return display_name(search_pokedex_by_id(int(i)))
    except Exception:
        return "#%d" % i


# --------------------------------------------- legendaries you've caught --
# Every legendary you've caught can turn up again in its home region at
# Mewtwo's rarity (SPAWN_RATE), as the same 3-vs-1 encounter - the Kanto birds
# after their expeditions, too - and every one you catch is kept (catches never
# replace a legendary: encounter_functions._duplicate_verdict). Not Paradox
# Pokemon (Area Zero only) or Kubfu / Urshifu (their own spawn and towers).
# Mew (151): only the 7-day goal streak gift (gym/mew.py), never the wild (user 2026-10-17).
_SKIP_AGAIN = {151, 891, 892, 984, 985, 986, 987, 988, 989, 990, 991, 992, 993, 994, 995,
               1005, 1006, 1009, 1010, 1020, 1021, 1022, 1023}


def _home(i):
    """The region a legendary belongs to."""
    hit = ROAMERS.get(i) or SPAWNS.get(i)
    if hit:
        return hit[1]
    try:
        from . import expedition
        for e in expedition.EXPEDITIONS:
            if int(getattr(e, "legendary_id", 0) or 0) == int(i):
                return e.region
    except Exception:
        pass
    for name, gen in REGION_GEN.items():
        lo = {1: 1, 2: 152, 3: 252, 4: 387, 5: 494, 6: 650, 7: 722, 8: 810, 9: 906}[gen]
        hi = {1: 151, 2: 251, 3: 386, 4: 493, 5: 649, 6: 721, 7: 809, 8: 905, 9: 1025}[gen]
        if lo <= int(i) <= hi:
            return name
    return None


def again_here(region):
    """Legendaries you've caught that can turn up again here."""
    ids = (set(LEGEND_IDS) | set(FORMS)) - _SKIP_AGAIN
    return sorted(i for i in ids if _home(i) == region and caught(i))


# ------------------------------------------------------------ conditions --
def _registered():
    try:
        from ..wild import dex
        return set(dex.registered())
    except Exception:
        return set()


def caught(i) -> bool:
    """One per save: registered in your Pokedex (you've owned it) - or, for a
    regional form (FORMS), caught through this system."""
    if _meta_get("legend_caught_%d" % int(i)):
        return True
    return int(i) not in FORMS and int(i) in _registered()


def _owned():
    from . import expedition
    return expedition.owned_ids()


def _types(i):
    try:
        from ..functions.pokedex_functions import search_pokedex_by_id, search_pokedex
        key = FORMS[int(i)].lower().replace("-", "") if int(i) in FORMS else search_pokedex_by_id(int(i)).lower()
        return [str(t).lower() for t in (search_pokedex(key, "types") or [])]
    except Exception:
        return []


def condition_met(cond, region) -> bool:
    try:
        if cond.get("released"):
            from . import expedition
            exp = next((e for e in expedition.EXPEDITIONS if e.key == cond["released"]), None)
            if exp is None or not expedition.done(exp):
                return False
        if cond.get("badges") and int(_wild().badges(region) or 0) < int(cond["badges"]):
            return False
        if cond.get("champion"):
            from . import expedition
            if not expedition.champion_beaten(region):
                return False
        owned = None
        if cond.get("owns"):
            owned = _owned()
            if not all(int(x) in owned for x in cond["owns"]):
                return False
        if cond.get("registered"):
            from ..wild import dex
            if dex.region_count(REGION_GEN.get(region, 1), dex.registered()) < int(cond["registered"]):
                return False
        if cond.get("legends") or cond.get("fire_water"):
            owned = owned if owned is not None else _owned()
            mine = [x for x in owned if x in LEGEND_IDS]
            if cond.get("legends") and len(mine) < int(cond["legends"]):
                return False
            if cond.get("fire_water"):
                kinds = [set(_types(x)) for x in mine]
                if not (any("fire" in k for k in kinds) and any("water" in k for k in kinds)):
                    return False
        return True
    except Exception as e:
        _log("warning", "condition check failed: %s" % e)
        return False


def roamers_here(region):
    return [i for i, (_n, r, c) in ROAMERS.items() if r == region and not caught(i) and condition_met(c, region)]


def spawns_here(region):
    return [i for i, (_n, r, c) in SPAWNS.items() if r == region and not caught(i) and condition_met(c, region)]


def release(ids):
    """A release expedition was cleared (Burned Tower): mark them loose."""
    for i in ids:
        _meta_set("legend_released_%d" % int(i), "1")


# ----------------------------------------------------------------- roll --
def roll(rng=random) -> bool:
    """Called for each new wild encounter (wild_rules.special_spawn). True if
    an ultra-rare encounter was queued (the encounter itself stays normal)."""
    global _pending
    if _pending is not None or _offering:
        return False
    try:
        ui = _ui()
        if not ui.CFG.enabled() or ui.gym_is_active():
            return False
        from . import expedition
        if expedition.is_active():
            return False
        region = _wild().region()
        here = roamers_here(region)
        rare = [i for i in here if (ROAMERS[i][2] or {}).get("rate") == "rare"]
        roam = [i for i in here if i not in rare]
        if roam and rng.random() < ROAMER_RATE:
            _pending = {"id": rng.choice(roam), "kind": "roamer", "region": region}
            return True
        if rare and rng.random() < SPAWN_RATE:          # roams, but as rarely as Mewtwo
            _pending = {"id": rng.choice(rare), "kind": "roamer", "region": region}
            return True
        once = spawns_here(region)
        if once and rng.random() < SPAWN_RATE:
            _pending = {"id": rng.choice(once), "kind": "spawn", "region": region}
            return True
        again = again_here(region)
        if again and rng.random() < SPAWN_RATE:          # a legendary you've caught, again
            _pending = {"id": rng.choice(again), "kind": "spawn", "region": region}
            return True
    except Exception as e:
        _log("warning", "roll skipped: %s" % e)
    return False


# ---------------------------------------------------------------- offer --
def maybe_offer():
    """Once per answered card: put the queued encounter in front of you."""
    if _pending is None or _offering:
        return
    QTimer.singleShot(900, _offer)


def offset_for(i, top) -> float:
    """Levels above the band top for this legendary (interpolated by band top)."""
    try:
        from .legends_data import OFFSETS, DEFAULT_OFFSET
    except Exception:
        return STRONG
    pts = sorted(OFFSETS.get(int(i)) or [])
    if not pts:
        return DEFAULT_OFFSET
    if top <= pts[0][0]:
        return pts[0][1]
    if top >= pts[-1][0]:
        return pts[-1][1]
    for (p1, k1), (p2, k2) in zip(pts, pts[1:]):
        if p1 <= top <= p2:
            return k1 + (k2 - k1) * (top - p1) / float(p2 - p1)
    return DEFAULT_OFFSET


def level_for(region, i=None) -> int:
    """A wild legendary's level: in the top 1% of the region's badge curve
    (wild_rules.legend_level, user 2026-10-18); without badge levels
    (classic mode), the old top-of-band + per-legendary offset."""
    try:
        lv = _wild().legend_level(region)
        if lv:
            return int(lv)
    except Exception:
        pass
    top = None
    try:
        b = _wild().band(region)
        if b:
            top = int(b[2])
    except Exception:
        pass
    if top is None:
        try:
            from . import gym_battle as GB
            lv = sorted((int(r.get("level") or 1) for r in GB.available_party()), reverse=True)[:3]
            top = round(sum(lv) / len(lv)) if lv else 40
        except Exception:
            top = 40
    k = offset_for(i, top) if i is not None else STRONG
    return max(5, min(100, int(round(top + k))))


def _moves(name, level, i):
    try:
        from .legends_data import SETS
        rows = [ms for lv, ms in SETS.get(int(i), []) if lv <= level]
        if rows:
            return list(rows[-1])
    except Exception:
        pass
    try:
        w = _wild()
        ids = list(w.LEGEND_SETS.get(int(i)) or w.legendary_moves(name.lower(), level) or [])
    except Exception:
        ids = []
    try:
        from ..move_names import format_move_name
        return [format_move_name(m) for m in ids] or None
    except Exception:
        return ids or None


def build(entry):
    """A one-Pokemon 'gym' for the fight (never saved, no badge, no timer)."""
    from .gym_data import Gym, GymMon, GYM
    i, kind, region = int(entry["id"]), entry["kind"], entry["region"]
    name = _name(i)
    level = level_for(region, i)
    types = _types(i) or ["normal"]
    g = Gym(LEGEND_GYM_BASE + i, "Wild %s" % name, name, types[0].capitalize(), "",
            "A wild %s - far stronger than the usual wild Pokemon. Beat it to catch it." % name,
            [GymMon(name, level, _moves(name, level, i))],
            cash_reward=0, kind=GYM, recommended_level=level, region=region)
    g.is_legend = True
    g.legend_id = i
    g.legend_kind = kind
    g.legend_ivs = {k: random.randint(IV_FLOOR, 31) for k in ("hp", "atk", "def", "spa", "spd", "spe")}
    try:                               # shiny is decided when it appears, so the fight shows it
        from ..functions.pokemon_functions import shiny_chance
        g.legend_shiny = bool(shiny_chance())
    except Exception:
        g.legend_shiny = False
    hp = _meta_get("legend_hp_%d" % i) if kind == "roamer" else None
    try:
        g.legend_hp = max(0.05, min(1.0, float(hp))) if hp not in (None, "") else 1.0
    except (TypeError, ValueError):
        g.legend_hp = 1.0
    return g


def prepare(leader, gym):
    """gym_ui.start_gym, after the leader team is built: IVs, and a roamer's
    damage from earlier meetings (carried into Showdown like expeditions)."""
    if not leader:
        return
    c = leader[0]
    src = c.source
    try:
        src.iv = dict(gym.legend_ivs)
        src.tier = "Legendary"
        src.shiny = bool(getattr(gym, "legend_shiny", False))
        mx = int(src.calculate_max_hp())
        hp = max(1, int(round(mx * float(getattr(gym, "legend_hp", 1.0)))))
        c.max_hp, c.hp = mx, hp
        src.max_hp, src.hp, src.current_hp = mx, hp, hp
        c.carry = hp < mx
    except Exception as e:
        _log("warning", "prepare failed: %s" % e)


def _offer():
    global _pending, _offering
    if _pending is None or _offering:
        return
    try:
        if _ui().gym_is_active() or QApplication.activeModalWidget() is not None:
            QTimer.singleShot(4000, _offer)           # another window is up: ask a bit later
            return
    except Exception:
        pass
    entry, _pending = _pending, None
    _offering = True
    try:
        g = build(entry)
        _meta_set("legend_seen_%d" % g.legend_id, "1")
        hurt = getattr(g, "legend_hp", 1.0) < 1.0
        r = QMessageBox.question(
            mw, "A powerful Pokémon!",
            "A wild %s appeared!%s It's very strong (Lv %d)%s.\n\n"
            "Battle it with three of your Pokémon? Beat it to catch it. "
            "If you don't, it flees." % (g.leader, " And it's SHINY!" if getattr(g, "legend_shiny", False) else "",
                                        g.team[0].level,
                                        " - still hurt from your last meeting" if hurt else ""),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes)
        if r != QMessageBox.StandardButton.Yes or not _ui().start_gym(g):
            _fled(g)
    except Exception as e:
        _log("error", "legend offer failed: %s" % e)
    finally:
        _offering = False


def _fled(g):
    try:
        from aqt.utils import tooltip
        tooltip("%s fled." % g.leader, period=3000)
    except Exception:
        pass


# --------------------------------------------------------------- result --
def finish(session):
    """gym_battle.finish_session for these fights: catch on a win, remember a
    roamer's damage on a loss. Never records gym progress."""
    g = session.gym
    c = session.leader_team[0]
    i = int(g.legend_id)
    from .gym_state import GymSession
    notes = []
    if session.status == GymSession.WON:
        try:
            src = c.source
            from ..functions.pokemon_functions import shiny_chance
            from ..functions.encounter_functions import save_caught_pokemon
            from ..singletons import achievements
            mx = int(src.calculate_max_hp())
            src.iv = dict(g.legend_ivs)
            src.max_hp = src.hp = src.current_hp = mx
            src.shiny = bool(getattr(g, "legend_shiny", False))     # rolled when it appeared (build)
            src.tier = "Legendary"
            src.stat_stages = {k: 0 for k in ("atk", "def", "spa", "spd", "spe", "accuracy", "evasion")}
            src.battle_status = "fighting"
            from .gym_battle import _dn
            save_caught_pokemon(src, _dn(src.name), achievements)
            if i in FORMS:                     # a form isn't its own Pokedex entry
                _meta_set("legend_caught_%d" % i, "1")
            notes.append("You caught %s!%s" % (g.leader, " And it's SHINY!" if src.shiny else ""))
        except Exception as e:
            _log("error", "saving %s failed: %s" % (g.leader, e))
            notes.append("You won, but saving %s failed: %s" % (g.leader, e))
        _meta_set("legend_hp_%d" % i, "")
        survivors = [p for p in session.player_team if not p.fainted]
        xp_each = max(1, int(c.level * 4 / max(1, len(survivors))))
        for p in survivors:
            try:
                rec = mw.ankimon_db.get_pokemon(p.individual_id)
                if rec:
                    rec["xp"] = int(rec.get("xp", 0)) + xp_each
                    mw.ankimon_db.save_pokemon(rec)
            except Exception as e:
                _log("warning", "xp failed for %s: %s" % (p.name, e))
        if survivors:
            notes.append("%d XP to each surviving Pokémon." % xp_each)
        try:
            from ..wild import dex
            dex.sync_and_award()
        except Exception:
            pass
    else:
        if g.legend_kind == "roamer":
            frac = (float(c.hp) / max(1, c.max_hp)) if c.hp > 0 else 1.0
            _meta_set("legend_hp_%d" % i, "%.3f" % frac)
            notes.append("%s fled - it's still roaming %s%s." % (
                g.leader, g.region, ", and it hasn't healed" if frac < 1.0 else ""))
        else:
            notes.append("%s fled. It may turn up again some day." % g.leader)
        notes.append("Your team is healed.")
    return notes


# ------------------------------------------------------------------- UI --
def menu_note(region) -> str:
    """The Expeditions page line: powerful Pokemon may be in the wild here."""
    try:
        here = roamers_here(region) + spawns_here(region)
    except Exception:
        return ""
    if not here:
        return ""
    seen = [_name(i) for i in here if _meta_get("legend_seen_%d" % i)]
    return ("<b>Powerful Pokémon may be found in %s's wild.</b>%s" % (
        region, (" <span style='color:gray'>Seen: %s.</span>" % ", ".join(seen)) if seen else ""))
