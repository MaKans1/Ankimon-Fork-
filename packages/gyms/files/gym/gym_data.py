"""
gym_data.py — the boss ladder.

Fixed levels: you can be under-levelled and lose, or over-level and walk it.
That is deliberate - it is what gives training a purpose. The game never looks
at your level; the GAP between your Pokemon and the boss sets the difficulty.

RED/BLUE (from the pokered disassembly, Desktop/.claude/Ankimon/showdown_proto/rb)
    Every leader uses their real Red/Blue Pokemon at their real levels - the ace
    plus the next two highest (Brock and Misty only ever had two). Recommended
    level = the ace's level, so a fight at the recommended level is level for
    level, like the originals. Blue's team is the Charizard version.
    moves    = Modernized: the 2 best attacks + 2 best support moves each
               Pokemon learns by that level (the default; with Pokemon
               Showdown's rules a type-matched team at level wins ~89%,
               a neutral one ~66% - close to the 85/65 targets)
    rb_moves = Original: the exact Red/Blue sets incl. the leaders' signature
               moves (Onix's Bide, Lapras's Blizzard...) - near-trivial (~99%)

OLD BALANCE NOTES (classic-engine tuning, superseded)
    Each boss's whole team sits at one level - its RECOMMENDED level - tuned
    so a type-matched team at that level, played well, wins ~85% against the
    planning leader AI. Roughly -20% per 5 levels under, easier when over.
    Neutral-type teams at level win ~55-65%. Levels never drop along the ladder.
    Movesets: each boss Pokemon's 2 best attacks + 2 best support moves from its
    level-up learnset (support ranked by how often a planning player chose it).

Adding a boss is a pure data edit: append a Gym(...) below. Everything else
(badge case, progress gates, HUD counter) iterates GYMS.

KINDS
    "gym"       — the eight badge gyms, one interval apart
    "elite4"    — the Elite Four
    "champion"  — the final fight

ELITE FOUR MODES  (setting: gym.elite_four_classic)
    Classic ON  — beat all five back to back in one sitting. Your team heals
                  between members but you cannot swap it, and losing any one
                  ends the whole run.
    Classic OFF — they behave like ordinary gyms: an interval between each,
                  and you re-pick your three every time.
"""

from dataclasses import dataclass, field
from typing import List, Optional

GYM, ELITE4, CHAMPION = "gym", "elite4", "champion"


@dataclass
class GymMon:
    """One Pokémon on a boss's team.

    species : must match a name in the addon's pokedex CSVs.
    level   : fixed. Not scaled to the player.
    moves   : None -> pulled from the species learnset at that level.
              Otherwise an explicit list, which is how you hand-tune a fight.
    """
    species: str
    level: int
    moves: Optional[List[str]] = None       # Modernized set (default)
    rb_moves: Optional[List[str]] = None    # Original Red/Blue set (setting: Gym Moveset: Original)


@dataclass
class Gym:
    gym_id: int
    name: str
    leader: str
    type_theme: str
    badge_name: str
    blurb: str
    team: List[GymMon]
    cash_reward: int = 500
    kind: str = GYM
    # Level your team should be at: a type-matched team at this level, played
    # well, wins ~85% (tuned on Pokemon Showdown's rules). 0 = boss team level.
    recommended_level: int = 0
    # Legacy fallback only; the live threshold comes from
    # GymProgress.unlock_point(), which measures from the previous win.
    unlock_at_reviews: int = 100
    region: str = "Kanto"

    @property
    def is_elite(self) -> bool:
        return self.kind in (ELITE4, CHAMPION)


# --- The ladder ------------------------------------------------------------

