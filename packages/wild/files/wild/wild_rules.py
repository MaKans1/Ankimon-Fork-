"""
wild_rules.py - wild-mode exploration rules.

REGIONS (TRAVEL)
    Ankimon -> Game -> Travel. You are always in exactly one region; only its
    Pokemon appear in the wild (Kanto = #1-151 ...). Each region has its own
    gym ladder, badges, wild levels and level cap.

LEVELS
    With "Wild Levels Follow Badges" on (and the gym ladder enabled), wild
    levels follow your badges like the routes in Red/Blue. About 1 in 10 is a
    strong one, up to 10 levels above the band. Off = classic Ankimon
    (your Pokemon's level +-3).

MOVES
    Both sides pick moves with wild_ai (buff / debuff / status / attack).
    Your Pokemon only uses the moves ticked in its wild menu.

TEAM ROTATION
    Your buddy always leads. When the Pokemon in front faints, the next team
    member (team slots 1-6) comes in at full HP against the SAME wild
    Pokemon, which keeps its damage, boosts and status. If the whole team
    faints you hurry away (counts as fleeing) and a new wild Pokemon appears.
    When an encounter ends (win, catch, flee, whiteout) everyone is healed
    and your buddy is back in front.

EXP
    The Pokemon that lands the final blow gets 50% of the EXP; the other 50%
    is split evenly between everyone else that fought. Alone = 100%.

POPUPS
    Every wild-battle popup has its own setting (Battle > Wild Battle
    Popups), all off by default. popup(kind) is the single gate.

FLEEING
    Free, and brings a new wild Pokemon.

HIDDEN RULES (deliberately not shown in the UI)
    survive rule   your Pokemon at full HP survives any single hit with 1 HP
                   (the Sturdy effect, wild battles only)
    heal budget    a wild Pokemon regains at most 50% of its max HP per
                   encounter, so drain / recovery can't stall forever
    repeat limit   a support move is used at most twice per life (wild_ai)
    flee block     the encounter that replaces one you fled from is never shiny
"""
import json
import math
import random
import re
import sys

from ..poke_engine.data import all_move_json
from ..poke_engine.helpers import normalize_name
from ..poke_engine.damage_calculator import type_effectiveness_modifier
from . import wild_ai

# Travel model: you are always in exactly one region (no "all regions" mode).
REGIONS = ["Kanto", "Johto", "Hoenn", "Sinnoh", "Unova", "Kalos", "Alola", "Galar", "Paldea"]
REGION_GEN = {name: i + 1 for i, name in enumerate(REGIONS)}
HOME_REGION = "Kanto"
GEN_MAX = {1: 151, 2: 251, 3: 386, 4: 493, 5: 649, 6: 721, 7: 809, 8: 905, 9: 1025}

# Red/Blue-style route levels by badges earned (9 = champion beaten)
RB_BANDS = {0: (2, 7), 1: (5, 14), 2: (8, 18), 3: (13, 26), 4: (20, 30), 5: (22, 35),
            6: (25, 38), 7: (30, 42), 8: (40, 55), 9: (46, 67)}
STRONG_PCT = 0.10          # share of strong spawns
STRONG_MAX = 10            # up to this many levels above the band
HEAL_BUDGET = 0.5          # wild may regain at most this share of max HP per encounter
BABY_PREVO_STRONG_BST = 450  # Snorlax, Chansey, Lucario...: wild from Lv 20, not Lv 1

_ENG_BOOSTS = {"atk": "attack_boost", "def": "defense_boost", "spa": "special_attack_boost",
               "spd": "special_defense_boost", "spe": "speed_boost",
               "accuracy": "accuracy_boost", "evasion": "evasion_boost"}


class _WildState:
    def __init__(self):
        self.hist_user = []      # moves used since the buddy's current life began
        self.hist_enemy = []     # same for the wild Pokemon
        self.healed = 0          # HP the wild Pokemon has regained this encounter
        self.block_shiny = False
        self.home_iid = None     # your buddy, restored when the encounter ends
        self.switched_in = None  # the teammate WE put in front (None = buddy still leads)
        self.fainted = set()     # team members that fainted this encounter
        self.participants = []   # everyone who fought this encounter, in order
        self.meta_loaded = False
        self.rounds = 0          # rounds fought this encounter
        self.team_sig = None     # (buddy, team slots) as the fight stands


