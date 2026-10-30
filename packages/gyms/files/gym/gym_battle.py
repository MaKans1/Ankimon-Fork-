"""
gym_battle.py — the bridge between GymSession and Ankimon / poke-engine.

Everything Anki-specific lives here. gym_state.py stays importable standalone.

TURN MODEL
    A gym is NOT advanced by answering cards. Reviewing only *offers* the gym;
    the fight itself is played in gym_window.GymBattleWindow, where a turn
    happens because the player acted (manual) or the auto-timer ticked. A gym
    is meant to be a break from reviewing, not a second thing riding on it.

AUTO vs MANUAL
    The gym window owns move selection: four attack buttons plus keys 1-4 in
    manual mode, or a self-advancing timer in auto. The default comes from the
    "Gym Auto-Battle By Default" setting and can be flipped mid-fight.
"""

import copy
import random
import uuid
from datetime import date
from typing import List, Optional

from aqt import mw

from ..pyobj.pokemon_obj import PokemonObject
from ..functions.pokedex_functions import (
    search_pokedex, get_growth_rate, get_base_experience, get_effort_values,
    find_details_move,
)
from ..functions.learnset_retrieval import get_random_moves_for_pokemon
from ..singletons import settings_obj, logger
from .gym_state import (
    Combatant, GymSession, GymProgress, TEAM_SIZE, RETRY_COST_REVIEWS,
    STRUGGLE,
)
from .gym_data import get_gym, next_gym, GYM
from . import gym_engine as GE          # also applies the global move fixes
from . import gym_showdown as GS        # real-game rules via Pokemon Showdown

DEFAULT_IV = {"hp": 15, "atk": 15, "def": 15, "spa": 15, "spd": 15, "spe": 15}
ZERO_EV = {"hp": 0, "atk": 0, "def": 0, "spa": 0, "spd": 0, "spe": 0}


def _log(level, msg):
    try:
        logger.log(level, "[gym] %s" % msg)
    except Exception:
        print("[gym] %s" % msg)


# ---------------------------------------------------------------- leader ---
def build_leader_pokemon(mon) -> Optional[PokemonObject]:
    """Turn a GymMon (species + level) into a real PokemonObject.

    Base stats, types, ability and growth rate come from the addon's own
    pokedex data, so a gym Pokémon is statistically identical to a wild one of
    the same species and level. Only the level is scripted.
    """
    try:
        name = mon.species
        # pokedex.json keys the dex number as "species_id" (with "actual_id"
        # for alternate formes). There is no "num" key — asking for one
        # returned [] and silently skipped every gym Pokemon.
        species_id = search_pokedex(name.lower(), "species_id")
        actual_id = search_pokedex(name.lower(), "actual_id") or species_id
        if not species_id:
            _log("error", "unknown species %r — skipping" % name)
            return None

        stats = search_pokedex(name.lower(), "baseStats") or {}
        types = search_pokedex(name.lower(), "types") or ["Normal"]
        abilities = search_pokedex(name.lower(), "abilities") or {}
        ability = (abilities.get("0") if isinstance(abilities, dict)
                   else (abilities[0] if abilities else "None")) or "None"

        # Gym Moveset setting: Original (exact Red/Blue) or Modernized (default)
        try:
            from .gym_config import original_movesets
            use_rb = original_movesets() and bool(getattr(mon, "rb_moves", None))
        except Exception:
            use_rb = False
        moves = (mon.rb_moves if use_rb else mon.moves) or             get_random_moves_for_pokemon(name.lower(), mon.level)
        if not moves:
            moves = ["Tackle"]

        base_stats = {
            "hp": stats.get("hp", 50), "atk": stats.get("atk", 50),
            "def": stats.get("def", 50), "spa": stats.get("spa", 50),
            "spd": stats.get("spd", 50), "spe": stats.get("spe", 50),
            "xp": 0,
        }

        p = PokemonObject(
            name=_dn(name), id=int(actual_id), shiny=False,
            level=int(mon.level), ability=ability, type=types,
            base_stats=base_stats, attacks=list(moves),
            # growth rate is keyed on species_id, base experience on actual_id
            base_experience=get_base_experience(int(actual_id)) or 60,
            growth_rate=get_growth_rate(int(species_id)) or "medium",
            ev=dict(ZERO_EV), iv=dict(DEFAULT_IV),
            # lowercase: the engine reads "Fighting" as an existing status and
            # then refuses every status move against this Pokemon
            gender=random.choice(["M", "F"]), battle_status="fighting", xp=0,
            position=(5, 5), tier="Normal", captured_date=None,
            individual_id=str(uuid.uuid4()),
        )
        mx = int(p.calculate_max_hp())
        p.max_hp, p.hp, p.current_hp = mx, mx, mx
        return p
    except Exception as e:
        _log("error", "failed building %s: %s" % (mon.species, e))
        return None