GYMS: List[Gym] = [
    Gym(1, "Stonewall Gym", "Brock", "Rock", "Boulder Badge",
        "Rock-hard defence. Bring something that hits special, or grass and "
        "water types.",
        [GymMon("Geodude", 12, ["Bulldoze", "Rollout", "Defense Curl", "Rock Polish"],
                rb_moves=["Tackle", "Defense Curl"]),
         GymMon("Onix", 14, ["Smack Down", "Rock Throw", "Rock Polish", "Harden"],
                rb_moves=["Tackle", "Screech", "Bide"])],
        cash_reward=500, unlock_at_reviews=100),

    Gym(2, "Cerulean Gym", "Misty", "Water", "Cascade Badge",
        "Fast, bulky water types. Electric and grass moves will carry you; "
        "neutral physical attackers will stall out.",
        [GymMon("Staryu", 18, ["Water Gun", "Rapid Spin", "Minimize", "Harden"],
                rb_moves=["Tackle", "Water Gun"]),
         GymMon("Starmie", 21, ["Psychic", "Surf", "Recover", "Cosmic Power"],
                rb_moves=["Tackle", "Water Gun", "Bubble Beam"])],
        cash_reward=800, unlock_at_reviews=200),

    Gym(3, "Vermilion Gym", "Lt. Surge", "Electric", "Thunder Badge",
        "High speed and paralysis. Ground types ignore electric entirely — "
        "if you have one, lead with it.",
        [GymMon("Voltorb", 21, ["Spark", "Charge Beam", "Swift", "Charge"],
                rb_moves=["Tackle", "Screech", "Sonic Boom"]),
         GymMon("Pikachu", 18, ["Thunder Shock", "Quick Attack", "Nasty Plot", "Double Team"],
                rb_moves=["Thunder Shock", "Growl", "Thunder Wave", "Quick Attack"]),
         GymMon("Raichu", 24, ["Thunderbolt", "Discharge", "Agility", "Nasty Plot"],
                rb_moves=["Thunder Shock", "Growl", "Thunderbolt"])],
        cash_reward=1200, unlock_at_reviews=300),

    Gym(4, "Celadon Gym", "Erika", "Grass", "Rainbow Badge",
        "Grass types with status moves that stall. Fire, flying and ice cut "
        "straight through; watch for sleep powder.",
        [GymMon("Victreebel", 29, ["Leaf Storm", "Power Whip", "Razor Leaf", "Sleep Powder"],
                rb_moves=["Razor Leaf", "Wrap", "Poison Powder", "Sleep Powder"]),
         GymMon("Tangela", 24, ["Vine Whip", "Ancient Power", "Mega Drain", "Growth"],
                rb_moves=["Constrict", "Bind"]),
         GymMon("Vileplume", 29, ["Petal Dance", "Petal Blizzard", "Moonlight", "Growth"],
                rb_moves=["Petal Dance", "Poison Powder", "Mega Drain", "Sleep Powder"])],
        cash_reward=1600, unlock_at_reviews=400),

    Gym(5, "Fuchsia Gym", "Koga", "Poison", "Soul Badge",
        "Poison and residual damage. Bring something that resists toxic, or "
        "end fights fast with psychic and ground moves.",
        [GymMon("Muk", 39, ["Sludge Wave", "Sludge Bomb", "Minimize", "Harden"],
                rb_moves=["Disable", "Poison Gas", "Minimize", "Sludge"]),
         GymMon("Koffing", 37, ["Self-Destruct", "Sludge Bomb", "Sludge", "Poison Gas"],
                rb_moves=["Tackle", "Smog", "Sludge", "Smokescreen"]),
         GymMon("Weezing", 43, ["Self-Destruct", "Sludge Bomb", "Sludge", "Poison Gas"],
                rb_moves=["Smog", "Sludge", "Toxic", "Self-Destruct"])],
        cash_reward=2000, unlock_at_reviews=500),

    Gym(6, "Saffron Gym", "Sabrina", "Psychic", "Marsh Badge",
        "Very high special attack and speed. Dark and bug moves are your best "
        "answer; a slow physical attacker will be outrun.",
        [GymMon("Kadabra", 38, ["Psychic", "Psyshock", "Recover", "Reflect"],
                rb_moves=["Disable", "Psybeam", "Recover", "Psychic"]),
         GymMon("Venomoth", 38, ["Bug Buzz", "Leech Life", "Quiver Dance", "Sleep Powder"],
                rb_moves=["Poison Powder", "Leech Life", "Stun Spore", "Psybeam"]),
         GymMon("Alakazam", 43, ["Psychic", "Psyshock", "Recover", "Reflect"],
                rb_moves=["Psybeam", "Recover", "Psywave", "Reflect"])],
        cash_reward=2500, unlock_at_reviews=600),

    Gym(7, "Cinnabar Gym", "Blaine", "Fire", "Volcano Badge",
        "Heavy fire damage and burn chances. Water, rock and ground types "
        "hold up; anything grass or steel will melt.",
        [GymMon("Growlithe", 42, ["Flamethrower", "Fire Fang", "Agility", "Howl"],
                rb_moves=["Ember", "Leer", "Take Down", "Agility"]),
         GymMon("Rapidash", 42, ["Megahorn", "Flame Wheel", "Poison Jab", "Agility"],
                rb_moves=["Tail Whip", "Stomp", "Growl", "Fire Spin"]),
         GymMon("Arcanine", 47, ["Flare Blitz", "Flamethrower", "Agility", "Howl"],
                rb_moves=["Roar", "Ember", "Fire Blast", "Take Down"])],
        cash_reward=3000, unlock_at_reviews=700),

    Gym(8, "Viridian Gym", "Giovanni", "Ground", "Earth Badge",
        "Ground types with real bulk and the last badge on the line. Water, "
        "grass and ice moves are the fastest route through.",
        [GymMon("Rhyhorn", 45, ["Earthquake", "Drill Run", "Bulldoze", "Scary Face"],
                rb_moves=["Stomp", "Tail Whip", "Fury Attack", "Horn Drill"]),
         GymMon("Nidoking", 45, ["Earth Power", "Poison Jab", "Megahorn", "Toxic Spikes"],
                rb_moves=["Tackle", "Horn Attack", "Poison Sting", "Thrash"]),
         GymMon("Rhydon", 50, ["Earthquake", "Drill Run", "Bulldoze", "Scary Face"],
                rb_moves=["Stomp", "Tail Whip", "Fissure", "Horn Drill"])],
        cash_reward=4000, unlock_at_reviews=800),

    # --- Elite Four -------------------------------------------------------
    Gym(9, "Elite Four", "Lorelei", "Ice", "Elite Four: Lorelei",
        "Ice and water, with freeze chances. Fighting, rock and electric "
        "moves break through fastest.",
        [GymMon("Slowbro", 54, ["Future Sight", "Psychic", "Curse", "Slack Off"],
                rb_moves=["Growl", "Water Gun", "Withdraw", "Amnesia"]),
         GymMon("Jynx", 56, ["Psychic", "Ice Punch", "Lovely Kiss", "Sweet Kiss"],
                rb_moves=["Double Slap", "Ice Punch", "Body Slam", "Thrash"]),
         GymMon("Lapras", 56, ["Ice Beam", "Hydro Pump", "Brine", "Life Dew"],
                rb_moves=["Body Slam", "Confuse Ray", "Blizzard", "Hydro Pump"])],
        cash_reward=5000, kind=ELITE4, unlock_at_reviews=900),

    Gym(10, "Elite Four", "Bruno", "Fighting", "Elite Four: Bruno",
        "Pure physical pressure. Psychic and flying moves are the classic "
        "answer; do not try to out-muscle him.",
        [GymMon("Hitmonlee", 55, ["Close Combat", "High Jump Kick", "Axe Kick", "Brick Break"],
                rb_moves=["Jump Kick", "Focus Energy", "High Jump Kick", "Mega Kick"]),
         GymMon("Onix", 56, ["Double-Edge", "Stone Edge", "Curse", "Rock Polish"],
                rb_moves=["Rock Throw", "Rage", "Slam", "Harden"]),
         GymMon("Machamp", 58, ["Vital Throw", "Low Sweep", "Bulk Up", "Scary Face"],
                rb_moves=["Leer", "Focus Energy", "Fissure", "Submission"])],
        cash_reward=5500, kind=ELITE4, unlock_at_reviews=1000),

    Gym(11, "Elite Four", "Agatha", "Ghost", "Elite Four: Agatha",
        "Ghost and poison with status spam. Dark and psychic moves hit hard; "
        "normal attacks do nothing at all.",
        [GymMon("Golbat", 56, ["Venoshock", "Air Cutter", "Poison Fang", "Bite"],
                rb_moves=["Supersonic", "Confuse Ray", "Wing Attack", "Haze"]),
         GymMon("Arbok", 58, ["Belch", "Sludge Bomb", "Crunch", "Coil"],
                rb_moves=["Bite", "Glare", "Screech", "Acid"]),
         GymMon("Gengar", 60, ["Shadow Ball", "Dream Eater", "Curse", "Hypnosis"],
                rb_moves=["Confuse Ray", "Night Shade", "Toxic", "Dream Eater"])],
        cash_reward=6000, kind=ELITE4, unlock_at_reviews=1100),

    Gym(12, "Elite Four", "Lance", "Dragon", "Elite Four: Lance",
        "Dragons with huge stats across the board. Ice moves are the answer "
        "and very little else will do.",
        [GymMon("Gyarados", 58, ["Hydro Pump", "Aqua Tail", "Dragon Dance", "Scary Face"],
                rb_moves=["Dragon Rage", "Leer", "Hydro Pump", "Hyper Beam"]),
         GymMon("Aerodactyl", 60, ["Stone Edge", "Rock Slide", "Agility", "Scary Face"],
                rb_moves=["Supersonic", "Bite", "Take Down", "Hyper Beam"]),
         GymMon("Dragonite", 62, ["Outrage", "Hurricane", "Dragon Dance", "Agility"],
                rb_moves=["Agility", "Slam", "Barrier", "Hyper Beam"])],
        cash_reward=7000, kind=ELITE4, unlock_at_reviews=1200),

    Gym(13, "Champion", "Blue", "Mixed", "Champion",
        "No type theme to exploit — a balanced team at the highest levels on "
        "the ladder. Bring your best three.",
        [GymMon("Exeggutor", 61, ["Wood Hammer", "Leaf Storm", "Synthesis", "Growth"],
                rb_moves=["Barrage", "Hypnosis", "Stomp"]),
         GymMon("Gyarados", 63, ["Hydro Pump", "Aqua Tail", "Dragon Dance", "Scary Face"],
                rb_moves=["Dragon Rage", "Leer", "Hydro Pump", "Hyper Beam"]),
         GymMon("Charizard", 65, ["Flare Blitz", "Flamethrower", "Heat Wave", "Scary Face"],
                rb_moves=["Rage", "Slash", "Flamethrower", "Fire Spin"])],
        cash_reward=10000, kind=CHAMPION, unlock_at_reviews=1300),
]