STATE = _WildState()


def _settings():
    from ..singletons import settings_obj
    return settings_obj


def _flag(v, default=True):
    if v is None:
        return default
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "on", "enabled")
    return bool(v)


POPUP_KEYS = {
    "damage": "battle.popup_damage",      # -12 HP / +8 HP numbers
    "faint": "battle.popup_faint",        # fainted, "Go, X!", fled, team wiped
    "xp": "battle.popup_xp",              # XP gained, team XP split
    "levelup": "battle.popup_levelup",    # level up, new move learned
    "catch": "battle.popup_catch",        # caught / upgraded / released
}


def popup(kind):
    """Should this kind of wild-battle popup be shown? (all off by default)"""
    try:
        return _flag(_settings().get(POPUP_KEYS[kind], False), False)
    except Exception:
        return False


def tip(kind, msg, colour="#F5B041"):
    if not popup(kind):
        return
    try:
        from ..functions.drawing_utils import tooltipWithColour
        tooltipWithColour(msg, colour)
    except Exception:
        pass


# ------------------------------------------------------------- regions ----
def region():
    """The region you're in. Anything else stored (the old "All") -> Kanto."""
    try:
        r = str(_settings().get("misc.region", HOME_REGION) or HOME_REGION)
    except Exception:
        r = HOME_REGION
    return r if r in REGIONS else HOME_REGION


def set_region(name):
    if name in REGIONS:
        _settings().set("misc.region", name)


def region_gen():
    return REGION_GEN.get(region())


def gen_of(dex):
    try:
        dex = int(dex)
    except (TypeError, ValueError):
        return None
    for g in range(1, 10):
        if dex <= GEN_MAX[g]:
            return g
    return None


def region_name(dex):
    g = gen_of(dex)
    return REGIONS[g - 1] if g else "?"


def region_allows(dex):
    """Only the current region's Pokémon appear in the wild."""
    return gen_of(dex) == region_gen()


def filter_ids(ids):
    """A tier list -> this region's ids, so the spawn loop picks a valid
    species on the first try."""
    g = region_gen()
    return [i for i in ids if isinstance(i, int) and gen_of(i) == g]


# -------------------------------------------------------------- levels ----
def follow_badges():
    try:
        return _flag(_settings().get("battle.wild_levels_follow_badges", True), True)
    except Exception:
        return True


def _defeated():
    from ..gym import gym_ui
    return {int(i) for i in gym_ui.progress().defeated_ids()}


def badges(reg=None):
    """Badges earned in a region (default: the one you're in); 9 = that
    region's Champion beaten. None without the gym ladder."""
    try:
        from ..gym import gym_config
        if not gym_config.enabled():
            return None
        from ..gym import gym_data
        ids = _defeated()
        reg = reg or region()
        if gym_data.champion_beaten(ids, reg):
            return 9
        return min(8, gym_data.badges_earned(ids, reg))
    except Exception:
        return None


def band(reg=None):
    """(badges, lo, hi) of the current level band, or None in classic mode.
    Kanto uses Red/Blue's route levels; other regions sit just under the
    next leader's strongest Pokemon."""
    if not follow_badges():
        return None
    reg = reg or region()
    b = badges(reg)
    if b is None:
        return None
    if reg == "Kanto":
        lo, hi = RB_BANDS[b]
        return b, lo, hi
    try:
        from ..gym import gym_data
        aces = [gym_data.ace_level(g) for g in gym_data.ladder(reg) if g.kind == gym_data.GYM]
    except Exception:
        aces = []
    if not aces:
        lo, hi = RB_BANDS[min(b, 9)]
        return b, lo, hi
    nxt = aces[b] if b < len(aces) else aces[-1] + 10
    lo = max(2, nxt - 14)
    return b, lo, max(lo + 3, nxt - 4)


def level_cap(reg=None):
    """Highest level your Pokémon fight at here (next leader's ace + 5);
    None without the gym ladder or once the region's Champion is beaten."""
    try:
        from ..gym import gym_config, gym_data
        if not gym_config.enabled():
            return None
        return gym_data.level_cap(_defeated(), reg or region())
    except Exception:
        return None