# Kalos/Hoenn rematches once that region's Elite Four is beaten: the leader has a Mega of
# its own (functions/mega.py, user 2026-10-28). These leaders' rosters have no Pokemon that
# can Mega Evolve (Brawly's and Ramos's only in their early versions), so a type-matched one
# leads instead.
LEADER_MEGA_FALLBACK = {301: "Aerodactyl", 302: "Medicham", 303: "Manectric", 304: "Camerupt",
                        305: "Kangaskhan", 307: "Alakazam", 308: "Gyarados", 602: "Aerodactyl",
                        604: "Victreebel", 605: "Ampharos", 607: "Alakazam"}


def _leader_mega(gym, out):
    region = str(getattr(gym, "region", "") or "")
    if not (out and getattr(gym, "is_rematch", False) and region in ("Kalos", "Hoenn")):
        return
    from . import gym_data
    from .gym_ui import progress
    from ..functions import mega as _mega
    elite = [g.gym_id for g in gym_data.ladder(region) if g.kind == gym_data.ELITE4]
    if not elite or not set(elite) <= set(progress().defeated_ids()):
        return
    forms = {st["species"]: st["form"] for item, st in _mega.stones().items() if item != _mega.DRAGON_KEY}
    pick = next((c for c in reversed(out) if c.species_id in forms), None)
    if pick is None:
        name = LEADER_MEGA_FALLBACK.get(int(getattr(gym, "gym_id", 0) or 0))
        p = build_leader_pokemon(gym_data.GymMon(name, int(out[-1].level))) if name else None
        if p is None or int(p.id) not in forms:
            return
        pp = build_pp(p.attacks)
        out[0] = Combatant(name=p.name, level=p.level, max_hp=int(p.max_hp), hp=int(p.max_hp),
                           attacks=list(p.attacks), species_id=p.id, is_player=False, source=p,
                           pp=dict(pp), max_pp=dict(pp))
        pick = out[0]
    pick.mega_form = pick.source.mega_form = forms[pick.species_id]   # gym_showdown gives it the stone


def build_leader_team(gym) -> List[Combatant]:
    out = []
    for mon in gym.team:
        p = build_leader_pokemon(mon)
        if p is None:
            continue
        pp = build_pp(p.attacks)
        out.append(Combatant(
            name=p.name, level=p.level, max_hp=int(p.max_hp), hp=int(p.max_hp),
            attacks=list(p.attacks), species_id=p.id, is_player=False, source=p,
            pp=dict(pp), max_pp=dict(pp)))
    if getattr(gym, "totem", None) and out:
        out[0].name = "Totem %s" % out[0].name      # Alola: the totem leads; gymsim/gym_engine key on it
    if getattr(gym, "dynamax", "") == "gmax" and out:
        out[-1].gigantamax = True                   # Galar: the ace Gigantamaxes (gym_showdown passes it)
    if getattr(gym, "tera_rolled", "") and out:
        out[-1].tera_type = gym.tera_rolled         # Paldea: the ace's Tera type, rolled for this fight
    try:
        _leader_mega(gym, out)
    except Exception as e:
        _log("warning", "leader Mega failed: %s" % e)
    return out


