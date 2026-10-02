"""
gym_state.py — gym battle state machine and progress persistence.

Deliberately free of any `aqt` / Anki import so the fight logic can be unit
tested standalone. Anything needing Anki lives in gym_battle.py / gym_ui.py.

THE RULE THAT DRIVES THE DESIGN
    Inside a gym, a fainted Pokemon does NOT heal. The next one comes in at
    whatever HP it already has. You win only by knocking out all three of the
    leader's Pokemon before all three of yours go down.

    Standard Ankimon does the opposite: encounter_functions.handle_main_pokemon_faint
    sets hp = max_hp immediately. GymSession never calls that path.

HOW "HEAL ON EXIT" WORKS
    A session battles on Combatants built from *copies* of the player's saved
    Pokemon. Damage lives on the copy. Leaving the gym discards the copies, so
    the saved team is untouched — the heal is free and cannot half-apply.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

TEAM_SIZE = 3

# How many further reviews a loss costs before the gym can be rechallenged.
RETRY_COST_REVIEWS = 100


STRUGGLE = "struggle"


@dataclass
class Combatant:
    """One Pokémon in a gym fight. HP is authoritative and persists until the
    session ends."""
    name: str
    level: int
    max_hp: int
    hp: int
    attacks: List[str] = field(default_factory=list)
    species_id: Optional[int] = None
    individual_id: Optional[str] = None
    is_player: bool = False
    # The underlying PokemonObject / dict, kept so the UI can draw sprites and
    # so a win can write XP back to the real saved Pokemon.
    source: Any = None
    # PP is gym-only and lives here, on the throwaway combatant. Nothing is
    # persisted, so leaving a gym restores full PP for free — exactly like HP.
    pp: Dict[str, int] = field(default_factory=dict)
    max_pp: Dict[str, int] = field(default_factory=dict)

    @property
    def fainted(self) -> bool:
        return self.hp <= 0

    # --- PP ------------------------------------------------------------
    def pp_left(self, move: str) -> int:
        return int(self.pp.get(move, 0))

    def usable_moves(self) -> List[str]:
        """Moves with PP remaining. Empty means this Pokémon must Struggle."""
        return [m for m in self.attacks if self.pp_left(m) > 0]

    def must_struggle(self) -> bool:
        return bool(self.attacks) and not self.usable_moves()

    def spend_pp(self, move: str) -> bool:
        """Consume one PP. Struggle is free and always available."""
        if move == STRUGGLE:
            return True
        if self.pp.get(move, 0) <= 0:
            return False
        self.pp[move] -= 1
        return True

    def clamp(self):
        if self.hp < 0:
            self.hp = 0
        if self.hp > self.max_hp:
            self.hp = self.max_hp

    def hp_pct(self) -> float:
        return 0.0 if self.max_hp <= 0 else max(0.0, self.hp / self.max_hp)


class GymSession:
    """One attempt at one gym. Create, drive with apply_damage(), read status."""

    ACTIVE, WON, LOST = "active", "won", "lost"

    def __init__(self, gym, player_team: List[Combatant],
                 leader_team: List[Combatant]):
        if not player_team:
            raise ValueError("player team is empty")
        if not leader_team:
            raise ValueError("leader team is empty")
        self.gym = gym
        self.player_team = player_team
        self.leader_team = leader_team
        self.p_idx = 0
        self.l_idx = 0
        self.status = self.ACTIVE
        self.events: List[str] = []
        # One poke-engine State for the whole fight (gym_engine.EngineBattle),
        # built on the first turn. Kept as Any so this module stays Anki-free.
        self.engine = None
        self.turns = 0

    # --- current combatants -------------------------------------------
    @property
    def player_active(self) -> Optional[Combatant]:
        # Once the engine runs the fight it decides who is out: U-turn or
        # Baton Pass can bring in someone other than the next in line.
        if self.engine is not None:
            return self.engine.active("user")
        return self._first_alive(self.player_team, self.p_idx)

    @property
    def leader_active(self) -> Optional[Combatant]:
        if self.engine is not None:
            return self.engine.active("opponent")
        return self._first_alive(self.leader_team, self.l_idx)

    @staticmethod
    def _first_alive(team, idx) -> Optional[Combatant]:
        for i in range(idx, len(team)):
            if not team[i].fainted:
                return team[i]
        return None

    # --- counts for the HUD -------------------------------------------
    def player_remaining(self) -> int:
        return sum(1 for c in self.player_team if not c.fainted)

    def leader_remaining(self) -> int:
        return sum(1 for c in self.leader_team if not c.fainted)

    # --- the state machine --------------------------------------------
    def apply_damage(self, to_player: int = 0, to_leader: int = 0):
        """Apply one turn's damage, then resolve faints and switch-ins.

        Returns a list of event strings for the battle log.
        """
        if self.status != self.ACTIVE:
            return []

        self.turns += 1
        turn_events: List[str] = []

        p, l = self.player_active, self.leader_active
        if p is not None and to_player:
            p.hp -= int(to_player)
            p.clamp()
        if l is not None and to_leader:
            l.hp -= int(to_leader)
            l.clamp()

        # Resolve leader faint first, then player, then terminal conditions.
        if l is not None and l.fainted:
            turn_events.append("%s fainted!" % l.name)
            self.l_idx = self.leader_team.index(l) + 1
            nxt = self.leader_active
            if nxt is not None:
                turn_events.append("%s sent out %s!" % (self.gym.leader, nxt.name))

        if p is not None and p.fainted:
            turn_events.append("Your %s fainted!" % p.name)
            self.p_idx = self.player_team.index(p) + 1
            nxt = self.player_active
            if nxt is not None:
                # NOTE: no heal. It comes in at its existing HP.
                turn_events.append(
                    "Go, %s! (%d/%d HP)" % (nxt.name, nxt.hp, nxt.max_hp))

        if self.leader_remaining() == 0:
            self.status = self.WON
            turn_events.append("%s is out of Pokémon. You win!" % self.gym.leader)
        elif self.player_remaining() == 0:
            self.status = self.LOST
            turn_events.append("You are out of Pokémon. You lose.")

        self.events.extend(turn_events)
        return turn_events

    def record_turn(self, lines: List[str]) -> List[str]:
        """Engine path: HP, faints and switch-ins were already resolved by
        gym_engine. Count the turn and settle win/loss."""
        if self.status != self.ACTIVE:
            return []
        self.turns += 1
        out = list(lines)
        if self.leader_remaining() == 0:
            self.status = self.WON
            out.append("%s is out of Pokémon. You win!" % self.gym.leader)
        elif self.player_remaining() == 0:
            self.status = self.LOST
            out.append("You are out of Pokémon. You lose.")
        self.events.extend(out)
        return out

    @property
    def finished(self) -> bool:
        return self.status != self.ACTIVE

    def summary(self) -> str:
        return "%s vs %s — %s (you %d/%d left, leader %d/%d left, %d turns)" % (
            self.gym.name, self.gym.leader, self.status,
            self.player_remaining(), len(self.player_team),
            self.leader_remaining(), len(self.leader_team), self.turns)


class GymProgress:
    """Persistence: which gyms are beaten, and the retry gate after a loss.

    Uses its own table so the addon's existing migration machinery is left
    alone. `db` needs only .execute(query, params) returning a cursor —
    satisfied by Ankimon's DatabaseManager and by a plain sqlite3 connection.
    """

    DDL = """
    CREATE TABLE IF NOT EXISTS gym_progress (
        gym_id            INTEGER PRIMARY KEY,
        defeated          INTEGER NOT NULL DEFAULT 0,
        attempts          INTEGER NOT NULL DEFAULT 0,
        last_attempt_rev  INTEGER NOT NULL DEFAULT 0,
        defeated_at       TEXT
    )"""

    META_DDL = """
    CREATE TABLE IF NOT EXISTS gym_meta (
        key   TEXT PRIMARY KEY,
        value TEXT
    )"""

    def __init__(self, db):
        self.db = db
        self.db.execute(self.DDL)
        self.db.execute(self.META_DDL)
        self._commit()

    # --- meta -----------------------------------------------------------
    def get_meta(self, key, default=None):
        try:
            r = self.db.execute(
                "SELECT value FROM gym_meta WHERE key=?", (key,)).fetchone()
            return r[0] if r else default
        except Exception:
            return default

    def set_meta(self, key, value):
        self.db.execute(
            "INSERT INTO gym_meta (key, value) VALUES (?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value)))
        self._commit()

    def baseline(self, current_lifetime: int) -> int:
        """Lifetime review count when the ladder started.

        Gating counts reviews SINCE the ladder began, not since you first
        installed Anki. Without this an established collection (thousands of
        reviews already logged) would unlock every gym the moment the feature
        switched from a daily counter to a lifetime one.
        """
        v = self.get_meta("baseline_reviews")
        if v is None:
            self.set_meta("baseline_reviews", current_lifetime)
            return current_lifetime
        try:
            return int(v)
        except (TypeError, ValueError):
            return 0

    def _commit(self):
        for attr in ("commit", "_commit"):
            fn = getattr(self.db, attr, None)
            if callable(fn):
                try:
                    fn()
                    return
                except Exception:
                    pass
        conn = getattr(self.db, "conn", None)
        if conn is not None:
            try:
                conn.commit()
            except Exception:
                pass

    def _row(self, gym_id):
        cur = self.db.execute(
            "SELECT gym_id, defeated, attempts, last_attempt_rev "
            "FROM gym_progress WHERE gym_id=?", (gym_id,))
        return cur.fetchone()

    def defeated_ids(self):
        cur = self.db.execute(
            "SELECT gym_id FROM gym_progress WHERE defeated=1")
        return {r[0] for r in cur.fetchall()}

    def attempts(self, gym_id) -> int:
        r = self._row(gym_id)
        return r[2] if r else 0

    def record_attempt(self, gym_id, review_count: int):
        r = self._row(gym_id)
        if r is None:
            self.db.execute(
                "INSERT INTO gym_progress (gym_id, defeated, attempts, "
                "last_attempt_rev) VALUES (?,0,1,?)", (gym_id, review_count))
        else:
            self.db.execute(
                "UPDATE gym_progress SET attempts=attempts+1, "
                "last_attempt_rev=? WHERE gym_id=?", (review_count, gym_id))
        self._commit()

    def record_win(self, gym_id, review_count: int, when: str = ""):
        self.record_attempt(gym_id, review_count)
        self.db.execute(
            "UPDATE gym_progress SET defeated=1, defeated_at=? WHERE gym_id=?",
            (when, gym_id))
        self._commit()

    def unlock_point(self, gym, cadence: int) -> int:
        """Review count at which this gym becomes available.

        Measured from when the PREVIOUS gym was beaten, not as an absolute
        multiple of the cadence. Absolute thresholds meant that once your
        review count was already past gym N+1's mark, beating gym N offered
        N+1 instantly with no interval — which is exactly what happened when
        Misty challenged the moment Brock went down.

        A defeated gym's last_attempt_rev is the review count at its win,
        because record_win() routes through record_attempt() first.
        """
        cadence = max(1, int(cadence))
        prev_id = int(gym.gym_id) - 1
        if prev_id >= 1:
            r = self._row(prev_id)
            if r and r[1]:                 # previous gym defeated
                return int(r[3]) + cadence
        return cadence                     # first gym: cadence from baseline

    def can_challenge(self, gym, review_count: int,
                      unlock_at=None, retry_cost=None):
        """(bool, reason). Enforces unlock threshold and post-loss retry gate.

        unlock_at / retry_cost default to the live Settings values; the tests
        pass them explicitly so the state machine stays Anki-free.
        """
        if unlock_at is None:
            try:
                from .gym_config import reviews_per_gym
                unlock_at = self.unlock_point(gym, reviews_per_gym())
            except Exception:
                unlock_at = gym.unlock_at_reviews
        if retry_cost is None:
            try:
                from .gym_config import retry_cost as _rc
                retry_cost = _rc()
            except Exception:
                retry_cost = RETRY_COST_REVIEWS

        if gym.gym_id in self.defeated_ids():
            return False, "%s is already beaten." % gym.name
        r = self._row(gym.gym_id)
        # A gym you've already fought was unlocked then; only the retry gate
        # applies now (the HUD shows the same).
        if not (r is not None and r[2] > 0) and review_count < unlock_at:
            return False, "Review %d more cards to unlock %s." % (
                unlock_at - review_count, gym.name)
        if r is not None and r[2] > 0:
            ready_at = r[3] + retry_cost
            if review_count < ready_at:
                return False, ("You lost your last attempt. Review %d more "
                               "cards to rechallenge." % (ready_at - review_count))
        return True, ""
