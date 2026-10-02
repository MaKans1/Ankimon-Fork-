"""
gym_engine.py — gym battles on one real poke-engine State.

No aqt / Anki imports: everything here is plain engine work, so it can be
tested outside Anki.

WHY THIS EXISTS
    Gyms used to borrow the wild-battle hook, which rebuilds BOTH sides from
    scratch whenever anything faints. That wiped the survivor's boosts, status
    and screens, and the rebuilt Pokemon carried the status "Fighting", which
    the engine read as an existing status - so Thunder Wave, Toxic, Will-O-Wisp
    and friends could never land in a gym.

    Here the whole 3v3 lives in one State for the entire fight:
      - both teams sit in the engine's reserve, so U-turn / Baton Pass work
      - a fainted Pokemon is replaced through the engine's own switch routine,
        so Stealth Rock / Spikes / Toxic Spikes / Sticky Web hit on entry, the
        fainted Pokemon's boosts go with it, and Reflect / Light Screen /
        Tailwind stay up for the rest of their turns

GYM-ONLY MOVE BALANCE
    gym_move_patch.json holds the gym balance pass (91 moves, see the balance
    sim). It is laid over the engine's move table only while a gym turn or a
    gym AI decision is being computed, and always restored afterwards, so wild
    battles never see it.

GLOBAL MOVE FIXES
    Four moves were broken in the engine data for everyone (they boosted the
    ENEMY). apply_global_fixes() corrects them in memory for wild and gym alike.

PLANNING LEADERS
    leader_plan() reads the live battle every turn and plays each of its moves
    a few turns forward (then keeps hitting with its best attack), assuming the
    player presses their strongest attack. It picks whatever leaves the player
    worst off. No script: faints, switches, boosts and status are all just part
    of the state it reads. ~10 ms per decision.
"""

import copy
import json
import os
import random
from collections import defaultdict
from contextlib import contextmanager

from ..poke_engine import constants
from ..poke_engine.data import all_move_json
from ..poke_engine.helpers import normalize_name
from ..poke_engine.objects import State, Side, StateMutator, TransposeInstruction
from ..poke_engine.find_state_instructions import get_all_state_instructions
from ..poke_engine.instruction_generator import get_instructions_from_switch
from ..poke_engine.evaluate import evaluate

HERE = os.path.dirname(os.path.abspath(__file__))
STRUGGLE = "struggle"
PLAN_ROLLOUTS = 3
PLAN_HORIZON = 8
SIDE_CONDITIONS = ("stealthrock", "spikes", "toxicspikes", "stickyweb", "tailwind",
                   "reflect", "lightscreen", "auroraveil", "protect", "safeguard", "mist")

# --------------------------------------------------------- move fixes ----
GLOBAL_MOVE_FIXES = {
    # Ally-targeted boosts land on the ENEMY in a singles engine.
    "howl": {"target": "self"},
    "coaching": {"target": "self"},
    "aromaticmist": {"target": "self"},
    # Curse boosted the enemy and cursed it. Now the non-Ghost version for
    # everyone: +1 Atk, +1 Def, -1 Spe on the user.
    "curse": {"target": "self", "volatileStatus": None},
}
_global_done = False


def _apply_fields(e, changes):
    for k, v in changes.items():
        if k == "secondary_chance":
            if isinstance(e.get("secondary"), dict):
                e["secondary"] = dict(e["secondary"], chance=v)
        elif k == "self_boosts":
            e["self"] = dict(e.get("self") or {}, boosts=dict(v))
        elif k == "boosts":
            e["boosts"] = dict(v)
        elif v is None:
            e.pop(k, None)
        else:
            e[k] = list(v) if isinstance(v, (list, tuple)) else v


def apply_global_fixes():
    """Idempotent. Safe to call on every import."""
    global _global_done
    if _global_done:
        return
    for m, ch in GLOBAL_MOVE_FIXES.items():
        e = all_move_json.get(m)
        if e is not None:
            _apply_fields(e, ch)
    _global_done = True


_PATCH = None
_overlay_depth = 0
_overlay_saved = {}