# ---------------------------------------------------------------- player ---
def _obj_from_saved(rec, cap=None) -> Optional[PokemonObject]:
    """Rebuild a PokemonObject from a saved captured_pokemon record."""
    try:
        name = rec.get("name", "?")
        sid = int(rec.get("id") or search_pokedex(name.lower(), "species_id") or 0)
        base = rec.get("base_stats") or rec.get("stats") or {}
        types = rec.get("type") or search_pokedex(name.lower(), "types") or ["Normal"]
        atks = rec.get("attacks") or rec.get("moves") or ["Tackle"]
        p = PokemonObject(
            name=_dn(name), id=sid, shiny=bool(rec.get("shiny", False)),
            level=_capped(int(rec.get("level", 5)), cap), ability=rec.get("ability", "None"),
            type=types, base_stats=base, attacks=list(atks),
            base_experience=rec.get("base_experience", 60),
            growth_rate=rec.get("growth_rate", "medium"),
            ev=rec.get("ev", dict(ZERO_EV)), iv=rec.get("iv", dict(DEFAULT_IV)),
            gender=rec.get("gender", "M"), battle_status="fighting",
            xp=int(rec.get("xp", 0)), position=(5, 5),
            tier=rec.get("tier", "Normal"),
            captured_date=rec.get("captured_date"),
            individual_id=rec.get("individual_id") or str(uuid.uuid4()),
            # the held item goes into the fight (Showdown applies it; a
            # Z-Crystal is what makes a Z-Move possible)
            held_item=rec.get("held_item") or None,
        )
        # ALWAYS FULL HP at gym start. The saved record's current_hp is
        # ignored on purpose: you picked this Pokemon for a gym run, you
        # should not have to think about leftover damage from wild battles.
        mx = int(p.calculate_max_hp())
        p.max_hp, p.hp, p.current_hp = mx, mx, mx
        # Fighting below its real level: moves it couldn't have at that level are
        # sealed for this fight (functions/move_seal.py); all sealed -> its best
        # level-up moves for that level
        p.sealed_moves = {}
        real = int(rec.get("level", 5) or 5)
        if int(p.level) < real:
            try:
                from ..functions import move_seal
                moves = list(p.attacks)
                try:                # scaling in effect in this region: its scaled moveset
                    from ..wild import wild_rules as _w
                    wcap = _w.level_cap()
                    if wcap and real > wcap and not rec.get("_picked_moves"):   # autopick chose for this level
                        moves = move_seal.scaled_moves(rec, _w.region(), wcap)[0]
                except ImportError:
                    pass
                usable, sealed = move_seal.seal(name, moves, int(p.level), real)
                p.attacks = usable or move_seal.fallback(name, int(p.level))
                p.sealed_moves = sealed
            except Exception as e:
                _log("warning", "move seal skipped: %s" % e)
        return p
    except Exception as e:
        _log("error", "could not rebuild saved Pokémon: %s" % e)
        return None


def _capped(level: int, cap=None) -> int:
    """Anything above the cap fights at the cap - never raised to it (the saved
    Pokémon keeps its real level - fights use copies). cap: the boss's level
    (boss_level); without one, the region's level cap."""
    try:
        if not cap:
            from .gym_ui import current_cap
            cap = current_cap()
        return min(level, cap) if cap else level
    except Exception:
        return level


def caps_on() -> bool:
    """Level caps / locks apply where you are: 3+ badges in another region
    (gym_data.caps_apply, user 2026-10-27). Unknown -> the old behaviour (on)."""
    try:
        from .gym_ui import progress
        from .gym_data import caps_apply, current_region
        return caps_apply(progress().defeated_ids(), current_region())
    except Exception:
        return True


def boss_level(gym):
    """Gyms, the Elite Four, Champions, wild legendaries and expeditions: your
    Pokémon above the opponent's strongest level fight at it (user 2026-10-22).
    None if the team is unknown, or while caps don't apply (caps_on)."""
    if not caps_on():
        return None
    try:
        lv = max(int(m.level) for m in (getattr(gym, "team", None) or []))
        return lv if lv > 0 else None
    except Exception:
        return None


