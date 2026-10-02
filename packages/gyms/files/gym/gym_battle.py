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
from .gym_data import get_gym, next_gym
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
    return out


# ---------------------------------------------------------------- player ---
def _obj_from_saved(rec) -> Optional[PokemonObject]:
    """Rebuild a PokemonObject from a saved captured_pokemon record."""
    try:
        name = rec.get("name", "?")
        sid = int(rec.get("id") or search_pokedex(name.lower(), "species_id") or 0)
        base = rec.get("base_stats") or rec.get("stats") or {}
        types = rec.get("type") or search_pokedex(name.lower(), "types") or ["Normal"]
        atks = rec.get("attacks") or rec.get("moves") or ["Tackle"]
        p = PokemonObject(
            name=_dn(name), id=sid, shiny=bool(rec.get("shiny", False)),
            level=_capped(int(rec.get("level", 5))), ability=rec.get("ability", "None"),
            type=types, base_stats=base, attacks=list(atks),
            base_experience=rec.get("base_experience", 60),
            growth_rate=rec.get("growth_rate", "medium"),
            ev=rec.get("ev", dict(ZERO_EV)), iv=rec.get("iv", dict(DEFAULT_IV)),
            gender=rec.get("gender", "M"), battle_status="fighting",
            xp=int(rec.get("xp", 0)), position=(5, 5),
            tier=rec.get("tier", "Normal"),
            captured_date=rec.get("captured_date"),
            individual_id=rec.get("individual_id") or str(uuid.uuid4()),
        )
        # ALWAYS FULL HP at gym start. The saved record's current_hp is
        # ignored on purpose: you picked this Pokemon for a gym run, you
        # should not have to think about leftover damage from wild battles.
        mx = int(p.calculate_max_hp())
        p.max_hp, p.hp, p.current_hp = mx, mx, mx
        return p
    except Exception as e:
        _log("error", "could not rebuild saved Pokémon: %s" % e)
        return None


def _capped(level: int) -> int:
    """Region level cap: anything above it fights at the cap (the saved
    Pokémon keeps its real level - fights use copies)."""
    try:
        from .gym_ui import current_cap
        cap = current_cap()
        return min(level, cap) if cap else level
    except Exception:
        return level


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


def build_player_team(selected: List[dict]) -> List[Combatant]:
    """Deep-copies deliberately: damage must never touch the saved Pokémon.
    Discarding these on exit IS the heal."""
    out = []
    for rec in selected[:TEAM_SIZE]:
        p = _obj_from_saved(copy.deepcopy(rec))
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


def _engine(session: GymSession):
    """The fight's single engine State, built on the first turn."""
    if session.engine is None:
        session.engine = GE.EngineBattle(session.player_team, session.leader_team,
                                         leader_label=session.gym.leader)
    return session.engine


def run_turn(session: GymSession, forced_move: Optional[str] = None):
    """Resolve one gym turn. Returns a list of battle-log lines.

    forced_move: the move the player chose in the gym window (manual mode).
    None means auto-battle: we press the move with the highest expected damage
    right now (type matchups, stats and boosts included).
    """
    if session.finished:
        return []
    if isinstance(session.engine, GS.ShowdownBattle):
        return _showdown_turn(session, session.engine, forced_move)
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

    p.spend_pp(p_move)
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


def _showdown_turn(session: GymSession, sd, forced_move):
    """One turn on Pokémon Showdown's simulator. Showdown owns HP, status, PP,
    locked moves (Petal Dance, Outrage...) and faint replacement; the log it
    returns is already readable ("Your Growlithe used Flame Wheel!")."""
    p = session.player_active
    if p is None or session.leader_active is None:
        return []
    move = forced_move if (forced_move and p.pp_left(forced_move) > 0) else None
    try:
        from .gym_config import leader_smart_moves
        smart = leader_smart_moves()
    except Exception:
        smart = True
    try:
        lines = sd.play_turn(move, smart=smart)
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
                           leader_label=session.gym.leader)


# --------------------------------------------------------------- rewards ---
def award_victory(session: GymSession):
    """Badge, cash and XP — written to the real saved Pokémon, not the copies."""
    gym = session.gym
    notes = []
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
    notes.append("You earned the %s!" % gym.badge_name)

    # Boss loot: two draws from the normal item pool (TMs included).
    try:
        from ..utils import random_item
        got = [_item_label(random_item()) for _ in range(2)]
        notes.append("Loot: %s." % " and ".join(got))
    except Exception as e:
        _log("warning", "loot failed: %s" % e)
    return notes


def _item_label(name) -> str:
    """random_item() returns the item name, or a TM's type sprite for a TM."""
    s = str(name or "item")
    if s.startswith("Bag_TM_"):
        return "a %s-type TM" % s.split("_")[2].capitalize()
    return s.replace("-", " ").title()


def finish_session(session: GymSession, progress: GymProgress, review_count: int):
    """Close out a gym. Leaving discards the damaged copies, which is the heal."""
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