def gym_patch():
    global _PATCH
    if _PATCH is None:
        try:
            with open(os.path.join(HERE, "gym_move_patch.json"), encoding="utf-8") as f:
                _PATCH = json.load(f)
        except Exception:
            _PATCH = {}
    return _PATCH


@contextmanager
def gym_moves():
    """Lay the gym balance patch over the engine move table for the duration.
    Re-entrant; the outermost exit restores the original entries in place."""
    global _overlay_depth
    if _overlay_depth == 0:
        _overlay_saved.clear()
        for m, ch in gym_patch().items():
            e = all_move_json.get(m)
            if e is None:
                continue
            _overlay_saved[m] = copy.deepcopy(e)
            _apply_fields(e, ch)
    _overlay_depth += 1
    try:
        yield
    finally:
        _overlay_depth -= 1
        if _overlay_depth == 0:
            for m, orig in _overlay_saved.items():
                e = all_move_json[m]
                e.clear()
                e.update(orig)
            _overlay_saved.clear()


def engine_id(move):
    mid = normalize_name(str(move or ""))
    return mid if mid in all_move_json else "splash"


def is_attack(mid):
    e = all_move_json.get(mid) or {}
    return mid == STRUGGLE or (e.get("category") != "status" and (e.get("basePower") or 0) > 0) \
        or e.get("damage") is not None or e.get("ohko")


# ------------------------------------------------------------ log text ----
_STATUS_TEXT = {"par": "is paralyzed", "brn": "was burned", "psn": "was poisoned",
                "tox": "was badly poisoned", "slp": "fell asleep", "frz": "was frozen solid"}
_STAT_TEXT = {"attack": "Attack", "defense": "Defense", "special-attack": "Sp. Atk",
              "special-defense": "Sp. Def", "speed": "Speed", "accuracy": "accuracy",
              "evasion": "evasiveness"}
_SIDE_TEXT = {"reflect": "Reflect", "lightscreen": "Light Screen", "auroraveil": "Aurora Veil",
              "tailwind": "Tailwind", "safeguard": "Safeguard", "mist": "Mist",
              "stealthrock": "Stealth Rock", "spikes": "Spikes", "toxicspikes": "Toxic Spikes",
              "stickyweb": "Sticky Web"}
_VOLATILE_TEXT = {"confusion": "became confused", "leechseed": "was seeded",
                  "substitute": "made a substitute", "flinch": "flinched",
                  "taunt": "fell for the taunt", "yawn": "grew drowsy",
                  "attract": "fell in love", "encore": "got an encore"}


def _amount(n):
    return {1: "rose", 2: "rose sharply"}.get(n, "rose drastically")


def _drop(n):
    return {1: "fell", 2: "harshly fell"}.get(n, "severely fell")