def available_party() -> List[dict]:
    """The player's 6-slot team as FULL saved records. Source for the 3-pick.

    get_team() returns only [{"individual_id": ...}] — the slot mapping, not
    the Pokémon. The real record lives obfuscated in captured_pokemon.data and
    must be resolved via get_pokemon(), which deobfuscates it. Passing the raw
    slot stubs to the UI is what rendered every row as "? Lv ?".
    """
    out: List[dict] = []
    try:
        slots = mw.ankimon_db.get_team() or []
    except Exception as e:
        _log("error", "could not read team: %s" % e)
        slots = []

    for slot in slots:
        if not isinstance(slot, dict):
            continue
        # Some versions may already hand back a full record; use it as-is.
        if slot.get("name"):
            out.append(slot)
            continue
        iid = slot.get("individual_id")
        if not iid:
            continue
        try:
            rec = mw.ankimon_db.get_pokemon(iid)
        except Exception as e:
            _log("warning", "could not resolve %s: %s" % (iid, e))
            rec = None
        if rec:
            rec.setdefault("individual_id", iid)
            out.append(rec)

    # Empty or unusable team slots would leave nothing to pick, so fall back
    # to the full collection rather than silently showing an empty list.
    if not out:
        try:
            out = [p for p in (mw.ankimon_db.get_all_pokemon() or []) if p]
            if out:
                _log("info", "team empty — offering all %d caught Pokémon" % len(out))
        except Exception as e:
            _log("error", "could not read collection: %s" % e)
    return out


def build_player_team(selected: List[dict], cap=None) -> List[Combatant]:
    """Deep-copies deliberately: damage must never touch the saved Pokémon.
    Discarding these on exit IS the heal. cap: the boss's level (boss_level)."""
    out = []
    for rec in selected[:TEAM_SIZE]:
        p = _obj_from_saved(copy.deepcopy(rec), cap)
        if p is None:
            continue
        pp = build_pp(p.attacks)
        out.append(Combatant(
            name=p.name, level=p.level, max_hp=int(p.max_hp), hp=int(p.max_hp),
            attacks=list(p.attacks), species_id=p.id,
            individual_id=p.individual_id, is_player=True, source=p,
            pp=dict(pp), max_pp=dict(pp)))
    return out


# ------------------------------------------------------------------ turn ---
def build_pp(attacks) -> dict:
    """Base PP per move from moves.json (all 952 moves carry a `pp` field).

    Gen 1 base PP, no PP Ups — poke-engine's `pp * 1.6` is the Showdown
    max-with-PP-Ups convention and is deliberately not used here.
    """
    out = {}
    for mv in attacks or []:
        try:
            d = find_details_move(mv) or {}
            out[mv] = int(d.get("pp") or 0) or 10
        except Exception:
            out[mv] = 10
    return out


def _leader_move(session: GymSession, leader, player):
    """Leaders are bound by PP exactly as the player is.

    Smart leaders (setting on) plan: every turn they read the live battle and
    play each of their moves a few turns forward - so they use Dragon Dance,
    Reflect or Thunder Wave when it pays and attack when it does not. Gym
    difficulty is tuned for this. Off: random, like wild Pokémon."""
    if not leader.attacks:
        return "Splash"
    usable = leader.usable_moves()
    if not usable:
        return STRUGGLE
    try:
        from .gym_config import leader_smart_moves
        if leader_smart_moves():
            return session.engine.leader_plan(leader, player)
    except Exception as e:
        _log("warning", "leader planning failed, picking at random: %s" % e)
    return random.choice(usable)


# Battle HP (user 2026-10-15): gym-style fights (gyms, rematches, the Elite Four,
# expeditions, legendaries, totems, Titans) run at x2 HP for both sides, so a
# single move rarely knocks anything out within 5 levels - one-shots drop from
# ~13% of matchups to ~1-2% (balance_sim/hp_inflation.py). Saved HP is untouched:
# the engines scale it up and read it back down. Wild battles are unchanged.
HP_MULT = 2.0

# Hidden boss guard (user 2026-10-15): wild legendaries, totems and Titans take
# 25% less damage. Never shown; battle-only, so a caught Pokemon doesn't keep it.
BOSS_GUARD = 0.75


def guard_for(gym):
    """The boss's damage multiplier for this fight, or None."""
    if getattr(gym, "guard", None):
        return float(gym.guard)
    if getattr(gym, "is_rematch", False):
        return None
    if getattr(gym, "is_legend", False) or getattr(gym, "totem", None) or getattr(gym, "titan", None):
        return BOSS_GUARD
    return None