def cap_engine(engine_mon, pobj):
    """Fight at the region's level cap: the engine copy gets its stats at the
    cap and its HP rescaled into the capped pool. The Pokémon itself keeps
    its real level and HP (real_hp converts back after each turn)."""
    try:
        cap = level_cap()
        if not cap or int(pobj.level) <= cap:
            return engine_mon
        P = type(pobj)
        iv, ev, bs = pobj.iv or {}, pobj.ev or {}, pobj.base_stats or {}
        nat = getattr(pobj, "nature", "serious")

        def st(k):
            return P.calc_stat(k, int(bs.get(k, 50)), cap, int(iv.get(k, 0)), int(ev.get(k, 0)), nat)
        mx = max(1, st("hp"))
        rmax, rhp = max(1, int(pobj.max_hp)), int(pobj.hp)
        engine_mon.level = cap
        engine_mon.attack, engine_mon.defense = st("atk"), st("def")
        engine_mon.special_attack, engine_mon.special_defense = st("spa"), st("spd")
        engine_mon.speed = st("spe")
        engine_mon.maxhp = mx
        engine_mon.hp = 0 if rhp <= 0 else (mx if rhp >= rmax else max(1, round(rhp * mx / rmax)))
    except Exception as e:
        print("Ankimon wild: level cap not applied:", e)
    return engine_mon


def shown_level_hp(pobj):
    """(level, hp, max_hp) the HUD shows for your buddy. While the region's
    level cap holds it back it shows - and fights - at the cap, with its HP
    scaled the same way cap_engine scales it; EXP and levelling carry on for
    real underneath, and it shows its own level again once the cap passes it."""
    try:
        lv, hp, mx = int(pobj.level), int(pobj.hp), max(1, int(pobj.max_hp))
    except Exception:
        return getattr(pobj, "level", 1), getattr(pobj, "hp", 0), getattr(pobj, "max_hp", 1)
    try:
        cap = level_cap()
        if not cap or lv <= cap:
            return lv, hp, mx
        P = type(pobj)
        iv, ev, bs = pobj.iv or {}, pobj.ev or {}, pobj.base_stats or {}
        cmx = max(1, P.calc_stat("hp", int(bs.get("hp", 50)), cap, int(iv.get("hp", 0)),
                                 int(ev.get("hp", 0)), getattr(pobj, "nature", "serious")))
        chp = 0 if hp <= 0 else (cmx if hp >= mx else max(1, round(hp * cmx / mx)))
        return cap, chp, cmx
    except Exception:
        return lv, hp, mx


def real_hp(pobj, engine_mon):
    """Engine HP -> the Pokémon's own HP (they differ while a cap applies)."""
    try:
        emax, rmax, hp = max(1, int(engine_mon.maxhp)), max(1, int(pobj.max_hp)), int(engine_mon.hp)
    except Exception:
        return getattr(engine_mon, "hp", 0)
    if emax == rmax:
        return hp
    if hp <= 0:
        return 0
    if hp >= emax:
        return rmax
    return max(1, round(hp * rmax / emax))


def pick_level(buddy_level, rng=random):
    """Wild level from the badge band, or None to keep the classic +-3."""
    bd = band()
    if bd is None:
        return None
    _b, lo, hi = bd
    if rng.random() < STRONG_PCT:
        return min(100, hi + rng.randint(1, STRONG_MAX))
    return rng.randint(lo, hi)


# ----------------------------------------------------- species fix-ups ----
def _dex_key(name):
    return re.sub(r"[^a-z0-9]", "", str(name or "").lower())


def baby_prevo_min_level(name):
    """Pikachu, Clefairy, Jigglypuff, Snorlax, Chansey, Marill...: their only
    pre-evolution is a baby Pokemon, and they are ordinary wild Pokemon in
    the real games. Ankimon treated them as never-wild (friendship / item
    evolutions). Returns their minimum wild level, or None if the rule
    doesn't apply. Stone and trade evolutions stay non-wild."""
    from ..functions.pokedex_functions import _load_pokedex_cache
    from ..functions import encounter_data
    dex = _load_pokedex_cache() or {}
    d = dex.get(_dex_key(name))
    if not d or d.get("evoLevel") or not d.get("evoType") or not d.get("prevo"):
        return None
    p = dex.get(_dex_key(d["prevo"]))
    if not p or p.get("species_id") not in encounter_data.BABY:
        return None
    bs = d.get("baseStats") or {}
    try:
        bst = sum(int(v) for v in bs.values())
    except Exception:
        bst = 0
    return 20 if bst >= BABY_PREVO_STRONG_BST else 1


