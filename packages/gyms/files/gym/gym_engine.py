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
from ..poke_engine.data import pokedex as _engine_dex

HERE = os.path.dirname(os.path.abspath(__file__))
STRUGGLE = "struggle"
PLAN_ROLLOUTS = 3
PLAN_HORIZON = 8
TOTEM_WITHDRAW, TOTEM_RETURN = 0.30, 0.50      # Alola totems (gymsim.js does the same)
TOTEM_STATS = (("atk", "attack_boost", "Attack"), ("def", "defense_boost", "Defense"),
               ("spa", "special_attack_boost", "Sp. Atk"), ("spd", "special_defense_boost", "Sp. Def"),
               ("spe", "speed_boost", "Speed"))
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

    def __init__(self, player_team, leader_team, leader_label="The leader", totem=None, titan=None,
                 guard=None, hp_mult=1.0):
        self.guard = float(guard) if guard else None     # hidden boss guard (gym_battle.guard_for)
        self.hp_mult = float(hp_mult or 1.0)             # battle HP (gym_battle.HP_MULT)
        self.p_team = list(player_team)
        self.l_team = list(leader_team)
        self.leader_label = leader_label
        self.by = {"user": {}, "opponent": {}}
        self.state = State(self._side(self.p_team, self.by["user"], self.hp_mult),
                           self._side(self.l_team, self.by["opponent"], self.hp_mult),
                           None, None, False)
        # Alola totem trial: the totem (named "Totem ...") + its reinforcements.
        self.totem = dict(totem) if totem else None
        self.totem_c = None
        self.pending = []               # lines shown with the next turn
        if self.totem:
            self.totem_c = next((c for c in self.l_team if str(c.name).startswith("Totem ")), self.l_team[0])
            if self.active("opponent") is self.totem_c:
                self.pending += self._totem_aura("%s's aura flared to life!" % self.totem_c.name)
        # Paldea Titan: alone; first faint -> Herba Mystica, full HP, power-up (gymsim.js titan*)
        self.titan = dict(titan) if titan else None
        self.titan_phase = 1
        if self.titan and self.l_team:
            self.pending += ["The Titan %s appeared!" % self.l_team[0].name]
            self.pending += self._boost_active(self.titan.get("aura") or {}, "%s towers over you!" % self.l_team[0].name)

    # --- construction ------------------------------------------------
    @staticmethod
    def _side(team, by_id, hp_mult=1.0):
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
            pk.hp, pk.maxhp = int(round(int(c.hp) * hp_mult)), int(round(int(c.max_hp) * hp_mult))
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
                # Two of one species (Jasmine's Magnemite, Lance's Dragonite): the
                # engine keys Pokemon by species, so the copy gets its own key,
                # with the species' dex entry under it. (This used to refuse the
                # team, and the fight never started.)
                base, n = pk.id, 2
                while "%scopy%d" % (base, n) in by_id:
                    n += 1
                pk.id = "%scopy%d" % (base, n)
                if pk.id not in _engine_dex and base in _engine_dex:
                    _engine_dex[pk.id] = _engine_dex[base]
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
                c.hp = 0 if int(mon.hp) <= 0 else max(1, int(round(int(mon.hp) / self.hp_mult)))
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
        lines, self.pending = list(self.pending), []
        ally = self.totem_withdrawal()
        if ally:                        # the worn-down totem calls for help
            lm = "%s %s" % (constants.SWITCH_STRING, ally)
            lines.append("%s called for help!" % self.totem_c.name)
        with gym_moves():
            mut = StateMutator(self.state)
            outs = get_all_state_instructions(mut, pm, lm)
            o = random.choices(outs, weights=[x.percentage for x in outs])[0]
            boss = self._boss_mon() if self.guard else None
            before = boss.hp if boss is not None else None
            mut.apply(o.instructions)
            if boss is not None and before is not None and boss.hp < before:
                lost = before - boss.hp                  # the guard: a quarter of it back
                boss.hp = min(boss.maxhp, boss.hp + (lost - int(round(lost * self.guard))))
            held = self._totem_hold() or self._titan_hold()
            said = self._describe(o.instructions, names)
            if held:                    # it didn't faint after all: it held on
                gone = "%s fainted" % (self.totem_c or self.l_team[0]).name   # totem or Titan
                said = [x for x in said if gone not in x] + [held]
            if ally:
                called = self.by["opponent"][ally].name
                said = [("%s answered the call!" % called) if x == "%s switched in!" % called else x
                        for x in said]
            lines += said
            self._sync()
            lines += self._totem_down()
            lines += self._replace("opponent")
            lines += self._replace("user")
        return lines

    # --- totems (Alola) -------------------------------------------------
    def totem_withdrawal(self):
        """Engine id of the reinforcement the totem calls this turn, or None:
        the totem is out, at 30% HP or less, and help is left."""
        if not self.totem or self.active("opponent") is not self.totem_c:
            return None
        t = self.totem_c
        if t.hp <= 0 or t.hp > t.max_hp * TOTEM_WITHDRAW:
            return None
        nxt = self._totem_allies()
        if not nxt:
            return None
        return next(k for k, v in self.by["opponent"].items() if v is nxt[0])

    def _totem_hold(self):
        """Anti one-shot: while it still has help to call, the totem can't
        drop below 30% HP (or faint) - it holds there and calls for help next
        turn. Returns the log line, or None. (gymsim.js totemLock.)"""
        if not self.totem or not self._totem_allies():
            return None
        s = self._side_obj("opponent")
        mon = next((m for m in [s.active] + list(s.reserve.values())
                    if self.by["opponent"].get(m.id) is self.totem_c), None)
        if mon is None:
            return None
        lock = max(1, int(mon.maxhp * TOTEM_WITHDRAW))
        if mon.hp >= lock:
            return None
        mon.hp = lock
        return "%s held on!" % self.totem_c.name

    def _boss_mon(self):
        """The engine mon of the boss (the leader's first Pokemon)."""
        boss = self.l_team[0] if self.l_team else None
        s = self._side_obj("opponent")
        return next((m for m in [s.active] + list(s.reserve.values())
                     if self.by["opponent"].get(m.id) is boss), None)

    def _totem_allies(self, gone=None):
        return [c for c in self.l_team if c is not self.totem_c and c is not gone and c.hp > 0
                and self.active("opponent") is not c]

    def _boost_active(self, boosts, msg):
        """Raise the opponent's active Pokemon's stat stages; log lines."""
        mon = self._side_obj("opponent").active
        name = self.by["opponent"].get(mon.id).name if self.by["opponent"].get(mon.id) else "foe"
        out = [msg]
        for key, attr, label in TOTEM_STATS:
            n = int((boosts or {}).get(key, 0) or 0)
            if n:
                before = getattr(mon, attr)
                setattr(mon, attr, max(-6, min(6, before + n)))
                if getattr(mon, attr) != before:
                    out.append("The foe's %s's %s rose%s!" % (name, label, " sharply" if n >= 2 else ""))
        return out

    def _titan_hold(self):
        """A Titan's first faint: it holds on, eats a Herba Mystica and comes back
        at full HP with its power-up. Returns the log line, or None."""
        if not self.titan or self.titan_phase != 1 or not self.l_team:
            return None
        s = self._side_obj("opponent")
        mon = next((m for m in [s.active] + list(s.reserve.values())
                    if self.by["opponent"].get(m.id) is self.l_team[0]), None)
        if mon is None or mon.hp > 0:
            return None
        self.titan_phase = 2
        mon.hp = mon.maxhp
        name = self.l_team[0].name
        self.pending += self._boost_active(self.titan.get("power") or {}, "") [1:]
        return "%s ate a Herba Mystica and grew even stronger! Its HP was fully restored!" % name

    def _totem_aura(self, msg):
        mon = self._side_obj("opponent").active
        out = [msg]
        for key, attr, label in TOTEM_STATS:
            n = int((self.totem or {}).get("aura", {}).get(key, 0) or 0)
            if n:
                before = getattr(mon, attr)
                setattr(mon, attr, max(-6, min(6, before + n)))
                if getattr(mon, attr) != before:
                    out.append("The foe's %s's %s rose%s!" % (self.totem_c.name, label,
                                                             " sharply" if n >= 2 else ""))
        return out

    def _totem_down(self):
        """The totem fainting ends the trial: its reinforcements leave."""
        if not self.totem or self.totem_c.hp > 0:
            return []
        rest = [c for c in self.l_team if c is not self.totem_c and c.hp > 0]
        if not rest:
            return []
        s = self._side_obj("opponent")
        for mon in [s.active] + list(s.reserve.values()):
            if self.by["opponent"].get(mon.id) in rest:
                mon.hp = 0
        for c in rest:
            c.hp = 0
        self._sync()
        return ["%s fainted - its allies fled!" % self.totem_c.name]

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
            if side == "opponent" and self.totem:
                allies = self._totem_allies(gone)
                nxt = allies[0] if allies else (self.totem_c if self.totem_c.hp > 0 and self.totem_c is not gone else None)
                if allies:
                    lines.append("%s called for help!" % self.totem_c.name)
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
            if side == "opponent" and self.totem:
                if nxt is self.totem_c:
                    half = int(nxt.max_hp * TOTEM_RETURN)
                    if s.active.hp < half:
                        s.active.hp = half
                        self._sync()
                    lines.append("%s is back in the fight!" % nxt.name)
                    lines += self._totem_aura("%s's aura is still flaring!" % nxt.name)
                else:
                    lines.append("%s answered the call!" % nxt.name)
                if hz:
                    lines.append("%s was hurt by the hazards on its side!" % nxt.name)
                continue
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
                n = int(ins[3])         # signed: Tail Whip is a boost of -1
                if n:
                    out.append("%s's %s %s!" % (label, _STAT_TEXT.get(ins[2], ins[2]),
                                                _amount(n) if n > 0 else _drop(-n)))
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