# Leaders who switch (user 2026-10-27): the Elite Four, Champions and every
# rematch, at most 3 times a battle with at least 5 of their moves between two,
# and only when it's clearly their best play (gymsim.js aiSwitch). Gym leaders
# the first time round, totems, Titans, legendaries and expeditions never do.
AI_SWITCH = {"max": 3, "gap": 5}


def ai_switch_for(gym):
    """The leader's switching rules for this fight, or None (never switches)."""
    if getattr(gym, "is_legend", False) or getattr(gym, "totem", None) or getattr(gym, "titan", None):
        return None
    if getattr(gym, "is_rematch", False) or getattr(gym, "is_elite", False):
        return dict(AI_SWITCH)
    return None


def _engine(session: GymSession):
    """The fight's single engine State, built on the first turn."""
    if session.engine is None:
        session.engine = GE.EngineBattle(session.player_team, session.leader_team,
                                         leader_label=session.gym.leader,
                                         totem=getattr(session.gym, "totem", None),
                                         titan=getattr(session.gym, "titan", None),
                                         guard=guard_for(session.gym), hp_mult=HP_MULT)
    return session.engine


def run_turn(session: GymSession, forced_move: Optional[str] = None, z=None, dmax=None, tera=None,
             switch_to=None):
    """Resolve one gym turn. Returns a list of battle-log lines.

    forced_move: the move the player chose in the gym window (manual mode).
    None means auto-battle: we press the move with the highest expected damage
    right now (type matchups, stats and boosts included).
    switch_to: a teammate (Combatant) to switch to instead - uses the turn.
    Showdown engine only; the classic engine has no switching.
    """
    if session.finished:
        return []
    if isinstance(session.engine, GS.ShowdownBattle):
        return _showdown_turn(session, session.engine, forced_move, z, dmax, tera, switch_to)
    try:
        eng = _engine(session)
    except Exception as e:
        _log("error", "could not start the gym engine: %s" % e)
        return []
    p, l = session.player_active, session.leader_active
    if p is None or l is None:
        return []

    # --- move selection under PP -------------------------------------
    try:
        if forced_move and p.pp_left(forced_move) > 0:
            p_move = forced_move
        elif p.must_struggle():
            p_move = STRUGGLE
        elif p.usable_moves():
            p_move = eng.best_attack(p, "user")
        else:
            p_move = "Splash"           # no moves at all (shouldn't happen)
        l_move = _leader_move(session, l, p)
    except Exception as e:
        _log("error", "move choice failed: %s" % e)
        return []

    withdraw = eng.totem_withdrawal() if hasattr(eng, "totem_withdrawal") else None
    p.spend_pp(p_move)
    if withdraw:                        # the totem calls for help instead of attacking
        header = "%s used %s." % (p.name, str(p_move).replace("-", " ").title())
    else:
        l.spend_pp(l_move)
        header = "%s used %s. %s used %s." % (
            p.name, str(p_move).replace("-", " ").title(),
            l.name, str(l_move).replace("-", " ").title())
    try:
        lines = eng.turn(p_move, l_move)
    except Exception as e:
        _log("error", "engine failed this turn: %s" % e)
        try:
            lines = eng.repair()        # damage may have landed: bring in the next Pokemon
        except Exception as e2:
            _log("error", "gym repair failed: %s" % e2)
            lines = []
    return [header] + session.record_turn(lines)


def _showdown_turn(session: GymSession, sd, forced_move, z=None, dmax=None, tera=None, switch_to=None):
    """One turn on Pokémon Showdown's simulator. Showdown owns HP, status, PP,
    locked moves (Petal Dance, Outrage...) and faint replacement; the log it
    returns is already readable ("Your Growlithe used Flame Wheel!")."""
    p = session.player_active
    if p is None or session.leader_active is None:
        return []
    move = forced_move if (forced_move and p.pp_left(forced_move) > 0) else None
    if switch_to is not None:
        move = None
    try:
        from .gym_config import leader_smart_moves
        smart = leader_smart_moves()
    except Exception:
        smart = True
    try:
        lines = sd.play_turn(move, smart=smart, z=z, dmax=dmax, tera=tera, switch_to=switch_to)
    except Exception as e:
        _log("error", "Showdown engine failed; continuing this fight on the classic engine: %s" % e)
        session.engine = _classic_from_current(session, sd)
        return (["(Battle engine hiccup - continuing on the classic engine.)"]
                + run_turn(session, forced_move))
    return session.record_turn(lines)