# --------------------------------------------------------------- moves ----
def move_id(move):
    return normalize_name(str(move or ""))


def move_data(move):
    return all_move_json.get(move_id(move))


def move_details(move):
    """Category for the battle-log colour (the chosen move, not a random one)."""
    e = move_data(move) or {}
    return {"category": str(e.get("category") or "physical").capitalize(),
            "type": e.get("type")}


def _type_eff(t, defender):
    try:
        return type_effectiveness_modifier(t, defender)
    except Exception:
        return 1.0


def _view(mon):
    """poke-engine Pokémon -> the plain dict wild_ai reads."""
    return {"level": mon.level, "types": list(mon.types or []),
            "atk": mon.attack, "def": mon.defense, "spa": mon.special_attack,
            "spd": mon.special_defense, "spe": mon.speed,
            "hp": max(0, mon.hp), "maxhp": max(1, mon.maxhp),
            "boosts": {k: getattr(mon, v, 0) for k, v in _ENG_BOOSTS.items()},
            "status": mon.status, "volatiles": set(mon.volatile_status or ())}


def _battle_mons(main_pokemon, enemy_pokemon, s):
    """The two Pokémon as the engine will see them this turn: the running
    battle state, or fresh ones when the battle is about to reset (same test
    simulate_battle_with_poke_engine uses)."""
    st = getattr(s, "new_state", None)
    if (st is not None and getattr(s, "mutator_full_reset", 1) == 0
            and st.user.active.id == main_pokemon.to_engine_format()["identifier"]):
        return st.user.active, st.opponent.active
    return (cap_engine(main_pokemon.to_poke_engine_Pokemon(), main_pokemon),
            enemy_pokemon.to_poke_engine_Pokemon())


# --- which of the buddy's moves are ticked for wild battles -------------
_PREFS_DDL = ("CREATE TABLE IF NOT EXISTS wild_move_prefs ("
              "individual_id TEXT PRIMARY KEY, off TEXT NOT NULL DEFAULT '[]')")
_prefs_cache = {}
_prefs_ready = [False]


def _db():
    from aqt import mw
    db = mw.ankimon_db
    if not _prefs_ready[0]:
        db.execute(_PREFS_DDL)
        _commit(db)
        _prefs_ready[0] = True
    return db


def _commit(db):
    try:
        db._get_connection().commit()
    except Exception:
        conn = getattr(db, "conn", None)
        if conn is not None:
            conn.commit()


def disabled_moves(individual_id):
    """Move ids un-ticked for wild battles (new moves start ticked)."""
    if not individual_id:
        return set()
    if individual_id in _prefs_cache:
        return _prefs_cache[individual_id]
    try:
        r = _db().execute("SELECT off FROM wild_move_prefs WHERE individual_id=?",
                          (individual_id,)).fetchone()
        off = set(json.loads(r[0])) if r else set()
    except Exception:
        off = set()
    _prefs_cache[individual_id] = off
    return off


def set_move_enabled(individual_id, move, enabled):
    off = set(disabled_moves(individual_id))
    mid = move_id(move)
    if enabled:
        off.discard(mid)
    else:
        off.add(mid)
    db = _db()
    db.execute("INSERT INTO wild_move_prefs (individual_id, off) VALUES (?, ?) "
               "ON CONFLICT(individual_id) DO UPDATE SET off=excluded.off",
               (individual_id, json.dumps(sorted(off))))
    _commit(db)
    _prefs_cache[individual_id] = off


def move_enabled(individual_id, move):
    return move_id(move) not in disabled_moves(individual_id)


def wild_moves(main_pokemon):
    """The buddy's ticked moves (all of them if somehow none are ticked)."""
    attacks = [a for a in (main_pokemon.attacks or []) if a]
    off = disabled_moves(getattr(main_pokemon, "individual_id", None))
    use = [a for a in attacks if move_id(a) not in off]
    return use or attacks


