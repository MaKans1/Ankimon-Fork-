"""
gym_showdown.py - run a gym fight on Pokemon Showdown's simulator.

A small Node.js helper (user_files/showdown: portable node + @pkmn/sim +
bridge.js) plays the battle with the real game's rules; this module drives it
over a private stdin/stdout pipe (no window, no network, no ports). It starts
when a gym opens and exits when the gym closes.

It mirrors the parts of gym_engine.EngineBattle that GymSession uses
(active(side)), so the gym window works unchanged. Showdown owns HP, status,
PP and faint replacement; after every turn the results are copied onto the
gym Combatants the window draws.

If the helper is missing, fails to start, or errors, the caller falls back to
the classic engine - a gym never fails to open because of it.

No aqt / Anki imports, so it can be tested outside Anki.
"""
import json
import os
import queue
import re
import subprocess
import threading
from pathlib import Path

RUNTIME = Path(__file__).resolve().parent.parent / "user_files" / "showdown"
# Portable Node: node\\node.exe on Windows, node/bin/node on macOS / Linux
NODE = RUNTIME / "node" / ("node.exe" if os.name == "nt" else os.path.join("bin", "node"))
BRIDGE = RUNTIME / "bridge.js"
SIM = RUNTIME / "node_modules" / "@pkmn" / "sim"
CREATE_NO_WINDOW = 0x08000000


class ShowdownError(Exception):
    pass


def available() -> bool:
    return NODE.exists() and BRIDGE.exists() and SIM.exists()


def to_id(s) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def _set_from(c):
    """Showdown team set from a gym Combatant (its PokemonObject source)."""
    src = c.source
    iv = dict(getattr(src, "iv", None) or {})
    ev = dict(getattr(src, "ev", None) or {})
    return {
        "name": str(c.name)[:18],
        "species": _species_key(getattr(src, "name", c.name)),
        "level": int(c.level),
        "ability": str(getattr(src, "ability", "") or ""),
        "item": to_id(getattr(src, "held_item", "") or ""),
        "nature": str(getattr(src, "nature", "") or "serious").capitalize(),
        "gender": getattr(src, "gender", "") or "",
        "shiny": bool(getattr(src, "shiny", False)),
        "ivs": {k: int(iv.get(k, 15)) for k in ("hp", "atk", "def", "spa", "spd", "spe")},
        "evs": {k: int(ev.get(k, 0)) for k in ("hp", "atk", "def", "spa", "spd", "spe")},
        "moves": [to_id(m) for m in (c.attacks or [])],
        "gigantamax": bool(getattr(c, "gigantamax", False)),
        **_tera_fields(c),
        **_carry(c),
    }


def _tera_fields(c):
    """Who may Terastallize, and into what: a leader's ace (tera_type, rolled per
    fight) or a Pokemon holding a Tera Shard ("water-tera-shard" -> Water)."""
    t = getattr(c, "tera_type", None)
    if not t:
        held = str(getattr(c.source, "held_item", "") or "").lower()
        if held.endswith("-tera-shard"):
            t = held[:-len("-tera-shard")].capitalize()
    return {"teraType": t or None, "canTera": bool(t)}


def _carry(c):
    """Expeditions: start the fight with the HP, status and PP this Pokémon
    finished the last floor with. Gym Combatants have no .carry, so gyms
    always start fresh."""
    if not getattr(c, "carry", False):
        return {}
    out = {"pp": {to_id(m): int(c.pp[m]) for m in (c.attacks or []) if m in c.pp}}
    if 0 < int(c.hp) < int(c.max_hp):
        out["curhp"] = int(c.hp)
    if getattr(c, "status", None):
        out["status"] = c.status
    return out


_STATUS_TAG = {"slp": "SLP", "brn": "BRN", "par": "PAR", "psn": "PSN", "tox": "TOX", "frz": "FRZ"}
_VOL_TAG = {"partiallytrapped": "TRAPPED", "confusion": "CONFUSED", "leechseed": "SEEDED",
            "substitute": "SUB", "lockedmove": "LOCKED IN", "taunt": "TAUNTED", "encore": "ENCORE",
            "yawn": "DROWSY", "focusenergy": "PUMPED", "mustrecharge": "RECHARGING",
            "attract": "INFATUATED", "curse": "CURSED", "nightmare": "NIGHTMARE",
            "perishsong": "PERISH", "aquaring": "AQUA RING", "ingrain": "ROOTED"}