def _classic_from_current(session: GymSession, sd):
    """Fallback mid-fight: rebuild the classic engine from the current HP,
    with each side's active Pokemon first (statuses/boosts are not carried)."""
    p_act, l_act = sd.active("user"), sd.active("opponent")
    for c in list(session.player_team) + list(session.leader_team):
        c._tags = []                      # Showdown-only tags; classic shows status only
    try:
        sd.close()
    except Exception:
        pass

    def order(team, act):
        alive = [c for c in team if c.hp > 0]
        return ([act] if act in alive else []) + [c for c in alive if c is not act]             + [c for c in team if c.hp <= 0]
    return GE.EngineBattle(order(session.player_team, p_act), order(session.leader_team, l_act),
                           leader_label=session.gym.leader,
                          totem=getattr(session.gym, "totem", None),
                                         titan=getattr(session.gym, "titan", None),
                                         guard=guard_for(session.gym), hp_mult=HP_MULT)


# --------------------------------------------------------------- rewards ---
# Z items in the post-battle recap: the Z-Move gold (gym_window's Z button).
# Notes are plain text; zspan() marks a stretch that notes_html() turns gold.
Z_GOLD = "#f4b400"
_Z_OPEN, _Z_CLOSE = "[[z]]", "[[/z]]"


def zspan(text: str) -> str:
    return "%s✦ %s%s" % (_Z_OPEN, text, _Z_CLOSE)


# Galar / Paldea / Titan rewards get their own colours in the recap
_COLOURS = {"d": "#a855f7", "t": "#22d3ee", "h": "#4ade80", "s": "#22d3ee"}


def dspan(text: str) -> str:           # Dynamax (purple)
    return "[[d]]◆ %s[[/d]]" % text


def tspan(text: str) -> str:           # Tera (cyan)
    return "[[t]]◈ %s[[/t]]" % text


def sspan(text: str) -> str:           # Tera Shards (light blue)
    return "[[s]]◈ %s[[/s]]" % text


def hspan(text: str) -> str:           # Herba Mystica (green)
    return "[[h]]✿ %s[[/h]]" % text


def notes_html(lines) -> str:
    """The recap lines as rich text: escaped, one per line, Z items in gold."""
    import html
    out = []
    for line in lines:
        s = html.escape(str(line))
        s = s.replace(_Z_OPEN, '<span style="color:%s; font-weight:bold;">' % Z_GOLD)
        s = s.replace(_Z_CLOSE, "</span>")
        for k, colour in _COLOURS.items():
            s = s.replace("[[%s]]" % k, '<span style="color:%s; font-weight:bold;">' % colour)
            s = s.replace("[[/%s]]" % k, "</span>")
        out.append(s)
    return "<br>".join(out)


def _item_name(item) -> str:
    try:
        from ..utils import item_display_name
        return item_display_name(item)
    except Exception:
        return str(item).replace("-", " ").title()