def choose_moves(main_pokemon, enemy_pokemon, s, rng=random):
    """(user_attack, enemy_attack) for this round. Falls back to the old
    random pick if anything goes wrong, so a review is never blocked."""
    ua = [a for a in (main_pokemon.attacks or []) if a]
    ea = [a for a in (enemy_pokemon.attacks or []) if a]
    user_attack = rng.choice(ua) if ua else "splash"
    enemy_attack = rng.choice(ea) if ea else "splash"
    try:
        me, foe = _battle_mons(main_pokemon, enemy_pokemon, s)
        mv, fv = _view(me), _view(foe)
        mine = wild_moves(main_pokemon)
        user_attack = wild_ai.choose(mine, mv, fv, move_data, _type_eff, rng,
                                     foe_moves=ea, history=STATE.hist_user) or user_attack
        if ea:
            enemy_attack = wild_ai.choose(ea, fv, mv, move_data, _type_eff, rng,
                                          foe_moves=mine, history=STATE.hist_enemy) or enemy_attack
    except Exception as e:
        print("Ankimon wild AI: falling back to random moves:", e)
    return user_attack, enemy_attack


# ------------------------------------------------------ battle hooks ----
def after_turn(s, user_attack, enemy_attack, heals_to_opponent, main_pokemon=None):
    """Record the moves (support-move limit) and who fought (EXP split), and
    hold the wild Pokémon to its healing budget. Returns the heal to show."""
    STATE.rounds += 1
    STATE.hist_user.append(user_attack)
    STATE.hist_enemy.append(enemy_attack)
    if main_pokemon is not None:
        note_participant(getattr(main_pokemon, "individual_id", None))
    try:
        heal = int(heals_to_opponent or 0)
        if heal <= 0:
            return heals_to_opponent
        opp = s.new_state.opponent.active
        allowed = max(0, int(HEAL_BUDGET * max(1, opp.maxhp)) - STATE.healed)
        if heal > allowed:
            if opp.hp > 0:
                opp.hp = max(1, opp.hp - (heal - allowed))
            heal = allowed
        STATE.healed += heal
        return heal
    except Exception:
        return heals_to_opponent


def survive_rule_applies(user_active):
    try:
        return 0 < user_active.hp and user_active.hp >= user_active.maxhp
    except Exception:
        return False


def _battle_loop_state():
    pkg = __name__.rsplit(".", 2)[0]
    bl = sys.modules.get(pkg + ".battle_loop")
    return getattr(bl, "_state", None) if bl is not None else None


def reset_battle():
    """Make the next round rebuild both sides from the Pokémon objects."""
    st = _battle_loop_state()
    if st is not None:
        st.mutator_full_reset = 1


def consume_shiny_block():
    b = STATE.block_shiny
    STATE.block_shiny = False
    return b


# ------------------------------------------------------ team rotation ----
_META_DDL = "CREATE TABLE IF NOT EXISTS wild_meta (key TEXT PRIMARY KEY, value TEXT)"
_meta_ready = [False]


def _meta_db():
    db = _db()
    if not _meta_ready[0]:
        db.execute(_META_DDL)
        _commit(db)
        _meta_ready[0] = True
    return db


def _load_meta():
    """Who to restore survives an Anki restart in the middle of a fight."""
    if STATE.meta_loaded:
        return
    STATE.meta_loaded = True
    try:
        rows = {r[0]: r[1] for r in _meta_db().execute("SELECT key, value FROM wild_meta").fetchall()}
        STATE.home_iid = rows.get("home_iid") or STATE.home_iid
        STATE.switched_in = rows.get("switched_in") or STATE.switched_in
    except Exception:
        pass