# ------------------------------------------------------------- battle ----
class EngineBattle:
    """One gym fight. Combatants (gym_state) stay the HP/PP authority for the
    UI; the engine State is the authority for everything else."""

    def __init__(self, player_team, leader_team, leader_label="The leader"):
        self.p_team = list(player_team)
        self.l_team = list(leader_team)
        self.leader_label = leader_label
        self.by = {"user": {}, "opponent": {}}
        self.state = State(self._side(self.p_team, self.by["user"]),
                           self._side(self.l_team, self.by["opponent"]),
                           None, None, False)

    # --- construction ------------------------------------------------
    @staticmethod
    def _side(team, by_id):
        mons = []
        for c in team:
            src = c.source
            # Clean slate: lowercase "fighting" means no status to the engine.
            src.battle_status = "fighting"
            src.volatile_status = set()
            src.stat_stages = {k: 0 for k in ("atk", "def", "spa", "spd", "spe",
                                              "accuracy", "evasion")}
            src.hp = src.current_hp = int(c.hp)
            pk = src.to_poke_engine_Pokemon()
            pk.hp, pk.maxhp = int(c.hp), int(c.max_hp)
            # Ankimon hands moves over as bare {"id": ...}. The engine's switch
            # routine also reads "disabled" and "current_pp" on every move of
            # the Pokemon leaving the field - without them the first faint
            # replacement raised KeyError and the fight froze.
            pp = {engine_id(k): v for k, v in (c.pp or {}).items()}
            fixed = []
            for m in (pk.moves or []):
                mid = m.get(constants.ID) if isinstance(m, dict) else normalize_name(str(m))
                fixed.append({constants.ID: mid, constants.DISABLED: False,
                              constants.CURRENT_PP: int(pp.get(mid, 16) or 16)})
            pk.moves = fixed
            pk.status = None
            if pk.id in by_id:
                raise ValueError("duplicate species on one side: %s" % pk.id)
            by_id[pk.id] = c
            mons.append(pk)
        sc = defaultdict(int, {k: 0 for k in SIDE_CONDITIONS})
        return Side(active=mons[0], reserve={p.id: p for p in mons[1:]},
                    wish=(0, 0), side_conditions=sc, future_sight=(0, 0))

    # --- views ---------------------------------------------------------
    def _side_obj(self, side):
        return self.state.user if side == "user" else self.state.opponent

    def active(self, side):
        """Active Combatant, or None once that side has nothing left."""
        mon = self._side_obj(side).active
        c = self.by[side].get(mon.id)
        return c if (c is not None and mon.hp > 0) else None

    def _sync(self):
        for side in ("user", "opponent"):
            s = self._side_obj(side)
            for mon in [s.active] + list(s.reserve.values()):
                c = self.by[side].get(mon.id)
                if c is None:
                    continue
                c.hp = max(0, int(mon.hp))
                try:
                    c.source.hp = c.source.current_hp = c.hp
                    c.source.battle_status = mon.status or ("fainted" if c.hp <= 0 else "fighting")
                except Exception:
                    pass

    # --- one turn --------------------------------------------------------
    def turn(self, p_move, l_move):
        """Resolve both moves, then any faints. Returns battle-log lines."""
        pm, lm = engine_id(p_move), engine_id(l_move)
        names = {"user": self._name("user"), "opponent": self._name("opponent")}
        with gym_moves():
            mut = StateMutator(self.state)
            outs = get_all_state_instructions(mut, pm, lm)
            o = random.choices(outs, weights=[x.percentage for x in outs])[0]
            mut.apply(o.instructions)
            lines = self._describe(o.instructions, names)
            self._sync()
            lines += self._replace("opponent")
            lines += self._replace("user")
        return lines

    def repair(self):
        """Bring in replacements for any fainted active Pokémon. Used if a turn
        errored after damage was applied, so the fight can carry on."""
        self._sync()
        return self._replace("opponent") + self._replace("user")

    def _name(self, side):
        c = self.by[side].get(self._side_obj(side).active.id)
        return c.name if c else "?"

    def _replace(self, side):
        """Bring in the next Pokémon (team order) through the engine switch, so
        entry hazards apply. Loops because a hazard can KO on entry."""
        lines = []
        s = self._side_obj(side)
        team = self.p_team if side == "user" else self.l_team
        while s.active.hp <= 0:
            gone = self.by[side].get(s.active.id)
            lines.append(("Your %s fainted!" if side == "user" else "%s fainted!")
                         % (gone.name if gone else "?"))
            nxt = next((c for c in team if c.hp > 0 and c is not gone), None)
            if nxt is None:
                break
            nid = next(k for k, v in self.by[side].items() if v is nxt)
            try:
                mut = StateMutator(self.state)
                ins = get_instructions_from_switch(mut, side, nid, TransposeInstruction(1.0, [], False))
                mut.apply(ins.instructions)
                hz = [i for i in ins.instructions if i[0] == constants.MUTATOR_DAMAGE]
            except Exception:
                # Safety net: never leave a fight stuck on a fainted Pokemon.
                # Swap directly (no entry hazards) if the engine switch fails.
                s.reserve[s.active.id] = s.active
                s.active = s.reserve.pop(nid)
                hz = []
            self._sync()
            lines.append(("Go, %s! (%d/%d HP)" if side == "user" else self.leader_label
                          + " sent out %s!") % ((nxt.name, nxt.hp, nxt.max_hp) if side == "user"
                                                else (nxt.name,)))
            if hz:
                lines.append("%s was hurt by the hazards on its side!" % nxt.name)
        return lines

    def _describe(self, instructions, names):
        """Readable effects - boosts, status, screens - not raw damage."""
        who = dict(names)
        out = []
        for ins in instructions:
            kind, side = ins[0], ins[1] if len(ins) > 1 else None
            if side not in ("user", "opponent"):
                continue
            label = ("your " if side == "user" else "the foe's ") + who.get(side, "?")
            if kind == constants.MUTATOR_SWITCH:
                c = self.by[side].get(ins[3])
                if c:
                    who[side] = c.name
                    out.append("%s switched in!" % c.name)
            elif kind == constants.MUTATOR_BOOST:
                out.append("%s's %s %s!" % (label, _STAT_TEXT.get(ins[2], ins[2]), _amount(ins[3])))
            elif kind == constants.MUTATOR_UNBOOST:
                out.append("%s's %s %s!" % (label, _STAT_TEXT.get(ins[2], ins[2]), _drop(ins[3])))
            elif kind == constants.MUTATOR_APPLY_STATUS:
                out.append("%s %s!" % (label, _STATUS_TEXT.get(ins[2], "got " + str(ins[2]))))
            elif kind == constants.MUTATOR_APPLY_VOLATILE_STATUS and ins[2] in _VOLATILE_TEXT:
                out.append("%s %s!" % (label, _VOLATILE_TEXT[ins[2]]))
            elif kind == constants.MUTATOR_SIDE_START and ins[2] in _SIDE_TEXT:
                out.append("%s went up on %s side!" % (
                    _SIDE_TEXT[ins[2]], "your" if side == "user" else "the foe's"))
            elif kind == constants.MUTATOR_HEAL and ins[2] > 0:
                out.append("%s restored HP." % label)
        # capitalise, de-duplicate consecutive repeats
        res = []
        for line in out:
            line = line[0].upper() + line[1:]
            if not res or res[-1] != line:
                res.append(line)
        return res

    # --- move choice -----------------------------------------------------
    def _usable(self, c):
        u = c.usable_moves()
        return u if u else [STRUGGLE]

    def expected_damage(self, move, attacker):
        """Expected HP the move takes off the other active Pokémon."""
        mid = engine_id(move)
        pm, em = (mid, "splash") if attacker == "user" else ("splash", mid)
        tgt = self.state.opponent if attacker == "user" else self.state.user
        mut = StateMutator(self.state)
        before = tgt.active.hp
        tot = 0.0
        for o in get_all_state_instructions(mut, pm, em):
            mut.apply(o.instructions)
            tot += o.percentage * (before - max(0, tgt.active.hp))
            mut.reverse(o.instructions)
        return tot

    def best_attack(self, c, side):
        """Highest expected damage right now (what auto-battle presses)."""
        with gym_moves():
            opts = self._usable(c)
            atk = [m for m in opts if is_attack(engine_id(m))] or opts
            return max(atk, key=lambda m: self.expected_damage(m, side))

    def leader_plan(self, leader, player):
        """Planning leader: play each option forward a few turns, pick the one
        that leaves the player worst off (lowest evaluation from our side)."""
        with gym_moves():
            opts = self._usable(leader)
            if len(opts) == 1:
                return opts[0]
            atk = [m for m in opts if is_attack(engine_id(m))] or opts
            follow = engine_id(max(atk, key=lambda m: self.expected_damage(m, "opponent")))
            p_opts = self._usable(player)
            p_atk = [m for m in p_opts if is_attack(engine_id(m))] or p_opts
            pm = engine_id(max(p_atk, key=lambda m: self.expected_damage(m, "user")))
            mut = StateMutator(self.state)
            best, bv = opts[0], float("inf")
            for m in opts:
                tot = 0.0
                for _ in range(PLAN_ROLLOUTS):
                    applied = []
                    move = engine_id(m)
                    for _t in range(PLAN_HORIZON):
                        outs = get_all_state_instructions(mut, pm, move)
                        o = random.choices(outs, weights=[x.percentage for x in outs])[0]
                        mut.apply(o.instructions)
                        applied.append(o.instructions)
                        if self.state.user.active.hp <= 0 or self.state.opponent.active.hp <= 0:
                            break
                        move = follow
                    tot += evaluate(self.state)
                    for ins in reversed(applied):
                        mut.reverse(ins)
                if tot < bv:
                    best, bv = m, tot
            return best


apply_global_fixes()