def award_victory(session: GymSession):
    """Badge, cash and XP — written to the real saved Pokémon, not the copies."""
    gym = session.gym
    notes, z_loot = [], []
    try:
        cash = int(settings_obj.get("trainer.cash") or 0)
        settings_obj.set("trainer.cash", cash + gym.cash_reward)
        notes.append("Earned $%d." % gym.cash_reward)
    except Exception as e:
        _log("warning", "cash award failed: %s" % e)

    # XP goes only to the Pokemon that were still standing.
    survivors = [c for c in session.player_team if not c.fainted]
    xp_each = max(1, int(sum(m.level for m in gym.team) * 4 / max(1, len(survivors))))
    for c in survivors:
        try:
            rec = mw.ankimon_db.get_pokemon(c.individual_id)
            if rec:
                rec["xp"] = int(rec.get("xp", 0)) + xp_each
                mw.ankimon_db.save_pokemon(rec)
        except Exception as e:
            _log("warning", "xp award failed for %s: %s" % (c.name, e))
    if survivors:
        notes.append("%d XP to each surviving Pokémon." % xp_each)
    if getattr(gym, "is_rematch", False):
        notes.append("Rematch won against %s (Lv %d)!" % (gym.leader, int(getattr(gym, "rematch_level", 0) or 0)))
    else:
        if getattr(gym, "is_test", False):
            notes.append("Test fight: no badge or ladder progress recorded.")
        elif getattr(gym, "titan", None):
            notes.append("You beat the %s!" % gym.name)      # Titans give no badge
        else:
            notes.append("You earned the %s!" % gym.badge_name)
        if getattr(gym, "z_crystal", ""):       # Alola: the Z-Crystal goes in the bag
            try:
                from ..utils import give_item
                give_item(gym.z_crystal)
                z_loot.append(zspan(_item_name(gym.z_crystal)))    # leads the Loot line, in gold
            except Exception as e:
                _log("warning", "Z-Crystal failed: %s" % e)
        if getattr(gym, "totem", None):         # your first totem trial: the Z-Ring
            try:
                from . import zmoves
                if not zmoves.has_ring():
                    from ..utils import give_item
                    give_item(zmoves.Z_RING)
                    notes.append("You received the %s! A Pokémon holding a Z-Crystal can now "
                                 "use its Z-Move once per battle in Alola's gyms and battles "
                                 "(Give to hold, in the bag)."
                                 % zspan("Z-Ring"))
            except Exception as e:
                _log("warning", "Z-Ring failed: %s" % e)
        region = str(getattr(gym, "region", "") or "")
        if region == "Galar" and getattr(gym, "kind", "") == GYM:    # your first Galar gym: the Dynamax Band
            try:
                from . import dmax as _dm
                if not _dm.has_band():
                    from ..utils import give_item
                    give_item(_dm.DYNAMAX_BAND)
                    notes.append("You received the %s! Your Pokémon can now Dynamax once per battle in "
                                 "Galar's gyms and battles." % dspan("Dynamax Band"))
            except Exception as e:
                _log("warning", "Dynamax Band failed: %s" % e)
        if region == "Galar":                                     # Kubfu joins after Milo
            try:
                from . import galar as _gl
                n = _gl.kubfu_gift(gym)
                if n:
                    notes.append(n)
            except Exception as e:
                _log("warning", "Kubfu failed: %s" % e)
        if region == "Paldea" and getattr(gym, "kind", "") == GYM:   # your first Paldea gym: the Tera Orb
            try:
                from . import tera as _tr
                if not _tr.has_orb():
                    from ..utils import give_item
                    give_item(_tr.TERA_ORB)
                    notes.append("You received the %s! Your Pokémon can now Terastallize once per battle "
                                 "in Paldea's gyms and battles." % tspan("Tera Orb"))
            except Exception as e:
                _log("warning", "Tera Orb failed: %s" % e)
        if getattr(gym, "tera_rolled", ""):         # the Tera Shard their ace used against you
            try:
                from . import tera as _tr
                from ..utils import give_item
                give_item(_tr.shard_item(gym.tera_rolled))
                z_loot.append(sspan(_tr.shard_name(gym.tera_rolled)))
            except Exception as e:
                _log("warning", "Tera Shard failed: %s" % e)
        if getattr(gym, "titan", None):             # a Titan: Herba Mystica
            try:
                from ..utils import give_item
                give_item("herba-mystica")
                z_loot.append(hspan("Herba Mystica"))
            except Exception as e:
                _log("warning", "Herba Mystica failed: %s" % e)

    # Daily Megas (functions/mega.py): the Mega Bracelet + a starter pick (Korrina / Norman,
    # or the next gym there), Kalos/Hoenn rematch stones after the Elite Four, Champion stones.
    try:
        from .gym_ui import progress
        from ..functions import mega as _mega
        m_notes, m_loot = _mega.gym_rewards(gym, progress().defeated_ids())
        notes.extend(m_notes)
        z_loot.extend(m_loot)
    except Exception as e:
        _log("warning", "Mega rewards failed: %s" % e)

    # Boss loot: from this leader's themed pool (gym/rewards.py: type TMs,
    # power item, stone, healing); the normal item pool only if there's none.
    got = []
    try:
        from . import rewards
        got = rewards.draw(gym.gym_id, version=int(getattr(gym, "rematch_version", 0) or 0),
                           draws=int(getattr(gym, "loot_draws", 2) or 2))
        if not got:
            from ..utils import random_item
            got = [_item_label(random_item()) for _ in range(2)]
    except Exception as e:
        _log("warning", "loot failed: %s" % e)
    if z_loot or got:
        notes.append("Loot: %s." % ", ".join(z_loot + list(got)))
    return notes