_BOOST_TAG = (("atk", "Atk"), ("def", "Def"), ("spa", "SpA"), ("spd", "SpD"), ("spe", "Spe"),
              ("accuracy", "Acc"), ("evasion", "Eva"))


def _tags_for(v):
    """Short tags for the gym window: status, then (active only) effects and
    stat stages, e.g. ['SLP'], ['TRAPPED', 'Atk+1']."""
    tags = []
    if v.get("status") in _STATUS_TAG and not v.get("fainted"):
        tags.append(_STATUS_TAG[v["status"]])
    for vol in v.get("vol") or []:
        if vol in _VOL_TAG and _VOL_TAG[vol] not in tags:
            tags.append(_VOL_TAG[vol])
    b = v.get("boosts") or {}
    for k, label in _BOOST_TAG:
        n = int(b.get(k) or 0)
        if n:
            tags.append("%s%+d" % (label, n))
    return tags


class ShowdownBattle:
    """One gym fight in the Showdown helper. Construct (spawns the helper),
    then start(); each play_turn() resolves one turn and returns log lines."""

    def __init__(self, timeout=20.0):
        if not available():
            raise ShowdownError("Showdown runtime not installed at %s" % RUNTIME)
        self.timeout = timeout
        self.p_team, self.l_team = [], []
        self.moves, self.locked, self.ended, self.winner = [], False, False, None
        self.zmoves, self.zused, self.zinfo, self.dmax, self.tera = {}, False, {}, {}, {}
        self.fled = []
        self._q = queue.Queue()
        self.proc = subprocess.Popen(
            [str(NODE), str(BRIDGE)], cwd=str(RUNTIME), stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
            bufsize=1, creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0)
        t = threading.Thread(target=self._reader, daemon=True)
        t.start()

    # --- pipe --------------------------------------------------------------
    def _reader(self):
        try:
            for line in self.proc.stdout:
                self._q.put(line)
        except Exception:
            pass
        self._q.put(None)                      # helper gone

    def _ask(self, obj, timeout=None):
        if self.proc.poll() is not None:
            raise ShowdownError("helper exited (code %s)" % self.proc.returncode)
        try:
            self.proc.stdin.write(json.dumps(obj) + "\n")
            self.proc.stdin.flush()
        except Exception as e:
            raise ShowdownError("could not talk to helper: %s" % e)
        try:
            line = self._q.get(timeout=timeout or self.timeout)
        except queue.Empty:
            raise ShowdownError("helper timed out on %s" % obj.get("cmd"))
        if line is None:
            raise ShowdownError("helper closed")
        r = json.loads(line)
        if not r.get("ok"):
            raise ShowdownError(r.get("error", "unknown error")[:300])
        return r

    def ping(self, timeout=15.0):
        return self._ask({"cmd": "ping"}, timeout=timeout)

    def close(self):
        try:
            if self.proc.poll() is None:
                try:
                    self.proc.stdin.write('{"cmd":"quit"}\n')
                    self.proc.stdin.flush()
                    self.proc.wait(timeout=2)
                except Exception:
                    self.proc.kill()
        except Exception:
            pass

    # --- battle ------------------------------------------------------------
    def start(self, player_team, leader_team, leader_label="The leader", wild=False, totem=None, dynamax=None,
              tera=None, titan=None, guard=None, hp_mult=1.0):
        """totem: {"aura": {...}} for an Alola totem trial (gymsim.js totem rules).
        dynamax: {"p1": bool, "p2": bool} - who may Dynamax (Galar; dmax.config_for).
        tera: {"p1": bool, "p2": bool} - who may Terastallize (Paldea; tera.config_for)."""
        self.p_team, self.l_team = list(player_team), list(leader_team)
        self.hp_mult = float(hp_mult or 1.0)       # battle HP; Combatants keep real HP
        r = self._ask({"cmd": "start", "hpmult": self.hp_mult, "p1": [_set_from(c) for c in self.p_team],
                       "p2": [_set_from(c) for c in self.l_team], "leader": leader_label,
                       "wild": bool(wild), "totem": totem or None, "dynamax": dynamax or None,
                       "tera": tera or None, "titan": titan or None,
                       "guard": {"mult": float(guard)} if guard else None})
        self._apply(r)
        return r.get("log") or []

    def play_turn(self, move=None, smart=True, z=None, dmax=None, tera=None):
        """move: the display name the player clicked, or None for auto.
        z: True = that move as its Z-Move; "auto" = auto-battle may spend it."""
        r = self._ask({"cmd": "turn", "move": to_id(move) if move else None, "smart": bool(smart),
                       "z": z, "dmax": dmax, "tera": tera})
        self._apply(r)
        lines = list(r.get("log") or [])
        if self.fled:
            lines.append("%s fainted - its allies fled!" % self.l_team[0].name)
        return lines

    def _apply(self, r):
        for team, key in ((self.p_team, "p1"), (self.l_team, "p2")):
            for v in r.get(key) or []:
                i = v.get("i")
                if i is None or not (0 <= i < len(team)):
                    continue
                c = team[i]
                m = getattr(self, "hp_mult", 1.0) or 1.0       # battle HP back to real HP
                c.max_hp = int(round(int(v["maxhp"]) / m)) or c.max_hp
                hp = 0 if v.get("fainted") else max(0, int(v["hp"]))
                c.hp = 0 if hp <= 0 else max(1, int(round(hp / m)))
                c._sd_active = bool(v.get("active"))
                c.status = None if c.hp <= 0 else (v.get("status") or None)
                c._tags = _tags_for(v)
                try:
                    c.source.hp = c.source.current_hp = c.hp
                    c.source.max_hp = c.max_hp
                    c.source.battle_status = v.get("status") or ("fainted" if c.hp <= 0 else "fighting")
                except Exception:
                    pass
        # PP for the player's active Pokemon, keyed back to its display names
        self.moves, self.locked = r.get("moves") or [], bool(r.get("locked"))
        # Z-Moves your active Pokemon could use now: {move id: Z-Move name}
        self.zmoves = {z["id"]: z["name"] for z in (r.get("z") or [])}
        # what each Z-Move really is (type, category, power or status bonus)
        self.zinfo = {z["id"]: z for z in (r.get("z") or [])}
        # Dynamax: {allowed, can, active, turns, gmax, used, foe, moves: [Max Move info]}
        self.dmax = r.get("dmax") or {}
        # Tera: {allowed, can (your Tera type), active (type), used, foe (type)}
        self.tera = r.get("tera") or {}
        self.zused = bool(r.get("zused"))
        a = self.active("user")
        if a is not None and self.moves and [to_id(n) for n in a.attacks] != [m["id"] for m in self.moves]:
            # a move slot changed mid-battle (Tera Blast): follow it, keep the PP
            a.attacks = [m.get("name") or m["id"] for m in self.moves]
        if a is not None and self.moves:
            by_id = {m["id"]: m for m in self.moves}
            for name in a.attacks:
                m = by_id.get(to_id(name))
                if m:
                    a.pp[name] = int(m["pp"])
                    a.max_pp[name] = int(m["maxpp"])
        self.ended, self.winner = bool(r.get("ended")), r.get("winner")
        # A totem trial ends when the totem faints (gymsim.js totemCheck), even
        # if it never got to call for help: its reinforcements leave, so the
        # session sees the leader out of Pokemon and counts the win - the
        # classic engine does the same (gym_engine._totem_down).
        self.fled = []
        if self.ended and self.winner == "p1":
            for c in self.l_team:
                if c.hp > 0:
                    c.hp = 0
                    self.fled.append(c)
                    try:
                        c.source.hp = c.source.current_hp = 0
                        c.source.battle_status = "fainted"
                    except Exception:
                        pass

    def active(self, side):
        team = self.p_team if side == "user" else self.l_team
        for c in team:
            if getattr(c, "_sd_active", False) and c.hp > 0:
                return c
        return None


def _species_key(name):
    """Showdown species id for a stored name ("Flabébé" -> "flabebe",
    "Nidoran\u2640" -> "nidoranf"); Showdown's own id drops accented letters."""
    import unicodedata
    s = str(name or "").replace("\u2640", "f").replace("\u2642", "m")
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", s.lower())