def unlock_reviews(gym) -> int:
    """Legacy fallback. The live threshold is GymProgress.unlock_point(),
    which measures a full interval from the previous boss's win."""
    try:
        from .gym_config import reviews_per_gym
        return int(gym.gym_id) * int(reviews_per_gym())
    except Exception:
        return int(gym.unlock_at_reviews)


# --------------------------------------------------------------- regions --
# Kanto is the full ladder above (ids 1-13, unchanged so existing progress
# carries over). Every other region's ladder lives in regions_data.py with ids
# <generation>01, <generation>02 ... (Johto 201+, Hoenn 301+ ... Paldea 901+).
# You are always in exactly one region (Ankimon > Game > Travel); the ladder,
# badges, wild levels and level cap all follow it.
from .regions_data import REGION_GYMS  # noqa: E402

REGION_ORDER = ["Kanto", "Johto", "Hoenn", "Sinnoh", "Unova", "Kalos", "Alola", "Galar", "Paldea"]
LADDERS = {"Kanto": GYMS, **REGION_GYMS}
for _region, _gyms in LADDERS.items():
    for _g in _gyms:
        _g.region = _region
ALL_GYMS: List[Gym] = [g for r in REGION_ORDER for g in LADDERS.get(r, [])]


def current_region() -> str:
    try:
        from ..wild import wild_rules
        r = wild_rules.region()
        return r if r in LADDERS else "Kanto"
    except Exception:
        return "Kanto"