def _item_label(name) -> str:
    """random_item() returns the item name, or a TM's type sprite for a TM."""
    try:
        from ..utils import item_display_name
        return item_display_name(name)
    except Exception:
        pass
    s = str(name or "item")
    if s.startswith("Bag_TM_"):
        return "a %s-type TM" % s.split("_")[2].capitalize()
    return s.replace("-", " ").title()


def finish_session(session: GymSession, progress: GymProgress, review_count: int):
    """Close out a gym. Leaving discards the damaged copies, which is the heal."""
    notes = _finish_session(session, progress, review_count)
    _log_fight(session)
    return notes


def _log_fight(session):
    """The fight's turn-by-turn log in app.log, after its summary line (user 2026-10-29:
    the battle window was the only copy, so a report about a fight couldn't be checked)."""
    try:
        team = lambda cs: ", ".join("%s Lv %s" % (c.name, getattr(c, "level", "?")) for c in cs)
        _log("info", "\n".join(["fight log - you: %s | %s: %s" % (
            team(session.player_team), session.gym.leader, team(session.leader_team))]
            + ["    %s" % line for line in (session.events or [])]))
    except Exception:
        pass


def _finish_session(session: GymSession, progress: GymProgress, review_count: int):
    if getattr(session.gym, "is_legend", False):
        # roaming legendaries / mythicals (legends.py): catch or flee, no progress
        from . import legends
        notes = legends.finish(session)
        _log("info", session.summary())
        return notes
    if getattr(session.gym, "is_test", False):
        # a test fight (Game > Test): the real battle and rewards, but no
        # badge, ladder progress or cooldown
        notes = (award_victory(session) if session.status == GymSession.WON
                 else ["Your team is healed. Test fight: nothing was recorded."])
        _log("info", session.summary())
        return notes
    if getattr(session.gym, "is_rematch", False):
        # rematches never touch badges or gym progress
        notes = (award_victory(session) if session.status == GymSession.WON
                 else ["Your team is healed. Your next rematch comes with your next gym interval."])
        _log("info", session.summary())
        return notes
    if session.status == GymSession.WON:
        progress.record_win(session.gym.gym_id, review_count, str(date.today()))
        notes = award_victory(session)
    else:
        progress.record_attempt(session.gym.gym_id, review_count)
        try:
            from .gym_config import retry_cost
            rc = retry_cost()
        except Exception:
            rc = RETRY_COST_REVIEWS
        notes = ["Your team is healed. Review %d more cards here to try again." % rc]
        # Classic Elite Four: beat them all in one go - a loss ends the run, and
        # the members you beat on the way have to be beaten again
        try:
            from .gym_config import elite_four_classic
            if session.gym.is_elite and elite_four_classic():
                from .gym_data import ladder
                run = [g for g in ladder(getattr(session.gym, "region", None)) if g.is_elite]
                done = progress.defeated_ids()
                beaten = [g.gym_id for g in run if g.gym_id in done]
                if run and beaten:
                    progress.reset_wins(beaten)
                    progress.record_attempt(run[0].gym_id, review_count)     # the retry wait starts there
                    notes.append("Classic Elite Four: the run is over. Next time you start again from %s."
                                 % run[0].leader)
        except Exception as e:
            _log("warning", "Elite Four reset failed: %s" % e)
    _log("info", session.summary())
    return notes


def _dn(n):
    """Real Pokémon name for display ("Iron Hands", "Mr. Mime")."""
    try:
        from ..functions.pokedex_functions import display_name
        return display_name(n)
    except Exception:
        s = str(n or "")
        return s[:1].upper() + s[1:]