def _save_meta():
    try:
        db = _meta_db()
        for k in ("home_iid", "switched_in"):
            v = getattr(STATE, k)
            if v:
                db.execute("INSERT INTO wild_meta (key, value) VALUES (?, ?) "
                           "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (k, v))
            else:
                db.execute("DELETE FROM wild_meta WHERE key=?", (k,))
        _commit(db)
    except Exception:
        pass


def _main():
    try:
        from ..singletons import main_pokemon
        return main_pokemon
    except Exception:
        return None


def _iid(p):
    return getattr(p, "individual_id", None)


def note_participant(iid):
    if iid and iid not in STATE.participants:
        STATE.participants.append(iid)


def _heal(p):
    try:
        p.hp = p.max_hp
        p.current_hp = p.max_hp
        p.reset_bonuses()
        p.battle_status = "fighting"
        p.volatile_status = set()
    except Exception:
        pass


def party():
    """Fighting order: your buddy, then team slots 1-6 (buddy not repeated)."""
    from aqt import mw
    db = mw.ankimon_db
    _load_meta()
    order = []
    lead = STATE.home_iid or _iid(_main())
    try:
        team = [t.get("individual_id") for t in (db.get_team() or [])]
    except Exception:
        team = []
    for iid in [lead] + team:
        if iid and iid not in order:
            try:
                if db.get_pokemon(iid):
                    order.append(iid)
            except Exception:
                pass
    return order


def ready_teammates():
    """Team members that can still be sent in this encounter."""
    cur = _iid(_main())
    return [i for i in party() if i != cur and i not in STATE.fainted]


def _send_out(main_pokemon, iid):
    """Put a team member in front (full HP). The buddy comes back afterwards."""
    from aqt import mw
    from ..functions.update_main_pokemon import update_main_pokemon
    _load_meta()
    if STATE.home_iid is None:
        STATE.home_iid = _iid(main_pokemon)
    if not mw.ankimon_db.set_main_pokemon(iid):
        return False
    update_main_pokemon(main_pokemon)
    _heal(main_pokemon)
    STATE.switched_in = iid
    STATE.hist_user = []
    _save_meta()
    reset_battle()
    mark_team()                 # our own switch, not yours
    return True


def switch_in(iid):
    """Manual switch from the wild menu (this fight only)."""
    mp = _main()
    return mp is not None and _send_out(mp, iid)


def on_buddy_fainted(main_pokemon, enemy_pokemon):
    """'next'     a teammate was sent in against the same wild Pokémon
       'won'      the wild one had already fainted too (nothing to do)
       'whiteout' nobody left - the caller ends the encounter"""
    _load_meta()
    STATE.hist_user = []
    cur = _iid(main_pokemon)
    note_participant(cur)
    if getattr(enemy_pokemon, "hp", 0) <= 0:
        _heal(main_pokemon)
        return "won"
    STATE.fainted.add(cur)
    if STATE.home_iid is None:
        STATE.home_iid = cur
    for iid in party():
        if iid != cur and iid not in STATE.fainted:
            if _send_out(main_pokemon, iid):
                return "next"
    _heal(main_pokemon)
    return "whiteout"


def _restore_home():
    """Encounter over: buddy back in front, everyone healed."""
    _load_meta()
    home, sw = STATE.home_iid, STATE.switched_in
    STATE.home_iid = STATE.switched_in = None
    if home or sw:
        _save_meta()
    mp = _main()
    if mp is None:
        return
    try:
        # Only undo OUR switch - if you picked a new buddy in the team window
        # mid-fight, that choice stands.
        if home and sw and _iid(mp) == sw and home != sw:
            from aqt import mw
            from ..functions.update_main_pokemon import update_main_pokemon
            if mw.ankimon_db.set_main_pokemon(home):
                update_main_pokemon(mp)
    except Exception as e:
        print("Ankimon wild: could not bring your buddy back:", e)
    _heal(mp)


def on_new_encounter(pokemon=None):
    """Called by new_pokemon whenever a new wild Pokémon appears."""
    STATE.hist_user = []
    STATE.hist_enemy = []
    STATE.healed = 0
    _restore_home()
    STATE.fainted = set()
    STATE.participants = []
    STATE.rounds = 0
    reset_battle()
    mark_team()
    # an encounter just ended (catch, win, flee...): register new species
    try:
        from . import dex
        dex.sync_and_award()
    except Exception:
        pass


# ---------------------------------------------------- team changes ----
def _team_sig():
    from aqt import mw
    try:
        team = tuple(t.get("individual_id") for t in (mw.ankimon_db.get_team() or []))
    except Exception:
        team = ()
    return (_iid(_main()), team)


def mark_team():
    """Remember your buddy and team as the fight stands."""
    try:
        STATE.team_sig = _team_sig()
    except Exception:
        STATE.team_sig = None


def check_team_change() -> bool:
    """Changing your buddy or team in the middle of a fight (say, to swap
    out a fainted Pokémon) makes the wild Pokémon flee. Before the first
    round it's fine. Returns True if it fled."""
    try:
        sig = _team_sig()
        if STATE.team_sig is None or STATE.rounds == 0:
            STATE.team_sig = sig
            return False
        if sig == STATE.team_sig:
            return False
        from . import wild_menus
        wild_menus.flee("The wild %s fled while you changed your team."
                        % _dn(getattr(_enemy(), "name", "Pokémon")))
        return True
    except Exception as e:
        print("Ankimon wild: team check failed:", e)
        return False


def _enemy():
    try:
        from ..singletons import enemy_pokemon
        return enemy_pokemon
    except Exception:
        return None


# ------------------------------------------------------------------ EXP ----
def share_exp(exp, finisher, logger=None, evo_window=None):
    """Final blow keeps 50%; the other 50% is split evenly between everyone
    else who fought (they are saved straight to the database). Returns the
    finisher's EXP, which then goes through the normal XP Share / Lucky Egg /
    level-up path."""
    fid = _iid(finisher)
    others = [i for i in STATE.participants if i and i != fid]
    if not others:
        return exp
    each = max(1, int(math.ceil(exp * 0.5 / len(others))))
    keep = max(1, int(math.ceil(exp * 0.5)))
    from aqt import mw
    from ..functions.trainer_functions import xp_share_gain_exp
    got = []
    for iid in others:
        try:
            rec = mw.ankimon_db.get_pokemon(iid) or {}
            # xp_share_gain_exp halves what it is given, so pass double;
            # it handles level-ups, Lucky Egg, evolution checks and saving.
            xp_share_gain_exp(logger, _settings(), evo_window, None, each * 2, iid)
            got.append(str(rec.get("nickname") or _dn(rec.get("name") or "?")))
        except Exception as e:
            print("Ankimon wild: EXP share failed for", iid, e)
    if got:
        tip("xp", "Team EXP: %s +%d (final blow), %s +%d each"
            % (_dn(getattr(finisher, "name", "?")), keep, ", ".join(got), each),
            "#a17cf7")
    return keep


# ------------------------------------------------------ special spawns ----
# Starters: a little rarer than anything else in the wild (not shiny-rare).
STARTER_RATE = 0.01          # ~1 encounter in 100
STARTERS = {1: [1, 4, 7], 2: [152, 155, 158], 3: [252, 255, 258], 4: [387, 390, 393],
            5: [495, 498, 501], 6: [650, 653, 656], 7: [722, 725, 728], 8: [810, 813, 816],
            9: [906, 909, 912]}
# Mewtwo: ultra-rare wild encounter once you have 8 Kanto badges and 100
# Kanto species registered. Kanto only; one per save, like Red/Blue.
MEWTWO_ID = 150
MEWTWO_LEVEL = 70
MEWTWO_RATE = 1.0 / 750      # ~1 encounter in 750 once unlocked
MEWTWO_KANTO_NEEDED = 100
MEWTWO_BADGES = 8
# Legendaries you catch simply by winning (any Automatic Battle mode)
MUST_CATCH = {144, 145, 146, 150}
# Hand-picked from its level-up moves at Lv 70 (the "last four learned" would
# be Psychic, Guard Swap, Power Swap and Mist)
LEGEND_SETS = {MEWTWO_ID: ["psychic", "aurasphere", "amnesia", "lifedew"]}


def starter_pool():
    return list(STARTERS.get(region_gen(), []))


def mewtwo_status():
    """(unlocked, reason) - also used by the wild info / menus."""
    try:
        from . import dex
        reg = dex.registered()
        if MEWTWO_ID in reg:
            return False, "already caught"
        if region() != "Kanto":
            return False, "only in Kanto"
        b = badges("Kanto") or 0
        if b < MEWTWO_BADGES:
            return False, "needs %d badges (you have %d)" % (MEWTWO_BADGES, b)
        k = dex.region_count(1, reg)
        if k < MEWTWO_KANTO_NEEDED:
            return False, "needs %d Kanto species registered (you have %d)" % (MEWTWO_KANTO_NEEDED, k)
        return True, "can appear"
    except Exception as e:
        return False, "error: %s" % e


def legendary_moves(name, level):
    """The last four moves the species learns by `level` (what a wild one
    of that level knows in the games)."""
    try:
        from ..functions.learnset_retrieval import _get_learnset_moves
        learned = _get_learnset_moves(str(name).lower(), int(level))
        order = sorted(learned.items(), key=lambda kv: (int(kv[1] or 0), str(kv[0])))
        moves = []
        for mv, _lv in reversed(order):
            if mv not in moves:
                moves.append(mv)
            if len(moves) == 4:
                break
        return list(reversed(moves)) or None
    except Exception:
        return None


def special_spawn(rng=random):
    """A rare spawn for this encounter, or None. Never right after a flee."""
    if STATE.block_shiny:
        return None
    try:
        if rng.random() < MEWTWO_RATE and mewtwo_status()[0]:
            return {"id": MEWTWO_ID, "tier": "Legendary", "level": MEWTWO_LEVEL,
                    "moves": LEGEND_SETS.get(MEWTWO_ID) or legendary_moves("mewtwo", MEWTWO_LEVEL)}
        if rng.random() < STARTER_RATE:
            pool = starter_pool()
            if pool:
                return {"id": rng.choice(pool), "tier": "Normal"}
    except Exception as e:
        print("Ankimon wild: special spawn skipped:", e)
    return None


def must_catch(pokemon):
    try:
        return int(getattr(pokemon, "id", 0)) in MUST_CATCH
    except Exception:
        return False


# --------------------------------------------- trade evolutions, no trade ----
# Ankimon has no trading, so trade evolutions without a held item (Kadabra,
# Machoke, Graveler, Haunter, Boldore, Gurdurr, Karrablast...) evolve once the
# Pokemon is level 37 AND has 160 friendship. Friendship is the bond you build
# by winning battles with it in front (+5-9 per win).
TRADE_EVO_LEVEL = 37
TRADE_EVO_FRIENDSHIP = 160
_trade_cache = {}


def trade_evolution(species_id):
    """(evo_id, evo_name) for a trade evolution that needs no item, or None."""
    try:
        species_id = int(species_id)
    except (TypeError, ValueError):
        return None
    if species_id in _trade_cache:
        return _trade_cache[species_id]
    out = None
    try:
        from ..functions.pokedex_functions import _load_pokedex_cache
        dexd = _load_pokedex_cache() or {}
        src = next((d for d in dexd.values()
                    if d.get("species_id") == species_id and not d.get("forme")), None)
        for evo_name in (src or {}).get("evos") or []:
            t = dexd.get(_dex_key(evo_name))
            if t and t.get("evoType") == "trade" and not t.get("evoItem") and not t.get("forme"):
                out = (int(t.get("species_id")), t.get("name") or evo_name)
                break
    except Exception:
        out = None
    _trade_cache[species_id] = out
    return out


def trade_readiness(species_id, level, friendship, everstone=False, rejected=False):
    """A readiness dict in friendship_evolution.evolution_readiness's shape,
    or None if this species has no item-less trade evolution."""
    te = trade_evolution(species_id)
    if not te:
        return None
    evo_id, evo_name = te
    level, friendship = int(level or 1), int(friendship or 0)
    lv_left = max(0, TRADE_EVO_LEVEL - level)
    fr_left = max(0, TRADE_EVO_FRIENDSHIP - friendship)
    ready = (not everstone) and lv_left == 0 and fr_left == 0
    if everstone:
        text = "Holding an Everstone - it won't evolve."
    elif ready:
        text = "Ready to evolve into %s!" % evo_name
    else:
        need = []
        if lv_left:
            need.append("Lv %d (%d to go)" % (TRADE_EVO_LEVEL, lv_left))
        if fr_left:
            need.append("%d friendship (%d to go)" % (TRADE_EVO_FRIENDSHIP, fr_left))
        text = "Evolves into %s at %s. (Trade evolution - no trading needed.)" % (
            evo_name, " and ".join(need))
    return {"evolvable": True, "ready": ready, "method": "friendship", "evo_id": evo_id,
            "evo_name": evo_name, "min_happiness": TRADE_EVO_FRIENDSHIP,
            "current_friendship": friendship, "friendship_remaining": fr_left,
            "required_time": None, "time_ok": True, "status_text": text,
            "bar_max": TRADE_EVO_FRIENDSHIP, "rejected": bool(rejected)}


def level_of(individual_id):
    """Current level: the live buddy's if it's the one in front, else saved."""
    try:
        mp = _main()
        if mp is not None and _iid(mp) == individual_id:
            return int(mp.level)
        from aqt import mw
        rec = mw.ankimon_db.get_pokemon(individual_id) or {}
        return int(rec.get("level") or 1)
    except Exception:
        return 1


def _dn(n):
    """Real Pokémon name for display ("Iron Hands", "Mr. Mime")."""
    try:
        from ..functions.pokedex_functions import display_name
        return display_name(n)
    except Exception:
        s = str(n or "")
        return s[:1].upper() + s[1:]