def ladder(region: Optional[str] = None) -> List[Gym]:
    return LADDERS.get(region or current_region(), GYMS)


def get_gym(gym_id: int) -> Optional[Gym]:
    for g in ALL_GYMS:
        if g.gym_id == gym_id:
            return g
    return None


def next_gym(defeated_ids, region: Optional[str] = None) -> Optional[Gym]:
    """The next boss not yet beaten in this region. Linear path: no skipping."""
    for g in ladder(region):
        if g.gym_id not in defeated_ids:
            return g
    return None


def ladder_complete(defeated_ids, region: Optional[str] = None) -> bool:
    return all(g.gym_id in defeated_ids for g in ladder(region))


def elite_run(gym) -> List[Gym]:
    """Every boss from this one to the end of the ladder, for a Classic
    Elite Four run. Empty if this boss is not part of the elite stretch."""
    if not gym.is_elite:
        return []
    return [g for g in ladder(gym.region) if g.is_elite and g.gym_id >= gym.gym_id]


def badge_count(region: Optional[str] = None) -> int:
    return sum(1 for g in ladder(region) if g.kind == GYM)


def badges_earned(defeated_ids, region: Optional[str] = None) -> int:
    return sum(1 for g in ladder(region) if g.kind == GYM and g.gym_id in defeated_ids)


def champion_beaten(defeated_ids, region: Optional[str] = None) -> bool:
    champs = [g for g in ladder(region) if g.kind == CHAMPION]
    return bool(champs) and all(g.gym_id in defeated_ids for g in champs)


# ----------------------------------------------------------- level caps --
CAP_MARGIN = 5          # you may be this many levels above the next ace
CAP_AFTER_INTRO = 10    # region whose ladder isn't finished yet: last ace + this


def ace_level(gym) -> int:
    return max(m.level for m in gym.team)


def level_cap(defeated_ids, region: Optional[str] = None) -> Optional[int]:
    """Highest level your Pokémon fight at in this region: the next leader's
    strongest Pokémon + CAP_MARGIN. None once the region's Champion is beaten.
    A region whose later gyms aren't built yet: last ace + CAP_AFTER_INTRO."""
    lad = ladder(region)
    if champion_beaten(defeated_ids, region):
        return None
    nxt = next_gym(defeated_ids, region)
    if nxt is not None:
        return ace_level(nxt) + CAP_MARGIN
    return max(ace_level(g) for g in lad) + CAP_AFTER_INTRO if lad else None
